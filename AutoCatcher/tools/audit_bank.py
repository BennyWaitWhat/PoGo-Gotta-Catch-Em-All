"""Self-check of the map bank (system/map/pogo_wigle.db) -- catches stale / drifting fort data automatically.

The scanner (tools/pogo_wigle.py) runs run() every 5 min on its own connection and prints ONE line:
  SELFCHECK ok  | ...counts...
  SELFCHECK FAIL <check>=<n> [offending ids] ... | ...counts...
and writes system/map/selfcheck.json (shown by tools/map_live.py). On demand, read-only:

  python tools/audit_bank.py [--window 10] [--since "YYYY-mm-dd HH:MM:SS"] [--json] [--write-health]

Invariants (FAIL = the bank is lying about "now"; WARN = degraded; INFO = context only):
  heartbeat          moving (track kmh > 0 in the last 60 s) but no map reply for > 120 s
  schema             the gym-state / raw_t columns exist
  gym_state_lag      every gym seen in the window has gym_state_t == last_seen (state written on EVERY sighting)
  raw_vs_live        raw Team / GuardPokemonId == team / guard columns for every fort seen in the window
                     (the bug of 2026-09-25: raw said Valor, 842 CP, 5 open slots; the gym was Mystic and full).
                     A team change in the fort's last <= 30 s of sightings whose re-read the scanner's per-reply cap
                     postponed is "raw_pending" (INFO); longer than that it FAILs.
  same_read          where raw_t == last_seen, raw agrees with every live column written by the same read
  raw_age            forts seen in the window whose full record is > 10 min older than last_seen, or that were in
                     view > 60 s without one (> 5% of the window fails, fewer warns)
  team_event_refresh every team change in the window is followed by a gym-state read (always at that sighting) AND a
                     full-record read (pending as above)
  gym_consistency    team != 0 => guard != 0, gym_cp > 0, slots NOT NULL and 0..5; team == 0 => guard == 0, no CP,
                     slots NULL (no display sent) or 0..6; 0 <= motivation <= 1
  canary             the most recently seen gym: state stamped at that sighting (held => a display was read)
  js_reads           (scanner only) failed full reads <= 1 %, zero unreadable GymDisplay reads
  consumers   WARN   the map_live data file carries its age; no tools/*.py that opens the bank reads a DYNAMIC key
                     (GymDisplay, SlotsAvailable, Team, GuardPokemonId, IsInBattle, ...) -- those live in raw, stale
The window is the last --window minutes before the newest map reply; inside the scanner it is the same rolling
10 min but never before the scanner started, so rows written by older code are judged only as INFO (legacy_raw_stale),
and one past glitch cannot keep FAILing for the rest of the session (every sighting is still judged at least once).
"""
import argparse
import glob
import io
import json
import os
import re
import sqlite3
import sys
import time
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
# keys of PokemonFortProto that change during play: a consumer must take them from the live columns, never from raw
DYNAMIC_RAW = re.compile(r"""["'](GymDisplay|SlotsAvailable|TotalGymCp|LowestPokemonMotivation|OccupiedMillis|IsInBattle|"""
                         r"""Team|GuardPokemonId|ActiveFortModifier|Visited|RaidInfo|PokestopDisplays)["']""")
LINT_SKIP = {"pogo_wigle.py", "audit_bank.py"}      # the writer and this checker compare raw against the columns
DB = os.path.join(ROOT, "system", "map", "pogo_wigle.db")
HEALTH = os.path.join(ROOT, "system", "map", "selfcheck.json")
LIVE_DATA = os.path.join(ROOT, "system", "analysis", "pogo_map_data.js")
FMT = "%Y-%m-%d %H:%M:%S"
GYM_COLS = ("slots", "gym_cp", "motivation", "occupied_ms", "in_battle", "gym_state_t", "raw_t")
WINDOW_S = 600
RAW_MAX_LAG_S = 600
RAW_STALE_SHARE = 0.05
PENDING_S = 30              # a full re-read capped away in one reply lands within a few replies (~6 s each)


def ep(s):
    return time.mktime(time.strptime(s[:19], FMT)) if s else None


def st(e):
    return time.strftime(FMT, time.localtime(e))


def _raw(s):
    try:
        return json.loads(s) if s else None
    except ValueError:
        return None


def _b(v):
    return 1 if v else 0


