"""Plan walking loops through the densest PokeStops/gyms the GAME reports, along real walkable ways (OpenStreetMap).

  python tools/route_planner.py plan --km 4 [--bbox S,W,N,E] [--near LAT,LNG] [--name NAME]
                                     [--spots map|bank] [--pattern loop|clover] [--petals 4]
  python tools/route_planner.py hubs [--bbox S,W,N,E] [--spots map|bank] [--n 5] [--sep 1200]

hubs prints the n densest centres (stops + gyms within 300 m), at least --sep metres apart: where to centre a route
(pass one as --near).

Spots come from system/analysis/map_full.json (map_read.py: PokemonFortProto read live from PoGo), or with
--spots bank from the scanner's bank system/map/pogo_wigle.db (pogo_wigle.py: every map reply while you walk). A spot
is COVERED when the path passes within 80 m (FortSettings.InteractionRangeMeters); each spot counts once per lap.
Ways: manhattan_ways.json inside Manhattan; anywhere else the bbox's walkable ways are downloaded once from
Overpass and cached as system/map/ways_S_W_N_E.json.
The loop is built with a prize-collecting insertion heuristic on the walking graph (sidewalks, crossings,
footpaths, plazas, indoor corridors, steps; no motorways): keep adding the anchor with the best
new-spots-per-extra-metre until the length budget is used, then 2-opt. --pattern clover splits the budget into
PETALS loops that all start and end at the densest hub (the anchor with the most spots within 150 m), one per
compass sector (borders rotated to balance the sectors); every petal is at least MIN_PETAL_M, so the hub's stops are
off their 5-min cooldown each time a petal brings you back. Output: waypoints for the GPS Joystick WALK command, a
GPX file (importable as a saved joystick route) and an HTML map.
"""
import argparse
import glob
import heapq
import html
import json
import math
import os
import pickle
import sqlite3
import time
import urllib.parse
import urllib.request
from collections import defaultdict

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
WAYS = os.path.join(ROOT, "system", "map", "manhattan_ways.json")
MANHATTAN = (40.70, -74.02, 40.88, -73.91)                       # S, W, N, E fully covered by WAYS
OVERPASS = "https://overpass-api.de/api/interpreter"
SPOTS = os.path.join(ROOT, "system", "analysis", "map_full.json")
BANK = os.path.join(ROOT, "system", "map", "pogo_wigle.db")
OUTDIR = os.path.join(ROOT, "system", "map", "routes")
RANGE = 80.0
MIN_PETAL_M = 900.0                                               # 5 min at 10.6 km/h = a stop's spin cooldown
WALKABLE = {"footway", "pedestrian", "path", "steps", "living_street", "residential", "service", "tertiary",
            "secondary", "primary", "unclassified", "cycleway", "track", "bridleway", "corridor", "elevator",
            "primary_link", "secondary_link", "tertiary_link", "road"}
R = 6371008.8


def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return 2 * R * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


class Grid:
    """Metre-ish bucket index for points near a latitude."""
    def __init__(self, lat0, cell=100.0):
        self.ky, self.kx, self.cell, self.b = 111320.0, 111320.0 * math.cos(math.radians(lat0)), cell, defaultdict(list)

    def key(self, p):
        return int(p[0] * self.ky // self.cell), int(p[1] * self.kx // self.cell)

    def add(self, p, item):
        self.b[self.key(p)].append(item)

    def near(self, p, rad):
        ky, kx = self.key(p)
        n = int(rad // self.cell) + 1
        for i in range(ky - n, ky + n + 1):
            for j in range(kx - n, kx + n + 1):
                yield from self.b.get((i, j), ())


def seg_dist(p, a, b):
    k = math.cos(math.radians(p[0])) * 111320.0
    ax, ay = (a[1] - p[1]) * k, (a[0] - p[0]) * 111320.0
    bx, by = (b[1] - p[1]) * k, (b[0] - p[0]) * 111320.0
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1.0)))
    return math.hypot(ax + t * dx, ay + t * dy)


