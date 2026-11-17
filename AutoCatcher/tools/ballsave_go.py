"""BALL-SAVER, one command (Benny 2026-11-16 Minior Showers: "max star dust and all balls except 50 used by 9:01pm";
"keep going until you have 50 balls left"; "when in these kinds of star dust modes, you need to catch all shinies
regardless"). Replaces the 11-16 scratch scripts (go_ballsave.sh, replan5.py, starpiece_watch.py).

WRITES TO THE PHONE (the plan file only) -- run it on Benny's go typed in the session. --dry never writes.
  python AutoCatcher/tools/ballsave_go.py --start 17:00 --end 21:00 --keep 50 [--prior DIR] [--every 5] [--dry]
  python AutoCatcher/tools/ballsave_go.py --save-prior DIR --start 17:16:45 --end 21:00 --since 19:12:40 [--date 2026-11-16]
  python AutoCatcher/tools/ballsave_go.py --selftest
What a round does: pull the phone's spawn ledger + catcher log tails (reads) -> join each catch's stardust ("d"; the
11-17 catcher writes it itself) -> tools/ballsave_plan.py: species ranked by stardust per ball, rates from the last
30 throwing minutes, margin 1.0 (no feedback: 11-16 it chased noise) -> push the plan ATOMICALLY (a .new file, then mv:
the catcher never reads half a file) -> read it back. The catcher re-solves every second against its live ball count,
keeps the --keep balls IN ALL (its own 5/5/5 floors count toward them), and opens every spawn it leaves alone to see
whether it is shiny (a shiny gets any ball, the kept ones too).
--every N: a new plan every N minutes until --end, and between rounds the catcher's SHINY / STARPIECE / NOT CATCHING /
HOLD / ERR lines (and a BALLSAVE off / ended) are printed as they come (one line each: a session's Monitor turns them
into pings). Until the FIRST plan lands it retries every 20 s ("NO PLAN PUSHED YET": the phone still has an older one).
--prior DIR: an earlier shower's catches (written by --save-prior) -- the first plan of a day has no data of its own.
Stop: Ctrl-C (the plan stays). Off: delete /data/local/tmp/pogo_ballsave.json."""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ballsave_plan as bp  # noqa: E402

DEV = os.environ.get("ADB_TARGET", "100.98.158.56:5555")   # deploy.sh uses the same variable
POGO = "/data/data/com.termux/files/home/pogo/system/analysis/pokemod"
PLAN = "/data/local/tmp/pogo_ballsave.json"
GM = os.path.join(HERE, os.pardir, os.pardir, "pogo_extract", "gamemaster_pokeminers.json")
CATCH = re.compile(r"^(\d\d):(\d\d):(\d\d) CATCH \S+ #(\d+) .*?dust=(\d+)")
EVENT = re.compile(r"^\d\d:\d\d:\d\d (SHINY|STARPIECE|BALLSAVE (?:off|the plan ended|waiting)|NOT CATCHING|HOLD|ERR|"
                   r"JS ERROR|install failed|attached|waiting for PoGo|!!! SAFETY HOLD|safety hold lifted|"
                   r"paused for another tool|--- link drop|--- error)")   # BALLSAVE's minute-by-minute cut is noise


def adb(*args, timeout=120):
    """Out of a native adb, never Git Bash's path rewriting (memory: feedback-git-bash-windows)."""
    r = subprocess.run(["adb", "-s", DEV] + list(args), capture_output=True, timeout=timeout)
    out = r.stdout.decode("utf-8", "replace").replace("\r", "")
    if r.returncode:   # adb says why on stderr ("device offline", "unauthorized"): keep it for the error line
        out += r.stderr.decode("utf-8", "replace").replace("\r", "")
    return r.returncode, out


def epoch_of(day, hms):
    h, m, *s = (int(x) for x in hms.split(":"))
    return time.mktime(dt.datetime(day.year, day.month, day.day, h, m, s[0] if s else 0).timetuple())


