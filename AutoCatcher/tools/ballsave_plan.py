"""Build the BALL-SAVER plan for catch_loop_fast.py (Benny 2026-11-16 meteor shower: "i need max stardust between now and
until the meteor shower is over"; spins refused, so the balls on hand are all there are). Read-only: writes a local JSON.
tools/ballsave_go.py is the usual caller (it pulls the phone's data, joins each catch's stardust, pushes the plan).

usage: python tools/ballsave_plan.py --ledger L.jsonl [--log catch_loop.log] --start EPOCH --end EPOCH --out plan.json
                                     [--keep N] [--margin 1.0] [--gamemaster GM.json] [--since EPOCH] [--recent MIN]
       python tools/ballsave_plan.py --selftest
  ledger   spawn_ledger.jsonl records (a tail is fine); records with t0 >= --start count. A record's "d" is its catch's
           stardust (catchers from 11-17 write it; ballsave_go.py joins older ones from the log)
  log      only when no caught record carries "d": every CATCH line in it is used (the caller cuts the window)
  keep     balls to keep IN ALL (Benny 11-16 20:48: "keep going until you have 50 balls left") -- the catcher's own
           5 Poke / 5 Great / 5 Ultra floors count toward it (catch_loop_fast.plan_reserve)
  margin   multiplies every species' balls per minute. 1.0 = the target itself. 11-16: a feedback margin chased noise
           (1.19 -> 0.75 in 20 min) and a 400-run simulation found a fixed 1.0 as good, so there is no feedback
  gamemaster  pogo_extract/gamemaster_pokeminers.json: the award of a species never caught comes from its
           encounter.bonusStardustCaptureReward, (25 + 2 x (100 + bonus)) x 1.5
  since    when the ball-saver went live (a RE-plan): a species left alone since then has no throws, so its balls per
           minute come from the minutes BEFORE it; a species still thrown at uses the whole window
  recent   balls per minute from only the last N throwing minutes (a left-alone species: the last N before --since).
           11-16: the shower faded, whole-evening rates held ~20% too many balls back
STAR PIECE BASIS: an award without a Star Piece is a multiple of 25 (225, 2025 ...); it counts x1.5, so a lapse
(11-16 18:47-19:09) does not rank its species lower. The cut is in Star Piece stardust; the order never changes.
Per species: stardust per ball = (catches + 2 x c0) x average award / (balls thrown + 2 x b0), c0 / b0 = catches /
balls per spawn over ALL species (two average spawns of prior: a species seen once is neither perfect nor worthless).
Activate = /data/local/tmp/pogo_ballsave.json on the phone; delete it = catch everything again."""
import argparse
import collections
import json
import re
import sys
import time

CATCH = re.compile(r" CATCH \S+ #(\d+) .*?dust=(\d+)")
FLOORS = 15   # catch_loop_fast CFG floors: 5 Poke + 5 Great + 5 Ultra, always kept


def sp_basis(v):
    """An award on the Star Piece basis: a bare one (a multiple of 25) x 1.5."""
    v = int(v)
    return v * 1.5 if v % 25 == 0 else float(v)


def gm_bonus(path):
    out = {}
    for e in json.load(open(path, encoding="utf-8")):
        m = re.match(r"V(\d{4})_POKEMON_", e.get("templateId", ""))
        st = (e.get("data") or {}).get("pokemonSettings")
        if m and st:
            b = int((st.get("encounter") or {}).get("bonusStardustCaptureReward") or 0)
            out[int(m.group(1))] = max(out.get(int(m.group(1)), 0), b)
    return out


def last_words(records, start):
    """One record per spawn (its last word), t0 >= start (epoch s)."""
    last = {}
    for r in records:
        if r.get("k", "spawn") != "spawn" or not r.get("t0") or r["t0"] < start * 1000 or r.get("id") is None:
            continue
        old = last.get(r["e"])
        if old is None or (r.get("t1") or 0) >= (old.get("t1") or 0):
            last[r["e"]] = r
    return last


