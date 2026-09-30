"""One-off read-only look at every live buddy record (BuddyPokemonProto, BuddyObservedData, BuddyStatsProto...)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
JS = dl.JS.split("rpc.exports = {")[0] + r"""
rpc.exports = {
  buddy: function (names) {
    var out = {};
    names.forEach(function (n) {
      var kl = findClass('holo-protos.dll', n); if (!kl) { out[n] = 'no class'; return; }
      out[n] = instances(kl, 16).map(function (o) { return readObj(o, 2); });
    });
    return out;
  }
};
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
r = sc.exports_sync.buddy(sys.argv[1].split(",") if len(sys.argv) > 1 else ["BuddyPokemonProto", "BuddyObservedData"])
sc.unload(); sess.detach()
for k, v in r.items():
    print("==", k, "instances:", len(v) if isinstance(v, list) else v)
    if isinstance(v, list):
        seen = set()
        for x in v:
            s = json.dumps(x, sort_keys=True)
            if s in seen: continue
            seen.add(s); print("  ", s[:900])
