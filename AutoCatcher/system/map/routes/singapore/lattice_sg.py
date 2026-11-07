"""Hop points for a teleport scan of Singapore (main island + Sentosa), same rule as miami_ftl/lattice.py.

Every map reply holds every level-15 S2 cell that touches a ~709 m circle around the reported player position
(nearest cell EDGE). A hex lattice 1.5 km apart leaves every point within S/sqrt(3) = 0.87 km of a hop, so every cell
of the area is sent. Land = OpenStreetMap's island outlines (Nominatim: relation 1769123 "Singapore Island",
relation 9574725 "Sentosa"); a lattice point is kept when it lies within REACH of land. Jurong Island, Pulau Tekong
and Pulau Ubin are left out (restricted / military / no streets to route on).

Order: rings around START (Marina Bay), so the densest core is scanned first if the scan has to stop early.

  python -I lattice_sg.py OSM_DIR OUT.json [START_LAT,START_LNG]
"""
import json, math, os, sys
import s2sphere

OSM, OUT = sys.argv[1], sys.argv[2]
START = tuple(float(x) for x in sys.argv[3].split(",")) if len(sys.argv) > 3 else (1.2830, 103.8590)
S, REACH = 1.5, 0.88                                       # km
LAT0, LNG0 = 1.35, 103.82
KX, KY = 111.32 * math.cos(math.radians(LAT0)), 110.57
xy = lambda p: ((p[1] - LNG0) * KX, (p[0] - LAT0) * KY)
ll = lambda q: (LAT0 + q[1] / KY, LNG0 + q[0] / KX)


def island(fn, osm_id):
    """Outer ring of the island with this OSM relation id, as (lat, lng)."""
    for d in json.load(open(os.path.join(OSM, fn))):
        if d.get("osm_id") == osm_id and d.get("category") == "place" and d["geojson"]["type"] == "Polygon":
            return [(b, a) for a, b in d["geojson"]["coordinates"][0]]
    raise SystemExit(f"{fn}: no place/island polygon for relation {osm_id}")


POLYS = [island("nominatim_pulau_ujong.json", 1769123), island("nominatim_sentosa.json", 9574725)]
PX = [[xy(p) for p in poly] for poly in POLYS]


def inside(q):
    for poly in PX:
        c, n = False, len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            if (a[1] > q[1]) != (b[1] > q[1]) and q[0] < (b[0] - a[0]) * (q[1] - a[1]) / (b[1] - a[1]) + a[0]:
                c = not c
        if c:
            return True
    return False


def seg_d(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1)))
    return math.hypot(q[0] - a[0] - t * dx, q[1] - a[1] - t * dy)


def to_land(q):
    if inside(q):
        return 0.0
    return min(seg_d(q, poly[i], poly[(i + 1) % len(poly)]) for poly in PX for i in range(len(poly)))


def area(poly):
    return 0.5 * abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))))


allp = [q for poly in PX for q in poly]
x0, x1 = min(q[0] for q in allp) - S, max(q[0] for q in allp) + S
y0, y1 = min(q[1] for q in allp) - S, max(q[1] for q in allp) + S
dy = S * math.sqrt(3) / 2
pts, j = [], 0
while y0 + j * dy <= y1:
    y, off = y0 + j * dy, (S / 2 if j % 2 else 0.0)
    pts += [q for q in ((x0 + off + i * S, y) for i in range(int((x1 - x0) / S) + 2)) if to_land(q) <= REACH]
    j += 1

# rings around START, each ring walked by angle, alternate rings reversed (consecutive hops stay ~1.5 km apart)
st = xy(START)
rings = {}
for q in pts:
    d = math.hypot(q[0] - st[0], q[1] - st[1])
    rings.setdefault(int(d / S + 0.5), []).append((math.atan2(q[1] - st[1], q[0] - st[0]), q))
hops = []
for k in sorted(rings):
    ring = [q for _, q in sorted(rings[k])]
    hops += ring[::-1] if k % 2 else ring

# every level-15 cell whose centre is on land must have a hop within REACH of its centre
s, w = ll((x0, y0))
n, e = ll((x1, y1))
rc = s2sphere.RegionCoverer()
rc.min_level = rc.max_level = 15
rc.max_cells = 1000000
rect = s2sphere.LatLngRect.from_point_pair(s2sphere.LatLng.from_degrees(s, w), s2sphere.LatLng.from_degrees(n, e))
cells, worst = 0, 0.0
for cid in rc.get_covering(rect):
    c = cid.to_lat_lng()
    q = xy((c.lat().degrees, c.lng().degrees))
    if not inside(q):
        continue
    cells += 1
    worst = max(worst, min(math.hypot(q[0] - h[0], q[1] - h[1]) for h in hops))
jumps = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(hops, hops[1:]))
land = sum(area(p) for p in PX)
json.dump({"spacing_km": S, "reach_km": REACH, "start": START, "hull": [list(p) for p in POLYS[0]],
           "polys": [[list(p) for p in poly] for poly in POLYS],
           "hops": [[round(a, 6), round(b, 6)] for a, b in map(ll, hops)]}, open(OUT, "w"))
print(f"land {land:.0f} km2 (main island {area(PX[0]):.0f} + Sentosa {area(PX[1]):.1f}) | {len(hops)} hops {S} km apart in "
      f"{len(rings)} rings | {cells} level-15 cells on land, farthest cell centre from its nearest hop {worst * 1000:.0f} m "
      f"(reach {REACH * 1000:.0f}) | jumps {jumps:.0f} km")
print(f"time at the Miami pace: ~{len(hops) * 7 / 60:.0f} min (7 s/hop average), worst ~{len(hops) * 11 / 60:.0f} min (11 s/hop)")
print(f"first hop {ll(hops[0])[0]:.5f},{ll(hops[0])[1]:.5f}  last hop {ll(hops[-1])[0]:.5f},{ll(hops[-1])[1]:.5f}")
