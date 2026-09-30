"""Midtown dense loop: sweep the avenues where the catcher actually catches most, one lap ~ one spawn's life.

User 2026-09-30: "Only walk thru high density high lure areas exclusively. Map everything from mid Central Park to
Bryant Park ... I'm sure there's a super fancy formula or tactics you can do".

Why this shape (measured 2026-09-30 03:08-03:31, speed_governor CSV, catches per km walked on the old
Bryant Park <-> Central Park route): Bryant Park 58/km, 42nd-50th St 41-63/km, 50th-57th 27/km, 57th-60th 16/km,
Central Park 24/km. Lure history (pogo_wigle.db, 354 lure events, 2026-09-25 03:13-06:14): two thirds within ~500 m
of Bryant Park / Times Sq -- but that scan walked mostly there, so it says little about elsewhere.
The formula: a wild spawn lives ~30 min and each spawn point fires once an hour. A lap shorter than 30 min comes back
to spots whose spawn it already caught; a lap longer than 30 min lets spawns expire unseen. So: the densest ground,
walked as one loop that takes ~25-30 min at the speed cap, never the same block twice in a lap. Avenues are ~270 m
apart and the game shows Pokemon within ~140 m, so one lane per avenue covers the ground between them.

Loop (street numbers are Manhattan's): up 8th Ave 42nd->N, east on N, down 7th to S, east on S, up 6th, east on N,
down 5th, east on S, up Park, east on N, down 3rd to 42nd, west on 42nd (Grand Central, Bryant Park, Times Sq) to 8th.

  python tools/dense_loop.py [--south 32] [--north 53] [--speed 28] [--laps 2]          plan only (prints km, minutes)
  python tools/dense_loop.py --send ...                                                    hand it to GPS JoyStick WALK
It never teleports: the walk starts at the far corner of the loop side nearest the current fix (the corner ahead,
so a re-send mid-lap carries straight on) and the joystick walks there.
"""
import argparse, json, math, os, re, sys, time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cutoff_hunt as ch          # noqa: E402  adb(), fix(), meters(), api()
import route_planner as rp        # noqa: E402  rp.WAYS = system/map/manhattan_ways.json
from grid_routes import AVE_NAMES, ROADS, street_no   # noqa: E402

LANES = [8, 7, 6, 5, 4, 3]        # 8th, 7th, 6th, 5th, Park, 3rd
BBOX = (40.735, -74.005, 40.800, -73.955)   # S, W, N, E: Midtown Manhattan only


def intersections(streets):
    """(avenue, street) -> (lat, lng) from the OpenStreetMap road ways."""
    d = json.load(open(rp.WAYS, encoding="utf-8"))
    ave_at, st_at, pos = defaultdict(set), defaultdict(set), {}
    for el in d["elements"]:
        t = el.get("tags", {})
        if el["type"] != "way" or t.get("highway") not in ROADS:
            continue
        ave, st = AVE_NAMES.get(t.get("name", "")), street_no(t.get("name", ""))
        if (ave not in LANES) and (st not in streets):
            continue
        for nid, g in zip(el.get("nodes") or [], el.get("geometry") or []):
            if not (BBOX[0] <= g["lat"] <= BBOX[2] and BBOX[1] <= g["lon"] <= BBOX[3]):
                continue                  # the file has New Jersey too (Park Ave & 42nd St in Weehawken)
            pos[nid] = (g["lat"], g["lon"])
            if ave in LANES:
                ave_at[nid].add(ave)
            elif st in streets:
                st_at[nid].add(st)
    out = defaultdict(list)
    for nid in set(ave_at) & set(st_at):
        for a in ave_at[nid]:
            for s in st_at[nid]:
                out[(a, s)].append(pos[nid])
    # a divided avenue gives two nodes per corner: use their middle
    return {k: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for k, v in out.items()}


def off_side(p, a, b):
    """Metres from point p to the segment a-b (flat projection; fine at block scale)."""
    k = 111320.0 * math.cos(math.radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * k, a[0] * 111320.0, b[1] * k, b[0] * 111320.0, p[1] * k, p[0] * 111320.0
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1.0)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def loop(south, north):
    """The corner sequence of one lap (see the docstring)."""
    seq = [(8, 42), (8, north), (7, north), (7, south), (6, south), (6, north), (5, north), (5, south),
           (4, south), (4, north), (3, north), (3, 42), (5, 42), (6, 42), (7, 42)]   # Park Ave crosses 42nd on the viaduct
    return seq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--south", type=int, default=32)
    ap.add_argument("--north", type=int, default=53)
    ap.add_argument("--speed", type=float, default=28.0)
    ap.add_argument("--laps", type=int, default=2)
    ap.add_argument("--send", action="store_true", help="hand the loop to GPS JoyStick (WALK); default: plan only")
    ap.add_argument("--out", help="write the lap as JSON (for the map page)")
    a = ap.parse_args()
    if a.speed > 28.0:
        sys.exit("speed cap is 28 km/h")
    corners = loop(a.south, a.north)
    xy = intersections({a.south, a.north, 42})
    miss = [c for c in corners if c not in xy]
    if miss:
        sys.exit("no OpenStreetMap corner for %s" % miss)
    pts = [xy[c] for c in corners]
    lap_m = sum(ch.meters(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
    print("lap: %d corners, %.2f km = %.1f min at %.0f km/h (real ~%.1f)" % (
        len(pts), lap_m / 1000, lap_m / 1000 / (a.speed * 0.992) * 60, a.speed, a.speed * 0.992))
    if a.out:
        json.dump({"south": a.south, "north": a.north, "speed": a.speed, "lap_km": round(lap_m / 1000, 2),
                   "corners": [{"ave": c[0], "st": c[1], "lat": p[0], "lng": p[1]} for c, p in zip(corners, pts)]},
                  open(a.out, "w"), indent=1)
    if not a.send:
        return
    if "Pixel" not in ch.adb("getprop ro.product.model"):
        sys.exit("not the phone")
    if not ch.adb("pidof com.theappninjas.fakegpsjoystick:overlay").strip():
        sys.exit("GPS Joystick overlay is not running -- not sending")
    here = ch.fix()
    if not here:
        sys.exit("no mock fix")
    # start at the END of the loop side we are on (or nearest to), so a re-send never turns back
    i = (min(range(len(pts)), key=lambda k: off_side(here[:2], pts[k], pts[(k + 1) % len(pts)])) + 1) % len(pts)
    seq = [pts[(i + k) % len(pts)] for k in range(len(pts) * a.laps + 1)]
    wp = ";".join("%.6f,%.6f" % p for p in seq)
    ch.api("WALK", '--es waypoints "%s" --ez teleport false --ef speed %.1f' % (wp, a.speed))
    print("%s sent %d waypoints (%d laps) from %s St & %s; start corner %.0f m from the fix %.6f,%.6f" % (
        time.strftime("%H:%M:%S"), len(seq), a.laps, corners[i][1], corners[i][0], ch.meters(here[:2], pts[i]),
        here[0], here[1]))
    for _ in range(4):
        time.sleep(3)
        print("  fix:", ch.fix())


if __name__ == "__main__":
    main()
