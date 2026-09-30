"""Restore pokemon.db from a snapshot.

Usage:
    python restore_db.py                       # interactive: list + prompt
    python restore_db.py latest                # most recent snapshot
    python restore_db.py 2026-05-19_143022     # by timestamp prefix
    python restore_db.py a1b2c3d4e5f60718      # by schema hash (first match)
    python restore_db.py cull_v8               # by tag (most recent match)
    python restore_db.py --list                # just list snapshots, no restore

Safety: takes a snapshot of the CURRENT db (tag=pre_restore) before
overwriting, so a bad restore is itself reversible.
"""
from __future__ import annotations
import sys, shutil, gzip
from pathlib import Path
from db_safety import list_snapshots, snapshot, SnapshotInfo


def _resolve(selector: str, snaps: list[SnapshotInfo]) -> SnapshotInfo | None:
    if not snaps:
        return None
    if selector == 'latest':
        return snaps[0]
    # timestamp prefix
    for s in snaps:
        if s.timestamp.strftime('%Y-%m-%d_%H%M%S').startswith(selector):
            return s
    # schema hash
    for s in snaps:
        if s.schema_hash == selector:
            return s
    # tag (most recent match - snaps already sorted desc by ts)
    for s in snaps:
        if s.tag == selector:
            return s
    # substring on filename, last resort
    for s in snaps:
        if selector in s.path.name:
            return s
    return None


def _print_list(snaps: list[SnapshotInfo]) -> None:
    if not snaps:
        print("(no snapshots)")
        return
    print(f"{'#':>3}  {'when':<19}  {'tag':<24}  {'schema':<16}  {'size':>8}")
    for i, s in enumerate(snaps):
        print(f"{i:>3}  {s.timestamp:%Y-%m-%d %H:%M:%S}  {s.tag:<24}  "
              f"{s.schema_hash:<16}  {s.size_bytes/1024:>6.0f} KB")


def restore(snap: SnapshotInfo, db_path: Path = Path('pokemon.db')) -> None:
    if db_path.exists():
        print(f"snapshotting current {db_path.name} before restore...")
        snapshot('pre_restore', db_path)
    tmp = db_path.with_suffix(db_path.suffix + '.restoring')
    with gzip.open(snap.path, 'rb') as fi, open(tmp, 'wb') as fo:
        shutil.copyfileobj(fi, fo)
    # atomic swap
    import os
    os.replace(tmp, db_path)
    print(f"restored {snap.path.name} -> {db_path.name}")


def main() -> int:
    snaps = list_snapshots()
    args = sys.argv[1:]
    if args and args[0] in ('--list', '-l', 'list'):
        _print_list(snaps)
        return 0
    if not args:
        _print_list(snaps)
        if not snaps:
            return 1
        sel = input("\nselect by index, tag, or timestamp (empty=cancel): ").strip()
        if not sel:
            print("cancelled")
            return 0
        if sel.isdigit() and int(sel) < len(snaps):
            target = snaps[int(sel)]
        else:
            target = _resolve(sel, snaps)
    else:
        target = _resolve(args[0], snaps)
    if not target:
        print(f"no snapshot matched {args[0] if args else ''!r}", file=sys.stderr)
        return 2
    print(f"about to restore: {target.path.name}")
    print(f"  taken {target.timestamp:%Y-%m-%d %H:%M:%S}  tag={target.tag}  schema={target.schema_hash}")
    confirm = input("type 'yes' to proceed: ").strip().lower()
    if confirm != 'yes':
        print("cancelled")
        return 0
    restore(target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
