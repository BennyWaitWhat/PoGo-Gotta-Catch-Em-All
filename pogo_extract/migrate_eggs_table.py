"""Add eggs table to pokemon.db. Idempotent.

Run once. Re-running is a no-op. Snapshots before mutating.
"""
import sqlite3
import db_safety

EGGS_DDL = """
CREATE TABLE IF NOT EXISTS eggs (
    uid_hex TEXT PRIMARY KEY,
    uid INTEGER,
    egg_km_walked_target REAL,
    egg_km_walked_start REAL,
    is_hatched INTEGER,
    incubator_id TEXT,
    in_bag INTEGER DEFAULT 1,
    first_seen_ms INTEGER,
    last_seen_ms INTEGER
)
"""


def migrate(db_path: str = 'pokemon.db') -> None:
    with db_safety.snapshot_before('add_eggs_table', db_path):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(EGGS_DDL)
            conn.commit()
            db_safety.record_schema(db_path, conn, note='add eggs table')
            conn.commit()
        finally:
            conn.close()
        print('[migrate] eggs table ready')


if __name__ == '__main__':
    migrate()
