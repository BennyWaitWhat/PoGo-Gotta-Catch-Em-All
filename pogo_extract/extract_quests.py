"""Extract active quests from QuestService - includes Special Research."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var inst = null;
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
                onEnter: function(args) {
                    if (!inst) { inst = args[0].toString(); send({type:'h', msg:'inst '+inst}); }
                }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {inst: inst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 180s for QuestService hook (open Today / Quests menu in PoGo)...")
inst = None
for i in range(180):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('inst'):
        inst = g['inst']; break
if not inst:
    print("Hook didn't fire. Open Today view or Quest list in PoGo")
    sess.detach(); exit(1)
print(f"QuestService: {inst}")
hs.unload()

js = """
rpc.exports = {
    walkQuests: function(addr) {
        var inst = ptr(addr);
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
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
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));

        function readUtf16Str(p) {
            if (p.isNull()) return '';
            var len = p.add(0x10).readS32();
            if (len <= 0 || len > 500) return '';
            var chars = [];
            for (var i = 0; i < len; i++) {
                var ch = p.add(0x14 + i*2).readU16();
                if (ch === 0) break;
                chars.push(String.fromCharCode(ch));
            }
            return chars.join('');
        }

        // Get QuestsProto
        var getProto = cMN(cls, Memory.allocUtf8String('get_QuestsProto'), 0);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var protoObj = rI(getProto, inst, ptr(0), exc);
        if (protoObj.isNull()) return {error:'null'};

        function walkRepeated(rfPtr, isString) {
            if (rfPtr.isNull()) return [];
            var arr = rfPtr.add(0x10).readPointer();
            var count = rfPtr.add(0x18).readS32();
            if (arr.isNull() || count <= 0) return [];
            var maxLen = arr.add(0x18).readS32();
            var data = arr.add(0x20);
            var items = [];
            for (var i = 0; i < Math.min(count, maxLen, 1000); i++) {
                var p = data.add(i * 8).readPointer();
                if (isString) items.push(readUtf16Str(p));
                else items.push(p);
            }
            return items;
        }

        // Active quests RepeatedField<QuestProto> at +0x10
        var activeRf = protoObj.add(0x10).readPointer();
        var activePtrs = walkRepeated(activeRf, false);
        // Completed story quest IDs RepeatedField<String> at +0x18
        var completedRf = protoObj.add(0x18).readPointer();
        var completedIds = walkRepeated(completedRf, true);

        var active = [];
        for (var i = 0; i < activePtrs.length; i++) {
            var quest = activePtrs[i];
            if (quest.isNull()) continue;
            var rec = {
                questType: quest.add(0x10).readS32(),
                questId: readUtf16Str(quest.add(0x28).readPointer()),
                templateId: readUtf16Str(quest.add(0x40).readPointer()),
                progress: quest.add(0x48).readS32(),
                status: quest.add(0x58).readS32(),
                createdMs: quest.add(0x68).readS64().toString(),
                lastUpdateMs: quest.add(0x70).readS64().toString(),
                completionMs: quest.add(0x78).readS64().toString(),
                endMs: quest.add(0xb0).readS64().toString(),
            };
            // Goal target
            var goal = quest.add(0x50).readPointer();
            if (!goal.isNull()) {
                try { rec.goalTarget = goal.add(0x18).readS32(); } catch(e) {}
            }
            active.push(rec);
        }
        return {active: active, completedStoryIds: completedIds};

        var results = [];
        var n = Math.min(size, maxLen, 200);
        for (var i = 0; i < n; i++) {
            var cqProto = data.add(i * 8).readPointer();
            if (cqProto.isNull()) continue;
            // ClientQuestProto: +0x10 Quest (QuestProto), +0x18 QuestDisplay (QuestDisplayProto)
            var quest = cqProto.add(0x10).readPointer();
            var display = cqProto.add(0x18).readPointer();
            if (quest.isNull()) continue;

            var rec = {};
            rec.questType = quest.add(0x10).readS32();
            rec.questId = readUtf16Str(quest.add(0x28).readPointer());
            rec.templateId = readUtf16Str(quest.add(0x40).readPointer());
            rec.progress = quest.add(0x48).readS32();
            rec.status = quest.add(0x58).readS32();
            rec.createdMs = quest.add(0x68).readS64().toString();
            rec.lastUpdateMs = quest.add(0x70).readS64().toString();
            rec.completionMs = quest.add(0x78).readS64().toString();
            rec.endMs = quest.add(0xb0).readS64().toString();

            // Goal proto at +0x50 - has currentValue and goalValue
            var goal = quest.add(0x50).readPointer();
            if (!goal.isNull()) {
                try {
                    // QuestGoalProto fields tbd; will probe later
                    rec.goalPtr = goal.toString();
                } catch(e) {}
            }

            if (!display.isNull()) {
                rec.title = readUtf16Str(display.add(0x28).readPointer());
                rec.description = readUtf16Str(display.add(0x20).readPointer());
                rec.slot = display.add(0x30).readS32();
                rec.iconName = readUtf16Str(display.add(0x70).readPointer());
                // SubquestDisplays at +0x38
                try {
                    var sub = display.add(0x38).readPointer();
                    if (!sub.isNull()) {
                        var subItems = sub.add(0x10).readPointer();
                        var subSize = sub.add(0x18).readS32();
                        if (!subItems.isNull() && subSize > 0) {
                            var subList = [];
                            var subData = subItems.add(0x20);
                            var subMax = subItems.add(0x18).readS32();
                            for (var s = 0; s < Math.min(subSize, subMax, 20); s++) {
                                var sd = subData.add(s * 8).readPointer();
                                if (sd.isNull()) continue;
                                subList.push({
                                    title: readUtf16Str(sd.add(0x28).readPointer()),
                                    desc: readUtf16Str(sd.add(0x20).readPointer())
                                });
                            }
                            rec.subQuests = subList;
                        }
                    }
                } catch(e) { rec.subErr = e.toString(); }
            }
            results.push(rec);
        }
        return {size: size, walked: results.length, quests: results};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.walk_quests(inst)
