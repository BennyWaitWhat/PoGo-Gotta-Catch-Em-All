"""Does the auto-catcher keep catching at speed? SPEED (GPS Joystick Pro API) steps, catcher log as the record.

  SEG=300 python tools/catch_speed_test.py 10.5 16 20 24 28 28 24 20 16 10.5     [SEG s per window, default 120]
  EVENTS=w.jsonl LOOP=dense_loop.json SEG=180 python tools/catch_speed_test.py 16 18 22 20 18 20 16 22 ...
  python tools/catch_speed_test.py report w.jsonl dense_loop.json             the same-ground table of a finished run

Per speed: SPEED X, 15 s settle, then SEG seconds counted from the catcher's own log on the phone:
caught / escaped / fled / gone (from its cumulative run counters), every other outcome word (NORESULT, errors...),
"no Pokemon seen" refreshes and the average Pokemon visible/tracked; plus the measured real speed and km.
escaped = it broke out of the ball and got another throw (NOT lost); fled = lost after a throw; gone = tracked, then off
the map before a throw (passed by). flee% = fled / (caught + fled) -- the number Benny asked for (2026-09-30: "fastest speed
with less than 5% flee rate").
SAME GROUND (user 2026-09-30: "some places you walk while testing don't have the same spawn density"): the ground under
a window changes what it catches, so a speed that happened to get the dense blocks looks better. EVENTS= writes every
window's fixes and its CATCH / FLED lines; with LOOP= (dense_loop.py --out) each one is put on the loop side where it
happened and the flee% of every speed is re-weighted to the SAME mix of sides (direct standardisation). Interleave the
speeds in short windows (a Williams order, each speed after every other once) so every speed walks every side.
Safety (2026-09-30): never above speed_governor.MAX_KMH (28); before every SPEED the governor's guard() must pass
(joystick overlay alive, no joystick screen in front), else it stops and sends nothing more; a full bag (the
catcher's "Pokemon storage is full") ends the test, since nothing can be caught. Ends on the speed it found.
"""
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from speed_governor import MAX_KMH, guard   # noqa: E402

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
LOG = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod/catch_loop.log"
SEG = int(os.environ.get("SEG", "120"))
EVENTS, LOOP = os.environ.get("EVENTS"), os.environ.get("LOOP")


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def lines_count():
    return int((adb(f"su -c 'wc -l < {LOG}'").strip() or "0"))


def lines_since(n):
    return adb(f"su -c 'tail -n +{n + 1} {LOG}'").splitlines()


def fix():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?et=\+(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?(?:(\d+)ms)?.*?vel=([0-9.]+)",
                  adb("dumpsys location | grep -m1 'last mock location'"))
    if not m:
        return None
    # et= is uptime and gains a day field after 24 h ("+1d21h18m28s184ms"); without (\d+)d the whole match came back 0
    et = int(m[3] or 0) * 86400 + int(m[4] or 0) * 3600 + int(m[5] or 0) * 60 + int(m[6] or 0) + int(m[7] or 0) / 1000
    return float(m[1]), float(m[2]), et, float(m[8]) * 3.6


def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def counters(lines):
    """(caught, esc, flee, gone) from the newest run line."""
    for ln in reversed(lines):
        m = re.search(r" run \d+s \| caught=(-?\d+) esc=(-?\d+) flee=(-?\d+)", ln)
        if m:
            g = re.search(r"'gone': (\d+)", ln)
            return tuple(int(x) for x in m.groups()) + (int(g[1]) if g else 0,)
    return None


def pct(f, c):
    return 100.0 * f / (c + f) if c + f else 0.0


