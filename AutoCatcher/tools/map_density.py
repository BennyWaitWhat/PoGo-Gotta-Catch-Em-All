"""Read-only: every PokeStop / gym and wild spawn the game has loaded (PokemonFortProto, WildPokemonProto)."""
import json, os, sys, math, collections
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
JS = dl.JS.split("rpc.exports = {")[0] + r"""
function pick(o, names) { var r = readObj(o, 0), out = {}; names.forEach(function (n) { if (r[n] !== undefined) out[n] = r[n]; }); return out; }
rpc.exports = {
  go: function () {
    var out = {};
    var f = findClass('holo-protos.dll', 'PokemonFortProto');
    out.forts = f ? instances(f, 4000).map(function (o) { return pick(o, ['FortId', 'Latitude', 'Longitude', 'FortType', 'Enabled', 'ActiveFortModifier', 'PowerUpLevel']); }) : [];
    var w = findClass('holo-protos.dll', 'WildPokemonProto');
    out.wild = w ? instances(w, 4000).map(function (o) { return pick(o, ['EncounterId', 'Latitude', 'Longitude', 'SpawnPointId']); }) : [];
    return out;
  }
};
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
r = sc.exports_sync.go(); sc.unload(); sess.detach()
forts = {x.get('FortId'): x for x in r['forts'] if x.get('Latitude') and x.get('Longitude')}
wild = {x.get('SpawnPointId') or x.get('EncounterId'): x for x in r['wild'] if x.get('Latitude')}
json.dump({'forts': list(forts.values()), 'wild': list(wild.values())}, open(os.path.join(os.path.dirname(HERE), 'system', 'analysis', 'map_density.json'), 'w'), indent=0)
print(f"forts loaded: {len(forts)} (gyms {sum(1 for x in forts.values() if x.get('FortType') in (None, 0, 'GYM'))}, stops {sum(1 for x in forts.values() if x.get('FortType') not in (None, 0, 'GYM'))}) | wild spawn points: {len(wild)}")
lat = [x['Latitude'] for x in forts.values()]; lng = [x['Longitude'] for x in forts.values()]
if lat: print(f"fort area: lat {min(lat):.4f}..{max(lat):.4f}, lng {min(lng):.4f}..{max(lng):.4f}")
