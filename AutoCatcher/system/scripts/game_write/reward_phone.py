"""On-device launcher for the Field-Research reward catcher (same trick as catch_phone.py):
monkey-patch pg.get_session() to attach to the local loopback gadget so reward_catcher.py runs
ON THE PHONE, driven by the app's "Catch Rewards" button instead of a desktop session.

The reward catcher needs the gadget to itself (single client), so catcher_ctl.sh stops the
auto-catcher around this and restores the toggles afterwards.

Writes a one-line result to /data/local/tmp/pogo_rewards.txt for the app UI to display.
Run: LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib python3.13 reward_phone.py [MAX] [--dry]
"""
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)

import frida  # noqa: E402
import pogo_il2cpp as pg  # noqa: E402

STATUS = "/data/local/tmp/pogo_rewards.txt"   # app reads this (world-writable, pre-created by root)

_dm = frida.get_device_manager()


def _status(txt):
    """Publish a single status line for the app UI. Best-effort; never fatal."""
    try:
        with open(STATUS, "w") as fh:
            fh.write(txt.strip()[:300] + "\n")
    except Exception:
        pass


def _dev():
    try:
        return _dm.add_remote_device(pg.FRIDA_REMOTE)
    except Exception:
        for d in _dm.enumerate_devices():
            nm = getattr(d, "name", "") or ""
            if pg.FRIDA_REMOTE in nm or getattr(d, "id", "") == "socket@" + pg.FRIDA_REMOTE:
                return d
        raise


def phone_get_session(retries=3):
    last = None
    for _ in range(max(1, retries)):
        try:
            dev = _dev()
            sess = dev.attach("Gadget")
            pid = 0
            try:
                for p in dev.enumerate_processes():
                    if p.name == "Gadget":
                        pid = p.pid
                        break
            except Exception:
                pass
            return sess, pid
        except Exception as e:
            last = e
    raise last or RuntimeError("phone attach failed")


pg.get_session = phone_get_session

_status(f"running... (started {time.strftime('%H:%M:%S')})")
sys.path.insert(0, HERE)
try:
    import reward_catcher  # noqa: E402,F401  (module-level main() does the work)
except SystemExit:
    raise
except Exception as e:
    # The most common real-world failure is the lazily-created QuestStateManager being absent
    # because Field Research / "Today" was never opened after a PoGo restart. Say so plainly.
    msg = str(e)
    if "singleton" in msg.lower() or "qsm" in msg.lower():
        _status("FAILED: open Field Research (Today) in PoGo first, then tap again")
    else:
        _status(f"FAILED: {type(e).__name__}: {msg[:120]}")
    traceback.print_exc()
    sys.exit(1)

# reward_catcher writes its own detailed log; summarise the last line for the UI.
try:
    logp = os.path.join(ROOT, "system", "analysis", "pokemod", "reward_catch.log")
    tail = ""
    with open(logp, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if "OPERATION DONE" in ln:
                tail = ln.strip()
    import re
    # Read the LAST outcome line of this run — never assume success. A failed/stuck pass previously
    # published "done", which is precisely the silent failure this status line exists to prevent.
    outcome = ""
    with open(logp, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if ("OPERATION DONE" in ln or "NOT READY" in ln or "READY:" in ln
                    or "DRY result" in ln or "MISSING" in ln):
                outcome = ln.strip()
    now = time.strftime("%H:%M:%S")
    if "OPERATION DONE" in outcome:
        c = re.search(r"caught_total=(\d+)", outcome)
        secs = re.search(r"in ([0-9.]+)s", outcome)
        dust = re.search(r"dust \d+->\d+ \(\+(\d+)", outcome)
        n = c.group(1) if c else "?"
        if n == "0":
            _status(f"done: nothing left to catch @ {now}")
        else:
            _status("done: caught {} in {}s{} @ {}".format(
                n, secs.group(1) if secs else "?",
                f", +{dust.group(1)} dust" if dust else "", now))
    elif "reason=stuck" in outcome or "STUCK:" in outcome:
        c = re.search(r"caught_total=(\d+)", outcome)
        _status(f"STUCK: one reward wouldn't catch; got {c.group(1) if c else '?'} — tap again @ {now}")
    elif "MISSING" in outcome or "no_qsm" in outcome:
        _status(f"FAILED: open Field Research (Today) in PoGo, then tap again @ {now}")
    elif "NOT READY" in outcome or "reason=error" in outcome:
        err = re.search(r"errs=\[([^\]]*)\]", outcome)
        _status(f"FAILED: {err.group(1)[:90] if err else 'not ready'} @ {now}")
    elif "READY" in outcome or "reason=dry_check" in outcome:
        waiting = "dangling_type=None" not in outcome
        _status(f"ready: {'rewards waiting' if waiting else 'nothing waiting'} (dry check ok) @ {now}")
    else:
        _status(f"finished, no outcome line @ {now}")
except Exception as e:
    _status(f"FAILED: status read: {type(e).__name__} @ {time.strftime('%H:%M:%S')}")
