"""Exhaustive Manhattan-grid loop search: every avenue x street rectangle, scored on the GAME's spots.

  python tools/grid_routes.py [--min 3] [--max 6] [--top 10] [--bbox S,W,N,E]

Intersections come from named OpenStreetMap road ways (avenues x numbered streets). Every block segment
(avenue between two consecutive streets, street between two consecutive avenues) is routed once on the walking
graph and pre-scored with the spots within 80 m (FortSettings.InteractionRangeMeters). A rectangle's score is the
UNION of its four sides' spots (each counts once per lap), so all rectangles are evaluated exactly and fast.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import route_planner as rp  # noqa: E402

AVE_NAMES = {
    "11th Avenue": 11, "West End Avenue": 11, "10th Avenue": 10, "Amsterdam Avenue": 10, "9th Avenue": 9,
    "Columbus Avenue": 9, "8th Avenue": 8, "Central Park West": 8, "7th Avenue": 7, "Avenue of the Americas": 6,
    "6th Avenue": 6, "5th Avenue": 5, "Fifth Avenue": 5, "Madison Avenue": 4.5, "Park Avenue": 4, "Lexington Avenue": 3.5,
    "3rd Avenue": 3, "2nd Avenue": 2, "1st Avenue": 1,
}
AVE_LABEL = {11: "11th/West End", 10: "10th/Amsterdam", 9: "9th/Columbus", 8: "8th/CPW", 7: "7th", 6: "6th",
             5: "5th", 4.5: "Madison", 4: "Park", 3.5: "Lexington", 3: "3rd", 2: "2nd", 1: "1st"}
ROADS = {"primary", "secondary", "tertiary", "residential", "unclassified", "living_street", "primary_link",
         "secondary_link", "tertiary_link", "pedestrian", "service"}


def street_no(name):
    m = re.match(r"^(?:East|West)?\s*(\d+)(?:st|nd|rd|th)\s+Street$", name or "")
    return int(m.group(1)) if m else None


def build(bbox):
    s, w, n, e = bbox
    d = json.load(open(rp.WAYS, encoding="utf-8"))
    node_ave, node_st = defaultdict(set), defaultdict(set)
    for el in d["elements"]:
        t = el.get("tags", {})
        if el["type"] != "way" or t.get("highway") not in ROADS:
            continue
        nm = t.get("name", "")
        ave = AVE_NAMES.get(nm)
        st = street_no(nm)
        if ave is None and st is None:
            continue
        for nid, g in zip(el.get("nodes") or [], el.get("geometry") or []):
            if s <= g["lat"] <= n and w <= g["lon"] <= e:
                (node_ave[nid].add(ave) if ave is not None else node_st[nid].add(st))
    inter = {}
    for nid in set(node_ave) & set(node_st):
        for a in node_ave[nid]:
            for st in node_st[nid]:
                inter.setdefault((a, st), nid)
    return inter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=3.0)
    ap.add_argument("--max", type=float, default=6.0)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--bbox", default="40.740,-74.005,40.785,-73.955")
    a = ap.parse_args()
    bbox = tuple(float(x) for x in a.bbox.split(","))
    pos, adj = rp.load_graph(bbox)
    spots, read_at = rp.load_spots(bbox)
    age = rp.snapshot_age_s(read_at)
    print(f"spots from the map snapshot read at {read_at} ({'?' if age is None else round(age / 60)} min old);"
          f" 'lured' below is the state at that time, not now", flush=True)
    inter = {k: v for k, v in build(bbox).items() if v in pos}
    aves = sorted({k[0] for k in inter}, reverse=True)
    sts = sorted({k[1] for k in inter})
    print(f"intersections {len(inter)} | avenues {[AVE_LABEL.get(x, x) for x in aves]} | streets {sts[0]}..{sts[-1]} ({len(sts)})", flush=True)
    lat0 = (bbox[0] + bbox[2]) / 2
    sg = rp.Grid(lat0, 80.0)
    for k, v in spots.items():
        sg.add(v["p"], k)

    def cover(pts):
        c = set()
        for p, q in zip(pts, pts[1:]):
            mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            for sid in sg.near(mid, rp.RANGE + rp.hav(p, q) / 2):
                if sid not in c and rp.seg_dist(spots[sid]["p"], p, q) <= rp.RANGE:
                    c.add(sid)
        return c
    seg = {}                                          # (kind, fixed, from, to) -> (path points, metres, spots)

    def block(u, v):
        key = (u, v)
        if key not in seg:
            path, L = rp.dijkstra(adj, pos, inter[u], inter[v])
            seg[key] = None if path is None or L > 3 * rp.hav(pos[inter[u]], pos[inter[v]]) + 50 else ([pos[x] for x in path], L)
            if seg[key]:
                seg[key] = seg[key] + (cover(seg[key][0]),)
        return seg[key]

    def side(fixed_ave, a_or_s, lo, hi):
        """Walk along an avenue (streets lo..hi) or a street (avenues lo..hi) as a chain of block segments."""
        pts, L, cov = [], 0.0, set()
        chain = [x for x in (sts if fixed_ave else aves) if lo <= x <= hi] if fixed_ave else [x for x in aves if min(lo, hi) <= x <= max(lo, hi)]
        if not fixed_ave:
            chain = sorted(chain, reverse=True)
        for x, y in zip(chain, chain[1:]):
            u, v = ((a_or_s, x), (a_or_s, y)) if fixed_ave else ((x, a_or_s), (y, a_or_s))
            if u not in inter or v not in inter:
                return None
            b = block(u, v)
            if b is None:
                return None
            pts += b[0] if not pts else b[0][1:]
            L += b[1]
            cov |= b[2]
        return pts, L, cov
    results = []
    for i, A1 in enumerate(aves):
        for A2 in aves[i + 1:]:
            for j, S1 in enumerate(sts):
                for S2 in sts[j + 1:]:
                    w_ = side(True, A1, S1, S2)          # up the west avenue
                    if w_ is None:
                        continue
                    n_ = side(False, S2, A2, A1)         # across the north street
                    e_ = side(True, A2, S1, S2)          # the east avenue (walked down)
                    s_ = side(False, S1, A2, A1)         # back across the south street
                    if not (n_ and e_ and s_):
                        continue
                    L = w_[1] + n_[1] + e_[1] + s_[1]
                    if not (a.min * 1000 <= L <= a.max * 1000):
                        continue
                    cov = w_[2] | n_[2] | e_[2] | s_[2]
                    k = len(cov)
                    results.append((k / (L / 1000), k, L, A1, A2, S1, S2, cov))
    results.sort(key=lambda r: -r[0])
    print(f"rectangles evaluated in {a.min:g}-{a.max:g} km: {len(results)} (block segments routed: {len(seg)})", flush=True)
    out = []
    for dens, k, L, A1, A2, S1, S2, cov in results[:a.top]:
        stops = sum(1 for s in cov if spots[s]["stop"])
        lured = sum(1 for s in cov if spots[s]["lured"])
        print(f"  {dens:5.1f}/km | {k:3d} spots ({stops} stops, {k - stops} gyms, {lured} lured at {read_at[11:16]}) | {L / 1000:.2f} km | "
              f"{AVE_LABEL.get(A1, A1)} <-> {AVE_LABEL.get(A2, A2)}, {S1}th-{S2}th St", flush=True)
        out.append({"density": dens, "spots": k, "km": L / 1000, "ave": [A1, A2], "st": [S1, S2]})
    you = [r for r in results if (r[3], r[4], r[5], r[6]) == (6, 5, 40, 59)]
    if you:
        rank = results.index(you[0]) + 1
        print(f"YOUR loop (6th<->5th, 40th-59th): {you[0][0]:.1f}/km, {you[0][1]} spots, {you[0][2] / 1000:.2f} km -> rank {rank} of {len(results)}")
    json.dump(out, open(os.path.join(rp.OUTDIR if os.path.isdir(rp.OUTDIR) else HERE, "grid_top.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
