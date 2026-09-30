"""Hook the CompleteQuestOutProto deserialization to capture server response status."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook the CompleteQuestOutProto MergeFrom (deserializer) - that's where server data comes in
# AND hook the CompleteQuest response continuation
js = """
var responses = [];

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
    var mGPC = bind('il2cpp_method_get_param_count','int',['pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var hpr = null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-protos.dll'){ hpr=i; break; } }

    var oCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('CompleteQuestOutProto'));
    if (!oCls || oCls.isNull()) { send({type:'h', msg:'CompleteQuestOutProto not found'}); return 0; }

    // Hook every method on CompleteQuestOutProto - status reads will get logged
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, count = 0;
    while ((m = cGM(oCls, iter)) && !m.isNull()) {
        var n = mGN(m).readCString();
        if (n === 'set_Status' || n === 'MergeFrom') {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                (function(mname) {
                    Interceptor.attach(addr, {
                        onEnter: function(args) {
                            var thiz = args[0];
                            try {
                                var st = thiz.add(0x10).readS32();  // Status field
                                var qPtr = thiz.add(0x18).readPointer();  // Quest field
                                var info = {method: mname, status: st, questPtr: qPtr.toString()};
                                if (mname === 'set_Status' && args[1]) {
                                    info.newStatus = args[1].toInt32();
                                }
                                responses.push(info);
                                send({type:'r', data: info});
                            } catch(e) {}
                        }
                    });
                    count++;
                })(n);
            } catch(e) {}
        }
    }
    send({type:'h', msg: 'hooked '+count+' on CompleteQuestOutProto'});
    return count;
}
rpc.exports = {
    setup: function() { return {hooked: init()}; },
    fetch: function() { var r = responses; responses = []; return r; }
};
"""
hs = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict):
        if 'msg' in p: print(f"  HOOK: {p['msg']}")
        elif 'data' in p: print(f"  RESPONSE: {p['data']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
time.sleep(2)

# Now find QuestRpcService and fire CompleteQuest for each sub-quest
import subprocess as sp
print("\n=== Hooks installed. Waiting 10s for any pending PoGo activity ===")
time.sleep(10)

# Now trigger CompleteQuest via separate script (already have RPC inst from earlier)
# Or just get it again
print("\n=== Now hook QuestRpcService to get instance + fire CompleteQuest ===")
hook2_js = """
var rpcSvc = null;
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
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestRpcService'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) { if (!rpcSvc) { rpcSvc = args[0].toString(); send({type:'h', msg:'rpc '+rpcSvc}); } }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {rpc: rpcSvc}; } };
"""
hs2 = sess.create_script(hook2_js)
hs2.on('message', on)
hs2.load()
hs2.exports_sync.setup()
print("Waiting up to 120s for QuestRpcService hook (open Today/Quests)...")
rpc_inst = None
for i in range(120):
    time.sleep(1)
    g = hs2.exports_sync.get()
    if g.get('rpc'): rpc_inst = g['rpc']; break
print(f"RPC: {rpc_inst}")
if rpc_inst:
    # Fire CompleteQuest for Sub0
    fire_js = """
    rpc.exports = {
        cq: function(addr, qid, sqid) {
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
            var stringNew = new NativeFunction(addrs['il2cpp_string_new'],'pointer',['pointer']);
            var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
            var gi = null;
            for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
            var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestRpcService'));
            var m = cMN(cls, Memory.allocUtf8String('CompleteQuest'), 4);
            var qStr = stringNew(Memory.allocUtf8String(qid));
            var sqStr = stringNew(Memory.allocUtf8String(sqid));
            var nullableBuf = Memory.alloc(8); nullableBuf.writeS32(0); nullableBuf.add(4).writeU8(0);
            var pid = Memory.alloc(8); pid.writeU64(0);
            var args = Memory.alloc(4 * Process.pointerSize);
            args.writePointer(qStr); args.add(8).writePointer(sqStr);
            args.add(16).writePointer(nullableBuf); args.add(24).writePointer(pid);
            var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
            var ret = rI(m, inst, args, ex);
            return {ret: ret ? ret.toString() : 'null'};
        }
    };
    """
    fs = sess.create_script(fire_js); fs.load()
    print("\nFiring CompleteQuest for Sub0...")
    print(fs.exports_sync.cq(rpc_inst, 'STORY_QUEST_WAINA23_1', 'STORY_QUEST_WAINA23_1_Sub0'))
    print("\nWaiting 8s for server response to come back...")
    time.sleep(8)
    print("\n=== Captured CompleteQuestOutProto activities: ===")
    captured = hs.exports_sync.fetch()
    for c in captured: print(f"  {c}")
sess.detach()