def same_ground(events, loop, min_n=5):
    """Every CATCH / FLED onto the loop side it happened on (the fix nearest in time, within 60 m of a side), then
    per speed: flee% on the raw mix and flee% re-weighted to one common mix of sides (each side weighted by its
    encounters over ALL speeds; only sides every speed walked with >= min_n encounters). Prints the table."""
    import dense_loop as dl
    lp = json.load(open(loop))
    pts = [(c["lat"], c["lng"]) for c in lp["corners"]]
    nm = [(c["ave"], c["st"]) for c in lp["corners"]]
    sec = lambda hms: int(hms[:2]) * 3600 + int(hms[3:5]) * 60 + int(hms[6:8])
    cell = defaultdict(lambda: [0, 0])                  # (side, speed) -> [caught, fled]
    off = 0
    for ln in open(events):
        w = json.loads(ln)
        fx = [(sec(t), la, lo) for t, la, lo in w["fixes"]]
        for t, kind in w["events"]:
            if not fx:
                break
            f = min(fx, key=lambda x: abs(x[0] - sec(t)))
            k = min(range(len(pts)), key=lambda j: dl.off_side(f[1:], pts[j], pts[(j + 1) % len(pts)]))
            if abs(f[0] - sec(t)) > 10 or dl.off_side(f[1:], pts[k], pts[(k + 1) % len(pts)]) > 60:
                off += 1
                continue
            a, b = nm[k], nm[(k + 1) % len(pts)]
            side = "%s Ave %s-%s" % (a[0], a[1], b[1]) if a[0] == b[0] else "%s St %s-%s Ave" % (a[1], a[0], b[0])
            cell[(side, w["speed"])][kind == "FLED"] += 1
    speeds = sorted({v for _, v in cell})
    sides = sorted({s for s, _ in cell})
    common = [s for s in sides if all(sum(cell[(s, v)]) >= min_n for v in speeds)]
    tot = {s: sum(sum(cell[(s, v)]) for v in speeds) for s in common}
    n = sum(tot.values())
    print("SAME GROUND (%d events off the loop or unmatched; %d of %d sides walked by every speed, >= %d encounters "
          "each):" % (off, len(common), len(sides), min_n), flush=True)
    for s in sides:
        print("  %-22s %s%s" % (s, "  ".join("%g: %d/%d" % (v, cell[(s, v)][1], sum(cell[(s, v)])) for v in speeds),
                                "" if s in common else "  (not in the common mix)"), flush=True)
    for v in speeds:
        c = sum(cell[(s, v)][0] for s in sides)
        f = sum(cell[(s, v)][1] for s in sides)
        std = sum(tot[s] / n * pct(cell[(s, v)][1], cell[(s, v)][0]) for s in common) if n else float("nan")
        print("  %5.1f km/h: raw flee %4.1f%% (%d of %d) | same-ground flee %4.1f%%" % (v, pct(f, c), f, c + f, std),
              flush=True)


