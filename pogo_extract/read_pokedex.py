"""Read PokedexImpl directly to find hundo (FourStar) acquired pokedex entries."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var inst = null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
    var dG = bind('il2cpp_domain_get','pointer',[]);
    var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokedexImpl'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, count = 0;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) {
                    if (!inst) { inst = args[0].toString(); send({type:'h', msg:'inst '+inst}); }
                }
            });
            count++;
        } catch(e) {}
    }
    return count;
}
rpc.exports = { setup: function() { return {hooked: init()}; }, get: function() { return {inst: inst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
print(hs.exports_sync.setup())
print("Waiting up to 120s for hook (open Pokedex in PoGo if not auto-firing)...")
inst = None
for i in range(120):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('inst'):
        inst = g['inst']; break
if not inst:
    print("Hook didn't fire. Open Pokedex (or just any menu).")
    sess.detach(); exit(1)
print(f"PokedexImpl inst: {inst}")
hs.unload()

# Read all 10 dicts and dump counts + keys
js = """
rpc.exports = {
    walk: function(addr) {
        var inst = ptr(addr);
        function walkDict(dictPtr) {
            var entries = dictPtr.add(0x18).readPointer();
            var count = dictPtr.add(0x20).readS32();
            if (entries.isNull() || count <= 0) return {count: count, keys: []};
            var maxLen = entries.add(0x18).readS32();
            var data = entries.add(0x20);
            // Entry<Int32, PokedexEntryProto>: hashCode(4) next(4) key(4) pad(4) value(8) = 24
            var entrySize = 24;
            var keys = [];
            for (var i = 0; i < maxLen; i++) {
                var ep = data.add(i * entrySize);
                var hashCode = ep.readS32();
                if (hashCode < 0) continue;
                var key = ep.add(8).readS32();
                var valPtr = ep.add(16).readPointer();
                if (valPtr.isNull()) continue;
                keys.push(key);
            }
            return {count: count, keys: keys, walked: keys.length};
        }
        var dicts = {};
        var offsets = [0x10,0x18,0x20,0x28,0x30,0x38,0x40,0x48,0x50,0x58];
        var labels = ['cugr','cugs','cugt','cugu','cugv','cugw','cugx','cugy','cugz','cuha'];
        for (var i = 0; i < offsets.length; i++) {
            var dp = inst.add(offsets[i]).readPointer();
            if (dp.isNull()) { dicts[labels[i]] = {error: 'null'}; continue; }
            dicts[labels[i]] = walkDict(dp);
        }
        return dicts;
    },

    walkOneDict: function(addr, offset) {
        var inst = ptr(addr);
        var dp = inst.add(offset).readPointer();
        var entries = dp.add(0x18).readPointer();
        var count = dp.add(0x20).readS32();
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);
        var keys = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var key = ep.add(8).readS32();
            var valPtr = ep.add(16).readPointer();
            if (valPtr.isNull()) continue;
            // Read CategoryStatus map at +0x80 OR check direct flags
            // PokedexEntryProto +0x10 = PokedexEntryNumber, +0x18 = TimesCaptured, +0x40 = CapturedShiny
            var entryNum = valPtr.add(0x10).readS32();
            var timesCaptured = valPtr.add(0x18).readS32();
            var capturedShiny = valPtr.add(0x40).readU8();
            keys.push({key: key, entryNum: entryNum, captured: timesCaptured, shiny: capturedShiny});
        }
        return {count: count, walked: keys.length, items: keys};
    }
};
"""
script = sess.create_script(js)
script.load()
print("\n=== Reading all 10 dicts in PokedexImpl ===")
r = script.exports_sync.walk(inst)
for label, info in r.items():
    if 'error' in info:
        print(f"  {label}: ERROR {info['error']}")
    else:
        print(f"  {label}: count={info['count']} walked={info['walked']}")
with open('pokedex_dicts.json','w') as f:
    json.dump(r, f, indent=2)
print(f"\nSaved per-dict keys to pokedex_dicts.json")
sess.detach()
