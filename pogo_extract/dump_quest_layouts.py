"""STEP 0 (run this FIRST, once): dump authoritative IL2CPP field layouts for every
quest-related proto class in holo-protos.dll + the QuestService / QuestRpcService /
I18n surfaces in holo-game.dll.

This is the FOUNDATION for dump_research_full.py. The string-only metadata blob is
obfuscated and deduplicated, so field ORDER (=> offsets) cannot be trusted from it.
This script reflects the live runtime (il2cpp_class_get_fields / _field_get_offset /
_type_get_name) and writes the real offsets.

READ-ONLY. Invokes no game logic, only reflection. Writes JSON + MD locally.

Usage:
    python dump_quest_layouts.py

Outputs (next to this file):
    quest_layouts.json   {fqcn: {namespace,name,instSize,fields:[{name,type,offset,is_static}]}}
    quest_layouts.md     human-readable, sorted by instSize desc

After running, open quest_layouts.md and copy the real offsets into the OFF_* dicts
at the top of dump_research_full.py (they are pre-filled with the best static guesses,
each flagged `# VALIDATE`).
"""
import json, os, time
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, 'quest_layouts.json')
OUT_MD = os.path.join(HERE, 'quest_layouts.md')

# Substring match on class name. Broad on purpose.
PROTO_FILTERS = [
    'QuestProto', 'QuestsProto', 'ClientQuestProto', 'QuestGoalProto',
    'QuestRewardProto', 'QuestConditionProto', 'QuestDisplayProto',
    'MultiPartQuestProto', 'QuestEncounterProto', 'QuestPokemonEncounterProto',
    'QuestSettingsProto', 'QuestBranchRewardProto', 'QuestStampProto',
    'QuestStampCardProto', 'SubquestDisplay', 'QuestHeaderDisplay',
    'ItemRewardProto', 'PokemonEncounterRewardProto', 'PokemonCandyRewardProto',
    'StardustRewardProto', 'PokemonEggRewardProto', 'LootTableRewardProto',
    'MegaResourceProto', 'PokemonIndividualStatRewardProto',
    # concrete quest-by-type payloads (each carries its own goal/condition shape):
    'CatchPokemonQuestProto', 'SpinPokestopQuestProto', 'EvolveIntoPokemonQuestProto',
    'GetStardustQuestProto', 'BattleQuestProto', 'TakeSnapshotQuestProto',
    'TravelRouteQuestProto', 'AddFriendQuestProto', 'TradePokemonQuestProto',
    'DailyBuddyAffectionQuestProto', 'SubmitSleepRecordsQuestProto',
    'BuddyEvolutionWalkQuestProto', 'PokemonReachCpQuestProto', 'SpendStardustQuestProto',
    'DaysWithARowQuestProto', 'DailyQuestProto',
]

# holo-game.dll service classes to dump (ns, class)
GAME_CLASSES = [
    ('Niantic.Holoholo.Quests', 'QuestService'),
    ('Niantic.Holoholo.Internationalization', 'I18n'),
]

