"""DB safety: snapshots + schema-version tracking for pokemon.db.

Public API:
    snapshot(tag, db_path='pokemon.db') -> Path
        Create a compressed snapshot. Returns the snapshot path.

    with snapshot_before(tag, db_path='pokemon.db'):
        # any code that mutates the DB
    Context manager wrapper - snapshots, then runs body. If body raises,
    snapshot still exists (you'll want it).

    list_snapshots(db_path='pokemon.db') -> list[SnapshotInfo]

    prune(db_path='pokemon.db') -> int
        Apply retention policy. Returns number removed.

    record_schema(db_path='pokemon.db', conn=None) -> str
        Compute schema hash, log to schema_version table if changed.
        Call after any ALTER TABLE. Returns the new hash.

Retention: keep the newest 100 snapshots (Benny 2026-09-30: "Just keep the last 100 culls.").

Snapshot mechanism: sqlite3.Connection.backup() into a fresh file, then gzip.
This is safe with concurrent readers/writers (SQLite handles locking).
"""
from __future__ import annotations
import sqlite3, gzip, shutil, hashlib, time, os, sys, json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

SNAPSHOT_DIR = Path('.db_snapshots')
KEEP_RECENT = 100   # ~4 MB each; nothing reads further back than 30 culls (Bag Pulse's chart reads ladder_history)


@dataclass
class SnapshotInfo:
    path: Path
    tag: str
    timestamp: datetime
    size_bytes: int
    schema_hash: str

    @property
    def age(self) -> timedelta:
        return datetime.now() - self.timestamp


def _ensure_dir(db_path: str | Path) -> Path:
    d = Path(db_path).parent / SNAPSHOT_DIR
    d.mkdir(exist_ok=True)
    return d


def _schema_hash(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    blob = json.dumps(rows, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _parse_name(name: str) -> tuple[datetime, str, str] | None:
    # pokemon.db.2026-05-19_143022.cull_v8.a1b2c3d4e5f60718.gz
    if not name.endswith('.gz'):
        return None
    base = name[:-3]
    parts = base.split('.')
    if len(parts) < 5:
        return None
    try:
        ts = datetime.strptime(parts[-3], '%Y-%m-%d_%H%M%S')
    except ValueError:
        return None
    tag = parts[-2]
    sh = parts[-1]
    return ts, tag, sh


def snapshot(tag: str, db_path: str | Path = 'pokemon.db') -> Path:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    snap_dir = _ensure_dir(db_path)
    ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')

    src = sqlite3.connect(str(db_path))
    try:
        sh = _schema_hash(src)
        fname = f"{db_path.name}.{ts}.{tag}.{sh}.gz"
        out = snap_dir / fname
        tmp = snap_dir / f".{fname}.tmp"
        tmp_db = snap_dir / f".{fname}.db"
        dst = sqlite3.connect(str(tmp_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
        with open(tmp_db, 'rb') as fi, gzip.open(tmp, 'wb', compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo)
        tmp_db.unlink()
        os.replace(tmp, out)
    finally:
        src.close()
    print(f"[db_safety] snapshot: {out.name} ({out.stat().st_size/1024:.0f} KB)")
    return out


@contextmanager
def snapshot_before(tag: str, db_path: str | Path = 'pokemon.db'):
    snap_path = snapshot(tag, db_path)
    try:
        yield snap_path
    finally:
        # Prune AFTER body completes (success or failure) - never prune the
        # just-taken snapshot, since "keep the newest 100" includes the new one.
        try:
            prune(db_path)
        except Exception as e:
            print(f"[db_safety] prune failed: {e}", file=sys.stderr)


def list_snapshots(db_path: str | Path = 'pokemon.db') -> list[SnapshotInfo]:
    db_path = Path(db_path)
    snap_dir = _ensure_dir(db_path)
    out = []
    for p in snap_dir.iterdir():
        parsed = _parse_name(p.name)
        if not parsed:
            continue
        ts, tag, sh = parsed
        out.append(SnapshotInfo(
            path=p, tag=tag, timestamp=ts,
            size_bytes=p.stat().st_size, schema_hash=sh,
        ))
    out.sort(key=lambda s: s.timestamp, reverse=True)
    return out


def prune(db_path: str | Path = 'pokemon.db') -> int:
    snaps = list_snapshots(db_path)
    keep: set[Path] = set()
    for s in snaps[:KEEP_RECENT]:      # newest first
        keep.add(s.path)
    removed = 0
    for s in snaps:
        if s.path not in keep:
            s.path.unlink()
            removed += 1
    if removed:
        print(f"[db_safety] pruned {removed} old snapshots ({len(snaps)-removed} kept)")
    return removed


# --- schema-version tracking ----------------------------------------------

SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    column_count INTEGER NOT NULL,
    note TEXT,
    columns_json TEXT NOT NULL
)
"""


def record_schema(db_path: str | Path = 'pokemon.db',
                  conn: sqlite3.Connection | None = None,
                  note: str | None = None) -> str:
    """Compute current schema hash. If different from last logged, insert a row.

    Pass `conn` if you're already inside an open connection (avoids lock churn
    and lets the schema log share the transaction with your migration).
    Returns the current schema hash.
    """
    own = conn is None
    if own:
        conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(SCHEMA_VERSION_DDL)
        sh = _schema_hash(conn)
        last = conn.execute(
            "SELECT hash FROM schema_version ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last and last[0] == sh:
            return sh
        cols = conn.execute("PRAGMA table_info(pokemon)").fetchall()
        col_names = [c[1] for c in cols]
        conn.execute(
            "INSERT INTO schema_version (hash, recorded_at, column_count, note, columns_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (sh, datetime.now().isoformat(timespec='seconds'),
             len(col_names), note, json.dumps(col_names)),
        )
        if own:
            conn.commit()
        print(f"[db_safety] schema changed -> {sh} ({len(col_names)} cols on pokemon)")
        return sh
    finally:
        if own:
            conn.close()


if __name__ == '__main__':
    # Quick CLI: `python db_safety.py snapshot <tag>` / `list` / `prune` / `schema`
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    if cmd == 'snapshot':
        snapshot(sys.argv[2] if len(sys.argv) > 2 else 'manual')
    elif cmd == 'list':
        for s in list_snapshots():
            print(f"{s.timestamp:%Y-%m-%d %H:%M:%S}  {s.tag:<24} {s.schema_hash}  "
                  f"{s.size_bytes/1024:>6.0f} KB  {s.path.name}")
    elif cmd == 'prune':
        prune()
    elif cmd == 'schema':
        record_schema(note='manual')
    else:
        print(__doc__)
        sys.exit(2)
