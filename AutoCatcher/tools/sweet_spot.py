"""Fastest catching sweet spot: per speed, catchable Pokemon passed/min (server map data) x share caught (catcher log).

  python tools/sweet_spot.py 20 25 31 15 30 25 31 20        (SEG=180 s per window; map_recorder must be running)
"""
import json, os, re, subprocess, sys, time
from collections import defaultdict
DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
LOG = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod/catch_loop.log"
REC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "system", "analysis", "map_record.jsonl")
SEG = int(os.environ.get("SEG", "180"))
def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""
def nlines(): return int(adb(f"su -c 'wc -l < {LOG}'").strip() or 0)
def catchables_between(t0, t1):
    """Wild Pokemon whose spawn point (S2 level-20 token = its map position) came within 140 m of the player's
    requested positions during the window. The server sends wild coordinates as 0, so the spawn point is the position."""
    import math
    import s2sphere
    pos, wild = [], {}
    with open(REC, encoding="utf-8") as fh:
        for ln in fh:
            try: e = json.loads(ln)
            except ValueError: continue
            if not (t0 * 1000 <= e.get("t", 0) <= t1 * 1000): continue
            if e.get("k") == "req" and e.get("lat"): pos.append((e["lat"], e["lng"]))
            elif e.get("k") == "resp":
                for w in e.get("wild") or []:
                    wild.setdefault(w[0], w)
    def m(a, b):
        R = 6371008.8; p1, p2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
        return 2 * R * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
    near = {}
    for enc, w in wild.items():
        try:
            ll = s2sphere.CellId.from_token(w[1]).to_lat_lng(); sp = (ll.lat().degrees, ll.lng().degrees)
        except Exception:
            continue
        if pos and min(m(sp, q) for q in pos[::3]) <= 140:
            near[enc] = w
    catchables_between.last = (len(wild), len(pos))
    return near


def main():
    speeds = [float(x) for x in sys.argv[1:]]
    if max(speeds) >= 32: sys.exit("refusing: >= 32 km/h warning")
    if "Pixel" not in adb("getprop ro.product.model"): sys.exit("not the phone")
    agg = defaultdict(lambda: [0, 0, 0, 0.0])      # speed -> passed, caught, fled, minutes
    for sp in speeds:
        adb(f"am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed {sp}")
        time.sleep(15)
        n0, t0 = nlines(), time.time()
        time.sleep(SEG)
        t1 = time.time()
        new = adb(f"su -c 'tail -n +{n0 + 1} {LOG}'").splitlines()
        caught = sum(1 for l in new if " CATCH " in l)
        fled = sum(1 for l in new if " FLED " in l)
        passed = len(catchables_between(t0, t1))
        mins = (t1 - t0) / 60
        a = agg[sp]; a[0] += passed; a[1] += caught; a[2] += fled; a[3] += mins
        wild_all, npos = catchables_between.last
        print(f"{time.strftime('%H:%M:%S')} SPEED {sp:4.1f} | map: {wild_all} wild seen, {npos} map requests | within 140 m: {passed:3d} ({passed / mins:5.1f}/min) | caught {caught:3d}"
              f" ({caught / mins:5.1f}/min) | fled {fled} | share caught {caught / passed * 100 if passed else 0:5.1f}%", flush=True)
    adb("am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed 10.6")
    print("SUMMARY (all windows per speed pooled):", flush=True)
    for sp in sorted(agg):
        p, c, f, m = agg[sp]
        print(f"   {sp:4.1f} km/h | passed {p / m:5.1f}/min | caught {c / m:5.1f}/min | share {c / p * 100 if p else 0:5.1f}% | fled {f} | {m:.1f} min", flush=True)
    print("back on 10.6. done", flush=True)
if __name__ == "__main__":
    main()