def ways_for(bbox):
    """The walkable-way file covering bbox: the Manhattan dump, any cached download whose bbox contains it, else an
    Overpass download cached per bbox."""
    s, w, n, e = bbox
    if MANHATTAN[0] <= s and n <= MANHATTAN[2] and MANHATTAN[1] <= w and e <= MANHATTAN[3]:
        return WAYS
    for p in glob.glob(os.path.join(ROOT, "system", "map", "ways_*.json")):
        try:
            cs, cw, cn, ce = (float(x) for x in os.path.basename(p)[5:-5].split("_"))
        except ValueError:
            continue
        if cs <= s and n <= cn and cw <= w and e <= ce:
            return p
    path = os.path.join(ROOT, "system", "map", f"ways_{s:.3f}_{w:.3f}_{n:.3f}_{e:.3f}.json")
    if not os.path.exists(path):
        q = f'[out:json][timeout:180];way["highway"]({s},{w},{n},{e});out geom;'
        req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": "pogo-route-planner/1.0"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        if not json.loads(data).get("elements"):                 # never cache an empty or broken download
            raise RuntimeError(f"Overpass returned no ways for {bbox}")
        open(path, "wb").write(data)
    return path


def load_graph(bbox, ways=None):
    s, w, n, e = bbox
    ways = ways or ways_for(bbox)
    cache = os.path.join(ROOT, "system", "map", f"graph_{s:.3f}_{w:.3f}_{n:.3f}_{e:.3f}.pkl")
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(ways):
        return pickle.load(open(cache, "rb"))
    d = json.load(open(ways, encoding="utf-8"))
    pos, adj = {}, defaultdict(list)
    for el in d["elements"]:
        if el["type"] != "way" or el["tags"].get("highway") not in WALKABLE:
            continue
        nodes, geom = el.get("nodes") or [], el.get("geometry") or []
        if len(nodes) != len(geom):
            continue
        prev = None
        for nid, g in zip(nodes, geom):
            p = (g["lat"], g["lon"])
            inside = s <= p[0] <= n and w <= p[1] <= e
            if inside:
                pos[nid] = p
            if prev is not None and inside and prev in pos:
                L = hav(pos[prev], p)
                adj[prev].append((nid, L))
                adj[nid].append((prev, L))
            prev = nid if inside else None
    # keep the largest connected component (islands of sidewalk pieces are useless for loops)
    seen, best = set(), []
    for start in pos:
        if start in seen or start not in adj:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v, _ in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        if len(comp) > len(best):
            best = comp
    keep = set(best)
    pos = {k: v for k, v in pos.items() if k in keep}
    adj = {k: [(v, L) for v, L in adj[k] if v in keep] for k in keep}
    pickle.dump((pos, adj), open(cache, "wb"))
    return pos, adj


def load_bank_spots(bbox):
    """Every enabled stop/gym the scanner banked inside bbox (lured = lured at a sighting in the last 30 min; Rocket
    unknown). The `closed` column is not a filter: the game sets Closed on every held gym."""
    s, w, n, e = bbox
    db = sqlite3.connect(f"file:{BANK}?mode=ro", uri=True)
    where = "lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?"
    fresh = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - LURE_MAX_S))
    spots = {}
    for fid, lat, lng, kind, lured, team, visited, seen in db.execute(
            f"SELECT id, lat, lng, kind, lured, team, visited, last_seen FROM forts WHERE {where} AND COALESCE(enabled, 1) = 1",
            (s, n, w, e)):
        stop = kind == "stop"
        spots[fid] = {"p": (lat, lng), "stop": stop, "lured": bool(lured) and (seen or "") >= fresh, "rocket": False,
                      "team": None if stop else int(team or 0), "visited": bool(visited)}
    read_at = db.execute(f"SELECT MAX(last_seen) FROM forts WHERE {where}", (s, n, w, e)).fetchone()[0] or ""
    db.close()
    return spots, read_at


