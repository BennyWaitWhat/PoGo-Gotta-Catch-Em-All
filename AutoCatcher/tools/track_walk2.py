"""Live walking progress from the GAME'S OWN RECORDS only (read-only).

Every SNAP_S seconds:
  PlayerStatsProto.KmWalked            -- the distance the server has credited you (newest copy = highest value)
  BuddyObservedData.TotalStats.KmWalked -- the buddy's own walked record (+ CurrentPointsEarned)
Every 3rd snapshot (and at start/end):
  EggIncubatorProto Start/TargetKmWalked -- each egg's "walked X / Y km", the game's formula (KmWalked - Start)
At start/end: BuddyPokemonProto (LastKmAwarded, StartKmWalked) and the buddy's PokemonProto (BuddyKmWalked,
BuddyCandyAwarded) found by BuddyPokemonId.
GPS movement is printed separately and labelled -- it is my measurement, not a game record.

Usage: python tools/track_walk2.py [minutes=5] [snapshot seconds=30]
"""
import math
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
var KS = {};
function k(name) { if (!(name in KS)) KS[name] = findClass('holo-protos.dll', name); return KS[name]; }
function off(kl, name) { var o = -1; fieldsOf(kl).forEach(function (fd) { if (fd.name === name) o = fd.off; }); return o; }
rpc.exports = {
  snap: function (names) {
    var out = {};
    names.forEach(function (n) {
      var kl = k(n); if (!kl) { out[n] = 'class not found'; return; }
      out[n] = instances(kl, 64).map(function (o) { return readObj(o, 2); });
    });
    return out;
  },
  buddyMon: function (idStr) {   /* the buddy's own PokemonProto: match the u64 Id, read only that object */
    var kl = k('PokemonProto'); if (!kl) return 'no class';
    var io = off(kl, 'Id'); if (io < 0) return 'no Id field';
    var want = uint64(idStr), hits = instances(kl, 30000), n = hits.length, best = null, copies = 0;
    for (var i = 0; i < n; i++) {   /* several live copies can exist (old syncs): keep the one with the most buddy km */
      try { if (hits[i].add(io).readU64().equals(want)) { copies++; var r = readObj(hits[i], 1); var o = {};
        Object.keys(r).forEach(function (key) { if (/Buddy|PokemonId|Nickname|Cp$/.test(key)) o[key] = r[key]; });
        if (!best || (parseFloat(o.BuddyKmWalked) || 0) > (parseFloat(best.BuddyKmWalked) || 0)) best = o; } } catch (e) {}
    }
    if (!best) return {notFound: true, scanned: n};
    best._copies = copies; best._scanned = n; return best;
  }
};
"""


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True,
                          env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout


def spot():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?vel=([0-9.]+)", adb("dumpsys location | grep -m1 'last mock location'"))
    return (float(m[1]), float(m[2]), float(m[3])) if m else None


def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl_ = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl_ / 2) ** 2))


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def top(rows, getter):
    vals = [getter(r) for r in rows if isinstance(r, dict)]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 5
    every = float(sys.argv[2]) if len(sys.argv) > 2 else 30
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone -- refusing")
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    print(f"attached pid {pid}; game records every {every:g}s for {minutes:g} min", flush=True)

    def buddy_block(tag):
        s = sc.exports_sync.snap(["BuddyPokemonProto"])
        bp = [x for x in s["BuddyPokemonProto"] if isinstance(x, dict) and x.get("BuddyPokemonId")]
        if not bp:
            print(f"{tag} BuddyPokemonProto: none", flush=True)
            return None
        b = bp[-1]
        mon = sc.exports_sync.buddy_mon(str(b["BuddyPokemonId"]))
        print(f"{tag} BuddyPokemonProto: LastKmAwarded={b.get('LastKmAwarded')} StartKmWalked={b.get('StartKmWalked')} "
              f"set@{time.strftime('%H:%M:%S', time.localtime(int(b.get('LastSetTimestampMs', 0)) / 1000))} | "
              f"buddy PokemonProto: {mon}", flush=True)
        return b

    buddy_block("START")
    t0, i, moved, last = time.time(), 0, 0.0, spot()
    base = {}
    eggs_raw = []
    try:
        while True:
            names = ["PlayerStatsProto", "BuddyObservedData"] + (["EggIncubatorProto"] if i % 3 == 0 else [])
            s = sc.exports_sync.snap(names)
            km = top(s["PlayerStatsProto"], lambda r: f(r.get("KmWalked")))
            bo = [r for r in s["BuddyObservedData"] if isinstance(r, dict)]
            bkm = top(bo, lambda r: f((r.get("TotalStats") or {}).get("KmWalked")))
            bpts = top(bo, lambda r: f(r.get("CurrentPointsEarned")))
            aff = top(bo, lambda r: f((r.get("TodayStatsShownHearts") or {}).get("BuddyAffectionKmInProgress", 0)))
            if "EggIncubatorProto" in s:
                eggs_raw = [e for e in s["EggIncubatorProto"] if isinstance(e, dict) and e.get("PokemonId")]
            base.setdefault("km", km)
            base.setdefault("bkm", bkm)
            eggs = {}
            for e in eggs_raw:
                st, tg = f(e.get("StartKmWalked")), f(e.get("TargetKmWalked"))
                if st is not None and tg and km is not None and tg > km:
                    eggs[(st, tg)] = f"{km - st:.2f}/{tg - st:g} km"
            el = time.time() - t0
            print(f"{time.strftime('%H:%M:%S')} +{el:4.0f}s | PlayerStats.KmWalked {km:.3f} (+{(km - base['km']) * 1000:.0f} m)"
                  f" | eggs (walked/total): {', '.join(v for _, v in sorted(eggs.items())) or '-'}"
                  f" | WalkTogether BuddyAffectionKmInProgress {aff:.3f} | hearts {bpts:g}"
                  f" | moved (GPS, not a game record) {moved:.0f} m", flush=True)
            i += 1
            if el >= minutes * 60:
                break
            nxt = time.time() + every
            while time.time() < nxt - 1:
                p = spot()
                if p and last and meters(last, p) < 200:
                    moved += meters(last, p)
                last = p or last
                time.sleep(2)
        buddy_block("END  ")
    finally:
        sc.unload()
        sess.detach()
    print("done", flush=True)


if __name__ == "__main__":
    main()
