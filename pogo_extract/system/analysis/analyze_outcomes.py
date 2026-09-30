"""Analyse the FULL outcome stream (CATCH + LOSS lines) that the catcher now emits.
These are the questions that were impossible while only failures were logged:
  * probability CALIBRATION — does base p actually predict the catch rate (via p_real = 1-(1-p)^3.4)?
  * per-BALL success — is Ultra earning its scarcity vs Poke?
  * per-DISTANCE success — does an on-screen far spawn really catch as well as a near one?
  * per-SOURCE and per-SPECIES success — which spawns waste balls?
  * attempts distribution — is the 12-throw budget ever used?
"""
import re, sys, collections

LOG = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\system\analysis\pokemod\catch_loop.SAMPLE.log"

rows = []
seen_catch = False   # CATCH logging was added mid-file; before it, only failures were recorded,
                     # so anything earlier would bias every rate downwards. Start at the first CATCH.
for ln in open(LOG, encoding="utf-8", errors="replace"):
    if " CATCH r=" in ln:
        seen_catch = True
    if not seen_catch:
        continue
    if " CATCH r=" not in ln and " LOSS r=" not in ln:
        continue
    g = lambda p, c=float: (c(m.group(1)) if (m := re.search(p, ln)) else None)
    rows.append(dict(
        ok=" CATCH r=" in ln,
        r=g(r"\br=(\d+)", int), p=g(r"\bp=(-?[0-9.]+)"), ball=g(r"\bball=(\d+)", int),
        pid=g(r"\bpid=(\d+)", int), att=g(r"\batt=(\d+)", int), dist=g(r"\bdist=(-?\d+)m", int),
        spd=g(r"\bspd=(-?[0-9.]+)"), age=g(r"\bage=([0-9.]+)s"),
        src=(m.group(1) if (m := re.search(r"\bsrc=(\w+)", ln)) else "?")))

if not rows:
    print("no CATCH/LOSS rows found"); sys.exit()

n_ok = sum(1 for r in rows if r["ok"])
print(f"=== OUTCOMES: {len(rows)} throws logged | caught {n_ok} ({100*n_ok/len(rows):.1f}%) ===\n")

def rate(sel, label, fmt="{}"):
    print(label)
    for k, v in sorted(sel.items(), key=lambda kv: str(kv[0])):
        tot = v["n"]; ok = v["ok"]
        if tot >= 3:
            print(f"   {fmt.format(k):<22} n={tot:<5} caught={ok:<5} {100*ok/tot:5.1f}%")
    print()

def bucketise(keyfn):
    d = collections.defaultdict(lambda: {"n": 0, "ok": 0})
    for r in rows:
        k = keyfn(r)
        if k is None: continue
        d[k]["n"] += 1
        d[k]["ok"] += 1 if r["ok"] else 0
    return d

BALLS = {1: "1 Poke", 2: "2 Great", 3: "3 Ultra"}
rate(bucketise(lambda r: BALLS.get(r["ball"])), "--- by BALL ---")

def dband(r):
    d = r["dist"]
    if d is None or d < 0: return None
    for lo, hi in [(0,20),(20,40),(40,60),(60,80),(80,100),(100,1000)]:
        if lo <= d < hi: return f"{lo}-{hi if hi<1000 else '+'}m"
rate(bucketise(dband), "--- by DISTANCE (tests 'on screen = catchable') ---")

def pband(r):
    p = r["p"]
    if p is None or p < 0: return None
    for lo in [0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.8]:
        if p < lo + (0.1 if lo < 0.6 else 0.2): return f"p {lo:.1f}-{lo+(0.1 if lo<0.6 else 0.2):.1f}"
    return "p 1.0"
pb = bucketise(pband)
print("--- CALIBRATION: observed vs predicted p_real = 1-(1-p)^3.4 ---")
for k, v in sorted(pb.items()):
    if v["n"] < 3: continue
    lo = float(k.split()[1].split("-")[0]); hi = float(k.split("-")[1])
    mid = (lo + hi) / 2
    pred = 1 - (1 - mid) ** 3.4
    obs = v["ok"] / v["n"]
    print(f"   {k:<14} n={v['n']:<5} observed={100*obs:5.1f}%   predicted={100*pred:5.1f}%   diff={100*(obs-pred):+5.1f}")
print()

rate(bucketise(lambda r: r["src"]), "--- by SOURCE ---")
rate(bucketise(lambda r: r["att"]), "--- by ATTEMPT # (is the 12-throw budget used?) ---", "att {}")

worst = sorted(bucketise(lambda r: r["pid"]).items(), key=lambda kv: (kv[1]["ok"]/kv[1]["n"], -kv[1]["n"]))
print("--- worst species (n>=4) ---")
for k, v in worst:
    if v["n"] >= 4 and v["ok"] / v["n"] < 0.85:
        print(f"   pid {k:<6} n={v['n']:<4} caught={v['ok']:<4} {100*v['ok']/v['n']:5.1f}%")
ages = [r["age"] for r in rows if r["age"] is not None]
if ages:
    ages.sort()
    print(f"\n--- throw->result latency: median={ages[len(ages)//2]:.2f}s max={ages[-1]:.2f}s ---")