def date_log(lines, now):
    """catch_loop.log has no dates. Walking back from the newest line (dated today), a time LATER than the line after it
    means the day before (a midnight, or a catcher that was off overnight). -> [(epoch, line)], oldest first."""
    out, day, nxt = [], dt.date.fromtimestamp(now), None
    for ln in reversed(lines):
        if len(ln) < 8 or ln[2] != ":" or ln[5] != ":":
            continue
        try:
            sec = int(ln[0:2]) * 3600 + int(ln[3:5]) * 60 + int(ln[6:8])
        except ValueError:
            continue
        if nxt is not None and sec > nxt + 60:
            day -= dt.timedelta(days=1)
        nxt = sec
        out.append((epoch_of(day, ln[:8]), ln))
    out.reverse()
    return out


def join_dust(records, dated):
    """Give each caught record without "d" the stardust of its CATCH line: same species, within 4 s of its end."""
    idx = {}
    for t, ln in dated:
        m = CATCH.match(ln)
        if m:
            idx.setdefault(int(m.group(4)), []).append((t, int(m.group(5))))
    n = 0
    for r in records:
        if r.get("r") != "caught" or r.get("d") is not None or r.get("t1") is None or r.get("id") is None:
            continue
        best = None
        for t, d in idx.get(int(r["id"]), []):
            gap = abs(t - r["t1"] / 1000)
            if gap <= 4 and (best is None or gap < best[0]):
                best = (gap, d)
        if best:
            r["d"] = best[1]
            n += 1
    return n


def merge(*lists):
    """One record per spawn: its last word (the latest t1), across the prior and today's pull."""
    last = {}
    for lst in lists:
        for r in lst:
            if r.get("e") is None:
                continue
            o = last.get(r["e"])
            if o is None or (r.get("t1") or 0) >= (o.get("t1") or 0):
                last[r["e"]] = r
    return list(last.values())


def load_prior(d):
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    recs = [json.loads(ln) for ln in open(os.path.join(d, "catches.jsonl"), encoding="utf-8") if ln.strip()]
    return meta, recs


def pull(tail, adb_=adb):
    """-> (spawn records, log lines, the log's mtime: its newest line's date -- not the PC's today; None if unread)."""
    rc1, led = adb_("exec-out", f"su -c 'tail -n {tail} {POGO}/spawn_ledger.jsonl'")
    rc2, log = adb_("exec-out", f"su -c 'stat -c %Y {POGO}/catch_loop.log; tail -n 40000 {POGO}/catch_loop.log'")
    if rc1 or rc2 or not led.strip():
        why = (led if rc1 else log if rc2 else "the ledger came back empty").strip()[-200:]
        raise RuntimeError(f"pull failed (ledger rc {rc1}, log rc {rc2}): {why}")
    lines = log.splitlines()
    mtime = int(lines.pop(0)) if lines and lines[0].strip().isdigit() else None
    recs = []
    for ln in led.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("k", "spawn") == "spawn":
            recs.append(r)
    return recs, lines, mtime


def push(local, adb_=adb):
    """Atomic: the catcher re-reads the file when its mtime changes; a half-pushed file read once = no saver for a second."""
    rc, out = adb_("push", local, PLAN + ".new")
    if rc:
        raise RuntimeError(f"push failed: {out[-200:]}")
    rc, out = adb_("shell", f"su -c 'chmod 644 {PLAN}.new && mv -f {PLAN}.new {PLAN} && cat {PLAN}'")
    try:
        back = json.loads(out)
    except ValueError:
        back = None
    if rc or not back or back.get("made") != json.load(open(local, encoding="utf-8")).get("made"):
        raise RuntimeError(f"read-back of {PLAN} does not match what was pushed (rc {rc})")
    return back


