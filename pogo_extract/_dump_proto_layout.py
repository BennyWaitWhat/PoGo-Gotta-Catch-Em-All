"""Enumerate every field of every Pokémon-related proto class in holo-protos.dll.

Reflects via IL2CPP exports (il2cpp_image_get_class_count / il2cpp_image_get_class
/ il2cpp_class_get_fields / il2cpp_field_get_offset / il2cpp_type_get_name) to
produce a complete authoritative field map. No guessing offsets.

Outputs:
  proto_layout.json  — {class_name: {ns, instSize, fields:[{name,type,offset,is_static}, ...]}}
  proto_layout.md    — human-readable summary

Targets (substring match on class name):
  PokemonProto, PokemonDisplayProto, PokemonMove, BuddyPokemonProto,
  HoloPokemon, FriendshipProto, OriginalTrainer, CapturedPokemon, etc.
"""
import json, os, sys, time

import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, 'proto_layout.json')
OUT_MD = os.path.join(HERE, 'proto_layout.md')

# Substrings to include when filtering classes. Broad on purpose — discovery.
NAME_FILTERS = [
    'PokemonProto', 'PokemonDisplayProto', 'PokemonHomeMetadata',
    'HoloPokemon', 'BuddyPokemonProto', 'CapturedPokemon', 'PokemonStats',
    'PokemonMove', 'PokemonBadge', 'PokemonSize',
    'FriendshipProto', 'OriginalTrainer', 'LocationCard',
    'MegaLevel', 'TempEvolution', 'Hatch',
    'PokemonContestRating', 'StoredHomeMetadata',
]

JS = r"""
rpc.exports.dumpLayouts = function(nameFilters) {
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
    var tAttr = bind('il2cpp_type_get_attrs', 'int', ['pointer']);
    var freeFn = bind('il2cpp_free', 'void', ['pointer']);

    // Find holo-protos.dll image
    var sp = Memory.alloc(4);
    var asms = IL2.dGA(IL2.dG(), sp);
    var na = sp.readS32();
    var img = null;
    for (var a = 0; a < na; a++) {
        var img2 = IL2.aGI(asms.add(a*Process.pointerSize).readPointer());
        if (IL2.iGN(img2).readCString() === 'holo-protos.dll') { img = img2; break; }
    }
    if (!img) return {err: 'holo-protos.dll not found'};

    var n = iGCC(img);
    var out = {};
    for (var i = 0; i < n; i++) {
        var k = iGC(img, i);
        if (k.isNull()) continue;
        var nm = cN(k).readCString();
        if (!nm) continue;
        var match = false;
        for (var fi = 0; fi < nameFilters.length; fi++) {
            if (nm.indexOf(nameFilters[fi]) >= 0) { match = true; break; }
        }
        if (!match) continue;
        var nsPtr = cNS(k);
        var ns = nsPtr.isNull() ? '' : nsPtr.readCString();
        var size = cIS(k);
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var fields = [];
        var f;
        while ((f = cGF(k, iter)) && !f.isNull()) {
            var name = fGN(f).readCString();
            var off = fGO(f);
            var typ = fGT(f);
            var tnPtr = tGN(typ);
            var typeName = tnPtr.readCString();
            try { if (freeFn) freeFn(tnPtr); } catch(e) {}
            var attrs = tAttr ? tAttr(typ) : 0;
            // attrs 0x10 = static
            var isStatic = (attrs & 0x10) !== 0;
            fields.push({name: name, type: typeName, offset: off, is_static: isStatic});
        }
        var key = ns ? (ns + '.' + nm) : nm;
        out[key] = {namespace: ns, name: nm, instSize: size, fields: fields};
    }
    return out;
};
"""


def main():
    print('Attaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')
    try:
        script = pg.get_script_with_helpers(sess, JS)
        t0 = time.time()
        result = script.exports_sync.dump_layouts(NAME_FILTERS)
        if isinstance(result, dict) and 'err' in result:
            print(f'ERROR: {result["err"]}')
            return
        print(f'  enumerated {len(result)} matching classes in {time.time()-t0:.2f}s')
        with open(OUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f'  wrote {OUT_JSON}')
        script.unload()
    finally:
        sess.detach()

    # Generate markdown summary
    layouts = json.load(open(OUT_JSON, encoding='utf-8'))
    lines = ['# Pokémon Proto Class Layouts\n']
    lines.append(f'Enumerated {len(layouts)} matching classes via IL2CPP reflection.\n')
    # Sort by instSize descending so the big ones (the actual protos) come first
    for key, info in sorted(layouts.items(), key=lambda kv: -kv[1]['instSize']):
        non_static = [fld for fld in info['fields'] if not fld['is_static']]
        if not non_static and info['instSize'] < 32:
            continue  # skip pure-enum / pure-static helpers
        lines.append(f'## `{key}` (size {info["instSize"]} bytes, {len(non_static)} instance fields)\n')
        if non_static:
            lines.append('| Offset | Name | Type |')
            lines.append('|---:|---|---|')
            for fld in sorted(non_static, key=lambda f: f['offset']):
                t = fld['type'][:80]
                lines.append(f"| 0x{fld['offset']:03x} | `{fld['name']}` | `{t}` |")
            lines.append('')
    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'  wrote {OUT_MD}')

    # Console summary — show the most-relevant classes
    print('\n=== Summary ===')
    for key, info in sorted(layouts.items(), key=lambda kv: -kv[1]['instSize']):
        non_static = [fld for fld in info['fields'] if not fld['is_static']]
        print(f'  {key:65s} size={info["instSize"]:>5} fields={len(non_static)}')


if __name__ == '__main__':
    main()