def load_spots(bbox, source="map"):
    if source == "bank":
        return load_bank_spots(bbox)
    s, w, n, e = bbox
    d = json.load(open(SPOTS, encoding="utf-8"))
    spots = {}
    for f in d.get("PokemonFortProto", []):
        if f.get("Latitude") and f.get("FortId") and s <= f["Latitude"] <= n and w <= f["Longitude"] <= e:
            stop = f.get("FortType") not in (None, 0)
            disp = f.get("PokestopDisplays") if isinstance(f.get("PokestopDisplays"), list) else []
            spots[f["FortId"]] = {"p": (f["Latitude"], f["Longitude"]), "stop": stop, "lured": bool(f.get("ActiveFortModifier")),
                                  "rocket": any(isinstance(x, dict) and x.get("IncidentDisplayType") for x in disp),
                                  "team": int(f.get("Team") or 0) if not stop else None, "visited": bool(f.get("Visited"))}
    return spots, d.get("read_at", "")


LURE_MAX_S = 1800          # a lure lasts 30 min: lure / Rocket flags from an older snapshot are history, not "now"


def snapshot_age_s(read_at):
    try:
        return time.time() - time.mktime(time.strptime(read_at[:19], "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return None


def dijkstra(adj, pos, src, dst):
    goal = pos[dst]
    dist, prev, pq = {src: 0.0}, {}, [(hav(pos[src], goal), 0.0, src)]
    while pq:
        _, g, u = heapq.heappop(pq)
        if u == dst:
            break
        if g > dist.get(u, 1e18):
            continue
        for v, L in adj[u]:
            ng = g + L
            if ng < dist.get(v, 1e18):
                dist[v], prev[v] = ng, u
                heapq.heappush(pq, (ng + hav(pos[v], goal), ng, v))
    if dst not in dist:
        return None, float("inf")
    path, u = [dst], dst
    while u != src:
        u = prev[u]
        path.append(u)
    return path[::-1], dist[dst]


DET = 1.30                                                         # street detour factor over straight lines


def prepare(bbox, source="map"):
    """Graph, spots, spot values and anchors shared by every pattern."""
    pos, adj = load_graph(bbox)
    spots, read_at = load_spots(bbox, source)
    lat0 = (bbox[0] + bbox[2]) / 2
    ng = Grid(lat0, 60.0)
    for nid, p in pos.items():
        ng.add(p, nid)
    # value of each spot: stops 1, gyms 1 (both spinnable), lured +0.5 (Pokemon magnet), Rocket +0.3 -- the bonuses only
    # while the snapshot is younger than a lure's 30 min; after that they are history and would bias the loop
    age = snapshot_age_s(read_at)
    live = age is not None and age <= LURE_MAX_S
    if not live:
        print(f"spots snapshot {read_at} is {'?' if age is None else round(age / 60)} min old: lure / Rocket bonuses ignored", flush=True)
    val = {k: 1.0 + ((0.5 if v["lured"] else 0) + (0.3 if v["rocket"] else 0) if live else 0) for k, v in spots.items()}
    # anchor = the graph node closest to each spot (a path through it covers the spot and its neighbours)
    sg = Grid(lat0, 80.0)
    for k, v in spots.items():
        sg.add(v["p"], k)
    anchors = {}
    for k, v in spots.items():
        best = min(ng.near(v["p"], 60.0), key=lambda nid: hav(pos[nid], v["p"]), default=None)
        if best is not None:
            anchors[best] = [s for s in sg.near(pos[best], RANGE) if hav(spots[s]["p"], pos[best]) <= RANGE]
    return {"pos": pos, "adj": adj, "spots": spots, "read_at": read_at, "age": age, "live": live, "val": val, "sg": sg,
            "anchors": anchors}


def grow(tour, length, pool, covered, budget, ctx):
    """Prize-collecting insertion: keep adding the anchor with the best new-spots-per-extra-metre until the length
    budget is used. Updates `covered` in place; tour[0] stays first."""
    pos, anchors, val = ctx["pos"], ctx["anchors"], ctx["val"]
    pool = list(pool)
    while True:
        best, bgain = None, 0.0
        for c in pool:
            gain = sum(val[s] for s in anchors[c] if s not in covered)
            if gain <= 0:
                continue
            for i in range(len(tour)):
                a, b = pos[tour[i]], pos[tour[(i + 1) % len(tour)]]
                extra = (hav(a, pos[c]) + hav(pos[c], b) - hav(a, b)) * DET
                if length + extra > budget:
                    continue
                score = gain / (extra + 30.0)
                if score > bgain:
                    best, bgain, bi, bx = c, score, i, extra
        if best is None:
            return tour, length
        tour.insert(bi + 1, best)
        covered |= set(anchors[best])
        length += bx
        pool.remove(best)


def two_opt(tour, pos):
    """2-opt on straight-line distances; tour[0] never moves."""
    improved = True
    while improved:
        improved = False
        for i in range(len(tour) - 1):
            for j in range(i + 2, len(tour) - (i == 0)):
                a, b, c, d = pos[tour[i]], pos[tour[i + 1]], pos[tour[j]], pos[tour[(j + 1) % len(tour)]]
                if hav(a, c) + hav(b, d) < hav(a, b) + hav(c, d) - 1:
                    tour[i + 1:j + 1] = reversed(tour[i + 1:j + 1])
                    improved = True
    return tour


def walk(tour, ctx):
    """The real walking path around the closed tour: (graph nodes, metres)."""
    pos, adj = ctx["pos"], ctx["adj"]
    path, real = [], 0.0
    for i in range(len(tour)):
        seg, L = dijkstra(adj, pos, tour[i], tour[(i + 1) % len(tour)])
        if seg is None:
            continue
        path += seg if not path else seg[1:]
        real += L
    return path, real


def result(path, real, n_anchors, t0, ctx):
    """Exact coverage along the real path, and the summary every pattern reports."""
    pos, spots, sg, age = ctx["pos"], ctx["spots"], ctx["sg"], ctx["age"]
    pts = [pos[n] for n in path]
    cov = set()
    for a, b in zip(pts, pts[1:] + pts[:1]):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        for s in sg.near(mid, RANGE + hav(a, b) / 2):
            if s not in cov and seg_dist(spots[s]["p"], a, b) <= RANGE:
                cov.add(s)
    return {"km": real / 1000, "points": pts, "covered": sorted(cov), "stops": sum(1 for s in cov if spots[s]["stop"]),
            "gyms": sum(1 for s in cov if not spots[s]["stop"]), "lured": sum(1 for s in cov if spots[s]["lured"]),
            "rocket": sum(1 for s in cov if spots[s]["rocket"]), "anchors": n_anchors, "secs": time.time() - t0,
            "read_at": ctx["read_at"], "age_txt": "?" if age is None else f"{age / 60:.0f} min", "lure_weighted": ctx["live"]}


def plan(bbox, km, near=None, candidates=900, source="map"):
    t0 = time.time()
    ctx = prepare(bbox, source)
    pos, anchors, val = ctx["pos"], ctx["anchors"], ctx["val"]
    ranked = sorted(anchors, key=lambda a: -sum(val[s] for s in anchors[a]))[:candidates]
    if near:
        ranked.sort(key=lambda a: hav(pos[a], near) / 400.0 - sum(val[s] for s in anchors[a]))
    start = ranked[0]
    partner = max(ranked[1:60], key=lambda a: sum(val[s] for s in set(anchors[a]) - set(anchors[start])) / (hav(pos[a], pos[start]) + 50))
    tour = [start, partner]
    covered = set(anchors[start]) | set(anchors[partner])
    tour, _ = grow(tour, 2 * hav(pos[start], pos[partner]) * DET, [a for a in ranked if a not in tour], covered, km * 1000.0, ctx)
    path, real = walk(two_opt(tour, pos), ctx)
    return result(path, real, len(tour), t0, ctx), ctx["spots"]


def bearing(a, b):
    """Compass bearing a -> b in degrees (0 = north, clockwise)."""
    p1, p2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


def plan_clover(bbox, km, petals=4, near=None, candidates=900, source="map"):
    """PETALS loops that all start and end at one hub: the anchor with the most spot value within 150 m (only anchors
    within 300 m of `near` if given). Each petal grows only in its own compass sector, with km/PETALS of the budget."""
    t0 = time.time()
    ctx = prepare(bbox, source)
    pos, anchors, val, spots, sg = ctx["pos"], ctx["anchors"], ctx["val"], ctx["spots"], ctx["sg"]
    petals = max(1, min(petals, int(km * 1000 // MIN_PETAL_M)))
    core = {a: sum(val[s] for s in sg.near(pos[a], 150.0) if hav(spots[s]["p"], pos[a]) <= 150.0) for a in anchors}
    pick = list(anchors)
    if near:                                                      # never drift to a denser hub elsewhere in the bbox
        pick = [a for a in anchors if hav(pos[a], near) <= 300.0] or [min(anchors, key=lambda a: hav(pos[a], near))]
    hub = max(pick, key=lambda a: core[a])
    budget = km * 1000.0 / petals
    reach = budget / 2 / DET                                      # a petal goes out and back: it reaches ~half its length
    ranked = sorted(anchors, key=lambda a: -sum(val[s] for s in anchors[a]))[:candidates]
    cand = [a for a in ranked if a != hub and hav(pos[a], pos[hub]) <= reach]
    ang, width = {a: bearing(pos[hub], pos[a]) for a in cand}, 360.0 / petals

    def sector(a, off):
        return int(((ang[a] - off) % 360) // width) % petals

    def balance(off):                                             # the weakest sector's value for these borders
        tot = [0.0] * petals
        for a in cand:
            tot[sector(a, off)] += sum(val[s] for s in anchors[a])
        return min(tot)
    off = max(range(0, max(5, int(width)), 5), key=balance)
    covered, path, real, lens, ends, n = set(anchors[hub]), [], 0.0, [], [], 1
    for i in range(petals):
        tour, _ = grow([hub], 0.0, [a for a in cand if sector(a, off) == i], covered, budget, ctx)
        if len(tour) < 2:
            continue
        p, L = walk(two_opt(tour, pos), ctx)
        if L < MIN_PETAL_M / 3:                                   # a stub, not a petal
            continue
        path += p if not path else p[1:]
        real += L
        lens.append(L / 1000)
        ends.append(len(path))                                    # points[:ends[0]] = petal 1, and so on
        n += len(tour) - 1
    res = result(path, real, n, t0, ctx)
    res.update({"pattern": "clover", "petals": lens, "petal_ends": ends, "hub": pos[hub],
                "hub_spots": sum(1 for s in sg.near(pos[hub], RANGE) if hav(spots[s]["p"], pos[hub]) <= RANGE)})
    return res, spots


def hubs(bbox, n=5, sep=1200.0, radius=300.0, source="map"):
    """The n densest centres (spot value within `radius`), at least `sep` apart: where routes should be centred."""
    ctx = prepare(bbox, source)
    pos, anchors, val, spots, sg = ctx["pos"], ctx["anchors"], ctx["val"], ctx["spots"], ctx["sg"]
    dens = {a: sum(val[s] for s in sg.near(pos[a], radius) if hav(spots[s]["p"], pos[a]) <= radius) for a in anchors}
    out = []
    for a in sorted(dens, key=lambda a: -dens[a]):
        if all(hav(pos[a], h["p"]) >= sep for h in out):
            out.append({"p": pos[a], "value": dens[a],
                        "stops": sum(1 for s in sg.near(pos[a], radius) if spots[s]["stop"] and hav(spots[s]["p"], pos[a]) <= radius),
                        "gyms": sum(1 for s in sg.near(pos[a], radius) if not spots[s]["stop"] and hav(spots[s]["p"], pos[a]) <= radius)})
            if len(out) == n:
                break
    return out


def simplify(pts, tol=4.0):
    """Douglas-Peucker in metres (keeps the walking shape, drops redundant sidewalk vertices)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, bi = 0.0, None
        for k in range(i + 1, j):
            d = seg_dist(pts[k], pts[i], pts[j])
            if d > best:
                best, bi = d, k
        if bi is not None and best > tol:
            keep[bi] = True
            stack += [(i, bi), (bi, j)]
    return [p for p, k in zip(pts, keep) if k]


def export(res, spots, name):
    os.makedirs(OUTDIR, exist_ok=True)
    way = simplify(res["points"])
    if way[0] != way[-1]:
        way.append(way[0])
    wp = ";".join(f"{a:.6f},{b:.6f}" for a, b in way)
    open(os.path.join(OUTDIR, f"{name}.waypoints.txt"), "w").write(wp)
    gpx = ['<?xml version="1.0" encoding="UTF-8"?>', '<gpx version="1.1" creator="pogo-route-planner" xmlns="http://www.topografix.com/GPX/1/1">',
           f"<rte><name>{html.escape(name)}</name>"] + [f'<rtept lat="{a:.6f}" lon="{b:.6f}"/>' for a, b in way] + ["</rte></gpx>"]
    open(os.path.join(OUTDIR, f"{name}.gpx"), "w").write("\n".join(gpx))
    cov = set(res["covered"])
    spts = [{"a": v["p"][0], "o": v["p"][1], "s": 1 if v["stop"] else 0, "c": 1 if k in cov else 0, "l": 1 if v["lured"] else 0,
             "r": 1 if v["rocket"] else 0, "t": v["team"] or 0} for k, v in spots.items()]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PoGo Route</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
:root {{ --fg:#1d1d1b; --mut:#6b6b66; --line:#e4e2dc; --card:#ffffff; --bg:#fafaf8; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --bg:#141413; }} }}
:root[data-theme="dark"] {{ --fg:#ecebe6; --mut:#a3a19a; --line:#2c2b28; --card:#1c1c1a; --bg:#141413; }}
html,body {{ height:100%; margin:0; background:var(--bg); font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
#map {{ position:absolute; inset:0; }}
.panel {{ position:absolute; z-index:1000; top:12px; left:12px; max-width:min(320px, calc(100% - 24px)); background:var(--card); color:var(--fg);
  border:1px solid var(--line); border-radius:10px; padding:10px 12px; box-shadow:0 2px 10px rgba(0,0,0,.15); }}
.panel h1 {{ font-size:15px; margin:0 0 4px; }} .mut {{ color:var(--mut); font-size:12px; }} .row {{ display:flex; justify-content:space-between; gap:10px; }}
</style></head><body><div id="map"></div>
<div class="panel"><h1>{html.escape(name)}</h1>
<div class="mut">Planned on real walkable ways (OpenStreetMap) through the spots PoGo reported at {html.escape(res['read_at'])}.
A spot counts when the route passes within 80 m (the game's interaction range); once per lap.</div>
<div class="row"><span>Loop length</span><b>{res['km']:.2f} km</b></div>
<div class="row"><span>PokéStops in range</span><b>{res['stops']}</b></div>
<div class="row"><span>Gyms in range</span><b>{res['gyms']}</b></div>
<div class="row"><span>Stops + gyms per km</span><b>{(res['stops'] + res['gyms']) / max(res['km'], 0.01):.1f}</b></div>
<div class="row"><span>Lured at {html.escape(res['read_at'][11:])} ({html.escape(res['age_txt'])} old)</span><b>{res['lured']}</b></div>
<div class="row"><span>Team Rocket at {html.escape(res['read_at'][11:])}</span><b>{res['rocket']}</b></div>
<div class="row"><span>Lap time at 10.6 km/h</span><b>{res['km'] / 10.6 * 60:.0f} min</b></div>
{f'<div class="row"><span>Cloverleaf: {len(res["petals"])} petals from the hub</span><b>{" / ".join(f"{L / 10.6 * 60:.0f}" for L in res["petals"])} min</b></div>' if res.get("petals") else ""}
<div class="mut">Waypoints: {len(way)} (for the joystick WALK command / GPX route)</div></div>
<script>
var S = {json.dumps(spts, separators=(',', ':'))};
var R = {json.dumps([[round(a, 6), round(b, 6)] for a, b in way], separators=(',', ':'))};
var map = L.map('map', {{preferCanvas: true}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19, attribution: '&copy; OpenStreetMap'}}).addTo(map);
var TEAM = ['#8a8a8a', '#2f7de1', '#e0463f', '#f2c230'];
S.forEach(function (p) {{
  var col = p.s ? (p.r ? '#222' : (p.l ? '#e84fa3' : '#2f7de1')) : (TEAM[p.t] || '#8a8a8a');
  L.circleMarker([p.a, p.o], {{radius: p.s ? (p.c ? 5 : 3) : 7, color: p.c ? '#ff7a00' : col, weight: p.c ? 2 : 1, fillColor: col, fillOpacity: p.c ? .95 : .35}}).addTo(map);
}});
var line = L.polyline(R, {{color: '#ff7a00', weight: 4}}).addTo(map);
map.fitBounds(line.getBounds(), {{padding: [30, 30]}});
</script></body></html>"""
    open(os.path.join(OUTDIR, f"{name}.html"), "w", encoding="utf-8").write(page)
    return way


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "hubs"])
    ap.add_argument("--km", type=float, default=4.0)
    ap.add_argument("--bbox", default="40.745,-73.995,40.772,-73.965")     # Midtown: 34th..64th St, 9th Ave..Lexington
    ap.add_argument("--near", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--spots", choices=["map", "bank"], default="map")
    ap.add_argument("--pattern", choices=["loop", "clover"], default="loop")
    ap.add_argument("--petals", type=int, default=4)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--sep", type=float, default=1200.0)
    a = ap.parse_args()
    bbox = tuple(float(x) for x in a.bbox.split(","))
    near = tuple(float(x) for x in a.near.split(",")) if a.near else None
    if a.cmd == "hubs":
        for i, h in enumerate(hubs(bbox, a.n, a.sep, source=a.spots), 1):
            print(f"{i}. {h['p'][0]:.6f},{h['p'][1]:.6f}  {h['stops']} stops + {h['gyms']} gyms within 300 m")
        return
    if a.pattern == "clover":
        res, spots = plan_clover(bbox, a.km, a.petals, near, source=a.spots)
    else:
        res, spots = plan(bbox, a.km, near, source=a.spots)
    name = a.name or f"midtown_{a.km:g}km"
    way = export(res, spots, name)
    print(f"{name}: {res['km']:.2f} km | stops {res['stops']} gyms {res['gyms']} = {(res['stops'] + res['gyms']) / res['km']:.1f}/km"
          f" | lured {res['lured']} rocket {res['rocket']} as of {res['read_at']} ({res['age_txt']} old) | anchors {res['anchors']} | waypoints {len(way)} | {res['secs']:.0f}s")
    if res.get("petals"):
        print(f"  clover hub {res['hub'][0]:.6f},{res['hub'][1]:.6f} ({res['hub_spots']} spots in range) | petals "
              + ", ".join(f"{L:.2f} km = {L / 10.6 * 60:.0f} min" for L in res["petals"]))


if __name__ == "__main__":
    main()
