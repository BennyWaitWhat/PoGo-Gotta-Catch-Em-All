"""Trigger SleepService.ReadNewSleepLogs + check WAINA state."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var sleepInst = null, qsInst = null;
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
    var pairs = [
        ['Niantic.Holoholo.Sleep','SleepService','sleep'],
        ['Niantic.Holoholo.Quests','QuestService','q'],
    ];
    for (var p = 0; p < pairs.length; p++) {
        var cls = cFN(gi, Memory.allocUtf8String(pairs[p][0]), Memory.allocUtf8String(pairs[p][1]));
        if (!cls || cls.isNull()) continue;
        var label = pairs[p][2];
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                (function(lbl){
                    Interceptor.attach(addr, {
                        onEnter: function(args) {
                            if (lbl==='sleep' && !sleepInst) { sleepInst = args[0].toString(); send({type:'h', msg:'sleep '+sleepInst}); }
                            if (lbl==='q' && !qsInst) { qsInst = args[0].toString(); send({type:'h', msg:'q '+qsInst}); }
                        }
                    });
                })(label);
            } catch(e) {}
        }
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {sleep: sleepInst, q: qsInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting 240s for hooks (open Today, swipe to Sleep view)...", flush=True)
got = None
for i in range(240):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('sleep') and g.get('q'): got = g; break
got = got or hs.exports_sync.get()
print(f"\nGot: {got}", flush=True)
if not got.get('sleep'):
    print("No SleepService instance. Need to navigate to Sleep view in PoGo.", flush=True)
    sess.detach(); exit(1)
hs.unload()

js = """
rpc.exports = {
    inspect: function(sleepAddr) {
        var inst = ptr(sleepAddr);
        // SleepService dwst (SleepRecordsProto) at +0x48
        var srProto = inst.add(0x48).readPointer();
        var lastUpdate = inst.add(0x50).readS64().toString();
        if (srProto.isNull()) return {error:'no SleepRecordsProto'};
        var srRf = srProto.add(0x10).readPointer();
        if (srRf.isNull()) return {srRf:'null'};
        var arr = srRf.add(0x10).readPointer();
        var count = srRf.add(0x18).readS32();
        var data = arr.add(0x20);
        var records = [];
        for (var i = 0; i < Math.min(count, 100); i++) {
            var rp = data.add(i * 8).readPointer();
            if (rp.isNull()) continue;
            records.push({
                day: rp.add(0x10).readU32(),
                duration: rp.add(0x14).readU32(),
                rewarded: rp.add(0x18).readU8()
            });
        }
        var lastUpdate2 = srProto.add(0x18).readS64().toString();
        return {count: count, lastUpdate: lastUpdate, lastUpdateProto: lastUpdate2, records: records};
    },

    triggerSync: function(sleepAddr) {
        var inst = ptr(sleepAddr);
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
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
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Sleep'), Memory.allocUtf8String('SleepService'));
        var m = cMN(cls, Memory.allocUtf8String('ReadNewSleepLogs'), 0);
        if (!m || m.isNull()) return {error:'no ReadNewSleepLogs'};
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var ret = rI(m, inst, ptr(0), ex);
        return {ret: ret ? ret.toString() : 'null', exc: ex.readPointer().toString()};
    }
};
"""
sc = sess.create_script(js); sc.load()
print("\n=== BEFORE: SleepRecords cache state ===", flush=True)
r = sc.exports_sync.inspect(got['sleep'])
print(json.dumps(r, indent=2), flush=True)

print("\n=== Triggering ReadNewSleepLogs ===", flush=True)
print(json.dumps(sc.exports_sync.trigger_sync(got['sleep']), indent=2), flush=True)
print("Waiting 10s for any RPC response...", flush=True)
time.sleep(10)

print("\n=== AFTER: SleepRecords cache state ===", flush=True)
r = sc.exports_sync.inspect(got['sleep'])
print(json.dumps(r, indent=2), flush=True)
sess.detach()
