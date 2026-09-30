"""On-device launcher: runs the EXACT desktop catcher (catch_loop_fast.py) on the
phone by monkey-patching pg.get_session() to attach to the local loopback gadget
('Gadget' over 127.0.0.1:27047) instead of the desktop's adb-forward + pidof path.
Everything else (catch JS, re-throw, berry, dust tracking, telemetry) is unchanged.
Run with: LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib python3.13 catch_phone.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, ROOT)

import frida  # noqa: E402
import pogo_il2cpp as pg  # noqa: E402

_dm = frida.get_device_manager()


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
    """Attach to the local gadget. Returns (frida.Session, pid) like the original."""
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

# Hand off to the real catcher (its module-level main() runs on import).
sys.path.insert(0, HERE)
import catch_loop_fast  # noqa: E402,F401
