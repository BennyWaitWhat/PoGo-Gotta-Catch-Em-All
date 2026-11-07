"""Render the Singapore routes page (copy of miami_ftl/final.py; only names, places and titles differ) (self-contained HTML: OSM base maps as JPEG + SVG overlays) plus one GPX, one
WALK-waypoints file and one stepper path per route.

  python final.py ROUTES.json DATA_DIR OUT_DIR SCAN_NOTE
"""
import base64, html, io, json, math, os, re, sys, time
import requests
from PIL import Image

ROUTES, DATA, OUT, SCAN_NOTE = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
TILES = os.path.join(DATA, "tiles")
SECRETISH = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|tskey-(?:auth|client|api)-[0-9A-Za-z]{8,}|gh[pousr]_[0-9A-Za-z]{30,}")  # = triple_check SECRET
os.makedirs(TILES, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "pogo-route-preview/1.0 (personal one-off route preview)"}
SPEED, MAXPX, MARGIN, R = 10.6, 1800, 70, 6371008.8
PETAL = ["#ff6a00", "#7b3fe4", "#00a383", "#d81b60", "#1e88e5", "#6d4c41"]
TEAM = ["#9e9e9e", "#1565c0", "#e53935", "#f9a825"]
PLACES = [("Marina Bay Sands", 1.2834, 103.8607), ("Gardens by the Bay", 1.2816, 103.8636), ("Merlion Park", 1.2868, 103.8545),
          ("Raffles Place", 1.2840, 103.8514), ("Chinatown", 1.2830, 103.8440), ("Clarke Quay", 1.2906, 103.8465),
          ("City Hall / Civic District", 1.2930, 103.8520), ("Bugis", 1.3000, 103.8550), ("Kampong Glam", 1.3025, 103.8590),
          ("Little India", 1.3066, 103.8518), ("Dhoby Ghaut", 1.2990, 103.8456), ("Orchard Road", 1.3040, 103.8320),
          ("Botanic Gardens", 1.3138, 103.8159),
          ("Novena", 1.3204, 103.8438), ("Tiong Bahru", 1.2860, 103.8270), ("HarbourFront / VivoCity", 1.2643, 103.8223),
          ("Sentosa (Resorts World)", 1.2540, 103.8238), ("Sentosa (Siloso)", 1.2560, 103.8100), ("Holland Village", 1.3111, 103.7958),
          ("Bukit Timah", 1.3294, 103.8021), ("Toa Payoh", 1.3326, 103.8474), ("Bishan", 1.3510, 103.8485), ("Ang Mo Kio", 1.3700, 103.8496),
          ("Serangoon", 1.3508, 103.8723), ("Paya Lebar", 1.3180, 103.8930), ("Katong / Joo Chiat", 1.3050, 103.9050),
          ("Geylang", 1.3130, 103.8850), ("Kallang / National Stadium", 1.3040, 103.8740), ("Bedok", 1.3240, 103.9300),
          ("Tampines", 1.3530, 103.9450), ("Pasir Ris", 1.3730, 103.9490), ("Changi Airport (Jewel)", 1.3602, 103.9898),
          ("Hougang", 1.3712, 103.8925), ("Sengkang", 1.3917, 103.8954), ("Punggol", 1.4052, 103.9024), ("Yishun", 1.4294, 103.8350),
          ("Woodlands", 1.4360, 103.7860), ("Sembawang", 1.4491, 103.8201), ("Jurong East", 1.3331, 103.7422),
          ("Jurong Lake Gardens", 1.3410, 103.7280), ("Clementi", 1.3150, 103.7650), ("Bukit Batok", 1.3490, 103.7496),
          ("Choa Chu Kang", 1.3854, 103.7443), ("Bukit Panjang", 1.3786, 103.7620), ("Jurong West", 1.3392, 103.7060),
          ("Queenstown", 1.2944, 103.8060), ("one-north / Buona Vista", 1.3070, 103.7900), ("Kent Ridge / NUS", 1.2966, 103.7764)]


