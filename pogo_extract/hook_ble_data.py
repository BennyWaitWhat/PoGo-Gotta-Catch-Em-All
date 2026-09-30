"""Hook PoGo's BLE inbound-data callbacks. Capture all data from PGP."""
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
var exps = mod.enumerateExports();
var addrMap = {};
exps.forEach(function(e){ addrMap[e.name] = e.address; });

var SAVE_VALUE = '_ZN3pgp7android21AndroidCharacteristic30nativeSaveValueChangedCallbackEP7_JNIEnvP8_jobjectP11_jbyteArray';
var VALUE_CHANGED = '_ZN3pgp7android21AndroidCharacteristic26nativeValueChangedCallbackEP7_JNIEnvP8_jobjecthhi';
var READ_DONE = '_ZN3pgp7android21AndroidCharacteristic26nativeReadCompleteCallbackEP7_JNIEnvP8_jobjecthi';
var WRITE_DONE = '_ZN3pgp7android21AndroidCharacteristic27nativeWriteCompleteCallbackEP7_JNIEnvP8_jobjecthi';

// Find JNIEnv->GetByteArrayElements and ->ReleaseByteArrayElements
// JNIEnv is a struct of function pointers. Functions live in JavaVM's libart.so

// SaveValueChanged is what we want most - it includes the actual data payload
if (addrMap[SAVE_VALUE]) {
    Interceptor.attach(addrMap[SAVE_VALUE], {
        onEnter: function(args) {
            var jniEnv = args[0];
            var thisObj = args[1];   // the AndroidCharacteristic Java object
            var jbyteArr = args[2];  // jbyteArray with the data
            var rec = {fn:'SaveValueChanged', ts: Date.now(), thisObj: thisObj.toString(), arr: jbyteArr.toString()};
            try {
                // JNIEnv* points to a table of functions. Get JNIEnv functions table at *jniEnv
                var jniTbl = jniEnv.readPointer();
                // GetArrayLength is at offset 0xAB * 8 = 0x558? Actually let me use offset positions:
                // JNIEnv functions:
                // GetArrayLength is index 171 = offset 171*8 = 1368 (0x558)
                // GetByteArrayElements is index 184 = 184*8 = 1472 (0x5C0)
                // ReleaseByteArrayElements is index 192 = 192*8 = 1536 (0x600)
                var GetArrayLength = jniTbl.add(171*8).readPointer();
                var GetByteArrayElements = jniTbl.add(184*8).readPointer();
                var ReleaseByteArrayElements = jniTbl.add(192*8).readPointer();
                var lenFn = new NativeFunction(GetArrayLength, 'int', ['pointer','pointer']);
                var getFn = new NativeFunction(GetByteArrayElements, 'pointer', ['pointer','pointer','pointer']);
                var relFn = new NativeFunction(ReleaseByteArrayElements, 'void', ['pointer','pointer','pointer','int']);
                var len = lenFn(jniEnv, jbyteArr);
                rec.len = len;
                if (len > 0 && len < 4096) {
                    var dataPtr = getFn(jniEnv, jbyteArr, ptr(0));
                    if (!dataPtr.isNull()) {
                        var bytes = dataPtr.readByteArray(Math.min(len, 256));
                        var u8 = new Uint8Array(bytes);
                        var hex = '';
                        for (var j = 0; j < u8.length; j++) hex += ('0'+u8[j].toString(16)).slice(-2);
                        rec.hex = hex;
                        relFn(jniEnv, jbyteArr, dataPtr, 0);
                    }
                }
            } catch(e) { rec.err = e.toString(); }
            captures.push(rec);
            send({type:'h', msg:'SaveValueChanged len='+rec.len+' hex='+(rec.hex||'').substring(0,120)});
        }
    });
}

if (addrMap[VALUE_CHANGED]) {
    Interceptor.attach(addrMap[VALUE_CHANGED], {
        onEnter: function(args) {
            var rec = {fn:'ValueChanged', ts: Date.now(),
                       arg2: args[2].toInt32() & 0xff,
                       arg3: args[3].toInt32() & 0xff,
                       arg4: args[4].toInt32()};
            captures.push(rec);
        }
    });
}

if (addrMap[READ_DONE]) {
    Interceptor.attach(addrMap[READ_DONE], {
        onEnter: function(args) {
            captures.push({fn:'ReadComplete', ts: Date.now(),
                           arg2: args[2].toInt32() & 0xff,
                           arg3: args[3].toInt32() & 0xff,
                           arg4: args[4].toInt32()});
        }
    });
}

if (addrMap[WRITE_DONE]) {
    Interceptor.attach(addrMap[WRITE_DONE], {
        onEnter: function(args) {
            captures.push({fn:'WriteComplete', ts: Date.now(),
                           arg2: args[2].toInt32() & 0xff,
                           arg3: args[3].toInt32() & 0xff,
                           arg4: args[4].toInt32()});
        }
    });
}

send({type:'h', msg: 'Hooks installed: SaveValueChanged='+(addrMap[SAVE_VALUE]?'Y':'N')+' ValueChanged='+(addrMap[VALUE_CHANGED]?'Y':'N')+' ReadDone='+(addrMap[READ_DONE]?'Y':'N')+' WriteDone='+(addrMap[WRITE_DONE]?'Y':'N')});
"""
sc = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
sc.on('message', on)
sc.load()
print("\n=== BLE inbound data hooks installed. Watching 60s for traffic ===", flush=True)

# Trigger: open Today + sleep view should fire BLE reads
print("\nTriggering ReadNewSleepLogs...", flush=True)
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
        try { var addr = m.readPointer(); if (addr.isNull()) continue;
            Interceptor.attach(addr, { onEnter: function(args) { if (!inst) { inst = args[0].toString(); send({type:'h', msg:'sleep '+inst}); }}});
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
sleep_inst = None
for i in range(60):
    time.sleep(1)
    g = sc2.exports_sync.get()
    if g.get('sleep'): sleep_inst = g['sleep']; break
print(f"SleepService inst: {sleep_inst}", flush=True)

if sleep_inst:
    for i in range(5):
        sc2.exports_sync.trigger(sleep_inst)
        time.sleep(2)

print("\nWatching 60s for BLE inbound...", flush=True)
for i in range(60):
    time.sleep(1)
    caps = sc.exports_sync.fetch()
    for c in caps:
        print(f"  [{i+1}s] {c}", flush=True)

sess.detach()