def check_plan(plan, end, keep):
    sp = plan.get("species") or {}
    bad = [k for k, v in sp.items() if not (v[0] == v[0] and v[1] == v[1] and v[0] >= 0 and v[1] >= 0)]   # NaN / negative
    if plan.get("end") != end or plan.get("keep") != keep or len(sp) < 20 or bad:
        raise RuntimeError(f"bad plan: end {plan.get('end')} keep {plan.get('keep')} species {len(sp)} bad {bad[:5]}")


def old_catcher(dated):
    """The phone's catcher from before 11-17 (its attach line has no 'shiny' field): no shiny look; it holds the keep through
    the plan's "reserve" (on top of its floors) -- the plan carries both."""
    att = [ln for _t, ln in dated if " attached pid=" in ln]
    return bool(att) and "'shiny'" not in att[-1]


def one_round(a, prior, since, out_dir, adb_=adb, now=None):
    now = now or time.time()
    recs, log, mtime = pull(a.tail, adb_)
    dated = date_log(log, mtime or now)
    today = [r for r in recs if (r.get("t0") or 0) >= a.start_e * 1000]
    joined = join_dust(today, dated)
    bare = sum(1 for r in today if r.get("r") == "caught" and not r.get("d"))   # None, or 0: the award was not read
    allrecs = merge(prior, today)
    start = min([a.start_e] + [r["t0"] / 1000 for r in prior if r.get("t0")])
    plan, sm = bp.build(allrecs, start, a.end_e, keep=a.keep, margin=1.0,
                        bonus=bp.gm_bonus(GM) if os.path.exists(GM) else None, since=since, recent=a.recent)
    if sm["dust_from"] != "ledger":   # every species would rank by the game master's bonus alone: worse than no new plan
        raise RuntimeError("no catch carries its stardust (no prior, nothing joined to the log): not pushing a blind plan")
    check_plan(plan, a.end_e, a.keep)
    local = os.path.join(out_dir, "pogo_ballsave.json")
    json.dump(plan, open(local, "w", encoding="utf-8"), indent=0)
    top = list(plan["species"].items())[:3]
    head = (f"{sm['species']} species, {sm['minutes']} throwing minutes, today {len(today)} spawns ({joined} catches joined to "
            f"the log), stardust from the {sm['dust_from']} | best " + ", ".join(f"#{d} {v[0]:.0f}/ball" for d, v in top))
    if bare > max(20, 0.2 * sum(1 for r in today if r.get("r") == "caught")):
        head += f" | WARNING {bare} of today's catches have no stardust (log dates?): ranked on the prior for those"
    if old_catcher(dated):
        head += " | WARNING the phone runs the pre-11-17 catcher: NO shiny look (the keep is held through the plan's reserve)"
    if a.dry:
        return head + " | DRY: nothing written to the phone", dated
    push(local, adb_)
    return head + f" | plan pushed {time.strftime('%H:%M:%S')} (end {time.strftime('%H:%M', time.localtime(a.end_e))}, keep {a.keep} in all)", dated


def new_events(dated, seen):
    """EVENT lines of a round's pull not printed yet (they came after the last events() poll), oldest first."""
    new = [ln for _t, ln in dated[-600:] if EVENT.match(ln) and ln not in seen]
    seen.update(new)
    return new


def events(adb_, seen):
    """New catcher lines worth a look, oldest first (seen = the lines already printed)."""
    rc, out = adb_("exec-out", f"su -c 'tail -n 80 {POGO}/catch_loop.log'", timeout=30)
    new = []
    for ln in out.splitlines():
        if EVENT.match(ln) and ln not in seen:
            seen.add(ln)
            new.append(ln)
    return new


