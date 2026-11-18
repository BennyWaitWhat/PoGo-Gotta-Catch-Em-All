"""Offline checks for the Gym Battle switch ON THE PHONE (Benny 2026-11-18: "why cant gym mode work without the PC? i want it
working on my phone"). No phone, no game, no Frida, no adb: fakes stand in for all of them.   python test_gym_phone.py

  1. on_phone.py -- which side this is (what is really there, POGO_ON_PHONE on top); the data folder; the ONE root shell
     (a real `sh` stands in for `su`): exact stdout, stderr dropped, a command can never read the shell's own input, one
     command at a time from many threads, a command without an answer is never sent twice.
  2. The PC path is unchanged: cutoff_hunt.adb builds the same adb call as before; on the phone the SAME command text goes
     to the root shell (the GPS fix, the joystick WALK). gym_run.py talks to the device through nothing else, and uses
     nothing of pogo_il2cpp that the phone's copy lacks.
  3. The attach on the phone: the /proc gate (cold start, too young, gadget not listening, process gone), the wait, the
     session through the local gadget BY PID -- same signatures as both pogo_il2cpp copies, whose bag walk is one code.
  4. gym_run.py imported the way the phone imports it (the phone's pogo_il2cpp, POGO_ON_PHONE=1): the swaps are in.
  5. --on-open and a stop that comes in before the runner ever attached (the switch went off while the game was closed);
     the wait for the game in 10 s slices; --switch, the switch file read by the runner itself (off = the inbox's stop).
     5b. --preflight with fakes: reads only, a clean unload, FAIL where a run could not work.
  6. run_gym.sh, read: run_catch.sh's shebang / environment / python pick / game_up, the exact command line (every option
     exists in gym_run.py, berries off, no roaming option), never a kill, never the game, never the joystick, never a
     write to the switch; a hangup never reaches the runner; every status text fits the app's line.
  7. run_gym.sh, RUN (bash + a fake gym_run.py in a temp folder): off at start; --preflight (also beside a live supervisor
     and beside Catch Rewards: refused); the game closed, then up; Catch Rewards running = no runner is started; ONE
     runner with the exact command line; the status line from the runner's own log, rewritten on time; a second copy
     leaves; switch off = a stop file in the inbox, the runner's own exit, "off"; the crash loop stops at three and
     starts afresh when the switch is set again; a runner that stopped because the switch was flipped is no crash; a stop
     taken back / written again / outlived; a runner that is not this switch's.
"""
import argparse
import ast
import contextlib
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types

if importlib.util.find_spec("frida") is None:                # CI / the offline sandbox: nothing here ever attaches
    sys.modules["frida"] = types.ModuleType("frida")
HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.dirname(HERE)                                    # AutoCatcher (the phone's ~/pogo)
sys.path.insert(0, HERE)
os.environ.pop("POGO_ON_PHONE", None)                        # (this process is the PC side; the phone side is forced per check)
import on_phone as op  # noqa: E402
import cutoff_hunt as ch  # noqa: E402
import gym_tapper  # noqa: E402
import gym_run  # noqa: E402
import gym_status  # noqa: E402

FAILS = []
PHONE_PG = os.path.join(AC, "ondevice_toggle", "phone_pogo_il2cpp.py")
LISTEN = ":69A7 00000000:0000 0A"                            # the gadget's LISTEN entry in /proc/net/tcp (port 27047)


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)
    return cond


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeShell:
    """Stands in for the phone's root shell: answers from a function, remembers what it was asked."""
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def run(self, cmd, timeout=None):
        self.asked.append(cmd)
        return self.answer(cmd)


@contextlib.contextmanager
def phone(answer=lambda cmd: ""):
    """This process as the phone: ON_PHONE on, a fake root shell in place."""
    was = op.ON_PHONE, op._SHELL
    op.ON_PHONE, op._SHELL = True, FakeShell(answer)
    try:
        yield op._SHELL
    finally:
        op.ON_PHONE, op._SHELL = was


# ------------------------------------------------------------------------------------------------ 1. on_phone.py
def side_checks():
    no, yes = (lambda p: False), (lambda p: p == op.TERMUX)
    check(op.detect({}, yes) is True and op.detect({}, no) is False, "the Termux prefix decides which side this is")
    check(op.detect({"POGO_ON_PHONE": "1"}, no) is True and op.detect({"POGO_ON_PHONE": "0"}, yes) is False, "POGO_ON_PHONE=1 / 0 overrides it")
    check(op.detect({"POGO_ON_PHONE": "yes"}, no) is False and op.detect({"POGO_ON_PHONE": ""}, yes) is True, "any other value of it is ignored")
    if not check(op.ON_PHONE is False, "this check runs on the PC side (no Termux here, POGO_ON_PHONE unset)"):
        return
    repo = os.path.dirname(AC)
    check(op.data_dir(HERE, "pogo_extract") == os.path.join(repo, "pogo_extract") == gym_run.GM_DIR, "PC: the game master folder is <repo>/pogo_extract, as before")
    check(os.path.dirname(gym_tapper.GM_PATH) == os.path.dirname(gym_tapper.FORM_ENUM_PATH) == gym_run.GM_DIR, "PC: the tapper's two game master files are in that folder, as before")
    with phone():
        check(op.data_dir(HERE, "pogo_extract") == os.path.join(AC, "pogo_extract"), "phone: the game master folder is inside ~/pogo (pogo/pogo_extract)")
    print("ok: which side this is, and where the data folder is on each")


