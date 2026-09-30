"""Thin retry wrapper around PID-drift issues in pogo_il2cpp."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import time
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pogo_il2cpp as pg

ADB_TARGET = pg.ADB_TARGET
POGO_PKG = pg.POGO_PKG


def _pidof():
    """Return PoGo PID via adb or None."""
    try:
        out = subprocess.check_output(
            ['adb', '-s', ADB_TARGET, 'shell', 'pidof', POGO_PKG],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return int(out) if out else None
    except (subprocess.CalledProcessError, ValueError):
        return None


def session(retries=4, backoff=3):
    """get_session() with PID-drift retry and adb pidof pre-check.

    Returns (frida.Session, int pid).
    Raises RuntimeError after exhausting retries.
    """
    last_err = None
    for attempt in range(1, retries + 1):
        pid = _pidof()
        if not pid:
            if attempt < retries:
                time.sleep(backoff * attempt)
                continue
            raise RuntimeError(
                f'PoGo not running after {retries} attempts '
                f'(pidof {POGO_PKG} returned nothing)'
            )
        try:
            return pg.get_session()
        except (RuntimeError, Exception) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(
        f'Could not attach to PoGo after {retries} retries: {last_err}'
    )


def pick(sess, ns, cls):
    """pick_singleton with one retry on transient failure."""
    try:
        return pg.pick_singleton(sess, ns, cls)
    except RuntimeError:
        time.sleep(1)
        return pg.pick_singleton(sess, ns, cls)
