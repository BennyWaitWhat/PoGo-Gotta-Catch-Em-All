"""Offline test of AutoCatcher/deploy.sh against a fake adb (no phone): python tools/deploy_sim.py
The fake adb logs every call and answers the phone's md5 step with "ok <dst>" or "FAIL <dst>" (STUB_MODE), with the CR
line endings a real `adb shell` can add. Checks: a good copy restarts with --restart; a bad copy stops at once with
exit 1, never restarts and never pushes the next file; the desktop pogo_il2cpp.py is still refused.
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
esac
exit 0
'''
failed = 0


def check(name, got, want):
    global failed
    ok = got == want
    failed += not ok
    print(("ok   " if ok else "FAIL ") + name.ljust(46), repr(got), "" if ok else f"  want {want!r}")


def run(mode, *files):
    d = tempfile.mkdtemp()
    stub = os.path.join(d, "adb")
    with open(stub, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(STUB)
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log = os.path.join(d, "calls.log")
    open(log, "w").close()
    env = dict(os.environ, STUB_MODE=mode, STUB_LOG=log, PATH=d + os.pathsep + os.environ.get("PATH", ""))
    # the full path: on Windows a bare "bash" is System32\bash.exe (WSL), not Git Bash
    r = subprocess.run([shutil.which("bash") or "bash", DEPLOY, *files], capture_output=True, text=True, env=env, timeout=120)
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
sys.exit(1 if failed else 0)
