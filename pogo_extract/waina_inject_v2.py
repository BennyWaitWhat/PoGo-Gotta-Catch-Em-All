"""V2: Capture live RpcRequest, copy its service deps to fresh one, fire WAINA submit."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var liveRr = null;
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
    var rrCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Rpc'), Memory.allocUtf8String('RpcRequest'));
    if (rrCls.isNull()) return;
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(rrCls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            var n = mGN(m).readCString();
            if (n === 'Send' || n === 'bayq' || n === 'bayr' || n === 'bays') {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (!liveRr) { liveRr = args[0].toString(); send({type:'h', msg:'liveRr '+liveRr}); }
                    }
                });
            }
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {rr: liveRr}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 90s for live RpcRequest (PoGo will fire one within seconds)...", flush=True)
liveRr = None
for i in range(90):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('rr'): liveRr = g['rr']; break
if not liveRr:
    print("No live RpcRequest captured. Move around in PoGo to trigger map RPCs.", flush=True)
    sess.detach(); exit(1)
print(f"\nLive RpcRequest: {liveRr}", flush=True)
hs.unload()

js = """
rpc.exports = {
    inject: function(liveRrAddr, startTimeSec, durationSec) {
        var live = ptr(liveRrAddr);
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
        var reqCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('WainaSubmitSleepDataRequest'));
        var recCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('ClientSleepRecord'));
        var rrCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Rpc'), Memory.allocUtf8String('RpcRequest'));

        // Build the proto
        var req = objNew(reqCls);
        var reqCtor = cMN(reqCls, Memory.allocUtf8String('.ctor'), 0);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        rI(reqCtor, req, ptr(0), ex);
        var rec = objNew(recCls);
        var recCtor = cMN(recCls, Memory.allocUtf8String('.ctor'), 0);
        rI(recCtor, rec, ptr(0), ex);
        rec.add(0x10).writeU32(startTimeSec);
        rec.add(0x14).writeU32(durationSec);

        // Add rec to req's RepeatedField via direct array manipulation
        var rfPtr = req.add(0x10).readPointer();
        var arrayNewSpec = new NativeFunction(addrs['il2cpp_array_new_specific'],'pointer',['pointer','uint32']);
        var arrayClassGet = new NativeFunction(addrs['il2cpp_array_class_get'],'pointer',['pointer','uint32']);
        var arrCls = arrayClassGet(recCls, 1);
        var arr = arrayNewSpec(arrCls, 1);
        arr.add(0x20).writePointer(rec);
        rfPtr.add(0x10).writePointer(arr);
        rfPtr.add(0x18).writeS32(1);

        // Now allocate fresh RpcRequest and copy service deps from live
        var rr = objNew(rrCls);
        var rrCtor = cMN(rrCls, Memory.allocUtf8String('.ctor'), 0);
        rI(rrCtor, rr, ptr(0), ex);

        // Copy service refs: live[+0x10..+0x38] → rr[+0x10..+0x38]
        // cwtr (RpcManager), cwts (TimeService), cwtt (Random), cwtu (Scheduler), cwtv (Connectivity)
        var fieldsBefore = {
            cwtr_before: rr.add(0x10).readPointer().toString(),
            cwts_before: rr.add(0x18).readPointer().toString(),
            cwtt_before: rr.add(0x20).readPointer().toString(),
            cwtu_before: rr.add(0x28).readPointer().toString(),
            cwtv_before: rr.add(0x30).readPointer().toString(),
        };
        for (var off = 0x10; off <= 0x30; off += 8) {
            var p = live.add(off).readPointer();
            rr.add(off).writePointer(p);
        }
        var fieldsAfter = {
            cwtr_after: rr.add(0x10).readPointer().toString(),
            cwts_after: rr.add(0x18).readPointer().toString(),
            cwtt_after: rr.add(0x20).readPointer().toString(),
            cwtu_after: rr.add(0x28).readPointer().toString(),
            cwtv_after: rr.add(0x30).readPointer().toString(),
        };

        // Set sane defaults: TimeoutMs=30000, RetryDelay=5000, RpcId=arbitrary
        rr.add(0x58).writeS32(30000);
        rr.add(0x5c).writeS32(5000);
        rr.add(0x60).writeS32(3);  // HighLevelRetries
        rr.add(0x64).writeS32(0xCAFE0001);  // unique RpcId

        // Now call bayq(826, req, null, null)
        var bayq = cMN(rrCls, Memory.allocUtf8String('bayq'), 4);
        var methodIdBuf = Memory.alloc(4); methodIdBuf.writeS32(826);
        var args = Memory.alloc(4 * Process.pointerSize);
        args.writePointer(methodIdBuf);
        args.add(8).writePointer(req);
        args.add(16).writePointer(ptr(0));
        args.add(24).writePointer(ptr(0));
        var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
        var bayqRet = rI(bayq, rr, args, ex2);
        var bayqExc = ex2.readPointer();

        // Call Send
        var sendM = cMN(rrCls, Memory.allocUtf8String('Send'), 0);
        var ex3 = Memory.alloc(Process.pointerSize); ex3.writePointer(ptr(0));
        var sendRet = rI(sendM, rr, ptr(0), ex3);
        var sendExc = ex3.readPointer();

        return {
            req: req.toString(), rec: rec.toString(), rr: rr.toString(),
            fieldsBefore: fieldsBefore, fieldsAfter: fieldsAfter,
            bayqRet: bayqRet ? bayqRet.toString() : 'null',
            bayqExc: bayqExc.toString(),
            sendRet: sendRet ? sendRet.toString() : 'null',
            sendExc: sendExc.toString()
        };
    },

    readExc: function(addr) {
        var p = ptr(addr);
        if (p.isNull()) return null;
        var addrs = {}; var il2cpp = Process.findModuleByName('libil2cpp.so');
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        var ogc = new NativeFunction(addrs['il2cpp_object_get_class'],'pointer',['pointer']);
        var cGN = new NativeFunction(addrs['il2cpp_class_get_name'],'pointer',['pointer']);
        function readUtf16(p2) {
            if (p2.isNull()) return '';
            var len = p2.add(0x10).readS32();
            if (len <= 0 || len > 500) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(p2.add(0x14 + i*2).readU16()));
            return chars.join('');
        }
        var cls = ogc(p);
        var clsName = cGN(cls).readCString();
        var msg = '';
        for (var off = 0x10; off < 0x40; off += 8) {
            try {
                var sp2 = p.add(off).readPointer();
                if (!sp2.isNull()) {
                    var s = readUtf16(sp2);
                    if (s.length > 5 && s.length < 500) { msg = s; break; }
                }
            } catch(e) {}
        }
        return {cls: clsName, msg: msg};
    }
};
"""
sc = sess.create_script(js); sc.load()
import datetime
now = int(time.time())
yesterday_10pm = now - 86400 * 1 - 4*3600
print(f"\n=== Injecting WAINA submit: start={yesterday_10pm}, duration=28800s ===", flush=True)
r = sc.exports_sync.inject(liveRr, yesterday_10pm, 28800)
print(json.dumps(r, indent=2), flush=True)

# Decode any exceptions
if r.get('bayqExc') != '0x0':
    print('\nbayq exception:', sc.exports_sync.read_exc(r['bayqExc']), flush=True)
if r.get('sendExc') != '0x0':
    print('send exception:', sc.exports_sync.read_exc(r['sendExc']), flush=True)
print("\nWaiting 8s for response...", flush=True)
time.sleep(8)
sess.detach()
