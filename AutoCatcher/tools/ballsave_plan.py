"""Build the BALL-SAVER plan for catch_loop_fast.py (Benny 2026-11-16 meteor shower: "i need max stardust between now and
until the meteor shower is over"; spins refused, so the balls on hand are all there are). Read-only: writes a local JSON.

usage: python tools/ballsave_plan.py <spawn_ledger.jsonl> <catch log lines> <start epoch s> <end epoch s> <out.json> [margin]
  ledger   the phone's ~/pogo/system/analysis/pokemod/spawn_ledger.jsonl (a tail is fine); records from <start> on count
  log      catch_loop.log lines of the same window (the caller cuts them: every CATCH line in the file is used)
Per species: stardust per ball = catches x average award / (balls thrown + 1) (the +1 keeps a one-throw species from
looking perfect), balls per minute = balls thrown / minutes the catcher was throwing. The catcher then keeps the best
stardust per ball while the balls on hand cover them until <end> (ballsave_skip in catch_loop_fast.py).
Activate = put the file at /data/local/tmp/pogo_ballsave.json on the phone; delete it = catch everything again."""
import collections
import json
import re
import sys
import time

LED, LOG, START, END, OUT = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
MARGIN = float(sys.argv[6]) if len(sys.argv) > 6 else 1.15

seen, balls, caught = collections.Counter(), collections.Counter(), collections.Counter()
last = {}
for ln in open(LED, encoding="utf-8", errors="replace"):
    try:
        r = json.loads(ln)
    except ValueError:
        continue
    if r.get("k") != "spawn" or not r.get("t0") or r["t0"] < START * 1000 or r.get("id") is None:
        continue
    old = last.get(r["e"])
    if old is None or (r.get("t1") or 0) >= (old.get("t1") or 0):
        last[r["e"]] = r                      # one record per spawn: its last word
active = set()
for r in last.values():
    d, n = int(r["id"]), int(r.get("n") or 0)
    seen[d] += 1
    balls[d] += n
    caught[d] += r.get("r") == "caught"
    if n:
        active.add(r["t0"] // 60000)
dust = collections.defaultdict(list)
for ln in open(LOG, encoding="utf-8", errors="replace"):
    m = re.search(r" CATCH \S+ #(\d+) .*?dust=(\d+)", ln)
    if m:
        dust[int(m.group(1))].append(int(m.group(2)))
mins = max(1, len(active))
species = {}
for d in seen:
    avg = sum(dust[d]) / len(dust[d]) if dust[d] else 0.0
    species[str(d)] = [round(caught[d] * avg / (balls[d] + 1), 1), round(balls[d] / mins, 4)]
plan = {"end": END, "margin": MARGIN, "made": time.strftime("%Y-%m-%d %H:%M:%S"), "minutes": mins,
        "species": dict(sorted(species.items(), key=lambda kv: -kv[1][0]))}
json.dump(plan, open(OUT, "w", encoding="utf-8"), indent=0)
need = sum(v[1] for v in species.values())
print(f"{len(species)} species over {mins} throwing minutes | all of them use {need:.1f} balls/min | wrote {OUT}")
for d, (dpb, rate) in list(plan["species"].items())[:12]:
    print(f"  #{d:>4} {dpb:7.0f} stardust/ball  {rate:5.2f} balls/min  seen {seen[int(d)]:4d} caught {caught[int(d)]:4d} balls {balls[int(d)]:4d}")
