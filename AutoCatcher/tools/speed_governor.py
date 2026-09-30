"""Speed governor for GPS JoyStick (Pro Intents API) while the on-phone catcher runs.

User 2026-09-30: "3 ok check and drive the joystick, I paid for Pro for a reason ... be aware of where you're walking.
I'm sure it goes up when I'm on my route rn to Bryant Park back and forth to Central Park."

What it does, every SAMPLE_S seconds (cloud side, over adb):
  1. reads the mocked GPS fix the game sees (dumpsys location: lat, lng, speed, bearing) -> where we are walking;
  2. reads the catcher's latest 10 s run line (vis / track / pend = something to catch, caught, gone);
  3. picks a speed: BUSY_KMH for IDLE_S after a Pokemon escaped out of range ('gone' went up), else FAST_KMH
     (PARK_KMH inside a park); never above MAX_KMH. A busy screen alone does not slow it (measured: saved nothing);
  4. sends theappninjas.gpsjoystick.SPEED only when the target changes (and speeds up only after IDLE_S of nothing).
It NEVER teleports, starts/stops a route or touches anything else. It stands still (sends nothing) when the fix jumps
(a teleport of his), when the walk is stopped (speed ~0), or when the position is outside the Midtown corridor.
On exit it puts the speed back to RESTORE_KMH. Every sample goes to a CSV, so catches/min per speed can be checked.

  python tools/speed_governor.py --csv <file> [--minutes 60] [--dry]
"""
import argparse, csv, math, os, re, signal, subprocess, sys, time

ADB = os.environ.get("ADB_TARGET", "100.98.158.56:5555")
LOG = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod/catch_loop.log"
HERE = os.path.dirname(os.path.abspath(__file__))

MAX_KMH = 28.0       # hard cap (the 3 ok was "under ~32 km/h, moderate ban risk")
FAST_KMH = 28.0      # the catcher keeps up: sweep more ground (catches scale with distance covered, ~30-40 wild/km)
PARK_KMH = 28.0      # parks: same until the data says otherwise -- dense spawns trip the backlog rule by themselves
BUSY_KMH = 16.0      # a Pokemon escaped out of range ('gone' went up): let the catcher finish for IDLE_S
# NO BACKLOG SLOW-DOWN (measured 2026-09-30 03:08-03:16: slowing on a busy screen saved 0 escapes -- 'gone' never moved
# in 7 min, 16.4 caught/min vs 12.6 at a steady 20). Same as docs/memory: loss rate is flat with speed, "Do NOT slow the
# route for catch rate". Only a real escape slows it now.
BACKLOG_PEND = 10 ** 6
BACKLOG_SEEN = 10 ** 6
RESTORE_KMH = 20.0   # what he had set (measured 20.0 km/h at 03:03) -- put back on exit
IDLE_S = 20          # speed up only after this long with nothing to catch
SAMPLE_S = 5
JUMP_M = 300         # a fix that moved more than this between samples = a teleport: hands off for HOLD_S
HOLD_S = 300

# Where we walk: Bryant Park (40th-42nd St, 5th-6th Ave) and Central Park (rotated rectangle, 59th-110th St).
PARKS = {
    "Bryant Park": [(40.75247, -73.98483), (40.75400, -73.98126), (40.75501, -73.98200), (40.75347, -73.98559)],
    "Central Park": [(40.76812, -73.98186), (40.76440, -73.97296), (40.79690, -73.94935), (40.80053, -73.95813)],
}
# Where it may drive: Midtown 30th-60th St, 9th Ave-3rd Ave, plus Central Park to 110th St. Outside it, hands off.
# (2026-09-30 03:35: tools/dense_loop.py walks 32nd-53rd St, 8th Ave-3rd Ave.)
CORRIDOR = (40.740, 40.802, -73.998, -73.947)


def inside(poly, lat, lng):
    """Point-in-polygon (ray casting) on lat/lng -- fine at park scale."""
    n, hit = len(poly), False
    for i in range(n):
        (y1, x1), (y2, x2) = poly[i], poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def meters(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def sh(cmd, root=False, timeout=20):
    c = ["adb", "-s", ADB, "shell", "su -c '%s'" % cmd if root else cmd]
    return subprocess.run(c, capture_output=True, text=True, timeout=timeout).stdout


def fix():
    """(lat, lng, kmh, bearing) of the mocked GPS fix the game is fed, or None."""
    m = re.search(r"last mock location=Location\[gps ([\d.\-]+),([\d.\-]+).*?vel=([\d.]+)(?:.*?bear=([\d.]+))?",
                  sh("dumpsys location"))
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)) * 3.6, float(m.group(4) or 0)) if m else None


RUN = re.compile(r"^(\d\d:\d\d:\d\d) run (\d+)s \| caught=(\d+) .*? vis=(\d+) track=(\d+) pend=(\d+).*?skip=(\{[^}]*\})")


def catcher():
    """The catcher's latest run line -> dict(t, run_s, caught, vis, track, pend, gone), or None."""
    for line in reversed(sh("tail -c 6000 %s" % LOG, root=True).splitlines()):
        m = RUN.search(line)
        if m:
            g = re.search(r"'gone': (\d+)", m.group(7))
            return dict(t=m.group(1), run_s=int(m.group(2)), caught=int(m.group(3)), vis=int(m.group(4)),
                        track=int(m.group(5)), pend=int(m.group(6)), gone=int(g.group(1)) if g else 0)
    return None


