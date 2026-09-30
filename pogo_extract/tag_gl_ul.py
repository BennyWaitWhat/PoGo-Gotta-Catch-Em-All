"""Create GL and UL tags, tag all #1 rank pokemon in each league."""
import frida, json, time, subprocess, sqlite3

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')

mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook to capture both bag + service instances
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
    fns.mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4);
    var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
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
rpc.exports = {
    setup: function() { init(); return {ok:true}; },
    get: function() { return {bag: bagInst, svc: svcInst}; }
};
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

# Now create tags + tag pokemon
script = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
script.load()
script.exports_sync.init_status()

# Create GL tag (color 3 = green)
print("\nCreating GL tag (color 3)...")
res = script.exports_sync.add_tag_on_instance(svc, 'GL', 3)
print(f"  result: {res}")
time.sleep(1)

# Create UL tag (color 4 = blue)
print("Creating UL tag (color 4)...")
res = script.exports_sync.add_tag_on_instance(svc, 'UL', 4)
print(f"  result: {res}")
time.sleep(1)

# Find tag protos
ftid_gl = script.exports_sync.find_tag_id_by_name(svc, 'GL')
ftid_ul = script.exports_sync.find_tag_id_by_name(svc, 'UL')
if not ftid_gl.get('ok') or not ftid_ul.get('ok'):
    print(f"Tag find failed: GL={ftid_gl} UL={ftid_ul}")
    sess.detach(); exit(1)
print(f"\nGL tagProto: {ftid_gl['tagProtoAddr']} idx={ftid_gl['idx']}")
print(f"UL tagProto: {ftid_ul['tagProtoAddr']} idx={ftid_ul['idx']}")

# Bag walk for proto pointers
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
script.unload()
walker = sess.create_script(js_walk)
walker.load()

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

# Get GL #1 UIDs
gl_rows = c.execute("SELECT uid_hex, uid FROM pokemon WHERE in_bag=1 AND gl_rank=1").fetchall()
ul_rows = c.execute("SELECT uid_hex, uid FROM pokemon WHERE in_bag=1 AND ul_rank=1").fetchall()
print(f"\nGL #1 pokemon: {len(gl_rows)}")
print(f"UL #1 pokemon: {len(ul_rows)}")

def to_uid_str(uid):
    u = int(uid)
    return str(u if u >= 0 else u + 2**64)

gl_uids = [to_uid_str(r[1]) for r in gl_rows]
ul_uids = [to_uid_str(r[1]) for r in ul_rows]

# Find proto pointers for both lists
all_uids = list(set(gl_uids + ul_uids))
print(f"Looking up {len(all_uids)} unique UIDs...")
r = walker.exports_sync.find_protos(bag, all_uids)
found = r['found']
print(f"Found protos: {len(found)}/{len(all_uids)}")
walker.unload()

# Tag via bulk_tag.js
script2 = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
script2.load()
script2.exports_sync.init_status()

# Tag GL
gl_ptrs = [found[u] for u in gl_uids if u in found]
print(f"\nTagging {len(gl_ptrs)} as GL...")
# Warm-up call
if gl_ptrs:
    script2.exports_sync.bulk_tag_many(svc, ftid_gl['tagProtoAddr'], gl_ptrs[:1])
    time.sleep(1)
    total_built = 0
    for i in range(0, len(gl_ptrs), 30):
        chunk = gl_ptrs[i:i+30]
        res = script2.exports_sync.bulk_tag_many(svc, ftid_gl['tagProtoAddr'], chunk)
        if res.get('ok'):
            total_built += res.get('built', 0)
            print(f"  GL batch {i//30+1}: built {res.get('built')}/{len(chunk)}")
        else:
            print(f"  GL batch {i//30+1}: FAIL {res.get('err')}")
        time.sleep(0.3)

# Tag UL
ul_ptrs = [found[u] for u in ul_uids if u in found]
print(f"\nTagging {len(ul_ptrs)} as UL...")
if ul_ptrs:
    script2.exports_sync.bulk_tag_many(svc, ftid_ul['tagProtoAddr'], ul_ptrs[:1])
    time.sleep(1)
    for i in range(0, len(ul_ptrs), 30):
        chunk = ul_ptrs[i:i+30]
        res = script2.exports_sync.bulk_tag_many(svc, ftid_ul['tagProtoAddr'], chunk)
        if res.get('ok'):
            print(f"  UL batch {i//30+1}: built {res.get('built')}/{len(chunk)}")
        else:
            print(f"  UL batch {i//30+1}: FAIL {res.get('err')}")
        time.sleep(0.3)

# Verify
time.sleep(2)
gl_check = script2.exports_sync.get_pokemon_for_tag(svc, ftid_gl['idx'])
ul_check = script2.exports_sync.get_pokemon_for_tag(svc, ftid_ul['idx'])
print(f"\nFinal counts:")
print(f"  GL: {gl_check['dump'].get('+0x18_listish', {}).get('count', '?')}")
print(f"  UL: {ul_check['dump'].get('+0x18_listish', {}).get('count', '?')}")
sess.detach()
