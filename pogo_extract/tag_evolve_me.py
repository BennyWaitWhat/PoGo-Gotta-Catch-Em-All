"""Create 'Evolve Me' tag and tag form-completion candidates:
   - 15 Scatterbug/Spewpa for missing Vivillon patterns
   - Best Tandemaus for missing Maushold FamilyOfThree
   - Best Own Tempo Rockruff for missing Lycanroc Dusk
"""
import frida, json, time, subprocess, sqlite3
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

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
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
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
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 60s for hooks (interact with PoGo: open storage, tap a tag)...")
bag = svc = None
for i in range(60):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('bag') and not bag: bag = g['bag']
    if g.get('svc') and not svc: svc = g['svc']
    if bag and svc: break
if not bag or not svc:
    print(f"FAIL: bag={bag} svc={svc}")
    sess.detach(); exit(1)
print(f"Got: bag={bag} svc={svc}")
hs.unload()

# Build candidate list
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
fe = {int(k):v for k,v in json.load(open('form_enum.json')).items()}

def best(species, form):
    return c.execute("""SELECT uid_hex, uid, iv_total FROM pokemon
        WHERE species_name=? AND form=? AND in_bag=1
        ORDER BY iv_total DESC, cp DESC LIMIT 1""", (species, form)).fetchone()

candidates = []  # (label, uid_hex, uid)
# Vivillon completion - prefer Scatterbug, fall back to Spewpa
def pat(n): return n.replace('Vivillon','').replace('Scatterbug','').replace('Spewpa','')
have_pats = set(pat(fe.get(r[0],'')) for r in c.execute("SELECT form FROM pokemon WHERE species_name='Vivillon' AND in_bag=1"))
all_pats = set(pat(fe[fid]) for fid in range(2594, 2614) if fid in fe)
for pp in sorted(all_pats - have_pats):
    sc = next((f for f,n in fe.items() if 2745<=f<=2764 and pat(n)==pp), None)
    sp = next((f for f,n in fe.items() if 2765<=f<=2784 and pat(n)==pp), None)
    pick = None
    if sc:
        r = best('Scatterbug', sc)
        if r: pick = ('Scatterbug', pp, r)
    if not pick and sp:
        r = best('Spewpa', sp)
        if r: pick = ('Spewpa', pp, r)
    if pick:
        candidates.append((f"viv_{pp}", pick[2][0], pick[2][1]))

# Maushold FamilyOfThree - best Tandemaus
have_maus = set(r[0] for r in c.execute("SELECT form FROM pokemon WHERE species_name='Maushold' AND in_bag=1"))
if 2983 not in have_maus:
    r = c.execute("""SELECT uid_hex, uid FROM pokemon WHERE species_name='Tandemaus' AND in_bag=1
        ORDER BY iv_total DESC, cp DESC LIMIT 1""").fetchone()
    if r: candidates.append(('maus_FoT', r[0], r[1]))

# Lycanroc Dusk - best Own Tempo Rockruff (form 2737)
have_lyc = set(r[0] for r in c.execute("SELECT form FROM pokemon WHERE species_name='Lycanroc' AND in_bag=1"))
if 2686 not in have_lyc:
    r = c.execute("""SELECT uid_hex, uid FROM pokemon WHERE species_name='Rockruff' AND form=2737 AND in_bag=1
        ORDER BY iv_total DESC, cp DESC LIMIT 1""").fetchone()
    if r: candidates.append(('lyc_Dusk', r[0], r[1]))

print(f"\nCandidates to tag: {len(candidates)}")
for lbl, uh, _ in candidates: print(f"  {lbl:20s} {uh}")

# Create Evolve Me tag
script = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
script.load()
script.exports_sync.init_status()

# Check if tag exists already
existing = script.exports_sync.find_tag_id_by_name(svc, 'Evolve Me')
if not existing.get('ok'):
    print("\nCreating 'Evolve Me' tag (color 5)...")
    rr = script.exports_sync.add_tag_on_instance(svc, 'Evolve Me', 5)
    print(f"  result: {rr}")
    time.sleep(1)
    existing = script.exports_sync.find_tag_id_by_name(svc, 'Evolve Me')
if not existing.get('ok'):
    print(f"FAIL to find tag after create: {existing}")
    sess.detach(); exit(1)
print(f"\nEvolve Me tagProto: {existing['tagProtoAddr']} idx={existing['idx']}")

# Find proto pointers via bag walk
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
        while (node && !node.isNull() && iters < count + 100) {
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
def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
uids = [to_uid_str(c[2]) for c in candidates]
walker = sess.create_script(js_walk)
walker.load()
r = walker.exports_sync.find_protos(bag, uids)
found = r['found']
print(f"\nFound protos: {len(found)}/{len(uids)}")
walker.unload()

ptrs = [found[u] for u in uids if u in found]
if ptrs:
    print(f"\nTagging {len(ptrs)} as Evolve Me...")
    # Warm-up
    script.exports_sync.bulk_tag_many(svc, existing['tagProtoAddr'], ptrs[:1])
    time.sleep(1)
    for i in range(0, len(ptrs), 30):
        chunk = ptrs[i:i+30]
        res = script.exports_sync.bulk_tag_many(svc, existing['tagProtoAddr'], chunk)
        if res.get('ok'):
            print(f"  batch {i//30+1}: built {res.get('built')}/{len(chunk)}")
        else:
            print(f"  batch {i//30+1}: FAIL {res.get('err')}")
        time.sleep(0.3)

time.sleep(2)
chk = script.exports_sync.get_pokemon_for_tag(svc, existing['idx'])
print(f"\nFinal Evolve Me count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")
sess.detach()