def guard():
    """None when it is safe to send a command, else why not (docs/memory/reference-gps-joystick-control.md):
    - the joystick's :overlay process is gone -> the spoof stopped and the REAL location can reach PoGo. Any intent now
      would auto-launch the joystick app over the game. Send nothing; Benny decides (never restart PoGo from here).
    - a GPS JoyStick screen has the focus -> the Pro gate ("GATE_REQUIRED") popped over the game once (2026-09-25)."""
    if not sh("pidof com.theappninjas.fakegpsjoystick:overlay").strip():
        return "JOYSTICK OVERLAY GONE -- spoof stopped, the real GPS may reach PoGo"
    foc = re.search(r"mCurrentFocus=\S+ \S+ (\S+)\}", sh("dumpsys window | grep mCurrentFocus"))
    if foc and foc.group(1).startswith("com.theappninjas.fakegpsjoystick"):
        return "a GPS JoyStick screen is in front (%s)" % foc.group(1)
    return None


def set_speed(kmh, dry):
    kmh = min(float(kmh), MAX_KMH)
    if dry:
        return "dry"
    out = sh("am start-foreground-service -a theappninjas.gpsjoystick.SPEED --ef speed %.1f" % kmh)
    return "ok" if "Starting service" in out else out.strip()[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--dry", action="store_true", help="decide and log, send nothing")
    ap.add_argument("--csv", required=True, help="where every sample is logged (keep it out of git)")
    a = ap.parse_args()
    CSV = a.csv
    new = not os.path.exists(CSV)
    fh = open(CSV, "a", newline="")
    wr = csv.writer(fh)
    if new:
        wr.writerow(["time", "lat", "lng", "kmh", "bearing", "place", "vis", "track", "pend", "caught", "gone",
                     "target", "sent", "why"])
    end = time.time() + a.minutes * 60
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # a stop from outside still runs the restore below
    last_fix, target, last_busy, hold_until, last_gone, alarm, said = None, None, 0.0, 0.0, None, None, ""
    print("speed governor: %s, cap %.0f km/h (fast %.0f / park %.0f / busy %.0f), restore %.0f on exit -> %s"
          % ("DRY RUN" if a.dry else "LIVE", MAX_KMH, FAST_KMH, PARK_KMH, BUSY_KMH, RESTORE_KMH, CSV), flush=True)
    try:
        while time.time() < end:
            t0 = time.time()
            f, c = fix(), catcher()
            why, want = "", None
            bad = guard()
            if bad:
                if bad != alarm:
                    print("%s ALERT: %s -- sending nothing until it clears" % (time.strftime("%H:%M:%S"), bad), flush=True)
                alarm = bad
                f = None                          # no decision this sample
                why = bad
            elif alarm:
                print("%s ALERT cleared: %s" % (time.strftime("%H:%M:%S"), alarm), flush=True)
                alarm = None
            if bad:
                pass
            elif f is None or c is None:
                why = "no fix" if f is None else "no catcher line"
            else:
                lat, lng, kmh, bear = f
                place = next((p for p, poly in PARKS.items() if inside(poly, lat, lng)), "street")
                if last_fix and meters(last_fix, (lat, lng)) > JUMP_M:
                    hold_until = time.time() + HOLD_S
                    why = "fix jumped %.0f m (teleport?) -- hands off %d s" % (meters(last_fix, (lat, lng)), HOLD_S)
                elif time.time() < hold_until:
                    why = "hands off after a jump"
                elif not (CORRIDOR[0] <= lat <= CORRIDOR[1] and CORRIDOR[2] <= lng <= CORRIDOR[3]):
                    why = "outside the Bryant Park - Central Park corridor -- hands off"
                elif kmh < 1.0:
                    why = "not walking (route paused or stopped) -- hands off"
                else:
                    escaped = last_gone is not None and 0 < c["gone"] - last_gone < 50   # a restart resets it: ignore
                    busy = c["pend"] >= BACKLOG_PEND or c["vis"] + c["track"] >= BACKLOG_SEEN or escaped
                    if busy:
                        last_busy = time.time()
                    if busy or time.time() - last_busy < IDLE_S:
                        want, why = BUSY_KMH, "backed up (vis %d track %d pend %d%s)" % (
                            c["vis"], c["track"], c["pend"], ", %d escaped" % (c["gone"] - last_gone) if escaped else "")
                    elif place != "street":
                        want, why = PARK_KMH, "in %s, keeping up" % place
                    else:
                        want, why = FAST_KMH, "street, keeping up"
                last_fix = (lat, lng)
            if c is not None:
                last_gone = c["gone"]
            sent = ""
            if want is not None and want != target:
                sent = set_speed(want, a.dry)
                target = want
                print("%s speed -> %.0f km/h (%s) [%s]" % (time.strftime("%H:%M:%S"), want, why, sent), flush=True)
            elif want is None and why and why != said:
                print("%s %s" % (time.strftime("%H:%M:%S"), why), flush=True)   # once per new reason, not every 5 s
            said = why if want is None else ""
            wr.writerow([time.strftime("%Y-%m-%d %H:%M:%S")] + (
                ["%.6f" % f[0], "%.6f" % f[1], "%.1f" % f[2], "%.0f" % f[3],
                 next((p for p, poly in PARKS.items() if inside(poly, f[0], f[1])), "street")] if f else [""] * 5)
                + ([c["vis"], c["track"], c["pend"], c["caught"], c["gone"]] if c else [""] * 5)
                + [target or "", sent, why])
            fh.flush()
            time.sleep(max(0.5, SAMPLE_S - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        if target is not None and not a.dry and guard() is None:   # never poke a dead joystick (it would pop its app)
            print("%s restoring %.0f km/h [%s]" % (time.strftime("%H:%M:%S"), RESTORE_KMH, set_speed(RESTORE_KMH, False)),
                  flush=True)
        fh.close()


if __name__ == "__main__":
    sys.exit(main())
