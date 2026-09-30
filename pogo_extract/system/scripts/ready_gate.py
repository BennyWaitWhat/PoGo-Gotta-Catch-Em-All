"""ready_gate.py -- the pre-flight gate every tag-WRITE path must pass.

Why this exists
---------------
Tag writes (AddTag / create_tag / apply_members / bulk_untag) on this account
have a long, expensive history of *silently no-op-ing*: the Frida attach
succeeds, the singleton resolves, the bag-walk and tag READS all work -- so
everything LOOKS healthy -- yet ``create_tag`` comes back "verify failed: not
found" and applied membership simply never persists. Every one of those
multi-hour failure cascades traced back to a small set of DEVICE-STATE
preconditions that were not true at write time:

  * PoGo had bounced to the Play Store / a different activity (NOT foreground),
  * the screen had slept (mWakefulness != Awake),
  * Android's cached-app *freezer* had moved PoGo to the /background cpuset,
  * Doze (deep deviceidle) had kicked in on low battery,
  * the cold start had loaded the bag but not yet instantiated
    TaggingRpcService ("no instances of TaggingRpcService"),
  * the PID had drifted out from under a previously-attached session.

READS are tolerant of all of the above; WRITES are not. The single biggest
offender, documented in memory as "THE FOREGROUND-WRITE LESSON", is #6:
PoGo must be *truly* foregrounded -- ``dumpsys window mCurrentFocus`` must name
``com.nianticlabs.pokemongo/...UnityMainActivity`` -- or SetPokemonTags returns
ok and nothing changes.

``ensure_ready_for_writes(sess, pid)`` performs all seven checks. Every probe
is a read-only ``adb``/``dumpsys`` call; the ONLY actions it ever takes are the
explicitly-listed, idempotent remediations (wake the screen, bring PoGo to the
foreground). On the first unrecoverable failure it raises ``NotReadyForWrites``
(a typed exception carrying the failed ``check`` name and a human ``hint``).
On success it returns a small ``ReadyStatus`` dataclass.

Usage (one-liner: gate a Frida session before any tag write)
-----
    import os, sys; sys.path.insert(0, os.path.join(REPO, "system", "scripts"))
    import pogo_il2cpp as pg
    from ready_gate import ensure_ready_for_writes, NotReadyForWrites

    sess, pid = pg.get_session()
    try:
        status = ensure_ready_for_writes(sess, pid)   # raises if not write-safe
        # ... now safe to create_tag / apply_members / untag ...
    except NotReadyForWrites as e:
        print(f"BLOCKED [{e.check}]: {e}  ->  {e.hint}")

(This repo has no `system/__init__.py`, so import it as the bare module
`ready_gate` after putting `system/scripts` on sys.path -- the same pattern
tag_ops.py / refresh.py use. ready_gate itself adds REPO root to sys.path so
its own `import pogo_il2cpp` resolves regardless of how it was invoked.)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import os
import time
import logging
import subprocess
from dataclasses import dataclass, field

# Import the canonical Frida/IL2CPP module so we share ONE definition of
# ADB_TARGET / POGO_PKG / pick_singleton / the get_NumberOfTags probe JS.
# Works whether invoked as `python system/scripts/ready_gate.py`, imported as
# `system.scripts.ready_gate`, or imported as bare `ready_gate`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pogo_il2cpp as pg  # noqa: E402

log = logging.getLogger("ready_gate")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
ADB_TARGET = pg.ADB_TARGET          # '100.98.158.56:5555' (Tailscale)
POGO_PKG = pg.POGO_PKG              # 'com.nianticlabs.pokemongo'
# Foreground activity that the in-game map / storage UI runs under.
POGO_ACTIVITY = "com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity"

BATTERY_FLOOR = 15                  # %, only enforced when NOT externally powered
PID_STABLE_SECS = 3                 # PID must hold this long (catches mid-drift)
PID_SETTLED_SECS = 60               # a process up this long is past its launch: its age proves stability, no 3 s wait
FOREGROUND_WAIT_SECS = 25           # poll budget after am start / monkey relaunch
WAKE_SETTLE_SECS = 1.5             # let the screen come up after KEYCODE_WAKEUP
ADB_TIMEOUT = 20                    # per adb invocation


# ---------------------------------------------------------------------------
# Typed failure + status
# ---------------------------------------------------------------------------
class NotReadyForWrites(RuntimeError):
    """Raised when the device/Frida state is unsafe for tag WRITES.

    Attributes:
        check: short id of the failed gate ("device", "il2cpp", "awake",
               "power", "frozen", "foreground", "tagservice").
        hint:  one-line remediation the operator can act on.
    """

    def __init__(self, check, message, hint=""):
        self.check = check
        self.hint = hint
        super().__init__(f"[{check}] {message}")


@dataclass
class ReadyStatus:
    """Returned by ensure_ready_for_writes() when every check passes."""
    pid: int
    device: str
    wakefulness: str = "Awake"
    foreground: str = ""
    powered: bool = False
    battery: int = -1
    cpuset: str = ""
    num_tags: int = -1
    svc_addr: str = ""
    inv_age_s: float = None            # the live graph's InventoryCache age at this check (informational, H02-4)
    remediations: list = field(default_factory=list)

    def summary(self):
        rem = (" remediated=" + ",".join(self.remediations)) if self.remediations else ""
        return (
            f"READY pid={self.pid} dev={self.device} fg=ok "
            f"wake={self.wakefulness} "
            f"batt={self.battery}%{'(powered)' if self.powered else ''} "
            f"cpuset={self.cpuset} tags={self.num_tags}"
            f" inventory={'%.0fs old' % self.inv_age_s if self.inv_age_s is not None else '?'}{rem}"
        )


# ---------------------------------------------------------------------------
# adb plumbing
# ---------------------------------------------------------------------------
def _adb(*args, root=False, dev=None):
    """Run an adb shell command. Returns (rc, stdout, stderr) with text stripped.

    Uses the exact `adb -s <ADB_TARGET> ...` form. `root=True` wraps the command
    in `su -c '<joined args>'`. Never raises on non-zero rc (callers inspect rc).
    """
    dev = dev or ADB_TARGET
    base = ["adb", "-s", dev, "shell"]
    if root:
        cmd = base + ["su", "-c", " ".join(args)]
    else:
        cmd = base + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=ADB_TIMEOUT)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "adb timeout"
    except FileNotFoundError:
        return 127, "", "adb not on PATH"


def _adb_ok(dev=None):
    """True if `adb get-state` reports 'device' for the target."""
    dev = dev or ADB_TARGET
    try:
        p = subprocess.run(
            ["adb", "-s", dev, "get-state"],
            capture_output=True, text=True, timeout=ADB_TIMEOUT,
        )
        return p.stdout.strip() == "device"
    except Exception:
        return False


def _pidof(dev=None):
    """Return PoGo PID via adb pidof, or None."""
    rc, out, _ = _adb("pidof", POGO_PKG, dev=dev)
    if rc != 0 or not out:
        return None
    try:
        return int(out.split()[0])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def _check_device(dev):
    """(1) Device reachable + PoGo has a live PID."""
    if not _adb_ok(dev):
        raise NotReadyForWrites(
            "device",
            f"adb device {dev} not in 'device' state",
            hint="reconnect Tailscale `adb connect 100.98.158.56:5555` "
                 "(or plug in USB) and restart frida-server if needed",
        )
    pid = _pidof(dev)
    if not pid:
        raise NotReadyForWrites(
            "device",
            f"PoGo ({POGO_PKG}) is not running on {dev}",
            hint=f"launch PoGo: adb -s {dev} shell monkey -p {POGO_PKG} "
                 "-c android.intent.category.LAUNCHER 1",
        )
    return pid


def _has_il2cpp(pid, dev):
    """True if libil2cpp.so is mapped into PID (root grep of /proc/PID/maps)."""
    rc, out, _ = _adb(
        f"grep -c libil2cpp /proc/{pid}/maps 2>/dev/null", root=True, dev=dev
    )
    try:
        return int(out) > 0
    except ValueError:
        return False


def _proc_age(pid, dev):
    """Seconds PID has been running (/proc/uptime minus its start time, field 22 of /proc/PID/stat, 100 ticks/s on
    Android), or None when it cannot be read or looks wrong -- the caller then waits the full window."""
    rc, out, _ = _adb(f"cat /proc/uptime /proc/{pid}/stat", dev=dev)
    try:
        up_line, stat_line = [l for l in out.splitlines() if l.strip()][:2]
        start_ticks = int(stat_line.rsplit(")", 1)[1].split()[19])   # fields after the (comm) start at field 3
        age = float(up_line.split()[0]) - start_ticks / 100.0
    except (ValueError, IndexError):
        return None
    return age if rc == 0 and 0 <= age < 10 ** 7 else None


def _check_il2cpp_and_stable(pid, dev):
    """(2) libil2cpp.so loaded AND the PID holds steady for ~PID_STABLE_SECS.

    A drifting PID (cached-app freezer re-launching PoGo) invalidates every
    Frida address mid-operation, so we confirm it is the SAME pid before and
    after a short settle, and that the native runtime is actually mapped.
    """
    if not _has_il2cpp(pid, dev):
        raise NotReadyForWrites(
            "il2cpp",
            f"libil2cpp.so not yet mapped in PID {pid} "
            "(cold start still loading the runtime)",
            hint="wait for the PoGo map to finish loading, then retry",
        )
    # AGE INSTEAD OF A WAIT (2026-09-30, cull speed pick 2): the window below exists for a PID that is still changing
    # right after a launch. A process already up PID_SETTLED_SECS is past that, and its age is one adb call instead of
    # a 3 s sleep plus 3 pidof calls -- twice per cull (prune, post-tags). Unknown age -> the window, as before.
    age = _proc_age(pid, dev)
    if age is not None and age >= PID_SETTLED_SECS:
        return True
    # PID-stability window.
    deadline = time.monotonic() + PID_STABLE_SECS
    while time.monotonic() < deadline:
        time.sleep(1)
        cur = _pidof(dev)
        if cur != pid:
            raise NotReadyForWrites(
                "il2cpp",
                f"PID drifted {pid} -> {cur} during stability window "
                "(cached-app freezer relaunched PoGo)",
                hint="apply the freezer fix "
                     "(`device_config put activity_manager use_freezer false`), "
                     "re-attach a fresh session, and retry",
            )
    return True


def _check_awake(dev, remediations):
    """(3) Screen Awake; if not, send KEYCODE_WAKEUP and re-poll once.

    Tag writes silently no-op while the screen is asleep, so this is a hard gate
    -- but waking is a safe, idempotent remediation we are permitted to perform.
    """
    rc, out, _ = _adb("dumpsys power", dev=dev)
    if "mWakefulness=Awake" in out:
        return "Awake"

    log.info("screen not Awake -- sending KEYCODE_WAKEUP")
    _adb("input", "keyevent", "KEYCODE_WAKEUP", dev=dev)
    remediations.append("wake")
    time.sleep(WAKE_SETTLE_SECS)

    rc, out, _ = _adb("dumpsys power", dev=dev)
    if "mWakefulness=Awake" in out:
        return "Awake"

    # Best-effort extraction of the current state for the error message.
    state = "unknown"
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("mWakefulness=") and "Changing" not in s:
            state = s.split("=", 1)[1].strip()
            break
    raise NotReadyForWrites(
        "awake",
        f"screen did not reach Awake after KEYCODE_WAKEUP (mWakefulness={state})",
        hint="physically wake/unlock the phone (it may be in a secured/off "
             "state KEYCODE_WAKEUP can't clear), then retry",
    )


def _parse_battery(out):
    """Parse `dumpsys battery` into (level:int|-1, powered:bool)."""
    level = -1
    powered = False
    for line in out.splitlines():
        s = line.strip().lower()
        if s.startswith("level:"):
            try:
                level = int(s.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif s.endswith("powered: true") and (
            s.startswith("ac ") or s.startswith("usb ")
            or s.startswith("wireless ") or s.startswith("dock ")
        ):
            powered = True
    return level, powered


def _check_power(dev):
    """(4) Battery >= floor OR externally powered, AND not in deep Doze.

    Low battery throttling + Doze both starve the RPC channel and were a
    documented amplifier of the silent-write failures. Returns (battery, powered).
    """
    rc, out, _ = _adb("dumpsys battery", dev=dev)
    level, powered = _parse_battery(out)
    if not powered and 0 <= level < BATTERY_FLOOR:
        # NO LONGER A HARD BLOCK (user 2026-07-26: "why on earth is there a block for battery level?
        # get rid of that"). Low battery only makes writes FLAKY, never destructive -- and every sync is
        # followed by reconcile + verify_tags_live.py, which catch a write that didn't land. So warn and
        # proceed; the verifier is the real safety net. Set POGO_BATTERY_GATE=1 to restore the block.
        if os.environ.get("POGO_BATTERY_GATE") == "1":
            raise NotReadyForWrites(
                "power",
                f"battery {level}% < {BATTERY_FLOOR}% floor and not externally powered "
                "(throttling will make tag writes flaky/no-op)",
                hint="plug in the phone (or charge above the floor), then retry",
            )
        log.warning("battery %d%% < %d%% floor and not powered -- proceeding anyway; "
                    "if tag writes come back short, charge the phone and re-sync", level, BATTERY_FLOOR)

    # Deep Doze gate: `deviceidle get deep` must be ACTIVE (not IDLE/IDLE_PENDING).
    rc, deep, _ = _adb("dumpsys", "deviceidle", "get", "deep", dev=dev)
    deep = (deep or "").strip().upper()
    if deep and deep != "ACTIVE":
        raise NotReadyForWrites(
            "power",
            f"device is in Doze (deviceidle deep state = {deep}); "
            "background RPCs are deferred",
            hint=f"wake/interact with the phone or run "
                 f"`adb -s {dev} shell dumpsys deviceidle unforce` "
                 "(and ensure it is not force-IDLEd), then retry",
        )
    return level, powered


def _check_not_frozen(pid, dev):
    """(5) PID is not in the /background freezer cpuset.

    The cached-app freezer parks backgrounded PoGo in cpuset:/background and
    suspends it; a write issued against a frozen process never lands. A
    foreground app sits in /top-app (or /foreground). Returns the cpuset path.
    """
    rc, out, _ = _adb(f"cat /proc/{pid}/cgroup", root=True, dev=dev)
    cpuset = ""
    for line in out.splitlines():
        # format: "<hierarchy-id>:cpuset:/<path>"
        if ":cpuset:" in line:
            cpuset = line.split(":cpuset:", 1)[1].strip()
            break
    if cpuset in ("/background", "background"):
        raise NotReadyForWrites(
            "frozen",
            f"PID {pid} is in the frozen cpuset ({cpuset}) -- writes will not land",
            hint="bring PoGo to the foreground (the next check does this) and/or "
                 "apply the freezer fix "
                 "(`device_config put activity_manager use_freezer false`)",
        )
    return cpuset or "(unknown)"


def _focus_line(dev):
    """Return the combined mCurrentFocus + mFocusedApp text from dumpsys window."""
    rc, out, _ = _adb("dumpsys window", dev=dev)
    keep = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("mCurrentFocus") or s.startswith("mFocusedApp"):
            keep.append(s)
    return "\n".join(keep)


def _is_pogo_foreground(dev):
    """True iff PoGo's UnityMainActivity is the current focus (or focused app).

    Primary signal is mCurrentFocus; we tolerate mFocusedApp too (during a
    transition the focused activity record can be set a beat before the window
    focus settles).
    """
    text = _focus_line(dev)
    needle = f"{POGO_PKG}/{POGO_ACTIVITY}"
    # Tolerate the activity shown with or without the full package-qualified
    # class (some builds print ".../UnityMainActivity").
    return (needle in text) or (
        POGO_PKG in text and "UnityMainActivity" in text
    )


def _check_foreground(dev, remediations):
    """(6) PoGo's UnityMainActivity is foregrounded -- THE silent-no-op root cause.

    Tag writes silently succeed-then-vanish unless PoGo is *truly* foreground.
    If it isn't, relaunch it (am start, then monkey LAUNCHER as a fallback) and
    poll mCurrentFocus for up to FOREGROUND_WAIT_SECS.
    """
    if _is_pogo_foreground(dev):
        return _focus_line(dev)

    log.info("PoGo not foreground -- relaunching and polling mCurrentFocus")
    # Preferred: direct activity start. Fall back to the LAUNCHER intent.
    _adb("am", "start", "-n", f"{POGO_PKG}/{POGO_ACTIVITY}", dev=dev)
    remediations.append("foreground")

    deadline = time.monotonic() + FOREGROUND_WAIT_SECS
    launched_via_monkey = False
    while time.monotonic() < deadline:
        time.sleep(2)
        if _is_pogo_foreground(dev):
            return _focus_line(dev)
        # Halfway through, try the monkey LAUNCHER intent once as a fallback.
        if not launched_via_monkey and time.monotonic() > deadline - FOREGROUND_WAIT_SECS / 2:
            log.info("am start did not foreground PoGo -- trying monkey LAUNCHER")
            _adb("monkey", "-p", POGO_PKG, "-c",
                 "android.intent.category.LAUNCHER", "1", dev=dev)
            launched_via_monkey = True

    raise NotReadyForWrites(
        "foreground",
        f"PoGo's {POGO_ACTIVITY} never became mCurrentFocus within "
        f"{FOREGROUND_WAIT_SECS}s -- tag writes would silently no-op. "
        f"current focus: {_focus_line(dev) or '(none)'}",
        hint="bring PoGo to the foreground on the map (dismiss any Play Store / "
             "login / OS dialog covering it), then retry",
    )


def _check_tag_service(sess):
    """(7) TaggingRpcService singleton resolves with a plausible NumberOfTags.

    Even fully foregrounded, a fresh cold start can have the bag loaded but the
    tag service not yet instantiated ("no instances of TaggingRpcService"). The
    fix is to open the Pokemon storage UI so the service is created. Returns
    (svc_addr, num_tags).
    """
    try:
        svc = pg.pick_singleton(sess, "Niantic.Holoholo.Tagging", "TaggingRpcService")
    except Exception as exc:
        msg = str(exc)
        if "no instances" in msg.lower():
            raise NotReadyForWrites(
                "tagservice",
                "TaggingRpcService has no live instance "
                "(bag loaded but tag service not yet created)",
                hint="open the Pokemon storage UI in PoGo (tap the Pokeball -> "
                     "Pokemon) to instantiate TaggingRpcService, then retry",
            )
        raise NotReadyForWrites(
            "tagservice",
            f"could not resolve TaggingRpcService singleton: {msg}",
            hint="ensure PoGo is on the map/storage UI and re-attach Frida",
        )

    # Confirm the service object answers get_NumberOfTags, reusing the canonical probe JS. NOT proof that its graph
    # is live or that the server hears it (H02-4, 2026-09-29: a stale graph's service answers this cached getter the
    # same way): pick_singleton above returns the LIVE graph's service or refuses; the walk tripwires judge that
    # graph's liveness (rc 8), and prune_tags refuses a push through a graph older than, or rebuilt since, the walk.
    num_tags = -1
    s = pg.get_script_with_helpers(sess, pg._SVC_PROBE_JS)
    try:
        pr = s.exports_sync.probe_number_of_tags(svc)
        if pr.get("ok"):
            num_tags = int(pr.get("n", -1))
    except Exception:
        pass
    finally:
        s.unload()

    if num_tags < 0:
        raise NotReadyForWrites(
            "tagservice",
            f"TaggingRpcService @ {svc} did not return get_NumberOfTags "
            "(service not fully initialized)",
            hint="open the Pokemon storage UI in PoGo, wait a few seconds, "
                 "then retry",
        )
    return svc, num_tags


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def ensure_ready_for_writes(sess, pid):
    """Gate every tag-WRITE path against the documented silent-no-op failure modes.

    Runs all seven checks in dependency order. All probes are read-only
    adb/dumpsys calls; the only side effects are the explicitly-listed,
    idempotent remediations (KEYCODE_WAKEUP to wake the screen; am start /
    monkey LAUNCHER to foreground PoGo).

    Args:
        sess: a live ``frida.Session`` already attached to PoGo (e.g. from
              ``pogo_il2cpp.get_session()``).
        pid:  the PID that session was attached to (used for the il2cpp /
              freezer / stability checks).

    Returns:
        ReadyStatus -- on success, with the observed device state.

    Raises:
        NotReadyForWrites -- on the first unrecoverable failure. The exception's
        ``.check`` names the failed gate and ``.hint`` gives a remediation.
    """
    dev = ADB_TARGET
    remediations = []

    # (1) device reachable + pidof
    live_pid = _check_device(dev)
    if live_pid != pid:
        # The caller's session is bound to `pid`; if the live PID differs the
        # session is already stale -- fail loudly rather than gate the wrong proc.
        raise NotReadyForWrites(
            "device",
            f"live PoGo PID {live_pid} != attached session PID {pid} "
            "(PID drifted since attach)",
            hint="re-attach with a fresh pogo_il2cpp.get_session() and retry",
        )

    # (2) il2cpp mapped + PID stable
    _check_il2cpp_and_stable(pid, dev)

    # (3) screen Awake (remediable)
    wakefulness = _check_awake(dev, remediations)

    # (4) battery floor / powered + not Doze
    battery, powered = _check_power(dev)

    # (5) not frozen (cpuset != /background)
    cpuset = _check_not_frozen(pid, dev)

    # (6) FOREGROUND -- the silent-no-op root cause (remediable)
    foreground = _check_foreground(dev, remediations)

    # (7) TaggingRpcService singleton + plausible NumberOfTags
    svc_addr, num_tags = _check_tag_service(sess)

    _g = getattr(sess, '_pogo_graph', None) or {}
    try:
        _inv_age = (int(_g.get('now')) - int(_g.get('ts'))) / 1000.0
    except (TypeError, ValueError):
        _inv_age = None
    status = ReadyStatus(
        inv_age_s=_inv_age,
        pid=pid,
        device=dev,
        wakefulness=wakefulness,
        foreground=foreground,
        powered=powered,
        battery=battery,
        cpuset=cpuset,
        num_tags=num_tags,
        svc_addr=svc_addr,
        remediations=remediations,
    )
    log.info(status.summary())
    return status


# ---------------------------------------------------------------------------
# CLI smoke test:  python system/scripts/ready_gate.py
# ---------------------------------------------------------------------------
def _main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    print("ready_gate self-test: attaching to PoGo via pogo_il2cpp ...")
    sess, pid = pg.get_session()
    try:
        status = ensure_ready_for_writes(sess, pid)
        print("\n" + status.summary())
        print("RESULT: READY FOR WRITES")
        return 0
    except NotReadyForWrites as e:
        print(f"\nRESULT: BLOCKED [{e.check}] {e}")
        print(f"  hint: {e.hint}")
        return 1
    finally:
        try:
            sess.detach()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(_main())
