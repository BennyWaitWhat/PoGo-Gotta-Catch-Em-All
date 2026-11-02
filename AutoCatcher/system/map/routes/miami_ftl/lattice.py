"""Hop points for a teleport scan of the whole SOUTHCOM - Miami - Fort Lauderdale area.

Every map reply holds every level-15 S2 cell that touches a ~709 m circle around the reported player position
(nearest cell EDGE; centres reach ~0.93 km). A hex lattice 1.5 km apart leaves every cell's nearest edge within
~0.67 km of a hop (checked 2026-11-01: 6,227 cells, worst 669 m), so every cell of the area is sent. The REACH test
below (cell centre within 0.88 km of a hop) is the older, stricter-looking proxy; the edge rule is the real one. Area = convex hull of the Doral loop, both Miami scan paths and downtown/beach
Fort Lauderdale; a lattice point is kept when it lies within REACH of that hull.

  python -I lattice.py DATA_DIR OUT.json START_LAT,START_LNG
"""
import json, math, os, sys
import s2sphere

DATA, OUT = sys.argv[1], sys.argv[2]
START = tuple(float(x) for x in sys.argv[3].split(","))
S, REACH = 1.5, 0.88                                       # km
LAT0, LNG0 = 25.95, -80.23
KX, KY = 111.32 * math.cos(math.radians(LAT0)), 110.95
xy = lambda p: ((p[1] - LNG0) * KX, (p[0] - LAT0) * KY)
ll = lambda q: (LAT0 + q[1] / KY, LNG0 + q[0] / KX)

pts = []
for f in ("scan_doral.json", "scan_path.json", "scan_path2.json"):
    pts += [tuple(p) for p in json.load(open(os.path.join(DATA, f)))["line"]]
pts += [(25.80616, -80.34827), (26.1224, -80.1373), (26.1190, -80.1035), (26.1350, -80.1450), (26.1350, -80.1020)]
P = sorted({xy(p) for p in pts})


def cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


lo, up = [], []
for p in P:
    while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
        lo.pop()
    lo.append(p)
for p in reversed(P):
    while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
        up.pop()
    up.append(p)
hull = lo[:-1] + up[:-1]                                   # counter-clockwise


def inside(q):
    return all(cross(hull[i], hull[(i + 1) % len(hull)], q) >= 0 for i in range(len(hull)))


def seg_d(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1)))
    return math.hypot(q[0] - a[0] - t * dx, q[1] - a[1] - t * dy)


def to_hull(q):
    return 0.0 if inside(q) else min(seg_d(q, hull[i], hull[(i + 1) % len(hull)]) for i in range(len(hull)))


area = 0.5 * abs(sum(hull[i][0] * hull[(i + 1) % len(hull)][1] - hull[(i + 1) % len(hull)][0] * hull[i][1] for i in range(len(hull))))
x0, x1 = min(p[0] for p in hull) - S, max(p[0] for p in hull) + S
y0, y1 = min(p[1] for p in hull) - S, max(p[1] for p in hull) + S
dy = S * math.sqrt(3) / 2
rows, j = [], 0
while y0 + j * dy <= y1:
    y, off = y0 + j * dy, (S / 2 if j % 2 else 0.0)
    row = [(x0 + off + i * S, y) for i in range(int((x1 - x0) / S) + 2)]
    row = [q for q in row if to_hull(q) <= REACH]
    if row:
        rows.append(row)
    j += 1
# snake south -> north, the first row starting at its end nearest the start point
st = xy(START)
first_east = math.hypot(rows[0][-1][0] - st[0], rows[0][-1][1] - st[1]) < math.hypot(rows[0][0][0] - st[0], rows[0][0][1] - st[1])
hops = []
for k, row in enumerate(rows):
    hops += row[::-1] if (k % 2 == 0) == first_east else row

# every level-15 cell whose centre is inside the hull must have a hop within REACH of its centre
lat_lo, lat_hi = min(ll(p)[0] for p in hull), max(ll(p)[0] for p in hull)
lng_lo, lng_hi = min(ll(p)[1] for p in hull), max(ll(p)[1] for p in hull)
rc = s2sphere.RegionCoverer()
rc.min_level = rc.max_level = 15
rc.max_cells = 1000000
rect = s2sphere.LatLngRect.from_point_pair(s2sphere.LatLng.from_degrees(lat_lo, lng_lo), s2sphere.LatLng.from_degrees(lat_hi, lng_hi))
cells = 0
worst = 0.0
for cid in rc.get_covering(rect):
    c = cid.to_lat_lng()
    q = xy((c.lat().degrees, c.lng().degrees))
    if not inside(q):
        continue
    cells += 1
    worst = max(worst, min(math.hypot(q[0] - h[0], q[1] - h[1]) for h in hops))
jumps = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(hops, hops[1:]))
json.dump({"spacing_km": S, "reach_km": REACH, "hull": [ll(p) for p in hull], "hops": [[round(a, 6), round(b, 6)] for a, b in map(ll, hops)]},
          open(OUT, "w"))
print(f"area {area:.0f} km2 | {len(rows)} rows, {len(hops)} hops {S} km apart | {cells} level-15 cells inside, "
      f"farthest cell centre from its nearest hop {worst * 1000:.0f} m (reach {REACH * 1000:.0f}) | jumps {jumps:.0f} km")
print(f"first hop {ll(hops[0])[0]:.5f},{ll(hops[0])[1]:.5f}  last hop {ll(hops[-1])[0]:.5f},{ll(hops[-1])[1]:.5f}")
