"""Plan the routes for the whole SOUTHCOM - Miami - Fort Lauderdale scan: hubs = the densest spots in the bank
(stops + gyms within 300 m, at least SEP apart, inside the scanned hull), one cloverleaf + the plain densest loop
per hub on real streets (route_planner; Overpass ways per hub box). Writes ROUTES.json for final.py.

A hub qualifies with >= MIN_VALUE stops + gyms within 300 m; an area with no such hub still gets its densest one
(>= AREA_MIN). A route counts as scanned where its points lie within REACH of a hop that got a map reply.

  python plan_region.py TOOLS_DIR HOPS.json OUT.json [KM]
  python plan_region.py TOOLS_DIR HOPS.json - 0 MAX_LAT     only download the ways (+-2.0 km) for hubs south of MAX_LAT
"""
import glob, json, os, sys, time

sys.path.insert(0, sys.argv[1])
import route_planner as rp  # noqa: E402

HOPS, OUT = sys.argv[2], sys.argv[3]
KM = float(sys.argv[4]) if len(sys.argv) > 4 else 5.5
PREFETCH = float(sys.argv[5]) if len(sys.argv) > 5 else None
SEP, RAD, MIN_VALUE, AREA_MIN, REACH = 1300.0, 300.0, 25, 12, 880.0
HALF = (0.016, 0.018)                      # +-1.8 km around a hub (a 5.5 km clover reaches ~1.1 km)
# overpass-api.de answered 502 for minutes on 2026-11-01; z.overpass-api.de and the mail.ru mirror answered (slowly)
MIRRORS = ["https://z.overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
           "https://overpass-api.de/api/interpreter"]


def area_of(p):
    lat, lng = p
    if lng < -80.29 and lat < 25.87:
        return "Doral / SOUTHCOM"
    if lng > -80.145 and lat < 25.875:
        return "Miami Beach"
    if lat < 25.86 and lng >= -80.215:
        return "Miami"
    if lng < -80.215 and lat < 25.84:
        return "Miami west / Airport"
    if lng < -80.215 and lat < 25.98:
        return "Hialeah / Miami Gardens"
    if lat < 25.975:
        return "North Miami / Aventura / Sunny Isles"
    if lat < 26.065:
        return "Hallandale / Hollywood / Dania"
    return "Fort Lauderdale"


def fetch(bb):
    for k in range(8):
        rp.OVERPASS = MIRRORS[k % len(MIRRORS)]
        try:
            t0 = time.time()
            f = rp.ways_for(bb)
            return f, time.time() - t0
        except Exception as e:
            print(f"  ways {bb} via {rp.OVERPASS.split('/')[2]}: {type(e).__name__} {str(e)[:70]}", flush=True)
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"no Overpass server gave the ways for {bb}")


H = json.load(open(HOPS))
hull = [tuple(p) for p in H["hull"]]
LOGS = glob.glob(os.path.join(os.path.dirname(os.path.abspath(HOPS)), "hops*.json.log.jsonl"))   # main pass + re-checks + retries
ok_hops = {tuple(r["p"]) for f in LOGS for r in map(json.loads, open(f)) if r["how"] != "timeout"}
hop_grid = rp.Grid(25.95, 500.0)
for h in ok_hops:
    hop_grid.add(h, h)


def scanned(pts):
    return sum(any(rp.hav(p, h) <= REACH for h in hop_grid.near(p, REACH)) for p in pts) / max(1, len(pts))


def inside(p):
    n, c = len(hull), False
    for i in range(n):
        a, b = hull[i], hull[(i + 1) % n]
        if (a[0] > p[0]) != (b[0] > p[0]) and p[1] < (b[1] - a[1]) * (p[0] - a[0]) / (b[0] - a[0]) + a[1]:
            c = not c
    return c


bbox = (min(p[0] for p in hull), min(p[1] for p in hull), PREFETCH or max(p[0] for p in hull), max(p[1] for p in hull))
spots, _ = rp.load_bank_spots(bbox)
sg = rp.Grid(25.95, 100.0)
for k, v in spots.items():
    sg.add(v["p"], k)
dens = {}
for k, v in spots.items():
    if inside(v["p"]):
        near = [s for s in sg.near(v["p"], RAD) if rp.hav(spots[s]["p"], v["p"]) <= RAD]
        dens[k] = (len(near), sum(spots[s]["stop"] for s in near))
