"""Deep-dive the FULL instrumented log for AREAS OF IMPROVEMENT:
reconnect churn, run stability, proper speed->flee-rate (volume-controlled via deltas),
loss classification, stale-skip effectiveness, throughput."""
import re, collections

LOG = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\system\analysis\pokemod\catch_loop.FULL.log"
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()

def gi(pat, s, cast=float, d=None):
    m = re.search(pat, s); return cast(m.group(1)) if m else d

def tsec(ln):  # HH:MM:SS -> seconds, with day rollover handled by caller
    m = re.match(r"(\d\d):(\d\d):(\d\d)", ln)
    return int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3)) if m else None

summaries, losses = [], []
n_reconnect = n_connect = 0
recon_ts = []   # absolute seconds (rollover-adjusted)
prev_raw, day = None, 0
for ln in lines:
    t = tsec(ln)
    if t is not None:
        if prev_raw is not None and t + 60 < prev_raw:  # rolled past midnight
            day += 1
        prev_raw = t
        abst = day*86400 + t
    else:
        abst = None
    if "link drop" in ln:
        n_reconnect += 1
        if abst is not None: recon_ts.append(abst)
    if "connected pid=" in ln:
        n_connect += 1
    if " LOSS " in ln:
        losses.append(dict(r=gi(r"\br=(\d+)",ln,int), p=gi(r"\bp=(-?[0-9.]+)",ln,float),
            att=gi(r"\batt=(\d+)",ln,int), spd=gi(r"\bspd=(-?[0-9.]+)",ln,float),
            dist=gi(r"\bdist=(-?\d+)m",ln,int),
            src=(re.search(r"src=(\w+)",ln).group(1) if re.search(r"src=(\w+)",ln) else "?")))
    elif re.search(r"run \d+s \|", ln):
        summaries.append(dict(abst=abst, run=gi(r"run (\d+)s",ln,int,0), caught=gi(r"caught=(\d+)",ln,int,0),
            flee=gi(r"flee=(\d+)",ln,int,0), esc=gi(r"esc=(\d+)",ln,int,0),
            spd=gi(r"spd=(-?[0-9.]+)km/h",ln,float), stale=gi(r"stale=(\d+)",ln,int)))

# ---- RUNS (split on run-counter reset) ----
runs = []; cur = []
prev = -1
for s in summaries:
    if (s["run"] or 0) < prev: runs.append(cur); cur = []
    cur.append(s); prev = s["run"] or 0
if cur: runs.append(cur)
run_durs = [r[-1]["run"] or 0 for r in runs if r]
run_caught = [max((x["caught"] or 0) for x in r) for r in runs if r]
short = sum(1 for d in run_durs if d < 120)
tot_caught = sum(run_caught)
tot_flee = sum(max((x["flee"] or 0) for x in r) for r in runs if r)
tot_stale = sum(max((x["stale"] or 0) for x in r if x["stale"] is not None) if any(x["stale"] is not None for x in r) else 0 for r in runs if r)

# ---- runtime span ----
span_h = (summaries[-1]["abst"] - summaries[0]["abst"])/3600.0 if len(summaries)>1 and summaries[0]["abst"] and summaries[-1]["abst"] else 0

# ---- reconnect storms: reconnects per 5-min window ----
storm = collections.Counter()
for t in recon_ts:
    storm[t//300] += 1
worst = storm.most_common(5)

# ---- SPEED -> flee rate, volume-controlled via per-interval deltas within a run ----
def bk(spd):
    if spd is None: return None
    if spd <= 0.5: return "0 still"
    if spd <= 10: return "1-10"
    if spd <= 30: return "10-30"
    return "30+"
bucket_caught = collections.Counter(); bucket_flee = collections.Counter()
for r in runs:
    for a, b in zip(r, r[1:]):
        dc = (b["caught"] or 0) - (a["caught"] or 0)
        df = (b["flee"] or 0) - (a["flee"] or 0)
        if dc < 0 or df < 0: continue
        k = bk(b["spd"])
        if k is None: continue
        bucket_caught[k] += dc; bucket_flee[k] += df

# ---- loss classification (instrumented LOSS lines) ----
flees = [d for d in losses if d["r"] == 3]
stale_flee = sum(1 for d in flees if d["dist"] is not None and d["dist"] < 0)
inrange_flee = sum(1 for d in flees if d["dist"] is not None and d["dist"] >= 0)
hiP = sum(1 for d in flees if (d["p"] or -1) > 0.6 and d["att"] == 1)
pb = collections.Counter()
for d in flees:
    p = d["p"]
    pb["unknown" if p is None or p < 0 else "<0.3" if p<0.3 else "0.3-0.5" if p<0.5 else "0.5-0.7" if p<0.7 else ">=0.7"] += 1
src = collections.Counter(d["src"] for d in losses)

print("=== SCALE / THROUGHPUT ===")
print(f"runtime span ~{span_h:.1f}h | summaries={len(summaries)} | runs={len(runs)} | caught={tot_caught} flee={tot_flee} | catch%={100*tot_caught/(tot_caught+tot_flee):.1f}")
print(f"throughput ~{tot_caught/span_h:.0f} catches/h" if span_h else "")
print(f"stale-skips total ~{tot_stale}")
print()
print("=== STABILITY (the big one) ===")
print(f"reconnects (link drop/script destroyed) = {n_reconnect}  -> ~{n_reconnect/span_h:.0f}/h, ~1 per {span_h*3600/n_reconnect:.0f}s avg" if span_h and n_reconnect else f"reconnects={n_reconnect}")
print(f"process (re)connects 'connected pid=' = {n_connect} | run-counter resets = {len(runs)-1}")
print(f"runs shorter than 120s = {short}/{len(runs)}  (churn indicator)")
print(f"run-duration buckets: <60s={sum(1 for d in run_durs if d<60)} 60-300s={sum(1 for d in run_durs if 60<=d<300)} 300-1800s={sum(1 for d in run_durs if 300<=d<1800)} >1800s={sum(1 for d in run_durs if d>=1800)}")
print(f"worst 5-min reconnect storms (window->count): {[c for _,c in worst]}")
print()
print("=== SPEED -> FLEE RATE (volume-controlled, deltas) ===")
for k in ["0 still","1-10","10-30","30+"]:
    c, f = bucket_caught.get(k,0), bucket_flee.get(k,0)
    print(f"  {k:7s}: caught={c:5d} flee={f:4d} flee%={100*f/(c+f):.1f}" if (c+f) else f"  {k:7s}: (no data)")
print()
print("=== LOSS CLASSIFICATION (instrumented LOSS lines) ===")
print(f"flee events={len(flees)} | stale(dist=-1)={stale_flee} | in-range={inrange_flee} | hi-prob(>0.6,att1)={hiP}")
print(f"prob bands: {dict(pb)}")
print(f"loss by source: {dict(src)}")
