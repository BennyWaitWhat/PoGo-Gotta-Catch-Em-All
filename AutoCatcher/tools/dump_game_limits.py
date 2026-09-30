"""Read-only dump of every limit / threshold the Pokemon GO client knows about.

Two sources, both live in PoGo's memory:
  1. GlobalSettingsProto  -- the settings the server sends at login (map, GPS/driving, forts, background mode, ...)
  2. GameMasterClientTemplateProto -- the game master; only its *settings* templates are kept (not the per-Pokemon,
     per-move, per-item ones)
Instances are found with the C liveness lookup (world stopped, no JS inside -- safe next to the running catcher);
everything else is plain memory reads by field name. Nothing is written to the game.

Usage (desktop, phone on adb):  python tools/dump_game_limits.py
Writes system/analysis/game_limits.json
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg  # noqa: E402

OUT = os.path.join(ROOT, "system", "analysis", "game_limits.json")

JS = r"""
var PROP = {exceptions: 'propagate'}, PS = Process.pointerSize;
var EX = {}; Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (x) { EX[x.name] = x.address; });
function f(n, r, a) { return EX[n] ? new NativeFunction(EX[n], r, a, PROP) : null; }
var IL = {
  domain: f('il2cpp_domain_get', 'pointer', []), asms: f('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']),
  asmImage: f('il2cpp_assembly_get_image', 'pointer', ['pointer']), imageName: f('il2cpp_image_get_name', 'pointer', ['pointer']),
  classCount: f('il2cpp_image_get_class_count', 'uint32', ['pointer']), classAt: f('il2cpp_image_get_class', 'pointer', ['pointer', 'uint32']),
  className: f('il2cpp_class_get_name', 'pointer', ['pointer']), objClass: f('il2cpp_object_get_class', 'pointer', ['pointer']),
  fields: f('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']), fieldName: f('il2cpp_field_get_name', 'pointer', ['pointer']),
  fieldOffset: f('il2cpp_field_get_offset', 'uint32', ['pointer']), fieldFlags: f('il2cpp_field_get_flags', 'int', ['pointer']),
  fieldType: f('il2cpp_field_get_type', 'pointer', ['pointer']), typeEnum: f('il2cpp_type_get_type', 'int', ['pointer']),
  typeName: f('il2cpp_type_get_name', 'pointer', ['pointer']), classFromType: f('il2cpp_class_from_type', 'pointer', ['pointer']),
  isEnum: f('il2cpp_class_is_enum', 'bool', ['pointer']), parent: f('il2cpp_class_get_parent', 'pointer', ['pointer']),
  isValueType: f('il2cpp_class_is_valuetype', 'int', ['pointer'])
};
/* SAFETY (a garbage pointer passed to il2cpp crashed PoGo at 23:35): a pointer that came out of object memory is only
   ever touched with Frida memory reads -- those throw a catchable JS error on a bad address. il2cpp functions only get
   class/field/type pointers that came from il2cpp's own metadata. Il2CppClass: image@0x0, gc_desc@0x8, name@0x10. */