def build(records, start, end, keep=None, margin=1.0, bonus=None, since=None, recent=None, log_lines=None, made=None):
    """records: ledger dicts. Returns (plan dict, summary dict)."""
    bonus = bonus or {}
    since_ms = since * 1000 if since else None
    seen, balls, caught = collections.Counter(), collections.Counter(), collections.Counter()
    balls_before, balls_after = collections.Counter(), collections.Counter()
    dust = collections.defaultdict(list)
    active, active_before = set(), set()
    per_min = collections.defaultdict(collections.Counter)    # throwing minute -> balls per species
    tried = 0                                                  # spawns the catcher tried for: the prior's "average spawn"
    last = last_words(records, start)
    with_d = any(r.get("r") == "caught" and int(r.get("d") or 0) > 0 for r in last.values())   # all 0 = the award was not read
    for r in last.values():
        d, n = int(r["id"]), int(r.get("n") or 0)
        if r.get("sh"):   # a shiny gets balls whatever the plan says (SHINY LOOK): not the species' rate or its odds
            seen.setdefault(d, 0)
            continue
        seen[d] += 1
        tried += r.get("r") != "ballsave"   # left alone (since 11-17 every one has a record): no catch, no ball, no odds
        balls[d] += n
        caught[d] += r.get("r") == "caught"
        if with_d and r.get("r") == "caught" and r.get("d") is not None and int(r["d"]) > 0:
            dust[d].append(sp_basis(r["d"]))
        before = since_ms is None or r["t0"] < since_ms
        (balls_before if before else balls_after)[d] += n
        if n:
            mm = r["t0"] // 60000
            active.add(mm)
            per_min[mm][d] += n
            if before:
                active_before.add(mm)
    if not with_d:
        for ln in log_lines or []:
            m = CATCH.search(ln)
            if m and int(m.group(2)) > 0:
                dust[int(m.group(1))].append(sp_basis(m.group(2)))
    mins, mins_before = max(1, len(active)), max(1, len(active_before))
    rec_all, rec_before = sorted(active)[-recent:] if recent else [], sorted(active_before)[-recent:] if recent else []
    rb_all, rb_before = collections.Counter(), collections.Counter()
    for mm in rec_all:
        rb_all.update(per_min[mm])
    for mm in rec_before:
        rb_before.update(per_min[mm])
    n_balls, n_caught = sum(balls.values()), sum(caught.values())
    c0, b0 = n_caught / max(1, tried), n_balls / max(1, tried)          # per spawn tried for, all species
    species = {}
    for d in seen:
        avg = sum(dust[d]) / len(dust[d]) if dust[d] else (25 + 2 * (100 + bonus.get(d, 0))) * 1.5
        kept = since_ms is None or balls_after[d]
        if recent:
            rate = rb_all[d] / max(1, len(rec_all)) if kept else rb_before[d] / max(1, len(rec_before))
        else:
            rate = balls[d] / mins if kept else balls_before[d] / mins_before
        den = balls[d] + 2 * b0   # 0 only when no ball was thrown at all: rank by the award
        species[str(d)] = [round((caught[d] + 2 * c0) * avg / den if den > 0 else avg, 1), round(rate, 4)]
    plan = {"end": end, "margin": margin, "made": made or time.strftime("%Y-%m-%d %H:%M:%S"), "minutes": mins,
            "basis": "star piece", "species": dict(sorted(species.items(), key=lambda kv: -kv[1][0]))}
    if keep is not None:
        plan["keep"] = int(keep)
        plan["reserve"] = max(0, int(keep) - FLOORS)   # a catcher from before 11-17 reads only this (on top of its floors)
    summary = {"species": len(species), "minutes": mins, "minutes_before": mins_before, "need": sum(v[1] for v in species.values()),
               "seen": seen, "caught": caught, "balls": balls, "dust_from": "ledger" if with_d else "log"}
    return plan, summary


