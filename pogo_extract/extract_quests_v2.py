"""V2: Get active quests with proper TITLES via GetQuestDisplayProto(questId)."""
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
print("Waiting for QuestService hook (open Today view)...")
inst = None
for i in range(180):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('inst'):
        inst = g['inst']; break
if not inst:
    inst = '0x77e0309700'  # cached
    print(f"Using cached {inst}")
print(f"QuestService: {inst}")
hs.unload()

js = """
rpc.exports = {
    walkAll: function(addr) {
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
            if (len <= 0 || len > 1000) return '';
            var chars = [];
            for (var i = 0; i < len; i++) {
                var ch = p.add(0x14 + i*2).readU16();
                if (ch === 0) break;
                chars.push(String.fromCharCode(ch));
            }
            return chars.join('');
        }

        function makeStrObj(s) {
            // Use Frida API to allocate a managed System.String
            return Memory.allocUtf8String(s);
        }

        // Get the proto + active quests
        var getProto = cMN(cls, Memory.allocUtf8String('get_QuestsProto'), 0);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var protoObj = rI(getProto, inst, ptr(0), exc);
        if (protoObj.isNull()) return {error:'null proto'};

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

        var activeRf = protoObj.add(0x10).readPointer();
        var activePtrs = walkRepeated(activeRf, false);
        var completedRf = protoObj.add(0x18).readPointer();
        var completedIds = walkRepeated(completedRf, true);

        // For each active quest, also try to find display via GetQuestDisplayProto(questId)
        var getDisplay = cMN(cls, Memory.allocUtf8String('GetQuestDisplayProto'), 1);

        // Helper to call GetQuestDisplayProto with a managed System.String
        // il2cpp_string_new creates a managed string
        var stringNew = new NativeFunction(addrs['il2cpp_string_new'], 'pointer', ['pointer']);

        var results = [];
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
                fortId: readUtf16Str(quest.add(0x80).readPointer()),
            };
            var goal = quest.add(0x50).readPointer();
            if (!goal.isNull()) {
                try { rec.goalTarget = goal.add(0x18).readS32(); } catch(e) {}
            }

            // Attempt to call GetQuestDisplayProto(questId)
            if (!getDisplay.isNull() && rec.questId) {
                try {
                    var qidStr = stringNew(Memory.allocUtf8String(rec.questId));
                    var argsArr = Memory.alloc(Process.pointerSize);
                    argsArr.writePointer(qidStr);
                    var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
                    var disp = rI(getDisplay, inst, argsArr, ex);
                    if (!disp.isNull()) {
                        rec.title = readUtf16Str(disp.add(0x28).readPointer());
                        rec.description = readUtf16Str(disp.add(0x20).readPointer());
                        rec.slot = disp.add(0x30).readS32();
                        rec.iconName = readUtf16Str(disp.add(0x70).readPointer());
                        rec.tagString = readUtf16Str(disp.add(0x58).readPointer());
                        rec.storyEnd = disp.add(0x40).readU8();
                        rec.storyEndDesc = readUtf16Str(disp.add(0x48).readPointer());
                        rec.sortOrder = disp.add(0xd8).readS32();
                        // Subquests at +0x38
                        try {
                            var subRf = disp.add(0x38).readPointer();
                            if (!subRf.isNull()) {
                                var subArr = subRf.add(0x10).readPointer();
                                var subCount = subRf.add(0x18).readS32();
                                if (!subArr.isNull() && subCount > 0) {
                                    var subData = subArr.add(0x20);
                                    var subList = [];
                                    for (var s = 0; s < Math.min(subCount, 20); s++) {
                                        var sd = subData.add(s * 8).readPointer();
                                        if (sd.isNull()) continue;
                                        subList.push({
                                            title: readUtf16Str(sd.add(0x28).readPointer()),
                                            desc: readUtf16Str(sd.add(0x20).readPointer())
                                        });
                                    }
                                    rec.subTasks = subList;
                                }
                            }
                        } catch(e) {}
                    }
                } catch(e) { rec.dispErr = e.toString(); }
            }
            results.push(rec);
        }
        return {active: results, completedIds: completedIds};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.walk_all(inst)
if 'error' in r:
    print(f"ERROR: {r}"); sess.detach(); exit(1)

print(f"\nActive: {len(r['active'])}, completed history: {len(r['completedIds'])}")

QSTAT = {0:'UNSET',1:'ACTIVE',2:'COMPLETED',3:'CLAIMED',4:'EXPIRED',5:'EXPIRED?'}
import json as jsmod
from datetime import datetime, timezone
def fmt_ts(ms):
    try:
        x = int(ms)
        if x <= 0: return '-'
        return datetime.fromtimestamp(x/1000, tz=timezone.utc).strftime('%Y-%m-%d')
    except: return '?'

print("\n=== ACTIVE QUESTS WITH TITLES ===")
for q in r['active']:
    st = QSTAT.get(q['status'], f"S{q['status']}")
    title = q.get('title','').strip() or '(no title)'
    desc = q.get('description','').strip()
    tag = q.get('tagString','').strip()
    print(f"\n[{st}] slot={q.get('slot','?')}  template={q['templateId']}")
    print(f"  Title: {title}")
    if tag: print(f"  Tag: {tag}")
    if desc: print(f"  Desc: {desc[:200]}")
    if q.get('progress',0) or q.get('goalTarget',0):
        print(f"  Progress: {q.get('progress',0)}/{q.get('goalTarget','?')}")
    print(f"  Updated: {fmt_ts(q['lastUpdateMs'])}  Created: {fmt_ts(q['createdMs'])}")
    if q.get('subTasks'):
        for s in q['subTasks']:
            print(f"    - {s.get('title','')[:80]}  ({s.get('desc','')[:80]})")

# Search WAINA / Z / sleep
print("\n=== Searching completed for WAINA / Z's / Sleep ===")
hits = [c for c in r['completedIds'] if any(k in c.upper() for k in ('WAINA','ZZZ','SLEEP','SOME_Z','CATCHING_SOME','SNORLAX'))]
for h in hits: print(f"  {h}")

with open('quests_v2_dump.json','w') as f: jsmod.dump(r, f, indent=2)
print(f"\nSaved.")
sess.detach()
