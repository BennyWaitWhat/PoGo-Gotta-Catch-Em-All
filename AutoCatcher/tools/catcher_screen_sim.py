"""Offline test of the catcher's ON-SCREEN gate (no phone): python tools/catcher_screen_sim.py
catch_loop_fast.py attaches only while Pokemon GO is on screen, detaches when it leaves, waits for its game code before the
first attach, and stops connecting to a game process that refused ATTACH_TRIES attaches; run_catch.sh never takes a silent
catcher behind other apps for a hang and never kills one mid-handshake (docs/requests/2026-11-15-catcher-attach-loop-crashes.md,
asks 1-6). Python side: the look's parse, the wait before an attach, the failed-attach count and hold, the log's date line,
the watcher thread, the session loop's wiring. Shell side (bash): run_catch.sh's look / end() / silence rule, with su, kill and
sleep faked. Exit code 1 when any check fails."""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, os.pardir, "system", "scripts", "game_write", "catch_loop_fast.py"), encoding="utf-8").read()
RUN = open(os.path.join(HERE, os.pardir, "run_catch.sh"), encoding="utf-8").read()
failed = 0


def check(name, got, want):
    global failed
    ok = got == want
    failed += not ok
    print(("ok   " if ok else "FAIL ") + name.ljust(60), repr(got), "" if ok else f"  want {want!r}")


class Clock:
    """time, as far as the gate uses it: a clock that moves only when the code sleeps. on_sleep(now) runs after each sleep."""
    def __init__(self, t=1_000_000.0):
        self.t, self.on_sleep = t, None

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s
        if self.on_sleep:
            self.on_sleep(self.t)

    def strftime(self, fmt, *a):
        import time as _t
        return _t.strftime(fmt, *a)

    def localtime(self, *a):
        import time as _t
        return _t.localtime(*a)


def load():
    ns = {"re": re, "os": os}
    for pat in (r"^GAME_PKG = .*$", r"^LOOK_S, OFF_LOOKS = .*$", r"^REATTACH_GAP_S = .*$", r"^ATTACH_TRIES = .*$"):
        exec(re.search(pat, SRC, re.M).group(0), ns)
    exec(re.search(r"^LOOK_CMD = \(.*?\)\n", SRC, re.S | re.M).group(0), ns)
    ns["subprocess"] = subprocess
    exec(re.search(r"^class RootShell:.*?(?=^WATCH = )", SRC, re.S | re.M).group(0), ns)
    exec(re.search(r"^WATCH = .*$", SRC, re.M).group(0), ns)
    for name in ("parse_look", "watch_loop", "look_now", "attachable", "off_screen_why", "wait_attachable", "failed_attach",
                 "hold_bad_pid"):
        exec(re.search(rf"^def {name}\(.*?(?=^\n\ndef )", SRC, re.S | re.M).group(0), ns)
    ns["time"] = Clock()
    ns["log"], ns["states"] = [], []
    ns["w"] = lambda s: ns["log"].append(s)
    ns["state"] = lambda why="", counters=None: ns["states"].append(why)
    ns["paused_until"] = lambda: 0
    return ns


TCP = "   0: 0100007F:69A7 00000000:0000 0A 00000000:00000000 00:00000000 00000000 10447        0 2206815 1 0000000000000000 100 0 0 10 0\n"
TOP = "    topResumedActivity=ActivityRecord{141776772 u0 %s/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity t59}\n"
GAME = "com.nianticlabs.pokemongo"


def look_out(up=True, pid=18521, adj=0, code=True, top=GAME, awake=True):
    """What LOOK_CMD prints on the phone (taken from a real run, 2026-11-19 12:5x, the game on screen)."""
    o = TCP if up else ""
    if pid is None:
        return o
    o += f"pid={pid}\nadj={adj}\n" + ("il2cpp=loaded\n" if code else "")
    if adj != 0:
        return o
    return o + (TOP % top if top else "") + f"  mWakefulness={'Awake' if awake else 'Asleep'}\n"


# ---- the look ---------------------------------------------------------------------------------------------------------------
ns = load()
pl = ns["parse_look"]
lk = pl(look_out())
check("look: the game on screen", (lk["up"], lk["pid"], lk["code"], lk["screen"], lk["what"]),
      (True, 18521, True, True, "Pokemon GO is on screen"))
