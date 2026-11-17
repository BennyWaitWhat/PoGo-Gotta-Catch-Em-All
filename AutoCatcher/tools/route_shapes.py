"""Symmetric joystick routes -- an infinity, or an eye (the infinity inside a ring) -- fitted to the PokeStops / gyms the GAME reports.

  python tools/route_shapes.py --near LAT,LNG [--radius 1100] [--shape infinity|eye] [--name NAME] [--spots map|bank] [--no-tiles]

Benny 2026-11-17 (Avalon, Alpharetta): "make a beautiful symmetrical route", after 10-31 "remember highest pokestop densities.
make a cool pattern". route_planner.py walks real ways, so its loops are never symmetric. This one draws the exact curve (a
spoofed walk needs no sidewalk) and picks its place, size and angle by what it reaches:

  infinity  x = A cos t, y = B sin 2t: two equal lobes through one crossing, laid along the densest strip. Each lobe is a lap of
            its own, so the crossing's stops are passed twice per lap.
  eye       the same infinity twice, then a ring through both lobe tips (same centre, same axis): the strip stays the main
            course, the ring reaches what lies around it.

A spot counts when the path passes within 80 m (FortSettings.InteractionRangeMeters); the fit uses PLAN_M (a margin under it).
Spins per hour = a steady-state walk at the joystick's real jogging speed with the 5-min spin cooldown per spot.
Spots: system/analysis/map_full.json (tools/map_read.py, one read-only pass; the game holds about 1 km around the player) or
--spots bank (pogo_wigle.db). Outputs in system/map/routes/<name>.*: .gpx (GPS Joystick route import), .waypoints.txt (the
joystick WALK command), .html (offline map: every spot + the route), .png (preview). Unknown arguments: rc 2, nothing is run.
"""
import argparse
import base64
import html
import io
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import route_planner as rp  # noqa: E402

RANGE_M = 80.0                 # FortSettings.InteractionRangeMeters (dumped from the client)
PLAN_M = 72.0                  # the fit's margin under the range
COOL_S = 300.0                 # a spot's spin cooldown
SPEED = 10.33 / 3.6            # the joystick's REAL jogging speed, m/s (label 10.4: reference-gps-joystick-control)
STEP_M = 8.0                   # path sampling for scoring
WP_M = 12.0                    # waypoint spacing in the exported route
KY = 111320.0


def to_xy(p, o):
    return ((p[1] - o[1]) * KY * math.cos(math.radians(o[0])), (p[0] - o[0]) * KY)


def to_ll(x, y, o):
    return (o[0] + y / KY, o[1] + x / (KY * math.cos(math.radians(o[0]))))


def _rot(x, y, cx, cy, rot):
    c, s = math.cos(rot), math.sin(rot)
    return np.column_stack([cx + x * c - y * s, cy + x * s + y * c])


def infinity(cx, cy, A, B, rot, n=900):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return _rot(A * np.cos(t), B * np.sin(2 * t), cx, cy, rot)


def ring(cx, cy, A, B, rot, n=900):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return _rot(A * np.cos(t), B * np.sin(t), cx, cy, rot)


def resample(P, step):
    """A closed path at even spacing: (points, length)."""
    Q = np.vstack([P, P[:1]])
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*(Q[1:] - Q[:-1]).T))])
    u = np.arange(0, s[-1], step)
    return np.column_stack([np.interp(u, s, Q[:, 0]), np.interp(u, s, Q[:, 1])]), float(s[-1])


def in_range(P, F, rng=PLAN_M, step=STEP_M):
    R, L = resample(P, step)
    d2 = (R[:, None, 0] - F[None, :, 0]) ** 2 + (R[:, None, 1] - F[None, :, 1]) ** 2
    return d2 <= rng * rng, L


def spins_per_hour(inr, L, step=STEP_M):
    """Steady state: 4 laps walked, laps 2-4 counted; a spot is spun when in range and 300 s past its last spin."""
    dt, n, total = step / SPEED, inr.shape[0], 0
    for j in range(inr.shape[1]):
        last = -1e9
        for lap in range(4):
            for i in np.flatnonzero(inr[:, j]):
                t = (lap * n + i) * dt
                if t - last >= COOL_S:
                    last = t
                    total += lap >= 1
    return total / (3 * L / SPEED) * 3600


KEEP_RATE = 0.95               # the biggest figure whose spins per hour stay within 5% of the best one wins