function jsClass(obj) {
  var k = obj.readPointer(), np = k.add(0x10).readPointer(), nm = np.readCString();   /* readCString(n) reads n bytes, NULs and all */
  if (nm.length > 200 || !/^[A-Za-z_][\w`<>.,]*$/.test(nm)) throw new Error('not an object');
  return {k: k, name: nm};
}
function cs(p) { try { return p.isNull() ? '' : p.readCString(); } catch (e) { return ''; } }
function findClass(image, name) {
  var sp = Memory.alloc(4), a = IL.asms(IL.domain(), sp), n = sp.readS32();
  for (var i = 0; i < n; i++) { var im = IL.asmImage(a.add(i * PS).readPointer()); if (cs(IL.imageName(im)) !== image) continue;
    var c = IL.classCount(im); for (var j = 0; j < c; j++) { var k = IL.classAt(im, j); if (!k.isNull() && cs(IL.className(k)) === name) return k; } }
  return null;
}
/* ---- the C liveness lookup (same code as the catcher; no static variables -- they are read-only in this gadget) ---- */
var C_SRC = [
  'typedef struct { void **out; int max; int n; } Hits;',
  'extern void *il2cpp_unity_liveness_allocate_struct(void *filter, int max, void *cb, void *ud, void *re);',
  'extern void il2cpp_unity_liveness_calculation_from_statics(void *st);',
  'extern void il2cpp_unity_liveness_finalize(void *st);',
  'extern void il2cpp_unity_liveness_free_struct(void *st);',
  'extern void il2cpp_stop_gc_world(void);',
  'extern void il2cpp_start_gc_world(void);',
  'extern void *il2cpp_alloc(unsigned long n);',
  'extern void il2cpp_free(void *p);',
  'static void on_objs(void **objs, int count, void *ud) { Hits *h = (Hits *)ud; int i; for (i = 0; i < count && h->n < h->max; i++) h->out[h->n++] = objs[i]; }',
  'static void *on_re(void *p, unsigned long size, void *ud) { if (p != 0 && size == 0) { il2cpp_free(p); return 0; } return il2cpp_alloc(size); }',
  'int find_instances(void *klass, void *hits) {',
  '  void *st; ((Hits *)hits)->n = 0;',
  '  il2cpp_stop_gc_world();',
  '  st = il2cpp_unity_liveness_allocate_struct(klass, 0, (void *)on_objs, hits, (void *)on_re);',
  '  if (st != 0) { il2cpp_unity_liveness_calculation_from_statics(st); il2cpp_unity_liveness_finalize(st); }',
  '  il2cpp_start_gc_world();',
  '  if (st != 0) il2cpp_unity_liveness_free_struct(st);',
  '  return ((Hits *)hits)->n;',
  '}'].join('\n');
var CM = null, FIND = null;
function instances(klass, max) {
  if (!CM) {
    var syms = {};
    ['il2cpp_unity_liveness_allocate_struct', 'il2cpp_unity_liveness_calculation_from_statics', 'il2cpp_unity_liveness_finalize',
     'il2cpp_unity_liveness_free_struct', 'il2cpp_stop_gc_world', 'il2cpp_start_gc_world', 'il2cpp_alloc', 'il2cpp_free'].forEach(function (n) { syms[n] = EX[n]; });
    CM = new CModule(C_SRC, syms); FIND = new NativeFunction(CM.find_instances, 'int', ['pointer', 'pointer'], PROP);
  }
  var hits = Memory.alloc(16 + PS * max); hits.writePointer(hits.add(16)); hits.add(8).writeS32(max); hits.add(12).writeS32(0);
  var n = FIND(klass, hits), out = [];
  for (var i = 0; i < n; i++) out.push(hits.add(16 + PS * i).readPointer());
  return out;
}
/* ---- generic protobuf reader: instance fields by name, memory reads only ---- */
var FCACHE = {};
function fieldsOf(k) {
  var key = k.toString(); if (FCACHE[key]) return FCACHE[key];
  var out = [], kk = k;
  while (kk && !kk.isNull()) {
    var it = Memory.alloc(PS); it.writePointer(NULL); var fd;
    while ((fd = IL.fields(kk, it)) && !fd.isNull()) {
      if (IL.fieldFlags(fd) & 0x10) continue;   /* static */
      var t = IL.fieldType(fd);
      out.push({name: cs(IL.fieldName(fd)), off: IL.fieldOffset(fd), te: IL.typeEnum(t), tn: cs(IL.typeName(t)), t: t});
    }
    var par = IL.parent(kk); if (!par || par.isNull() || cs(IL.className(par)) === 'Object') break; kk = par;
  }
  FCACHE[key] = out; return out;
}
function str(p) { try { if (p.isNull()) return null; var n = p.add(0x10).readS32(); return (n >= 0 && n < 4096) ? p.add(0x14).readUtf16String(n) : null; } catch (e) { return null; } }
function prim(p, te) {
  switch (te) {
    case 0x02: return p.readU8() !== 0; case 0x04: return p.readS8(); case 0x05: return p.readU8();
    case 0x06: return p.readS16(); case 0x07: return p.readU16(); case 0x08: return p.readS32(); case 0x09: return p.readU32();
    case 0x0a: return p.readS64().toString(); case 0x0b: return p.readU64().toString();
    case 0x0c: return Math.round(p.readFloat() * 1e6) / 1e6; case 0x0d: return Math.round(p.readDouble() * 1e9) / 1e9;
  }
  return undefined;
}
var ELEM = {'System.Int32': [0x08, 4], 'System.UInt32': [0x09, 4], 'System.Int64': [0x0a, 8], 'System.UInt64': [0x0b, 8],
            'System.Single': [0x0c, 4], 'System.Double': [0x0d, 8], 'System.Boolean': [0x02, 1], 'System.String': ['s', 8]};
function readObj(o, depth) {
  if (!o || o.isNull()) return null;
  var jc; try { jc = jsClass(o); } catch (e) { return '<unreadable>'; }
  var k = jc.k, cn = jc.name;
  if (cn === 'String') return str(o);
  if (depth > 6) return '<' + cn + '>';
  var res = {};
  fieldsOf(k).forEach(function (fd) {
    if (/^_?unknownFields|^_unknownFields$|UnknownFields/i.test(fd.name)) return;
    try {
      var p = o.add(fd.off), v;
      if (fd.te === 0x11) {   /* value type: enums read as int */
        var ec = IL.classFromType(fd.t); v = IL.isEnum(ec) ? p.readS32() : undefined;
        if (v === 0) return;   /* proto3 default: unset */
      } else if (fd.te === 0x0e) { v = str(p.readPointer()); if (!v) return; }
      else if (fd.te === 0x12 || fd.te === 0x15 || fd.te === 0x1c) {
        if (fd.te === 0x15 && IL.isValueType(IL.classFromType(fd.t))) return;   /* inline generic struct (Nullable<>, ...) */
        var q = p.readPointer(); if (q.isNull()) return;
        var qn; try { qn = jsClass(q).name; } catch (e) { return; }
        if (qn.indexOf('RepeatedField') === 0) {
          var arr = q.add(0x10).readPointer(), cnt = q.add(0x18).readS32(); if (cnt <= 0 || arr.isNull()) return;
          var m = /RepeatedField<(.+)>$/.exec(fd.tn), et = m ? m[1] : '', el = ELEM[et], list = [];
          for (var i = 0; i < Math.min(cnt, 40); i++) {
            if (el && el[0] === 's') list.push(str(arr.add(0x20 + 8 * i).readPointer()));
            else if (el) list.push(prim(arr.add(0x20 + el[1] * i), el[0]));
            else if (/Proto$|Settings|Entry|Pair/.test(et) || et.indexOf('.') >= 0) {
              var ep = arr.add(0x20 + 8 * i).readPointer();
              /* enum element types are 4-byte ints in the array */
              var ek = IL.classFromType(fd.t); list.push(ep.isNull() ? null : readObj(ep, depth + 1));
            }
          }
          if (cnt > 40) list.push('... ' + cnt + ' total');
          v = list;
        } else if (qn.indexOf('MapField') === 0) { v = '<map>'; }
        else v = readObj(q, depth + 1);
        if (v === null || (typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0)) return;
      } else { v = prim(p, fd.te); if (v === undefined || v === 0 || v === false || v === '0') return; }
      res[fd.name] = v;
    } catch (e) { res[fd.name] = '<unreadable>'; }
  });
  return res;
}
var TPL = [];
function findClassAny(name) {
  var sp = Memory.alloc(4), a = IL.asms(IL.domain(), sp), n = sp.readS32();
  for (var i = 0; i < n; i++) { var im = IL.asmImage(a.add(i * PS).readPointer()); var c = IL.classCount(im);
    for (var j = 0; j < c; j++) { var k = IL.classAt(im, j); if (!k.isNull() && cs(IL.className(k)) === name) return k; } }
  return null;
}
/* GameMasterData keeps ONE message per settings type in a Dictionary<System.Type, IMessage> (143 entries on 0.429.1).
   Dictionary<ref,ref> entries: hashCode@0 int, next@4 int, key@8, value@16 (24 bytes); array data starts at +0x20. */
var GMSET = [];
function gmSettingsList() {
  var k = findClassAny('GameMasterData'); if (!k) throw new Error('no GameMasterData');
  var gm = instances(k, 4)[0]; if (!gm) throw new Error('no GameMasterData instance');
  var dict = null;
  fieldsOf(k).forEach(function (fd) { if (/Dictionary<System\.Type,Niantic\.Protobuf\.IMessage>/.test(fd.tn)) dict = gm.add(fd.off).readPointer(); });
  if (!dict || dict.isNull()) throw new Error('settings dictionary not found');
  var dk = jsClass(dict).k, entries = NULL, count = 0;
  fieldsOf(dk).forEach(function (fd) { if (/entries/i.test(fd.name)) entries = dict.add(fd.off).readPointer(); if (/^_?count$/.test(fd.name)) count = dict.add(fd.off).readS32(); });
  if (entries.isNull()) throw new Error('no entries array');
  var out = [];
  for (var i = 0; i < count; i++) { var e = entries.add(0x20 + 24 * i); if (e.readS32() < 0) continue; var v = e.add(16).readPointer(); if (!v.isNull()) out.push(v); }
  return out;
}
rpc.exports = {
  globalSettings: function () {
    var k = findClass('holo-protos.dll', 'GlobalSettingsProto'); if (!k) return {err: 'GlobalSettingsProto not found'};
    var inst = instances(k, 16), best = null, bestN = -1;
    inst.forEach(function (o) { var d = readObj(o, 0); var n = JSON.stringify(d).length; if (n > bestN) { bestN = n; best = d; } });
    return {instances: inst.length, settings: best};
  },
  gmSettingsCount: function () { GMSET = gmSettingsList(); return GMSET.length; },
  gmSettings: function (from, n) {
    var out = [];
    for (var i = from; i < Math.min(GMSET.length, from + n); i++) {
      try { var jc = jsClass(GMSET[i]); out.push({type: jc.name, data: readObj(GMSET[i], 0)}); } catch (e) { out.push({type: 'error@' + i, err: String(e)}); }
    }
    return out;
  },
  findTemplates: function () {
    var k = findClass('holo-protos.dll', 'GameMasterClientTemplateProto'); if (!k) return {err: 'GameMasterClientTemplateProto not found'};
    TPL = instances(k, 30000); return {count: TPL.length};
  },
  templates: function (from, n) {
    var out = [];
    for (var i = from; i < Math.min(TPL.length, from + n); i++) {
      try {
        var o = TPL[i], k = jsClass(o).k, id = null;
        fieldsOf(k).forEach(function (fd) { if (fd.name === 'TemplateId' || fd.name === 'templateId_') id = str(o.add(fd.off).readPointer()); });
        if (!id || !/SETTINGS|_CONFIG|GLOBAL|LIMIT|THRESHOLD/.test(id) || /^V\d{4}|^COMBAT_V|^ITEM_|^BADGE_|^AVATAR|^FORMS_|^STICKER|^IAP_ITEM|^QUEST_|^TEMPORARY_EVOLUTION|^SPAWN_V|^POKEMON_HOME_FORM/.test(id)) continue;
        out.push({id: id, data: readObj(o, 0)});
      } catch (e) { out.push({id: 'error@' + i, err: String(e)}); }
    }
    return out;
  }
};
"""


def main():
    sess, pid = pg.get_session()
    print(f"attached pid {pid}")
    sc = sess.create_script(JS)
    sc.load()
    t = time.time()
    gs = sc.exports_sync.global_settings()
    print(f"GlobalSettingsProto: {gs.get('instances')} instance(s), {len(json.dumps(gs.get('settings') or {}))} bytes, {time.time() - t:.1f}s")
    n = sc.exports_sync.gm_settings_count()
    tpl = []
    for i in range(0, n, 20):   # chunks, so the shared JS lock is released between calls
        tpl.extend(sc.exports_sync.gm_settings(i, 20))
    print(f"game master settings objects: {n}, dumped {len(tpl)}")
    sc.unload()
    sess.detach()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"pid": pid, "read_at": time.strftime("%Y-%m-%d %H:%M:%S"), "global_settings": gs.get("settings"),
                   "game_master_settings": sorted(tpl, key=lambda x: x["type"])}, fh, indent=1)
    print(f"wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