JS = r"""
rpc.exports.dumpProtoLayouts = function(nameFilters) {
    _ensureInit();
    var exp = {};
    Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){
        if (e.name.indexOf('il2cpp_') === 0) exp[e.name] = e.address;
    });
    function bind(n, ret, args) { return exp[n] ? new NativeFunction(exp[n], ret, args) : null; }
    var iGCC = bind('il2cpp_image_get_class_count', 'int', ['pointer']);
    var iGC  = bind('il2cpp_image_get_class', 'pointer', ['pointer', 'int']);
    var cN   = bind('il2cpp_class_get_name', 'pointer', ['pointer']);
    var cNS  = bind('il2cpp_class_get_namespace', 'pointer', ['pointer']);
    var cIS  = bind('il2cpp_class_instance_size', 'int', ['pointer']);
    var cGF  = bind('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']);
    var fGN  = bind('il2cpp_field_get_name', 'pointer', ['pointer']);
    var fGO  = bind('il2cpp_field_get_offset', 'int', ['pointer']);
    var fGT  = bind('il2cpp_field_get_type', 'pointer', ['pointer']);
    var tGN  = bind('il2cpp_type_get_name', 'pointer', ['pointer']);
    var tAttr= bind('il2cpp_type_get_attrs', 'int', ['pointer']);
    var freeFn = bind('il2cpp_free', 'void', ['pointer']);

    function dumpImageClasses(img, matchFn) {
        var n = iGCC(img); var out = {};
        for (var i = 0; i < n; i++) {
            var k = iGC(img, i); if (k.isNull()) continue;
            var nm = cN(k).readCString(); if (!nm) continue;
            if (!matchFn(nm)) continue;
            var nsPtr = cNS(k); var ns = nsPtr.isNull() ? '' : nsPtr.readCString();
            var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
            var fields = [], f;
            while ((f = cGF(k, iter)) && !f.isNull()) {
                var name = fGN(f).readCString();
                var off = fGO(f);
                var typ = fGT(f); var tnPtr = tGN(typ);
                var typeName = tnPtr.readCString();
                try { if (freeFn) freeFn(tnPtr); } catch(e) {}
                var isStatic = ((tAttr ? tAttr(typ) : 0) & 0x10) !== 0;
                fields.push({name: name, type: typeName, offset: off, is_static: isStatic});
            }
            var key = ns ? (ns + '.' + nm) : nm;
            out[key] = {namespace: ns, name: nm, instSize: cIS(k), fields: fields};
        }
        return out;
    }

    var sp = Memory.alloc(4); var asms = IL2.dGA(IL2.dG(), sp); var na = sp.readS32();
    var protoImg = null, gameImg = null;
    for (var a = 0; a < na; a++) {
        var im = IL2.aGI(asms.add(a*Process.pointerSize).readPointer());
        var nm = IL2.iGN(im).readCString();
        if (nm === 'holo-protos.dll') protoImg = im;
        if (nm === 'holo-game.dll')   gameImg = im;
    }
    if (!protoImg) return {err: 'holo-protos.dll not found'};

    var result = dumpImageClasses(protoImg, function(nm){
        for (var fi = 0; fi < nameFilters.length; fi++)
            if (nm.indexOf(nameFilters[fi]) >= 0) return true;
        return false;
    });
    // also pull the two game-dll service classes (methods listed separately below)
    if (gameImg) {
        var svc = dumpImageClasses(gameImg, function(nm){
            return nm === 'QuestService' || nm === 'I18n';
        });
        for (var k in svc) result[k] = svc[k];
    }
    return result;
};

// Enumerate method names + param counts for a (ns, class) in holo-game.dll, so we
// can see the exact GetQuestDisplayProto / GetPokemonEncounterForQuest signatures.
rpc.exports.dumpMethods = function(ns, cls) {
    _ensureInit();
    var exp = {};
    Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function(e){
        if (e.name.indexOf('il2cpp_') === 0) exp[e.name] = e.address;
    });
    function bind(n, ret, args) { return exp[n] ? new NativeFunction(exp[n], ret, args) : null; }
    var cGM = bind('il2cpp_class_get_methods', 'pointer', ['pointer','pointer']);
    var mGN = bind('il2cpp_method_get_name', 'pointer', ['pointer']);
    var mGPC= bind('il2cpp_method_get_param_count', 'uint32', ['pointer']);
    var mGRT= bind('il2cpp_method_get_return_type', 'pointer', ['pointer']);
    var mGP = bind('il2cpp_method_get_param', 'pointer', ['pointer','uint32']);
    var tGN = bind('il2cpp_type_get_name', 'pointer', ['pointer']);
    var freeFn = bind('il2cpp_free', 'void', ['pointer']);
    var klass = cFN(ns, cls);
    if (!klass || klass.isNull()) return {err: 'class not found ' + ns + '.' + cls};
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, out = [];
    function tname(t){ if(!t||t.isNull()) return '?'; var p=tGN(t); var s=p.readCString(); try{if(freeFn)freeFn(p);}catch(e){} return s; }
    while ((m = cGM(klass, iter)) && !m.isNull()) {
        var nm = mGN(m).readCString();
        var pc = mGPC(m);
        var params = [];
        for (var i = 0; i < pc; i++) { try { params.push(tname(mGP(m, i))); } catch(e) { params.push('?'); } }
        out.push({name: nm, ret: tname(mGRT(m)), params: params});
    }
    return out;
};
"""


