"""The gym runner ON the phone itself (Termux + Magisk root): no PC, no adb.

Benny, 2026-11-18 15:20, about the AutoCatcher app's Gym Battle switch: "why cant gym mode work without the PC? i want it
working on my phone." gym_run.py is the same file on both sides. This module is the phone's half of the three things that
differ:

  1. THE DEVICE SHELL. On the PC every device command is `adb -s <phone> shell <cmd>` (cutoff_hunt.adb). On the phone it is
     the same command text in ONE root shell that stays open for the runner's whole life (`su`, commands written to its
     stdin). Not `su -c <cmd>` per command: Magisk reports every su request to its app through a fresh app_process (seen
     on the phone, 11-18: `app_process /system/bin com.android.commands.content.Content call --uri content://
     com.topjohnwu.magisk.provider ... --method notify`), and the runner reads the joystick's GPS fix about once a second
     during a takeover.
  2. THE ATTACH. The phone's pogo_il2cpp (ondevice_toggle/phone_pogo_il2cpp.py) finds the game through adb, which Termux
     does not have. install() gives it the two functions the runner calls -- same names, arguments and return values --
     built on the root shell and the game's own Frida gadget on 127.0.0.1:27047: the same /proc gate as the PC (libil2cpp
     mapped, the process at least 45 s old) plus "the gadget LISTENs", read from /proc/net/tcp. Never a connect probe
     (run_catch.sh: a connect-and-hang-up aborts the game).
  3. WHERE THE DATA IS. ~/pogo is the repo's AutoCatcher folder. What the PC keeps beside it (../pogo_extract: the game
     master) sits inside it on the phone: ~/pogo/pogo_extract.

Which side is this? ON_PHONE = what is really there: the Termux prefix /data/data/com.termux/files/usr exists on the phone
and cannot exist on the PC or in CI, so `python tools/gym_run.py` typed in Termux takes the phone's path too.
POGO_ON_PHONE=1 / 0 overrides it (run_gym.sh sets 1; the offline check sets both).
Offline check: python test_gym_phone.py
"""
import atexit
import os
import queue
import subprocess
import threading
import time

TERMUX = "/data/data/com.termux/files/usr"
PKG = "com.nianticlabs.pokemongo"
GADGET = "127.0.0.1:27047"                     # pogo_il2cpp.FRIDA_REMOTE: the game's own gadget; it listens only while the game runs
SCREENCAP = ["su", "-c", "screencap -p"]       # the one device call that returns bytes (gym_run's spin study): its own short root call
NOT_READY = RuntimeError                       # install() makes it the phone module's NotReadyToAttach


def detect(env=None, isdir=os.path.isdir):
    v = (os.environ if env is None else env).get("POGO_ON_PHONE")
    return v == "1" if v in ("0", "1") else bool(isdir(TERMUX))


ON_PHONE = detect()


def data_dir(here, name):
    """A data folder of the repo that is NOT under AutoCatcher (here = .../tools). The PC: beside AutoCatcher, as always
    (<repo>/<name>). The phone: inside ~/pogo (~/pogo/<name>) -- everything the runner touches there lives under ~/pogo."""
    return os.path.join(os.path.dirname(here) if ON_PHONE else os.path.dirname(os.path.dirname(here)), name)