def fit_infinity(F, R):
    """Place, size and angle of the infinity. Every SIZE gets its own best fit (most spots per metre of lap; coarse grid
    around the spots' centre and main axis, then a fine grid), each is walked for its spins per hour, and the figure that
    reaches the MOST spots while staying within 5% of the best rate wins -- a small loop on the densest corner and a
    big one down the whole strip spin about equally often, and the big one covers the area (Avalon 11-17: 29 vs 40 spots)."""
    c0 = F.mean(axis=0)
    w, v = np.linalg.eigh(np.cov((F - c0).T))
    ax0 = math.atan2(v[1, -1], v[0, -1])                          # the main axis of the spots
    if ax0 > math.pi / 2:
        ax0 -= math.pi
    if ax0 <= -math.pi / 2:
        ax0 += math.pi
    min_lap = COOL_S * SPEED

    def proxy(prm):
        inr, L = in_range(infinity(*prm, n=360), F)
        return int(inr.any(axis=0).sum()) / max(L, min_lap)

    coarse = []
    for cx in np.arange(c0[0] - 280, c0[0] + 281, 40):
        for cy in np.arange(c0[1] - 280, c0[1] + 281, 40):
            for A in np.arange(300, max(340, min(0.62 * R, 720)) + 1, 40):
                for B in (70, 90, 110, 140):
                    for dr in (-12, -6, 0, 6, 12):
                        prm = (float(cx), float(cy), float(A), float(B), ax0 + math.radians(dr))
                        coarse.append((proxy(prm), prm))
    finalists = []
    for A in sorted({r[1][2] for r in coarse}):
        seeds = sorted((r for r in coarse if r[1][2] == A), key=lambda r: -r[0])[:2]
        fine = []
        for _, (cx, cy, _A, B, rot) in seeds:
            for dx in (-20, -10, 0, 10, 20):
                for dy in (-20, -10, 0, 10, 20):
                    for dA in (-10, 0, 10):
                        for dB in (-20, -10, 0, 10, 20):
                            for dr in (-3, -1.5, 0, 1.5, 3):
                                prm = (cx + dx, cy + dy, A + dA, max(50.0, B + dB), rot + math.radians(dr))
                                fine.append((proxy(prm), prm))
        fine.sort(key=lambda r: -r[0])
        for _, prm in fine[:3]:
            inr, L = in_range(infinity(*prm), F)
            finalists.append((spins_per_hour(inr, L), int(inr.any(axis=0).sum()), prm))
    top = max(f[0] for f in finalists)
    return max((f for f in finalists if f[0] >= KEEP_RATE * top), key=lambda f: (f[1], f[0]))[2]


def fit_ring(F, prm):
    """The ring's half-width: the most spots reached together with the infinity, the shorter ring on a tie."""
    cx, cy, A, B, rot = prm
    base, _ = in_range(infinity(*prm), F)
    base = base.any(axis=0)
    best = None
    for Br in np.arange(B + 120, max(B + 140, 0.9 * A) + 1, 20):
        inr, L = in_range(ring(cx, cy, A, float(Br), rot), F)
        key = (int((base | inr.any(axis=0)).sum()), -L)
        if best is None or key > best[0]:
            best = (key, float(Br))
    return best[1]


def build(shape, prm, br=None):
    if shape == "infinity":
        return infinity(*prm)
    return np.vstack([infinity(*prm), infinity(*prm), ring(prm[0], prm[1], prm[2], br, prm[4])])   # 8, 8, ring: all from the same tip