def save_prior(a, adb_=adb):
    recs, log, mtime = pull(max(a.tail, 60000), adb_)
    dated = date_log(log, mtime or time.time())
    win = [r for r in recs if a.start_e * 1000 <= (r.get("t0") or 0) <= a.end_e * 1000]
    joined = join_dust(win, dated)
    os.makedirs(a.save_prior, exist_ok=True)
    with open(os.path.join(a.save_prior, "catches.jsonl"), "w", encoding="utf-8") as fh:
        for r in merge(win):
            fh.write(json.dumps(r) + "\n")
    json.dump({"start": a.start_e, "end": a.end_e, "saver_since": a.since_e, "made": time.strftime("%Y-%m-%d %H:%M:%S"),
               "records": len(win), "joined": joined}, open(os.path.join(a.save_prior, "meta.json"), "w", encoding="utf-8"), indent=1)
    caught = sum(1 for r in win if r.get("r") == "caught")
    with_d = sum(1 for r in win if r.get("r") == "caught" and int(r.get("d") or 0) > 0)   # 0 = the award was not read
    print(f"saved {len(win)} spawn records ({caught} caught, {with_d} with their stardust) to {a.save_prior}")


def _selftest():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name.ljust(46), repr(got)[:120], "" if ok else f"  want {want!r}")

    now = time.mktime(dt.datetime(2026, 11, 17, 0, 10, 0).timetuple())
    lines = ["23:58:00 run 10s", "23:59:59 CATCH Wild #774 ball=1 p=0.2 dust=3037 candy=3", "00:00:05 CATCH Wild #10 ball=1 dust=337 candy=3",
             "garbage", "00:09:00 run 20s"]
    dl = date_log(lines, now)
    check("dates: the line before midnight is yesterday", [time.strftime("%m-%d %H:%M:%S", time.localtime(t)) for t, _ in dl],
          ["11-16 23:58:00", "11-16 23:59:59", "11-17 00:00:05", "11-17 00:09:00"])
    off = ["21:00:00 run", "08:00:00 run"]   # catcher off overnight: 08:00 today, 21:00 yesterday
    check("dates: an overnight gap is a day too", [time.strftime("%d %H", time.localtime(t)) for t, _ in date_log(off, now + 9 * 3600)],
          ["16 21", "17 08"])
    t_m = time.mktime(dt.datetime(2026, 11, 16, 23, 59, 59).timetuple())
    recs = [{"e": "a", "id": 774, "r": "caught", "t1": (t_m + 2) * 1000, "t0": t_m * 1000},
            {"e": "b", "id": 774, "r": "caught", "t1": (t_m + 9) * 1000, "t0": t_m * 1000},
            {"e": "c", "id": 10, "r": "caught", "t1": (t_m + 6) * 1000, "d": 412, "t0": t_m * 1000},
            {"e": "d", "id": 10, "r": "fled", "t1": (t_m + 6) * 1000, "t0": t_m * 1000}]
    check("join: within 4 s, same species; d kept", (join_dust(recs, dl), [r.get("d") for r in recs]), (1, [3037, None, 412, None]))
    m = merge([{"e": "x", "t1": 5, "r": "gone"}], [{"e": "x", "t1": 9, "r": "caught"}, {"e": "y", "t1": 1}])
    check("merge: the last word per spawn", sorted((r["e"], r.get("r")) for r in m), [("x", "caught"), ("y", None)])
    # a whole round against a fake phone: pull, build, atomic push, read-back
    S = int(time.mktime(dt.datetime(2026, 11, 17, 17, 0, 0).timetuple()))
    led = []
    for i in range(40):
        for dex, n, d in ((774, 1, 3037), (10 + i % 25, 1, 337)):
            led.append(json.dumps({"k": "spawn", "e": f"{dex}-{i}", "id": dex, "t0": (S + 60 * i) * 1000, "t1": (S + 60 * i + 3) * 1000,
                                   "n": n, "r": "caught", "d": d}))
    phone = {}
    calls = []

    def fake(*args, timeout=120):
        calls.append(args[0] if args[0] != "exec-out" else "exec-out " + args[1].split("/")[-1].rstrip("'"))
        if args[0] == "exec-out" and "spawn_ledger" in args[1]:
            return 0, "\n".join(led) + "\n{bad json\n"
        if args[0] == "exec-out":
            return 0, "17:30:00 SHINY Wild #10 odds 1:0.300 -- left alone by the ball-saver, caught anyway\n17:30:01 run 5s\n"
        if args[0] == "push":
            phone["new"] = open(args[1], encoding="utf-8").read()
            return 0, ""
        if args[0] == "shell":
            phone["plan"] = phone.pop("new")
            return 0, phone["plan"]
        return 1, ""

    class A:
        tail, recent, keep, dry = 30000, 30, 50, False
        start_e, end_e = S, S + 4 * 3600
    with tempfile.TemporaryDirectory() as td:
        head, _ = one_round(A, [], None, td, adb_=fake, now=S + 3000)
        pushed = json.loads(phone["plan"])
        check("round: plan pushed atomically + read back", (calls[-2:], pushed["keep"], pushed["end"], pushed["margin"]),
              (["push", "shell"], 50, S + 4 * 3600, 1.0))
        check("round: Minior ranked first", list(pushed["species"])[0], "774")
        check("round: the summary line", head.split(" | ")[0][:31], "26 species, 40 throwing minutes")
        A.dry = True
        n_calls = len(calls)
        head, _ = one_round(A, [], None, td, adb_=fake, now=S + 3000)
        check("dry: reads only", [c for c in calls[n_calls:] if not c.startswith("exec-out")], [])
    seen = set()
    check("events: a SHINY line once", (len(events(fake, seen)), len(events(fake, seen))), (1, 0))
    try:
        check_plan({"end": 1, "keep": 50, "species": {str(i): [1.0, 0.1] for i in range(25)}}, 2, 50)
        check("check_plan: a wrong end stops it", "passed", "raised")
    except RuntimeError:
        check("check_plan: a wrong end stops it", "raised", "raised")
    # the log's own mtime dates it: a catcher silent since last night is not "today" on the PC
    t_last = int(time.mktime(dt.datetime(2026, 11, 16, 21, 0, 30).timetuple()))

    def fake2(*args, timeout=120):
        if "spawn_ledger" in args[1]:
            return 0, json.dumps({"k": "spawn", "e": "q", "id": 774, "t0": 1, "t1": 2, "n": 1, "r": "caught"}) + "\n"
        return 0, f"{t_last}\n20:59:58 CATCH Wild #774 ball=1 p=0.2 dust=3037\n21:00:30 run 5s\n"
    recs2, log2, mt2 = pull(10, fake2)
    check("pull: the log's mtime, then its lines", (mt2, len(log2), log2[0][:8]), (t_last, 2, "20:59:58"))
    check("dates from the mtime, not the PC's today", time.strftime("%m-%d %H:%M:%S", time.localtime(date_log(log2, mt2)[0][0])),
          "11-16 20:59:58")
    # no stardust anywhere (no prior, nothing joins): refuse instead of ranking on the game master alone

    def fake3(*args, timeout=120):
        if args[0] == "exec-out" and "spawn_ledger" in args[1]:
            return 0, "\n".join(json.dumps(dict(json.loads(ln), d=None)) for ln in led) + "\n"
        if args[0] == "exec-out":
            return 0, "17:30:01 run 5s\n"
        return 1, ""
    with tempfile.TemporaryDirectory() as td:
        A.dry = False
        try:
            one_round(A, [], None, td, adb_=fake3, now=S + 3000)
            check("no stardust anywhere: not pushed", "pushed", "refused")
        except RuntimeError as e:
            check("no stardust anywhere: not pushed", "refused" if "stardust" in str(e) else str(e), "refused")
    dd = [(0, "17:00:00 attached pid=1 age=5s | mighty={'wildPokemon': 16, 'display': 24, 'flag': 40}")]
    check("the pre-11-17 catcher is named", (old_catcher(dd), old_catcher([(0, dd[0][1][:-1] + ", 'shiny': 32}")]), old_catcher([])),
          (True, False, False))
    seen2 = set()
    hist = [(0, "17:00:00 SHINY Wild #10 ..."), (0, "17:00:01 BALLSAVE 300 balls to spend for 200 min, 50 kept in all: leaving 9"),
            (0, "17:00:02 BALLSAVE off: unreadable plan"), (0, "17:00:03 run 5s")]
    check("events: round lines once; the saver's cut is not one", (new_events(hist, seen2), new_events(hist, seen2)),
          (["17:00:00 SHINY Wild #10 ...", "17:00:02 BALLSAVE off: unreadable plan"], []))
    dark = ["17:01:00 !!! SAFETY HOLD: PoGo died within 20s of our attach 2x in a row -- not attaching for 30 min",
            "17:01:01 paused for another tool until 17:20:00 -- detached", "17:01:02 still paused (50s left)",
            "17:01:03 --- link drop after 40s attached: gone -- re-attaching ---", "17:01:04 --- error: boom -- retry in 4s ---",
            "17:01:05 safety hold (29 min left)"]
    check("events: the catcher going dark is one", [ln[9:17] for ln in dark if EVENT.match(ln)], ["!!! SAFE", "paused f", "--- link", "--- erro"])
    check("events: a run of 4 ball lines is not news", bool(EVENT.match("17:01:06 run 40s | caught=3")), False)
    # main() against a fake phone and clock: a failed first round does not replay old lines; one failure line per 5 min;
    # a run that never pushed a plan says so and exits 1
    import contextlib
    import io
    import types
    g = globals()
    real = {k: g[k] for k in ("one_round", "events", "time", "shutil")}
    day = dt.date.today()
    clock = [epoch_of(day, "17:00:00")]
    g.update(time=types.SimpleNamespace(time=lambda: clock[0], sleep=lambda x: clock.__setitem__(0, clock[0] + x),
                                        strftime=time.strftime, mktime=time.mktime, localtime=time.localtime),
             events=lambda adb_, seen: [], shutil=types.SimpleNamespace(which=lambda x: "adb"))
    old = [(0, "16:41:00 SHINY Wild #10 odds 1:0.300"), (0, "16:40:00 BALLSAVE the plan ended: catching everything above the 50 balls kept in all")]
    tries = {"n": 0}

    def flaky(*args, **kw):
        tries["n"] += 1
        if tries["n"] == 1:
            raise RuntimeError("pull failed (ledger rc 1, log rc 1): error: device offline")
        return "a plan line", old

    def dead(*args, **kw):
        raise RuntimeError("pull failed (ledger rc 1, log rc 1): error: device unauthorized")
    argv0 = sys.argv
    try:
        for name, fn in (("flaky", flaky), ("dead", dead)):
            clock[0] = epoch_of(day, "17:00:00")
            g["one_round"] = fn
            sys.argv = ["ballsave_go.py", "--start", "17:00", "--end", "17:12", "--keep", "50", "--every", "5"]
            out, code = io.StringIO(), 0
            with contextlib.redirect_stdout(out):
                try:
                    main()
                except SystemExit as ex:
                    code = ex.code or 0
            lines = out.getvalue().splitlines()
            if name == "flaky":
                check("main: a failed first try replays no old line", (sum("PHONE" in ln for ln in lines), sum("ROUND FAILED" in ln for ln in lines),
                                                                       "done" in lines[-1], code), (0, 1, True, 0))
            else:
                check("main: dead all along: 3 failure lines, no 'done', exit 1",
                      (sum("ROUND FAILED" in ln for ln in lines), "device unauthorized" in lines[0], lines[-1][9:28], code),
                      (3, True, "NO PLAN WAS PUSHED ", 1))
    finally:
        g.update(real)
        sys.argv = argv0
    return failed


