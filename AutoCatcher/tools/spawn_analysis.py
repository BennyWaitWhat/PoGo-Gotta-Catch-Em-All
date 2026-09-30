"""Spawn timing from recorded map downloads (map_recorder.py JSONL). Game data only; positions from spawn-point tokens.

  python tools/spawn_analysis.py FILE.jsonl [FILE2.jsonl ...]

Per wild encounter: first/last seen, its LastModifiedMs, spawn point (S2 level-20 token -> position), distance from
the player when it first appeared. Per minute: new arrivals and active count. Spawn points seen with more than one
encounter give the respawn interval.
"""
import json
import math
import statistics as st
import sys
import time
from collections import defaultdict

import s2sphere


def meters(a, b):
    r = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return 2 * r * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def hm(ms):
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000))


def main():
    events = []
    for fn in sys.argv[1:]:
        with open(fn, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    events.append(json.loads(ln))
                except ValueError:
                    pass
    events.sort(key=lambda e: e.get("t", 0))
    reqs = [(e["t"], (e["lat"], e["lng"]), e.get("spd")) for e in events if e.get("k") == "req" and e.get("lat")]
    resps = [e for e in events if e.get("k") == "resp"]
    if not resps:
        sys.exit("no map responses recorded")
    enc = {}
    for e in resps:
        for w in e.get("wild") or []:
            x = enc.setdefault(w[0], {"first": e["t"], "last": e["t"], "sp": w[1], "lastmod": set(), "species": w[6], "n": 0})
            x["last"] = e["t"]
            x["n"] += 1
            x["lastmod"].add(int(w[5]) if w[5] else 0)

    def pos_at(t):
        best = min(reqs, key=lambda r: abs(r[0] - t)) if reqs else None
        return best[1] if best and abs(best[0] - t) < 15000 else None

    dists, lag = [], []
    for x in enc.values():
        try:
            ll = s2sphere.CellId.from_token(x["sp"]).to_lat_lng()
            x["pos"] = (ll.lat().degrees, ll.lng().degrees)
        except Exception:
            x["pos"] = None
        p = pos_at(x["first"])
        if p and x["pos"]:
            dists.append(meters(p, x["pos"]))
        lag.append((x["first"] - min(x["lastmod"])) / 1000)
    t0, t1 = resps[0]["t"], resps[-1]["t"]
    print(f"recorded {hm(t0)} - {hm(t1)} ({(t1 - t0) / 60000:.1f} min): {len(reqs)} map requests, {len(resps)} responses, "
          f"{len(enc)} unique wild Pokemon, {len({x['sp'] for x in enc.values()})} spawn points")
    if reqs:
        gaps = [(b[0] - a[0]) / 1000 for a, b in zip(reqs, reqs[1:])]
        print(f"map request interval: median {st.median(gaps):.1f} s, p90 {sorted(gaps)[int(len(gaps) * 0.9)]:.1f} s "
              f"| response interval: median {st.median([(b['t'] - a['t']) / 1000 for a, b in zip(resps, resps[1:])]):.1f} s")
    if dists:
        ds = sorted(dists)
        print(f"distance from you when a wild Pokemon first appears in the map data: median {st.median(ds):.0f} m, "
              f"p90 {ds[int(len(ds) * 0.9)]:.0f} m, max {ds[-1]:.0f} m")
    ls = sorted(lag)
    print(f"LastModifiedMs vs first seen: median {st.median(ls):.0f} s before first seen (min {ls[0]:.0f}, max {ls[-1]:.0f} s)")
    vis = sorted((x["last"] - x["first"]) / 1000 for x in enc.values())
    print(f"time each Pokemon stayed in your map data: median {st.median(vis):.0f} s, p90 {vis[int(len(vis) * 0.9)]:.0f} s")
    per_min = defaultdict(lambda: [0, set()])
    for k, x in enc.items():
        per_min[int(x["first"] // 60000)][0] += 1
    for e in resps:
        for w in e.get("wild") or []:
            per_min[int(e["t"] // 60000)][1].add(w[0])
    print("per minute: new wild arrivals / distinct wild in the map data (speed km/h)")
    spd_at = {int(r[0] // 60000): r[2] for r in reqs}
    for m in sorted(per_min):
        print(f"   {time.strftime('%H:%M', time.localtime(m * 60))}  new {per_min[m][0]:3d}  active {len(per_min[m][1]):3d}"
              f"  ({(spd_at.get(m) or 0):.0f})  " + "#" * per_min[m][0])
    lm = defaultdict(int)
    for x in enc.values():
        lm[time.localtime(min(x["lastmod"]) / 1000).tm_min] += 1
    print("LastModifiedMs minute-of-hour histogram:", dict(sorted(lm.items())))
    bysp = defaultdict(list)
    for k, x in enc.items():
        bysp[x["sp"]].append(x)
    re_sp = [(sp, sorted(v, key=lambda y: y["first"])) for sp, v in bysp.items() if len(v) > 1]
    if re_sp:
        gaps = [(b["first"] - a["first"]) / 60000 for _, v in re_sp for a, b in zip(v, v[1:])]
        print(f"spawn points seen with >1 encounter: {len(re_sp)} (re-spawn gaps, min: {sorted(round(g, 1) for g in gaps)[:20]})")


if __name__ == "__main__":
    main()