def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return 2 * R * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def seg_dist(p, a, b):
    k = math.cos(math.radians(p[0])) * 111320.0
    ax, ay = (a[1] - p[1]) * k, (a[0] - p[0]) * 111320.0
    bx, by = (b[1] - p[1]) * k, (b[0] - p[0]) * 111320.0
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1.0)))
    return math.hypot(ax + t * dx, ay + t * dy)


def simplify(pts, tol=4.0):
    """Douglas-Peucker in metres (same rule as tools/route_planner.py)."""
    if len(pts) < 3:
        return list(pts)
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


def wpx(lat, lng, z):
    n = 256 * 2 ** z
    s = math.sin(math.radians(lat))
    return (lng + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def tile(z, x, y):
    f = os.path.join(TILES, f"{z}_{x}_{y}.png")
    if not os.path.exists(f):
        r = requests.get(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", headers=UA, timeout=30)
        r.raise_for_status()
        open(f, "wb").write(r.content)
        time.sleep(0.15)
    return Image.open(f).convert("RGB")


def basemap(pts):
    lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
    for z in (17, 16, 15):
        x0, y0 = wpx(max(lats), min(lngs), z)
        x1, y1 = wpx(min(lats), max(lngs), z)
        if max(x1 - x0, y1 - y0) + 2 * MARGIN <= MAXPX:
            break
    x0, y0, x1, y1 = int(x0 - MARGIN), int(y0 - MARGIN), int(x1 + MARGIN), int(y1 + MARGIN)
    img = Image.new("RGB", (x1 - x0, y1 - y0))
    for tx in range(x0 // 256, x1 // 256 + 1):
        for ty in range(y0 // 256, y1 // 256 + 1):
            img.paste(tile(z, tx, ty), (tx * 256 - x0, ty * 256 - y0))
    for q in range(78, 60, -1):           # random base64 can spell a key-shaped run that the repo's secret scan
        buf = io.BytesIO()                # (tools/triple_check.py) rejects: re-encode one step lower until none
        img.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        jpg = base64.b64encode(buf.getvalue()).decode()
        if not SECRETISH.search(jpg):
            break
    return {"z": z, "x0": x0, "y0": y0, "w": img.width, "h": img.height, "jpg": jpg}


GEO = os.path.join(DATA, "geocode.json")
geo = json.load(open(GEO)) if os.path.exists(GEO) else {}


def place(p):
    """The curated name within 800 m, else OpenStreetMap's neighbourhood name for the hub (Nominatim, cached)."""
    name, d = min(((n, hav(p, (a, b))) for n, a, b in PLACES), key=lambda x: x[1])
    if d <= 800:
        return name
    key = f"{p[0]:.4f},{p[1]:.4f}"
    if key not in geo:
        try:
            r = requests.get("https://nominatim.openstreetmap.org/reverse", headers=UA, timeout=20,
                             params={"lat": f"{p[0]:.5f}", "lon": f"{p[1]:.5f}", "zoom": 16, "format": "jsonv2"})
            a = r.json().get("address", {})
            geo[key] = next((a[k] for k in ("neighbourhood", "suburb", "quarter", "hamlet", "village", "city_district", "town", "city")
                             if a.get(k)), "")
            if geo[key]:                       # an empty answer is retried next run, never cached
                json.dump(geo, open(GEO, "w"))
            time.sleep(1.1)                    # Nominatim: at most 1 request a second
        except Exception:
            geo[key] = ""
    return geo[key] or (name if d <= 1500 else f"near {name}")


def files(key, title, pts):
    way = simplify([tuple(p) for p in pts])
    if hav(way[0], way[-1]) > 1:
        way.append(way[0])
    wp = ";".join(f"{a:.6f},{b:.6f}" for a, b in way)
    gpx = "\n".join(['<?xml version="1.0" encoding="UTF-8"?>',
                     '<gpx version="1.1" creator="pogo-route-planner" xmlns="http://www.topografix.com/GPX/1/1">',
                     f"<rte><name>{html.escape(title)}</name>"] + [f'<rtept lat="{a:.6f}" lon="{b:.6f}"/>' for a, b in way] + ["</rte></gpx>"])
    open(os.path.join(OUT, f"{key}.waypoints.txt"), "w").write(wp)
    open(os.path.join(OUT, f"{key}.gpx"), "w", encoding="utf-8").write(gpx)
    json.dump({"line": [list(p) for p in pts] + [list(pts[0])]}, open(os.path.join(DATA, f"path_{key}.json"), "w"))
    return wp, gpx, len(way)


d = json.load(open(ROUTES))
cdens = lambda r: (r["stops"] + r["gyms"]) / r["km"]
ldens = lambda r: (r["loop"]["stops"] + r["loop"]["gyms"]) / r["loop"]["km"]
dens = lambda r: max(cdens(r), ldens(r))   # rank and keep by the better of the two patterns around the hub
best = max(dens(r) for r in d["routes"])
top = {}                                   # the densest route of each area stays even under the 60% bar
for r in d["routes"]:
    if r.get("scanned", 1.0) >= 0.98 and (r.get("area") not in top or dens(r) > dens(top[r["area"]])):
        top[r.get("area")] = r
keep = [r for r in d["routes"] if r.get("scanned", 1.0) >= 0.98 and (dens(r) >= 0.6 * best or top.get(r.get("area")) is r)]
left = sorted((r for r in d["routes"] if r not in keep), key=lambda r: -dens(r))
others = (f'<details class="note"><summary>{len(left)} more hubs, not listed (under 60% of the best and not the best in their area)'
          f'</summary><p>' + "; ".join(f"{html.escape(place(r['hub']))} {dens(r):.1f}/km" for r in left) + "</p></details>") if left else ""
cards, rows = [], []
for i, r in enumerate(sorted(keep, key=lambda r: -dens(r)), 1):
    name = place(r["hub"])
    key = f"r{i}_" + "".join(ch for ch in name.lower() if ch.isalnum())[:16]
    pts, lp = r["points"], r["loop"]["points"]
    m = basemap(pts + lp)
    z, x0, y0 = m["z"], m["x0"], m["y0"]
    P = lambda la, lo: (wpx(la, lo, z)[0] - x0, wpx(la, lo, z)[1] - y0)
    unit = max(m["w"], m["h"]) / 1000.0
    # petals: points[start:end] for each petal, each starting and ending at the hub
    ends, layers, arrows, start = r["petal_ends"], [], [], 0
    for j, end in enumerate(ends):
        seg = pts[max(0, start - 1):end]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in (P(*p) for p in seg))
        col = PETAL[j % len(PETAL)]
        layers.append(f'<polyline class="casing" points="{poly}"/><polyline class="petal" style="stroke:{col}" points="{poly}"/>')
        acc, nxt = 0.0, 150.0
        for a, b in zip(seg, seg[1:]):
            L = hav(a, b)
            while L > 0 and acc + L >= nxt:
                t = (nxt - acc) / L
                pa, pb = P(*a), P(*b)
                x, y = pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t
                ang = math.degrees(math.atan2(pb[1] - pa[1], pb[0] - pa[0]))
                arrows.append(f'<path class="arr" style="fill:{col}" d="M{-6 * unit:.1f} {-5 * unit:.1f} L{7 * unit:.1f} 0 L{-6 * unit:.1f} {5 * unit:.1f} Z" '
                              f'transform="translate({x:.1f} {y:.1f}) rotate({ang:.0f})"/>')
                nxt += 350.0
            acc += L
        start = end
    loop_poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in (P(*p) for p in lp))
    dots = []
    for s in sorted(r["spots"], key=lambda s: (s["c"], -s["s"])):          # covered spots drawn last (on top)
        x, y = P(s["a"], s["o"])
        if not (0 <= x <= m["w"] and 0 <= y <= m["h"]):
            continue
        cls = "on" if s["c"] else "off"
        if s["s"]:
            dots.append(f'<circle class="stop {cls}" cx="{x:.1f}" cy="{y:.1f}" r="{4.2 * unit:.1f}"/>')
        else:
            k = 6.5 * unit
            dots.append(f'<path class="gym {cls}" style="fill:{TEAM[s["t"] % 4]}" d="M{x:.1f} {y - k:.1f} L{x + k:.1f} {y:.1f} L{x:.1f} {y + k:.1f} L{x - k:.1f} {y:.1f} Z"/>')
    hx, hy = P(*r["hub"])
    hub = (f'<g class="hub"><circle cx="{hx:.1f}" cy="{hy:.1f}" r="{14 * unit:.1f}"/>'
           f'<text x="{hx:.1f}" y="{hy + 14 * unit * 0.38:.1f}" font-size="{14 * unit * 1.05:.1f}">H</text></g>')
    title = f"{name} cloverleaf" + (f" ({r['area']})" if r.get("area") and r["area"] not in name else "")
    wp, gpx, nwp = files(key, title, pts)
    lwp, lgpx, _ = files(key + "_loop", f"{name} densest loop", lp)
    km, lap, spots = r["km"], r["km"] / SPEED * 60, r["stops"] + r["gyms"]
    spins = spots + (len(r["petals"]) - 1) * r["hub_spots"]
    lk, ls = r["loop"]["km"], r["loop"]["stops"] + r["loop"]["gyms"]
    petal_txt = " · ".join(f'<b style="color:{PETAL[j % len(PETAL)]}">{x / SPEED * 60:.0f} min</b>' for j, x in enumerate(r["petals"]))
    rows.append((key, title, km, lap, ls / lk, spots / km, spins))
    cards.append(f"""
<article class="card" id="{key}">
  <h3>{i}. {html.escape(title)}</h3>
  <div class="chips"><span class="chip strong">{spots / km:.1f} stops+gyms per km</span><span class="chip">{km:.1f} km lap · {lap:.0f} min</span>
    <span class="chip">{r['stops']} stops + {r['gyms']} gyms</span><span class="chip">{spins} spins per lap</span>{f'<span class="chip strong">plain loop {ls / lk:.1f}/km</span>' if ls / lk > spots / km else ''}</div>
  <figure class="map"><svg viewBox="0 0 {m['w']} {m['h']}" role="img" aria-label="Map of the {html.escape(title)}">
    <image href="data:image/jpeg;base64,{m['jpg']}" width="{m['w']}" height="{m['h']}"/>
    <g class="clover">{''.join(layers)}{''.join(arrows)}</g>
    <g class="loop" hidden><polyline class="casing" points="{loop_poly}"/><polyline class="plain" points="{loop_poly}"/></g>
    {''.join(dots)}{hub}
  </svg></figure>
  <p class="why">Hub <b>H</b>: {r['hub_stops300']} stops + {r['hub_gyms300']} gyms within 300 m, the densest point in this part of the scan.
    {len(r['petals'])} petals: {petal_txt}. Every petal ends back at the hub after at least 5 min, so the hub's {r['hub_spots']} stops and gyms
    are off cooldown each pass ({spins} spins per lap).</p>
  <p class="alt">Densest plain loop around the same hub: {lk:.1f} km, {ls} stops + gyms = <b>{ls / lk:.1f}/km</b>, no repeats.</p>
  <div class="actions">
    <button type="button" data-copy="{key}">Copy waypoints</button>
    <button type="button" data-gpx="{key}">Download GPX</button>
    <button type="button" data-toggle="{key}">Show plain loop</button>
    <button type="button" data-copy="{key}_loop">Copy loop waypoints</button>
    <a class="btn" href="https://www.google.com/maps/search/?api=1&amp;query={r['hub'][0]:.6f},{r['hub'][1]:.6f}" target="_blank" rel="noopener">Hub in Google Maps</a>
  </div>
  <script type="application/json" id="wp-{key}">{json.dumps({"name": title, "wp": wp, "gpx": gpx})}</script>
  <script type="application/json" id="wp-{key}_loop">{json.dumps({"name": title + " (plain loop)", "wp": lwp, "gpx": lgpx})}</script>
</article>""")
    print(f"{key:24s} z{z} {m['w']}x{m['h']} {km:.2f} km {spots} spots {spots / km:.1f}/km {spins} spins {nwp} waypoints")

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Singapore Routes</title>
<style>
:root {{ --bg:#f6f5f1; --card:#ffffff; --fg:#1d1d1b; --mut:#66645e; --line:#e2dfd7; --accent:#ff6a00; --accent-ink:#ffffff;
  --chip:#efece5; --ok:#1f8a4c; --note-bg:#eef5ff; --note-line:#b9d3f5; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141412; --card:#1d1d1a; --fg:#ecebe6; --mut:#a5a39b;
  --line:#2f2e2a; --chip:#2a2925; --note-bg:#16202d; --note-line:#2c4566; }} }}
:root[data-theme="dark"] {{ --bg:#141412; --card:#1d1d1a; --fg:#ecebe6; --mut:#a5a39b; --line:#2f2e2a; --chip:#2a2925;
  --note-bg:#16202d; --note-line:#2c4566; }}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:880px; margin:0 auto; padding:20px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; letter-spacing:-.01em; }}
.sub {{ color:var(--mut); margin:0 0 16px; }}
.note {{ background:var(--note-bg); border:1px solid var(--note-line); border-radius:10px; padding:10px 12px; margin:0 0 20px; }}
details.note summary {{ cursor:pointer; font-weight:600; }}
.tablewrap {{ overflow-x:auto; margin:0 0 24px; }} .tablewrap table {{ margin:0; }}
@media (max-width:480px) {{ th.lap, td.lap {{ display:none; }} }}
table {{ width:100%; border-collapse:collapse; font-size:14px; margin:0 0 24px; }}
th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }}
th {{ color:var(--mut); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
td.num,th.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
td a {{ color:inherit; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px; margin:0 0 18px; }}
.card h3 {{ margin:0 0 8px; font-size:18px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:6px; margin:0 0 10px; }}
.chip {{ background:var(--chip); border-radius:999px; padding:2px 10px; font-size:13px; }}
.chip.strong {{ background:var(--accent); color:var(--accent-ink); font-weight:600; }}
.map {{ margin:0; border-radius:10px; overflow:hidden; border:1px solid var(--line); background:var(--chip); }}
.map svg {{ display:block; width:100%; height:auto; max-height:80vh; }}
.map svg [hidden] {{ display:none; }}
.petal {{ fill:none; stroke-width:4.5; stroke-linejoin:round; stroke-linecap:round; vector-effect:non-scaling-stroke; }}
.plain {{ fill:none; stroke:#1d1d1b; stroke-width:3.5; stroke-dasharray:7 5; stroke-linejoin:round; vector-effect:non-scaling-stroke; }}
.casing {{ fill:none; stroke:#ffffff; stroke-width:8; stroke-linejoin:round; stroke-linecap:round; opacity:.85; vector-effect:non-scaling-stroke; }}
.stop {{ fill:#1e88e5; stroke:#ffffff; stroke-width:1.2; vector-effect:non-scaling-stroke; }}
.gym {{ stroke:#ffffff; stroke-width:1.4; vector-effect:non-scaling-stroke; }}
.off {{ opacity:.38; }}
.hub circle {{ fill:#1d1d1b; stroke:#fff; stroke-width:2.5; vector-effect:non-scaling-stroke; }}
.hub text {{ fill:#fff; font-weight:700; text-anchor:middle; font-family:system-ui,sans-serif; }}
.why {{ margin:10px 0 4px; }}
.alt {{ color:var(--mut); font-size:14px; margin:0 0 10px; }}
.actions {{ display:flex; flex-wrap:wrap; gap:8px; }}
button, .btn {{ font:inherit; font-size:14px; border:1px solid var(--line); background:var(--chip); color:var(--fg); border-radius:8px;
  padding:7px 12px; cursor:pointer; text-decoration:none; }}
button:hover, .btn:hover {{ border-color:var(--accent); }}
.key {{ display:flex; flex-wrap:wrap; gap:12px; color:var(--mut); font-size:13px; margin:0 0 18px; }}
.key svg {{ vertical-align:-3px; }}
footer {{ color:var(--mut); font-size:12.5px; margin-top:28px; }}
footer a {{ color:inherit; }}
</style></head>
<body><main>
<h1>Cloverleaf routes, Singapore</h1>
<p class="sub">Planned on real sidewalks and paths through the stops and gyms your game showed during the scan. Each hub has a cloverleaf and
the densest plain loop (button under the map); ranked by the denser of the two (bold in the table). Each area's best hub is listed even when it is less dense.</p>
<div class="note">{SCAN_NOTE}</div>
<div class="tablewrap"><table><thead><tr><th>Route</th><th class="num">Clover /km</th><th class="num">Loop /km</th><th class="num lap">Clover lap</th></tr></thead><tbody>
{''.join(f'<tr><td><a href="#{k}">{html.escape(t)}</a></td><td class="num">{"<b>" if pk >= lpk else ""}{pk:.1f}{"</b>" if pk >= lpk else ""}</td><td class="num">{"<b>" if lpk > pk else ""}{lpk:.1f}{"</b>" if lpk > pk else ""}</td><td class="num lap">{km:.1f} km · {lap:.0f} min</td></tr>' for k, t, km, lap, lpk, pk, sp in rows)}
</tbody></table></div>
<div class="key">
  <span><svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="#1e88e5" stroke="#fff"/></svg> stop in range</span>
  <span><svg width="16" height="16"><path d="M8 1 L15 8 L8 15 L1 8 Z" fill="#e53935" stroke="#fff"/></svg> gym (team colour)</span>
  <span><svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="#1e88e5" opacity=".38"/></svg> faded = not on the route</span>
  <span><svg width="16" height="16"><circle cx="8" cy="8" r="7" fill="#1d1d1b"/><text x="8" y="12" font-size="10" fill="#fff" text-anchor="middle" font-weight="700">H</text></svg> hub, start and end of every petal</span>
</div>
{''.join(cards)}
{others}
<footer>
<p>In range = within 80 m of the route (the game's interaction range); each stop counts once per lap, except the hub's, which you pass once
per petal. Lap time at {SPEED:g} km/h (full egg credit). Waypoints = the route simplified to 4 m, for the joystick's WALK command; the
GPX is the same line.</p>
<p>Map tiles and walking paths © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>.</p>
</footer>
</main>
<script>
function data(key) {{ return JSON.parse(document.getElementById('wp-' + key).textContent); }}
function flash(btn, text) {{ var t = btn.textContent; btn.textContent = text; setTimeout(function () {{ btn.textContent = t; }}, 1400); }}
function copyText(text) {{
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  return new Promise(function (ok, bad) {{
    var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try {{ document.execCommand('copy') ? ok() : bad(); }} catch (e) {{ bad(e); }} finally {{ ta.remove(); }}
  }});
}}
document.addEventListener('click', function (e) {{
  var b = e.target.closest('button'); if (!b) return;
  if (b.dataset.copy) copyText(data(b.dataset.copy).wp).then(function () {{ flash(b, 'Copied'); }}, function () {{ flash(b, 'Copy failed'); }});
  if (b.dataset.gpx) {{
    var d = data(b.dataset.gpx), a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([d.gpx], {{type: 'application/gpx+xml'}}));
    a.download = b.dataset.gpx + '.gpx'; document.body.appendChild(a); a.click(); a.remove();
  }}
  if (b.dataset.toggle) {{
    var card = document.getElementById(b.dataset.toggle), loop = card.querySelector('.loop'), clover = card.querySelector('.clover');
    var showLoop = loop.hasAttribute('hidden');
    if (showLoop) {{ loop.removeAttribute('hidden'); clover.setAttribute('hidden', ''); b.textContent = 'Show cloverleaf'; }}
    else {{ loop.setAttribute('hidden', ''); clover.removeAttribute('hidden'); b.textContent = 'Show plain loop'; }}
  }}
}});
</script>
</body></html>"""
path = os.path.join(OUT, "singapore_routes.html")
open(path, "w", encoding="utf-8").write(page)
print(f"page {os.path.getsize(path) / 1024:.0f} KB -> {path}")