check("look: another app on top", (pl(look_out(top="com.whatsapp"))["screen"], pl(look_out(top="com.whatsapp"))["what"]),
      (False, "com.whatsapp is on screen"))
check("look: the app itself on top (a tap in the app: the game is behind it)", pl(look_out(top="com.benny.autocatcher"))["screen"], False)
check("look: the screen off with the game on top", (pl(look_out(awake=False))["screen"], pl(look_out(awake=False))["what"]),
      (False, "the screen is off"))
check("look: adj not 0 = in the background (no dumpsys lines at all)",
      (pl(look_out(adj=700))["screen"], pl(look_out(adj=700))["what"], pl(look_out(adj=700))["code"]),
      (False, "Pokemon GO is in the background", True))
check("look: game code not loaded yet", (pl(look_out(code=False))["code"], pl(look_out(code=False))["screen"]), (False, True))
check("look: no game process", (pl(look_out(up=False, pid=None))["up"], pl(look_out(up=False, pid=None))["pid"],
                                pl(look_out(up=False, pid=None))["what"]), (False, None, "Pokemon GO is not running"))
check("look: a failed read (empty) = not on screen, nothing up", (pl("")["screen"], pl("")["up"], pl(None)["screen"]), (False, False, False))
check("look: the top line unreadable = not on screen", pl(look_out(top=None))["what"], "what is on screen could not be read")
check("look: older 'ResumedActivity:' form is read too",
      pl(look_out().replace("topResumedActivity=", "ResumedActivity: "))["screen"], True)
check("look: a package that only starts like the game's is not it",
      pl(look_out(top="com.nianticlabs.pokemongo.fake"))["screen"], False)
check("look: one su call, the LISTEN entry read and never connected to (no /dev/tcp, no nc)",
      ("/proc/net/tcp" in ns["LOOK_CMD"], "/dev/tcp" in ns["LOOK_CMD"], " nc " in ns["LOOK_CMD"]), (True, False, False))
check("look: dumpsys only when the game is the top app (adj 0)",
      ns["LOOK_CMD"].index('[ "$a" = 0 ] || exit 0') < ns["LOOK_CMD"].index("dumpsys"), True)

# ---- the watcher -------------------------------------------------------------------------------------------------------------
class Stop(BaseException):
    pass


ns = load()
outs = [look_out(), look_out(top="com.whatsapp"), "", look_out(code=False), look_out(), Stop]
cmds, shells = [], []


class FakeShell:
    def __init__(self):
        shells.append(self)

    def run(self, cmd, timeout=10):
        cmds.append(cmd)
        o = outs.pop(0)
        if o is Stop:
            raise Stop()
        return o


ns["RootShell"] = FakeShell
ns["su"] = lambda cmd, timeout=10: (_ for _ in ()).throw(AssertionError("the watcher made a su call of its own"))
offs = []
ns["time"].on_sleep = lambda t: offs.append(ns["WATCH"]["off"])
try:
    ns["watch_loop"]()
except Stop:
    pass
check("watcher: off-screen looks counted in a row, reset on screen (a failed read counts as off)", offs, [0, 1, 2, 0, 0])
check("watcher: it writes no log line and no app line (a hung main thread must stay silent)", (ns["log"], ns["states"]), ([], []))
check("watcher: one root shell for every look, no su call per look", len(shells), 1)
check("watcher: the maps are read until the code is found loaded, then skipped for that pid; a failed look forgets it",
      ['[ "$p" = 0 ]' in cmds[0], '[ "$p" = 18521 ]' in cmds[1], '[ "$p" = 18521 ]' in cmds[2], '[ "$p" = 0 ]' in cmds[3],
       '[ "$p" = 0 ]' in cmds[4], "KNOWN" in "".join(cmds)], [True, True, True, True, True, False])

