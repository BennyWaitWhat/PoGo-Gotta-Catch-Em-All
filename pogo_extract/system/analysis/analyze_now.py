"""Optimization scan of the CURRENT catcher log. Focus on things we can actually act on:
range vs loss (is MAXR=90 too generous?), spin success/failure mix, stale-skip rate,
reconnect churn, ball economy, and per-source yield. Only looks at the post-0.421.0 window
(the app updated 2026-07-26 00:12 and renamed obfuscated symbols)."""
import re, collections

LOG = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\system\analysis\pokemod\catch_loop.NOW.log"
lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()

def g(pat, s, cast=float, d=None):
    m = re.search(pat, s)
    return cast(m.group(1)) if m else d

# ---- only the tail of the file matters (recent behaviour); keep the last N lines ----
TAIL = 120000
lines = lines[-TAIL:]

losses, summaries = [], []
spin_ok = collections.Counter()
spin_fail = collections.Counter()
awards = []
reconnects = 0
backoffs = []
syntax_err = 0
for ln in lines:
    if " LOSS " in ln:
        losses.append(dict(
            r=g(r"\br=(\d+)", ln, int), p=g(r"\bp=(-?[0-9.]+)", ln, float),
            ball=g(r"\bball=(\d+)", ln, int), pid=g(r"\bpid=(\d+)", ln, int),
            dist=g(r"\bdist=(-?\d+)m", ln, int), spd=g(r"\bspd=(-?[0-9.]+)", ln, float),
            src=(re.search(r"\bsrc=(\w+)", ln).group(1) if re.search(r"\bsrc=(\w+)", ln) else "?")))
    elif "AWARD" in ln:
        awards.append(dict(res=g(r"res=(\d+)", ln, int), xp=g(r"xp=(\d+)", ln, int),
                           items=g(r"items=(\d+)", ln, int)))
        spin_ok[g(r"res=(\d+)", ln, int)] += 1
    elif "spinFail" in ln:
        m = re.search(r"-> (\S+)", ln)
        spin_fail[m.group(1) if m else "?"] += 1
    elif re.search(r"run \d+s \|", ln):
        summaries.append(dict(
            run=g(r"run (\d+)s", ln, int, 0), caught=g(r"caught=(\d+)", ln, int, 0),
            flee=g(r"flee=(\d+)", ln, int, 0), esc=g(r"esc=(\d+)", ln, int, 0),
            stale=g(r"stale=(\d+)", ln, int, 0), spd=g(r"spd=(-?[0-9.]+)km/h", ln, float),
            P=g(r"\bP=(\d+)", ln, int), G=g(r"\bG=(\d+)", ln, int), U=g(r"\bU=(\d+)", ln, int),
            inrange=g(r"'inRange': (\d+)", ln, int), spinnable=g(r"'spinnable': (\d+)", ln, int),
            cooling=g(r"'cooling': (\d+)", ln, int)))
    if "link drop" in ln:
        reconnects += 1
        b = g(r"reconnecting in (\d+)s", ln, int)
        if b: backoffs.append(b)
    if "SyntaxError" in ln:
        syntax_err += 1

# ---- per-run segments (counters reset on restart) ----
runs, cur, prev = [], [], -1
for s in summaries:
    if (s["run"] or 0) < prev: runs.append(cur); cur = []
    cur.append(s); prev = s["run"] or 0
if cur: runs.append(cur)
tot_caught = sum(max((x["caught"] or 0) for x in r) for r in runs if r)
tot_flee = sum(max((x["flee"] or 0) for x in r) for r in runs if r)
tot_stale = sum(max((x["stale"] or 0) for x in r) for r in runs if r)

print("=== SCALE ===")
print(f"summaries={len(summaries)} runs={len(runs)} caught={tot_caught} flee={tot_flee} stale-skips={tot_stale}")
if tot_caught + tot_flee:
    print(f"catch rate = {100*tot_caught/(tot_caught+tot_flee):.1f}%")