def mirror_error(P, prm):
    """How symmetric the exported path is: the worst distance from a mirrored waypoint (both axes) back to the path."""
    cx, cy, _, _, rot = prm
    c, s = math.cos(-rot), math.sin(-rot)
    Q = np.column_stack([(P[:, 0] - cx) * c - (P[:, 1] - cy) * s, (P[:, 0] - cx) * s + (P[:, 1] - cy) * c])
    D, _ = resample(Q, 1.0)
    worst = 0.0
    for M in (Q * [1, -1], Q * [-1, 1]):
        d = np.sqrt(((M[:, None, :] - D[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
        worst = max(worst, float(d.max()))
    return worst


def tiles(o, half_m, zoom=16):
    """An OpenStreetMap background for the square of +-half_m around o: (JPEG bytes, [x0, y0, x1, y1] in metres) or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    n = 2 ** zoom

    def tx(lng):
        return (lng + 180.0) / 360.0 * n

    def ty(lat):
        return (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    s, w = to_ll(-half_m, -half_m, o)
    nn, e = to_ll(half_m, half_m, o)
    x0, x1, y0, y1 = int(tx(w)), int(tx(e)), int(ty(nn)), int(ty(s))
    if (x1 - x0 + 1) * (y1 - y0 + 1) > 64:
        return None
    img = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    try:
        for X in range(x0, x1 + 1):
            for Y in range(y0, y1 + 1):
                req = urllib.request.Request(f"https://tile.openstreetmap.org/{zoom}/{X}/{Y}.png", headers={"User-Agent": "pogo-route-planner/1.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    img.paste(Image.open(io.BytesIO(r.read())).convert("RGB"), ((X - x0) * 256, (Y - y0) * 256))
    except Exception as ex:
        print(f"  (no map background: {type(ex).__name__}: {ex})")
        return None

    def lng_of(X):
        return X / n * 360.0 - 180.0

    def lat_of(Y):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * Y / n))))
    ax0, ay1 = to_xy((lat_of(y0), lng_of(x0)), o)                 # top-left corner of the stitched image, metres
    ax1, ay0 = to_xy((lat_of(y1 + 1), lng_of(x1 + 1)), o)         # bottom-right
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=72, optimize=True)                # (a PNG of the same tiles made each page 1.9 MB)
    return buf.getvalue(), [ax0, ay0, ax1, ay1]


def view_of(way_xy, margin=230.0):
    """The close-up frame: the route plus a margin, [x0, y0, x1, y1] in metres."""
    return [float(way_xy[:, 0].min() - margin), float(way_xy[:, 1].min() - margin), float(way_xy[:, 0].max() + margin), float(way_xy[:, 1].max() + margin)]


def render_png(path, way_xy, F, gym, team, cov, view, bg, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    wide = 12.0
    fig, ax = plt.subplots(figsize=(wide, max(4.5, wide * (view[3] - view[1]) / (view[2] - view[0]))), dpi=110)
    fig.patch.set_facecolor("#0e1116")
    ax.set_facecolor("#0e1116")
    if bg:
        from PIL import Image
        ax.imshow(Image.open(io.BytesIO(bg[0])), extent=[bg[1][0], bg[1][2], bg[1][1], bg[1][3]], alpha=0.55, zorder=0)
    W = np.vstack([way_xy, way_xy[:1]])
    for lw, al in ((14, 0.10), (9, 0.18), (5, 0.35)):
        ax.plot(W[:, 0], W[:, 1], color="#ff9d2e", lw=lw, alpha=al, solid_capstyle="round", zorder=2)
    ax.plot(W[:, 0], W[:, 1], color="#ffb04a", lw=2.6, zorder=3)
    tcol = ["#b9b9b9", "#3d8bff", "#ff5148", "#ffd23d"]
    for i in range(len(F)):
        if gym[i]:
            ax.scatter(F[i, 0], F[i, 1], s=170, marker="^", c=tcol[team[i]], edgecolors="white" if cov[i] else "#555", linewidths=1.4, zorder=5,
                       alpha=1 if cov[i] else 0.55)
        else:
            ax.scatter(F[i, 0], F[i, 1], s=62, c="#35d0f2" if cov[i] else "#56707a", edgecolors="white" if cov[i] else "#333", linewidths=0.9,
                       zorder=4, alpha=1 if cov[i] else 0.7)
    ax.scatter([way_xy[0, 0]], [way_xy[0, 1]], s=260, marker="*", c="#7CFC00", edgecolors="black", linewidths=1.2, zorder=6)
    ax.set_xlim(view[0], view[2])
    ax.set_ylim(view[1], view[3])
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color("#30363d")
    ax.set_title(title, color="#e6edf3", fontsize=13, pad=12)
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def page(name, st, way_ll, way_xy, spots, F, gym, team, cov, o, half_m, bg, shape, view):
    """The offline map page: one self-contained file (inline SVG, the background embedded once and shown twice: the
    route close up, then the whole area)."""
    def sx(x):
        return round(x + half_m, 1)

    def sy(y):
        return round(half_m - y, 1)
    tcol = ["#9a9a9a", "#2f7de1", "#e0463f", "#e8b520"]
    tname = ["no team", "blue", "red", "yellow"]
    dots = []
    for i, k in enumerate(spots):
        lat, lng = spots[k]["p"]
        tip = f"{'Gym (' + tname[team[i]] + ')' if gym[i] else 'PokeStop'} {lat:.6f},{lng:.6f} -- {'on the route' if cov[i] else 'not reached'}"
        if gym[i]:
            x, y = sx(F[i, 0]), sy(F[i, 1])
            dots.append(f'<polygon points="{x},{y - 13} {x - 11},{y + 8} {x + 11},{y + 8}" fill="{tcol[team[i]]}" stroke="{"#fff" if cov[i] else "#666"}" '
                        f'stroke-width="2.5" opacity="{1 if cov[i] else .55}"><title>{html.escape(tip)}</title></polygon>')
        else:
            dots.append(f'<circle cx="{sx(F[i, 0])}" cy="{sy(F[i, 1])}" r="{8 if cov[i] else 6}" fill="{"#19b5d8" if cov[i] else "#7d8f96"}" '
                        f'stroke="{"#fff" if cov[i] else "#444"}" stroke-width="2"><title>{html.escape(tip)}</title></circle>')
    pts = " ".join(f"{sx(x)},{sy(y)}" for x, y in np.vstack([way_xy, way_xy[:1]]))
    bgimg = ""
    if bg:
        x0, y0, x1, y1 = bg[1]
        bgimg = (f'<image href="data:image/jpeg;base64,{base64.b64encode(bg[0]).decode()}" x="{sx(x0)}" y="{sy(y1)}" width="{round(x1 - x0, 1)}" '
                 f'height="{round(y1 - y0, 1)}" preserveAspectRatio="none" opacity=".6"/>')
    missed = [(spots[k]["p"], gym[i]) for i, k in enumerate(spots) if not cov[i]]
    rows = "".join(f'<tr><td>{"Gym" if g else "PokeStop"}</td><td><a href="https://www.google.com/maps/search/?api=1&query={p[0]:.6f},{p[1]:.6f}">'
                   f'{p[0]:.6f}, {p[1]:.6f}</a></td><td>{rp.hav(way_ll[0], p):.0f} m</td></tr>' for p, g in missed)
    start = way_ll[0]
    shape_txt = ("An infinity: two equal lobes through one crossing, laid along the densest strip of stops."
                 if shape == "infinity" else
                 "An eye: the infinity twice, then a ring through both lobe tips. One lap = infinity, infinity, ring.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(st['title'])}</title>
<style>
:root {{ --bg:#f7f6f2; --card:#ffffff; --fg:#1b1b19; --mut:#66655f; --line:#e2e0d8; --acc:#d9720a; --map:#e9eef0; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0e1116; --card:#161b22; --fg:#e6edf3; --mut:#9aa4af; --line:#2a313a; --acc:#ffb04a; --map:#10161d; }} }}
:root[data-theme="dark"] {{ --bg:#0e1116; --card:#161b22; --fg:#e6edf3; --mut:#9aa4af; --line:#2a313a; --acc:#ffb04a; --map:#10161d; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:20px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:28px 0 8px; }}
.sub {{ color:var(--mut); margin:0 0 16px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin:0 0 16px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }}
.stat b {{ display:block; font-size:22px; color:var(--acc); }} .stat span {{ color:var(--mut); font-size:13px; }}
.map {{ background:var(--map); border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
svg {{ display:block; width:100%; height:auto; }}
.legend {{ display:flex; flex-wrap:wrap; gap:14px; color:var(--mut); font-size:13px; margin:10px 2px 0; }}
.legend i {{ display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:6px; vertical-align:-1px; }}
ol {{ padding-left:20px; }} li {{ margin:4px 0; }}
code {{ background:var(--card); border:1px solid var(--line); border-radius:6px; padding:1px 6px; font-size:13px; word-break:break-all; }}
.wrap {{ overflow-x:auto; }} table {{ border-collapse:collapse; width:100%; font-size:14px; }}
td,th {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); }} th {{ color:var(--mut); font-weight:600; }}
a {{ color:var(--acc); }}
</style></head><body><main>
<h1>{html.escape(st['title'])}</h1>
<p class="sub">{html.escape(shape_txt)} Fitted to the {len(spots)} PokeStops and gyms the game reported at {html.escape(st['read_at'])}
within {st['radius']:.0f} m of {o[0]:.6f}, {o[1]:.6f}.</p>
<div class="stats">
<div class="stat"><b>{st['km']:.2f} km</b><span>one lap</span></div>
<div class="stat"><b>{st['min']:.0f} min</b><span>per lap at 10.4 km/h (jogging)</span></div>
<div class="stat"><b>{st['stops']} + {st['gyms']}</b><span>PokeStops + gyms within 80 m</span></div>
<div class="stat"><b>{st['per_km']:.1f}</b><span>stops and gyms per km</span></div>
<div class="stat"><b>{st['spins_h']:.0f}</b><span>spins per hour (5-min cooldown counted)</span></div>
<div class="stat"><b>{st['of']}</b><span>stops and gyms in the whole area</span></div>
</div>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><g id="lyr">
{bgimg}
<polyline points="{pts}" fill="none" stroke="#ff9d2e" stroke-width="26" stroke-opacity=".22" stroke-linejoin="round"/>
<polyline points="{pts}" fill="none" stroke="#ff8a00" stroke-width="7" stroke-linejoin="round"/>
{''.join(dots)}
<circle cx="{sx(way_xy[0, 0])}" cy="{sy(way_xy[0, 1])}" r="13" fill="#6fdc00" stroke="#000" stroke-width="2.5"><title>Start: {start[0]:.6f},{start[1]:.6f}</title></circle>
</g></defs></svg>
<h2>The route</h2>
<div class="map"><svg viewBox="{sx(view[0])} {sy(view[3])} {view[2] - view[0]:.0f} {view[3] - view[1]:.0f}" role="img" aria-label="The route close up"><use href="#lyr"/></svg></div>
<h2>The whole area: all {len(spots)} PokeStops and gyms</h2>
<div class="map"><svg viewBox="0 0 {2 * half_m:.0f} {2 * half_m:.0f}" role="img" aria-label="Map of the whole area: the route and every PokeStop and gym"><use href="#lyr"/></svg></div>
<div class="legend"><span><i style="background:#19b5d8"></i>PokeStop on the route</span><span><i style="background:#7d8f96"></i>PokeStop not reached</span>
<span><i style="background:#e0463f;border-radius:0;clip-path:polygon(50% 0,0 100%,100% 100%)"></i>Gym (team colour)</span>
<span><i style="background:#6fdc00"></i>Start (nearest point to where you stood)</span><span><i style="background:#ff8a00;border-radius:2px;height:4px"></i>Route</span></div>
<h2>Run it</h2>
<ol>
<li>GPS Joystick: Routes, Import, pick <code>{html.escape(name)}.gpx</code> from the phone's Download folder, then play it on loop in Jogging.</li>
<li>Or from the PC: the joystick WALK command with the line in <code>{html.escape(name)}.waypoints.txt</code> ({len(way_ll)} waypoints, start
<a href="https://www.google.com/maps/search/?api=1&query={start[0]:.6f},{start[1]:.6f}">{start[0]:.6f}, {start[1]:.6f}</a>).</li>
</ol>
<h2>Not reached ({len(missed)})</h2>
<div class="wrap"><table><tr><th>Kind</th><th>Position</th><th>From the start</th></tr>{rows or '<tr><td colspan="3">Everything in the area is on the route.</td></tr>'}</table></div>
<p class="sub" style="margin-top:18px">Symmetry check on the exported waypoints: a mirrored waypoint lands within {st['mirror']:.1f} m of the path on both axes.
Background: OpenStreetMap contributors.</p>
</main></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--near", required=True, help="LAT,LNG: the centre of the area (where the player stands)")
    ap.add_argument("--radius", type=float, default=1100.0)
    ap.add_argument("--shape", choices=["infinity", "eye"], default="infinity")
    ap.add_argument("--name", default="")
    ap.add_argument("--spots", choices=["map", "bank"], default="map")
    ap.add_argument("--no-tiles", action="store_true", help="no OpenStreetMap background (no network at all)")
    a = ap.parse_args()
    o = tuple(float(v) for v in a.near.split(","))
    dlat, dlng = a.radius / KY, a.radius / (KY * math.cos(math.radians(o[0])))
    spots, read_at = rp.load_spots((o[0] - dlat, o[1] - dlng, o[0] + dlat, o[1] + dlng), a.spots)
    spots = {k: v for k, v in spots.items() if rp.hav(o, v["p"]) <= a.radius}
    if len(spots) < 8:
        raise SystemExit(f"only {len(spots)} spots within {a.radius:.0f} m of {o} in the {a.spots} data -- read the map there first (tools/map_read.py)")
    F = np.array([to_xy(v["p"], o) for v in spots.values()])
    gym = np.array([not v["stop"] for v in spots.values()])
    team = [int(v.get("team") or 0) for v in spots.values()]
    t0 = time.time()
    prm = fit_infinity(F, a.radius)
    br = fit_ring(F, prm) if a.shape == "eye" else None
    P = build(a.shape, prm, br)
    R, L = resample(P, WP_M)
    k0 = int(np.argmin(np.hypot(R[:, 0], R[:, 1])))                # start at the point nearest to the player
    R = np.vstack([R[k0:], R[:k0]])
    way_ll = [to_ll(x, y, o) for x, y in R]
    name = a.name or f"shape_{a.shape}_{time.strftime('%Y%m%d_%H%M')}"
    os.makedirs(os.path.dirname(os.path.join(rp.OUTDIR, name)), exist_ok=True)
    base = os.path.join(rp.OUTDIR, name)
    closed = way_ll + [way_ll[0]]
    open(base + ".waypoints.txt", "w").write(";".join(f"{la:.6f},{lo:.6f}" for la, lo in closed))
    gpx = ['<?xml version="1.0" encoding="UTF-8"?>', '<gpx version="1.1" creator="pogo-route-shapes" xmlns="http://www.topografix.com/GPX/1/1">',
           f"<rte><name>{html.escape(os.path.basename(name))}</name>"] + [f'<rtept lat="{la:.6f}" lon="{lo:.6f}"/>' for la, lo in closed] + ["</rte></gpx>"]
    open(base + ".gpx", "w").write("\n".join(gpx))
    # everything below is measured on the EXPORTED waypoints (what the joystick walks), not on the ideal curve
    W = np.array([to_xy(p, o) for p in way_ll])
    inr80, Lw = in_range(W, F, RANGE_M)
    inrp, _ = in_range(W, F, PLAN_M)
    cov = inr80.any(axis=0)
    st = {"title": os.path.basename(name).replace("_", " ").title(), "read_at": read_at, "radius": a.radius, "km": Lw / 1000, "min": Lw / SPEED / 60,
          "stops": int((cov & ~gym).sum()), "gyms": int((cov & gym).sum()), "per_km": cov.sum() / (Lw / 1000), "spins_h": spins_per_hour(inr80, Lw),
          "of": len(spots), "mirror": mirror_error(W, prm), "margin": int(inrp.any(axis=0).sum())}
    half = max(float(np.abs(F).max()), float(np.abs(W).max())) + 90
    bg = None if a.no_tiles else tiles(o, half)
    view = view_of(W)
    render_png(base + ".png", W, F, gym, team, cov, view, bg,
               f"{st['title']}: {st['km']:.2f} km, {st['min']:.0f} min a lap, {st['stops']} stops + {st['gyms']} gyms, {st['spins_h']:.0f} spins/h")
    open(base + ".html", "w", encoding="utf-8").write(page(os.path.basename(name), st, way_ll, W, spots, F, gym, team, cov, o, half, bg, a.shape, view))
    json.dump({"shape": a.shape, "near": o, "radius": a.radius, "read_at": read_at, "centre": to_ll(prm[0], prm[1], o), "half_length_m": prm[2],
               "lobe_half_width_m": prm[3], "axis_deg_from_east": math.degrees(prm[4]), "ring_half_width_m": br,
               **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in st.items()},
               "spots": [{"id": k, "lat": v["p"][0], "lng": v["p"][1], "gym": bool(g), "team": t, "on_route": bool(c)}
                         for (k, v), g, t, c in zip(spots.items(), gym, team, cov)]}, open(base + ".json", "w"), indent=1)
    print(f"{a.shape} fitted in {time.time() - t0:.0f} s: centre {to_ll(prm[0], prm[1], o)[0]:.6f},{to_ll(prm[0], prm[1], o)[1]:.6f}, half-length {prm[2]:.0f} m, "
          f"lobe half-width {prm[3]:.0f} m, axis {math.degrees(prm[4]):.1f} deg from east" + (f", ring half-width {br:.0f} m" if br else ""))
    print(f"  lap {st['km']:.2f} km = {st['min']:.0f} min at 10.4 km/h | within 80 m: {st['stops']} stops + {st['gyms']} gyms of {len(spots)} "
          f"({st['margin']} within the {PLAN_M:.0f} m margin) | {st['per_km']:.1f} per km | {st['spins_h']:.0f} spins/h | {len(closed)} waypoints | "
          f"mirror error {st['mirror']:.1f} m")
    print(f"  wrote {base}.gpx / .waypoints.txt / .html / .png / .json")


if __name__ == "__main__":
    main()
