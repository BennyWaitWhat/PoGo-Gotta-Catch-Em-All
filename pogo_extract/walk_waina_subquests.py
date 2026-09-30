"""Walk WAINA23_1 sub-quest progress one day at a time so each Snorlax claim becomes available."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

QSVC_INST = "0x0"

js = """
rpc.exports = {
    getMultiPart: function(qsAddr) {
        var qsInst = ptr(qsAddr);
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
        if (!qpFound) return {error:'WAINA23_1 not found'};

        // Invoke get_MultiPart() on the QuestProto
        var qpCls = cFN(hpr, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('QuestProto'));
        var getMP = cMN(qpCls, Memory.allocUtf8String('get_MultiPart'), 0);
        if (!getMP || getMP.isNull()) return {error:'no get_MultiPart'};
        var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
        var mp = rI(getMP, qpFound, ptr(0), ex2);
        if (mp.isNull()) return {error:'multipart null', questPtr: qpFound.toString()};

        // mp is MultiPartQuestProto; SubQuests at +0x10 is RepeatedField<QuestProto>
        var subRf = mp.add(0x10).readPointer();
        var subArr = subRf.add(0x10).readPointer();
        var subCount = subRf.add(0x18).readS32();
        var subMaxLen = subArr.add(0x18).readS32();
        var subData = subArr.add(0x20);

        var subs = [];
        for (var s = 0; s < Math.min(subCount, subMaxLen, 50); s++) {
            var sq = subData.add(s * 8).readPointer();
            if (sq.isNull()) continue;
            // Read sub-quest fields
            var rec = {
                ptr: sq.toString(),
                questType: sq.add(0x10).readS32(),
                questId: readUtf16Str(sq.add(0x28).readPointer()),
                templateId: readUtf16Str(sq.add(0x40).readPointer()),
                progress: sq.add(0x48).readS32(),
                status: sq.add(0x58).readS32()
            };
            // Goal
            var goal = sq.add(0x50).readPointer();
            if (!goal.isNull()) {
                rec.goal = {target: goal.add(0x18).readS32()};
            }
            subs.push(rec);
        }
        return {questPtr: qpFound.toString(), multiPartPtr: mp.toString(), subCount: subCount, subs: subs};
    },

    setProgress: function(subPtr, val) {
        var p = ptr(subPtr);
        var old = p.add(0x48).readS32();
        p.add(0x48).writeS32(val);
        return {old: old, newVal: p.add(0x48).readS32()};
    },

    setStatus: function(subPtr, val) {
        var p = ptr(subPtr);
        var old = p.add(0x58).readS32();
        p.add(0x58).writeS32(val);
        return {old: old, newVal: p.add(0x58).readS32()};
    }
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.get_multi_part(QSVC_INST)
import json as jsmod
print(jsmod.dumps(r, indent=2))

if 'error' in r:
    sess.detach(); exit(1)

print(f"\n=== Walking each sub-quest day-by-day to its goal target ===")
for i, sq in enumerate(r['subs']):
    target = sq.get('goal',{}).get('target', 0)
    if target == 0:
        print(f"\nsub {i+1}/{r['subCount']}: {sq['templateId']}  goal=0 (skipping)")
        continue
    print(f"\nsub {i+1}/{r['subCount']}: {sq['templateId']}  current progress={sq['progress']}, target={target}")
    for day in range(sq['progress'] + 1, target + 1):
        res = sc.exports_sync.set_progress(sq['ptr'], day)
        print(f"  day {day}/{target}: progress {res['old']} -> {res['newVal']}")
        time.sleep(0.4)
    # Mark complete
    res = sc.exports_sync.set_status(sq['ptr'], 2)
    print(f"  status: {res['old']} -> {res['newVal']} (Complete)")

# Also re-mark parent status complete
print("\n=== Re-confirming state ===")
r2 = sc.exports_sync.get_multi_part(QSVC_INST)
print(jsmod.dumps([{
    'tid': s['templateId'], 'progress': s['progress'], 'goal': s.get('goal',{}).get('target',0), 'status': s['status']
} for s in r2['subs']], indent=2))

print("\nNow open Catching Some Z's (2/2) in PoGo - each completed sub-quest should be claimable.")
sess.detach()
