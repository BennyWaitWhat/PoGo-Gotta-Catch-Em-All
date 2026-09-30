"""Read-only census of every map data type the game holds right now (instances + a sample record each)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
JS = dl.JS.split("rpc.exports = {")[0] + r"""
rpc.exports = {
  census: function (names) {
    var out = {};
    names.forEach(function (c) {
      var k = findClass('holo-protos.dll', c); if (!k) { out[c] = {n: -1}; return; }
      var hits = instances(k, 3000), sample = [];
      for (var i = 0; i < Math.min(hits.length, 3); i++) { try { sample.push(readObj(hits[i], 2)); } catch (e) {} }
      out[c] = {n: hits.length, sample: sample};
    });
    return out;
  }
};
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
names = ["ClientSpawnPointProto", "ClientMapCellProto", "ClientWeatherProto", "StationProto", "RaidInfoProto",
         "PokestopIncidentDisplayProto", "HyperlocalExperimentClientProto", "EventMapObject", "GymStateProto"]
r = sc.exports_sync.census(names); sc.unload(); sess.detach()
json.dump(r, open(os.path.join(os.path.dirname(HERE), 'system', 'analysis', 'map_types.json'), 'w'), indent=1)
for c in names:
    x = r[c]; print(f"== {c}: {x['n']} live")
    for s in (x.get('sample') or [])[:1]:
        print("   ", json.dumps(s)[:700])
