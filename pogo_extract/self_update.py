"""Continuous self-update runner for the PoGo toolkit.

Steps:
  1. Run pogo_pipeline.py (Frida, phone must be reachable)
  2. Run account_snapshot.py (writes account_snapshot.json)
  3. Diff new snapshot vs previous (stored in snapshots/)
  4. Write dated changelog to snapshots/changelog_YYYYMMDD_HHMMSS.txt
  5. Send Telegram summary of meaningful changes

Usage:
    python self_update.py [--dry-run] [--skip-pipeline] [--skip-snapshot]

    --dry-run        Pass --dry-run to pipeline; still diffs and notifies.
    --skip-pipeline  Skip step 1 (useful if pipeline just ran externally).
    --skip-snapshot  Skip step 2 (reuse current account_snapshot.json).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent.resolve()
SNAPSHOTS_DIR = HERE / 'snapshots'
SNAPSHOT_LIVE = HERE / 'account_snapshot.json'

TELEGRAM_CHAT_ID = '8749793156'
TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'

MAX_PHONE_RETRIES = 2
RETRY_DELAY_S = 30


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(label, args, retries=MAX_PHONE_RETRIES, retry_delay=RETRY_DELAY_S):
    """Run a subprocess. Returns (returncode, stdout+stderr text).

    Retries on non-zero exit up to `retries` times, interpreting a non-zero
    return as a transient phone/frida error. On final failure returns the
    last (returncode, output) without raising.
    """
    cmd = [sys.executable] + [str(a) for a in args]
    attempt = 0
    while True:
        attempt += 1
        print(f'[self_update] {label}: running (attempt {attempt})')
        result = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode == 0:
            print(f'[self_update] {label}: ok')
            return 0, output
        print(f'[self_update] {label}: exit {result.returncode}')
        print(output[-500:] if len(output) > 500 else output)
        if attempt > retries:
            return result.returncode, output
        print(f'[self_update] retrying in {retry_delay}s...')
        time.sleep(retry_delay)


# ---------------------------------------------------------------------------
# Snapshot archiving
# ---------------------------------------------------------------------------

def _archive_snapshot(ts_str):
    """Copy account_snapshot.json into snapshots/snapshot_<ts>.json. Returns path."""
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    dest = SNAPSHOTS_DIR / f'snapshot_{ts_str}.json'
    if SNAPSHOT_LIVE.exists():
        shutil.copy2(str(SNAPSHOT_LIVE), str(dest))
        print(f'[self_update] archived snapshot -> {dest.name}')
    return dest


def _load_prev_snapshot():
    """Load the most recent archived snapshot (second-most-recent after archiving).

    Returns parsed dict or None.
    """
    if not SNAPSHOTS_DIR.exists():
        return None
    files = sorted(SNAPSHOTS_DIR.glob('snapshot_*.json'))
    # The newest one is the one just archived; prev is the one before it.
    if len(files) < 2:
        return None
    try:
        with open(str(files[-2])) as f:
            return json.load(f)
    except Exception as e:
        print(f'[self_update] could not load prev snapshot: {e}')
        return None


def _load_snapshot(path):
    """Load snapshot from path, return dict or None."""
    try:
        with open(str(path)) as f:
            return json.load(f)
    except Exception as e:
        print(f'[self_update] could not load snapshot {path}: {e}')
        return None


# ---------------------------------------------------------------------------
# Diff logic
# ---------------------------------------------------------------------------

def _diff_snapshots(prev, curr):
    """Compare two snapshot dicts. Returns list of human-readable change strings.

    Understands these top-level keys (all optional, skipped if absent):
      pokemon_count, pokedex_seen, pokedex_caught,
      stardust, coins, candy (dict pid->count),
      hundos (list of uid_hex), shinies (list of uid_hex),
      new_shinies (list), new_hundos (list),
      tags (dict tag_name -> list of uid_hex),
      bag (list of {uid_hex, species_name, cp, iv_total, is_shiny, is_hundo})
    """
    if prev is None:
        return ['First run - no previous snapshot to compare.']

    changes = []

    def _delta(key, label, fmt='+{d}'):
        p, c = prev.get(key), curr.get(key)
        if p is None or c is None:
            return
        d = c - p
        if d == 0:
            return
        sign = '+' if d > 0 else ''
        changes.append(f'{label}: {p} -> {c} ({sign}{d})')

    _delta('pokemon_count', 'Pokemon in bag')
    _delta('pokedex_seen', 'Dex seen')
    _delta('pokedex_caught', 'Dex caught')
    _delta('stardust', 'Stardust')
    _delta('coins', 'Coins')

    # Candy deltas (dict pid/name -> count)
    prev_candy = prev.get('candy', {})
    curr_candy = curr.get('candy', {})
    candy_changes = []
    all_keys = set(prev_candy) | set(curr_candy)
    for k in sorted(all_keys):
        p, c = prev_candy.get(k, 0), curr_candy.get(k, 0)
        d = c - p
        if abs(d) >= 5:  # skip noise
            candy_changes.append(f'{k}:{"+"+str(d) if d>0 else str(d)}')
    if candy_changes:
        changes.append('Candy changes: ' + ', '.join(candy_changes[:15])
                       + (f' (+{len(candy_changes)-15} more)' if len(candy_changes) > 15 else ''))

    # New pokemon (uid_hex in bag not in prev bag)
    prev_uids = {p['uid_hex'] for p in prev.get('bag', []) if 'uid_hex' in p}
    curr_bag = curr.get('bag', [])
    new_mons = [p for p in curr_bag if p.get('uid_hex') not in prev_uids]
    if new_mons:
        lines = []
        for p in new_mons[:10]:
            name = p.get('species_name', '?')
            cp = p.get('cp', '?')
            iv = p.get('iv_total', '?')
            flags = []
            if p.get('is_shiny'): flags.append('SHINY')
            if p.get('is_hundo'): flags.append('HUNDO')
            tag = (' [' + ','.join(flags) + ']') if flags else ''
            lines.append(f'{name} CP{cp} IV{iv}{tag}')
        extra = f' (+{len(new_mons)-10} more)' if len(new_mons) > 10 else ''
        changes.append('New pokemon (' + str(len(new_mons)) + '): ' + ', '.join(lines) + extra)

    # Transferred pokemon (in prev bag but not in curr)
    curr_uids = {p['uid_hex'] for p in curr_bag if 'uid_hex' in p}
    prev_bag = prev.get('bag', [])
    gone = [p for p in prev_bag if p.get('uid_hex') not in curr_uids]
    if gone:
        changes.append(f'Transferred/gone: {len(gone)} pokemon')

    # New hundos
    prev_hundos = set(prev.get('hundos', []))
    curr_hundos = set(curr.get('hundos', []))
    new_hundos = curr_hundos - prev_hundos
    if new_hundos:
        # Look up species names from curr bag
        uid_to_name = {p['uid_hex']: p.get('species_name', '?') for p in curr_bag}
        names = [uid_to_name.get(u, u[:8]) for u in list(new_hundos)[:8]]
        changes.append(f'New hundos ({len(new_hundos)}): {", ".join(names)}')

    # New shinies
    prev_shinies = set(prev.get('shinies', []))
    curr_shinies = set(curr.get('shinies', []))
    new_shinies = curr_shinies - prev_shinies
    if new_shinies:
        uid_to_name = {p['uid_hex']: p.get('species_name', '?') for p in curr_bag}
        names = [uid_to_name.get(u, u[:8]) for u in list(new_shinies)[:8]]
        changes.append(f'New shinies ({len(new_shinies)}): {", ".join(names)}')

    # Tag changes
    prev_tags = prev.get('tags', {})
    curr_tags = curr.get('tags', {})
    all_tag_names = set(prev_tags) | set(curr_tags)
    tag_changes = []
    for tag in sorted(all_tag_names):
        p_set = set(prev_tags.get(tag, []))
        c_set = set(curr_tags.get(tag, []))
        added = len(c_set - p_set)
        removed = len(p_set - c_set)
        if added or removed:
            parts = []
            if added: parts.append(f'+{added}')
            if removed: parts.append(f'-{removed}')
            tag_changes.append(f'{tag}({",".join(parts)})')
    if tag_changes:
        changes.append('Tag changes: ' + ', '.join(tag_changes[:12])
                       + (f' (+{len(tag_changes)-12} more)' if len(tag_changes) > 12 else ''))

    return changes if changes else ['No meaningful changes detected.']


# ---------------------------------------------------------------------------
# Changelog writer
# ---------------------------------------------------------------------------

def _write_changelog(ts_str, pipeline_ok, snapshot_ok, changes, pipeline_output):
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    path = SNAPSHOTS_DIR / f'changelog_{ts_str}.txt'
    with open(str(path), 'w', encoding='utf-8') as f:
        f.write(f'=== PoGo self-update {ts_str} ===\n\n')
        f.write(f'Pipeline:  {"OK" if pipeline_ok else "FAILED"}\n')
        f.write(f'Snapshot:  {"OK" if snapshot_ok else "FAILED"}\n\n')
        f.write('Changes:\n')
        for line in changes:
            f.write(f'  {line}\n')
        if not pipeline_ok:
            f.write('\nPipeline tail output:\n')
            f.write(pipeline_output[-1000:] if pipeline_output else '(none)\n')
    print(f'[self_update] changelog -> {path.name}')
    return path


# ---------------------------------------------------------------------------
# Telegram notify
# ---------------------------------------------------------------------------

def _telegram_send(text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        print('[self_update] TELEGRAM_BOT_TOKEN not set - skipping notify')
        return
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = urllib.parse.urlencode({
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
    }).encode()
    try:
        req = urllib.request.Request(url, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        print('[self_update] Telegram notify sent')
    except Exception as e:
        print(f'[self_update] Telegram notify failed: {e}')


def _build_telegram_message(ts_str, pipeline_ok, snapshot_ok, changes):
    header = f'<b>PoGo update {ts_str[:8]} {ts_str[9:]}</b>'
    status_parts = []
    if not pipeline_ok:
        status_parts.append('Pipeline FAILED')
    if not snapshot_ok:
        status_parts.append('Snapshot FAILED')
    if status_parts:
        header += '\n<i>' + ', '.join(status_parts) + '</i>'
    body_lines = []
    for line in changes[:20]:
        body_lines.append(line)
    if len(changes) > 20:
        body_lines.append(f'...and {len(changes)-20} more changes')
    return header + '\n' + '\n'.join(body_lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='PoGo daily self-update runner')
    ap.add_argument('--dry-run', action='store_true',
                    help='pass --dry-run to pipeline (no server writes)')
    ap.add_argument('--skip-pipeline', action='store_true',
                    help='skip running pogo_pipeline.py')
    ap.add_argument('--skip-snapshot', action='store_true',
                    help='skip running account_snapshot.py (reuse existing)')
    args = ap.parse_args()

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    print(f'[self_update] starting at {ts}')

    # Step 1: pipeline
    pipeline_ok = True
    pipeline_output = ''
    if not args.skip_pipeline:
        pipeline_args = ['pogo_pipeline.py']
        if args.dry_run:
            pipeline_args.append('--dry-run')
        rc, pipeline_output = _run('pipeline', pipeline_args)
        pipeline_ok = (rc == 0)
    else:
        print('[self_update] pipeline: skipped')

    # Step 2: snapshot
    snapshot_ok = True
    if not args.skip_snapshot:
        rc, _ = _run('snapshot', ['account_snapshot.py'], retries=1)
        snapshot_ok = (rc == 0)
    else:
        print('[self_update] snapshot: skipped')

    # Step 3: archive new snapshot, load prev
    _archive_snapshot(ts)
    prev = _load_prev_snapshot()
    curr = _load_snapshot(SNAPSHOT_LIVE)

    # Step 4: diff
    if curr is not None:
        changes = _diff_snapshots(prev, curr)
    else:
        changes = ['Snapshot unavailable - cannot diff.']
    for c in changes:
        print(f'[self_update] change: {c}')

    # Step 5: write changelog
    _write_changelog(ts, pipeline_ok, snapshot_ok, changes, pipeline_output)

    # Step 6: Telegram notify
    msg = _build_telegram_message(ts, pipeline_ok, snapshot_ok, changes)
    _telegram_send(msg)

    print(f'[self_update] done.')


if __name__ == '__main__':
    main()
