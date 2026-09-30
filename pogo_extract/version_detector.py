"""Detect installed PoGo version + reconcile against pogo_offsets.json."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = "com.nianticlabs.pokemongo"
OFFSETS_PATH = Path(__file__).with_name("pogo_offsets.json")
STATE_PATH = Path(__file__).with_name(".pogo_version_state.json")


def adb_dumpsys_versionname(package: str = PACKAGE) -> str:
    """Return the installed app's versionName, e.g. '0.359.0'.

    Raises RuntimeError if the package is not installed or adb is unreachable.
    """
    try:
        out = subprocess.check_output(
            ["adb", "shell", "dumpsys", "package", package],
            stderr=subprocess.STDOUT,
            timeout=15,
        ).decode("utf-8", errors="replace")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise RuntimeError(f"adb dumpsys failed: {e}") from e

    m = re.search(r"^\s*versionName=(\S+)", out, re.MULTILINE)
    if not m:
        raise RuntimeError(f"versionName not found in dumpsys for {package}")
    return m.group(1)


def adb_dumpsys_versioncode(package: str = PACKAGE) -> int | None:
    try:
        out = subprocess.check_output(
            ["adb", "shell", "dumpsys", "package", package],
            stderr=subprocess.STDOUT,
            timeout=15,
        ).decode("utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(r"versionCode=(\d+)", out)
    return int(m.group(1)) if m else None


def load_offsets() -> dict:
    with open(OFFSETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_offsets(data: dict) -> None:
    tmp = OFFSETS_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, OFFSETS_PATH)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def reconcile(installed_version: str, offsets: dict, state: dict) -> dict:
    """Compare installed version against last seen + known map.

    Returns a dict with the following keys:
      installed:       current versionName (str)
      last_seen:       previous versionName we ran against (str | None)
      known:           is the installed version in the JSON known_good set
      status:          one of {first_run, same, version_bump, unknown_version}
      action_required: one of {none, drift_check, full_validation}
    """
    known_versions = set(offsets.get("versions", {}).keys())
    last_seen = state.get("last_seen_version")
    is_known = installed_version in known_versions

    if last_seen is None:
        status = "first_run"
    elif last_seen == installed_version:
        status = "same"
    else:
        status = "version_bump"

    if status == "same" and is_known:
        action = "none"
    elif is_known:
        action = "drift_check"
    else:
        action = "full_validation"

    return {
        "installed": installed_version,
        "last_seen": last_seen,
        "known": is_known,
        "status": status,
        "action_required": action,
    }


def mark_run(installed_version: str) -> None:
    state = load_state()
    state["last_seen_version"] = installed_version
    state["last_seen_at"] = int(time.time())
    save_state(state)


def main() -> int:
    try:
        v = adb_dumpsys_versionname()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    offsets = load_offsets()
    state = load_state()
    info = reconcile(v, offsets, state)

    print(f"installed:       {info['installed']}")
    print(f"last_seen:       {info['last_seen']}")
    print(f"known_good:      {info['known']}")
    print(f"status:          {info['status']}")
    print(f"action_required: {info['action_required']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
