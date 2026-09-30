"""Route through every PokéStop the game says you have never spun (Visited = false), in straight lines -- no streets.

  python tools/route_unspun.py plan [--scope all|confirmed] [--pass 40] [--leg-km 10.4] [--speed 10.4]
  python tools/route_unspun.py status                      how many of the route's stops show Visited now
  python tools/route_unspun.py walk [--leg N] [--speed S]  hand one leg to GPS Joystick (WALK) -- touches the phone

How the plan is built:
  1. every never-spun stop in the bank (scope 'all' also takes the 03:13 one-time read, which agreed with the live scan
     on 956/956 overlapping stops);
  2. one closed tour from where you are now: nearest neighbour, then 2-opt and Or-opt until nothing improves;
  3. the path only has to come within --pass metres of each stop (the game's spin range is
     FortSettings.InteractionRangeMeters = 80), so each waypoint slides toward its neighbours and waypoints the path
     already passes are dropped; every stop is then re-checked against the final line;
  4. the tour is cut into legs of about --leg-km that chain end to start, the last leg returning to where you began.
Writes system/map/routes/active_route.json (drawn by tools/map_live.py) and one GPX per leg for GPS Joystick's import.
"""
import argparse
import json
import math
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
DB = os.path.join(ROOT, "system", "map", "pogo_wigle.db")
RDIR = os.path.join(ROOT, "system", "map", "routes")
ACTIVE = os.path.join(RDIR, "active_route.json")
SEED = "first_seen='2026-09-25 03:13:57' AND last_seen='2026-09-25 03:13:57'"   # known only from the one-time read
SPIN_RANGE = 80.0                                                                 # FortSettings.InteractionRangeMeters


class Proj:
    """Local flat projection in metres (error well under 0.1% across Manhattan)."""
    def __init__(self, lat0, lng0):
        self.lat0, self.lng0 = lat0, lng0
        self.kx = 111320.0 * math.cos(math.radians(lat0))
        self.ky = 110574.0

    def xy(self, lat, lng):
        return ((lng - self.lng0) * self.kx, (lat - self.lat0) * self.ky)

    def ll(self, x, y):
        return (self.lat0 + y / self.ky, self.lng0 + x / self.kx)


def d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    L2 = ax * ax + ay * ay
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L2))
    return math.hypot(p[0] - a[0] - t * ax, p[1] - a[1] - t * ay)


def tour(P):
    """Closed tour over P (P[0] = fixed start). Nearest neighbour, then 2-opt + Or-opt to a local optimum."""
    n = len(P)
    left, t = set(range(1, n)), [0]
    while left:
        c = P[t[-1]]
        j = min(left, key=lambda k: d(c, P[k]))
        left.remove(j)
        t.append(j)
    D = lambda i, j: d(P[t[i % n]], P[t[j % n]])
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):                                   # 2-opt: reverse t[i..k]
            for k in range(i + 1, n):
                if D(i - 1, k) + D(i, k + 1) + 1e-6 < D(i - 1, i) + D(k, k + 1):
                    t[i:k + 1] = t[i:k + 1][::-1]
                    improved = True
        for L in (1, 2, 3):                                          # Or-opt: move a run of L stops elsewhere
            i = 1
            while i + L <= n:
                run = t[i:i + L]
                a, b = t[i - 1], t[(i + L) % n]
                gain = d(P[a], P[run[0]]) + d(P[run[-1]], P[b]) - d(P[a], P[b])
                rest = t[:i] + t[i + L:]
                best, where, rev = 1e-6, None, False
                for j in range(len(rest)):
                    u, v = P[rest[j]], P[rest[(j + 1) % len(rest)]]
                    for r in (False, True):
                        s, e = (run[-1], run[0]) if r else (run[0], run[-1])
                        c = d(u, P[s]) + d(P[e], v) - d(u, v)
                        if gain - c > best:
                            best, where, rev = gain - c, j, r
                if where is not None:
                    seg = run[::-1] if rev else run
                    t = rest[:where + 1] + seg + rest[where + 1:]
                    if t[0] != 0:                                    # keep the start first
                        z = t.index(0)
                        t = t[z:] + t[:z]
                    improved = True
                else:
                    i += 1
    return t


