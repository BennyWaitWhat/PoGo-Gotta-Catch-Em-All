"""Catch map, mid Central Park to Bryant Park: where the catcher catches, where lures were, and the dense loop.

  python tools/catch_map.py --csv <speed_governor CSV> --loop <dense_loop.py --out JSON> --out page.html

Layers (all from this repo's own data, nothing fetched):
  streets + Central Park paths   system/map/manhattan_ways.json (OpenStreetMap)
  stops / gyms, lure history     system/map/pogo_wigle.db (forts, fort_events 'lure'; scanned 2026-09-25 03:13-06:14)
  catches per km walked          the speed governor's CSV (5 s samples: mock fix + the catcher's caught counter)
  the loop                       tools/dense_loop.py --out
The map is turned 29 degrees so the avenues run straight up, like the grid on the ground.
"""
import argparse, csv, datetime as dt, json, math, os, sqlite3, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WAYS = os.path.join(ROOT, "system", "map", "manhattan_ways.json")
DB = os.path.join(ROOT, "system", "map", "pogo_wigle.db")
sys.path.insert(0, HERE)
from speed_governor import PARKS, inside   # noqa: E402

S, W, N, E = 40.7350, -74.0200, 40.8000, -73.9300     # coarse prefilter; the page is the U x V box below
U = (-1050.0, 3600.0)       # metres uptown from Bryant Park: ~29th St .. ~86th St (mid Central Park)
V = (-1500.0, 1650.0)       # metres east: ~11th Ave .. the East River
LAT0, LNG0, TH = 40.7536, -73.9832, math.radians(29.0)
ROADS = {"primary", "secondary", "tertiary", "residential", "unclassified", "pedestrian", "living_street",
         "primary_link", "secondary_link", "tertiary_link"}
PARK_PATHS = {"footway", "path", "bridleway", "cycleway", "steps"}


def uv(lat, lng):
    """metres: u = uptown along the avenues, v = east across them (Bryant Park = 0,0)."""
    y = (lat - LAT0) * 111320.0
    x = (lng - LNG0) * 111320.0 * math.cos(math.radians(LAT0))
    return round(x * math.sin(TH) + y * math.cos(TH), 1), round(x * math.cos(TH) - y * math.sin(TH), 1)


def meters(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def keep(pts):
    return any(U[0] <= u <= U[1] and V[0] <= v <= V[1] for u, v in pts)


def streets():
    roads, paths = [], []
    for el in json.load(open(WAYS, encoding="utf-8"))["elements"]:
        if el["type"] != "way":
            continue
        h = el.get("tags", {}).get("highway")
        g = [(p["lat"], p["lon"]) for p in el.get("geometry") or []]
        if not g or not any(S <= a <= N and W <= b <= E for a, b in g):
            continue
        if h in ROADS:
            pts = [uv(a, b) for a, b in g]
            if keep(pts):
                roads.append(pts)
        elif h in PARK_PATHS and inside(PARKS["Central Park"], *g[len(g) // 2]):
            pts = [uv(a, b) for a, b in g]
            if keep(pts):
                paths.append(pts)
    return roads, paths


def forts():
    db = sqlite3.connect(DB)
    lures = dict(db.execute("select fort, count(*) from fort_events where event='lure' group by fort"))
    out = []
    for fid, lat, lng, kind in db.execute("select id, lat, lng, kind from forts"):
        u, v = uv(lat, lng)
        if U[0] <= u <= U[1] and V[0] <= v <= V[1]:
            out.append([u, v, 1 if kind == "gym" else 0, lures.get(fid, 0)])
    return out


def track(path, since=""):
    """5 s samples -> segments with catches per km (smoothed over +-3 samples)."""
    rows = [r for r in csv.DictReader(open(path)) if r["lat"] and r["caught"]]
    seg = []
    for a, b in zip(rows, rows[1:]):
        pa, pb = (float(a["lat"]), float(a["lng"])), (float(b["lat"]), float(b["lng"]))
        d = meters(pa, pb)
        c = int(b["caught"]) - int(a["caught"])
        t = (dt.datetime.fromisoformat(b["time"]) - dt.datetime.fromisoformat(a["time"])).total_seconds()
        if d > 300 or c < 0 or t > 15:
            seg.append(None)
            continue
        seg.append((pa, pb, d, c, b["time"][11:16], b["place"]))
    out = []
    for i, s in enumerate(seg):
        if not s:
            continue
        win = [x for x in seg[max(0, i - 3):i + 4] if x]
        km = sum(x[2] for x in win) / 1000
        out.append([*uv(*s[0]), *uv(*s[1]), round(sum(x[3] for x in win) / km, 1) if km > 0.02 else 0, s[4], s[3]])
    zones = defaultdict(lambda: [0.0, 0, 0.0])
    for s, r in zip(seg, rows[1:]):
        if s:
            for k in [s[5]] + (["Loop so far"] if since and r["time"][11:] >= since else []):
                z = zones[k]
                z[0] += s[2]
                z[1] += s[3]
                z[2] += 5
    return out, {k: {"km": round(v[0] / 1000, 2), "caught": v[1], "per_km": round(v[1] / (v[0] / 1000), 1),
                     "per_min": round(v[1] / (v[2] / 60), 1)} for k, v in zones.items() if v[0] > 300}, rows[-1]


def labels():
    """Avenue and street names at their real positions (OpenStreetMap corners)."""
    import dense_loop as dl
    sts = [34, 42, 50, 59, 72, 79, 86]
    xy = dl.intersections(set(sts))
    names = {8: "8th", 7: "7th", 6: "6th", 5: "5th", 4: "Park", 3: "3rd"}
    aves = []
    for a in dl.LANES:
        vs = sorted(uv(*p)[1] for (ave, st), p in xy.items() if ave == a and st <= 59)   # Midtown corners only
        if vs:
            aves.append([names[a], vs[len(vs) // 2]])
    out = []
    for st in sts:
        us = [uv(*p)[0] for (ave, s_), p in xy.items() if s_ == st]
        if us:
            out.append([st, round(sum(us) / len(us), 1)])
    return aves, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--loop", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default="", help="loop started at (HH:MM:SS) -- measure the loop from here")
    a = ap.parse_args()
    roads, paths = streets()
    seg, zones, last = track(a.csv, a.since)
    lp = json.load(open(a.loop))
    loop = [uv(c["lat"], c["lng"]) for c in lp["corners"]]
    parks = {k: [uv(*p) for p in poly] for k, poly in PARKS.items()}
    data = {"roads": roads, "paths": paths, "forts": forts(), "seg": seg, "zones": zones, "loop": loop,
            "lap_km": lp["lap_km"], "parks": parks, "me": uv(float(last["lat"]), float(last["lng"])),
            "asof": last["time"], "U": U, "V": V}
    data["aves"], data["sts"] = labels()
    page = open(os.path.join(HERE, "catch_map.html"), encoding="utf-8").read()
    open(a.out, "w", encoding="utf-8").write(page.replace("/*DATA*/null", json.dumps(data, separators=(",", ":"))))
    print("wrote %s: %d roads, %d park paths, %d stops/gyms, %d track segments" % (
        a.out, len(roads), len(paths), len(data["forts"]), len(seg)))


if __name__ == "__main__":
    main()
