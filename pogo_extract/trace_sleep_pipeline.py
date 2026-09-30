"""Trace the entire sleep submission pipeline to identify where to inject."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
var fired = [];
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
    var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi = null, hpr = null;
    for (var a=0;a<na;a++){
        var i=aGI(asms.add(a*Process.pointerSize).readPointer());
        var n = iGN(i).readCString();
        if (n==='holo-game.dll') gi=i;
        if (n==='holo-protos.dll') hpr=i;
    }
    var pairs = [
        [gi, 'Niantic.Holoholo.Sleep', 'SleepService'],
        [gi, 'PokemonGoPlus', 'PgpApi'],
        [gi, 'Niantic.Holoholo.Pgp', 'PgpService'],
        [gi, 'Niantic.Holoholo.Pgp', 'PgpDeviceService'],
        [hpr, 'Holoholo.Rpc', 'WainaSubmitSleepDataRequest'],
        [hpr, 'Holoholo.Rpc', 'ClientSleepRecord'],
        [hpr, 'Holoholo.Rpc', 'WainaSubmitSleepDataResponse'],
    ];
    var hookedCount = 0;
    for (var p = 0; p < pairs.length; p++) {
        var cls = cFN(pairs[p][0], Memory.allocUtf8String(pairs[p][1]), Memory.allocUtf8String(pairs[p][2]));
        if (cls.isNull()) continue;
        var label = pairs[p][2];
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                var n = mGN(m).readCString();
                (function(lbl, mname) {
                    Interceptor.attach(addr, {
                        onEnter: function(args) {
                            fired.push({cls: lbl, method: mname, ts: Date.now()});
                        }
                    });
                })(label, n);
                hookedCount++;
            } catch(e) {}
        }
    }
    return hookedCount;
}
rpc.exports = {
    setup: function() { return {hooked: init()}; },
    fetch: function() { var r = fired.slice(); fired = []; return r; }
};
"""
sc = sess.create_script(js); sc.load()
print(sc.exports_sync.setup(), flush=True)

# Now trigger SleepService.ReadNewSleepLogs and see the cascade
hook_inst_js = """
var sleepInst = null;
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
    var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Sleep'), Memory.allocUtf8String('SleepService'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) { if (!sleepInst) { sleepInst = args[0].toString(); send({type:'h', msg:'sleep '+sleepInst}); } }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {sleep: sleepInst}; } };
"""
hs = sess.create_script(hook_inst_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Wait for SleepService instance (open Today/Sleep)...", flush=True)
sleep_inst = None
for i in range(120):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('sleep'): sleep_inst = g['sleep']; break
print(f"Got: {sleep_inst}", flush=True)

# Trigger ReadNewSleepLogs and watch what fires
trig_js = """
rpc.exports = {
    triggerRnsl: function(addr) {
        var inst = ptr(addr);
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
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        rI(m, inst, ptr(0), ex);
        return {triggered: true};
    }
};
"""
ts = sess.create_script(trig_js); ts.load()

if sleep_inst:
    print("Triggering ReadNewSleepLogs...", flush=True)
    ts.exports_sync.trigger_rnsl(sleep_inst)
    print("Waiting 10s for cascade...", flush=True)
    time.sleep(10)

evts = sc.exports_sync.fetch()
print(f"\n=== {len(evts)} events fired ===", flush=True)
from collections import Counter
seq = [(e['cls'], e['method']) for e in evts]
seen_seq = []
for s in seq:
    if not seen_seq or seen_seq[-1] != s:
        seen_seq.append(s)
print(f"\nUnique consecutive method calls (first 30):", flush=True)
for s in seen_seq[:30]:
    print(f"  {s[0]}.{s[1]}", flush=True)

print(f"\n=== Summary by class ===", flush=True)
ctr = Counter(e['cls'] for e in evts)
for cls, count in ctr.items():
    print(f"  {cls}: {count}", flush=True)

sess.detach()