def slide(stops, R, passes=12, pinned=frozenset()):
    """Waypoints for a closed loop through `stops` (stops[0] = the start, kept exact). Each other waypoint moves to
    the point within R of its stop that shortens prev->w->next; a waypoint the straight prev->next line already passes
    within R is dropped. Returns the waypoint list (closed: returns to waypoint 0)."""
    W = [list(s) for s in stops]
    keep = [True] * len(W)
    for _ in range(passes):
        idx = [i for i in range(len(W)) if keep[i]]
        for pos in range(1, len(idx)):
            i = idx[pos]
            a = W[idx[pos - 1]]
            b = W[idx[(pos + 1) % len(idx)]]
            s = stops[i]
            if i not in pinned and seg_dist(s, a, b) <= R:
                keep[i] = False                                      # the line already comes within range
                continue
            best, bw = None, None
            for k in range(144):                                     # the optimum sits on the circle of radius R
                ang = 2 * math.pi * k / 144
                w = (s[0] + R * math.cos(ang), s[1] + R * math.sin(ang))
                c = d(a, w) + d(w, b)
                if best is None or c < best:
                    best, bw = c, w
            W[i] = [bw[0], bw[1]]
    return [tuple(W[i]) for i in range(len(W)) if keep[i]]


def poly_len(pts):
    return sum(d(a, b) for a, b in zip(pts, pts[1:]))


def min_dist_to_path(p, pts):
    return min(seg_dist(p, a, b) for a, b in zip(pts, pts[1:]))


def gpx(path, name, lls):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<gpx version="1.1" creator="route_unspun" xmlns="http://www.topografix.com/GPX/1/1">\n'
                 f'<rte><name>{name}</name>\n')
        for i, (la, lo) in enumerate(lls):
            fh.write(f'<rtept lat="{la:.6f}" lon="{lo:.6f}"><name>{i + 1}</name></rtept>\n')
        fh.write('</rte>\n</gpx>\n')


def plan(a):
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    me = db.execute("SELECT lat, lng, t FROM track ORDER BY t DESC LIMIT 1").fetchone()
    start, at = (me[0], me[1]), me[2]
    fix_age = time.time() - time.mktime(time.strptime(at[:19], "%Y-%m-%d %H:%M:%S"))
    if fix_age > 60:
        print(f"WARNING: the start position is the scanner's last fix from {at} ({fix_age / 60:.0f} min old);"
              f" the route starts there, not necessarily where you are now")
    where = "1" if a.scope == "all" else f"NOT ({SEED})"
    rows = db.execute(f"SELECT id, lat, lng, COALESCE(name, ''), ({SEED}) FROM forts WHERE kind='stop' AND visited=0 AND {where}").fetchall()
    allstops = db.execute("SELECT lat, lng, visited FROM forts WHERE kind='stop'").fetchall()
    if not rows:
        sys.exit("no unspun stops in the bank for that scope")
    pj = Proj(*start)
    P = [pj.xy(*start)] + [pj.xy(r[1], r[2]) for r in rows]
    t0 = time.time()
    order = tour(P)
    on_stop = poly_len([P[i] for i in order] + [P[0]])
    ordered = [P[i] for i in order]
    pinned = set()
    for _ in range(8):                      # a stop left out of range by a later slide gets pinned and re-planned
        W = slide(ordered, a.pass_m, pinned=frozenset(pinned))
        loop = W + [W[0]]
        miss = [k for k in range(1, len(ordered)) if min_dist_to_path(ordered[k], loop) > a.pass_m + 0.5]
        if not miss:
            break
        pinned.update(miss)
    total = poly_len(loop)
    worst = max(min_dist_to_path(P[i], loop) for i in range(1, len(P)))
    if worst > a.pass_m + 0.5:
        sys.exit(f"check failed: a stop is {worst:.1f} m from the path (limit {a.pass_m} m)")
    # cut into legs of about leg_km that chain end -> start
    nlegs = 1 if a.leg_km <= 0 else max(1, round(total / (a.leg_km * 1000)))
    target = total / nlegs
    legs, cur, acc = [], [loop[0]], 0.0
    for p, q in zip(loop, loop[1:]):
        acc += d(p, q)
        cur.append(q)
        if acc >= target * (len(legs) + 1) - 1e-6 and len(legs) < nlegs - 1:
            legs.append(cur)
            cur = [q]
    legs.append(cur)
    # stops (by id) each leg covers, and how many stops in all the GO Plus may spin on it (within 80 m)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(RDIR, exist_ok=True)
    out_legs = []
    for n, leg in enumerate(legs, 1):
        cov = [rows[i - 1][0] for i in range(1, len(P)) if min_dist_to_path(P[i], leg) <= a.pass_m + 0.5]
        near = sum(1 for la, lo, v in allstops if min_dist_to_path(pj.xy(la, lo), leg) <= SPIN_RANGE)
        lls = [pj.ll(*p) for p in leg]
        km = poly_len(leg) / 1000
        name = a.name if len(legs) == 1 else f"{a.name} {n} of {len(legs)}"
        fn = os.path.join(RDIR, f"unspun_{stamp}_leg{n}.gpx")
        gpx(fn, name, lls)
        out_legs.append({"n": n, "name": name, "km": round(km, 2), "minutes": round(km / a.speed * 60), "unspun": len(cov),
                         "stops_in_spin_range": near, "gpx": fn, "points": [[round(x, 6), round(y, 6)] for x, y in lls],
                         "waypoints": ";".join(f"{x:.6f},{y:.6f}" for x, y in lls[1:])})
    out = {"kind": "unspun", "created": time.strftime("%Y-%m-%d %H:%M:%S"), "scope": a.scope, "start": list(start),
           "start_fix_at": at, "speed_kmh": a.speed, "pass_m": a.pass_m, "km": round(total / 1000, 2),
           "minutes": round(total / 1000 / a.speed * 60), "km_touching_each_stop": round(on_stop / 1000, 2),
           "worst_stop_distance_m": round(worst, 1),
           "stops": [{"id": r[0], "lat": r[1], "lng": r[2], "name": r[3], "seed_only": bool(r[4])} for r in rows],
           "legs": out_legs}
    json.dump(out, open(os.path.join(RDIR, f"unspun_{stamp}.json"), "w", encoding="utf-8"), indent=1)
    json.dump(out, open(ACTIVE, "w", encoding="utf-8"), indent=1)
    seed = sum(1 for r in rows if r[4])
    print(f"{len(rows)} never-spun stops ({seed} from the 03:13 read) | planned in {time.time() - t0:.0f} s")
    print(f"closed loop {total / 1000:.1f} km (stepping onto every stop would be {on_stop / 1000:.1f} km);"
          f" every stop within {worst:.1f} m of the line (limit {a.pass_m:g} m)")
    for L in out_legs:
        print(f"  {L['name']}: {L['km']:.1f} km, ~{L['minutes']} min at {a.speed:g} km/h, {L['unspun']} unspun stops,"
              f" {L['stops_in_spin_range']} stops in all within 80 m, {len(L['points'])} waypoints")


