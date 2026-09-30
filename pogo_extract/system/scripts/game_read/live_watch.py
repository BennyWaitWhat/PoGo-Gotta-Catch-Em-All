"""TRACK-1 live watch: sample the on-phone catcher log every ~12s for 3 min, compute
per-interval deltas + rates, flag anomalies / errors / reconnects. Read-only (no Frida,
no gadget contention) — just tails the log over adb."""
import subprocess, time, re

LOG = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod/catch_loop.log"
DEV = "100.98.158.56:5555"
DUR = 180

def tail(n=6):
    try:
        r = subprocess.run(["adb", "-s", DEV, "shell", f"su -c 'tail -n {n} {LOG}'"],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.splitlines()
    except Exception as e:
        return [f"<tail error: {e}>"]

FIELDS = [("run", r"run (\d+)s"), ("dust", r"now (\d+) dust"), ("gain", r"\+(\d+) this run"),
          ("rate", r"\((\d+)/min\)"), ("fired", r"fired=(\d+)"), ("caught", r"caught=(\d+)"),
          ("esc", r"esc=(\d+)"), ("flee", r"flee=(\d+)"), ("miss", r"miss=(\d+)"),
          ("skip", r"skipPhantom=(\d+)"), ("q", r"q=(\d+)"), ("vis", r"vis=(\d+)"),
          ("inr", r"inr=(\d+)"), ("P", r"P=(\d+)"), ("G", r"G=(\d+)"), ("U", r"U=(\d+)"), ("pc", r"pc=(\d+)")]

def parse(line):
    d = {}
    for k, p in FIELDS:
        m = re.search(p, line)
        if m:
            d[k] = int(m.group(1))
    m = re.search(r"skipPhantom=\d+ (\{[^}]*\})", line)
    if m:
        d["skipd"] = m.group(1)
    m = re.search(r"tally=(\{[^}]*\})", line)
    if m:
        d["tally"] = m.group(1)
    return d

print("=== TRACK-1 LIVE WATCH (3 min) ===", flush=True)
t0 = time.time()
prev = None
seen = set()
while time.time() - t0 < DUR:
    lines = tail(6)
    for ln in lines:
        s = ln.strip()
        if any(x in s for x in ("link drop", "waiting for PoGo", "connected pid", "stopped (all balls", "Traceback", "reconnect")):
            if s not in seen:
                seen.add(s)
                print(f"  [EVENT @ +{int(time.time()-t0)}s] {s}", flush=True)
    summ = [ln for ln in lines if ("run " in ln and "caught=" in ln)]
    cur = parse(summ[-1]) if summ else None
    if cur and prev:
        dC = cur.get('caught', 0) - prev.get('caught', 0)
        dFL = cur.get('flee', 0) - prev.get('flee', 0)
        dSK = cur.get('skip', 0) - prev.get('skip', 0)
        dF = cur.get('fired', 0) - prev.get('fired', 0)
        dD = cur.get('dust', 0) - prev.get('dust', 0)
        dP = cur.get('P', 0) - prev.get('P', 0)
        fl = ""
        if dFL > 0:
            fl += f"  !!FLEE+{dFL}"
        if cur.get('q', 0) > 5:
            fl += f"  !Q={cur['q']}"
        if dF == 0 and cur.get('q', 0) > 0:
            fl += "  !STALL(q>0,no-throw)"
        if cur.get('P', 999) < 10:
            fl += "  !BALLS_LOW"
        print(f"  +{int(time.time()-t0):>3}s | dCaught={dC} dFlee={dFL} dSkip={dSK} dFired={dF} | dDust={dD} dPoke={dP} | q={cur.get('q')} vis={cur.get('vis')} pc={cur.get('pc')} skip={cur.get('skipd')} tally={cur.get('tally')}{fl}", flush=True)
    elif cur:
        print(f"  baseline | caught={cur.get('caught')} flee={cur.get('flee')} skip={cur.get('skip')} dust={cur.get('dust')} P={cur.get('P')} q={cur.get('q')}", flush=True)
    if cur:
        prev = cur
    time.sleep(12)

print("=== END ===", flush=True)
if prev:
    print(f"FINAL | caught={prev.get('caught')} flee={prev.get('flee')} skipPhantom={prev.get('skip')} {prev.get('skipd')} dust={prev.get('dust')} balls(P/G/U)={prev.get('P')}/{prev.get('G')}/{prev.get('U')}", flush=True)
print(f"distinct events: {len(seen)}", flush=True)
