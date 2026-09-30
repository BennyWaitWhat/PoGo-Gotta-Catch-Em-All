"""Hook every native BLE read completion path. Log UUID + bytes returned.
Find the sleep-records characteristic, then inject forged bytes there."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
var captures = [];
rpc.exports = { fetch: function() { var r = captures.slice(); captures = []; return r; } };

var mod = Process.findModuleByName('libholoholo.so');
var allExports = mod.enumerateExports();

// Look for read-related, notify-related, and characteristic-data-handling functions
var hookFns = [];
allExports.forEach(function(e) {
    var n = e.name;
    if (n.indexOf('Characteristic') < 0 && n.indexOf('Peripheral') < 0 && n.indexOf('Sleep') < 0 && n.indexOf('Sfida') < 0) return;
    // Filter to JNI bridge methods + completion handlers + value-read handlers
    if (n.indexOf('OnRead') >= 0 || n.indexOf('OnNotif') >= 0 || n.indexOf('ReadValue') >= 0
        || n.indexOf('OnDataReceived') >= 0 || n.indexOf('GetValue') >= 0
        || n.indexOf('nativeOn') >= 0 || n.indexOf('native_on') >= 0
        || n.indexOf('CharacteristicChanged') >= 0 || n.indexOf('OnSleep') >= 0
        || n.indexOf('ProcessSleepLog') >= 0 || n.indexOf('HandleSleep') >= 0
        || n.indexOf('SleepLogRecord') >= 0
        || (n.indexOf('Characteristic') >= 0 && (n.indexOf('Update') >= 0 || n.indexOf('Set') >= 0))) {
        hookFns.push(e);
    }
});

send({type:'h', msg:'Hooking '+hookFns.length+' candidate read/notify methods'});
hookFns.forEach(function(e) {
    try {
        Interceptor.attach(e.address, {
            onEnter: function(args) {
                var rec = {fn: e.name.substring(0,90), addr: e.address.toString(), ts: Date.now(), args: []};
                // Read first 6 args; try to dereference each as bytes
                for (var i = 0; i < 6; i++) {
                    var a = args[i];
                    var info = {idx: i};
                    try {
                        info.val = a.toString();
                        if (!a.isNull()) {
                            // Try reading as int32 (size, length, etc)
                            try { info.asI32 = a.toInt32(); } catch(_) {}
                            // Try reading 16 bytes from this pointer
                            try {
                                var bytes = a.readByteArray(16);
                                if (bytes) {
                                    var u8 = new Uint8Array(bytes);
                                    var hex = '';
                                    for (var j = 0; j < u8.length; j++) hex += ('0'+u8[j].toString(16)).slice(-2);
                                    info.hex16 = hex;
                                }
                            } catch(_) {}
                        }
                    } catch(e2) {}
                    rec.args.push(info);
                }
                captures.push(rec);
            }
        });
    } catch(e) {}
});
send({type:'h', msg:'All hooks installed'});
"""
sc = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  HOOK: {p['msg']}", flush=True)
sc.on('message', on)
sc.load()

# Now trigger ReadNewSleepLogs from SleepService
# (PoGo will attempt to read sleep records from PGP via BLE)
hook2 = """
var inst = null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
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
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Sleep'), Memory.allocUtf8String('SleepService'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) { if (!inst) { inst = args[0].toString(); send({type:'h', msg:'sleep '+inst}); } }
            });
        } catch(e) {}
    }
}
rpc.exports = {
    setup: function() { init(); return {ok:true}; },
    get: function() { return {sleep: inst}; },
    trigger: function(addr) {
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
        return {ok: true};
    }
};
"""
sc2 = sess.create_script(hook2)
sc2.on('message', on)
sc2.load()
sc2.exports_sync.setup()
print("Wait for SleepService instance (open Today)...", flush=True)
sleep_inst = None
for i in range(60):
    time.sleep(1)
    g = sc2.exports_sync.get()
    if g.get('sleep'): sleep_inst = g['sleep']; break
print(f"Got: {sleep_inst}", flush=True)

if sleep_inst:
    print("Triggering ReadNewSleepLogs 5 times...", flush=True)
    for i in range(5):
        sc2.exports_sync.trigger(sleep_inst)
        time.sleep(2)

print("\nWaiting 15s for BLE traffic...", flush=True)
time.sleep(15)
caps = sc.exports_sync.fetch()
print(f"\n=== {len(caps)} BLE-related events ===", flush=True)
# Group by function
from collections import Counter
fn_counts = Counter(c['fn'][:60] for c in caps)
for fn, n in fn_counts.most_common(20):
    print(f"  [{n:3d}]  {fn}", flush=True)
# Show sample events
print(f"\n=== Sample events (first 5) ===", flush=True)
for c in caps[:5]:
    print(f"\n  {c['fn'][:80]}", flush=True)
    for a in c['args']:
        if a.get('hex16'): print(f"    arg{a['idx']}: ptr={a['val']} hex={a['hex16']}", flush=True)
sess.detach()
