"""Read-only check of WAINA23_1 sub-quest state. Fresh hook, no writes."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var qInst = null;
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
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) { if (!qInst) { qInst = args[0].toString(); send({type:'h', msg:'q '+qInst}); } }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {q: qInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 240s for QuestService hook (open Today / Quests in PoGo)...")
inst = None
for i in range(240):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('q'): inst = g['q']; break
if not inst:
    print("Hook never fired - PoGo needs to be at the Today/Quests screen")
    sess.detach(); exit(1)
print(f"QuestService: {inst}")
hs.unload()

js = """
rpc.exports = {
    read: function(addr) {
        var qsInst = ptr(addr);
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
        var gi = null, hpr = null;
        for (var a=0;a<na;a++){
            var i=aGI(asms.add(a*Process.pointerSize).readPointer());
            var n = iGN(i).readCString();
            if (n==='holo-game.dll') gi=i;
            if (n==='holo-protos.dll') hpr=i;
        }
        var qsCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));
        function readUtf16Str(p) {
            if (p.isNull()) return '';
            var len = p.add(0x10).readS32();
            if (len <= 0 || len > 1000) return '';
            var chars = [];
            for (var i = 0; i < len; i++) {
                var ch = p.add(0x14 + i*2).readU16();
                if (ch === 0) break;
                chars.push(String.fromCharCode(ch));
            }
            return chars.join('');
        }
        var getProto = cMN(qsCls, Memory.allocUtf8String('get_QuestsProto'), 0);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var protoObj = rI(getProto, qsInst, ptr(0), ex);
        if (protoObj.isNull()) return {error:'null'};
        var rfPtr = protoObj.add(0x10).readPointer();
        var arr = rfPtr.add(0x10).readPointer();
        var count = rfPtr.add(0x18).readS32();
        var maxLen = arr.add(0x18).readS32();
        var data = arr.add(0x20);

        var qpFound = null;
        for (var i = 0; i < Math.min(count, maxLen, 100); i++) {
            var qp = data.add(i * 8).readPointer();
            if (qp.isNull()) continue;
            var tid = readUtf16Str(qp.add(0x40).readPointer());
            if (tid === 'STORY_QUEST_WAINA23_1') { qpFound = qp; break; }
        }
        if (!qpFound) return {error:'WAINA23_1 not in active list'};

        var qpCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('QuestProto'));
        var getMP = cMN(qpCls, Memory.allocUtf8String('get_MultiPart'), 0);
        var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
        var mp = rI(getMP, qpFound, ptr(0), ex2);
        if (mp.isNull()) return {error:'multipart null'};
        var subRf = mp.add(0x10).readPointer();
        var subArr = subRf.add(0x10).readPointer();
        var subCount = subRf.add(0x18).readS32();
        var subData = subArr.add(0x20);
        var subs = [];
        for (var s = 0; s < subCount; s++) {
            var sq = subData.add(s * 8).readPointer();
            if (sq.isNull()) continue;
            var goal = sq.add(0x50).readPointer();
            subs.push({
                tid: readUtf16Str(sq.add(0x40).readPointer()),
                progress: sq.add(0x48).readS32(),
                status: sq.add(0x58).readS32(),
                goal: goal.isNull() ? 0 : goal.add(0x18).readS32()
            });
        }
        return {parentStatus: qpFound.add(0x58).readS32(), parentProgress: qpFound.add(0x48).readS32(), subs: subs};
    }
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.read(inst)
import json as jsmod
print(jsmod.dumps(r, indent=2))
sess.detach()
