"""Build the BALL-SAVER plan for catch_loop_fast.py (Benny 2026-11-16 meteor shower: "i need max stardust between now and
until the meteor shower is over"; spins refused, so the balls on hand are all there are). Read-only: writes a local JSON.

usage: python tools/ballsave_plan.py <spawn_ledger.jsonl> <catch log lines> <start epoch s> <end epoch s> <out.json> [margin] [gamemaster.json]
  ledger   the phone's ~/pogo/system/analysis/pokemod/spawn_ledger.jsonl (a tail is fine); records from <start> on count
  log      catch_loop.log lines of the same window (the caller cuts them: every CATCH line in the file is used)
  gamemaster  pogo_extract/gamemaster_pokeminers.json: the award of a species never caught in the window comes from its
              encounter.bonusStardustCaptureReward, (25 + 2 x (100 + bonus)) x the window's Star Piece factor
Per species: stardust per ball = (catches + 2 x c0) x average award / (balls thrown + 2 x b0), where c0 / b0 = catches /
balls per spawn over ALL species: two average spawns of prior, so a species seen once is neither perfect nor worthless
(11-16: Exeggutor and Blissey, bonus 200, fled once each and scored 0 without it). Balls per minute = balls thrown /
minutes the catcher was throwing. The catcher then keeps the best stardust per ball while the balls on hand cover them
until <end> (ballsave_skip in catch_loop_fast.py).
Activate = put the file at /data/local/tmp/pogo_ballsave.json on the phone; delete it = catch everything again."""
import collections
import json
import re
import sys
import time

LED, LOG, START, END, OUT = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
MARGIN = float(sys.argv[6]) if len(sys.argv) > 6 else 1.15
BONUS = {}
if len(sys.argv) > 7:
    for e in json.load(open(sys.argv[7], encoding="utf-8")):
        m = re.match(r"V(\d{4})_POKEMON_", e.get("templateId", ""))
        st = (e.get("data") or {}).get("pokemonSettings")
        if m and st:
            b = int((st.get("encounter") or {}).get("bonusStardustCaptureReward") or 0)
            BONUS[int(m.group(1))] = max(BONUS.get(int(m.group(1)), 0), b)

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
n_seen, n_balls, n_caught = sum(seen.values()), sum(balls.values()), sum(caught.values())
c0, b0 = n_caught / max(1, n_seen), n_balls / max(1, n_seen)          # per spawn, all species
plain = [v for vs in dust.values() for v in vs if v < 600]               # ordinary awards: 225/275 bare, 337/412 Star Piece
sp = 1.5 if plain and sorted(plain)[len(plain) // 2] > 300 else 1.0      # the window's Star Piece factor
species = {}
for d in seen:
    avg = sum(dust[d]) / len(dust[d]) if dust[d] else (25 + 2 * (100 + BONUS.get(d, 0))) * sp
    species[str(d)] = [round((caught[d] + 2 * c0) * avg / (balls[d] + 2 * b0), 1), round(balls[d] / mins, 4)]
plan = {"end": END, "margin": MARGIN, "made": time.strftime("%Y-%m-%d %H:%M:%S"), "minutes": mins,
        "species": dict(sorted(species.items(), key=lambda kv: -kv[1][0]))}
json.dump(plan, open(OUT, "w", encoding="utf-8"), indent=0)
need = sum(v[1] for v in species.values())
print(f"{len(species)} species over {mins} throwing minutes | all of them use {need:.1f} balls/min | wrote {OUT}")
for d, (dpb, rate) in list(plan["species"].items())[:12]:
    print(f"  #{d:>4} {dpb:7.0f} stardust/ball  {rate:5.2f} balls/min  seen {seen[int(d)]:4d} caught {caught[int(d)]:4d} balls {balls[int(d)]:4d}")