# ---- the root shell itself (a fake su that is a plain sh; POSIX only: Windows has no select() on pipes -- CI runs it) ----------
if os.name == "posix":
    rns = load()   # (its own namespace: the checks after this block use ns)
    rns["time"] = __import__("time")
    d = tempfile.mkdtemp()
    old_path = os.environ.get("PATH", "")
    try:
        open(os.path.join(d, "su"), "w").write("#!/bin/sh\necho started >> \"$(dirname \"$0\")/starts\"\nexec sh\n")
        os.chmod(os.path.join(d, "su"), 0o755)
        os.environ["PATH"] = d + os.pathsep + old_path
        rs = rns["RootShell"]()
        a = rs.run("echo hi; exit 0")
        p1 = rs.p
        b = rs.run(rns["LOOK_CMD"].replace("KNOWN", "0"))   # no game here: it prints nothing, and its exit ends only its subshell
        c = rs.run("echo two")
        check("root shell: output up to its end mark; `exit` in a command keeps the shell", (a, b, c, rs.p is p1), ("hi\n", "", "two\n", True))
        t = __import__("time").time()
        e = rs.run("sleep 5", timeout=0.5)
        check("root shell: a command past its timeout -> '' and the shell dropped, in time", (e, rs.p, __import__("time").time() - t < 3),
              ("", None, True))
        f = rs.run("echo back")
        rs.close()
        starts = open(os.path.join(d, "starts")).read().count("started")
        check("root shell: the next call starts a new one (two su in all)", (f, starts), ("back\n", 2))
    finally:
        os.environ["PATH"] = old_path
        shutil.rmtree(d, ignore_errors=True)
else:
    print("skip root shell: no select() on pipes on Windows (CI runs it on Linux)")
ns["WATCH"]["at"] = ns["time"].t - 30
check("watcher: a look older than 4 looks + 10 s is no look", ns["look_now"](), None)

# ---- the wait before an attach -------------------------------------------------------------------------------------------------
def run_wait(script, detached_ago=None, pause_at=None):
    """script = [(seconds, look output)]: each look holds from its time on. Returns (result, seconds waited, log, app lines)."""
    ns = load()
    t0 = ns["time"].t
    base = {} if detached_ago is None else {"detached_at": t0 - detached_ago}

    def feed(now):
        cur = [o for s, o in script if t0 + s <= now]
        ns["WATCH"]["look"], ns["WATCH"]["at"] = ns["parse_look"](cur[-1]), now
    feed(t0)
    ns["time"].on_sleep = feed
    if pause_at is not None:
        ns["paused_until"] = lambda: (ns["time"].t + 60) if ns["time"].t - t0 >= pause_at else 0
    r = ns["wait_attachable"](ns["w"], base)
    return r, ns["time"].t - t0, ns["log"], ns["states"]


r, dt, log, st = run_wait([(0, look_out())])
check("wait: on screen, never detached -> attach at once, nothing said", (r, dt, log, st), (True, 0, [], []))
r, dt, log, st = run_wait([(0, look_out())], detached_ago=3)
check("wait: back on screen 3 s after our detach -> the gap holds it to 8 s, nothing said", (r, dt, log, st), (True, 5, [], []))
r, dt, log, st = run_wait([(0, look_out(up=False, pid=None)), (5, look_out())])
check("wait: PoGo not open, then on screen -> the readers' 'waiting for PoGo...' line, then attaching",
      (r, dt, log, st), (True, 5, ["waiting for PoGo...", "Pokemon GO is on screen -- attaching"], ["PoGo is not open"]))
r, dt, log, st = run_wait([(0, look_out(code=False)), (4, look_out(top="com.whatsapp")), (200, look_out())])
check("wait: game code loading, then behind WhatsApp 196 s, then back", (r, dt), (True, 200))
check("wait: its log lines (a change, a 2-min heartbeat, the attach)", log,
      ["waiting: Pokemon GO is still loading its game code (no libil2cpp.so in its memory yet)",
       "waiting: com.whatsapp is on screen -- attaching once Pokemon GO is on screen",
       "still waiting: com.whatsapp is on screen -- attaching once Pokemon GO is on screen",
       "Pokemon GO is on screen -- attaching"])
check("wait: the app's line says why, and is rewritten every 30 s (the app calls 90 s 'not reporting')",
      (st[0], st[1], len(st), set(st[1:])),
      ("starting: Pokemon GO is still loading its game code",
       "paused: Pokemon GO is not on screen -- the catcher attaches again when you are back in the game", 8,
       {"paused: Pokemon GO is not on screen -- the catcher attaches again when you are back in the game"}))