def main():
    ap = argparse.ArgumentParser(description="ball-saver: plan, push, re-plan (writes the plan file on the phone)")
    ap.add_argument("--start", help="HH:MM[:SS] local, the shower's start (records from it count)")
    ap.add_argument("--end", help="HH:MM[:SS] local, when the balls should be spent (the shower's end)")
    ap.add_argument("--keep", type=int, help="balls to keep IN ALL at --end")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--prior", action="append", default=[], help="an earlier shower's --save-prior directory")
    ap.add_argument("--since", help="HH:MM[:SS]: when the saver went live (default: the prior's, else the first push)")
    ap.add_argument("--recent", type=int, default=30)
    ap.add_argument("--tail", type=int, default=30000)
    ap.add_argument("--every", type=float, help="re-plan every N minutes until --end")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--save-prior", help="write the window's records (with their stardust) to this directory, nothing else")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(1 if _selftest() else 0)
    if not (a.start and a.end):
        ap.error("--start and --end are needed")
    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    a.start_e, a.end_e = int(epoch_of(day, a.start)), int(epoch_of(day, a.end))
    a.since_e = int(epoch_of(day, a.since)) if a.since else None
    if a.end_e <= a.start_e:
        ap.error(f"--end {a.end} is not after --start {a.start} (24-hour times: 21:00, not 9:00)")
    if a.save_prior:
        save_prior(a)
        return
    if a.keep is None:
        ap.error("--keep is needed (balls to keep in all)")
    if not a.dry and a.end_e <= time.time() + 60:   # a plan past its end only holds the keep: nothing to plan
        ap.error(f"--end {a.end} has passed (or is under a minute away)")
    if not shutil.which("adb"):
        sys.exit("adb not found")
    prior, since = [], a.since_e
    for d in a.prior:
        meta, recs = load_prior(d)
        prior += recs
        since = since or meta.get("saver_since")
    since = since or int(time.time())   # a saver going live now: its species left alone from now on
    out_dir = tempfile.mkdtemp(prefix="ballsave_")
    seen, pushed, primed, said = set(), False, False, ("", 0.0)
    while True:
        t0 = time.time()
        try:
            head, dated = one_round(a, prior, since, out_dir)
            print(f"{time.strftime('%H:%M:%S')} {head}", flush=True)
            pushed = pushed or not a.dry
            for ln in new_events(dated, seen):
                if primed:   # the first GOOD round only marks the history (review 11-16: a failed first try replayed it)
                    print(f"PHONE {ln}", flush=True)
            primed, said = True, ("", 0.0)
        except Exception as e:   # noqa: BLE001 -- one bad round must not end a 4-hour run
            msg = (f"ROUND FAILED: {type(e).__name__}: {str(e)[:300]} -- "
                   + ("the last plan stays in force" if pushed else "NO PLAN PUSHED YET (the phone keeps whatever it had)"))
            if msg != said[0] or time.time() - said[1] >= 300:   # the same failure once per 5 min, not every 20 s retry
                print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)
                said = (msg, time.time())
            if not a.every:
                sys.exit(1)
            if not pushed and not a.dry and time.time() < a.end_e - 60:
                time.sleep(20)   # the first plan is the one that matters: retry soon, not in N minutes
                continue
        if not a.every or a.dry or time.time() >= a.end_e - 60:
            break
        while time.time() - t0 < a.every * 60 and time.time() < a.end_e - 60:
            try:
                for ln in events(adb, seen):
                    print(f"PHONE {ln}", flush=True)
            except Exception:   # noqa: BLE001 -- a missed poll is caught up by the next round
                pass
            time.sleep(15)
    if not a.dry and not pushed:   # never "done" for a run whose plan never reached the phone
        print(f"{time.strftime('%H:%M:%S')} NO PLAN WAS PUSHED by this run (the phone kept whatever it had)", flush=True)
        sys.exit(1)
    if not a.dry:
        print(f"{time.strftime('%H:%M:%S')} done (the plan stays on the phone: it keeps {a.keep} balls in all until it is deleted)", flush=True)


if __name__ == "__main__":
    main()