def main():
    print('Attaching (read-only reflection)...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')
    try:
        script = pg.get_script_with_helpers(sess, JS)
        t0 = time.time()
        layouts = script.exports_sync.dump_proto_layouts(PROTO_FILTERS)
        if isinstance(layouts, dict) and 'err' in layouts:
            print('ERROR:', layouts['err']); return
        print(f'  {len(layouts)} classes in {time.time()-t0:.2f}s')

        # method signatures for the load-bearing calls
        methods = {}
        for ns, cls in [
            ('Niantic.Holoholo.Quests', 'QuestService'),
            ('Niantic.Holoholo.Quests', 'QuestRpcService'),
            ('Niantic.Holoholo.Internationalization', 'I18n'),
        ]:
            try:
                methods[f'{ns}.{cls}'] = script.exports_sync.dump_methods(ns, cls)
            except Exception as e:
                methods[f'{ns}.{cls}'] = {'err': str(e)}
        script.unload()
    finally:
        sess.detach()

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump({'layouts': layouts, 'methods': methods}, f, indent=2)
    print('  wrote', OUT_JSON)

    lines = ['# Quest Proto Layouts (authoritative, IL2CPP reflection)\n']
    for key, info in sorted(layouts.items(), key=lambda kv: -kv[1]['instSize']):
        nsf = [f for f in info['fields'] if not f['is_static']]
        lines.append(f'## `{key}` (size {info["instSize"]}, {len(nsf)} instance fields)\n')
        if nsf:
            lines.append('| Offset | Name | Type |')
            lines.append('|---:|---|---|')
            for fld in sorted(nsf, key=lambda f: f['offset']):
                lines.append(f"| 0x{fld['offset']:03x} | `{fld['name']}` | `{fld['type'][:70]}` |")
            lines.append('')
    lines.append('\n# Method signatures\n')
    for cls, ms in methods.items():
        lines.append(f'## `{cls}`\n')
        if isinstance(ms, dict) and 'err' in ms:
            lines.append(f"_{ms['err']}_\n"); continue
        for m in ms:
            if any(k in m['name'] for k in ('Quest', 'Encounter', 'Display', 'Reward',
                                             'Text', 'Description', 'Goal', 'Story', 'Incident')):
                lines.append(f"- `{m['name']}({', '.join(m['params'])}) -> {m['ret']}`")
        lines.append('')
    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('  wrote', OUT_MD)

    print('\n=== key classes ===')
    for key in ['Holoholo.Rpc.QuestProto', 'Holoholo.Rpc.QuestsProto',
                'Holoholo.Rpc.QuestGoalProto', 'Holoholo.Rpc.QuestRewardProto',
                'Holoholo.Rpc.QuestConditionProto', 'Holoholo.Rpc.QuestDisplayProto',
                'Holoholo.Rpc.MultiPartQuestProto', 'Holoholo.Rpc.ClientQuestProto']:
        if key in layouts:
            info = layouts[key]
            nsf = [f for f in info['fields'] if not f['is_static']]
            print(f'  {key}: size={info["instSize"]} fields={len(nsf)}')
        else:
            print(f'  {key}: NOT FOUND (check exact name in quest_layouts.md)')


if __name__ == '__main__':
    main()
