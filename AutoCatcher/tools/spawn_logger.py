"""Read-only spawn logger: every INTERVAL s, record every wild Pokemon (species, exact spot, spawn point, despawn
timer) and every nearby-radar entry (species at a stop) the game holds, plus the player's spoofed position.
The server no longer sends spawn points, so this is how a spawn map gets built.

  python tools/spawn_logger.py [INTERVAL=60] [MINUTES=0 (forever)]
Appends to system/analysis/spawns.jsonl (one JSON object per observation, deduped by encounter id).
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
OUT = os.path.join(os.path.dirname(HERE), "system", "analysis", "spawns.jsonl")
JS = dl.JS.split("rpc.exports = {")[0] + r"""
function pickWild(o) {
  var r = readObj(o, 2), pd = r.PokemonData || {};
  return {enc: r.EncounterId, sp: r.SpawnPointId, lat: r.Latitude, lng: r.Longitude, ttl: r.TimeTillHiddenMs,
          pid: pd.PokemonId, disp: pd.PokemonDisplay ? {form: pd.PokemonDisplay.Form, shiny: pd.PokemonDisplay.Shiny, costume: pd.PokemonDisplay.Costume} : null};
}
rpc.exports = {
  snap: function () {
    var w = findClass('holo-protos.dll', 'WildPokemonProto'), n = findClass('holo-protos.dll', 'NearbyPokemonProto');
    return {wild: w ? instances(w, 400).map(pickWild) : [],
            near: n ? instances(n, 800).map(function (o) { var r = readObj(o, 1); return {pid: r.PokedexNumber, fort: r.FortId, enc: r.EncounterId, dist: r.DistanceInMeters}; }) : []};
  }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def me():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?vel=([0-9.]+)", adb("dumpsys location | grep -m1 'last mock location'"))
    return (float(m[1]), float(m[2]), round(float(m[3]) * 3.6, 2)) if m else None


def main():
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 0
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    seen_w, seen_n = set(), set()
    t0 = time.time()
    sess = sc = None
    while not minutes or time.time() - t0 < minutes * 60:
        try:
            if sc is None:
                pg.wait_ready_to_attach(timeout_s=600, min_age_s=45)
                sess, pid = pg.get_session()
                sc = sess.create_script(JS)
                sc.load()
                print(f"{time.strftime('%H:%M:%S')} attached pid {pid}", flush=True)
            s = sc.exports_sync.snap()
            pos = me()
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            nw = nn = 0
            with open(OUT, "a", encoding="utf-8") as fh:
                for w in s["wild"]:
                    if w.get("enc") and w["enc"] not in seen_w and w.get("lat"):
                        seen_w.add(w["enc"]); nw += 1
                        fh.write(json.dumps({"t": now, "kind": "wild", **w, "me": pos}) + "\n")
                for n in s["near"]:
                    key = f"{n.get('enc')}"
                    if n.get("enc") and key not in seen_n:
                        seen_n.add(key); nn += 1
                        fh.write(json.dumps({"t": now, "kind": "nearby", **n, "me": pos}) + "\n")
            print(f"{time.strftime('%H:%M:%S')} +{nw} wild, +{nn} nearby (totals {len(seen_w)} / {len(seen_n)}) at {pos}", flush=True)
        except Exception as e:   # PoGo restarted / detached: drop the session and re-attach on the next round
            print(f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {str(e)[:120]} -- re-attaching", flush=True)
            try:
                sess and sess.detach()
            except Exception:
                pass
            sess = sc = None
        time.sleep(interval)


if __name__ == "__main__":
    main()