def shell_checks():
    sh = shutil.which("sh")
    if not sh:
        print("  (no sh on this machine: the root shell's protocol was not run)")
        return
    rs = op.RootShell([sh], timeout=20)
    try:
        check(rs.run("echo hi") == "hi\n" and rs.run("printf abc") == "abc" and rs.run("true") == "", "a command's stdout comes back exactly (with or without a last newline, or none)")
        first = rs.p.pid
        check(rs.run("echo a; echo b 1>&2; echo c") == "a\nc\n", "stderr is dropped, as adb's is on the PC")
        check(rs.run("cat") == "" and rs.run("echo next") == "next\n", "a command that reads its input gets nothing -- it can never swallow the next command")
        line = "      last mock location=Location[gps 51.500000,-0.120000 hAcc=1.0 et=+1d2h3m4s5ms vel=2.0]"
        check(rs.run("echo '%s' | grep -m1 'last mock location'" % line) == line + "\n", "a piped command with quotes comes back whole")
        check(rs.run("echo one; echo; echo three") == "one\n\nthree\n", "empty lines inside the output are kept")
        got = {}
        ts = [threading.Thread(target=lambda i=i: got.__setitem__(i, rs.run("echo %d" % i))) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        check(got == {i: "%d\n" % i for i in range(30)}, "30 threads: every caller gets its own command's answer")
        check(rs.p.pid == first, "all of that ran in ONE shell (one su request for the runner's life)")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slow = rs.run("sleep 4; echo late", timeout=0.5)
            back = rs.run("echo back")
        check(slow == "" and back == "back\n" and rs.p.pid != first, "no answer in time: '' now, a fresh shell for the next command")
        check(buf.getvalue().count("!! phone root shell") == 1 and re.match(r"\d\d:\d\d:\d\d   !! phone root shell: ", buf.getvalue()),
              "...said once, in the runner's own log format: " + repr(buf.getvalue()))
        with contextlib.redirect_stdout(io.StringIO()):
            gone = rs.run("exit 7")
        check(gone == "" and rs.run("echo again") == "again\n", "a shell that closed mid-command: '' and a fresh one, never the same command twice")
        p = rs.p
        rs.close()
        check(p.poll() is not None and rs.p is None, "close() ends the shell")
    finally:
        rs.close()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        none = op.RootShell([os.path.join(HERE, "no_such_su")]).run("echo x")
    check(none == "" and "!! phone root shell" in buf.getvalue(), "no su at all: '' and one line that says so -- never an exception into the runner")
    src = read(os.path.join(HERE, "on_phone.py"))
    check('"LD_LIBRARY_PATH", "LD_PRELOAD"' in src, "the root shell never inherits Termux's library path")
    print("ok: the phone's root shell (protocol run against sh)")


# ------------------------------------------------------------------------------------------------ 2. one device function
def device_checks():
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return types.SimpleNamespace(stdout="from adb")
    real, ch.subprocess.run = ch.subprocess.run, fake_run
    try:
        out = ch.adb("getprop ro.product.model")
        argv, kw = calls[-1]
        check(out == "from adb" and argv == ["adb", "-s", ch.DEV, "shell", "getprop ro.product.model"], "PC: adb -s <phone> shell <cmd>, as before")
        check(kw.get("capture_output") is True and kw.get("text") is True and kw.get("encoding") == "utf-8" and kw.get("errors") == "replace"
              and kw.get("env", {}).get("MSYS_NO_PATHCONV") == "1" and set(kw) == {"capture_output", "text", "encoding", "errors", "env"},
              "PC: the same subprocess options as before")
        ch.api("WALK", '--es waypoints "1.0,2.0;3.0,4.0" --ef speed 10.4')
        pc_walk = calls[-1][0][4]
        n = len(calls)
        fix_line = "      last mock location=Location[gps 51.500000,-0.120000 hAcc=1.0 et=+1d2h3m4s5ms vel=2.0]\n"
        with phone(lambda cmd: fix_line if "last mock location" in cmd else "") as fs:
            check(ch.adb("getprop ro.product.model") == "" and fs.asked == ["getprop ro.product.model"], "phone: the same command text goes to the root shell")
            f = ch.fix()
            check(fs.asked[-1] == "dumpsys location | grep -m1 'last mock location'" and f is not None and f[:2] == (51.5, -0.12)
                  and abs(f[2] - (86400 + 2 * 3600 + 3 * 60 + 4.005)) < 1e-6 and abs(f[3] - 7.2) < 1e-9, "phone: the joystick's GPS fix is read the same way: %r" % (f,))
            ch.api("WALK", '--es waypoints "1.0,2.0;3.0,4.0" --ef speed 10.4')
            check(fs.asked[-1] == pc_walk == 'am start-foreground-service -a theappninjas.gpsjoystick.WALK --es waypoints "1.0,2.0;3.0,4.0" --ef speed 10.4',
                  "phone: the joystick WALK is the same command text as on the PC")
        check(len(calls) == n, "phone: adb is never started")
    finally:
        ch.subprocess.run = real
    cs = read(os.path.join(HERE, "cutoff_hunt.py"))
    check(cs.count('"adb"') == 1 and 'return subprocess.run(["adb", "-s", DEV, "shell", cmd], capture_output=True, text=True, encoding="utf-8",\n'
          '                          errors="replace", env=dict(os.environ, MSYS_NO_PATHCONV="1")).stdout or ""' in cs,
          "cutoff_hunt.py: one adb call, the statement it always was")
    gs = read(os.path.join(HERE, "gym_run.py")).replace("\r\n", "\n")
    check(gs.count('["adb"') == 1 and 'subprocess.run(op.SCREENCAP if op.ON_PHONE else ["adb", "-s", os.environ.get("ADB_TARGET", ch.DEV), "exec-out", "screencap", "-p"],' in gs,
          "gym_run.py: its one direct adb call (the screenshot) has the phone's form beside it")
    check(op.SCREENCAP == ["su", "-c", "screencap -p"] and "subprocess" not in re.sub(r"subprocess\.run\(op\.SCREENCAP[^\n]*", "", gs.split("import frida", 1)[1]),
          "gym_run.py: no other process is started by the runner (every device command is cutoff_hunt's)")
    used = set(re.findall(r"\bpg\.([A-Za-z_]+)", gs))
    check(used == {"walk_bag_protos", "wait_ready_to_attach", "get_session", "busy_acquire"}, "gym_run.py uses four names of pogo_il2cpp: %s" % sorted(used))
    check(re.findall(r"\bpg\.busy_acquire\b(?! = lambda)", gs) == [] and len(re.findall(r"\bpg\.busy_acquire = lambda", gs)) == 2,
          "...and pg.busy_acquire is only ASSIGNED (the phone's copy has none: nothing calls it)")
    for mod in ("gym_tapper.py", "live_graph_js.py", "dump_game_limits.py"):
        ms = read(os.path.join(HERE, mod))
        top = "\n".join(x for x in ms.split("\n") if x.startswith(("import ", "from ")))
        check("subprocess" not in top and "frida" not in top, "%s starts no process and imports no Frida of its own" % mod)
    print("ok: one device function -- adb on the PC as before, the root shell on the phone")


# ------------------------------------------------------------------------------------------------ 3. the attach
class FakeTime:
    def __init__(self):
        self.t, self.naps = 1000.0, []

    def time(self):
        return self.t

    def sleep(self, s):
        self.naps.append(s)
        self.t += s

    def strftime(self, *a):
        return time.strftime(*a)


def gate(mapped="1", start="123456", up="5000.00", hz="100", listen="L1", pid="1392"):
    def answer(cmd):
        if cmd.startswith("pidof "):
            return pid + "\n" if pid else ""
        if "/maps" in cmd:
            return "".join(x + "\n" for x in (mapped, start, up, hz, listen) if x is not None)
        return ""
    return answer


class FakeFrida(types.ModuleType):
    def __init__(self, attach=None, add_fails=False):
        super().__init__("frida")
        self.log, self._attach, self._add_fails = [], attach or (lambda pid: "SESSION"), add_fails

    def get_device_manager(self):
        me = self

        class Dev:
            id, name = "socket@127.0.0.1:27047", "127.0.0.1:27047"

            def attach(self, target):
                me.log.append(("attach", target))
                return me._attach(target)

        class DM:
            def add_remote_device(self, addr):
                me.log.append(("add", addr))
                if me._add_fails:
                    raise RuntimeError("already added")
                return Dev()

            def enumerate_devices(self):
                me.log.append(("enumerate",))
                return [types.SimpleNamespace(id="local", name="Local System"), Dev()]
        return DM()


def attach_checks():
    pc, ph = load(os.path.join(AC, "pogo_il2cpp.py"), "_pg_pc"), load(PHONE_PG, "_pg_phone")
    for fn in ("wait_ready_to_attach", "get_session"):
        a, b, c = (str(inspect.signature(getattr(m, fn))) for m in (pc, ph, op))
        check(a == b == c, "%s%s: one signature on the PC, in the phone's copy and in on_phone (%s / %s / %s)" % (fn, a, a, b, c))
    check(inspect.getsource(pc.walk_bag_protos) == inspect.getsource(ph.walk_bag_protos), "walk_bag_protos is the same code in both pogo_il2cpp copies")
    cut = lambda js: js[js.index("function _bag_walk_core"):js.index("rpc.exports = {")]
    check(cut(pc.JS_PREAMBLE) == cut(ph.JS_PREAMBLE) and "stopWorld()" not in cut(ph.JS_PREAMBLE), "...and so is the in-game bag walk it calls (no stopped world in it)")
    check(hasattr(pc, "busy_acquire") and not hasattr(ph, "busy_acquire"), "the desktop marker (busy_acquire) is the PC copy's only: the phone's has none")
    was = op.PKG, op.GADGET, op.NOT_READY, sys.modules.get("frida"), op.time
    try:
        op.install(ph)
        check(ph.wait_ready_to_attach is op.wait_ready_to_attach and ph.get_session is op.get_session, "install(): the phone's pogo_il2cpp gets the two functions that need no adb")
        check(op.GADGET == ph.FRIDA_REMOTE == "127.0.0.1:27047" and op.PKG == ph.POGO_PKG and op.NOT_READY is ph.NotReadyToAttach, "...on its own gadget address, package and NotReadyToAttach")
        with phone(gate()) as fs:
            check(op.pidof() == 1392 and fs.asked == ["pidof com.nianticlabs.pokemongo"], "pidof: the game's pid from the root shell")
            ok, why = op.ready_to_attach(1392)
            check(ok and "ready" in why and LISTEN in fs.asked[-1] and "/proc/1392/maps" in fs.asked[-1] and "/proc/1392/stat" in fs.asked[-1],
                  "the gate reads /proc only (il2cpp mapped, age, the gadget's LISTEN entry): %s" % why)
        for name, g, want in (("cold start", gate(mapped="0"), "not yet mapped"), ("45 s rule", gate(start="498000"), "only 20s old"),
                              ("gadget", gate(listen="L0"), "gadget is not listening"), ("gadget unread", gate(listen="L"), "gadget is not listening"),
                              ("process gone", gate(mapped=None), "/proc read failed"), ("odd /proc", gate(start="abc"), "non-numeric"),
                              ("nothing", lambda cmd: "", "/proc read failed")):
            with phone(g):
                ok, why = op.ready_to_attach(1392)
                check(ok is False and want in why, "the gate refuses (%s): %s" % (name, why))
        for out, want in (("1392\n", 1392), ("", None), ("1392 1400\n", None), ("x\n", None)):
            with phone(lambda cmd, out=out: out):
                check(op.pidof() == want, "pidof %r -> %r" % (out, want))
        op.time = ft = FakeTime()
        seq = iter(["", "", "1392\n"])
        with phone(lambda cmd: next(seq) if cmd.startswith("pidof ") else gate()(cmd)):
            check(op.wait_ready_to_attach(timeout_s=60) == 1392 and ft.naps == [5, 5], "wait_ready_to_attach: polls every 5 s, returns the ready pid")
        op.time = ft = FakeTime()
        with phone(gate(pid="")):
            try:
                op.wait_ready_to_attach(timeout_s=30)
                check(False, "wait_ready_to_attach must raise when the game never comes")
            except RuntimeError as e:
                check(str(e) == "PoGo never became attach-safe in 30s (no pid yet)" and sum(ft.naps) == 30, "wait_ready_to_attach: RuntimeError when the time is up (%s)" % e)
        op.time = was[4]
        sys.modules["frida"] = ff = FakeFrida()
        with phone(gate()):
            check(op.get_session() == ("SESSION", 1392) and ff.log == [("add", "127.0.0.1:27047"), ("attach", 1392)],
                  "get_session: (session, pid) through the local gadget, attached BY PID (the pid that passed the gate): %r" % (ff.log,))
        sys.modules["frida"] = ff = FakeFrida(add_fails=True)
        with phone(gate()):
            check(op.get_session() == ("SESSION", 1392) and ("enumerate",) in ff.log, "get_session: a gadget added before (a re-attach) is found again")
        sys.modules["frida"] = ff = FakeFrida()
        with phone(gate(pid="")):
            try:
                op.get_session()
                check(False, "get_session must raise when the game is not running")
            except RuntimeError as e:
                check("PoGo not running" in str(e) and ff.log == [], "get_session: no game = RuntimeError, nothing touched")
        with phone(gate(start="498000")):
            try:
                op.get_session()
                check(False, "get_session must refuse a cold game")
            except ph.NotReadyToAttach as e:
                check("init storm" in str(e) and ff.log == [], "get_session: a game that is not attach-safe is NEVER attached (NotReadyToAttach): %s" % e)
        with phone(gate(start="498000")):
            check(op.get_session(allow_cold=True) == ("SESSION", 1392), "get_session(allow_cold=True) skips the gate, as the PC's does")

        def boom(pid):
            raise ValueError("unable to find process with pid 1392")
        sys.modules["frida"] = FakeFrida(attach=boom)
        with phone(gate()):
            try:
                op.get_session()
                check(False, "get_session must raise when the attach fails")
            except RuntimeError as e:
                check("unable to find process with pid 1392" in str(e), "get_session: a failed attach = RuntimeError (the runner's own loop retries): %s" % e)
    finally:
        op.PKG, op.GADGET, op.NOT_READY, op.time = was[0], was[1], was[2], was[4]
        if was[3] is None:
            sys.modules.pop("frida", None)
        else:
            sys.modules["frida"] = was[3]
    print("ok: the attach on the phone (gate, wait, session by pid through the local gadget)")


# ------------------------------------------------------------------------------------------------ 4. imported as the phone does
def import_checks():
    code = r'''
import importlib.util, json, os, sys, types
if importlib.util.find_spec("frida") is None:
    sys.modules["frida"] = types.ModuleType("frida")
here, phone_pg = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("pogo_il2cpp", phone_pg)      # ~/pogo/pogo_il2cpp.py IS this file on the phone
pg = importlib.util.module_from_spec(spec); sys.modules["pogo_il2cpp"] = pg; spec.loader.exec_module(pg)
sys.path.insert(0, here)
import on_phone as op, gym_run, gym_tapper, cutoff_hunt
asked = []
op._SHELL = types.SimpleNamespace(run=lambda cmd, timeout=None: asked.append(cmd) or "")
cutoff_hunt.adb("input keyevent 4")
print(json.dumps({"on": op.ON_PHONE, "same_pg": gym_run.pg is pg, "wait": pg.wait_ready_to_attach is op.wait_ready_to_attach,
                  "sess": pg.get_session is op.get_session, "gm": gym_run.GM_DIR, "gm_path": gym_tapper.GM_PATH, "enum": gym_tapper.FORM_ENUM_PATH,
                  "asked": asked, "busy": hasattr(pg, "busy_acquire"), "cool": gym_run.COOL_OBS, "dd": gym_run.DD["path"]}))
'''
    r = subprocess.run([sys.executable, "-c", code, HERE, PHONE_PG], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, POGO_ON_PHONE="1", PYTHONIOENCODING="utf-8"))
    if not check(r.returncode == 0 and r.stdout.strip(), "gym_run.py imports with the phone's pogo_il2cpp and POGO_ON_PHONE=1: " + r.stderr[-600:]):
        return
    d = json.loads(r.stdout.strip().splitlines()[-1])
    gm = os.path.join(AC, "pogo_extract")
    check(d["on"] is True and d["same_pg"] and d["wait"] and d["sess"], "phone import: the phone's pogo_il2cpp got on_phone's wait + session")
    check(d["gm"] == gm and d["gm_path"] == os.path.join(gm, "gamemaster_pokeminers.json") and d["enum"] == os.path.join(gm, "form_enum.json"),
          "phone import: the runner AND the tapper read the game master from pogo/pogo_extract")
    check(d["asked"] == ["input keyevent 4"] and d["busy"] is False, "phone import: device commands go to the root shell; no busy marker function is needed")
    state = os.path.join(HERE, "gym_state")
    check(os.path.dirname(d["cool"]) == os.path.dirname(d["dd"]) == state, "phone import: the runner's state files stay under tools/gym_state (pogo/tools/gym_state)")
    print("ok: gym_run.py imported the way the phone imports it")


