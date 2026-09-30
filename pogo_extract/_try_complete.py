"""Try CompleteQuest RPC for stuck WAINA23_1."""
import frida, subprocess, time
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook to capture RPC service
hook_js = """
var rpcInst = null;
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
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestRpcService'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) { if (!rpcInst) { rpcInst = args[0].toString(); send({type:'h', msg:"rpc "+rpcInst}); } }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {rpc: rpcInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 120s for QuestRpcService hook...")
inst = '0x7508f4c510'  # cached fallback
for i in range(120):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('rpc'): inst = g['rpc']; break
print(f"RPC: {inst}")
hs.unload()

js = """
rpc.exports = {
    cq: function(addr, qid, subQid) {
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
        var sqStr = stringNew(Memory.allocUtf8String(subQid));
        var nullableBuf = Memory.alloc(8); nullableBuf.writeS32(0); nullableBuf.add(4).writeU8(0);
        var pid = Memory.alloc(8); pid.writeU64(0);
        var args = Memory.alloc(4 * Process.pointerSize);
        args.writePointer(qStr);
        args.add(8).writePointer(sqStr);
        args.add(16).writePointer(nullableBuf);
        args.add(24).writePointer(pid);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var ret = rI(m, inst, args, ex);
        var excPtr = ex.readPointer();
        var excClass = '?';
        if (!excPtr.isNull()) {
            try {
                var exObj = excPtr;
                var klass = exObj.readPointer();
                // klass+0x10 -> name
                var nm = klass.add(0x10).readPointer();
                if (!nm.isNull()) excClass = nm.readCString();
            } catch(e) {}
        }
        return {ret: ret ? ret.toString() : 'null', exception: excPtr.toString(), excClass: excClass};
    }
};
"""
sc = sess.create_script(js); sc.load()
QID = 'STORY_QUEST_WAINA23_1'

print(f"\n=== Trying CompleteQuest({QID}, subQuestId='') ===")
r = sc.exports_sync.cq(inst, QID, '')
print(f"  {r}")

# Try various sub-quest ID patterns
for sq in ['STORY_QUEST_WAINA23_1_0','STORY_QUEST_WAINA23_1_1','0','1']:
    print(f"\n=== Trying CompleteQuest({QID}, subQuestId='{sq}') ===")
    r = sc.exports_sync.cq(inst, QID, sq)
    print(f"  {r}")
sess.detach()