def status(a):
    r = json.load(open(ACTIVE, encoding="utf-8"))
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ids = [s["id"] for s in r["stops"]]
    got = {i: (v, ls) for i, v, ls in db.execute("SELECT id, visited, last_seen FROM forts WHERE id IN (%s)"
                                                  % ",".join("?" * len(ids)), ids).fetchall()}
    done = sum(1 for i in ids if (got.get(i) or (0, ""))[0])
    unseen = [i for i in ids if not (got.get(i) or (0, ""))[0] and (got.get(i) or (0, ""))[1] < r["created"]]
    last = db.execute("SELECT MAX(t) FROM replies").fetchone()[0]
    print(f"{done}/{len(ids)} of the route's stops show Visited in the game's map data (last map reply {last})")
    print(f"  not visited, seen since the plan ({r['created']}): {len(ids) - done - len(unseen)}")
    print(f"  not re-seen since the plan -- spun state unknown, the scanner has not passed them: {len(unseen)}")


def walk(a):
    sys.path.insert(0, HERE)
    import cutoff_hunt as ch
    r = json.load(open(ACTIVE, encoding="utf-8"))
    leg = r["legs"][a.leg - 1]
    if "Pixel" not in ch.adb("getprop ro.product.model"):
        sys.exit("not the phone")
    if not ch.adb("pidof com.theappninjas.fakegpsjoystick:overlay").strip():
        sys.exit("GPS Joystick is not running -- not sending a route")
    speed = a.speed or r["speed_kmh"]
    ch.api("WALK", f'--es waypoints "{leg["waypoints"]}" --ef speed {speed}')
    time.sleep(3)
    print(f"sent {leg['name']} ({len(leg['points']) - 1} waypoints) at {speed} km/h; phone now reports {ch.fix()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "status", "walk"])
    ap.add_argument("--scope", choices=["all", "confirmed"], default="all")
    ap.add_argument("--pass", dest="pass_m", type=float, default=40.0)
    ap.add_argument("--leg-km", type=float, default=10.4)
    ap.add_argument("--speed", type=float, default=10.4)
    ap.add_argument("--leg", type=int, default=1)
    ap.add_argument("--name", default="Unspun Manhattan")
    a = ap.parse_args()
    if a.cmd == "walk" and not any(x.startswith("--speed") for x in sys.argv):
        a.speed = None
    {"plan": plan, "status": status, "walk": walk}[a.cmd](a)


if __name__ == "__main__":
    main()
