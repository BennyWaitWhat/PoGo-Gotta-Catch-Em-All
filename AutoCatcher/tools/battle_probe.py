"""Read-only probe: which battle engine do gym battles use in this game version?

Lists every class whose full name looks battle/gym related (metadata only -- nothing in the game is called or
changed), then the methods of the interesting ones. Output: system/analysis/battle_classes.json.

  python tools/battle_probe.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "system", "analysis", "battle_classes.json")
JS = dl.JS.split("rpc.exports = {")[0] + r"""
var NS = f('il2cpp_class_get_namespace', 'pointer', ['pointer']);
var GM = f('il2cpp_class_get_methods', 'pointer', ['pointer', 'pointer']);
var MN = f('il2cpp_method_get_name', 'pointer', ['pointer']);
var MC = f('il2cpp_method_get_param_count', 'uint32', ['pointer']);
var PN = f('il2cpp_class_get_parent', 'pointer', ['pointer']);
function full(k) { var n = cs(NS(k)); return (n ? n + '.' : '') + cs(IL.className(k)); }
rpc.exports = {
  classes: function (pattern) {
    var re = new RegExp(pattern, 'i'), out = [], cnt = Memory.alloc(PS);
    var arr = IL.asms(IL.domain(), cnt), n = cnt.readU32();
    for (var i = 0; i < n; i++) {
      var img = IL.asmImage(arr.add(i * PS).readPointer()), iname = cs(IL.imageName(img)), c = IL.classCount(img);
      for (var j = 0; j < c; j++) {
        var k = IL.classAt(img, j); if (k.isNull()) continue;
        var nm = full(k);
        if (re.test(nm)) out.push({image: iname, name: nm, parent: (function () { var p = PN(k); return p.isNull() ? '' : full(p); })()});
      }
    }
    return out;
  },
  fieldTypes: function (name) {        /* fields of one class with their type names */
    var cnt = Memory.alloc(PS), arr = IL.asms(IL.domain(), cnt), n = cnt.readU32();
    for (var i = 0; i < n; i++) {
      var img = IL.asmImage(arr.add(i * PS).readPointer()), c = IL.classCount(img);
      for (var j = 0; j < c; j++) { var k = IL.classAt(img, j); if (!k.isNull() && full(k) === name)
        return fieldsOf(k).map(function (x) { return {name: x.name, off: x.off, type: x.tn}; }); }
    }
    return null;
  },
  methods: function (names) {
    var want = {}, res = {}, cnt = Memory.alloc(PS);
    names.forEach(function (x) { want[x] = 1; });
    var arr = IL.asms(IL.domain(), cnt), n = cnt.readU32();
    for (var i = 0; i < n; i++) {
      var img = IL.asmImage(arr.add(i * PS).readPointer()), c = IL.classCount(img);
      for (var j = 0; j < c; j++) {
        var k = IL.classAt(img, j); if (k.isNull()) continue;
        var nm = full(k); if (!want[nm]) continue;
        var ms = [], it = Memory.alloc(PS); it.writePointer(NULL); var m;
        while ((m = GM(k, it)) && !m.isNull()) ms.push(cs(MN(m)) + '/' + MC(m));
        var fs = []; try { fs = fieldsOf(k).map(function (x) { return x.name + '@' + x.off; }); } catch (e) {}
        res[nm] = {methods: ms, fields: fs};
      }
    }
    return res;
  }
};
"""

PATTERN = r"(gym.*(battle|attack|session|combat|fight|lobby|approach)|(battle|attack|session|combat|fight).*gym|vnext\..*(battle|director|gamemode|attack|pokemon|input|state)|battledirector|battlegamemode|battleinput|attackbutton|\.battle\.)"
FOCUS = ("BattleDirector", "GymBattle", "GameMode", "BattleInput", "AttackButton", "BattleUI", "GymBattleVNext", "GymVNext")


def of(cls):
    """--of CLASS: its fields with types, then the methods of every field's class (read-only)."""
    pg.wait_ready_to_attach(timeout_s=300, min_age_s=45)
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    fields = sc.exports_sync.field_types(cls) or []
    types = sorted({f["type"].split("<")[0] for f in fields if f["type"].startswith(("Niantic.", "Holoholo."))})
    meth = sc.exports_sync.methods(types)
    sc.unload()
    sess.detach()
    for f in fields:
        print(f"  {f['off']:4d}  {f['name']:<40} {f['type']}")
    for t, v in meth.items():
        print(f"\n== {t}\n  methods: {', '.join(v['methods'])}\n  fields: {', '.join(v['fields'][:40])}")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--of":
        return of(sys.argv[2])
    pg.wait_ready_to_attach(timeout_s=300, min_age_s=45)
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    t0 = time.time()
    cls = sc.exports_sync.classes(PATTERN)
    print(f"attached pid {pid}; {len(cls)} matching classes in {time.time() - t0:.1f} s", flush=True)
    names = sorted({c["name"] for c in cls if any(k.lower() in c["name"].lower() for k in FOCUS)})[:80]
    meth = sc.exports_sync.methods(names)
    sc.unload()
    sess.detach()
    json.dump({"read_at": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": pid, "classes": cls, "detail": meth}, open(OUT, "w", encoding="utf-8"), indent=1)
    gym = [c["name"] for c in cls if "gym" in c["name"].lower()]
    vnext = [c["name"] for c in cls if "vnext" in c["name"].lower()]
    print(f"gym-named classes: {len(gym)} | VNext battle classes: {len(vnext)} | detail for {len(meth)} -> {OUT}")
    for n in sorted(gym)[:80]:
        print("  G", n)
    for n in sorted(vnext)[:80]:
        print("  V", n)


if __name__ == "__main__":
    main()