def _selftest():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name.ljust(46), repr(got), "" if ok else f"  want {want!r}")

    S = 1_800_000_000
    rec = []
    for i in range(10):   # Minior: 10 spawns, 8 caught with 10 balls, 3037 each (two bare 2025 = a Star Piece lapse)
        rec.append({"k": "spawn", "e": f"m{i}", "id": 774, "t0": (S + 60 * i) * 1000, "t1": (S + 60 * i + 5) * 1000,
                    "n": 1 if i < 8 else 1, "r": "caught" if i < 8 else "fled", "d": (2025 if i in (0, 1) else 3037) if i < 8 else None})
    for i in range(10):   # an ordinary one: 10 spawns, 10 caught, 15 balls, 337 each
        rec.append({"k": "spawn", "e": f"o{i}", "id": 10, "t0": (S + 60 * i) * 1000, "t1": (S + 60 * i + 5) * 1000,
                    "n": 2 if i < 5 else 1, "r": "caught", "d": 337})
    rec.append({"k": "spawn", "e": "o0", "id": 10, "t0": S * 1000, "t1": (S + 1) * 1000, "n": 0, "r": "gone"})   # an older word
    rec.append({"k": "spawn", "e": "x", "id": 999, "t0": (S - 99) * 1000, "t1": S * 1000, "n": 3, "r": "caught", "d": 337})  # before start
    plan, sm = build(rec, S, S + 3600, keep=50, bonus={316: 300})
    check("species (before --start dropped)", sorted(plan["species"]), ["10", "774"])
    check("a bare award counts x1.5 (Star Piece basis)", sp_basis(2025), 3037.5)
    check("dust from the ledger's d", sm["dust_from"], "ledger")
    c0, b0 = 18 / 20, 25 / 20
    want = round((8 + 2 * c0) * 3037.125 / (10 + 2 * b0), 1)
    check("Minior stardust per ball", plan["species"]["774"][0], want)
    check("balls per minute = balls / throwing minutes", plan["species"]["10"][1], round(15 / 10, 4))
    check("keep written for the catcher", (plan["keep"], plan["margin"], plan["basis"]), (50, 1.0, "star piece"))
    check("best first", list(plan["species"])[0], "774")
    rec2 = [dict(r, d=None) for r in rec]
    plan2, sm2 = build(rec2, S, S + 3600, log_lines=["20:00:00 CATCH Wild #774 ball=1 p=0.2 dust=3037", "20:00:01 CATCH Wild #10 ball=1 dust=225"])
    check("no d anywhere: the log's CATCH lines", (sm2["dust_from"], round(plan2["species"]["10"][0])),
          ("log", round((10 + 2 * c0) * 337.5 / (15 + 2 * b0))))
    plan3, _ = build(rec + [{"k": "spawn", "e": "n1", "id": 316, "t0": S * 1000, "t1": S * 1000 + 1, "n": 1, "r": "fled"}], S, S + 3600,
                     bonus={316: 300})
    check("never caught: the game master's bonus", plan3["species"]["316"][0],
          round((0 + 2 * (18 / 21)) * ((25 + 2 * 400) * 1.5) / (1 + 2 * (26 / 21)), 1))
    plan4, sm4 = build(rec, S, S + 3600, since=S + 300)   # the saver went live at minute 5: #10 still thrown at after it
    check("since: a kept species uses the whole window", plan4["species"]["10"][1], round(15 / 10, 4))
    rec5 = [r for r in rec if not (r["id"] == 10 and r["t0"] >= (S + 300) * 1000)]   # #10 left alone from minute 5
    plan5, _ = build(rec5, S, S + 3600, since=S + 300)
    check("since: a left-alone species, minutes before", plan5["species"]["10"][1], round(10 / 5, 4))
    plan6, _ = build(rec, S, S + 3600, recent=3)
    check("recent 3 throwing minutes", plan6["species"]["10"][1], round(3 / 3, 4))
    check("reserve for a catcher from before 11-17", plan["reserve"], 50 - 15)
    rec7 = rec + [{"k": "spawn", "e": "s1", "id": 10, "t0": (S + 30) * 1000, "t1": (S + 40) * 1000, "n": 10, "r": "caught", "d": 337, "sh": 1}]
    rec7 += [{"k": "spawn", "e": f"b{i}", "id": 10, "t0": (S + 60 * i + 7) * 1000, "t1": (S + 60 * i + 7) * 1000, "n": 0, "r": "ballsave"}
             for i in range(10)]
    plan7, _ = build(rec7, S, S + 3600, bonus={316: 300})
    check("a shiny's balls + left-alone spawns change nothing", plan7["species"], plan["species"])
    rec8 = [{"k": "spawn", "e": f"z{i}", "id": 20 + i, "t0": (S + i) * 1000, "t1": (S + i + 1) * 1000, "n": 0, "r": "fled"} for i in range(3)]
    plan8, _ = build(rec8, S, S + 3600, bonus={21: 900})
    check("no ball thrown at all: ranked by the award", list(plan8["species"].items())[0], ("21", [3037.5, 0.0]))
    _, sm9 = build([dict(r, d=0 if r.get("d") is not None else None) for r in rec], S, S + 3600)
    check("every d is 0 (award unread): not 'from the ledger'", sm9["dust_from"], "log")
    return failed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger")
    ap.add_argument("--log")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--out")
    ap.add_argument("--keep", type=int)
    ap.add_argument("--margin", type=float, default=1.0)
    ap.add_argument("--gamemaster")
    ap.add_argument("--since", type=float)
    ap.add_argument("--recent", type=int)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(1 if _selftest() else 0)
    if not (a.ledger and a.start and a.end and a.out):
        ap.error("--ledger, --start, --end and --out are needed")
    recs = []
    for ln in open(a.ledger, encoding="utf-8", errors="replace"):
        try:
            recs.append(json.loads(ln))
        except ValueError:
            continue
    log_lines = open(a.log, encoding="utf-8", errors="replace").read().splitlines() if a.log else None
    plan, sm = build(recs, a.start, a.end, a.keep, a.margin, gm_bonus(a.gamemaster) if a.gamemaster else None, a.since, a.recent, log_lines)
    json.dump(plan, open(a.out, "w", encoding="utf-8"), indent=0)
    print(f"{sm['species']} species over {sm['minutes']} throwing minutes" + (f" ({sm['minutes_before']} before the saver)" if a.since else "")
          + (f", rates from the last {a.recent}" if a.recent else "") + f", stardust from the {sm['dust_from']}"
          + f" | all of them use {sm['need']:.1f} balls/min | wrote {a.out}")
    for d, (dpb, rate) in list(plan["species"].items())[:12]:
        dd = int(d)
        print(f"  #{d:>4} {dpb:7.0f} stardust/ball  {rate:5.2f} balls/min  seen {sm['seen'][dd]:4d} caught {sm['caught'][dd]:4d} balls {sm['balls'][dd]:4d}")


if __name__ == "__main__":
    main()
