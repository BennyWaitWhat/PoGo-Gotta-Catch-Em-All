"""Inject WAINA sleep data via RpcRequest.bayq + Send. Test with 1 day first."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# First hook: capture an existing RpcRequest instance to mimic its setup
hook_js = """
var rpcReqInst = null;
var rpcHandlerInst = null;
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

    // Hook RpcHandler.SendRpc to capture handler instance + see existing requests fly
    var rhCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Rpc'), Memory.allocUtf8String('RpcHandler'));
    if (!rhCls.isNull()) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = cGM(rhCls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                var n = mGN(m).readCString();
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (!rpcHandlerInst) { rpcHandlerInst = args[0].toString(); send({type:'h', msg:'rh '+rpcHandlerInst}); }
                    }
                });
            } catch(e) {}
        }
    }
    // Hook RpcRequest .ctor or any method to capture an instance of RpcRequest
    var rrCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Rpc'), Memory.allocUtf8String('RpcRequest'));
    if (!rrCls.isNull()) {
        var iter2 = Memory.alloc(Process.pointerSize); iter2.writePointer(ptr(0));
        var m2;
        while ((m2 = cGM(rrCls, iter2)) && !m2.isNull()) {
            try {
                var addr = m2.readPointer();
                if (addr.isNull()) continue;
                var n = mGN(m2).readCString();
                if (n === 'Send' || n === 'bayq') {
                    Interceptor.attach(addr, {
                        onEnter: function(args) {
                            if (!rpcReqInst) { rpcReqInst = args[0].toString(); send({type:'h', msg:'rr '+rpcReqInst}); }
                        }
                    });
                }
            } catch(e) {}
        }
    }
}
rpc.exports = {
    setup: function() { init(); return {ok:true}; },
    get: function() { return {rh: rpcHandlerInst, rr: rpcReqInst}; }
};
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 90s for RpcHandler instance (any RPC firing in PoGo)...", flush=True)
got = None
for i in range(90):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('rh'): got = g; break
got = got or hs.exports_sync.get()
print(f"\nGot: {got}", flush=True)
if not got.get('rh'):
    print("No RpcHandler. Move around in PoGo to trigger map RPCs.", flush=True)
    sess.detach(); exit(1)
hs.unload()

