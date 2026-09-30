"""Does the auto-catcher keep catching at speed? SPEED (GPS Joystick Pro API) steps, catcher log as the record.

  python tools/catch_speed_test.py 10.6 15 20 25 30      [SEG seconds per speed, default 120]

Per speed: SPEED X, 15 s settle, then SEG seconds counted from the catcher's own log on the phone:
caught / escaped / fled (from its cumulative run counters), every other outcome word (NORESULT, errors...),
"no Pokemon seen" refreshes and the average Pokemon visible/tracked; plus the measured real speed.
Stays well under the 32.19 km/h "too fast" warning (8.9408 m/s). Ends back on 10.6.
"""
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # cloud: the Tailscale bridge exports ADB_TARGET
LOG = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod/catch_loop.log"
SEG = int(os.environ.get("SEG", "120"))


def adb(cmd):
    return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""


def lines_count():
    return int((adb(f"su -c 'wc -l < {LOG}'").strip() or "0"))


def lines_since(n):
    return adb(f"su -c 'tail -n +{n + 1} {LOG}'").splitlines()


def fix():
    m = re.search(r"Location\[gps ([-0-9.]+),([-0-9.]+) .*?et=\+(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?(?:(\d+)ms)?.*?vel=([0-9.]+)",
                  adb("dumpsys location | grep -m1 'last mock location'"))
    if not m:
        return None
    et = int(m[3] or 0) * 3600 + int(m[4] or 0) * 60 + int(m[5] or 0) + int(m[6] or 0) / 1000
    return float(m[1]), float(m[2]), et, float(m[7]) * 3.6


def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def counters(lines):
    for ln in reversed(lines):
        m = re.search(r" run \d+s \| caught=(-?\d+) esc=(-?\d+) flee=(-?\d+)", ln)
        if m:
            return tuple(int(x) for x in m.groups())
    return None


def main():
    speeds = [float(x) for x in sys.argv[1:]]
    if "Pixel" not in adb("getprop ro.product.model"):
        sys.exit("not the phone")
    if max(speeds) >= 32:
        sys.exit("refusing: at or above the 32.19 km/h warning")
    rows = []
    for sp in speeds:
        adb(f"am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed {sp}")
        time.sleep(15)
        n0 = lines_count()
        c0 = counters(adb(f"su -c 'tail -n 60 {LOG}'").splitlines())
        t0, p0, moved, last, labels = time.time(), fix(), 0.0, None, []
        last = p0
        while time.time() - t0 < SEG:
            time.sleep(2)
            p = fix()
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
        d = [b - a for a, b in zip(c0, c1)] if (c0 and c1) else [catches, 0, 0]
        row = (sp, real, min(labels or [0]), max(labels or [0]), d[0], d[1], d[2], catches / dt * 60,
               sum(vis) / len(vis) if vis else 0, sum(trk) / len(trk) if trk else 0, empty, dict(words))
        rows.append(row)
        print(f"{time.strftime('%H:%M:%S')} SET {sp:5.1f} | real {real:5.2f} km/h (label {row[2]:.1f}..{row[3]:.1f}) | "
              f"caught {d[0]} escaped {d[1]} fled {d[2]} in {dt:.0f}s = {row[7]:.1f}/min | visible avg {row[8]:.1f} "
              f"tracked {row[9]:.1f} | 'no Pokemon' refreshes {empty} | other outcomes {dict(words) or '-'}", flush=True)
    adb("am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed 10.6")
    print("back on 10.6. done", flush=True)


if __name__ == "__main__":
    main()