r, dt, log, st = run_wait([(0, look_out(awake=False)), (10, look_out())])
check("wait: the screen off -> its own words", st, ["paused: the screen is off -- the catcher attaches again when you are back in the game"])
r, dt, log, st = run_wait([(0, look_out(adj=900))], pause_at=7)
check("wait: a pause requested while it waits -> it returns False to honour it", (r, dt), (False, 7))
r, dt, log, st = run_wait([(0, look_out(top="com.whatsapp")), (2, look_out(top="com.instagram.android")), (9, look_out())])
check("wait: another app, then another -> one line, not one per app", len([x for x in log if x.startswith("waiting")]), 1)
r, dt, log, st = run_wait([(0, look_out(top="com.whatsapp")), (3, look_out())], detached_ago=0)
check("wait: back 3 s after our detach -> attach at 8 s (the gap), the attach line said", (r, dt, log[-1]),
      (True, 8, "Pokemon GO is on screen -- attaching"))

# ---- failed attaches to one game process ----------------------------------------------------------------------------------------
ns = load()
fa, bad = ns["failed_attach"], {"pid": None, "n": 0}
seq = [fa(bad, p) for p in (100, 100, 200, 200, 200, None, 300)]
check("failed attaches: counted per game pid, a new pid starts again, no pid known = 0", seq, [1, 2, 1, 2, 3, 0, 1])


def run_hold(script, flip_at=None):
    ns = load()
    t0 = ns["time"].t
    mt = {"v": 1}
    ns["flag_mtime"] = lambda name: mt["v"]

    def feed(now):
        cur = [o for s, o in script if t0 + s <= now]
        ns["WATCH"]["look"], ns["WATCH"]["at"] = ns["parse_look"](cur[-1]), now
        if flip_at is not None and now - t0 >= flip_at:
            mt["v"] = 2
    feed(t0)
    ns["time"].on_sleep = feed
    ns["hold_bad_pid"](ns["w"], 18521, 3, RuntimeError("timeout was reached\nmore"))
    return ns["time"].t - t0, ns["log"], ns["states"]


dt, log, st = run_hold([(0, look_out()), (300, look_out(pid=19999))])
check("hold: no attach to that pid until the game is started again (new pid at 300 s)", dt, 300)
check("hold: its lines (the reason, heartbeats every 2 min, the new start)",
      (log[0], log[1], log[-1], len(log)),
      ("!!! cannot attach to this game start (3 tries failed) -- the catcher tries again when Pokemon GO is started again, "
       "or when you switch Catch off and on; last error: timeout was reached (game pid 18521)",
       "still not attaching to game pid 18521: it refused 3 attaches",
       "Pokemon GO was started again (game pid 18521 -> 19999) -- attaching again", 4))
check("hold: the app's line says so, every 30 s (at 0 s, then 30 .. 270 s)",
      (st[0].startswith("cannot attach to this game start"), len(st)), (True, 10))
dt, log, st = run_hold([(0, look_out()), (40, look_out(up=False, pid=None))])
check("hold: the game closed -> the hold ends (the next wait is for PoGo)", (dt, log[-1]),
      (40, "Pokemon GO was started again (game pid 18521 -> none) -- attaching again"))
dt, log, st = run_hold([(0, look_out())], flip_at=25)
check("hold: Catch switched in the app -> it tries this game start again", (dt, log[-1]),
      (25, "Catch was switched in the app -- trying this game start again"))

# ---- the wiring in catch_loop_fast.py -------------------------------------------------------------------------------------------
sl = re.search(r"^def session_loop\(.*?(?=^\n\ndef )", SRC, re.S | re.M).group(0)
mn = re.search(r"^def main\(.*?(?=^\n\nmain\(\))", SRC, re.S | re.M).group(0)
check("wiring: session_loop waits for the screen before anything attaches",
      sl.index("wait_attachable(w, base)") < sl.index("pg.get_session()"), True)
check("wiring: and looks again after the cold-start wait",
      sl.index("time.sleep(COLD_AGE_S - age)") < sl.index("if not attachable(look_now()):") < sl.index("pg.get_session()"), True)
