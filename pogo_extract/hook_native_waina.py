"""Hook native WAINA serializer + emplace_back to capture sleep record buffer location.

When a real device session ever submits, we get:
- The exact bytes sent on the wire
- The address of the sleep log entry vector
- The pgp::sfida::Module instance pointer

With those, we can directly inject records OR replay the wire bytes via PoGo's auth-bound network send.
"""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
var captures = [];

function init() {
    var mod = Process.findModuleByName('libholoholo.so');
    if (!mod) return {error:'no libholoholo'};

    // Look up symbols by mangled name
    var SERIALIZE = '_ZNK27WainaSubmitSleepDataRequest18_InternalSerializeEPhPN6google8protobuf2io19EpsCopyOutputStreamE';
    var POSTPROC = '_ZNK3pgp5sfida19WainaSleepLogRecord14PostProcessLogEv';
    var EMPLACE = '_ZNSt6__ndk16vectorIN3pgp5sfida24WainaSleepLogRecordEntryENS_9allocatorIS3_EEE12emplace_backIJRNS2_15WainaSleepStateERjEEERS3_DpOT_';
    var HANDLERPC = '_ZN3pgp5sfida6Module17HandleRpcResponseENSt6__ndk112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEEN3nia3api10background10RpcManager6StatusENS2_8functionIFvvEEE';

    var exps = {};
    mod.enumerateExports().forEach(function(e){ exps[e.name] = e.address; });

    var sAddr = exps[SERIALIZE];
    var ppAddr = exps[POSTPROC];
    var emAddr = exps[EMPLACE];
    var hrAddr = exps[HANDLERPC];

    if (sAddr) {
        Interceptor.attach(sAddr, {
            onEnter: function(args) {
                this.thiz = args[0];
                this.outBuf = args[1];
                // Read up to 256 bytes of state from `this` for record introspection
                var bytes = [];
                try {
                    for (var off = 0; off < 0x80; off += 8) {
                        bytes.push({off:off, val: this.thiz.add(off).readPointer().toString()});
                    }
                } catch(e) {}
                captures.push({type:'serialize_enter', this: this.thiz.toString(), bytes: bytes});
                send({type:'h', msg:'WainaSubmit serialize() FIRED, this='+this.thiz});
            },
            onLeave: function(retval) {
                // After serialize, read what was written to outBuf
                captures.push({type:'serialize_leave', ret: retval ? retval.toString() : 'void'});
            }
        });
    }
    if (ppAddr) {
        Interceptor.attach(ppAddr, {
            onEnter: function(args) {
                captures.push({type:'PostProcessLog_enter', this: args[0].toString()});
                send({type:'h', msg:'PostProcessLog FIRED, this='+args[0]});
            }
        });
    }
    if (emAddr) {
        Interceptor.attach(emAddr, {
            onEnter: function(args) {
                // emplace_back<WainaSleepState&, uint&> - args[0]=vector, args[1]=&state, args[2]=&uint
                captures.push({type:'emplace_back_enter', vec: args[0].toString(), state: args[1].toString(), uint: args[2] ? args[2].readU32() : 0});
                send({type:'h', msg:'emplace_back FIRED on vec='+args[0]});
            }
        });
    }
    if (hrAddr) {
        Interceptor.attach(hrAddr, {
            onEnter: function(args) {
                captures.push({type:'HandleRpcResponse_enter', this: args[0].toString()});
                send({type:'h', msg:'HandleRpcResponse FIRED'});
            }
        });
    }
    return {hooked: {sAddr: sAddr ? sAddr.toString() : null, ppAddr: ppAddr ? ppAddr.toString() : null, emAddr: emAddr ? emAddr.toString() : null, hrAddr: hrAddr ? hrAddr.toString() : null}};
}

rpc.exports = {
    setup: function() { return init(); },
    fetch: function() { var c = captures.slice(); captures = []; return c; }
};
"""
sc = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  HOOK: {p['msg']}", flush=True)
sc.on('message', on)
sc.load()
print(json.dumps(sc.exports_sync.setup(), indent=2), flush=True)
print("\nHooks installed on native WAINA pipeline.", flush=True)
print("Now triggering ReadNewSleepLogs to provoke pipeline activity...", flush=True)

# Get SleepService instance and trigger ReadNewSleepLogs
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
        return {triggered: true};
    }
};
"""
sc2 = sess.create_script(hook2)
sc2.on('message', on)
sc2.load()
sc2.exports_sync.setup()
print("Wait for SleepService instance (open Today/Sleep)...", flush=True)
sleep_inst = None
for i in range(120):
    time.sleep(1)
    g = sc2.exports_sync.get()
    if g.get('sleep'): sleep_inst = g['sleep']; break
print(f"Got SleepService: {sleep_inst}", flush=True)

if sleep_inst:
    print("\nTriggering ReadNewSleepLogs 3 times with delays...", flush=True)
    for i in range(3):
        sc2.exports_sync.trigger(sleep_inst)
        time.sleep(3)

print("\nWaiting 30s for any native pipeline activity...", flush=True)
time.sleep(30)

caps = sc.exports_sync.fetch()
print(f"\n=== Native pipeline captures: {len(caps)} ===", flush=True)
for c in caps:
    print(f"  {c}", flush=True)
sess.detach()
