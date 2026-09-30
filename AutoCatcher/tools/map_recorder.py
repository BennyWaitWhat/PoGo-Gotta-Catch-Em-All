"""Record every GetMapObjects exchange (read-only hooks): request position + everything the server returns.

  python tools/map_recorder.py MINUTES [OUT.jsonl]

Per map download: time, the request's PlayerLat/PlayerLng and cell count, and per returned cell the counts of
forts / spawn points / wild / catchable / nearby, plus every wild (encounter, spawn point, position,
TimeTillHiddenMs, species), catchable (expiration) and nearby (distance, fort) entry. Also the joystick fix speed.
Analysis: tools/map_analysis.py.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
JS = dl.JS.split("rpc.exports = {")[0] + r"""
var EV = [], OFF = {}, KL = {};
function offs(name) {
  if (OFF[name]) return OFF[name];
  var k = findClass('holo-protos.dll', name); KL[name] = k; var o = {};
  fieldsOf(k).forEach(function (f) { o[f.name] = {off: f.off, te: f.te}; });
  return (OFF[name] = o);
}
function rep(obj, f) {   /* RepeatedField<T>: backing array @0x10, count @0x18 -> element pointers (or values) */
  var r = obj.add(f.off).readPointer(); if (r.isNull()) return {arr: NULL, n: 0};
  return {arr: r.add(0x10).readPointer(), n: r.add(0x18).readS32()};
}
function rd(o, f) {
  if (!f) return null; var p = o.add(f.off);
  switch (f.te) { case 0x02: return p.readU8() !== 0; case 0x08: return p.readS32(); case 0x09: return p.readU32();
    case 0x0a: return p.readS64().toString(); case 0x0b: return p.readU64().toString(); case 0x0c: return p.readFloat();
    case 0x0d: return p.readDouble(); case 0x0e: return str(p.readPointer()); case 0x11: return p.readS32(); }
  return null;
}
function readResp(o) {
  var R = offs('GetMapObjectsOutProto'), C = offs('ClientMapCellProto'), W = offs('WildPokemonProto'),
      M = offs('MapPokemonProto'), N = offs('NearbyPokemonProto'), P = offs('PokemonProto');
  var cells = rep(o, R.MapCell), out = {status: rd(o, R.Status), cells: [], wild: [], catchable: [], nearby: []};
  for (var i = 0; i < cells.n; i++) {
    var c = cells.arr.add(0x20 + 8 * i).readPointer(); if (c.isNull()) continue;
    var fo = rep(c, C.Fort), sp = rep(c, C.SpawnPoint), wi = rep(c, C.WildPokemon), ca = rep(c, C.CatchablePokemon), ne = rep(c, C.NearbyPokemon);
    out.cells.push([rd(c, C.S2CellId), fo.n, sp.n, wi.n, ca.n, ne.n, rd(c, C.AsOfTimeMs), rd(c, C.IsTruncatedList)]);
    for (var j = 0; j < wi.n; j++) { var w = wi.arr.add(0x20 + 8 * j).readPointer(); if (w.isNull()) continue;
      var pk = w.add(W.Pokemon.off).readPointer();
      out.wild.push([rd(w, W.EncounterId), rd(w, W.SpawnPointId), rd(w, W.Latitude), rd(w, W.Longitude), rd(w, W.TimeTillHiddenMs),
                     rd(w, W.LastModifiedMs), pk.isNull() ? null : rd(pk, P.pokemonId_ || P.PokemonId)]); }
    for (j = 0; j < ca.n; j++) { var m = ca.arr.add(0x20 + 8 * j).readPointer(); if (m.isNull()) continue;
      out.catchable.push([rd(m, M.EncounterId), rd(m, M.SpawnpointId), rd(m, M.Latitude), rd(m, M.Longitude), rd(m, M.ExpirationTimeMs), rd(m, M.PokedexTypeId)]); }
    for (j = 0; j < ne.n; j++) { var q = ne.arr.add(0x20 + 8 * j).readPointer(); if (q.isNull()) continue;
      out.nearby.push([rd(q, N.EncounterId), rd(q, N.PokedexNumber), rd(q, N.DistanceMeters), rd(q, N.FortId)]); }
  }
  return out;
}
function hookParse(name, cb) {
  var k = findClass('holo-protos.dll', name);
  var getM = new NativeFunction(EX['il2cpp_class_get_methods'], 'pointer', ['pointer', 'pointer'], PROP);
  var mName = new NativeFunction(EX['il2cpp_method_get_name'], 'pointer', ['pointer'], PROP);
  var mArgs = new NativeFunction(EX['il2cpp_method_get_param_count'], 'uint32', ['pointer'], PROP);
  var it = Memory.alloc(PS); it.writePointer(NULL); var m, n = 0;
  while ((m = getM(k, it)) && !m.isNull()) {
    var nm = cs(mName(m)); if (mArgs(m) !== 1) continue;
    if (cb.mode === 'parse' && ['WriteTo', 'Equals', '.ctor', 'CalculateSize'].indexOf(nm) >= 0) continue;
    if (cb.mode === 'write' && nm !== 'WriteTo') continue;
    Interceptor.attach(m.readPointer(), {onEnter: function (a) { this.s = a[0]; }, onLeave: function () { try { cb.fn(this.s); } catch (e) { EV.push({t: Date.now(), k: 'err', e: String(e)}); } }});
    n++;
  }
  return n;
}
var LASTRESP = null, DEBUG_LEFT = 0;
rpc.exports = {
  install: function () {
    var Q = offs('GetMapObjectsProto');
    var a = hookParse('GetMapObjectsProto', {mode: 'write', fn: function (s) {
      var cid = rep(s, Q.CellId);
      EV.push({t: Date.now(), k: 'req', lat: rd(s, Q.PlayerLat), lng: rd(s, Q.PlayerLng), cells: cid.n}); }});
    var b = hookParse('GetMapObjectsOutProto', {mode: 'parse', fn: function (s) {
      if (LASTRESP && s.equals(LASTRESP.p) && Date.now() - LASTRESP.t < 300) return;   /* same message through a 2nd overload */
      LASTRESP = {p: s, t: Date.now()};
      var r = readResp(s); if (!r.cells.length) return; r.t = Date.now(); r.k = 'resp';
      if (DEBUG_LEFT > 0) {   /* cross-check the fast offsets against the generic reader on a few samples */
        var C2 = offs('ClientMapCellProto'), cl = rep(s, offs('GetMapObjectsOutProto').MapCell);
        for (var i = 0; i < cl.n && DEBUG_LEFT > 0; i++) { var c = cl.arr.add(0x20 + 8 * i).readPointer(); var wl = rep(c, C2.WildPokemon), ml = rep(c, C2.CatchablePokemon);
          if (wl.n) { r.dbgWild = readObj(wl.arr.add(0x20).readPointer(), 1); DEBUG_LEFT--; }
          if (ml.n) { r.dbgCatch = readObj(ml.arr.add(0x20).readPointer(), 1); } } }
      EV.push(r); }});
    return {reqHooks: a, respHooks: b};
  },
  drain: function () { var e = EV; EV = []; return e; }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def main():
    minutes = float(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(HERE), "system", "analysis", "map_record.jsonl")
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    print(f"attached pid {pid}; hooks {sc.exports_sync.install()}; writing {out}", flush=True)
    t0, n_req, n_resp, last_print = time.time(), 0, 0, 0
    with open(out, "a", encoding="utf-8") as fh:
        try:
            while time.time() - t0 < minutes * 60:
                m = re.search(r"vel=([0-9.]+)", adb("dumpsys location | grep -m1 'last mock location'"))
                spd = float(m[1]) * 3.6 if m else None
                for e in sc.exports_sync.drain():
                    e["spd"] = spd
                    fh.write(json.dumps(e) + "\n")
                    n_req += e["k"] == "req"
                    n_resp += e["k"] == "resp"
                    if e["k"] == "err":
                        print("hook error:", e["e"], flush=True)
                fh.flush()
                if time.time() - last_print >= 30:
                    last_print = time.time()
                    print(f"{time.strftime('%H:%M:%S')} map requests {n_req}, responses {n_resp}, speed {spd or 0:.1f} km/h", flush=True)
                time.sleep(2)
        finally:
            sc.unload()
            sess.detach()
    print("done", flush=True)


if __name__ == "__main__":
    main()
