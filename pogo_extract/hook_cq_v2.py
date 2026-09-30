"""Capture actual server response for CompleteQuest. Unbuffered so we see logs in real time."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)

adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook CompleteQuestOutProto methods + QuestRpcService
js = """
var observed = [];
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

    // Hook ALL methods on CompleteQuestOutProto - log status reads
    var cqoCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('CompleteQuestOutProto'));
    if (!cqoCls.isNull()) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, hooked = 0;
        while ((m = cGM(cqoCls, iter)) && !m.isNull()) {
            var n = mGN(m).readCString();
            if (n === 'set_Status' || n === 'get_Status' || n === 'MergeFrom' || n === '.ctor') {
                try {
                    var addr = m.readPointer();
                    if (addr.isNull()) continue;
                    (function(mname, paramCount) {
                        Interceptor.attach(addr, {
                            onEnter: function(args) {
                                this.thiz = args[0];
                                var info = {when:'enter', cls:'CQO', method: mname};
                                if (mname === 'set_Status' && paramCount >= 1) {
                                    info.newStatus = args[1].toInt32();
                                }
                                send({type:'r', data: info});
                            },
                            onLeave: function(retval) {
                                if (mname === 'MergeFrom' && this.thiz) {
                                    try {
                                        var status = this.thiz.add(0x10).readS32();
                                        var questPtr = this.thiz.add(0x18).readPointer();
                                        var info = {when:'leave', cls:'CQO', method: mname, statusRead: status, questPtrIsNull: questPtr.isNull()};
                                        if (!questPtr.isNull()) {
                                            // ClientQuestProto: +0x10 Quest, +0x18 QuestDisplay
                                            var qp = questPtr.add(0x10).readPointer();
                                            if (!qp.isNull()) {
                                                info.questProgress = qp.add(0x48).readS32();
                                                info.questStatus = qp.add(0x58).readS32();
                                            }
                                        }
                                        // Rewards RepeatedField at +0x30
                                        try {
                                            var rewardsRf = this.thiz.add(0x30).readPointer();
                                            if (!rewardsRf.isNull()) {
                                                info.rewardsCount = rewardsRf.add(0x18).readS32();
                                            }
                                        } catch(e) {}
                                        send({type:'r', data: info});
                                    } catch(e) { send({type:'r', data:{err:e.toString()}}); }
                                }
                                if (mname === 'get_Status' && retval) {
                                    send({type:'r', data: {when:'leave', cls:'CQO', method: mname, ret: retval.toInt32()}});
                                }
                            }
                        });
                    })(n, mGPC(m));
                    hooked++;
                } catch(e) {}
            }
        }
        send({type:'h', msg:'hooked '+hooked+' on CompleteQuestOutProto'});
    } else {
        send({type:'h', msg:'CompleteQuestOutProto not found'});
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; } };
"""
sc = sess.create_script(js)
events = []
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict):
        if 'msg' in p: print(f"  HOOK: {p['msg']}", flush=True)
        elif 'data' in p: print(f"  EVT:  {p['data']}", flush=True); events.append(p['data'])
sc.on('message', on)
sc.load()
sc.exports_sync.setup()
print("\nHooks installed. Now firing CompleteQuest for Sub0...", flush=True)
time.sleep(2)

# Use a fresh hook to get RPC inst, then fire CompleteQuest
hook2 = """
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
sc2 = sess.create_script(hook2)
sc2.on('message', on)
sc2.load()
sc2.exports_sync.setup()
print("Waiting for QuestRpcService instance (open Today)...", flush=True)
rpc_inst = None
for i in range(120):
    time.sleep(1)
    g = sc2.exports_sync.get()
    if g.get('rpc'): rpc_inst = g['rpc']; break
print(f"RPC inst: {rpc_inst}", flush=True)

if rpc_inst:
    fire = """
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
    fs = sess.create_script(fire); fs.load()
    print("\nFiring CompleteQuest(STORY_QUEST_WAINA23_1, Sub0)...", flush=True)
    print(fs.exports_sync.cq(rpc_inst, 'STORY_QUEST_WAINA23_1', 'STORY_QUEST_WAINA23_1_Sub0'), flush=True)
    print("\nWaiting 15s for server response to deserialize...", flush=True)
    time.sleep(15)

print(f"\n=== TOTAL EVENTS captured: {len(events)} ===", flush=True)
for e in events:
    print(f"  {e}", flush=True)
sess.detach()
