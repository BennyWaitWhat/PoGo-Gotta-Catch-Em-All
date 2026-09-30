"""Walk WAINA23_1 progress +1 at a time in memory. Probe sub-quest structure first."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook QuestService to get instance
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
print("Waiting up to 120s for QuestService hook...")
inst = '0x74c5530380'  # cached fallback
for i in range(120):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('q'): inst = g['q']; break
print(f"QuestService: {inst}")
hs.unload()

js = """
rpc.exports = {
    findWaina: function(addr) {
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
        var protoObj = rI(getProto, inst, ptr(0), ex);
        if (protoObj.isNull()) return {error:'null'};
        var rfPtr = protoObj.add(0x10).readPointer();
        if (rfPtr.isNull()) return {error:'rf null'};
        var arr = rfPtr.add(0x10).readPointer();
        var count = rfPtr.add(0x18).readS32();
        var maxLen = arr.add(0x18).readS32();
        var data = arr.add(0x20);

        for (var i = 0; i < Math.min(count, maxLen, 100); i++) {
            var qp = data.add(i * 8).readPointer();
            if (qp.isNull()) continue;
            var tid = readUtf16Str(qp.add(0x40).readPointer());
            if (tid !== 'STORY_QUEST_WAINA23_1') continue;
            // Found! Probe its full structure
            var probe = {};
            probe.questPtr = qp.toString();
            probe.templateId = tid;
            probe.questType = qp.add(0x10).readS32();
            probe.progress = qp.add(0x48).readS32();
            probe.status = qp.add(0x58).readS32();
            // probe each pointer offset 0x18 - 0xd0 to find sub-data
            var offsets = [0x18,0x20,0x38,0x50];
            probe.fields = {};
            for (var o = 0; o < offsets.length; o++) {
                try {
                    var p = qp.add(offsets[o]).readPointer();
                    var info = {ptr: p.toString()};
                    if (!p.isNull()) {
                        // try reading first 0x40 bytes
                        var bytes = [];
                        for (var b = 0; b < 0x40; b += 8) {
                            try {
                                var pp = p.add(b).readPointer();
                                bytes.push({off:b, val:pp.toString()});
                            } catch(e) { bytes.push({off:b,err:1}); break; }
                        }
                        info.bytes = bytes;
                    }
                    probe.fields['+0x'+offsets[o].toString(16)] = info;
                } catch(e) {}
            }
            // Goal proto
            var goal = qp.add(0x50).readPointer();
            if (!goal.isNull()) {
                probe.goal = {
                    ptr: goal.toString(),
                    target: goal.add(0x18).readS32()
                };
                // Goal Conditions RepeatedField at +0x10
                var cond = goal.add(0x10).readPointer();
                if (!cond.isNull()) {
                    probe.goal.condCount = cond.add(0x18).readS32();
                }
            }
            return probe;
        }
        return {error:'WAINA23_1 not in active list'};
    },

    writeProgress: function(qPtr, val) {
        var p = ptr(qPtr);
        var oldVal = p.add(0x48).readS32();
        p.add(0x48).writeS32(val);
        return {old: oldVal, newVal: p.add(0x48).readS32()};
    },

    writeStatus: function(qPtr, val) {
        var p = ptr(qPtr);
        var oldVal = p.add(0x58).readS32();
        p.add(0x58).writeS32(val);
        return {old: oldVal, newVal: p.add(0x58).readS32()};
    }
};
"""
sc = sess.create_script(js); sc.load()

print("\n=== Probing WAINA23_1 in memory ===")
r = sc.exports_sync.find_waina(inst)
import json as jsmod
print(jsmod.dumps(r, indent=2))

if 'error' in r:
    sess.detach(); exit(1)

qPtr = r['questPtr']
goalTarget = r.get('goal',{}).get('target', 0)
print(f"\n=== Walking progress from {r['progress']} -> {goalTarget}, +1 each step ===")

# Increment progress 1 at a time, with delay between
for i in range(r['progress'] + 1, goalTarget + 1):
    res = sc.exports_sync.write_progress(qPtr, i)
    print(f"  step {i}/{goalTarget}: progress {res['old']} -> {res['newVal']}")
    time.sleep(0.5)

# Set status to Complete
print(f"\n=== Setting status to 2 (Complete) ===")
res = sc.exports_sync.write_status(qPtr, 2)
print(f"  status: {res['old']} -> {res['newVal']}")

# Re-read to confirm
print("\n=== Final state ===")
final = sc.exports_sync.find_waina(inst)
print(jsmod.dumps({'progress': final.get('progress'), 'status': final.get('status'), 'goalTarget': final.get('goal',{}).get('target')}, indent=2))

print("\nNow look at the quest in PoGo UI - if it shows complete, try tapping Claim.")
sess.detach()
