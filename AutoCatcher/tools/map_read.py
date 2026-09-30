"""Read-only: every fort (stop/gym) the game has loaded with its full record, plus wild/nearby Pokemon, in batches."""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
OUT = os.path.join(os.path.dirname(HERE), 'system', 'analysis', 'map_full.json')
JS = dl.JS.split("rpc.exports = {")[0] + r"""
var HITS = {};
rpc.exports = {
  find: function (names) { var n = {}; names.forEach(function (c) { var k = findClass('holo-protos.dll', c); HITS[c] = k ? instances(k, 6000) : []; n[c] = HITS[c].length; }); return n; },
  batch: function (c, from, count) {
    var out = [], h = HITS[c] || [];
    for (var i = from; i < Math.min(h.length, from + count); i++) { try { out.push(readObj(h[i], 3)); } catch (e) { out.push(null); } }
    return out;
  }
};
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
names = ["PokemonFortProto", "WildPokemonProto", "NearbyPokemonProto", "MapPokemonProto"]
counts = sc.exports_sync.find(names); print("live objects:", counts, flush=True)
data = {}
for c in names:
    rows = []
    for i in range(0, counts[c], 150):
        rows += [r for r in sc.exports_sync.batch(c, i, 150) if isinstance(r, dict)]
        time.sleep(0.05)                      # release the shared JS lock between batches
    data[c] = rows
sc.unload(); sess.detach()
json.dump({"read_at": time.strftime("%Y-%m-%d %H:%M:%S"), **data}, open(OUT, "w"), indent=0)
forts = {f.get("FortId"): f for f in data["PokemonFortProto"] if f.get("Latitude")}
print(f"unique forts {len(forts)} | keys seen on forts: {sorted({k for f in forts.values() for k in f})[:60]}")
