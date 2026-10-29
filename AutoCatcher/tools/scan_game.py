"""ONE read-only pass that re-scans the game's limits + hard-coded constants, then reports what changed since the last
scan of an older game version.

  python tools/scan_game.py              the phone pass (one attach, ~1 min), then the diff + both HTML reports
  python tools/scan_game.py --diff-only  no phone: diff the newest scans of the two newest game versions in scans/

The phone pass (2026-10-29, after the week's crash list -- see memory pogo-crash-kinds-2026-10-29):
  * adb-only preflight: Pixel 9 Pro, game version, PoGo pid at least MIN_AGE_S old (well past its startup crash window),
    no FOREIGN live desktop busy marker (waits up to 2 min, then refuses: this scan is never worth stacking on a cull
    or a runner), and the list of PoGo tombstones before the pass;
  * ONE attach (pogo_il2cpp.get_session: its own cold-start gate + the shared busy marker), the limits read and the
    constants walk on that one session, detach in a finally -- never a second attach, never a retry;
  * afterwards: same pid still running, and no new PoGo tombstone. Either one is printed as a FAIL line.
It never connects to the gadget port to "test" it, never starts / stops / foregrounds PoGo, and writes nothing to the game.
Unknown arguments: rc 2, nothing is run (see memory feedback-never-probe-scripts-with-help).
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import pogo_il2cpp as pg  # noqa: E402
import dump_game_limits as dl  # noqa: E402
import dump_game_constants as dc  # noqa: E402
import scan_diff as sd  # noqa: E402

MIN_AGE_S = 120            # PoGo's own startup crash (NianticLabsPlugin, "uptime 2s") happens in the first seconds
BUSY_WAIT_S = 120
PKG = "com.nianticlabs.pokemongo"


def sh(cmd, timeout=25):
    try:
        return subprocess.run(["adb", "-s", pg.ADB_TARGET, "shell", cmd], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout).stdout or ""
    except Exception as e:
        return f"<adb failed: {e}>"


def pogo_tombstones():
    """{tombstone file: 'Timestamp'} for every PoGo tombstone (reads files only)."""
    out = sh("su -c 'for f in /data/tombstones/tombstone_[0-9][0-9]; do "
             "grep -q \">>> com.nianticlabs.pokemongo\" $f 2>/dev/null && echo \"$f $(grep -m1 ^Timestamp: $f)\"; done'", 40)
    res = {}
    for line in out.splitlines():
        p = line.split(" ", 1)
        if len(p) == 2 and p[0].startswith("/data/tombstones/"):
            res[p[0]] = p[1].replace("Timestamp:", "").strip()
    return res


def pid_age(pid):
    out = sh(f"cut -d' ' -f22 /proc/{pid}/stat; cut -d' ' -f1 /proc/uptime; getconf CLK_TCK").split()
    try:
        return float(out[1]) - int(out[0]) / int(out[2])
    except (IndexError, ValueError, ZeroDivisionError):
        return None


def foreign_busy():
    """(who, seconds left) of a live desktop busy marker that is not ours, else None (phone clock)."""
    out = sh(f"cat {pg.BUSY_FILE} 2>/dev/null; date +%s").split()
    if len(out) < 3:
        return None
    who, dl_, now = out[0], out[1], out[-1]
    try:
        left = int(dl_) - int(now)
    except ValueError:
        return None
    if who in ("free", pg.BUSY_NAME) or left <= 0:
        return None
    return who, left


def preflight():
    model = sh("getprop ro.product.model").strip()
    if model != "Pixel 9 Pro":
        sys.exit(f"STOP: adb target {pg.ADB_TARGET} is {model!r}, not the Pixel 9 Pro -- nothing was attached")
    version = dl.game_version()
    pid = sh(f"pidof {PKG}").strip().split()
    if not pid:
        sys.exit("STOP: PoGo is not running -- open it (through Pokemod) and run again; nothing was attached")
    pid = int(pid[0])
    age = pid_age(pid)
    if age is None or age < MIN_AGE_S:
        sys.exit(f"STOP: PoGo pid {pid} is {age if age is None else round(age)} s old (< {MIN_AGE_S} s) -- run again in a "
                 "minute or two; nothing was attached")
    t_end = time.time() + BUSY_WAIT_S
    fb = foreign_busy()
    while fb and time.time() < t_end:
        print(f"waiting: {fb[0]} holds the phone busy marker ({fb[1]} s left)", flush=True)
        time.sleep(10)
        fb = foreign_busy()
    if fb:
        sys.exit(f"STOP: {fb[0]} is still attached (busy marker) -- this scan does not stack on another session; "
                 "nothing was attached")
    conns = sh("su -c 'cat /proc/net/tcp /proc/net/tcp6' 2>/dev/null | grep -c ':69A7 [0-9A-F:]* 01'").strip()   # a read, never a connect
    print(f"preflight ok: game {version}, pid {pid} up {age / 60:.0f} min, ESTABLISHED gadget links now {conns} (the catcher's own)",
          flush=True)
    return version, pid


def newest(stem, version=None, other_than=None):
    files = []
    for p in glob.glob(os.path.join(dl.SCANS, f"{stem}_*.json")):
        m = re.match(rf"{stem}_(.+?)_(\d{{8}}-\d{{4}})\.json$", os.path.basename(p))
        if not m:
            continue
        if version and m.group(1) != version:
            continue
        if other_than and m.group(1) == other_than:
            continue
        files.append((m.group(2), p, m.group(1)))
    return max(files)[1:] if files else (None, None)


def diff_and_report(lim_new, con_new, version):
    lim_base, lim_ver = newest("game_limits", other_than=version)
    con_base, con_ver = newest("game_constants", other_than=version)
    if not lim_base:
        print("no older scan to diff against", flush=True)
        return
    lr, lm = sd.diff_limits(lim_base, lim_new)
    cr = cm = None
    if con_base and con_new:
        cr, cm = sd.diff_constants(con_base, con_new)
    res, ours = sd.write(lr, lm, cr, cm)
    print(f"DIFF game {lim_ver} -> {version}:", flush=True)
    print(sd.summary(res, sd.order(ours)), flush=True)
    print(f"report: {sd.OUT_HTML}", flush=True)


def phone_pass():
    version, pid0 = preflight()
    before = pogo_tombstones()
    t0 = time.time()
    try:
        sess, pid = pg.get_session()
    except Exception as e:
        sys.exit(f"STOP: attach failed ({type(e).__name__}: {e}) -- not retried; nothing was read")
    print(f"attached pid {pid}", flush=True)
    lim = con = None
    try:
        lim = dl.run(sess, pid, version)
        con = dc.run(sess, pid, version)
    finally:
        try:
            sess.detach()
        except Exception:
            pass
        print(f"detached after {time.time() - t0:.0f} s", flush=True)
    time.sleep(5)
    after = sh(f"pidof {PKG}").strip().split()
    new_tomb = {k: v for k, v in pogo_tombstones().items() if before.get(k) != v}
    ok = after and int(after[0]) == pid and not new_tomb
    print(("POST ok: " if ok else "POST FAIL: ") + f"PoGo pid {pid} -> {after[0] if after else 'GONE'}, "
          f"new PoGo tombstones {len(new_tomb)}" + (f" {new_tomb}" if new_tomb else ""), flush=True)
    paths = {}
    if lim:
        paths["limits"] = dl.save(lim, dl.OUT, "game_limits")
    if con:
        paths["constants"] = dl.save(con, dc.OUT, "game_constants")
    print(f"saved {paths}", flush=True)
    for mod in ("limits_report", "constants_report"):   # the two existing HTML pages, now on the new dump
        try:
            __import__(mod).main()
        except Exception as e:
            print(f"{mod} failed: {type(e).__name__}: {e}", flush=True)
    diff_and_report(paths.get("limits"), paths.get("constants"), version)


def diff_only():
    lim_new, ver = None, None
    files = sorted(glob.glob(os.path.join(dl.SCANS, "game_limits_*.json")))
    if not files:
        sys.exit("no scans yet")
    stamp_ver = []
    for p in files:
        m = re.match(r"game_limits_(.+?)_(\d{8}-\d{4})\.json$", os.path.basename(p))
        if m:
            stamp_ver.append((m.group(2), m.group(1), p))
    _, ver, lim_new = max(stamp_ver)
    con_new, _ = newest("game_constants", version=ver)
    diff_and_report(lim_new, con_new, ver)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # game strings can hold any character; a print never kills the pass
    args = sys.argv[1:]
    if args == []:
        phone_pass()
    elif args == ["--diff-only"]:
        diff_only()
    else:
        print(__doc__)
        print(f"unknown arguments {args}: NOTHING was run")
        sys.exit(2)


if __name__ == "__main__":
    main()
