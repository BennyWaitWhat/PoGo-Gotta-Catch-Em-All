"""V3: Active quests with translated titles + WAINA/sleep search."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

hook_js = """
var quest = null, i18n = null;
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
        ['Niantic.Holoholo.Quests','QuestService','q'],
        ['Niantic.Holoholo.Internationalization','I18n','i'],
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
                            if (lbl === 'q' && !quest) { quest = args[0].toString(); send({type:'h', msg:'quest '+quest}); }
                            if (lbl === 'i' && !i18n) { i18n = args[0].toString(); send({type:'h', msg:'i18n '+i18n}); }
                        }
                    });
                })(label);
            } catch(e) {}
        }
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {q:quest, i:i18n}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
hs.exports_sync.setup()
print("Waiting up to 240s for hooks (open Today + a quest)...")
quest_inst = i18n_inst = None
for i in range(240):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('q'): quest_inst = g['q']
    if g.get('i'): i18n_inst = g['i']
    if quest_inst and i18n_inst: break
print(f"Quest: {quest_inst}, I18n: {i18n_inst}")
if not quest_inst or not i18n_inst:
    print("Couldn't get both. Need user to interact more.")
    sess.detach(); exit(1)
hs.unload()

js = """
rpc.exports = {
    walk: function(qAddr, iAddr) {
        var qInst = ptr(qAddr);
        var iInst = ptr(iAddr);
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
        var stringNew = new NativeFunction(addrs['il2cpp_string_new'], 'pointer', ['pointer']);

        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var qsCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Quests'), Memory.allocUtf8String('QuestService'));
        var i18nCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internationalization'), Memory.allocUtf8String('I18n'));

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

        function translate(key) {
            if (!key) return '';
            try {
                var textM = cMN(i18nCls, Memory.allocUtf8String('Text'), 1);
                if (!textM || textM.isNull()) return key;
                var keyStr = stringNew(Memory.allocUtf8String(key));
                var args = Memory.alloc(Process.pointerSize); args.writePointer(keyStr);
                var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
                var ret = rI(textM, iInst, args, ex);
                if (ret.isNull()) return key;
                return readUtf16Str(ret) || key;
            } catch(e) { return key + ' [err]'; }
        }

        var getProto = cMN(qsCls, Memory.allocUtf8String('get_QuestsProto'), 0);
        var ex = Memory.alloc(Process.pointerSize); ex.writePointer(ptr(0));
        var protoObj = rI(getProto, qInst, ptr(0), ex);
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

        var activePtrs = walkRepeated(protoObj.add(0x10).readPointer(), false);
        var completedIds = walkRepeated(protoObj.add(0x18).readPointer(), true);

        var getDisplay = cMN(qsCls, Memory.allocUtf8String('GetQuestDisplayProto'), 1);

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
            };
            var goal = quest.add(0x50).readPointer();
            if (!goal.isNull()) try { rec.goalTarget = goal.add(0x18).readS32(); } catch(e) {}

            // Display
            try {
                var qidStr = stringNew(Memory.allocUtf8String(rec.questId));
                var args = Memory.alloc(Process.pointerSize); args.writePointer(qidStr);
                var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
                var disp = rI(getDisplay, qInst, args, ex2);
                if (!disp.isNull()) {
                    var titleKey = readUtf16Str(disp.add(0x28).readPointer());
                    var descKey = readUtf16Str(disp.add(0x20).readPointer());
                    rec.titleKey = titleKey;
                    rec.title = translate(titleKey);
                    rec.descKey = descKey;
                    rec.description = translate(descKey);
                    rec.tagString = translate(readUtf16Str(disp.add(0x58).readPointer()));
                    rec.iconName = readUtf16Str(disp.add(0x70).readPointer());
                    var subRf = disp.add(0x38).readPointer();
                    if (!subRf.isNull()) {
                        var subArr = subRf.add(0x10).readPointer();
                        var subCount = subRf.add(0x18).readS32();
                        if (!subArr.isNull() && subCount > 0) {
                            var subList = [];
                            var subData = subArr.add(0x20);
                            for (var s = 0; s < Math.min(subCount, 20); s++) {
                                var sd = subData.add(s * 8).readPointer();
                                if (sd.isNull()) continue;
                                subList.push({
                                    title: translate(readUtf16Str(sd.add(0x28).readPointer())),
                                    desc: translate(readUtf16Str(sd.add(0x20).readPointer()))
                                });
                            }
                            rec.subTasks = subList;
                        }
                    }
                }
            } catch(e) { rec.dispErr = e.toString(); }
            results.push(rec);
        }
        return {active: results, completedIds: completedIds};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.walk(quest_inst, i18n_inst)
if 'error' in r: print(f"ERROR: {r}"); sess.detach(); exit(1)

QSTAT = {0:'UNSET',1:'ACTIVE',2:'COMPLETE',3:'EXPIRED',4:'TARGETS_MET'}
import json as jsmod
from datetime import datetime, timezone
def fmt_ts(ms):
    try:
        x = int(ms)
        if x <= 0: return '-'
        return datetime.fromtimestamp(x/1000, tz=timezone.utc).strftime('%Y-%m-%d')
    except: return '?'

print("\n========== ACTIVE QUESTS (with translated names) ==========")
for q in r['active']:
    st = QSTAT.get(q['status'], f"S{q['status']}")
    title = q.get('title','').strip() or '(none)'
    print(f"\n[{st}] {q['templateId']}")
    print(f"  Title: {title}")
    if q.get('description'): print(f"  Desc:  {q['description'][:200]}")
    if q.get('progress',0) or q.get('goalTarget',0):
        print(f"  Progress: {q.get('progress',0)}/{q.get('goalTarget','?')}")
    print(f"  Created: {fmt_ts(q['createdMs'])} / Last update: {fmt_ts(q['lastUpdateMs'])} / Ends: {fmt_ts(q['endMs'])}")
    if q.get('subTasks'):
        for s in q['subTasks']:
            print(f"    - {s.get('title','')[:80]}")
            if s.get('desc') and s['desc'] != s.get('title'):
                print(f"      ({s['desc'][:100]})")

print("\n========== Searching completed for sleep / Z's / WAINA ==========")
hits = [c for c in r['completedIds'] if any(k in c.upper() for k in ('WAINA','SLEEP','SOME_Z','ZZZ','SNORLAX'))]
for h in hits: print(f"  {h}")

with open('quests_v3_dump.json','w') as f: jsmod.dump(r, f, indent=2)
print(f"\nSaved.")
sess.detach()