# ------------------------------------------------------------------------------------------------ 5. a stop before the first attach
class Attach(Exception):
    """The fake get_session: the runner got as far as attaching."""


def stop_checks():
    saved = gym_run.pg.wait_ready_to_attach, gym_run.pg.get_session, getattr(gym_run.pg, "busy_acquire", None)
    late = RuntimeError("PoGo never became attach-safe in 10s (no pid yet)")

    def stop_file(inbox, name="1794000000000_app-switch.json"):
        os.makedirs(inbox, exist_ok=True)
        with open(os.path.join(inbox, name), "w", encoding="utf-8") as f:
            f.write('{"stop": true}\n')
        return os.path.join(inbox, name)

    def reset():
        gym_run.ATTACHED[0], gym_run.STOP_ASKED[0], gym_run.ONOPEN_BOOT[0] = 0, False, False
        gym_run.SWITCH[0], gym_run.SWITCH[1] = None, 0.0

    def go(a, during=None, script=()):
        """One run() with fakes. script: what each wait for the game does in turn (an exception is raised, anything else
        returns); after the script every wait finds the game. -> (the waits' time-outs, attached?, printed, what run() raised)"""
        waits, todo = [], list(script)

        def wait(timeout_s=240, min_age_s=45):
            waits.append((timeout_s, min_age_s))
            if during:
                during(len(waits))
            x = todo.pop(0) if todo else None
            if isinstance(x, Exception):
                raise x
            return 1392

        def sess():
            raise Attach()
        gym_run.pg.wait_ready_to_attach, gym_run.pg.get_session = wait, sess
        buf, attached, err = io.StringIO(), False, None
        with contextlib.redirect_stdout(buf):
            try:
                gym_run.run(a, None, None, {}, 0.0, [1, 3], [0.0, 0.0])
            except Attach:
                attached = True
            except RuntimeError as e:
                err = e
        return [w[0] for w in waits], attached, buf.getvalue(), err
    clock = gym_run.time
    try:
        with tempfile.TemporaryDirectory() as td:
            inbox = os.path.join(td, "runner_inbox")
            a = argparse.Namespace(cmd=os.path.join(td, "runner_cmd.json"), on_open=True)
            reset()
            old = stop_file(inbox)
            w, att, out, _e = go(a)
            check(w == [10] and att and not os.path.exists(old) and "COMMAND stop" not in out,
                  "--on-open, process start: a stop from BEFORE this process is thrown away, the runner waits and attaches")
            new = stop_file(inbox)
            w, att, out, _e = go(a)
            check(w == [] and not att and not os.path.exists(new) and "COMMAND stop: it came in before the runner ever attached -- not attaching; stopped" in out,
                  "--on-open, still not attached: a stop that came in since ends the wait -- no attach just to stop: " + out.strip())
            w, att, out, _e = go(a, during=lambda n: stop_file(inbox))
            check(w == [10] and not att and os.listdir(inbox) == [] and "COMMAND stop: it came in while the runner waited for the game" in out,
                  "--on-open: a stop that comes in DURING the wait for the game is taken when the wait ends -- no attach")
            check(gym_status.status_from_log(["12:00:00 lost the game connection (x) -- re-attaching in 3 s"] + out.strip().splitlines()) == "stopping",
                  "...and the app's line says 'stopping' for it")

            # the wait for the game, in slices (the game is closed: the wait times out again and again)
            reset()
            w, att, out, e = go(a, script=[late, late])
            check(w == [10, 10, 10] and att and e is None, "--on-open waits for the game in 10 s slices and attaches when it is up: %s" % w)
            reset()
            w, att, out, e = go(a, script=[late] * 9, during=lambda n: stop_file(inbox) if n == 3 else None)
            check(w == [10, 10, 10] and not att and e is None and os.listdir(inbox) == [] and "COMMAND stop: it came in while the runner waited for the game" in out,
                  "...a stop that comes in while the game is closed ends the wait at the next slice (not after five minutes), no attach: %s" % w)
            reset()
            w, att, out, e = go(a, script=[RuntimeError("No ADB device reachable.")] * 3)
            check(w == [10] and not att and str(e) == "No ADB device reachable.", "...any other error of the wait leaves at once, as it always did (no loop on it)")
            reset()
            gym_run.time = ft = FakeTime()
            w, att, out, e = go(a, script=[late] * 99, during=lambda n: ft.sleep(10))
            gym_run.time = clock
            check(len(w) == 30 and not att and e is late, "...and after five minutes of slices the time-out leaves as before (%d slices)" % len(w))

            # --switch: the runner reads the app's switch itself
            sw = os.path.join(td, "pogo_gym.on")

            def flip(v):
                if v is None:
                    if os.path.exists(sw):
                        os.remove(sw)
                else:
                    with open(sw, "w", newline="\n") as f:
                        f.write(v)
                gym_run.SWITCH[1] = 0.0                      # (the once-a-second limit: let the next look read the file)
            t0 = time.time()
            flip("1\n")
            check(gym_run.switch_off(sw) is False and time.time() - t0 < 0.25, "switch_off: a file that holds 1 is ON, on the first read")
            for v, what in (("0\n", "0"), ("", "an empty file"), ("11\n", "another value"), (None, "no file at all")):
                flip(v)
                check(gym_run.switch_off(sw, gap=0.01) is True, "switch_off: %s is OFF" % what)
            flip("")

            def later():                                     # (the app's write lands between the two reads)
                time.sleep(0.05)
                with open(sw, "w") as f:
                    f.write("1\n")
            th = threading.Thread(target=later)
            th.start()
            check(gym_run.switch_off(sw, gap=0.3) is False, "switch_off: one empty read between the app's truncate and its write is not OFF (two reads, 0.3 s apart)")
            th.join()
            reset()
            flip("0\n")
            check(gym_run.switch_stop() is False and gym_run.STOP_ASKED[0] is False, "switch_stop: without --switch the file is never asked (every PC run)")
            gym_run.SWITCH[0] = sw
            flip("1\n")
            check(gym_run.switch_stop() is False and gym_run.STOP_ASKED[0] is False, "switch_stop: the switch is on -- nothing")
            flip("0\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                first, again = gym_run.switch_stop(), gym_run.switch_stop()
            check(first is True and again is False and gym_run.STOP_ASKED[0] is True and buf.getvalue().count("the Gym Battle switch is off") == 1,
                  "switch_stop: the switch is off -- True once, said once, and the stop is remembered across a lost connection")
            reset()
            gym_run.SWITCH[0] = sw
            flip("0\n")
            gym_run.SWITCH[1] = time.time()
            check(gym_run.switch_stop() is False and gym_run.STOP_ASKED[0] is False, "switch_stop: the file is read at most once a second")
            reset()
            gym_run.SWITCH[0] = sw
            flip("0\n")
            w, att, out, e = go(a)
            check(w == [] and not att and e is None and "the Gym Battle switch is off" in out and "COMMAND stop" in out,
                  "--on-open --switch, the switch is off when the runner starts: no wait, no attach: " + " | ".join(out.strip().splitlines()))
            check(gym_status.status_from_log(["12:00:00   ON-OPEN mode (x)"] + out.strip().splitlines()) == "stopping", "...and the app's line says 'stopping'")
            reset()
            gym_run.SWITCH[0] = sw
            flip("1\n")
            w, att, out, e = go(a, script=[late] * 9, during=lambda n: flip("0\n") if n == 2 else None)
            check(w == [10, 10] and not att and e is None and "the Gym Battle switch is off" in out,
                  "--on-open --switch: the switch goes off while the game is closed -- the wait ends at the next slice, no attach: %s" % w)
            reset()
            gym_run.SWITCH[0] = sw
            flip("1\n")
            w, att, out, e = go(a)
            check(w == [10] and att and "switch" not in out, "--on-open --switch, the switch is on: the runner attaches")
            gym_run.ATTACHED[0] = 1                          # a lost connection later, the switch went off meanwhile
            flip("0\n")
            w, att, out, e = go(a)
            check(w == [] and not att and "COMMAND stop: it was asked before / while the game connection was down -- not attaching again; stopped" in out,
                  "--on-open --switch: the switch went off while the game connection was lost -- no re-attach")

            reset()
            a.on_open = False
            kept = stop_file(inbox)
            flip("0\n")
            w, att, out, e = go(a)
            check(w == [300] and att and os.path.exists(kept) and "COMMAND stop" not in out and gym_run.ONOPEN_BOOT[0] is False,
                  "normal mode, first attach: ONE 300 s wait, run() does not look at the inbox, as before (the session start discards an old stop)")
            w, att, out, e = go(a, script=[RuntimeError("PoGo never became attach-safe in 300s (no pid yet)")])
            check(w == [300] and not att and e is not None, "normal mode: the wait's time-out leaves at once, as before (no slices)")
    finally:
        gym_run.time = clock
        gym_run.pg.wait_ready_to_attach, gym_run.pg.get_session = saved[0], saved[1]
        if saved[2] is not None:
            gym_run.pg.busy_acquire = saved[2]
        reset()
    gs = read(os.path.join(HERE, "gym_run.py")).replace("\r\n", "\n")
    check(re.search(r'os\.path\.getmtime\(_p\) > 300 or \(json\.load\(open\(_p, encoding="utf-8"\)\)\.get\("stop"\)\s+and not a\.on_open\)\)', gs),
          "--on-open: a stop found at the session start is taken, not discarded (run() threw the old ones away); other modes discard it as before")
    check("    SWITCH[0] = a.switch if a.on_open else None" in gs and gs.count("SWITCH[0] = ") == 1,
          "--switch counts only with --on-open: no other run ever reads a switch file")
    pull = gs[gs.index("    def pull():"):gs.index("    def quick_cmds():")]
    check(re.search(r'def pull\(\):[^\n]*\n        if switch_stop\(\):[^\n]*\n            cmdq\.append\(\{"stop": True\}\)\n', pull),
          "inside a session the switch is asked where every command comes in (pull): off = one stop in the queue, the inbox stop's own path")
    check("    return found or switch_stop()" in gs, "...and outside a session wherever a stop is waited for (stop_waiting)")
    check("_later = bool(batch) and a.on_open and target is None" in gs and re.search(r"if _later:[^\n]*\n\s+batch = \[\]", gs)
          and "refresh=batch_check" in gs, "--on-open: no revive batch while the runner only waits (no item is used with no gym of yours open); the drill's own batch stays")
    fn = next(n for n in ast.parse(gs).body if isinstance(n, ast.FunctionDef) and n.name == "preflight")
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    check(not used & {"switch_stop", "switch_off", "stop_waiting", "SWITCH", "switch"}, "--preflight never asks the switch (run_gym.sh --preflight shows its value, nothing more)")
    print("ok: --on-open -- a stop before the first attach, the wait for the game in slices, the switch read by the runner itself")


# ------------------------------------------------------------------------------------------------ 5b. --preflight
LOOK_ONLY = {"install", "feedcfg", "where", "pickname", "bag", "teams", "quiesce"}     # every tapper call a preflight may make


class Exports:
    def __init__(self, owner):
        self._o = owner

    def __getattr__(self, name):
        def call(*args):
            self._o.calls.append((name, args))
            return self._o.answers[name](*args)
        return call


class FakeScript:
    def __init__(self, answers):
        self.calls, self.answers, self.loaded, self.unloaded, self.exports_sync = [], answers, False, False, Exports(self)

    def on(self, event, fn):
        pass

    def load(self):
        self.loaded = True

    def unload(self):
        self.unloaded = True


class FakeSession:
    def __init__(self, tapper, bag):
        self.tapper, self.bag, self.detached = tapper, bag, False

    def create_script(self, js):
        return self.tapper if js is gym_tapper.JS else self.bag

    def detach(self):
        self.detached = True


def preflight_checks():
    names = "Mewtwo Rayquaza Dialga Palkia Groudon Kyogre Metagross Garchomp Salamence Dragonite Tyranitar Machamp".split()
    roster = [[str(1000 + i), 4500 - 20 * i, 200, 200, names[i % len(names)], 1 if i >= 20 else 0] for i in range(26)]
    MAP = "MapExploreState"
    GYM = "MapExploreState > GymRootState > GymState > GymApproachState"

    def look(install=None, where=MAP, gy=((["101", 3643, 180, 180]), (["102", 3640, 0, 180])), wait=None, session=None):
        inst = {"ok": True, "gyms": 18, "range": 80.0, "autoplace": True, "pickName": "caxt", "pickWhy": "the one handler of this shape",
                "pickNames": ["caxt"], "team": True, "feed": True, "graph": {"graphs": 1, "ts": time.time() * 1000 - 4000}, "graphNotes": []}
        inst.update(install or {})
        tap = FakeScript({"install": lambda: dict(inst), "feedcfg": lambda *a: {}, "pickname": lambda n: {"ok": True}, "bag": lambda: "0xbag",
                          "where": lambda: {"chain": where, "leaf": where.split(" > ")[-1], "top": "none", "inBattle": False, "prepOpen": False},
                          "teams": lambda: {"aaaaaaaa1111": [1, 500, 51.5005, -0.12, 0, 3, 0, 9000, 0, 0, 1],
                                            "bbbbbbbb2222": [2, 400, 51.51, -0.12, 60000, -1, 0, 0, 0, 0, 0]},
                          "quiesce": lambda: True})
        bag = FakeScript({"scan": lambda ptrs: {"dep": 14, "gy": [list(x) for x in gy], "ro": [list(x) for x in roster], "dp": [],
                                                "fa": [["102", 3640, "Gyarados"]], "comp": []}})
        sess = FakeSession(tap, bag)
        api, asked = [], []

        def adb(cmd):
            asked.append(cmd)
            return "2000\n" if cmd == "id -u" else "\n1794000000\n"

        def get():
            if session:
                raise session
            return sess, 1392

        def ready(timeout_s=240, min_age_s=45):
            if wait:
                raise wait
            return 1392
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "gym_state", "runner_inbox"))
            a = argparse.Namespace(cmd=os.path.join(td, "gym_state", "runner_cmd.json"), study=None, on_open=True, feed_at=0.34, feed_hot=0.67, max_deployed=20)
            was = (gym_run.pg.wait_ready_to_attach, gym_run.pg.get_session, gym_run.pg.walk_bag_protos, getattr(gym_run.pg, "busy_acquire", None),
                   gym_run.ch.adb, gym_run.ch.fix, gym_run.ch.api, gym_run.COOL_OBS, gym_run.time)
            gym_run.pg.wait_ready_to_attach, gym_run.pg.get_session, gym_run.pg.walk_bag_protos = ready, get, (lambda s, live: {"1": "0x1", "2": "0x2"})
            gym_run.ch.adb, gym_run.ch.fix, gym_run.ch.api = adb, (lambda: (51.5, -0.12, 1.0, 0.0)), (lambda *x: api.append(x))
            gym_run.COOL_OBS = os.path.join(td, "gym_state", "cooldown_obs.jsonl")
            gym_run.time = types.SimpleNamespace(time=time.time, sleep=lambda s: None, strftime=time.strftime)
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rc = gym_run.preflight(a)
            finally:
                (gym_run.pg.wait_ready_to_attach, gym_run.pg.get_session, gym_run.pg.walk_bag_protos, _b,
                 gym_run.ch.adb, gym_run.ch.fix, gym_run.ch.api, gym_run.COOL_OBS, gym_run.time) = was
                if was[3] is not None:
                    gym_run.pg.busy_acquire = was[3]
        return rc, buf.getvalue(), tap, sess, api, asked

    rc, out, tap, sess, api, asked = look()
    called = [c[0] for c in tap.calls]
    lines = [x for x in out.splitlines() if x[:5] in ("PASS ", "FAIL ", "WARN ", "SKIP ")]
    check(rc == 0 and out.strip().splitlines()[-1].startswith("PREFLIGHT runner: PASS -- ") and not [x for x in lines if x.startswith("FAIL")],
          "--preflight, all well: exit code 0, no FAIL line: " + " / ".join(x for x in lines if x.startswith("FAIL")))
    check(set(called) <= LOOK_ONLY and called[:2] == ["install", "feedcfg"] and ("feedcfg", (False, 0.34, 0.67, False)) in tap.calls,
          "--preflight: the tapper is asked only to install, read and go quiet; berries are switched OFF right after install: %s" % called)
    check(api == [] and all(c == "id -u" or c.startswith(("cat /data/local/tmp/pogo_desktop_busy", "su -c 'echo")) for c in asked),
          "--preflight: nothing goes to the joystick, no key or tap to the phone (device commands: %s)" % sorted(set(c.split()[0] for c in asked)))
    check(tap.loaded and tap.unloaded and sess.detached and called[-1] == "quiesce", "--preflight ends like a run: quiet, unload, detach")
    for want in ("PASS  tapper: every class and field it needs was read live; fort range 80 m; 18 gyms in the game's map directory",
                 "PASS  screen: MapExploreState (top: none)", "PASS  auto-place: ON -- place handler caxt",
                 "PASS  bag: 14/20 of yours in gyms; shiny Gyarados at full HP and at home: 1 (CP 3643); 1 fainted",
                 "PASS  your six: Mewtwo 4500, Rayquaza 4480, Dialga 4460, Palkia 4440, Groudon 4420, Kyogre 4400",
                 "PASS  gyms on the map: 2 read live; nearest: aaaaaaaa team 1, 56 m, 3 free; bbbbbbbb team 2, 1112 m, raid",
                 "PASS  joystick: GPS Joystick is spoofing (51.5000,-0.1200)", "PASS  attach: a Frida session to pid 1392",
                 "PASS  unload: the tapper is unloaded and the session detached"):
        check(any(x.startswith(want) for x in lines), "--preflight says: " + want)
    rc, out, tap, sess, api, _ = look(where=GYM)
    called = [c[0] for c in tap.calls]
    check(rc == 0 and "teams" not in called and called.index("quiesce") < called.index("bag") and "SKIP  gyms on the map" in out and "silenced at once" in out,
          "--preflight with YOUR gym screen up: the tapper is silenced at once, the map read is skipped: %s" % called)
    rc, out, tap, sess, api, _ = look(install={"ok": False, "missing": ["class Niantic.Holoholo.Gym.GymState"]})
    check(rc == 1 and "FAIL  tapper: these could not be read live in this game version" in out and [c[0] for c in tap.calls] == ["install", "feedcfg", "quiesce"]
          and tap.unloaded and sess.detached, "--preflight, a game version the tapper cannot read: FAIL, exit code 1, still a clean unload")
    rc, out, tap, sess, api, _ = look(install={"autoplace": False, "pickNames": [], "pickName": None})
    check(rc == 1 and "FAIL  auto-place: OFF -- an emptied gym would wait for YOUR hand" in out, "--preflight, no place handler: FAIL (the Gyarados would not go in by itself)")
    rc, out, tap, sess, api, _ = look(gy=(["101", 3643, 0, 180],))
    check(rc == 0 and "WARN  placement: no shiny Gyarados at full HP: these go in instead -- " in out and "shiny Gyarados at full HP and at home: 0;" in out,
          "--preflight, no Gyarados at full HP: a WARN that names the fallback (your highest-CP shinies)")
    rc, out, tap, sess, api, _ = look(session=RuntimeError("frida attach timed out on the phone's own gadget (127.0.0.1:27047)"))
    check(rc == 1 and "FAIL  attach: RuntimeError: frida attach timed out" in out and "SKIP  tapper, bag, gyms" in out and tap.calls == [] and not tap.loaded,
          "--preflight, no session: FAIL, nothing is loaded")
    rc, out, tap, sess, api, _ = look(wait=RuntimeError("PoGo never became attach-safe in 20s (no pid yet)"))
    check(rc == 1 and "FAIL  game: PoGo never became attach-safe in 20s (no pid yet)" in out and tap.calls == [] and "  attach:" not in out,
          "--preflight, the game is closed: FAIL, no attach is tried")
    gs = read(os.path.join(HERE, "gym_run.py")).replace("\r\n", "\n")
    tree = ast.parse(gs)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "preflight")
    used = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "exports_sync"}
    check(used <= LOOK_ONLY - {"bag"} and "install" in used, "preflight(), read from gym_run.py: its tapper calls are %s -- no open, act, autodeploy, roster, scan, fastreport, topup, directdeploy" % sorted(used))
    attrs = {(n.value.id, n.attr) for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    check(not {a for a in attrs if a[0] == "mv" or a == ("ch", "api")} and {a[1] for a in attrs if a[0] == "ch"} == {"adb", "fix", "meters"}
          and [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("input ")] == []
          and "OBO_OK_TAP" not in ast.unparse(fn), "preflight(): no joystick command, no key, no tap (cutoff_hunt is used for id -u, the fix and a distance only)")
    src = ast.unparse(fn)
    check("feedcfg(False, a.feed_at, a.feed_hot, False)" in src and "refresh_deployed" not in src and "roster(" not in src,
          "preflight(): berries off by a constant, no roster is handed over (so nothing is healed or revived)")
    main_src = gs[gs.index("def main():"):gs.index("def gym_open(")]
    check(re.search(r"a = ap\.parse_args\(\)\n(?:.*\n){0,3}?    if a\.preflight:.*\n        sys\.exit\(preflight\(a\)\)\n", main_src) and '"--preflight"' in main_src,
          "--preflight leaves main() before anything else runs")
    check(re.search(r"phone_mark\(False\)[^\n]*\n    if a\.on_open:[^\n]*\n        sc\.exports_sync\.feedcfg\(a\.feed, a\.feed_at, a\.feed_hot, a\.feed_mate\)", gs),
          "--on-open: the switch's berry options reach the tapper right after install (its own default is ON)")
    print("ok: --preflight (a look with fakes: reads only, a clean unload, FAIL where a run could not work)")


# ------------------------------------------------------------------------------------------------ 6. run_gym.sh, read
def code_lines(sh):
    return [ln.split(" # ")[0] for ln in sh.split("\n") if not ln.lstrip().startswith("#")]


def pre_of(sh):
    """run_gym.sh's preflight() function, as text."""
    return sh[sh.index("\npreflight() {"):sh.index('\nif [ "${1:-}" = --preflight ]')]


def script_checks():
    sh, cat = read(os.path.join(AC, "run_gym.sh")), read(os.path.join(AC, "run_catch.sh"))
    check("\r" not in sh and sh.endswith("\n"), "run_gym.sh has LF line ends (Android's shell chokes on CRLF)")
    for what, pat in (("shebang", r"^#!.*$"), ("PREFIX", r"^export PREFIX=.*$"), ("HOME", r"^export HOME=.*$"), ("LD_LIBRARY_PATH", r"^export LD_LIBRARY_PATH=.*$"),
                      ("PATH", r"^export PATH=.*$"), ("the newest python3.N", r"^for p in .*python3.*$"), ("game_up()", r"^game_up\(\) .*$")):
        a, b = re.search(pat, sh, re.M), re.search(pat, cat, re.M)
        check(a and b and a.group(0) == b.group(0), "run_gym.sh: %s is run_catch.sh's, to the letter" % what)
    check(LISTEN in sh and "export POGO_ON_PHONE=1" in sh, "run_gym.sh: the game is 'up' by its gadget's LISTEN entry (never a connect); the runner is told it is on the phone")
    code = code_lines(sh)
    joined = "\n".join(code)
    m = re.search(r'exec "\$PY" -u (tools/gym_run\.py[^\n]*\\\n[^\n]*?) >> "\$LOG" 2>&1', joined)
    if check(m, "run_gym.sh starts the runner with `exec \"$PY\" -u tools/gym_run.py ... >> \"$LOG\" 2>&1`"):
        args = m.group(1).replace("\\\n", " ").split()
        check(args == ["tools/gym_run.py", "--on-open", "--no-feed", "--no-feed-mate", "--no-topup", "--switch", '"$FLAG"', "--cmd", '"$S/runner_cmd.json"',
                       "--minutes", "100000", "$(extra)"], "the runner's command line: %s" % " ".join(args))
        known = set(re.findall(r'add_argument\("(--[a-z-]+)"', read(os.path.join(HERE, "gym_run.py"))))
        opts = [x for x in args if x.startswith("--")]
        check(all(x in known for x in opts), "every option on it exists in gym_run.py: %s" % [x for x in opts if x not in known])
        check(not {"--topup", "--direct-deploy", "--route", "--goal", "--hop", "--home", "--join-first", "--study", "--adopt", "--area"} & set(opts),
              "no berries, no direct deploy, no roaming option on it")
        check("#       python -u tools/gym_run.py --on-open --no-feed --no-feed-mate --no-topup --switch /data/local/tmp/pogo_gym.on \\\n"
              "#           --cmd tools/gym_state/runner_cmd.json --minutes 100000\n" in sh and "\nFLAG=/data/local/tmp/pogo_gym.on\n" in sh,
              "the header comment shows the same command line")
        start = joined[joined.rindex("\n", 0, m.start()) + 1:m.start()]
        check(re.fullmatch(r"\s*\( set -f; trap '' HUP; cd \"\$P\" && ", start), "the runner is started with the hangup signal ignored (a terminal that goes away never kills an attached runner): %r" % start)
    check("\ntrap 'exit 0' TERM INT\ntrap '' HUP " in sh and "\n  trap '' HUP PIPE " in pre_of(sh),
          "the supervisor outlives its terminal too; --preflight ignores a hangup and a closed output (its attach half is never cut off mid-look)")
    kills = [ln for ln in code if re.search(r"\b(kill|pkill|killall)\b", ln)]
    check(kills and all(re.search(r"\bkill -0 ", ln) and not re.search(r"\bkill -[^0]|\bpkill\b|\bkillall\b", ln) for ln in kills),
          "run_gym.sh never kills anything: its only kill is `kill -0` (is it alive?) -- %d line(s)" % len(kills))
    check(not re.search(r"\bam (start|force-stop|broadcast)|\bmonkey\b|gpsjoystick|\binput (tap|keyevent|swipe)|\bpm \b", joined),
          "run_gym.sh never starts, stops or taps the game, and sends the joystick nothing")
    uses = re.findall(r'[^\n;{(]*\$FLAG[^\n;)]*', joined)
    check(not re.search(r'>\s*"?\$FLAG', joined) and len(uses) == 4
          and all(re.search(r'< "\$FLAG"|date -r "\$FLAG"|\[ -r "\$FLAG" \]|--switch "\$FLAG"', u) for u in uses),
          "run_gym.sh only READS the switch (its content, its time, is it there) and names it to the runner: %s" % uses)
    check('  case "$c" in *--preflight*) return 1 ;; *--on-open*) return 0 ;; esac\n' in sh,
          "a runner is this switch's by --on-open on its command line; a look-only --preflight is never adopted")
    check("\nrewards_alive() { ps -ef 2>/dev/null | grep -q '[r]eward_phone\\.py'; }\n" in sh
          and '\n  if rewards_alive; then status "waiting: Catch Rewards is running"; return; fi\n' in sh
          and '  elif rewards_alive; then\n    no "Catch Rewards is running' in pre_of(sh),
          "no runner is started, and no preflight attaches, while Catch Rewards (reward_phone.py) is running")
    check(re.search(r'^on\(\) \{ \[ "\$\(flag\)" = 1 \] \|\| \{ sleep 0\.3; \[ "\$\(flag\)" = 1 \]; \}; \}$', sh, re.M),
          "the switch is OFF only when it does not hold 1 on two reads (one read can land inside the app's write)")
    pre = pre_of(sh)
    check(not re.search(r'>\s*"?\$(STATUS|FLAG)|\bstatus "|\bmkstatus\b|\btake_lock\b|\$LOCK|\bsend_stop\b|\bstart_runner\b|run_gym\.child|--switch', pre)
          and "--on-open --preflight --no-feed --no-feed-mate --no-topup" in pre and 'if [ -n "$o" ]; then\n    no "a gym runner is alive' in pre
          and '  elif sup_alive; then\n    no "the switch\'s supervisor is running' in pre,
          "run_gym.sh --preflight: no write to the switch or the status line, no lock, no runner started or stopped; never beside a live runner or supervisor")
    texts = re.findall(r'status "([^"]*)"', joined)
    lit = [x for x in texts if "$" not in x]
    check(len(lit) >= 6 and all(len(x) <= gym_status.TEXT_MAX and x == gym_status.clean(x) for x in lit),
          "every fixed status text fits the app's line and needs no cleaning: %s" % [x for x in lit if len(x) > gym_status.TEXT_MAX or x != gym_status.clean(x)])
    worst = ["STOPPED: tools/gym_run.py is not on the phone -- ask Claude", "STOPPED: pogo/tools/gym_state cannot be written -- ask Claude",
             "STOPPED: the gym runner quit 3 times in a row -- flip the switch off and on", "STOPPED: the runner stopped itself: a party screen stayed open over a battle"]
    check(all(len(x) <= gym_status.TEXT_MAX for x in worst), "...and so does every STOPPED line: %s" % [x for x in worst if len(x) > gym_status.TEXT_MAX])
    check("the gym runner quit $quick times in a row -- flip the switch off and on" in sh and 'ready="tools/gym_run.py is not on the phone"' in sh
          and 'ready="pogo/tools/gym_state cannot be written"' in sh, "(those texts are the script's)")
    print("ok: run_gym.sh, read (environment, command line, never a kill / the game / the joystick / the switch)")


# ------------------------------------------------------------------------------------------------ 7. run_gym.sh, RUN
FAKE = r'''
import json, os, sys, time
td = os.environ["GYM_FAKE_DIR"]
mode = lambda: open(os.path.join(td, "mode")).read().strip()
say = lambda s: print(time.strftime("%H:%M:%S"), s, flush=True)
inbox = os.path.join(os.path.dirname(sys.argv[sys.argv.index("--cmd") + 1]), "runner_inbox")
if "--preflight" in sys.argv:                 # the look-only half of run_gym.sh --preflight
    with open(os.path.join(td, "preflight_argv.json"), "w") as f:
        json.dump(sys.argv, f)
    print("PASS  attach: a fake session")
    print("PREFLIGHT runner: %s" % ("FAIL" if mode() == "quit" else "PASS"), flush=True)
    sys.exit(1 if mode() == "quit" else 0)
with open(os.path.join(td, "started.log"), "a") as f:
    f.write(json.dumps({"pid": os.getpid(), "argv": sys.argv, "cwd": os.getcwd(), "on_phone": os.environ.get("POGO_ON_PHONE"),
                        "unbuffered": bool(getattr(sys.stdout, "write_through", False))}) + "\n")
say("  ON-OPEN mode (the AutoCatcher app's Gym Battle switch): a fake runner")
if mode() == "quit":
    sys.exit(3)
if mode() == "crash":
    raise RuntimeError("a fake crash")
say("attached pid 1: 3 gyms on the game's map directory")
say("  your Pokemon in gyms right now: 14/20; shiny Gyarados ready to place (CP): 3643")
say("  ON-OPEN: watching for a gym you open")
while not os.path.exists(os.path.join(td, "die")):
    if mode() == "selfstop" and os.path.exists(os.path.join(td, "go")):   # as if it had read the switch off by itself
        os.remove(os.path.join(td, "go"))
        say("  the Gym Battle switch is off (the runner read the switch file itself; no stop had come through the inbox): the same as a stop command")
        say("  COMMAND stop: no battle in progress -- stopped cleanly; the tapper unloads and the session detaches now")
        sys.exit(0)
    if mode() not in ("deaf", "selfstop"):
        for n in sorted(os.listdir(inbox)):
            if n.endswith(".json") and not n.startswith("."):
                c = json.load(open(os.path.join(inbox, n)))
                os.remove(os.path.join(inbox, n))
                if c.get("stop"):
                    if mode() == "slow":
                        time.sleep(2.5)
                    say("  COMMAND stop: no battle in progress -- stopped cleanly; the tapper unloads and the session detaches now")
                    sys.exit(0)
    time.sleep(0.1)
'''


class Phone:
    """A temp folder that stands in for the phone: ~/pogo with a fake gym_run.py, the switch, the status file, 'the game'."""
    def __init__(self, td, bash, deployed=True):
        ux = lambda p: p.replace("\\", "/")
        self.td, self.bash, self.procs = td, bash, []
        self.pogo, self.flag, self.status_f = os.path.join(td, "pogo"), os.path.join(td, "flag"), os.path.join(td, "status.txt")
        self.state = os.path.join(self.pogo, "tools", "gym_state")
        self.inbox = os.path.join(self.state, "runner_inbox")
        os.makedirs(os.path.join(self.pogo, "tools"))
        if deployed:
            with open(os.path.join(self.pogo, "tools", "gym_run.py"), "w", encoding="utf-8") as f:
                f.write(FAKE)
            shutil.copy(os.path.join(HERE, "gym_status.py"), os.path.join(self.pogo, "tools", "gym_status.py"))
            for n in ("run_gym.sh", "pogo_il2cpp.py", "tools/gym_tapper.py", "tools/live_graph_js.py", "tools/dump_game_limits.py",
                      "tools/cutoff_hunt.py", "tools/on_phone.py"):      # (only their presence is looked at, by --preflight)
                open(os.path.join(self.pogo, n), "w").close()
        self.mode("run")
        self.switch("0")
        open(self.status_f, "w").close()                     # (on the phone root made it; Termux only writes into it)
        self.env = os.path.join(td, "env.sh")
        with open(self.env, "w", encoding="utf-8", newline="\n") as f:
            f.write('export PATH="$GYM_TEST_PATH"\nexport GYM_FAKE_DIR="%s"\nP="%s"; FLAG="%s"; STATUS="%s"; PY="%s"\n'
                    'POLL=0.2; EVERY=2; STOP_AGAIN=2; STOP_GIVE_UP=30; GAP=0; GAME_EVERY=0; LOCK_WAIT=2\n'
                    'game_up() { [ -e "%s/game_up" ]; }\nmkstatus() { return 1; }\nroot_id() { echo 0; }\n'
                    'rewards_alive() { [ -e "%s/rewards" ]; }\n'
                    % (ux(td), ux(self.pogo), ux(self.flag), ux(self.status_f), ux(sys.executable), ux(td), ux(td)))

    def mode(self, m):
        with open(os.path.join(self.td, "mode.new"), "w") as f:
            f.write(m)
        os.replace(os.path.join(self.td, "mode.new"), os.path.join(self.td, "mode"))

    def switch(self, v):
        with open(self.flag, "w", newline="\n") as f:
            f.write(v + "\n")

    def go(self):
        open(os.path.join(self.td, "go"), "w").close()       # (mode selfstop: the runner now stops by itself)

    def rewards(self, up):
        p = os.path.join(self.td, "rewards")                 # (stands in for a live reward_phone.py: Catch Rewards)
        if up:
            open(p, "w").close()
        elif os.path.exists(p):
            os.remove(p)

    def game(self, up):
        p = os.path.join(self.td, "game_up")
        if up:
            open(p, "w").close()
        elif os.path.exists(p):
            os.remove(p)

    def preflight(self):
        """run_gym.sh --preflight, to its end -> (exit code, what it printed)."""
        script = os.path.join(AC, "run_gym.sh").replace("\\", "/")
        r = subprocess.run([self.bash, "-c", 'export GYM_TEST_PATH="$PATH"; exec bash "$0" --preflight', script], capture_output=True, text=True,
                           timeout=120, env=dict(os.environ, GYM_TEST_ENV=self.env.replace("\\", "/")), stdin=subprocess.DEVNULL)
        self.stderr = r.stderr
        return r.returncode, r.stdout.replace("\r\n", "\n")

    def supervisor(self):
        script = os.path.join(AC, "run_gym.sh").replace("\\", "/")
        out = open(os.path.join(self.td, "supervisor_%d.out" % len(self.procs)), "wb")
        p = subprocess.Popen([self.bash, "-c", 'export GYM_TEST_PATH="$PATH"; exec bash "$0"', script],
                             env=dict(os.environ, GYM_TEST_ENV=self.env.replace("\\", "/")), stdin=subprocess.DEVNULL,
                             stdout=out, stderr=subprocess.STDOUT)
        out.close()
        self.procs.append(p)
        return p

    def printed(self):
        txt = ""
        for i in range(len(self.procs)):
            try:
                txt += read(os.path.join(self.td, "supervisor_%d.out" % i))
            except OSError:
                pass
        return txt

    def status(self):
        try:
            return read(self.status_f).rstrip("\r\n")
        except OSError:
            return ""

    def text(self):
        return self.status()[9:]

    def started(self):
        try:
            return [json.loads(x) for x in read(os.path.join(self.td, "started.log")).splitlines() if x.strip()]
        except OSError:
            return []

    def stops(self):
        try:
            return sorted(n for n in os.listdir(self.inbox) if n.endswith("_app-switch.json") and not n.startswith("."))   # (as the runner reads it)
        except OSError:
            return []

    def log(self):
        try:
            return read(os.path.join(self.state, "run_gym.log"))
        except OSError:
            return ""

    def wait(self, cond, what, timeout=25.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return check(False, "%s -- not within %.0f s (status %r; runners started %d; supervisor log: %s; it printed: %s)"
                     % (what, timeout, self.status(), len(self.started()), self.log()[-700:].replace("\n", " | "),
                        self.printed()[-400:].replace("\n", " | ")))

    def gone(self, p, what, timeout=25.0):
        self.wait(lambda: p.poll() is not None, what, timeout)
        return p.poll()

    def close(self):
        open(os.path.join(self.td, "die"), "w").close()      # the fakes leave by themselves (the supervisor is never asked to kill one)
        self.switch("0")
        end = time.time() + 6
        while time.time() < end and any(p.poll() is None for p in self.procs):
            time.sleep(0.1)
        for p in self.procs:
            if p.poll() is None:
                p.terminate()                                # (a test's own bash, stuck: never a runner)
        end = time.time() + 6                                # no fake may outlive its phone: the next one's `ps` would see it
        while time.time() < end and any(alive(s["pid"]) for s in self.started()):
            time.sleep(0.1)


@contextlib.contextmanager
def phone_dir(bash, **k):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        ph = Phone(td, bash, **k)
        try:
            yield ph
        finally:
            ph.close()


def alive(pid):
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def supervisor_checks():
    bash = shutil.which("bash")
    if not bash:
        print("  (no bash on this machine: run_gym.sh was read, not run)")
        return
    same = lambda a, b: os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
    line = re.compile(r"^\d\d:\d\d:\d\d \S.*$")

    # --- the switch is off when it starts (and a lock a dead copy left behind does not stop it): one "off", nothing started
    with phone_dir(bash) as ph:
        os.makedirs(os.path.join(ph.state, "run_gym.lock"))
        with open(os.path.join(ph.state, "run_gym.lock", "pid"), "w") as f:
            f.write("999999\n")
        ph.game(True)
        rc = ph.gone(ph.supervisor(), "switch off at the start: the supervisor leaves by itself")
        check(rc == 0 and ph.text() == "off" and line.match(ph.status()) and ph.started() == [], "switch off at the start: 'HH:MM:SS off', no runner (%r)" % ph.status())
        check(not os.path.exists(os.path.join(ph.state, "run_gym.lock")), "...and its lock is gone when it leaves")

    # --- the files are not on the phone: STOPPED says so for as long as the switch is on
    with phone_dir(bash, deployed=False) as ph:
        ph.switch("1")
        ph.game(True)
        p = ph.supervisor()
        ph.wait(lambda: ph.text() == "STOPPED: tools/gym_run.py is not on the phone -- ask Claude", "a phone without tools/gym_run.py: STOPPED says so")
        ph.switch("0")
        check(ph.gone(p, "...and it leaves when the switch goes off") == 0 and ph.text() == "off", "...and 'off' is its last line")

    # --- run_gym.sh --preflight: PASS / FAIL lines, the look-only runner half, and NOTHING of the switch is touched
    with phone_dir(bash) as ph:
        ph.switch("1")
        ph.game(True)
        with open(ph.status_f, "w", newline="\n") as f:
            f.write("12:00:00 a line from before\n")
        before = (read(ph.flag), read(ph.status_f), os.path.getmtime(ph.flag), os.path.getmtime(ph.status_f))
        rc, out = ph.preflight()
        ls = out.splitlines()
        check(rc == 0 and ls and ls[-1] == "PREFLIGHT PASS" and not [x for x in ls if x.startswith("FAIL")],
              "run_gym.sh --preflight, all well: exit code 0, 'PREFLIGHT PASS' last: %s (stderr: %s)" % ([x for x in ls if not x.startswith("PASS")], ph.stderr[-300:]))
        for want in ("PASS  python: Python 3.", "PASS  file tools/gym_run.py (", "PASS  file pogo_il2cpp.py (0 bytes)", "PASS  folder tools/gym_state: this user can write it",
                     "PASS  switch file: readable, it holds '1' (left as it is)", "PASS  status file: writable (left as it is)", "PASS  root: su answers",
                     "PASS  game: its gadget is listening (port 27047)", "PASS  attach: a fake session", "PREFLIGHT runner: PASS"):
            check(any(x.startswith(want) for x in ls), "run_gym.sh --preflight says: " + want)
        check(re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d Gym Battle switch preflight \(read-only\)$", ls[0] if ls else ""), "...under a dated first line")
        try:
            av = json.loads(read(os.path.join(ph.td, "preflight_argv.json")))
        except (OSError, ValueError):
            av = []
        check(len(av) == 8 and av[:7] == ["tools/gym_run.py", "--on-open", "--preflight", "--no-feed", "--no-feed-mate", "--no-topup", "--cmd"]
              and same(av[7], os.path.join(ph.state, "runner_cmd.json")), "its runner half is gym_run.py --on-open --preflight, berries off: %s" % av)
        known = set(re.findall(r'add_argument\("(--[a-z-]+)"', read(os.path.join(HERE, "gym_run.py"))))
        check(all(x in known for x in av if x.startswith("--")), "...every option of it exists in gym_run.py")
        check(read(os.path.join(ph.state, "preflight.log")).replace("\r\n", "\n") == out, "the same lines are kept in gym_state/preflight.log")
        check(before == (read(ph.flag), read(ph.status_f), os.path.getmtime(ph.flag), os.path.getmtime(ph.status_f)), "--preflight leaves the switch and the status line exactly as they were")
        check(ph.started() == [] and ph.stops() == [] and not os.path.exists(os.path.join(ph.state, "run_gym.lock")) and not os.path.exists(os.path.join(ph.state, "run_gym.child"))
              and os.listdir(os.path.join(ph.state, "logs")) == [], "...starts no runner, sends no stop, takes no lock")
        check(len(ls) > 1 and ls[-2].startswith("NOTE  the switch is ON and no supervisor is running"),
              "the switch is ON and no supervisor is alive (a flip during the check starts none): its last line but one says so")
        ph.mode("quit")
        rc, out = ph.preflight()
        check(rc == 1 and "FAIL  gym_run.py --preflight ended with exit code 1" in out and out.splitlines()[-1] == "PREFLIGHT FAIL (1)", "a runner half that fails: FAIL, exit code 1")
        ph.game(False)
        ph.switch("0")
        if os.path.exists(os.path.join(ph.td, "preflight_argv.json")):   # (missing = the checks above already said why)
            os.remove(os.path.join(ph.td, "preflight_argv.json"))
        os.remove(os.path.join(ph.pogo, "tools", "on_phone.py"))
        rc, out = ph.preflight()
        check(rc == 1 and "FAIL  game: not running" in out and "FAIL  file tools/on_phone.py is not in " in out and "SKIP  the attach checks" in out
              and out.splitlines()[-1] == "PREFLIGHT FAIL (2)" and not os.path.exists(os.path.join(ph.td, "preflight_argv.json")),
              "the game closed and a file missing: two FAIL lines, the attach half is not run at all")
        check("NOTE" not in out and "PASS  switch file: readable, it holds '0' (left as it is)" in out, "...and with the switch off there is no note")

    # --- run_gym.sh --preflight beside a live supervisor: the attach half is refused (the supervisor starts a runner when it likes)
    with phone_dir(bash) as ph:
        ph.switch("1")
        p = ph.supervisor()
        ph.wait(lambda: ph.text() == "the game is closed -- the runner attaches when you open it", "a supervisor is up (the game closed)")
        rc, out = ph.preflight()
        check(rc == 1 and "FAIL  the switch's supervisor is running" in out and "NOTE" not in out and not os.path.exists(os.path.join(ph.td, "preflight_argv.json"))
              and p.poll() is None and os.path.isdir(os.path.join(ph.state, "run_gym.lock")),
              "--preflight beside a live supervisor: FAIL, no attach half, the supervisor and its lock untouched: %s" % [x for x in out.splitlines() if not x.startswith("PASS")])
        ph.switch("0")
        check(ph.gone(p, "...which leaves when the switch goes off") == 0 and ph.text() == "off", "...and 'off' is its last line")
        ph.game(True)
        ph.rewards(True)
        rc, out = ph.preflight()
        check(rc == 1 and "FAIL  Catch Rewards is running" in out and out.splitlines()[-1] == "PREFLIGHT FAIL (1)"
              and not os.path.exists(os.path.join(ph.td, "preflight_argv.json")), "--preflight while Catch Rewards runs: FAIL, no attach half beside it")
        ph.rewards(False)

    # --- the main path: game closed -> up -> ONE runner, the exact command line -> status from its log -> off = a stop file
    with phone_dir(bash) as ph:
        ph.switch("1")
        p = ph.supervisor()
        ph.wait(lambda: ph.text() == "the game is closed -- the runner attaches when you open it", "switch on, game closed: said so")
        time.sleep(1.0)
        check(ph.started() == [] and p.poll() is None, "switch on, game closed: nothing is started, the supervisor waits")
        ph.rewards(True)
        ph.game(True)
        ph.wait(lambda: ph.text() == "waiting: Catch Rewards is running", "the game is up but Catch Rewards is running: the line says so")
        time.sleep(1.0)
        check(ph.started() == [] and p.poll() is None, "...and no runner is started beside the reward catcher")
        ph.rewards(False)
        ph.wait(lambda: len(ph.started()) == 1, "Catch Rewards is done, the game is up: a runner is started")
        s = (ph.started() or [{}])[0]
        want = ["tools/gym_run.py", "--on-open", "--no-feed", "--no-feed-mate", "--no-topup", "--switch", "<switch>", "--cmd", "<cmd>", "--minutes", "100000"]
        av = list(s.get("argv") or [])
        cmd_ok = len(av) == 11 and same(av[6], ph.flag) and same(av[8], os.path.join(ph.state, "runner_cmd.json"))
        check(cmd_ok and av[:6] + ["<switch>", av[7], "<cmd>"] + av[9:] == want, "the runner's command line, exactly (the switch file is named to it): %s" % av)
        check(same(s.get("cwd", ""), ph.pogo) and s.get("on_phone") == "1" and s.get("unbuffered") is True, "...run from ~/pogo with -u and POGO_ON_PHONE=1")
        ph.wait(lambda: ph.text() == "watching for a gym you open | 14/20 in gyms", "the status line comes from the runner's own log (gym_status.py)")
        check(line.match(ph.status()) and len(ph.status()) <= 90, "the status line is 'HH:MM:SS text', at most 90 characters: %r" % ph.status())
        first = ph.status()
        ph.wait(lambda: ph.status() != first, "the same status is written again within EVERY (2 s here, 15 s on the phone)", 8)
        check(ph.text() == "watching for a gym you open | 14/20 in gyms", "...same text, a new time")
        p2 = ph.supervisor()
        check(ph.gone(p2, "a second copy leaves by itself (the lock)", 15) == 0 and p.poll() is None and len(ph.started()) == 1, "started twice: the second copy leaves, still ONE runner")
        logs = os.listdir(os.path.join(ph.state, "logs"))
        check(len(logs) == 1 and re.fullmatch(r"onopen_\d{4}_\d{6}\.log", logs[0]), "the runner's log is gym_state/logs/onopen_MMDD_HHMMSS.log: %s" % logs)
        ph.mode("deaf")
        time.sleep(0.3)
        ph.switch("0")
        ph.wait(lambda: len(ph.stops()) == 1, "switch off: ONE stop file in the runner's inbox")
        stop = os.path.join(ph.inbox, ph.stops()[0]) if ph.stops() else None
        if check(stop is not None and read(stop) == '{"stop": true}\n' and not [n for n in os.listdir(ph.inbox) if n.startswith(".")]
                 and re.fullmatch(r"\d{13}_app-switch\.json", os.path.basename(stop)), "...the file gym_send.sh would write (%s)" % (stop and os.path.basename(stop))):
            with tempfile.TemporaryDirectory() as t2:
                shutil.copy(stop, t2)
                gym_run.STOP_ASKED[0] = False
                check(gym_run.stop_waiting(t2) is True and os.listdir(t2) == [], "...and gym_run's own reader takes it")
                gym_run.STOP_ASKED[0] = False
        ph.wait(lambda: ph.text().startswith("stopping: "), "switch off, runner still busy: the line says 'stopping'")
        check(alive(s.get("pid", 0)) and p.poll() is None, "...and nothing is killed: the runner is alive, the supervisor waits for it")
        ph.mode("run")
        rc = ph.gone(p, "the runner takes the stop and exits; then the supervisor leaves")
        check(rc == 0 and ph.text() == "off" and not alive(s.get("pid", 0)) and len(ph.started()) == 1, "switch off: the runner's own exit, then 'off' (%r)" % ph.status())
        check(ph.stops() == [] and not os.path.exists(os.path.join(ph.state, "run_gym.lock")) and not os.path.exists(os.path.join(ph.state, "run_gym.child")),
              "...no stop left in the inbox, no lock, no child note")
        check("it was asked to stop" in ph.log() and "STOPPED" not in ph.log(), "...and its own log says the runner was asked to stop")
        runlog = read(os.path.join(ph.state, "logs", logs[0])) if logs else ""
        check("COMMAND stop: no battle in progress -- stopped cleanly" in runlog, "...which the runner's log confirms")

    # --- the crash loop: three runs that each end at once = STOPPED, no fourth; the switch set again = a fresh try
    with phone_dir(bash) as ph:
        ph.mode("quit")
        ph.switch("1")
        ph.game(True)
        p = ph.supervisor()
        ph.wait(lambda: ph.text() == "STOPPED: the gym runner quit 3 times in a row -- flip the switch off and on", "three runs that end at once: STOPPED")
        time.sleep(1.5)
        check(len(ph.started()) == 3 and p.poll() is None, "...after exactly three starts, and it stays there (%d starts)" % len(ph.started()))
        ph.mode("crash")
        time.sleep(1.1)                                      # (the switch file's time is read in whole seconds)
        ph.switch("1")
        ph.wait(lambda: len(ph.started()) == 6 and ph.text() == "STOPPED: the gym runner crashed -- ask Claude",
                "the switch set again: three fresh tries; a crash is named from the runner's log")
        ph.mode("run")
        time.sleep(1.1)
        ph.switch("1")
        ph.wait(lambda: len(ph.started()) == 7 and ph.text().startswith("watching for a gym you open"), "set again with a runner that works: it runs")
        ph.switch("0")
        check(ph.gone(p, "...and switch off ends it") == 0 and ph.text() == "off", "...and 'off' is the last line")

    # --- the runner reads the switch itself (--switch): it can stop before the supervisor ever saw the switch off. The switch
    #     was written during that run = he flipped it: never a "quit". No write during the run = three of them are a STOPPED.
    with phone_dir(bash) as ph:
        ph.mode("selfstop")
        ph.switch("1")
        ph.game(True)
        p = ph.supervisor()
        for i in (1, 2, 3):
            ph.wait(lambda: len(ph.started()) == i and ph.text().startswith("watching"), "run %d is up" % i)
            ph.switch("1")                                   # (off and on again, faster than the supervisor looks)
            if i == 3:
                time.sleep(1.2)                              # (whole seconds: run 4 must start AFTER the switch's last write)
            ph.go()
        ph.wait(lambda: len(ph.started()) == 4 and ph.text().startswith("watching"), "three runners that stopped because the switch was flipped: a fourth is started")
        check("STOPPED" not in ph.log() and ph.log().count("it was asked to stop") == 3 and "ended by itself" not in ph.log(),
              "...none of them counted as a quit: %s" % [x for x in ph.log().splitlines() if "ended" in x])
        for i in (4, 5, 6):
            ph.wait(lambda: len(ph.started()) == i and ph.text().startswith("watching"), "run %d is up" % i)
            ph.go()
        ph.wait(lambda: ph.text() == "STOPPED: the gym runner quit 3 times in a row -- flip the switch off and on",
                "three runs that stopped with no flip of the switch behind it: STOPPED (a runner and a supervisor that disagree never loop)")
        check(len(ph.started()) == 6 and ph.log().count("ended by itself") == 3, "...after exactly three more starts")
        ph.switch("0")
        check(ph.gone(p, "...and switch off ends it") == 0 and ph.text() == "off", "...and 'off' is the last line")

    # --- a stop taken back; a stop the runner threw away is written again; a runner that outlives the switch's return
    with phone_dir(bash) as ph:
        os.makedirs(ph.state)
        with open(os.path.join(ph.state, "switch_args.txt"), "w", newline="\n") as f:
            f.write("# the 11-17 drill\n--one-by-one --skip 4232f472,06350f49\n")
        ph.mode("deaf")
        ph.switch("1")
        ph.game(True)
        p = ph.supervisor()
        ph.wait(lambda: len(ph.started()) == 1 and ph.text().startswith("watching"), "a runner is up")
        check((ph.started() or [{}])[0].get("argv", [])[11:] == ["--one-by-one", "--skip", "4232f472,06350f49"], "gym_state/switch_args.txt: its options go on the end of the command line")
        ph.switch("0")
        ph.wait(lambda: len(ph.stops()) == 1 and ph.text().startswith("stopping"), "switch off: a stop is out")
        ph.switch("1")
        ph.wait(lambda: ph.stops() == [] and ph.text().startswith("watching"), "switch on again before the runner read the stop: the stop is taken back")
        check(len(ph.started()) == 1 and alive(ph.started()[0]["pid"]), "...and the same runner stays")
        ph.switch("0")
        ph.wait(lambda: len(ph.stops()) == 1, "switch off again: a stop is out")
        one = ph.stops()
        for n in one:
            os.remove(os.path.join(ph.inbox, n))             # the runner threw it away (a fresh runner does, at its own start)
        ph.wait(lambda: len(ph.stops()) == 1 and ph.stops() != one, "a stop that vanished unread is written again (after STOP_AGAIN)", 12)
        ph.mode("slow")                                      # it takes the stop, then needs 2.5 s to finish its battle
        ph.wait(lambda: ph.stops() == [], "the runner took the stop")
        ph.switch("1")
        ph.wait(lambda: ph.text() == "starting again: the last runner is still letting go of the game", "switch on while the runner is on its way out: it is waited for")
        ph.mode("run")
        ph.wait(lambda: len(ph.started()) == 2 and ph.text().startswith("watching"), "...then a fresh runner is started")
        check("STOPPED" not in ph.log() and ph.log().count("it was asked to stop") == 1, "an asked-for exit is never counted as a crash")
        ph.switch("0")
        check(ph.gone(p, "switch off ends it") == 0 and ph.text() == "off", "...and 'off' is the last line")

    # --- runners that are not this supervisor's children (needs a `ps -ef` that shows arguments: Linux / the phone, not Git Bash)
    with phone_dir(bash) as ph:
        os.makedirs(os.path.join(ph.state, "logs"))
        os.makedirs(ph.inbox)
        ph.mode("deaf")
        env = dict(os.environ, GYM_FAKE_DIR=ph.td)
        cmd = [sys.executable, "-u", "tools/gym_run.py", "--cmd", os.path.join(ph.state, "runner_cmd.json")]
        foreign = subprocess.Popen(cmd, cwd=ph.pogo, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8)
            seen = subprocess.run([bash, "-c", "ps -ef 2>/dev/null | grep '[g]ym_run\\.py' | awk '{print $2}'"], capture_output=True, text=True).stdout.split()
            if str(foreign.pid) not in seen:
                print("  (this machine's `ps -ef` shows no arguments: the foreign-runner and adoption cases were not run)")
            else:
                ph.switch("1")
                ph.game(True)
                p = ph.supervisor()
                ph.wait(lambda: ph.text() == "another gym runner is already running on the phone -- left alone", "a gym runner that is not --on-open: left alone, said so")
                time.sleep(1.0)
                check(len(ph.started()) == 1 and ph.stops() == [], "...nothing is started beside it, and it is never sent a stop")
                ph.switch("0")
                check(ph.gone(p, "switch off beside a foreign runner: the supervisor just leaves") == 0 and ph.text() == "off" and foreign.poll() is None and ph.stops() == [],
                      "switch off: 'off', the foreign runner untouched")
                open(os.path.join(ph.td, "die"), "w").close()
                foreign.wait(10)
                os.remove(os.path.join(ph.td, "die"))
                ph.mode("run")
                with open(os.path.join(ph.state, "logs", "onopen_0101_000000.log"), "wb") as lf:
                    orphan = subprocess.Popen(cmd[:3] + ["--on-open"] + cmd[3:], cwd=ph.pogo, env=env, stdout=lf, stderr=subprocess.STDOUT)
                try:
                    ph.switch("1")
                    p = ph.supervisor()
                    ph.wait(lambda: ph.text().startswith("watching for a gym you open"), "an --on-open runner that outlived its supervisor is adopted: its status is read")
                    check(len(ph.started()) == 2 and "it is this supervisor's now" in ph.log(), "...no second runner is started beside it")
                    ph.switch("0")
                    ph.wait(lambda: orphan.poll() is not None, "switch off: the adopted runner is stopped through the inbox")   # (poll() reaps it: this test is its parent)
                    check(orphan.returncode == 0, "...by its own exit (code %s)" % orphan.returncode)
                    check(ph.gone(p, "...then the supervisor leaves") == 0 and ph.text() == "off", "...and 'off' is the last line")
                finally:
                    if orphan.poll() is None:
                        orphan.kill()
        finally:
            if foreign.poll() is None:
                foreign.kill()
    print("ok: run_gym.sh, run against a fake runner (the switch's whole life)")


def fail_cap_checks():
    """--on-open: an error in the runner's own code, three sessions in a row, ends the runner with exit code 86 (it used to
    come back as an attach every ~13 s for as long as --minutes lasted, with the app saying "lost the game connection");
    run_gym.sh then says STOPPED at once. The same error on the PC keeps retrying, as before."""
    import tempfile
    names = ("run", "Game", "Mover", "dd_guard", "dd_said", "say")
    keep = {k: getattr(gym_run, k) for k in names}
    keep_sleep, keep_argv = gym_run.time.sleep, sys.argv
    said, runs, slept = [], [], []

    class G:
        on_open = False

    def boom(*_a, **_k):
        runs.append(1)
        if len(runs) >= 6:
            raise KeyboardInterrupt                            # the PC case never stops by itself: end it here
        raise KeyError("x")

    try:
        gym_run.run, gym_run.Game, gym_run.Mover = boom, G, (lambda *_a, **_k: None)
        gym_run.dd_guard, gym_run.dd_said, gym_run.say = (lambda *_a, **_k: None), (lambda *_a, **_k: None), said.append
        gym_run.time.sleep = slept.append
        sys.argv = ["gym_run.py", "--on-open", "--switch", os.path.join(tempfile.gettempdir(), "no_such_gym_switch"), "--minutes", "5"]
        code = None
        try:
            gym_run.main()
        except SystemExit as e:
            code = e.code
        check(code == 86 and len(runs) == 3 and slept == [10, 10],
              "--on-open: the third failed session in a row ends the runner with exit code 86 (two retries, no third): %r %r %r" % (code, len(runs), slept))
        check(bool(said) and said[-1].startswith("STOP: the gym runner failed 3 times in a row (KeyError: 'x')")
              and sum(s.startswith("session failed") for s in said) == 2, "...and its LAST line says STOP and why (gym_status.py reads the reason from it)")
        del said[:], runs[:], slept[:]
        sys.argv = ["gym_run.py", "--minutes", "5"]
        try:
            gym_run.main()
        except KeyboardInterrupt:
            pass
        check(len(runs) == 6 and not any(s.startswith("STOP: the gym runner failed") for s in said),
              "on the PC (no --on-open) a failing session keeps retrying, as before")
    finally:
        for k, v in keep.items():
            setattr(gym_run, k, v)
        gym_run.time.sleep, sys.argv = keep_sleep, keep_argv
    rs = read(os.path.join(os.path.dirname(HERE), "run_gym.sh"))
    check('      if [ "$rc" = 86 ]; then quick=$QUICK_MAX; fi\n      if [ "$quick" -ge "$QUICK_MAX" ]; then' in rs.replace("\r\n", "\n"),
          "run_gym.sh: exit code 86 is STOPPED at once (no second and third start of a runner that gave up)")
    print("ok: a runner whose own code keeps failing stops itself")


def main():
    for part in (side_checks, shell_checks, device_checks, attach_checks, import_checks, stop_checks, preflight_checks, script_checks, fail_cap_checks,
                 supervisor_checks):
        part()
    if FAILS:
        print("\n%d FAILED" % len(FAILS))
        return 1
    print("ALL GYM PHONE CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
