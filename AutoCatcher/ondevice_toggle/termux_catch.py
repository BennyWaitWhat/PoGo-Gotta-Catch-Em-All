#!/data/data/com.termux/files/usr/bin/python
"""termux_catch.py — PRIMARY on-device autonomous catcher (Termux-attach path).

Runs the PROVEN desktop catcher (catch_loop_fast.py + pogo_il2cpp.py) ON THE PHONE,
attaching to the ZygiskFrida gadget's own LISTEN socket at 127.0.0.1:27047. This
sidesteps QuickJS gadget *script* mode entirely and reuses the exact off-thread
architecture that has never crashed PoGo:

  - the catch logic runs in the gadget over the wire (the same JS the desktop injects),
  - the Unity stop-the-world GC liveness walk runs on THIS Python host thread in a
    transient script (pogo_il2cpp.liveness_find_instances), NEVER from PoGo's render
    frame — which is the structural property the broken in-process port violated.

WHY THIS IS THE PRIMARY PATH (not catch.js script mode):
  The in-process catch.js must self-find singletons via il2cpp_stop_gc_world from
  inside the process. Every in-process variant either (a) stops the GC world from the
  render thread (the original catch.js — caused the multi-thread pc==fault storm), or
  (b) calls Frida's single-threaded QuickJS runtime from a raw pthread_create worker
  (the catch.hardened.js worker model — calling GumJS from a thread Frida never
  created is undefined behavior). The Termux path has NEITHER hazard: the GC walk runs
  on a proper Frida-managed host thread, decoupled from the frame pump, exactly as on
  the desktop. It is the lowest-risk way to get reliable on-device catching, and it
  doubles as the control that proves the catch LOGIC is fine on this device/gadget.

PREREQUISITES (Termux, root present):
  pkg install python
  pip install frida            # match the gadget MAJOR (the device gadget is a 17.x
                               # fork "200046.1.1"; install a 17.x frida client)
  # Gadget must be in LISTEN mode (its historical/default config):
  su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
  su -c 'am force-stop com.nianticlabs.pokemongo'
  su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
  # Foreground PoGo on the live map, THEN run this.

USAGE (Termux):
  # from anywhere; this file lives in the repo subtree it imports from:
  python /sdcard/pogo_extract/system/ondevice_toggle/termux_catch.py
  # or wherever you placed the pogo_extract tree on-device. Ctrl-C to stop.

It changes NO gadget config and writes NO marker. It only ATTACHES. Ctrl-C ends it;
PoGo keeps running and the desktop can still attach on 27047 afterwards.
"""
import os
import sys
import subprocess
import importlib.util

# --- Locate the proven sources (this file sits in system/ondevice_toggle/) ---
HERE = os.path.dirname(os.path.abspath(__file__))
# ROOT = .../pogo_extract  (three dirs up: ondevice_toggle -> system -> pogo_extract)
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
# Allow override if the tree is placed elsewhere on-device.
ROOT = os.environ.get("POGO_ROOT", ROOT)
sys.path.insert(0, ROOT)

import frida  # noqa: E402
import pogo_il2cpp as pg  # noqa: E402

POGO_PKG = pg.POGO_PKG
FRIDA_REMOTE = pg.FRIDA_REMOTE  # '127.0.0.1:27047' — the gadget's local listen socket


def _local_pidof():
    """PoGo PID via a LOCAL pidof (Termux). Tries plain, then root. None if down.

    Only used as a fallback / sanity print — the real attach resolves the PID via
    the gadget's own enumerate_processes() (see get_session_local), which needs no
    adb and no pidof at all.
    """
    for cmd in (["pidof", POGO_PKG], ["su", "-c", "pidof " + POGO_PKG]):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
            if out:
                return int(out.split()[0])
        except Exception:
            pass
    return None


def get_session_local(retries=6):
    """ADB-free attach to the local gadget listen socket.

    Mirrors the proven in-repo pattern (capture_setpokemontags.py:5):
        d = frida.get_device_manager().add_remote_device('127.0.0.1:27047')
        sess = d.attach(d.enumerate_processes()[0].pid)
    The gadget injected into PoGo is the ONLY process the listen socket exposes, so
    enumerate_processes() yields exactly it. No adb connect/forward/pidof needed
    because the socket is already on this device's loopback.

    Returns (frida.Session, int pid). Raises RuntimeError on failure.
    Signature-compatible with pg.get_session so catch_loop_fast.py is unchanged.
    """
    import time
    last = "no attempt"
    for i in range(retries):
        try:
            dev = frida.get_device_manager().add_remote_device(FRIDA_REMOTE)
            procs = dev.enumerate_processes()
            if not procs:
                last = "gadget listen socket exposes no process (PoGo not up in LISTEN mode?)"
                time.sleep(3)
                continue
            # Prefer an explicit PoGo match if the gadget ever lists more than one;
            # otherwise take the sole entry (the injected PoGo) like the proven scripts.
            cand = [p for p in procs if "pokemongo" in (p.name or "").lower()]
            pid = (cand[0].pid if cand else procs[0].pid)
            sess = dev.attach(pid)
            return sess, pid
        except Exception as e:
            last = str(e)
            if i == 0:
                print("waiting for gadget on %s ... (%s)" % (FRIDA_REMOTE, last[:60]))
            time.sleep(3)
    raise RuntimeError(
        "Termux attach to %s failed: %s\n"
        "  - Is the gadget in LISTEN mode? "
        "(cp config.listen.so libgadget.config.so + relaunch PoGo)\n"
        "  - Is PoGo running and foregrounded?\n"
        "  - Does the Termux frida client major match the gadget (17.x)?"
        % (FRIDA_REMOTE, last)
    )


# --- Monkey-patch the two adb-dependent helpers BEFORE importing the catcher. ---
# catch_loop_fast.py only reaches the device through pg.get_session(); pg._adb_pidof
# is patched too for any incidental use. The host-thread / transient-script liveness
# architecture (the part the in-process port broke) is left 100% intact.
pg.get_session = get_session_local
pg._adb_pidof = lambda dev=None: _local_pidof()


def main():
    pid_hint = _local_pidof()
    print("=== Termux-attach catcher ===")
    print("ROOT      :", ROOT)
    print("gadget    :", FRIDA_REMOTE, "(listen mode required)")
    print("PoGo pid  :", pid_hint if pid_hint else "(unknown via pidof; will use gadget enumerate)")
    if pid_hint is None:
        print("note: pidof returned nothing — that's OK if PoGo is up; the gadget enumerate"
              " will still find it. If attach fails, confirm PoGo is running + LISTEN mode.")
    # Run the PROVEN catcher unchanged. catch_loop_fast.py calls main() at import time,
    # which connects, installs, finds singletons off-thread, and loops with self-reconnect.
    catch_path = os.path.join(ROOT, "system", "scripts", "game_write", "catch_loop_fast.py")
    if not os.path.exists(catch_path):
        raise SystemExit("catch_loop_fast.py not found at %s (set POGO_ROOT to the pogo_extract dir)" % catch_path)
    spec = importlib.util.spec_from_file_location("catch_loop_fast", catch_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # runs its module-level main()


if __name__ == "__main__":
    main()