if 'error' in r:
    print(f"ERROR: {r}"); sess.detach(); exit(1)
active = r['active']
completed = r['completedStoryIds']
print(f"\nActive quests: {len(active)}")
print(f"Completed story quest IDs: {len(completed)}")

QUEST_TYPE = {
    0:'UNSET', 1:'FIRST_CATCH', 2:'CATCH', 3:'CATCH_NEW', 4:'CATCH_TYPE',
    5:'COMPLETE_BATTLE', 7:'PLAYER_LEVEL', 8:'COMPLETE_QUEST', 9:'TRANSFER_POKEMON',
    10:'FAVORITE_POKEMON', 11:'AUTO_COMPLETE', 12:'FIRST_POKESTOP_OF_THE_DAY',
    13:'FIRST_CATCH_OF_THE_DAY', 14:'GET_BUDDY_CANDY', 15:'BADGE_RANK',
    16:'PLAYER_QUEST', 17:'MULTI_PART', 18:'EVOLVE_POKEMON', 19:'LAND_THROW',
    20:'EARN_BADGE', 21:'STORY_QUEST', 22:'CHALLENGE_QUEST',
    33:'TIMED_QUEST', 34:'TIMED_BRANCHING_QUEST',
}
STATUS = {0:'UNSET',1:'ACTIVE',2:'COMPLETED',3:'CLAIMED',4:'EXPIRED'}

import json as jsmod
from datetime import datetime, timezone
def fmt_ts(ms):
    try:
        x = int(ms)
        if x <= 0: return '-'
        return datetime.fromtimestamp(x/1000, tz=timezone.utc).strftime('%Y-%m-%d')
    except: return '?'

print("\n=== ACTIVE QUESTS ===")
print(f"{'Type':<22} {'Status':<10} {'TemplateId':<55} {'Progress':<12} {'Updated'}")
print('-'*120)
for q in active:
    qt = QUEST_TYPE.get(q['questType'], f"T{q['questType']}")
    st = STATUS.get(q['status'], f"S{q['status']}")
    tid = q.get('templateId','')[:53]
    progress = f"{q.get('progress',0)}/{q.get('goalTarget','?')}"
    print(f"{qt:<22} {st:<10} {tid:<55} {progress:<12} {fmt_ts(q['lastUpdateMs'])}")

print("\n=== COMPLETED STORY QUEST TEMPLATE IDS (sample) ===")
# Group completed IDs by prefix to summarize
from collections import Counter
prefix_count = Counter()
for cid in completed:
    parts = cid.split('-')
    if len(parts) >= 3:
        prefix = '-'.join(parts[:-1])  # everything except step number
    else:
        prefix = cid
    prefix_count[prefix] += 1
print(f"{'Story':<70} {'#Steps'}")
for prefix, n in sorted(prefix_count.items(), key=lambda x:-x[1])[:50]:
    print(f"  {prefix[:67]:<70} {n}")

with open('quests_dump.json','w') as f: jsmod.dump(r, f, indent=2)
print(f"\nSaved to quests_dump.json")
sess.detach()
