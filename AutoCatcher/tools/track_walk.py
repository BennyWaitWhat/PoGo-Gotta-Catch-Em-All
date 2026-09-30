"""Live check that walking distance is being credited: km walked (PlayerStats), egg incubators, buddy.

Read-only. Every SNAP_S seconds: the C liveness lookup (world stopped, no JS inside -- the same code as the
catcher and the limits dumper) finds the live PlayerStatsProto / EggIncubatorProto / BuddyPokemonProto objects and
their fields are read with plain memory reads. The newest PlayerStats is the one with the highest KmWalked
(it only ever grows). The phone's spoofed position is sampled at the same time for the distance actually moved.

Usage: python tools/track_walk.py [minutes=5] [snapshot seconds=30]
"""
import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402  (reuses its read-only JS: IL bindings, C liveness lookup, readObj)

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
JS = dl.JS.split("rpc.exports = {")[0] + r"""
var KS = {};
function k(name) { if (!(name in KS)) KS[name] = findClass('holo-protos.dll', name); return KS[name]; }
rpc.exports = {
  snap: function (names) {
    var out = {};
    (names || ['PlayerStatsProto', 'EggIncubatorProto', 'BuddyPokemonProto']).forEach(function (n) {
      var kl = k(n); if (!kl) { out[n] = 'class not found'; return; }
      out[n] = instances(kl, 64).map(function (o) { return readObj(o, 1); });
    });
    return out;
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


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 5
    every = float(sys.argv[2]) if len(sys.argv) > 2 else 30
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone -- refusing")
    sess, pid = pg.get_session()
    sc = sess.create_script(JS)
    sc.load()
    print(f"attached pid {pid}; snapshot every {every:g}s for {minutes:g} min", flush=True)
    t0 = time.time()
    first_km, moved, last_pos, prev_km = None, 0.0, spot(), None
    walk_t = time.time()
    full = sc.exports_sync.snap(None)          # eggs + buddy once (they change only on a hatch / candy)
    try:
        while time.time() - t0 <= minutes * 60 + 1:
            last = time.time() - t0 > minutes * 60 - every
            s = full if first_km is None else sc.exports_sync.snap(None if last else ["PlayerStatsProto"])
            if last:
                full = s
            ps = [x for x in (s.get("PlayerStatsProto") or []) if isinstance(x, dict)]
            kms = [num(x.get("KmWalked")) for x in ps if num(x.get("KmWalked")) is not None]
            km = max(kms) if kms else None
            if first_km is None and km is not None:
                first_km = km
            # distance actually moved: sample the spoofed position a few times since the last snapshot
            while time.time() - walk_t < every - 0.5:
                p = spot()
                if p and last_pos:
                    d = meters(last_pos, p)
                    if d < 200:        # ignore a teleport
                        moved += d
                last_pos = p or last_pos
                time.sleep(2)
            walk_t = time.time()
            eggs = []
            for e in full.get("EggIncubatorProto") or []:
                if not isinstance(e, dict):
                    continue
                tgt, start = num(e.get("TargetKmWalked")), num(e.get("StartKmWalked"))
                if tgt and km is not None and tgt > km and e.get("PokemonId"):
                    eggs.append((round(tgt - km, 3), round(tgt - (start or 0), 1), e.get("Id") or e.get("IncubatorType")))
            eggs = sorted(set(eggs))
            buddy = []
            for b in full.get("BuddyPokemonProto") or []:
                if isinstance(b, dict) and (b.get("Id") or b.get("StartKmWalked")):
                    buddy.append((b.get("LastKmAwarded"), b.get("StartKmWalked")))
            buddy = sorted(set((num(a), num(c)) for a, c in buddy))
            gain = (km - first_km) if (km is not None and first_km is not None) else None
            step = (km - prev_km) if (km is not None and prev_km is not None) else None
            prev_km = km if km is not None else prev_km
            el = time.time() - t0
            print(f"{time.strftime('%H:%M:%S')} +{el:4.0f}s | km walked {km if km is None else f'{km:.3f}'}"
                  f" | credited +{0 if gain is None else gain * 1000:.0f} m (this step +{0 if step is None else step * 1000:.0f} m)"
                  f" | moved {moved:.0f} m | label {last_pos[2] * 3.6 if last_pos else 0:.1f} km/h"
                  f" | eggs left (km): {', '.join(f'{r:.2f}/{tot:g}' for r, tot, _ in eggs[:9]) or '-'}"
                  f" | buddy +{(km - buddy[-1][1]) if (buddy and km is not None and buddy[-1][1]) else 0:.3f} km since set", flush=True)
            if el == 0 or len(sys.argv) > 3:
                print("   raw PlayerStats:", json.dumps(ps[:1])[:600], flush=True)
    finally:
        sc.unload()
        sess.detach()
    print("done", flush=True)


if __name__ == "__main__":
    main()