# Now: construct and send WAINA submit
js = """
rpc.exports = {
    inject: function(rhAddr, startTimeSec, durationSec) {
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
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null, hpr = null;
        for (var a=0;a<na;a++){
            var i=aGI(asms.add(a*Process.pointerSize).readPointer());
            var n = iGN(i).readCString();
            if (n==='holo-game.dll') gi=i;
            if (n==='holo-protos.dll') hpr=i;
        }

        // Get class refs
        var reqCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('WainaSubmitSleepDataRequest'));
        var recCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('ClientSleepRecord'));
        var rrCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Rpc'), Memory.allocUtf8String('RpcRequest'));
        if (reqCls.isNull() || recCls.isNull() || rrCls.isNull()) return {error: 'class lookup failed'};

        // Allocate WainaSubmitSleepDataRequest + call .ctor
        var req = objNew(reqCls);
        var reqCtor = cMN(reqCls, Memory.allocUtf8String('.ctor'), 0);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        rI(reqCtor, req, ptr(0), ex);
        if (!ex.readPointer().isNull()) return {error: 'req ctor exception'};

        // Allocate ClientSleepRecord + ctor
        var rec = objNew(recCls);
        var recCtor = cMN(recCls, Memory.allocUtf8String('.ctor'), 0);
        var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
        rI(recCtor, rec, ptr(0), ex2);
        if (!ex2.readPointer().isNull()) return {error: 'rec ctor exception'};

        // Set StartTimeSec (+0x10) and DurationSec (+0x14)
        rec.add(0x10).writeU32(startTimeSec);
        rec.add(0x14).writeU32(durationSec);

        // The req's SleepRecord RepeatedField at +0x10
        var rfPtr = req.add(0x10).readPointer();
        if (rfPtr.isNull()) return {error: 'SleepRecord RF is null after ctor'};

        // Manually populate the RepeatedField: array at +0x10, count at +0x18
        // We need to allocate an array of ClientSleepRecord[] size 1
        var arrayNewSpec = new NativeFunction(addrs['il2cpp_array_new_specific'],'pointer',['pointer','uint32']);
        var arrayClassGet = new NativeFunction(addrs['il2cpp_array_class_get'],'pointer',['pointer','uint32']);
        var arrCls = arrayClassGet(recCls, 1);
        var arr = arrayNewSpec(arrCls, 1);
        if (arr.isNull()) return {error: 'array alloc failed'};
        // Array data starts at +0x20
        arr.add(0x20).writePointer(rec);
        rfPtr.add(0x10).writePointer(arr);
        rfPtr.add(0x18).writeS32(1);

        // Diagnostic: read back
        var readBackArr = rfPtr.add(0x10).readPointer();
        var readBackCount = rfPtr.add(0x18).readS32();
        var readBackRec = readBackArr.add(0x20).readPointer();
        var readBackStart = readBackRec.add(0x10).readU32();
        var readBackDur = readBackRec.add(0x14).readU32();

        // Now construct RpcRequest + call bayq + Send
        var rr = objNew(rrCls);
        var rrCtor = cMN(rrCls, Memory.allocUtf8String('.ctor'), 0);
        var ex3 = Memory.alloc(Process.pointerSize); ex3.writePointer(ptr(0));
        rI(rrCtor, rr, ptr(0), ex3);
        if (!ex3.readPointer().isNull()) return {error: 'rr ctor exception'};

        // Call bayq(int methodId, IMessage proto, Func callback, List sideChannels)
        var bayq = cMN(rrCls, Memory.allocUtf8String('bayq'), 4);
        if (!bayq || bayq.isNull()) return {error: 'bayq method not found'};
        var methodIdBuf = Memory.alloc(4); methodIdBuf.writeS32(826);
        var args = Memory.alloc(4 * Process.pointerSize);
        args.writePointer(methodIdBuf);
        args.add(8).writePointer(req);
        args.add(16).writePointer(ptr(0)); // null callback
        args.add(24).writePointer(ptr(0)); // null sideChannels
        var ex4 = Memory.alloc(Process.pointerSize); ex4.writePointer(ptr(0));
        var bayqRet = rI(bayq, rr, args, ex4);
        var bayqExc = ex4.readPointer();

        // Call Send()
        var send = cMN(rrCls, Memory.allocUtf8String('Send'), 0);
        var ex5 = Memory.alloc(Process.pointerSize); ex5.writePointer(ptr(0));
        var sendRet = rI(send, rr, ptr(0), ex5);
        var sendExc = ex5.readPointer();

        return {
            req: req.toString(),
            rec: rec.toString(),
            rr: rr.toString(),
            readBack: {start: readBackStart, dur: readBackDur, count: readBackCount},
            bayqRet: bayqRet ? bayqRet.toString() : 'null',
            bayqExc: bayqExc.toString(),
            sendRet: sendRet ? sendRet.toString() : 'null',
            sendExc: sendExc.toString()
        };
    }
};
"""
sc = sess.create_script(js)
sc.on('message', on)
sc.load()

# Build a sleep record for last night: 10pm yesterday → 6am today, ~28800 sec
# Use unix timestamp seconds
import datetime, math
now = int(time.time())
yesterday_10pm = now - (now % 86400) - 86400 + 22*3600  # rough yesterday 10pm UTC
duration = 28800  # 8 hours
print(f"\n=== Injecting 1 sleep day: start={yesterday_10pm}, dur={duration} sec ===", flush=True)
r = sc.exports_sync.inject(got['rh'], yesterday_10pm, duration)
print(json.dumps(r, indent=2), flush=True)
print("\nWaiting 10s for response...", flush=True)
time.sleep(10)
sess.detach()
