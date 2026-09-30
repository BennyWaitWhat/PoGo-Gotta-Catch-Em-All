"""Parse egg entries out of a `full_inventory_v3.json` dump and upsert into pokemon.db.

Offsets (verified against 9 in-bag eggs, 2026-05):
    0x28  i32   pokemon_id           (== 0 for eggs)
    0x50  i32   is_egg               (== 1 for eggs, 0 otherwise)
    0x58  f64   egg_km_walked_target (2.0 / 5.0 / 7.0 / 10.0 / 12.0)
    0x60  f64   egg_km_walked_start  (km walked into incubator; 0.0 when not incubating)
    0xa0  i64   creation_time_ms     (treated as first_seen fallback)

The `egg_incubator_id` field is a string-pointer that lives in the heap-pointer
region (offsets 0xb8..0xd0). It points to a C# string and can't be resolved
from the proto_bytes hex alone. Captured as NULL here; the rescan_inventory.py
runtime can fill it from the live IL2CPP walk if needed.
"""
import json
import sqlite3
import struct
import time
from pathlib import Path


OFF_PID = 0x28
OFF_IS_EGG = 0x50
OFF_KM_TARGET = 0x58
OFF_KM_START = 0x60
OFF_CREATION_MS = 0xa0


def parse_egg(proto_hex: str) -> dict | None:
    """Return egg dict from proto bytes, or None if not an egg."""
    if not proto_hex:
        return None
    try:
        bs = bytes.fromhex(proto_hex)
    except ValueError:
        return None
    if len(bs) < OFF_CREATION_MS + 8:
        return None
    pid = struct.unpack_from('<i', bs, OFF_PID)[0]
    if pid != 0:
        return None
    is_egg = struct.unpack_from('<i', bs, OFF_IS_EGG)[0]
    if is_egg != 1:
        return None
    km_target = struct.unpack_from('<d', bs, OFF_KM_TARGET)[0]
    km_start = struct.unpack_from('<d', bs, OFF_KM_START)[0]
    creation_ms = struct.unpack_from('<q', bs, OFF_CREATION_MS)[0]
    return {
        'egg_km_walked_target': km_target,
        'egg_km_walked_start': km_start,
        'creation_time_ms': creation_ms,
    }


def upsert_eggs(inventory_json_path: str | Path = 'full_inventory_v3.json',
                db_path: str = 'pokemon.db') -> dict:
    """Walk inventory dump, upsert all eggs into the eggs table.

    Returns {'found': N, 'inserted': X, 'updated': Y, 'hatched_marked': Z}.
    """
    p = Path(inventory_json_path)
    if not p.exists():
        raise FileNotFoundError(p)
    data = json.loads(p.read_text())
    results = data['results']

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    now_ms = int(time.time() * 1000)
    eggs_seen: set[str] = set()
    inserted = 0
    updated = 0

    for uid_str, rec in results.items():
        egg = parse_egg(rec.get('protoBytes', ''))
        if not egg:
            continue
        uid_unsigned = int(uid_str)
        uid_signed = (uid_unsigned if uid_unsigned <= (2**63 - 1)
                      else uid_unsigned - 2**64)
        uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
        eggs_seen.add(uid_hex)

        existing = c.execute(
            "SELECT first_seen_ms FROM eggs WHERE uid_hex=?",
            (uid_hex,)
        ).fetchone()
        if existing is None:
            c.execute(
                "INSERT INTO eggs (uid_hex, uid, egg_km_walked_target, "
                "egg_km_walked_start, is_hatched, incubator_id, in_bag, "
                "first_seen_ms, last_seen_ms) "
                "VALUES (?,?,?,?,0,NULL,1,?,?)",
                (uid_hex, uid_signed, egg['egg_km_walked_target'],
                 egg['egg_km_walked_start'], now_ms, now_ms),
            )
            inserted += 1
        else:
            c.execute(
                "UPDATE eggs SET egg_km_walked_target=?, egg_km_walked_start=?, "
                "in_bag=1, is_hatched=0, last_seen_ms=? WHERE uid_hex=?",
                (egg['egg_km_walked_target'], egg['egg_km_walked_start'],
                 now_ms, uid_hex),
            )
            updated += 1

    # Eggs we had before but didn't see this pass: mark out-of-bag.
    # Differentiate "hatched" (now exists in pokemon table as a real pokemon
    # with is_hatched_from_egg=1) from "released" (gone, no pokemon row).
    hatched_marked = 0
    prev = c.execute(
        "SELECT uid_hex FROM eggs WHERE in_bag=1"
    ).fetchall()
    for (uid_hex,) in prev:
        if uid_hex in eggs_seen:
            continue
        # Is there now a hatched pokemon with this uid?
        row = c.execute(
            "SELECT is_hatched_from_egg FROM pokemon WHERE uid_hex=?",
            (uid_hex,),
        ).fetchone()
        is_hatched = 1 if row and row[0] else 0
        c.execute(
            "UPDATE eggs SET in_bag=0, is_hatched=?, last_seen_ms=? "
            "WHERE uid_hex=?",
            (is_hatched, now_ms, uid_hex),
        )
        if is_hatched:
            hatched_marked += 1

    conn.commit()
    conn.close()
    return {
        'found': len(eggs_seen),
        'inserted': inserted,
        'updated': updated,
        'hatched_marked': hatched_marked,
    }


if __name__ == '__main__':
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else 'full_inventory_v3.json'
    stats = upsert_eggs(src)
    print(f"[eggs_walker] {stats}")
