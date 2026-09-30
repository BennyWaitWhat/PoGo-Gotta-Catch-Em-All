"""Try to unstuck WAINA23_1 quest. Order: CompleteQueuedQuests -> UpdateQuestDetails -> CompleteQuest."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook QuestRpcService + QuestService + QuestAutoCompleteService
hook_js = """
var instances = {};
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
    var pairs = [
        ['Niantic.Holoholo.Quests','QuestRpcService','rpc'],
        ['Niantic.Holoholo.Quests','QuestService','svc'],
        ['Niantic.Holoholo.Quests','QuestAutoCompleteService','autoc'],
    ];
    for (var p = 0; p < pairs.length; p++) {
        var cls = cFN(gi, Memory.allocUtf8String(pairs[p][0]), Memory.allocUtf8String(pairs[p][1]));
        if (!cls || cls.isNull()) continue;
        var label = pairs[p][2];
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                (function(lbl) {
                    Interceptor.attach(addr, {
                        onEnter: function(args) {
                            if (!instances[lbl]) {
                                instances[lbl] = args[0].toString();
                                send({type:'h', msg:lbl+' '+instances[lbl]});
                            }
                        }
                    });
                })(label);
            } catch(e) {}
        }
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return instances; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 240s for Quest service hooks (open Today + a quest)...")
got = None
for i in range(240):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('rpc') and g.get('svc'):
        got = g; break
    if i % 30 == 29: print(f"  [{i+1}s] captured: {list(g.keys())}")
got = got or hs.exports_sync.get()
print(f"\nCaptured: {got}")
if not got.get('rpc'):
    print("No QuestRpcService captured. Need user to open quest UI / claim something.")
    sess.detach(); exit(1)
hs.unload()

js = """
rpc.exports = {
    tryAutoComplete: function(autocAddr) {
        var inst = ptr(autocAddr);
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
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestAutoCompleteService'));
        var m = cMN(cls, Memory.allocUtf8String('CompleteQueuedQuests'), 0);
        if (!m || m.isNull()) return {error:'no method'};
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var ret = rI(m, inst, ptr(0), ex);
        return {ret: ret.toString(), exception: ex.readPointer().toString()};
    },

    tryUpdateDetails: function(rpcAddr, questId) {
        var inst = ptr(rpcAddr);
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
        var objNew = new NativeFunction(addrs['il2cpp_object_new'],'pointer',['pointer']);
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null, mscorlib = null;
        for (var a=0;a<na;a++){
            var i=aGI(asms.add(a*Process.pointerSize).readPointer());
            var n = iGN(i).readCString();
            if (n==='holo-game.dll'){ gi=i; }
            if (n==='mscorlib.dll'){ mscorlib=i; }
        }
        var rpcCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestRpcService'));
        var m = cMN(rpcCls, Memory.allocUtf8String('UpdateQuestDetails'), 1);
        if (!m || m.isNull()) return {error:'no method'};

        // Build a List<string> with the questId
        var listCls = cFN(mscorlib, Memory.allocUtf8String('System.Collections.Generic'), Memory.allocUtf8String('List`1'));
        // Generic list construction is tricky; use Single<T> via enumerable
        // Simpler: use string[] (single elem)
        // Allocate object array and put string in it
        var arrayNewSpec = new NativeFunction(addrs['il2cpp_array_new_specific'],'pointer',['pointer','uint32']);
        var stringTd = new NativeFunction(addrs['il2cpp_class_get_type'],'pointer',['pointer']);
        // Get System.String class
        var strCls = cFN(mscorlib, Memory.allocUtf8String('System'), Memory.allocUtf8String('String'));
        if (!strCls || strCls.isNull()) return {error:'string class'};
        // Get string array class via il2cpp_array_class_get
        var arrayClassGet = new NativeFunction(addrs['il2cpp_array_class_get'],'pointer',['pointer','uint32']);
        var strArrCls = arrayClassGet(strCls, 1);
        var strArr = arrayNewSpec(strArrCls, 1);
        if (strArr.isNull()) return {error:'array alloc'};
        var qStr = stringNew(Memory.allocUtf8String(questId));
        // Array data starts at +0x20
        strArr.add(0x20).writePointer(qStr);

        var argsArr = Memory.alloc(Process.pointerSize);
        argsArr.writePointer(strArr);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var ret = rI(m, inst, argsArr, ex);
        var excPtr = ex.readPointer();
        return {ret: ret ? ret.toString() : 'null', exception: excPtr.toString()};
    },

    tryCompleteQuest: function(rpcAddr, questId, subQuestId) {
        var inst = ptr(rpcAddr);
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
        var rpcCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestRpcService'));
        var m = cMN(rpcCls, Memory.allocUtf8String('CompleteQuest'), 4);
        if (!m || m.isNull()) return {error:'no method'};

        // questId (string), subQuestId (string), choiceId (Nullable<int>), pokemonId (uint64)
        var qStr = stringNew(Memory.allocUtf8String(questId));
        var sqStr = stringNew(Memory.allocUtf8String(subQuestId || ''));
        // Nullable<int>: 8 bytes value + 1 byte hasValue (8 byte aligned = 12 bytes total in struct)
        // For runtime_invoke, pass pointer to the struct
        var nullableBuf = Memory.alloc(8);  // Value (4) + HasValue (1) padded
        nullableBuf.writeS32(0);
        nullableBuf.add(4).writeU8(0);  // HasValue = false
        var pokeIdBuf = Memory.alloc(8);
        pokeIdBuf.writeU64(0);

        var argsArr = Memory.alloc(4 * Process.pointerSize);
        argsArr.writePointer(qStr);
        argsArr.add(8).writePointer(sqStr);
        argsArr.add(16).writePointer(nullableBuf);
        argsArr.add(24).writePointer(pokeIdBuf);

        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var ret = rI(m, inst, argsArr, ex);
        var excPtr = ex.readPointer();
        return {ret: ret ? ret.toString() : 'null', exception: excPtr.toString()};
    }
};
"""
script = sess.create_script(js)
script.load()

QID = 'STORY_QUEST_WAINA23_1'
print(f"\n=== STEP 1: CompleteQueuedQuests (safest auto-claim) ===")
if got.get('autoc'):
    r = script.exports_sync.try_auto_complete(got['autoc'])
    print(f"  result: {r}")
else:
    print("  (no QuestAutoCompleteService instance captured; skipping)")

print(f"\n=== STEP 2: UpdateQuestDetails for {QID} (force server resync) ===")
r = script.exports_sync.try_update_details(got['rpc'], QID)
print(f"  result: {r}")

# Wait for server response, then re-check status
time.sleep(3)

# Don't auto-run CompleteQuest yet - that's destructive in nature. Show user the state first.
print(f"\n=== STEP 3 (NOT YET RUN): CompleteQuest for {QID} ===")
print(f"  This will send CompleteQuest RPC to server.")
print(f"  Server will validate progress and either accept (claim rewards) or reject.")
print(f"  NOT triggering automatically - user must approve.")
sess.detach()
