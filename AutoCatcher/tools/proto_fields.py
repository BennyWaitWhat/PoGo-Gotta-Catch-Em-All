"""Read-only: field names/types of given protos + one live sample (to write fast direct readers)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
JS = dl.JS.split("rpc.exports = {")[0] + r"""
rpc.exports = { go: function (names) { var out = {}; names.forEach(function (c) {
  var k = findClass('holo-protos.dll', c); if (!k) { out[c] = null; return; }
  var one = instances(k, 2)[0];
  out[c] = {fields: fieldsOf(k).map(function (f) { return f.name + ':' + f.tn + '@' + f.off; }), sample: one ? readObj(one, 2) : null};
}); return out; } };
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
r = sc.exports_sync.go(sys.argv[1].split(",")); sc.unload(); sess.detach()
for c, v in r.items():
    print("==", c); print("  fields:", v and v["fields"]); print("  sample:", v and json.dumps(v["sample"])[:600])
