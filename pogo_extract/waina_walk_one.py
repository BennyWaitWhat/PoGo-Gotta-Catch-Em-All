"""Walk a single WAINA23_1 sub-quest to complete + send CompleteQuest RPC for ONLY that one.
Pass sub-index as argv[1] (0-3)."""
import frida, json, time, subprocess, sys
SUB_IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 0
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}, walking Sub{SUB_IDX}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var qs = null, rpcSvc = null;
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
    var pairs = [['QuestService','q'],['QuestRpcService','r']];
    for (var p = 0; p < pairs.length; p++) {
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String(pairs[p][0]));
        if (!cls || cls.isNull()) continue;
        var label = pairs[p][1];
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                (function(lbl){
                    Interceptor.attach(addr, {
                        onEnter: function(args) {
                            if (lbl==='q' && !qs) { qs = args[0].toString(); send({type:'h', msg:'q '+qs}); }
                            if (lbl==='r' && !rpcSvc) { rpcSvc = args[0].toString(); send({type:'h', msg:'r '+rpcSvc}); }
                        }
                    });
                })(label);
            } catch(e) {}
        }
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {q: qs, r: rpcSvc}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 240s for hooks (open Today + tap Catching Some Z's)...")
got = None
for i in range(240):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('q') and g.get('r'): got = g; break
got = got or hs.exports_sync.get()
if not got.get('q'):
    print("No QuestService captured."); sess.detach(); exit(1)
print(f"Got: {got}")
hs.unload()

js = """
rpc.exports = {
    walkOne: function(qsAddr, rpcAddr, subIdx) {
        var qsInst = ptr(qsAddr);
        var rpcInst = ptr(rpcAddr);
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
        var gi = null, hpr = null;
        for (var a=0;a<na;a++){
            var i=aGI(asms.add(a*Process.pointerSize).readPointer());
            var n = iGN(i).readCString();
            if (n==='holo-game.dll') gi=i;
            if (n==='holo-protos.dll') hpr=i;
        }
        var qsCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));
        var qpCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('QuestProto'));
        var rpcCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestRpcService'));
        function readUtf16Str(p) {
            if (p.isNull()) return '';
            var len = p.add(0x10).readS32();
            if (len <= 0 || len > 1000) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(p.add(0x14 + i*2).readU16()));
            return chars.join('');
        }
        var getProto = cMN(qsCls, Memory.allocUtf8String('get_QuestsProto'), 0);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var protoObj = rI(getProto, qsInst, ptr(0), ex);
        var rfPtr = protoObj.add(0x10).readPointer();
        var arr = rfPtr.add(0x10).readPointer();
        var count = rfPtr.add(0x18).readS32();
        var maxLen = arr.add(0x18).readS32();
        var data = arr.add(0x20);
        var qp = null;
        for (var i = 0; i < Math.min(count, maxLen, 100); i++) {
            var p = data.add(i * 8).readPointer();
            if (p.isNull()) continue;
            if (readUtf16Str(p.add(0x40).readPointer()) === 'STORY_QUEST_WAINA23_1') { qp = p; break; }
        }
        if (!qp) return {error:'WAINA23_1 not found'};
        var getMP = cMN(qpCls, Memory.allocUtf8String('get_MultiPart'), 0);
        var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
        var mp = rI(getMP, qp, ptr(0), ex2);
        var subRf = mp.add(0x10).readPointer();
        var subArr = subRf.add(0x10).readPointer();
        var subCount = subRf.add(0x18).readS32();
        var subData = subArr.add(0x20);
        if (subIdx >= subCount) return {error:'subIdx out of range'};

        var sq = subData.add(subIdx * 8).readPointer();
        var subTid = readUtf16Str(sq.add(0x40).readPointer());
        var goal = sq.add(0x50).readPointer();
        var target = goal.isNull() ? 0 : goal.add(0x18).readS32();
        var oldP = sq.add(0x48).readS32();
        var oldS = sq.add(0x58).readS32();
        // Walk +1 at a time
        var steps = [];
        for (var v = oldP + 1; v <= target; v++) {
            sq.add(0x48).writeS32(v);
            steps.push(v);
        }
        sq.add(0x58).writeS32(2);

        // Send CompleteQuest RPC
        var cqM = cMN(rpcCls, Memory.allocUtf8String('CompleteQuest'), 4);
        var qStr = stringNew(Memory.allocUtf8String('STORY_QUEST_WAINA23_1'));
        var sqStr = stringNew(Memory.allocUtf8String(subTid));
        var nullableBuf = Memory.alloc(8); nullableBuf.writeS32(0); nullableBuf.add(4).writeU8(0);
        var pid = Memory.alloc(8); pid.writeU64(0);
        var args = Memory.alloc(4 * Process.pointerSize);
        args.writePointer(qStr); args.add(8).writePointer(sqStr);
        args.add(16).writePointer(nullableBuf); args.add(24).writePointer(pid);
        var ex3 = Memory.alloc(Process.pointerSize); ex3.writePointer(ptr(0));
        var ret = rI(cqM, rpcInst, args, ex3);
        return {
            subTid: subTid, target: target, progressBefore: oldP, statusBefore: oldS,
            progressAfter: sq.add(0x48).readS32(), statusAfter: sq.add(0x58).readS32(),
            steps: steps, rpcRet: ret ? ret.toString() : 'null'
        };
    }
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.walk_one(got['q'], got['r'], SUB_IDX)
print(json.dumps(r, indent=2))
print(f"\nSub{SUB_IDX} should now show as claimable. Try claiming JUST this one in PoGo.")
sess.detach()