# ---- RANGE: does loss probability rise with distance? (actionable: lower MAXR) ----
print("\n=== RANGE vs OUTCOME (loss events by throw distance) ===")
band = lambda d: "unknown" if d is None or d < 0 else ("0-30" if d <= 30 else "31-50" if d <= 50 else
        "51-70" if d <= 70 else "71-80" if d <= 80 else "81-90" if d <= 90 else ">90")
lb = collections.Counter(band(l["dist"]) for l in losses if l["r"] == 3)
for k in ["0-30", "31-50", "51-70", "71-80", "81-90", ">90", "unknown"]:
    if lb.get(k): print(f"  {k:8s} flees={lb[k]}")
far = sum(v for k, v in lb.items() if k in ("71-80", "81-90", ">90"))
near = sum(v for k, v in lb.items() if k in ("0-30", "31-50", "51-70"))
print(f"  -> flees at >70m: {far}   flees at <=70m: {near}")

# ---- SPIN health ----
print("\n=== SPIN ===")
print(f"  award responses by result code: {dict(spin_ok)}   (1=SUCCESS 2=OUT_OF_RANGE 3=COOLDOWN 4=INV_FULL 5=DAILY_LIMIT)")
print(f"  spinFail reasons: {dict(spin_fail) if spin_fail else 'none'}")
succ = [a for a in awards if a["res"] == 1]
zero = [a for a in succ if (a["xp"] or 0) == 0]
print(f"  successful spins={len(succ)}  of which ZERO-reward={len(zero)} ({100*len(zero)/len(succ):.0f}%)" if succ else "  no spins")
if succ:
    print(f"  total XP={sum(a['xp'] or 0 for a in succ)}  total items={sum(a['items'] or 0 for a in succ)}")

# ---- stop availability: are we leaving spins on the table? ----
sp = [s["spinnable"] for s in summaries if s["spinnable"] is not None]
cl = [s["cooling"] for s in summaries if s["cooling"] is not None]
if sp:
    print(f"\n=== STOP SUPPLY ===\n  spinnable now: avg={sum(sp)/len(sp):.1f} max={max(sp)}  |  cooling avg={sum(cl)/len(cl):.1f}")
    starved = sum(1 for x in sp if x == 0)
    print(f"  samples with ZERO spinnable: {starved}/{len(sp)} ({100*starved/len(sp):.0f}%)  <- if low, a faster spin interval pays off")

# ---- ball economy ----
last = summaries[-1] if summaries else {}
print(f"\n=== BALLS === P={last.get('P')} G={last.get('G')} U={last.get('U')}")
ballmix = collections.Counter(l["ball"] for l in losses if l["ball"])
print(f"  balls used on LOST throws: {dict(ballmix)} (1=Poke 2=Great 3=Ultra)")

# ---- churn ----
print(f"\n=== CHURN === reconnects={reconnects} backoff values seen={sorted(set(backoffs)) if backoffs else 'n/a'} syntaxErrors={syntax_err}")

# ---- speed ----
bc, bf = collections.Counter(), collections.Counter()
for r in runs:
    for a, b in zip(r, r[1:]):
        dc = (b["caught"] or 0) - (a["caught"] or 0); df = (b["flee"] or 0) - (a["flee"] or 0)
        if dc < 0 or df < 0: continue
        s = b["spd"]
        k = "still" if s is None or s <= 0.5 else "1-10" if s <= 10 else "10-30" if s <= 30 else "30+"
        bc[k] += dc; bf[k] += df
print("\n=== SPEED vs LOSS (volume-controlled) ===")
for k in ["still", "1-10", "10-30", "30+"]:
    c, f = bc.get(k, 0), bf.get(k, 0)
    if c + f: print(f"  {k:6s} caught={c:5d} fled={f:4d}  loss={100*f/(c+f):.1f}%")

# ---- per-source ----
print("\n=== LOSSES BY SOURCE ===")
for s, n in collections.Counter(l["src"] for l in losses).most_common():
    print(f"  {s:28s} {n}")