check("wiring: the attached loop breaks its sleep and detaches when the game left the screen",
      ("if paused_until() or WATCH[\"off\"] >= OFF_LOOKS:" in sl,
       re.search(r'if WATCH\["off"\] >= OFF_LOOKS:.*?release\(sess\)\n\s+base\["detached_at"\] = time.time\(\)\n\s+return', sl, re.S) is not None),
      (True, True))
check("wiring: a link drop and a pause also stamp the detach (the re-attach gap)",
      (sl.count('base["detached_at"] = time.time()'), "gadget_up(" in SRC), (3, False))
check("wiring: main starts the watcher, counts failed attaches per pid, holds at ATTACH_TRIES",
      ("threading.Thread(target=watch_loop" in mn, "failed_attach(bad, (look_now() or {}).get(\"pid\"))" in mn,
       "if n >= ATTACH_TRIES:" in mn and "hold_bad_pid(w, bad[\"pid\"], n, e)" in mn,
       'if base.get("attached_at", 0) >= t_call:' in mn), (True, True, True, True))
check("wiring: ATTACH_TRIES = 3, OFF_LOOKS = 2, LOOK_S = 3, REATTACH_GAP_S = 8",
      (ns["ATTACH_TRIES"], ns["OFF_LOOKS"], ns["LOOK_S"], ns["REATTACH_GAP_S"]), (3, 2, 3, 8))

# ---- the log's date line --------------------------------------------------------------------------------------------------------
lg = {"os": os, "time": __import__("time")}
exec(re.search(r"^def now_s\(.*?(?=^\n\ndef )", SRC, re.S | re.M).group(0), lg)
exec(re.search(r"^class Log:.*?(?=^\n\ndef )", SRC, re.S | re.M).group(0), lg)
d = tempfile.mkdtemp()
try:
    p = os.path.join(d, "catch_loop.log")
    L = lg["Log"](p)
    L.__class__.__call__.__globals__["print"] = lambda *a, **k: None
    L("one")
    L("two")
    L.day = "2000-01-01"   # as if the day changed since the last line
    L("three")
    L.f.close()
    lines = open(p, encoding="utf-8").read().splitlines()
    today = __import__("time").strftime("%Y-%m-%d")
    check("log: a date line first, again at a new day; every line starts HH:MM:SS (the readers' parse)",
          ([x[9:] for x in lines], all(re.match(r"^\d\d:\d\d:\d\d ", x) for x in lines)),
          ([f"===== date {today} =====", "one", "two", f"===== date {today} =====", "three"], True))
finally:
    shutil.rmtree(d, ignore_errors=True)

# ---- run_catch.sh (bash, with su / kill / sleep faked) --------------------------------------------------------------------------
bash = shutil.which("bash") or "bash"
fns = "\n".join(re.search(rf"^{n}\(\) \{{.*?^\}}\n", RUN, re.S | re.M).group(0) for n in ("look", "on_screen", "queued", "end"))
fns += "\n" + re.search(r"^up\(\) \{.*$", RUN, re.M).group(0) + "\n"


def sh(body, look, alive_for=10**6, on_term_exit=False):
    """Run body with run_catch.sh's functions. look = what su prints; the fake catcher (pid 4242) dies after alive_for kill -0
    checks, or at its TERM when on_term_exit. Prints the kills, the su calls and the say lines."""
    d = tempfile.mkdtemp()
    try:
        lf = os.path.join(d, "look.txt")
        open(lf, "w", newline="\n").write(look)
        fwd = d.replace("\\", "/")   # (a Windows path: bash reads its backslashes as escapes)
        script = (f"LOOKF='{fwd}/look.txt'\nSUF='{fwd}/su.calls'\nALIVE={alive_for}\nTERMX={1 if on_term_exit else 0}\nN=0\nDEAD=0\n"
                  'su() { echo x >> "$SUF"; cat "$LOOKF"; }\n'   # (look() runs su in a subshell: count in a file)
                  'sleep() { :; }\n'
                  'say() { echo "SAY $*"; }\n'
                  'kill() { case "$1" in -TERM) echo "TERM $2"; [ "$TERMX" = 1 ] && DEAD=1; return 0 ;; -9) echo "KILL9 $2"; DEAD=1; return 0 ;;'
                  ' -0) [ "$DEAD" = 1 ] && return 1; N=$((N+1)); [ "$N" -gt "$ALIVE" ] && { DEAD=1; return 1; }; return 0 ;; esac; }\n'
                  + fns + body + '\necho "SU_CALLS $(cat "$SUF" 2>/dev/null | wc -l | tr -d \' \')"\n')
        sf = os.path.join(d, "t.sh")
        open(sf, "w", newline="\n").write(script)
        r = subprocess.run([bash, sf], capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).strip().splitlines()
    finally:
        shutil.rmtree(d, ignore_errors=True)