def run(db, since=None, js=None, now=None, window_s=WINDOW_S, consumers=False, floor=None):
    """All checks; returns {"ok", "line", "fails", "warns", "info", "checked_at"}. Only SELECTs.
    since: judge forts seen at/after this time; default = the window before the newest reply, never before `floor`
    (the scanner passes its start time, so rows written by older code are only INFO)."""
    now = now or time.time()
    fails, warns, info = [], [], {}

    def flag(lst, name, ids, n=None):
        ids = sorted(ids)
        lst.append({"check": name, "n": len(ids) if n is None else n, "ids": ids[:8]})

    ref = db.execute("SELECT MAX(t) FROM replies").fetchone()[0]
    if ref is None:
        return {"ok": True, "line": "SELFCHECK ok | no map replies yet", "fails": [], "warns": [], "info": {},
                "checked_at": st(now)}
    if since is None:
        since = st(ep(ref) - window_s)
    if floor and since < floor:
        since = floor
    age = now - ep(ref)
    info.update(last_reply=ref, last_reply_age_s=round(age), since=since)

    # heartbeat
    moving = db.execute("SELECT COUNT(*) FROM track WHERE t >= ? AND kmh > 0", (st(now - 60),)).fetchone()[0]
    if moving and age > 120:
        flag(fails, f"heartbeat(no reply {round(age)}s while moving)", [])

    cols = {r[1] for r in db.execute("PRAGMA table_info(forts)")}
    missing = [c for c in GYM_COLS if c not in cols]
    if "raw" not in cols:
        missing.append("raw")
    if missing:
        flag(fails, "schema(missing " + ",".join(missing) + ")", [], n=len(missing))
    sel = ", ".join(c if c in cols else f"NULL AS {c}" for c in ("raw",) + GYM_COLS)

    rows = db.execute(f"SELECT id, kind, team, guard, visited, lured, last_seen, {sel}, first_seen FROM forts WHERE last_seen >= ?",
                      (since,)).fetchall()
    # the scanner caps full reads per reply (game safety), so a team change seen in the fort's LAST <= 30 s of sightings
    # may still be waiting for its re-read: "pending" (INFO), not a FAIL. Seen longer than that and still stale = FAIL.
    tlast = dict(db.execute("SELECT fort, MAX(t) FROM fort_events WHERE event='team' AND t >= ? GROUP BY fort", (since,)))

    def pending(fid, last, rawt):
        e = tlast.get(fid)
        return e is not None and (rawt is None or rawt < e) and ep(last) - ep(e) <= PENDING_S

    raw_live, same, lag, cons, rawold, pend = [], [], [], [], [], set()
    ngym = nstop = nraw = nsame = 0
    for (fid, kind, team, guard, vis, lured, last, raw, slots, cp, mot, occ, bat, gst, rawt, first) in rows:
        gym = kind == "gym"
        ngym += gym
        nstop += not gym
        o = _raw(raw)
        if o is not None:
            nraw += 1
            if int(o.get("Team") or 0) != int(team or 0) or int(o.get("GuardPokemonId") or 0) != int(guard or 0):
                (pend.add(fid) if not missing and pending(fid, last, rawt) else raw_live.append(fid))
            if not missing and rawt == last:
                nsame += 1
                gd = o.get("GymDisplay") or {}
                bad = (_b(o.get("Visited")) != _b(vis) or _b(o.get("ActiveFortModifier")) != _b(lured))
                if gym and gst == last:
                    if slots is None:          # stamped "no GymDisplay" (neutral): the full record must have none either
                        bad = bad or bool(gd)
                    else:                      # raw omits proto3 zeros: absent SlotsAvailable / TotalGymCp = 0
                        bad = bad or (int(gd.get("SlotsAvailable") or 0) != slots or int(gd.get("TotalGymCp") or 0) != (cp or 0))
                    bad = bad or (bat is not None and _b(o.get("IsInBattle")) != bat)
                if bad:
                    same.append(fid)
        if missing:
            continue
        # never full-read: only late once the fort has been in view > 60 s of this window (a first sighting over the
        # per-reply cap is read on a later reply); read once: late when > 10 min older than the last sighting
        if (ep(last) - max(ep(first) or 0, ep(since)) > PENDING_S * 2) if rawt is None else (ep(last) - ep(rawt) > RAW_MAX_LAG_S):
            rawold.append(fid)
        if gym:
            if gst is None or gst < last:
                lag.append(fid)
            elif gst == last:
                t_, g_ = int(team or 0), int(guard or 0)
                ok = 0 <= (mot or 0) <= 1
                if t_:                         # held: a display with >= 1 defender (0-5 open slots), CP and a top guard
                    ok = ok and slots is not None and g_ != 0 and (cp or 0) > 0 and 0 <= slots <= 5
                else:                          # neutral: no guard; display absent (NULL) or 0-6 open slots, no CP
                    ok = ok and g_ == 0 and (slots is None or 0 <= slots <= 6) and not cp
                if not ok:
                    cons.append(fid)
    if raw_live:
        flag(fails, "raw_vs_live", raw_live)
    if same:
        flag(fails, "same_read", same)
    if lag:
        flag(fails, "gym_state_lag", lag)
    if cons:
        flag(fails, "gym_consistency", cons)
    if rawold:
        (flag(fails, "raw_age", rawold) if len(rawold) > max(2, RAW_STALE_SHARE * len(rows))
         else flag(warns, "raw_age", rawold))

    # every team change must be followed by a state read and a full-record read
    nev = 0
    if not missing:
        tev = []
        for t, fid, gst, rawt, last in db.execute(
                "SELECT e.t, e.fort, f.gym_state_t, f.raw_t, f.last_seen FROM fort_events e JOIN forts f ON f.id = e.fort"
                " WHERE e.event='team' AND e.t >= ?", (since,)):
            nev += 1
            if gst is None or gst < t:                 # gym state is read on every sighting: never pending
                tev.append(fid)
            elif rawt is None or rawt < t:
                (pend.add(fid) if pending(fid, last, rawt) else tev.append(fid))
        if tev:
            flag(fails, "team_event_refresh", set(tev))
    info["raw_pending"] = len(pend)

    # canary: the gym seen last had its state read AT that sighting (a held gym with a display). Its raw record is not
    # required here: a first sighting may wait one reply for the per-reply full-read cap; raw_vs_live judges raw.
    c = db.execute(f"SELECT id, team, last_seen, {sel} FROM forts WHERE kind='gym' ORDER BY last_seen DESC LIMIT 1").fetchone()
    if c and c[2] >= since and not missing:
        if c[9] != c[2] or (c[1] and c[4] is None):
            flag(fails, "canary", [c[0]])
    info["canary"] = c[0] if c else None

    # read counters from the scanner's JS (reset each self-check)
    if js:
        fu, ff = js.get("fulls", 0), js.get("full_fail", 0)
        if ff >= 3 and ff > 0.01 * fu:
            flag(fails, f"js_full_reads({ff}/{fu} failed)", [], n=ff)
        if js.get("gym_fail"):
            flag(fails, f"js_gym_reads({js['gym_fail']}/{js.get('gyms', 0)} unreadable)", [], n=js["gym_fail"])
        if js.get("gym_nogd"):
            flag(warns, f"js_gym_no_display({js['gym_nogd']})", [], n=js["gym_nogd"])
        info["js"] = js

    # context (never a FAIL): what a consumer must label or exclude
    legacy = 0
    for fid, team, guard, raw in db.execute("SELECT id, team, guard, raw FROM forts WHERE raw IS NOT NULL"):
        o = _raw(raw) or {}
        legacy += int(o.get("Team") or 0) != int(team or 0) or int(o.get("GuardPokemonId") or 0) != int(guard or 0)
    info["legacy_raw_stale"] = legacy
    info["seed_only"] = db.execute("SELECT COUNT(*) FROM forts WHERE first_seen = '2026-09-25 03:13:57'"
                                   " AND last_seen = '2026-09-25 03:13:57'").fetchone()[0]   # one-time import, never seen live
    info["older_60min"] = db.execute("SELECT COUNT(*) FROM forts WHERE last_seen < ?", (st(ep(ref) - 3600),)).fetchone()[0]
    info["lure_older_30min"] = db.execute("SELECT COUNT(*) FROM forts WHERE lured=1 AND last_seen < ?",
                                          (st(ep(ref) - 1800),)).fetchone()[0]
    feeds = {}
    for name, q in (("spawns", "SELECT MAX(t) FROM spawns"), ("weather", "SELECT MAX(t) FROM weather"),
                    ("nearby", "SELECT MAX(t) FROM nearby"), ("raid", "SELECT COUNT(*) FROM forts WHERE raid IS NOT NULL"),
                    ("displays", "SELECT COUNT(*) FROM forts WHERE displays > 0")):
        try:
            feeds[name] = db.execute(q).fetchone()[0]
        except sqlite3.Error:
            feeds[name] = None
    info["not_collected"] = feeds       # by design since 2026-09-25 (no raid / incident / spawn decode)
    if not missing:
        fresh = db.execute("SELECT COUNT(*) FROM forts WHERE kind='gym' AND gym_state_t >= ?", (st(ep(ref) - 120),)).fetchone()[0]
        info["gyms_state_2min"] = fresh

    if consumers and os.path.exists(LIVE_DATA):
        try:                            # "stats" is the LAST key of a ~0.5 MB file: read its tail, not its head
            with open(LIVE_DATA, "rb") as fh:
                fh.seek(max(0, os.path.getsize(LIVE_DATA) - 65536))
                txt = fh.read().decode("utf-8", "replace")
            if '"last_reply_age_s"' not in txt:
                flag(warns, "map_live_data_unlabelled(no last_reply_age_s; restart map_live.py)", [], n=1)
        except OSError:
            pass
    if consumers:                       # the 2026-09-25 bug class: a bank consumer taking a dynamic value from raw
        hits = []
        for p in sorted(glob.glob(os.path.join(HERE, "*.py"))):
            if os.path.basename(p) in LINT_SKIP:
                continue
            try:
                src = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if "pogo_wigle.db" not in src:
                continue
            try:                        # string literals only (dict keys), so comments never trip it
                lits = [tk.string for tk in tokenize.generate_tokens(io.StringIO(src).readline) if tk.type == tokenize.STRING]
            except (tokenize.TokenError, SyntaxError):
                lits = [src]
            keys = sorted({k for s in lits for k in DYNAMIC_RAW.findall(s)})
            if keys:
                hits.append(f"{os.path.basename(p)}:{'/'.join(keys)}")
        if hits:
            flag(warns, "consumer_reads_dynamic_raw", hits)

    info.update(window_forts=len(rows), window_gyms=ngym, window_stops=nstop, window_raw=nraw, same_read_rows=nsame,
                team_events=nev)
    ok = not fails

    def fmt(x):
        ids = x["ids"]
        more = f" +{x['n'] - len(ids)}" if x["n"] > len(ids) else ""
        return f"{x['check']}={x['n']}" + (f" [{', '.join(ids)}{more}]" if ids else "")

    if missing:
        stamped = "gym state / raw age n/a (pre-fix schema)"
    else:
        stamped = (f"gym state fresh {ngym - len(lag)}/{ngym}, raw<=10min {len(rows) - len(rawold)}/{len(rows)},"
                   f" same-read {nsame - len(same)}/{nsame}, team events {nev}")
    counts = (f"since {since[11:]}: {ngym} gyms {nstop} stops seen, raw==live {nraw - len(raw_live)}/{nraw}, {stamped}"
              f" | last reply {round(age)}s ago | legacy raw stale {legacy}")
    if js:
        counts += f" | js full {js.get('fulls', 0)} fail {js.get('full_fail', 0)}, gym {js.get('gyms', 0)} fail {js.get('gym_fail', 0)}"
    head = "SELFCHECK ok" if ok else "SELFCHECK FAIL " + "; ".join(fmt(x) for x in fails)
    if warns:
        head += " | WARN " + "; ".join(fmt(x) for x in warns)
    return {"ok": ok, "line": f"{head} | {counts}", "fails": fails, "warns": warns, "info": info, "checked_at": st(now)}


def write_health(path, res):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--window", type=float, default=WINDOW_S / 60, help="minutes before the newest map reply")
    ap.add_argument("--since", help="judge rows seen at/after this local time instead of --window")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-health", action="store_true", help=f"also write {HEALTH}")
    a = ap.parse_args()
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=10)
    res = run(db, since=a.since, window_s=a.window * 60, consumers=True)
    db.close()
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(res["line"])
        for x in res["fails"]:
            print(f"  FAIL {x['check']}: {x['n']}  {' '.join(x['ids'])}")
        for x in res["warns"]:
            print(f"  WARN {x['check']}: {x['n']}  {' '.join(x['ids'])}")
        for k, v in res["info"].items():
            print(f"  info {k}: {v}")
    if a.write_health:
        write_health(HEALTH, res)
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
