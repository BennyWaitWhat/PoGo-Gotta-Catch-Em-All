"""Fix the 1 failed Maushold untag + the 2 missing add tags."""
import frida, json, time, subprocess, sqlite3
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

UNTAG_UIDS = ['5eef99894448a40b']  # Maushold (retry untag)
ADD_UIDS = [
    'da75689ebe85881c','8bfeb58f8cc949a3','4c808fe3eb3d1cbe',
    'f723d624a0b82ae2','447d2d2b9ac25db8',
]

# Hook bag + svc
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
print("Waiting up to 90s for hooks (open PoGo storage + tap a tag to invoke svc)...")
bag = svc = None
for i in range(90):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('bag') and not bag: bag = g['bag']
    if g.get('svc') and not svc: svc = g['svc']
    if bag and svc: break
print(f"Got: bag={bag} svc={svc}")
# Fall back to cached svc if hook didn't fire
if not svc:
    svc = '0x798a77fd00'
    print(f"Hook didn't fire; using cached svc={svc} from prior run (same PID)")
if not bag:
    bag = '0x798ae7c780'
    print(f"Hook didn't fire; using cached bag={bag}")
hs.unload()

script = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
script.load()
script.exports_sync.init_status()

ftid = script.exports_sync.find_tag_id_by_name(svc, 'Evolve Me')
print(f"tag idx={ftid['idx']}")

# Walk
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

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
def hex_to_uid_str(uh):
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    return to_uid_str(r[0]) if r else None

untag_str = [hex_to_uid_str(u) for u in UNTAG_UIDS]
add_str = [hex_to_uid_str(u) for u in ADD_UIDS]
all_uids = [u for u in untag_str + add_str if u]

walker = sess.create_script(js_walk)
walker.load()
r = walker.exports_sync.find_protos(bag, all_uids)
found = r['found']
print(f"Found {len(found)}/{len(all_uids)}")
for uh in UNTAG_UIDS + ADD_UIDS:
    u = hex_to_uid_str(uh)
    p = found.get(u)
    print(f"  {uh} -> uid_str={u} proto={p}")
walker.unload()

# Warm-up untag (might trigger NPE first time)
print('\n=== Warm-up untag with first found proto (in case of NPE) ===')
warmup_proto = list(found.values())[0] if found else None
if warmup_proto:
    res = script.exports_sync.bulk_untag_one(svc, warmup_proto, ftid['tagProtoAddr'])
    print(f"  warmup result: {res}")
    time.sleep(1)
    # Re-tag the warmup
    script.exports_sync.bulk_tag_many(svc, ftid['tagProtoAddr'], [warmup_proto])
    time.sleep(0.5)

# Now untag the Maushold
print('\n=== Untag Maushold ===')
for uh in UNTAG_UIDS:
    u = hex_to_uid_str(uh)
    if u and u in found:
        proto = found[u]
        res = script.exports_sync.bulk_untag_one(svc, proto, ftid['tagProtoAddr'])
        print(f"  {uh} -> {res}")
        time.sleep(0.3)

# Tag adds
print('\n=== Tag adds ===')
add_ptrs = [found[u] for u in add_str if u in found]
print(f"Have {len(add_ptrs)} ptrs to tag")
if add_ptrs:
    res = script.exports_sync.bulk_tag_many(svc, ftid['tagProtoAddr'], add_ptrs)
    print(f"  result: built={res.get('built')} ok={res.get('ok')} err={res.get('err')}")

time.sleep(2)
chk = script.exports_sync.get_pokemon_for_tag(svc, ftid['idx'])
print(f"\nFinal Evolve Me count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")
sess.detach()
