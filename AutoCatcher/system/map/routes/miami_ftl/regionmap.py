"""The whole-area scan map: every stop and gym the scanner banked from SOUTHCOM through Miami to Fort Lauderdale,
the scanned area (hull), every hop (grey = the game answered, red = no reply), the route hubs, counts per area.
Leaflet page (tiles from OpenStreetMap).

  python regionmap.py TOOLS_DIR HOPS.json ROUTES.json OUT.html
"""
import glob, html, json, os, sqlite3, sys, time

sys.path.insert(0, sys.argv[1])
import route_planner as rp  # noqa: E402

HOPS, ROUTES, OUT = sys.argv[2], sys.argv[3], sys.argv[4]
TEAM = ["#8a8a8a", "#2f7de1", "#e0463f", "#f2c230"]
AREAS = ["Doral / SOUTHCOM", "Miami", "Miami Beach", "Miami west / Airport", "Hialeah / Miami Gardens",
         "North Miami / Aventura / Sunny Isles", "Hallandale / Hollywood / Dania", "Fort Lauderdale"]


def area_of(p):                                            # same split as plan_region.py
    lat, lng = p
    if lng < -80.29 and lat < 25.87:
        return AREAS[0]
    if lng > -80.145 and lat < 25.875:
        return AREAS[2]
    if lat < 25.86 and lng >= -80.215:
        return AREAS[1]
    if lng < -80.215 and lat < 25.84:
        return AREAS[3]
    if lng < -80.215 and lat < 25.98:
        return AREAS[4]
    if lat < 25.975:
        return AREAS[5]
    if lat < 26.065:
        return AREAS[6]
    return AREAS[7]


H = json.load(open(HOPS))
hull = [tuple(p) for p in H["hull"]]


def inside(p):
    n, c = len(hull), False
    for i in range(n):
        a, b = hull[i], hull[(i + 1) % n]
        if (a[0] > p[0]) != (b[0] > p[0]) and p[1] < (b[1] - a[1]) * (p[0] - a[0]) / (b[0] - a[0]) + a[1]:
            c = not c
    return c


LOGS = glob.glob(os.path.join(os.path.dirname(os.path.abspath(HOPS)), "hops*.json.log.jsonl"))   # main pass + re-checks + retries
answered = {}
for r in (json.loads(l) for f in LOGS for l in open(f)):   # a point counts as answered if any of its hops got a reply
    p = tuple(r["p"])
    answered[p] = answered.get(p, False) or r["how"] != "timeout"
hops = [[round(p[0], 5), round(p[1], 5), 0 if ok else 1] for p, ok in answered.items()]
s, w = min(p[0] for p in hull) - 0.012, min(p[1] for p in hull) - 0.012
n, e = max(p[0] for p in hull) + 0.012, max(p[1] for p in hull) + 0.012
db = sqlite3.connect(f"file:{rp.BANK}?mode=ro", uri=True)
rows = db.execute("SELECT lat, lng, kind, team FROM forts WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? AND COALESCE(enabled, 1) = 1",
                  (s, n, w, e)).fetchall()
pts = [{"a": round(a, 6), "o": round(o, 6), "s": 1 if k == "stop" else 0, "t": int(t or 0) if k != "stop" else 0} for a, o, k, t in rows]
per = {a: [0, 0] for a in AREAS}
for a, o, k, _ in rows:
    if inside((a, o)):
        per[area_of((a, o))][0 if k == "stop" else 1] += 1
ns, ng = sum(v[0] for v in per.values()), sum(v[1] for v in per.values())
routes = json.load(open(ROUTES))["routes"] if os.path.exists(ROUTES) else []
dens = lambda r: (r["stops"] + r["gyms"]) / r["km"]
hubs = [[round(r["hub"][0], 5), round(r["hub"][1], 5), r["hub_stops300"], r["hub_gyms300"], round(dens(r), 1), r.get("area", "")]
        for r in sorted(routes, key=lambda r: -dens(r))]
if not routes:                             # no routes planned yet: the densest spots (>= 25 within 300 m, 1.3 km apart)
    sg = rp.Grid(25.95, 100.0)
    P = [(a, o, k == "stop") for a, o, k, _ in rows if inside((a, o))]
    for i, p in enumerate(P):
        sg.add(p[:2], i)
    near = {i: [j for j in sg.near(p[:2], 300.0) if rp.hav(P[j][:2], p[:2]) <= 300.0] for i, p in enumerate(P)}
    for i in sorted(near, key=lambda i: -len(near[i])):
        if len(near[i]) < 25:
            break
        if all(rp.hav(P[i][:2], (h[0], h[1])) >= 1300.0 for h in hubs):
            ns_ = sum(P[j][2] for j in near[i])
            hubs.append([round(P[i][0], 5), round(P[i][1], 5), ns_, len(near[i]) - ns_, 0, area_of(P[i][:2])])
