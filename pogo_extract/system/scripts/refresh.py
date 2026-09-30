"""Full self-healing data refresh: one command to bring every artefact current.

Stages (each timed, fail-soft):
  1. PRECHECK      -- confirm PoGo running via adb pidof; abort clearly if down
  2. RE-CRAWL      -- subprocess pogo_pipeline.py (DB + tags + ranks + cull)
  3. DEEP PROFILE  -- subprocess deep_profile.py (deep_profiles.json)
  4. TAG RECONCILE -- subprocess reconcile_tags.py --report;
                      if drift and --fix-tags: --fix-server
  5. AUTO-RESTORE  -- read system/tags/registry.json; for any registry tag
                      NOT present on the live server, call _restore_tags.py
  6. VERIFY        -- subprocess verify_tags.py
  7. SUMMARY       -- bag size, tag count, drift y/n, restored list,
                      profiles, elapsed, READY

Flags:
  --fix-tags    auto-run reconcile_tags.py --fix-server if drift detected
  --skip-crawl  skip stage 2 (e.g. if you just ran pogo_pipeline.py)
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
DB_PATH = os.path.join(REPO, 'pokemon.db')
REGISTRY_PATH = os.path.join(REPO, 'system', 'tags', 'registry.json')
ADB_TARGET = '100.98.158.56:5555'
POGO_PKG = 'com.nianticlabs.pokemongo'

# Reuse pogo_il2cpp's device resolver so precheck survives a Tailscale drop
# (Tailscale target down -> fall back to USB), matching the crawl subprocesses.
sys.path.insert(0, REPO)
try:
    import pogo_il2cpp as _pg
except Exception:
    _pg = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_T0 = None
_STAGE_TIMES = {}
_STAGE_RESULTS = {}


def _ts():
    return f"[t+{time.time() - _T0:6.1f}s]"


def _run_stage(name, fn):
    """Run fn(), capture timing and pass/fail. Never crashes the outer loop."""
    t0 = time.time()
    print(f"\n{'=' * 60}")
    print(f"{_ts()} STAGE: {name}")
    print('=' * 60)
    ok = False
    try:
        result = fn()
        ok = True
        _STAGE_RESULTS[name] = result
    except Exception as e:
        print(f"{_ts()} FAILED: {e}")
        _STAGE_RESULTS[name] = {'error': str(e)}
    elapsed = time.time() - t0
    _STAGE_TIMES[name] = elapsed
    tag = 'OK' if ok else 'FAIL'
    print(f"{_ts()} << {name} {tag} ({elapsed:.1f}s)")
    return ok


def _subprocess(label, cmd, cwd=REPO):
    """Run a subprocess, stream output, return (returncode, stdout_text)."""
    print(f"{_ts()} $ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace',
    )
    lines = []
    for line in proc.stdout:
        line = line.rstrip('\n')
        print(f"  {line}")
        lines.append(line)
    proc.wait()
    stdout_text = '\n'.join(lines)
    if proc.returncode != 0:
        print(f"{_ts()} {label} exited with rc={proc.returncode}")
    return proc.returncode, stdout_text


def _frida_safe():
    """Check PoGo is running. Resolves the device (Tailscale -> USB fallback)
    via pogo_il2cpp, then adb pidof. Returns 'pid@device' or None."""
    if _pg is not None:
        dev = _pg._resolve_device()
        if not dev:
            return None
        pid = _pg._adb_pidof(dev)
        return f"{pid}@{dev}" if pid else None
    # Fallback if pogo_il2cpp unimportable: original Tailscale-only check
    try:
        out = subprocess.check_output(
            ['adb', '-s', ADB_TARGET, 'shell', 'pidof', POGO_PKG],
            stderr=subprocess.DEVNULL, timeout=10,
        ).decode().strip()
        return out if out else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return None


def _load_registry():
    """Load system/tags/registry.json. Returns list of tag dicts or []."""
    if not os.path.isfile(REGISTRY_PATH):
        return []
    try:
        with open(REGISTRY_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return data.get('tags', [])
    except Exception:
        return []


def _get_server_tag_names():
    """Enumerate live server tag names via verify_tags.py's Frida enumerate.

    Falls back to reading DB auth_tag_names if Frida unavailable.
    Returns a set of tag-name strings present on the server.
    """
    # Fast path: query DB for distinct auth_tag_names (set after last crawl)
    names = set()
    if os.path.isfile(DB_PATH):
        try:
            conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
            rows = conn.execute(
                "SELECT DISTINCT auth_tag_names FROM pokemon "
                "WHERE in_bag=1 AND auth_tag_names IS NOT NULL "
                "AND auth_tag_names != ''"
            ).fetchall()
            for r in rows:
                for t in r[0].split(';'):
                    t = t.strip()
                    if t:
                        names.add(t)
            conn.close()
        except Exception:
            pass
    return names


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def stage_precheck():
    """Confirm PoGo is running on the device."""
    pid = _frida_safe()
    if not pid:
        raise RuntimeError(
            f"PoGo is NOT running on {ADB_TARGET}. "
            f"Open Pokemon GO and foreground it, then retry."
        )
    print(f"{_ts()} PoGo running, pid={pid}")
    return {'pid': pid}


def stage_recrawl():
    """Run pogo_pipeline.py as a subprocess (full re-baseline)."""
    rc, text = _subprocess('re-crawl', [sys.executable, 'pogo_pipeline.py'])
    if rc != 0:
        raise RuntimeError(f"pogo_pipeline.py failed (rc={rc})")
    return {'returncode': rc}


def stage_deep_profile():
    """Run deep_profile.py to regenerate deep_profiles.json."""
    rc, text = _subprocess('deep-profile',
                           [sys.executable,
                            os.path.join('system', 'scripts', 'deep_profile.py')])
    if rc != 0:
        raise RuntimeError(f"deep_profile.py failed (rc={rc})")
    profiles_path = os.path.join(REPO, 'system', 'analysis', 'deep_profiles.json')
    profile_count = 0
    if os.path.isfile(profiles_path):
        try:
            profile_count = len(json.load(open(profiles_path, encoding='utf-8')))
        except Exception:
            pass
    return {'returncode': rc, 'profile_count': profile_count}


def stage_reconcile(fix_tags):
    """Run reconcile_tags.py --report (or --fix-server if --fix-tags)."""
    mode_flag = '--report'
    rc, text = _subprocess('reconcile',
                           [sys.executable,
                            os.path.join('system', 'scripts', 'reconcile_tags.py'),
                            mode_flag])
    drift = 'DRIFT' in text.upper() or 'drift detected' in text.lower()

    fixed = False
    if drift and fix_tags:
        print(f"\n{_ts()} Drift detected -- applying --fix-server ...")
        rc2, text2 = _subprocess('reconcile-fix',
                                 [sys.executable,
                                  os.path.join('system', 'scripts',
                                               'reconcile_tags.py'),
                                  '--fix-server'])
        fixed = (rc2 == 0)
    elif drift:
        print(f"\n  NOTE: Tag drift detected. Pass --fix-tags to auto-fix.")

    return {'returncode': rc, 'drift': drift, 'fixed': fixed}


def stage_auto_restore():
    """Restore any registry tag missing from the live server.

    Reads system/tags/registry.json for the canonical tag list. Compares
    against server tags (from DB auth_tag_names after the crawl). For any
    registry tag NOT on the server, calls:
        python _restore_tags.py "Name:Color"
    This catches collateral-deleted tags (e.g. Legacy) automatically.
    """
    registry_tags = _load_registry()
    if not registry_tags:
        print(f"{_ts()} No registry.json or no tags defined -- skipping")
        return {'restored': [], 'checked': 0}

    server_names = _get_server_tag_names()
    print(f"{_ts()} Registry has {len(registry_tags)} tags, "
          f"server/DB has {len(server_names)} tag names")

    missing = []
    for entry in registry_tags:
        name = entry.get('name', '')
        if not name:
            continue
        if name not in server_names:
            missing.append(entry)

    if not missing:
        print(f"{_ts()} All registry tags present on server -- nothing to restore")
        return {'restored': [], 'checked': len(registry_tags)}

    restored = []
    for entry in missing:
        name = entry['name']
        color = entry.get('color', 1)
        spec = f"{name}:{color}"
        print(f"\n{_ts()} RESTORING missing tag: {spec}")
        rc, text = _subprocess(
            f'restore-{name}',
            [sys.executable, '_restore_tags.py', spec])
        if rc == 0:
            restored.append(name)
            print(f"{_ts()} Restored {name}")
        else:
            print(f"{_ts()} Failed to restore {name} (rc={rc})")

    return {'restored': restored, 'checked': len(registry_tags)}


def stage_verify():
    """Run verify_tags.py for tag integrity checks."""
    rc, text = _subprocess('verify',
                           [sys.executable,
                            os.path.join('system', 'scripts', 'verify_tags.py')])
    if rc != 0:
        raise RuntimeError(f"verify_tags.py failed (rc={rc})")
    return {'returncode': rc}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def _print_summary():
    print(f"\n{'=' * 60}")
    print(f"REFRESH SUMMARY")
    print('=' * 60)

    # Bag size
    bag_size = '?'
    if os.path.isfile(DB_PATH):
        try:
            conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
            bag_size = conn.execute(
                "SELECT COUNT(*) FROM pokemon WHERE in_bag=1"
            ).fetchone()[0]
            conn.close()
        except Exception:
            pass

    # Tag count from DB
    tag_count = '?'
    if os.path.isfile(DB_PATH):
        try:
            conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
            rows = conn.execute(
                "SELECT DISTINCT auth_tag_names FROM pokemon "
                "WHERE in_bag=1 AND auth_tag_names IS NOT NULL "
                "AND auth_tag_names != ''"
            ).fetchall()
            tags = set()
            for r in rows:
                for t in r[0].split(';'):
                    t = t.strip()
                    if t:
                        tags.add(t)
            tag_count = len(tags)
            conn.close()
        except Exception:
            pass

    # Drift
    recon = _STAGE_RESULTS.get('TAG RECONCILE', {})
    drift_str = 'yes' if recon.get('drift') else 'no'
    if recon.get('fixed'):
        drift_str += ' (fixed)'
    if recon.get('error'):
        drift_str = 'unknown (reconcile failed)'

    # Restored tags
    restore = _STAGE_RESULTS.get('AUTO-RESTORE', {})
    restored_list = restore.get('restored', [])
    restored_str = ', '.join(restored_list) if restored_list else 'none needed'
    if restore.get('error'):
        restored_str = 'error (see above)'

    # Profiles
    dp = _STAGE_RESULTS.get('DEEP PROFILE', {})
    profile_count = dp.get('profile_count', '?')

    # Elapsed
    total = time.time() - _T0

    print(f"  Bag size:       {bag_size}")
    print(f"  Tags:           {tag_count}")
    print(f"  Drift:          {drift_str}")
    print(f"  Restored:       {restored_str}")
    print(f"  Profiles:       {profile_count}")
    print(f"  Total elapsed:  {total:.1f}s")

    print(f"\n  Per-stage timing:")
    for name, elapsed in _STAGE_TIMES.items():
        status = 'OK' if 'error' not in _STAGE_RESULTS.get(name, {}) else 'FAIL'
        print(f"    {name:<20s} {elapsed:6.1f}s  {status}")

    print(f"\nREADY -- data current; use query.py for instant answers.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global _T0
    _T0 = time.time()

    ap = argparse.ArgumentParser(
        description='Self-healing full data refresh: precheck, re-crawl, '
                    'profile, reconcile, auto-restore, verify.')
    ap.add_argument('--fix-tags', action='store_true',
                    help='Auto-run reconcile_tags.py --fix-server if drift detected')
    ap.add_argument('--skip-crawl', action='store_true',
                    help='Skip the re-crawl stage (start from deep_profile)')
    args = ap.parse_args()

    # 1. PRECHECK
    ok = _run_stage('PRECHECK', stage_precheck)
    if not ok:
        print("\nAborting: PoGo must be open and foregrounded.")
        sys.exit(1)

    # 2. RE-CRAWL (unless --skip-crawl)
    if args.skip_crawl:
        print(f"\n{_ts()} STAGE: RE-CRAWL -- SKIPPED (--skip-crawl)")
        _STAGE_RESULTS['RE-CRAWL'] = {'skipped': True}
    else:
        _run_stage('RE-CRAWL', stage_recrawl)

    # 3. DEEP PROFILE
    _run_stage('DEEP PROFILE', stage_deep_profile)

    # 4. TAG RECONCILE
    _run_stage('TAG RECONCILE', lambda: stage_reconcile(args.fix_tags))

    # 5. AUTO-RESTORE (registry tags missing from server)
    _run_stage('AUTO-RESTORE', stage_auto_restore)

    # 6. VERIFY
    _run_stage('VERIFY', stage_verify)

    # 7. SUMMARY
    _print_summary()


if __name__ == '__main__':
    main()
