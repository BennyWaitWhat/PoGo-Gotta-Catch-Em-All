"""Apply all tag fixes: add missing, remove surplus, recompute JUMBO + Evolve Me."""
import frida, json, time, subprocess, sqlite3, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Compute all add/remove diffs for each tag
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

def tagged(name):
    return set(r[0] for r in c.execute(
        f"SELECT uid_hex FROM pokemon WHERE in_bag=1 AND auth_tag_names LIKE '%' || ? || '%'", (name,)).fetchall())
def by_rule(where):
    return set(r[0] for r in c.execute(f"SELECT uid_hex FROM pokemon WHERE in_bag=1 AND ({where})").fetchall())

# JUMBO: top 3 by weight per (species_form_costume) for XXL
jumbo_expected = set()
xxl_groups = {}
for r in c.execute("SELECT uid_hex, pokemon_id, form, fresh_costume, weight_kg FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5"):
    key = (r[1], r[2] or 0, r[3] or 0)
    xxl_groups.setdefault(key, []).append((r[4] or 0, r[0]))
for key, lst in xxl_groups.items():
    lst.sort(reverse=True)
    for _, uh in lst[:3]: jumbo_expected.add(uh)

# Vivillon Ocean is now hundo'd — should drop from Evolve Me
# Evolve Me drift: any tagged that has Vivillon evolved should be removed
em_tagged = tagged('Evolve Me')
em_now_useless = set()
for uh in em_tagged:
    r = c.execute("SELECT species_name FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    if r and r[0] == 'Vivillon':
        em_now_useless.add(uh)

diffs = [
    ('Hundos',       by_rule('iv_total=45') - tagged('Hundos'),  tagged('Hundos') - by_rule('iv_total=45')),
    ('Background',   by_rule('fresh_has_location_card=1') - tagged('Background'),  tagged('Background') - by_rule('fresh_has_location_card=1')),
    ('Adventure Eff',by_rule('fresh_pokemon_badge != 0') - tagged('Adventure Eff'), tagged('Adventure Eff') - by_rule('fresh_pokemon_badge != 0')),
    ('0-15-15',      by_rule('iv_atk=0 AND iv_def=15 AND iv_sta=15') - tagged('0-15-15'),  tagged('0-15-15') - by_rule('iv_atk=0 AND iv_def=15 AND iv_sta=15')),
    ('GL',           by_rule('gl_final_rank=1 AND gl_fits_at_current_level=1 AND final_form_max_cp >= 1400') - tagged('GL'),  tagged('GL') - by_rule('gl_final_rank=1 AND gl_fits_at_current_level=1 AND final_form_max_cp >= 1400')),
    ('UL',           by_rule('ul_final_rank=1 AND ul_fits_at_current_level=1 AND final_form_max_cp >= 2400') - tagged('UL'),  tagged('UL') - by_rule('ul_final_rank=1 AND ul_fits_at_current_level=1 AND final_form_max_cp >= 2400')),
    ('JUMBO',        jumbo_expected - tagged('JUMBO'),  tagged('JUMBO') - jumbo_expected),
    ('Evolve Me',    set(), em_now_useless),  # only remove evolved Vivillon
]

print('=== Fix plan ===', flush=True)
total_adds = 0; total_rems = 0
for tag, adds, rems in diffs:
    print(f'  {tag:<15} +{len(adds):>3}  -{len(rems):>3}', flush=True)
    total_adds += len(adds); total_rems += len(rems)
print(f'  Total +{total_adds} adds, -{total_rems} removes', flush=True)

# Hook services
hook_js = """
var fns={}; var bagCls=null, svcCls=null; var bagInst=null, svcInst=null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG=bind('il2cpp_domain_get','pointer',[]);
    fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4); var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    bagCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
    svcCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
    function hookAll(cls, label) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = fns.cGM(cls, iter)) && !m.isNull()) {
            try { var addr = m.readPointer(); if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (label === 'bag' && !bagInst) { bagInst = args[0].toString(); send({type:'h', msg:'bag '+bagInst}); }
                        if (label === 'svc' && !svcInst) { svcInst = args[0].toString(); send({type:'h', msg:'svc '+svcInst}); }
                    }
                });
            } catch(e) {}
        }
    }
    hookAll(bagCls, 'bag'); hookAll(svcCls, 'svc');
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {bag: bagInst, svc: svcInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload',{})
    if isinstance(p,dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("\nWaiting for bag+svc hooks (interact with PoGo)...", flush=True)
bag = svc = None
for i in range(120):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('bag') and not bag: bag = g['bag']
    if g.get('svc') and not svc: svc = g['svc']
    if bag and svc: break
if not bag or not svc:
    print(f"FAIL: bag={bag} svc={svc}", flush=True); sess.detach(); exit(1)
print(f"bag={bag} svc={svc}", flush=True)
hs.unload()

# Walk script: uids -> proto pointers
js_walk = """
rpc.exports = {
    findProtos: function(bag, uids) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cMN = bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
        var rI = bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga = cMN(cls, Memory.allocUtf8String('get_AllPokemon'), 0);
        var inst = ptr(bag);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = rI(ga, inst, ptr(0), exc);
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        var count = list.add(0x18).readS32();
        var wanted = {}; for (var i = 0; i < uids.length; i++) wanted[uids[i]] = true;
        var found = {}; var node = head; var iters = 0;
        while (node && !node.isNull() && iters < count + 200) {
            try {
                var key = node.add(0x28).readU64().toString();
                if (wanted[key]) found[key] = node.add(0x30).readPointer().toString();
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }
        return {found: found};
    }
};
"""
walker = sess.create_script(js_walk); walker.load()

bulk = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
bulk.load(); bulk.exports_sync.init_status()

def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
def hex_to_uid(uh):
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    return to_uid_str(r[0]) if r else None

# Collect all UIDs we need to look up at once
all_uids = set()
for _, adds, rems in diffs:
    for uh in adds: all_uids.add(uh)
    for uh in rems: all_uids.add(uh)
print(f"\nLooking up {len(all_uids)} uids in bag...", flush=True)
uid_strs = [hex_to_uid(uh) for uh in all_uids]
walk_r = walker.exports_sync.find_protos(bag, [u for u in uid_strs if u])
found = walk_r['found']
print(f"  Found {len(found)}/{len(uid_strs)}", flush=True)

# Build hex_to_proto map
hex_to_proto = {}
for uh in all_uids:
    u = hex_to_uid(uh)
    if u and u in found: hex_to_proto[uh] = found[u]

# Apply fixes
for tag_name, adds, rems in diffs:
    ftid = bulk.exports_sync.find_tag_id_by_name(svc, tag_name)
    if not ftid.get('ok'):
        print(f"\n!! Tag '{tag_name}' not found server-side, skipping", flush=True)
        continue
    tag_proto = ftid['tagProtoAddr']

    # Untag surplus
    if rems:
        print(f"\n--- Untagging {len(rems)} from {tag_name} ---", flush=True)
        for uh in rems:
            proto = hex_to_proto.get(uh)
            if not proto: print(f"  {uh} not in bag, skipping", flush=True); continue
            res = bulk.exports_sync.bulk_untag_one(svc, proto, tag_proto)
            ok = 'OK' if res.get('ok') else 'FAIL'
            print(f"  {ok}  {uh}", flush=True)
            time.sleep(0.2)

    # Tag adds
    if adds:
        print(f"\n--- Tagging {len(adds)} into {tag_name} ---", flush=True)
        ptrs = [hex_to_proto[uh] for uh in adds if uh in hex_to_proto]
        if not ptrs: continue
        bulk.exports_sync.bulk_tag_many(svc, tag_proto, ptrs[:1]); time.sleep(0.5)
        for i in range(0, len(ptrs), 30):
            chunk = ptrs[i:i+30]
            res = bulk.exports_sync.bulk_tag_many(svc, tag_proto, chunk)
            print(f"  batch {i//30+1}: built {res.get('built')}/{len(chunk)}", flush=True)
            time.sleep(0.3)

# Final verify
print("\n=== Final server-side counts ===", flush=True)
for tag_name, _, _ in diffs:
    ftid = bulk.exports_sync.find_tag_id_by_name(svc, tag_name)
    if ftid.get('ok'):
        chk = bulk.exports_sync.get_pokemon_for_tag(svc, ftid['idx'])
        cnt = chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')
        print(f"  {tag_name:<15} server-side count: {cnt}", flush=True)

sess.detach()
