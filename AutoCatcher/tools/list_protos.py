"""Read-only: list holo-protos class names matching a regex (metadata walk only, no instances)."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
JS = dl.JS.split("rpc.exports = {")[0] + r"""
rpc.exports = {
  names: function (img, rx) {
    var re_ = new RegExp(rx), out = [], sp = Memory.alloc(8), a = IL.asms(IL.domain(), sp), n = sp.readS32();
    for (var i = 0; i < n; i++) { var im = IL.asmImage(a.add(i * PS).readPointer()); if (cs(IL.imageName(im)) !== img) continue;
      var c = IL.classCount(im); for (var j = 0; j < c; j++) { var k = IL.classAt(im, j); if (k.isNull()) continue; var nm = cs(IL.className(k)); if (re_.test(nm)) out.push(nm); } }
    return out;
  }
};
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
for img in sys.argv[2:] or ["holo-protos.dll"]:
    r = sc.exports_sync.names(img, sys.argv[1]); print(img, len(r)); print("  " + "\n  ".join(sorted(r)))
sc.unload(); sess.detach()