# ------------------------------------------------------------------------------------------------ the device shell
class RootShell:
    """One shell, kept open; run(cmd) -> what the command printed (stdout only, like cutoff_hunt.adb on the PC), '' when
    the shell gives no answer. One command at a time (a lock: the runner also calls from threads). A command that got no
    answer in `timeout` s costs this shell its life -- the next call opens a fresh one -- and is NEVER sent twice (a Back
    key or a WALK must not repeat); only a shell that was already gone before the command went out is replaced and tried
    once more."""

    def __init__(self, argv=("su",), timeout=25.0, env=None):
        self.argv, self.timeout, self.env = list(argv), timeout, env
        self.lock, self.p, self.q, self.n, self.mark, self.told = threading.Lock(), None, None, 0, "", False

    def _open(self):
        # Termux's own libraries must never reach a system binary run as root (LD_LIBRARY_PATH is set for Frida's sake).
        env = self.env if self.env is not None else {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
        p = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        q = queue.Queue()
        threading.Thread(target=self._pump, args=(p, q), daemon=True).start()
        self.p, self.q = p, q

    @staticmethod
    def _pump(p, q):
        try:
            for raw in iter(p.stdout.readline, b""):
                q.put(raw)
        except (OSError, ValueError):
            pass
        q.put(None)                                          # the shell closed

    def close(self):
        p, self.p, self.q = self.p, None, None
        if p is None:
            return
        try:
            p.stdin.close()                                  # end of input: the shell leaves by itself
        except OSError:
            pass
        try:
            p.wait(1)
        except subprocess.TimeoutExpired:
            try:
                p.kill()                                     # (our own shell, stuck on a command -- never the game)
            except OSError:
                pass

    def _send(self, cmd):
        self.n += 1
        self.mark = "__pogo_%d_%d__" % (os.getpid(), self.n)
        # The group reads /dev/null: no command may swallow the lines that follow it on the shell's stdin. The bare echo
        # puts the end mark on a line of its own whatever the command printed last.
        self.p.stdin.write(("{ %s\n} </dev/null; echo; echo %s\n" % (cmd, self.mark)).encode("utf-8"))
        self.p.stdin.flush()

    def _read(self, timeout):
        out, end = [], time.time() + timeout
        while True:
            raw = self.q.get(timeout=max(0.01, end - time.time()))
            if raw is None:
                raise OSError("the shell closed")
            line = raw.decode("utf-8", "replace")
            if line.rstrip("\r\n") == self.mark:
                break
            out.append(line)
        text = "".join(out)
        return text[:-1] if text.endswith("\n") else text    # (the bare echo's newline)

    def run(self, cmd, timeout=None):
        err = None
        with self.lock:
            for _ in (0, 1):
                try:
                    if self.p is None or self.p.poll() is not None:
                        self.close()
                        self._open()
                    self._send(cmd)
                except (OSError, ValueError) as e:           # gone before the command went out: one fresh shell
                    self.close()
                    err = e
                    continue
                try:
                    out = self._read(self.timeout if timeout is None else timeout)
                    self.told = False
                    return out
                except queue.Empty:
                    err = TimeoutError("no answer in %.0f s" % (self.timeout if timeout is None else timeout))
                except OSError as e:
                    err = e
                self.close()
                break
            if not self.told:                                # once per outage, in the runner's log, in its own line format
                self.told = True
                print("%s   !! phone root shell: no answer to a device command (%s: %s) -- device commands return nothing until it is back"
                      % (time.strftime("%H:%M:%S"), type(err).__name__, err), flush=True)
            return ""


_SHELL = None


def sh(cmd, timeout=None):
    """One device command in the runner's root shell -> its stdout ('' on any failure, as adb gives on the PC)."""
    global _SHELL
    if _SHELL is None:
        _SHELL = RootShell()
        atexit.register(_SHELL.close)
    return _SHELL.run(cmd, timeout)


# ------------------------------------------------------------------------------------------------ the attach
def pidof():
    """The game's pid, or None (not running / two answers). pogo_il2cpp._adb_pidof without adb."""
    out = sh("pidof " + PKG).strip()
    try:
        return int(out) if out else None
    except ValueError:
        return None


def ready_to_attach(pid, min_age_s=45):
    """pogo_il2cpp._adb_ready_to_attach on the phone: (ok, why), from /proc alone, nothing attached. Attaching Frida to a
    game that is still loading crashes it, so: libil2cpp.so mapped, the process at least min_age_s old -- and, on the
    phone, its gadget listening (the PC reaches the same gadget through an adb forward that cannot be asked this)."""
    port = "%04X" % int(GADGET.rsplit(":", 1)[1])
    out = sh("grep -m1 -c libil2cpp.so /proc/%d/maps; cut -d' ' -f22 /proc/%d/stat; cut -d' ' -f1 /proc/uptime; getconf CLK_TCK; "
             "echo L$(grep -c ':%s 00000000:0000 0A' /proc/net/tcp)" % (pid, pid, port)).split()
    if len(out) < 5 or not out[4].startswith("L"):
        return False, "/proc read failed for pid %s (process gone mid-check?)" % pid
    mapped, start_ticks, uptime_s, hz = out[:4]
    if mapped != "1":
        return False, "libil2cpp.so not yet mapped in pid %s (cold start)" % pid
    try:
        age = float(uptime_s) - int(start_ticks) / int(hz)
    except (ValueError, ZeroDivisionError):
        return False, ("/proc gave non-numeric values for pid %s (start=%r uptime=%r hz=%r) -- treating as NOT ready"
                       % (pid, start_ticks, uptime_s, hz))
    if age < min_age_s:
        return False, "pid %s is only %.0fs old (< %ss) -- init storm, unsafe to attach" % (pid, age, min_age_s)
    if not out[4][1:].isdigit() or int(out[4][1:]) < 1:
        return False, "the game's Frida gadget is not listening on %s yet" % GADGET
    return True, "pid %s ready (il2cpp mapped, %.0fs old, gadget listening)" % (pid, age)


def wait_ready_to_attach(timeout_s=240, min_age_s=45):
    """Block until the game is safe to attach, polling /proc only. Returns the ready pid; RuntimeError when the time is up
    (the same contract as pogo_il2cpp.wait_ready_to_attach)."""
    deadline, last = time.time() + timeout_s, "no pid yet"
    while time.time() < deadline:
        pid = pidof()
        if pid:
            ok, last = ready_to_attach(pid, min_age_s)
            if ok:
                return pid
        time.sleep(5)
    raise RuntimeError("PoGo never became attach-safe in %ss (%s)" % (timeout_s, last))


def _device(frida):
    dm = frida.get_device_manager()
    try:
        return dm.add_remote_device(GADGET)
    except Exception:                                        # added before (a re-attach): find it (as catch_phone.py does)
        for d in dm.enumerate_devices():
            if GADGET in (getattr(d, "name", "") or "") or getattr(d, "id", "") == "socket@" + GADGET:
                return d
        raise


def get_session(retries=3, allow_cold=False):
    """(frida.Session, pid), like pogo_il2cpp.get_session -- through the local gadget. The pid that passed the /proc gate
    is the pid that is attached, by number: if the game restarted in between, the gadget of the new process refuses that
    number and the caller's wait starts over. A cold process is never attached unless allow_cold is set. `retries` is
    accepted for the signature's sake: one try per call, the runner's own loop does the retrying."""
    import frida
    pid = pidof()
    if not pid:
        raise RuntimeError("PoGo not running (%s) on this phone" % PKG)
    if not allow_cold:
        ok, why = ready_to_attach(pid)
        if not ok:
            raise NOT_READY(why + " -- wait (wait_ready_to_attach) instead of attaching")
    res, cancelled = {}, threading.Event()               # a hard 15 s limit, as on the PC: a late attach detaches itself

    def _attach():
        try:
            s = _device(frida).attach(pid)
            if cancelled.is_set():
                try:
                    s.detach()
                except Exception:
                    pass
                return
            res["sess"] = s
        except Exception as e:
            res["err"] = "%s: %s" % (type(e).__name__, e)

    t = threading.Thread(target=_attach, daemon=True)
    t.start()
    t.join(15)
    if t.is_alive():
        cancelled.set()
        raise RuntimeError("frida attach timed out on the phone's own gadget (%s)" % GADGET)
    if "sess" in res:
        return res["sess"], pid
    raise RuntimeError(res.get("err", "attach failed"))


def install(pg):
    """Hand the phone's pogo_il2cpp the two functions that need no adb. Nothing else in it is touched: walk_bag_protos and
    the rest work on a session and are the same code on both sides."""
    global PKG, GADGET, NOT_READY
    PKG, GADGET = getattr(pg, "POGO_PKG", PKG), getattr(pg, "FRIDA_REMOTE", GADGET)
    NOT_READY = getattr(pg, "NotReadyToAttach", RuntimeError)
    pg.wait_ready_to_attach, pg.get_session = wait_ready_to_attach, get_session