picked = []
for k in sorted(dens, key=lambda k: -dens[k][0]):
    p = spots[k]["p"]
    if all(rp.hav(p, q["p"]) >= SEP for q in picked):
        picked.append({"p": p, "value": dens[k][0], "stops": dens[k][1], "gyms": dens[k][0] - dens[k][1], "area": area_of(p)})
hubs = [h for h in picked if h["value"] >= MIN_VALUE]
for a in sorted({h["area"] for h in picked}):
    if not any(h["area"] == a for h in hubs):
        best = max((h for h in picked if h["area"] == a), key=lambda h: h["value"])
        if best["value"] >= AREA_MIN:
            hubs.append(best)
print(f"{len(spots)} spots in the box, {len(dens)} inside the hull; {len(hubs)} hubs: " +
      ", ".join(f"{h['area']} {h['value']}" for h in hubs), flush=True)
if PREFETCH:
    for h in hubs:
        p = h["p"]
        bb = (round(p[0] - 0.018, 3), round(p[1] - 0.0205, 3), round(p[0] + 0.018, 3), round(p[1] + 0.0205, 3))
        f, s = fetch(bb)
        print(f"  {h['area']:38s} {p[0]:.4f},{p[1]:.4f} -> {f[-48:]} ({s:.0f} s)", flush=True)
    sys.exit(0)

routes = []
for h in hubs:
    bb = (h["p"][0] - HALF[0], h["p"][1] - HALF[1], h["p"][0] + HALF[0], h["p"][1] + HALF[1])
    fetch(bb)
    clover, cs = rp.plan_clover(bb, KM, 4, h["p"], source="bank")
    loop, _ = rp.plan(bb, KM, h["p"], source="bank")
    # the planner budgets with straight lines x 1.30; across canals and bays the real walk comes out much longer
    # (Fort Lauderdale drafts: 10.5 km for 5.5 asked). One re-plan with the budget scaled down, kept if it is shorter.
    if clover["km"] > 1.35 * KM:
        c2, cs2 = rp.plan_clover(bb, KM * KM / clover["km"], 4, h["p"], source="bank")
        if c2["km"] < clover["km"]:
            print(f"  clover re-planned: {clover['km']:.2f} -> {c2['km']:.2f} km", flush=True)
            clover, cs = c2, cs2
    if loop["km"] > 1.35 * KM:
        l2, _ = rp.plan(bb, KM * KM / loop["km"], h["p"], source="bank")
        if l2["km"] < loop["km"]:
            print(f"  loop re-planned: {loop['km']:.2f} -> {l2['km']:.2f} km", flush=True)
            loop = l2
    hub = clover["hub"]
    hub_ids = [k for k, v in cs.items() if rp.hav(v["p"], hub) <= rp.RANGE]
    cov = set(clover["covered"])
    r = {"area": h["area"], "bbox": bb, "hub": hub, "hub_value": h["value"], "hub_stops300": h["stops"], "hub_gyms300": h["gyms"],
         "km": clover["km"], "stops": clover["stops"], "gyms": clover["gyms"], "petals": clover["petals"],
         "petal_ends": clover["petal_ends"], "points": [[round(a, 6), round(b, 6)] for a, b in clover["points"]],
         "hub_spots": len(hub_ids), "read_at": clover["read_at"], "scanned": scanned(clover["points"] + loop["points"]),
         "loop": {"km": loop["km"], "stops": loop["stops"], "gyms": loop["gyms"],
                  "points": [[round(a, 6), round(b, 6)] for a, b in loop["points"]]},
         "spots": [{"a": round(v["p"][0], 6), "o": round(v["p"][1], 6), "s": 1 if v["stop"] else 0, "c": 1 if k in cov else 0,
                    "h": 1 if k in hub_ids else 0, "t": v["team"] or 0} for k, v in cs.items()]}
    routes.append(r)
    print(f"{h['area']:38s} hub {hub[0]:.5f},{hub[1]:.5f} ({h['stops']}+{h['gyms']} in 300 m) | clover {r['km']:.2f} km "
          f"{r['stops']}+{r['gyms']} = {(r['stops'] + r['gyms']) / r['km']:.1f}/km | loop {loop['km']:.2f} km "
          f"{loop['stops']}+{loop['gyms']} = {(loop['stops'] + loop['gyms']) / loop['km']:.1f}/km | scanned {r['scanned']:.0%}", flush=True)
json.dump({"km_asked": KM, "routes": routes}, open(OUT, "w"))
print(f"{len(routes)} routes -> {OUT}")