def main():
    if sys.argv[1:2] == ["report"]:
        return same_ground(sys.argv[2], sys.argv[3])
    speeds = [float(x) for x in sys.argv[1:]]
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    if max(speeds) > MAX_KMH:
        sys.exit("refusing: above the %.0f km/h cap" % MAX_KMH)
    start = fix()
    back = round(start[3], 1) if start and start[3] > 1 else None      # the speed it found, to put back
    rows = []
    for sp in speeds:
        bad = guard()
        if bad:
            print(f"{time.strftime('%H:%M:%S')} ALERT: {bad} -- test stopped, nothing sent", flush=True)
            return
        adb(f"am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed {sp}")
        time.sleep(15)
        n0 = lines_count()
        c0 = counters(adb(f"su -c 'tail -n 60 {LOG}'").splitlines())
        t0, p0, moved, last, labels = time.time(), fix(), 0.0, None, []
        last, fixes, w0 = p0, [], time.strftime("%H:%M:%S")
        while time.time() - t0 < SEG:
            time.sleep(2)
            p = fix()
            if p:
                fixes.append((time.strftime("%H:%M:%S"), p[0], p[1]))
            if p and last and p[2] != last[2]:
                d = meters(last, p)
                if d < 300:
                    moved += d
                labels.append(p[3])
            last = p or last
        new = lines_since(n0)
        c1 = counters(new) or c0
        words = Counter()
        vis, trk, empty = [], [], 0
        for ln in new:
            parts = ln.split()
            if len(parts) > 1 and parts[1].isupper() and parts[1] not in ("CATCH", "MINUTE", "TYPES", "READY", "REFRESH:"):
                words[parts[1]] += 1
            m = re.search(r"vis=(\d+) track=(\d+)", ln)
            if m:
                vis.append(int(m[1])); trk.append(int(m[2]))
            if "no Pokemon seen" in ln:
                empty += 1
        catches = sum(1 for ln in new if " CATCH " in ln)
        dt = time.time() - t0
        real = moved / dt * 3.6
        d = [b - a for a, b in zip(c0, c1)] if (c0 and c1) else [catches, 0, 0, 0]
        if d[0] < 0:                          # the catcher restarted inside the window: count its CATCH lines
            d = [catches, 0, sum(1 for ln in new if " FLED " in ln), 0]
        full = any("storage is full" in ln for ln in new)
        row = (sp, real, min(labels or [0]), max(labels or [0]), d[0], d[1], d[2], d[0] / dt * 60,
               sum(vis) / len(vis) if vis else 0, sum(trk) / len(trk) if trk else 0, empty, dict(words), moved, dt)
        print(f"{time.strftime('%H:%M:%S')} SET {sp:5.1f} | real {real:5.2f} km/h (label {row[2]:.1f}..{row[3]:.1f}) | "
              f"caught {d[0]} escaped {d[1]} fled {d[2]} in {dt:.0f}s = {row[7]:.1f}/min, {d[0] / max(moved / 1000, 0.01):.0f}/km "
              f"| flee {pct(d[2], d[0]):.1f}% gone {d[3]} "
              f"| visible avg {row[8]:.1f} tracked {row[9]:.1f} | 'no Pokemon' refreshes {empty} | other outcomes "
              f"{dict(words) or '-'}", flush=True)
        if full:
            print(f"{time.strftime('%H:%M:%S')} BAG FULL -- the catcher holds; this window is not counted and the test stops",
                  flush=True)
            break
        rows.append(row + (d[3],))
        if EVENTS:
            with open(EVENTS, "a") as fh:
                fh.write(json.dumps({"speed": sp, "t0": w0, "t1": time.strftime("%H:%M:%S"), "fixes": fixes,
                                     "events": [(ln.split()[0], ln.split()[1]) for ln in new
                                                if len(ln.split()) > 1 and ln.split()[1] in ("CATCH", "FLED")]}) + "\n")
    tot = defaultdict(lambda: [0, 0, 0, 0.0, 0.0, 0, 0])
    for r in rows:
        t = tot[r[0]]
        t[0] += r[4]; t[1] += r[5]; t[2] += r[6]; t[3] += r[12]; t[4] += r[13]; t[5] += 1; t[6] += r[14]
    print("SUMMARY (per speed, all its windows):", flush=True)
    for sp in sorted(tot):
        c, e, f, m, sec, n, g = tot[sp]
        print(f"  {sp:5.1f} km/h: {n} window(s) {sec / 60:4.1f} min {m / 1000:5.2f} km | caught {c} = {c / sec * 60:5.1f}/min "
              f"{c / max(m / 1000, 0.01):5.1f}/km | escaped {e} fled {f} = flee {pct(f, c):.1f}% | gone {g}", flush=True)
    if EVENTS and LOOP:
        same_ground(EVENTS, LOOP)
    if back and guard() is None:
        adb(f"am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed {back}")
        print(f"back on {back} km/h (what it found). done", flush=True)
    else:
        print("done -- speed NOT put back (no starting speed, or the guard failed)", flush=True)


if __name__ == "__main__":
    main()
