"""Offline test of AutoCatcher/deploy.sh against a fake adb (no phone): python tools/deploy_sim.py
The fake adb logs every call and answers the phone's md5 step with "ok <dst>" or "FAIL <dst>" (STUB_MODE), with the CR
line endings a real `adb shell` can add. Checks: a good copy restarts with --restart; a bad copy stops at once with
exit 1, never restarts and never pushes the next file; the desktop pogo_il2cpp.py is still refused; a .sh file is made
runnable (chmod 744) before it takes its place, and no other file is touched that way; the STARDUST ONLY
table rides along exactly when the phone's copy is missing, different or older (STUB_DUST = what the phone holds).
Exit code 1 when any check fails."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.environ.get("DEPLOY_SH") or os.path.join(HERE, os.pardir, "deploy.sh")   # DEPLOY_SH: test another copy
STUB = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_LOG"
case "$*" in
  *"catcher_ctl.sh restart"*) echo "stub: restarted" ;;
  *"md5sum /data/local/tmp/"*)
    dst=$(printf '%s' "$*" | grep -o 'ok   [^"\\]*' | head -n 1 | cut -c6-)
    if [ "$STUB_MODE" = ok ]; then printf 'ok   %s\r\n' "$dst"; else printf 'FAIL %s\r\n' "$dst"; fi ;;
  *"exec-out"*"catch_dust.json"*)   # deploy.sh reads the phone's stardust table: STUB_DUST = a file to answer with
    case "${STUB_DUST:-}" in silent) exit 1 ;; none|"") ;; *) cat "$STUB_DUST" ;; esac
    echo END-OF-DUST-TABLE ;;
esac
exit 0
'''
failed = 0


def check(name, got, want):
    global failed
    ok = got == want
    failed += not ok
    print(("ok   " if ok else "FAIL ") + name.ljust(46), repr(got), "" if ok else f"  want {want!r}")


GW = os.path.join(HERE, os.pardir, "system", "scripts", "game_write")
TABLE, TREL = os.path.join(GW, "catch_dust.json"), "system/scripts/game_write/catch_dust.json"


def run(mode, *files, dust=TABLE, deploy=DEPLOY, update="1"):
    """dust = what the fake phone holds as its stardust table: a file, "none", or "silent" (adb gives no answer at all).
    update "1" = the table's own update step is skipped (CATCH_DUST_NO_UPDATE): a test never downloads or rewrites it."""
    d = tempfile.mkdtemp()
    stub = os.path.join(d, "adb")
    with open(stub, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(STUB)
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log = os.path.join(d, "calls.log")
    open(log, "w").close()
    env = dict(os.environ, STUB_MODE=mode, STUB_LOG=log, PATH=d + os.pathsep + os.environ.get("PATH", ""),
               STUB_DUST=dust.replace("\\", "/"), CATCH_DUST_NO_UPDATE=update, CATCH_DUST_NO_NET="1")
    # the full path: on Windows a bare "bash" is System32\bash.exe (WSL), not Git Bash
    r = subprocess.run([shutil.which("bash") or "bash", deploy, *files], capture_output=True, text=True, env=env, timeout=120)
    calls = open(log, encoding="utf-8").read().splitlines()
    shutil.rmtree(d, ignore_errors=True)
    return r, calls


F1, F2 = "system/scripts/game_write/catch_loop_fast.py", "catcher_ctl.sh"
r, calls = run("ok", "--restart", F1)
check("good copy: exit 0", r.returncode, 0)
check("good copy: restarted", sum("catcher_ctl.sh restart" in c for c in calls), 1)
check("good copy: old .pyc removed", sum("__pycache__" in c for c in calls), 1)
r, calls = run("FAIL", "--restart", F1)
check("bad copy: exit 1", r.returncode, 1)
check("bad copy: never restarted", sum("catcher_ctl.sh restart" in c for c in calls), 0)
check("bad copy: says STOPPED", "STOPPED at " + F1 in r.stderr, True)
r, calls = run("FAIL", "--restart", F1, F2)
check("bad first file: the next is not pushed", sum(" push " in f" {c} " for c in calls), 1)
r, calls = run("ok", F1, F2)
check("two good files, no --restart: exit 0", r.returncode, 0)
check("two good files: both pushed, no restart", (sum(" push " in f" {c} " for c in calls), sum("restart" in c for c in calls)), (2, 0))
r, calls = run("ok", "--restart", "pogo_il2cpp.py")
check("desktop pogo_il2cpp.py refused", (r.returncode, len(calls)), (2, 0))

# ---- a script lands runnable: the app runs catcher_ctl.sh as a program (a 644 copy = every switch dead)
H = "/data/data/com.termux/files/home/pogo"
SH, OTHER = [F2, "run_catch.sh", "tools/gym_send.sh"], [F1, "tools/GYM.md"]
r, calls = run("ok", *SH, *OTHER)
step = lambda f: [c for c in calls if f" cp /data/local/tmp/ac_{os.path.basename(f)} {H}/{f}.tmp && " in c]
check("modes: five files, each copied once", (r.returncode, [len(step(f)) for f in SH + OTHER]), (0, [1] * 5))
for f in SH:
    c = "".join(step(f))
    check(f"modes: {f} is made 744 as its .tmp, then moved into place",
          (f"chown 10762:10762 {H}/{f}.tmp && chmod 744 {H}/{f}.tmp && mv {H}/{f}.tmp {H}/{f} && " in c, c.count("chmod")), (True, 1))
for f in OTHER:
    c = "".join(step(f))
    check(f"modes: {f} gets no chmod: its copy step is as before",
          (f"chown 10762:10762 {H}/{f}.tmp && mv {H}/{f}.tmp {H}/{f} && " in c, c.count("chmod")), (True, 0))
r, calls = run("FAIL", F2)
check("modes: a script whose copy fails still stops the deploy", (r.returncode, "STOPPED at " + F2 in r.stderr), (1, True))

# ---- STARDUST ONLY's species table rides along (Benny 11-18: "make sure that table is always updated")
sys.path.insert(0, GW)
import catch_dust_table as dt  # noqa: E402
pushes = lambda calls: [c.split(" push ")[1].split()[-1] for c in calls if " push " in f" {c} "]
landed = lambda calls: sum(f"ok   {TREL}" in c for c in calls)
said = lambda r: [ln.split(" -- ")[0] for ln in r.stderr.splitlines() if ln.startswith("DUST TABLE:")]
asked = lambda calls: [i for i, c in enumerate(calls) if "exec-out" in c and "catch_dust.json" in c]
r, calls = run("ok", "--restart", F1)
check("table: the phone's is the same -> not pushed, said", (r.returncode, pushes(calls), said(r)),
      (0, ["/data/local/tmp/ac_catch_loop_fast.py"], ["DUST TABLE: the phone's table is the same"]))
check("table: the phone's copy is read once, before any push",
      (len(asked(calls)), asked(calls)[:1] < [i for i, c in enumerate(calls) if " push " in f" {c} "][:1]), (1, True))
r, calls = run("ok", "--restart", F1, dust="none")
check("table: the phone has none -> pushed after the named files, lands at its own path, then the restart",
      (r.returncode, pushes(calls), landed(calls), sum("catcher_ctl.sh restart" in c for c in calls), said(r)),
      (0, ["/data/local/tmp/ac_catch_loop_fast.py", "/data/local/tmp/ac_catch_dust.json"], 1, 1, ["DUST TABLE: the phone has no table"]))
check("table: only the .py gets its old .pyc removed", sum("__pycache__" in c for c in calls), 1)
t = dt.read_table(TABLE)
dd = tempfile.mkdtemp()
older, newer = os.path.join(dd, "older.json"), os.path.join(dd, "newer.json")
low = min(t["dust"])
for path, batch, d2 in ((older, t["batch"] - 1000, {**t["dust"], low: t["dust"][low] + 200}), (newer, t["batch"] + 1000, t["dust"])):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write(dt.table_text(d2, t["names"], batch))
r, calls = run("ok", F1, dust=older)
check("table: the phone's is an older batch -> pushed", (r.returncode, landed(calls), said(r)[:1]), (0, 1, [f"DUST TABLE: the phone's table differs (its batch {t['batch'] - 1000}, this one {t['batch']})"]))
r, calls = run("ok", F1, dust=newer)
check("table: the phone's is a NEWER batch (it updates itself) -> never replaced", (r.returncode, landed(calls), said(r)[:1]),
      (0, 0, [f"DUST TABLE: the phone's table is NEWER (batch {t['batch'] + 1000} > {t['batch']}): not replaced"]))
r, calls = run("ok", "--restart", F1, dust="silent")
check("table: adb gives no answer -> not pushed, the deploy goes on as before",
      (r.returncode, pushes(calls), sum("catcher_ctl.sh restart" in c for c in calls), said(r)),
      (0, ["/data/local/tmp/ac_catch_loop_fast.py"], 1, ["DUST TABLE: the phone did not answer"]))
r, calls = run("ok", TREL, F1, dust="none")
check("table: named by hand -> pushed once, not twice", (r.returncode, landed(calls), len(pushes(calls))), (0, 1, 2))
r, calls = run("FAIL", "--restart", F1, dust="none")
check("table: a bad copy of a named file still stops everything -- the table is not pushed after it, nothing restarts",
      (r.returncode, pushes(calls), sum("catcher_ctl.sh restart" in c for c in calls)), (1, ["/data/local/tmp/ac_catch_loop_fast.py"], 0))
# the update step itself, in a copy of the tree (a test must never rewrite the tracked table): no network here -> kept
tree = os.path.join(dd, "ac")
os.makedirs(os.path.join(tree, "system", "scripts", "game_write"))
shutil.copy(DEPLOY, os.path.join(tree, "deploy.sh"))
for name in ("catch_dust_table.py", "catch_dust.json", "catch_loop_fast.py"):
    shutil.copy(os.path.join(GW, name), os.path.join(tree, "system", "scripts", "game_write", name))
tcopy = os.path.join(tree, "system", "scripts", "game_write", "catch_dust.json")
before = open(tcopy, "rb").read()
r, calls = run("ok", F1, dust=tcopy, deploy=os.path.join(tree, "deploy.sh"), update="0")
check("table: every deploy runs its update first (here: no network, so it is kept), then asks the phone",
      (r.returncode, said(r), open(tcopy, "rb").read() == before, os.path.exists(tcopy.replace(".json", ".state.json")), pushes(calls)),
      (0, ["DUST TABLE: upstream not asked", "DUST TABLE: the phone's table is the same"], True, True, ["/data/local/tmp/ac_catch_loop_fast.py"]))
shutil.rmtree(dd, ignore_errors=True)
sys.exit(1 if failed else 0)