OUT = look_out().replace("pid=18521\nadj=0\nil2cpp=loaded\n", "")   # the supervisor's look has no pid lines
QUEUED = OUT.replace("00000000:00000000 00:00000000", "00000000:00000002 00:00000000", 1)
BEHIND = OUT.replace(GAME, "com.whatsapp")
DOWN = OUT.replace(TCP, "")
check("sh: look/up/on_screen/queued read the real lines",
      sh('look; up && echo UP; on_screen && echo SCREEN; queued && echo Q', OUT), ["UP", "SCREEN", "SU_CALLS 1"])
check("sh: a connection waiting in the accept queue is seen", sh('look; queued && echo Q', QUEUED), ["Q", "SU_CALLS 1"])
check("sh: behind another app / screen off = not on screen",
      (sh('look; on_screen || echo OFF', BEHIND), sh('look; on_screen || echo OFF', OUT.replace("Awake", "Asleep"))),
      (["OFF", "SU_CALLS 1"], ["OFF", "SU_CALLS 1"]))
check("sh: end(): the catcher exits at TERM -> no -9, no su", sh('end 4242', BEHIND, on_term_exit=True), ["TERM 4242", "SU_CALLS 0"])
check("sh: end(): it exits by itself 12 s after TERM -> no -9, no su", sh('end 4242', OUT, alive_for=12), ["TERM 4242", "SU_CALLS 0"])
r = sh('end 4242', BEHIND, alive_for=200)
check("sh: end(): stuck in a call behind another app -> never -9; a line a minute; it ends by itself",
      ([x for x in r if x.startswith(("KILL9", "TERM"))], len([x for x in r if x.startswith("SAY catcher still in a call")])),
      (["TERM 4242"], 3))
r = sh('end 4242', QUEUED, alive_for=200)
check("sh: end(): on screen but a connection waits on the gadget -> never -9", [x for x in r if x.startswith("KILL9")], [])
r = sh('end 4242', OUT)
check("sh: end(): stuck 30 s on screen, nothing waiting on the gadget -> -9 then",
      (r[:2], r[2].startswith("SAY catcher still alive 30s after TERM -> killed")), (["TERM 4242", "KILL9 4242"], True))
r = sh('end 4242', DOWN)
check("sh: end(): stuck and the game is gone -> -9 (nothing left to hurt)",
      (r[:2], r[2]), (["TERM 4242", "KILL9 4242"], "SAY catcher still alive 30s after TERM and the game is gone -> killed"))
loop = re.search(r"^while on; do.*^done\n", RUN, re.S | re.M).group(0)
check("sh: the silence rule looks first, and leaves a catcher behind other apps alone",
      (loop.index('[ "$age" -gt 240 ] || continue') < loop.index("look") < loop.index('if up && ! on_screen; then say "catcher silent')
       < loop.index('say "catcher silent ${age}s -> restarting it"; end "$pid"'),),
      (True,))
check("sh: no kill -9 left outside end()'s two guarded places (the old one fired after 3 s)",
      (len(re.findall(r'kill -9 "', RUN)), len(re.findall(r'kill -9 "', re.search(r"^end\(\) \{.*?^\}\n", RUN, re.S | re.M).group(0))),
       "for _ in 1 2 3 4 5 6 7 8 9 10 11 12" in RUN), (2, 2, False))
r = subprocess.run([bash, "-n", os.path.join(HERE, os.pardir, "run_catch.sh")], capture_output=True, text=True)
check("sh: run_catch.sh parses (bash -n)", (r.returncode, r.stderr.strip()), (0, ""))
check("sh: run_catch.sh has LF line ends (bash on the phone)", "\r" in RUN, False)

print(f"\n{'ALL OK' if not failed else f'{failed} FAILED'}")
sys.exit(1 if failed else 0)