rows_html = "".join(f'<div class="row"><span>{html.escape(a)}</span><b>{v[0]} + {v[1]}</b></div>' for a, v in per.items())
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOUTHCOM to Fort Lauderdale Scan</title>
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
.panel summary {{ cursor:pointer; font-weight:600; font-size:15px; }}
.mut {{ color:var(--mut); font-size:12px; margin-top:6px; }}
.row {{ display:flex; justify-content:space-between; gap:10px; }} .row.tot {{ border-top:1px solid var(--line); margin-top:4px; padding-top:4px; }}
.key i {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin:0 3px 0 6px; vertical-align:-1px; }}
.hub {{ background:#1d1d1b; color:#fff; border:2px solid #fff; border-radius:50%; font:700 12px/22px system-ui,sans-serif; text-align:center; width:22px; height:22px; }}
</style></head><body><div id="map"></div>
<div class="panel"><details open><summary>SOUTHCOM to Fort Lauderdale scan</summary>
<div class="mut">Stops + gyms inside the scanned area</div>
{rows_html}
<div class="row tot"><span>All</span><b>{ns} + {ng}</b></div>
<div class="mut">{len(hops)} hops 1.5 km apart (each map reply holds every map cell touching a ~709 m circle, so the circles overlap).
Numbers = route hubs, densest first. As of {time.strftime('%Y-%m-%d %H:%M')}.</div>
<div class="mut key"><i style="background:#2f7de1"></i>stop<i style="background:#e0463f"></i>gym<i style="background:#bbb"></i>hop<i style="background:#d50000"></i>hop, no reply</div>
</details></div>
<script>
var S = {json.dumps(pts, separators=(',', ':'))};
var P = {json.dumps(hops, separators=(',', ':'))};
var U = {json.dumps([[round(a, 5), round(b, 5)] for a, b in hull], separators=(',', ':'))};
var B = {json.dumps(hubs, separators=(',', ':'))};
var TEAM = {json.dumps(TEAM)};
var map = L.map('map', {{preferCanvas: true}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19, attribution: '&copy; OpenStreetMap'}}).addTo(map);
L.polygon(U, {{color: '#555', weight: 2, dashArray: '6 6', fill: false}}).addTo(map);
var hopLayer = L.layerGroup(P.map(function (h) {{
  return L.circleMarker([h[0], h[1]], {{radius: h[2] ? 5 : 2.5, color: h[2] ? '#d50000' : '#999', weight: 1, fillOpacity: .8}});
}}));
var fortLayer = L.layerGroup(S.map(function (p) {{
  return L.circleMarker([p.a, p.o], {{radius: p.s ? 3 : 5, color: '#fff', weight: p.s ? .5 : 1, fillColor: p.s ? '#2f7de1' : TEAM[p.t], fillOpacity: .9}});
}})).addTo(map);
var hubLayer = L.layerGroup(B.map(function (h, i) {{
  return L.marker([h[0], h[1]], {{icon: L.divIcon({{className: '', html: '<div class="hub">' + (i + 1) + '</div>', iconSize: [22, 22]}})}})
    .bindPopup('Hub ' + (i + 1) + ' (' + h[5] + '): ' + h[2] + ' stops + ' + h[3] + ' gyms within 300 m' + (h[4] ? '; cloverleaf ' + h[4] + ' per km' : ''));
}})).addTo(map);
L.control.layers(null, {{'Stops and gyms': fortLayer, 'Hops': hopLayer, 'Route hubs': hubLayer}}, {{collapsed: true, position: 'topright'}}).addTo(map);
map.fitBounds(L.latLngBounds(U), {{padding: [10, 10]}});
</script></body></html>"""
open(OUT, "w", encoding="utf-8").write(page)
print(f"{ns} stops + {ng} gyms inside the area, {len(hops)} hops ({sum(h[2] for h in hops)} without a reply), {len(hubs)} hubs -> {OUT} "
      f"({os.path.getsize(OUT) // 1024} KB)")
for a, v in per.items():
    print(f"  {a:38s} {v[0]:5d} stops {v[1]:4d} gyms")
