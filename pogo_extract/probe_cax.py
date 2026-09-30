"""Inject records into dwst, then call each cax* method on SleepService to find which submits."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook CompleteQuestOutProto AND WainaSubmitSleepDataResponse to detect if WAINA RPC fires
hook_js = """
var wainaFired = [];
var sleepInst = null;
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
    var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi=null, hpr=null;
    for (var a=0;a<na;a++){
        var i=aGI(asms.add(a*Process.pointerSize).readPointer());
        var n = iGN(i).readCString();
        if (n==='holo-game.dll') gi=i;
        if (n==='holo-protos.dll') hpr=i;
    }
    // Hook WainaSubmitSleepDataRequest .ctor to detect when PoGo builds one
    var wreqCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('WainaSubmitSleepDataRequest'));
    if (!wreqCls.isNull()) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = cGM(wreqCls, iter)) && !m.isNull()) {
            var n = mGN(m).readCString();
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        wainaFired.push({cls:'WainaReq', method: n, ts: Date.now()});
                    }
                });
            } catch(e) {}
        }
    }
    // Hook WainaSubmitSleepDataResponse same way
    var wrespCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('WainaSubmitSleepDataResponse'));
    if (!wrespCls.isNull()) {
        var iter2 = Memory.alloc(Process.pointerSize); iter2.writePointer(ptr(0));
        var m2;
        while ((m2 = cGM(wrespCls, iter2)) && !m2.isNull()) {
            var n2 = mGN(m2).readCString();
            try {
                var addr = m2.readPointer();
                if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        wainaFired.push({cls:'WainaResp', method: n2, ts: Date.now()});
                    }
                });
            } catch(e) {}
        }
    }
    // Hook SleepService to capture instance
    var ssCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Sleep'), Memory.allocUtf8String('SleepService'));
    if (!ssCls.isNull()) {
        var iter3 = Memory.alloc(Process.pointerSize); iter3.writePointer(ptr(0));
        var m3;
        while ((m3 = cGM(ssCls, iter3)) && !m3.isNull()) {
            try {
                var addr = m3.readPointer();
                if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) { if (!sleepInst) { sleepInst = args[0].toString(); send({type:'h', msg:'sleep '+sleepInst}); } }
                });
            } catch(e) {}
        }
    }
}
rpc.exports = {
    setup: function() { init(); return {ok:true}; },
    fetch: function() { var r = wainaFired.slice(); wainaFired = []; return r; },
    sleepInst: function() { return sleepInst; }
};
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Wait for SleepService instance (open Sleep view)...", flush=True)
sleep_inst = None
for i in range(90):
    time.sleep(1)
    sleep_inst = hs.exports_sync.sleep_inst()
    if sleep_inst: break
print(f"Got: {sleep_inst}", flush=True)
if not sleep_inst:
    sess.detach(); exit(1)

# Helper to call any 0-arg method on SleepService
js = """
rpc.exports = {
    callMethod: function(addr, methodName) {
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
        var gi=null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Sleep'), Memory.allocUtf8String('SleepService'));
        var m = cMN(cls, Memory.allocUtf8String(methodName), 0);
        if (!m || m.isNull()) return {error:'no method '+methodName};
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var ret = rI(m, inst, ptr(0), ex);
        return {
            ret: ret ? ret.toString() : 'null',
            exc: ex.readPointer().toString()
        };
    },

    inject: function(addr, count) {
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
        var objNew = new NativeFunction(addrs['il2cpp_object_new'],'pointer',['pointer']);
        var arrNewSpec = new NativeFunction(addrs['il2cpp_array_new_specific'],'pointer',['pointer','uint32']);
        var arrClsGet = new NativeFunction(addrs['il2cpp_array_class_get'],'pointer',['pointer','uint32']);
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var hpr=null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-protos.dll'){ hpr=i; break; } }
        var dayCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('SleepDayRecordProto'));
        var srProto = inst.add(0x48).readPointer();
        var srRf = srProto.add(0x10).readPointer();
        var dayCtor = cMN(dayCls, Memory.allocUtf8String('.ctor'), 0);
        var arrCls = arrClsGet(dayCls, 1);
        var arr = arrNewSpec(arrCls, count);
        var startDay = 130;
        for (var i = 0; i < count; i++) {
            var rec = objNew(dayCls);
            var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
            rI(dayCtor, rec, ptr(0), ex);
            rec.add(0x10).writeU32(startDay + i);
            rec.add(0x14).writeU32(28800);
            rec.add(0x18).writeU8(0);
            arr.add(0x20 + i*8).writePointer(rec);
        }
        srRf.add(0x10).writePointer(arr);
        srRf.add(0x18).writeS32(count);
        return {injected: count};
    }
};
"""
sc = sess.create_script(js); sc.load()

print("\n=== Injecting 8 fake records ===", flush=True)
print(sc.exports_sync.inject(sleep_inst, 8), flush=True)

methods_to_try = ['cawz', 'caxc', 'caxf', 'ReadNewSleepLogs']
for mname in methods_to_try:
    print(f"\n=== Calling SleepService.{mname}() ===", flush=True)
    r = sc.exports_sync.call_method(sleep_inst, mname)
    print(f"  {r}", flush=True)
    print(f"  Waiting 5s for any WAINA RPC...", flush=True)
    time.sleep(5)
    fired = hs.exports_sync.fetch()
    print(f"  WAINA-related events fired: {len(fired)}", flush=True)
    if fired:
        for f in fired[:5]: print(f"    {f}", flush=True)
        print(f"  *** {mname} TRIGGERED WAINA RPC! ***", flush=True)

print("\n=== Final WAINA fires from any source ===", flush=True)
final = hs.exports_sync.fetch()
print(f"  total: {len(final)}", flush=True)
sess.detach()
