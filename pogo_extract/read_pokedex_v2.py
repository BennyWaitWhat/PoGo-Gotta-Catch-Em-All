"""V2: Walk all 10 PokedexImpl dicts; per-regional-dex hundo status.

Each cug{r,s,t,u,v,w,x,y,z} + cuha = a regional dex dict per PoGo's grouping.
"""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook to capture instance
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
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) {
                    if (!inst) { inst = args[0].toString(); send({type:'h', msg:'inst '+inst}); }
                }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {inst: inst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 120s for PokedexImpl hook (open Pokedex in PoGo if needed)...")
inst = None
for i in range(120):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('inst'):
        inst = g['inst']; break
if not inst:
    print("Hook didn't fire. Open the Pokedex in PoGo")
    sess.detach(); exit(1)
print(f"PokedexImpl: {inst}")
hs.unload()

js = """
rpc.exports = {
    walkAllRegional: function(addr) {
        var inst = ptr(addr);
        function readUtf16Str(strPtr) {
            if (strPtr.isNull()) return '';
            var len = strPtr.add(0x10).readS32();
            if (len <= 0 || len > 200) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
            return chars.join('');
        }

        function readEntry(protoPtr) {
            if (protoPtr.isNull()) return null;
            var entryNum = protoPtr.add(0x10).readS32();
            var timesCaptured = protoPtr.add(0x18).readS32();
            var timesEncountered = protoPtr.add(0x14).readS32();
            var capturedShiny = protoPtr.add(0x40).readU8();
            // Walk CategoryStatus MapField at +0x80
            var hundoAcq = false;
            var shinyHundoAcq = false;
            var threeStarAcq = false;
            var hundoTimestamp = '0';
            var mapField = protoPtr.add(0x80).readPointer();
            if (!mapField.isNull()) {
                var list = mapField.add(0x18).readPointer();
                if (!list.isNull()) {
                    var head = list.add(0x10).readPointer();
                    var lcount = list.add(0x18).readS32();
                    var node = head; var iters = 0;
                    while (node && !node.isNull() && iters < lcount + 50) {
                        try {
                            var kvpVal = node.add(0x30).readPointer();
                            if (!kvpVal.isNull()) {
                                var catEnum = kvpVal.add(0x10).readS32();
                                var acq = kvpVal.add(0x15).readU8();
                                var ts = kvpVal.add(0x18).readU64().toString();
                                if (catEnum === 14 && acq) { hundoAcq = true; hundoTimestamp = ts; }
                                if (catEnum === 102 && acq) shinyHundoAcq = true;
                                if (catEnum === 13 && acq) threeStarAcq = true;
                            }
                            var next = node.add(0x18).readPointer();
                            if (next.isNull() || next.equals(head)) break;
                            node = next;
                        } catch(e) { break; }
                        iters++;
                    }
                }
            }
            return {pid: entryNum, captured: timesCaptured, encountered: timesEncountered,
                    shiny: capturedShiny, hundo: hundoAcq, hundoTs: hundoTimestamp,
                    shinyHundo: shinyHundoAcq, threeStar: threeStarAcq};
        }

        var labels = ['cugr','cugs','cugt','cugu','cugv','cugw','cugx','cugy','cugz','cuha'];
        var offsets = [0x10,0x18,0x20,0x28,0x30,0x38,0x40,0x48,0x50,0x58];
        var out = {};
        for (var di = 0; di < labels.length; di++) {
            var dictPtr = inst.add(offsets[di]).readPointer();
            if (dictPtr.isNull()) { out[labels[di]] = []; continue; }
            var entries = dictPtr.add(0x18).readPointer();
            var maxLen = entries.add(0x18).readS32();
            var data = entries.add(0x20);
            var arr = [];
            for (var i = 0; i < maxLen; i++) {
                var ep = data.add(i * 24);
                var hashCode = ep.readS32();
                if (hashCode < 0) continue;
                var key = ep.add(8).readS32();
                var protoPtr = ep.add(16).readPointer();
                if (protoPtr.isNull()) continue;
                var e = readEntry(protoPtr);
                if (e) { e.dictKey = key; arr.push(e); }
            }
            out[labels[di]] = arr;
        }
        return out;
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.walk_all_regional(inst)
print(f"\nWalked dicts:")
for k, v in r.items():
    print(f"  {k}: {len(v)} entries")

with open('pokedex_regional.json','w') as f:
    json.dump(r, f, indent=2)
print(f"\nSaved pokedex_regional.json")
sess.detach()
