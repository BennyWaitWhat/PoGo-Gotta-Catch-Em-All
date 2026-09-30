"""Decode captured_cell_hex S2 cell IDs into lat/lon and write to pokemon table."""
import sqlite3
import random
from collections import Counter
from s2sphere import CellId, LatLng

DB = "pokemon.db"


def hex_to_int_candidates(h):
    """Return (big_endian_int, little_endian_int)."""
    h = h.strip()
    if len(h) != 16:
        return None, None
    be = int(h, 16)
    # little-endian: reverse bytes
    le = int.from_bytes(bytes.fromhex(h), "little")
    return be, le


def try_decode(cell_int):
    """Return (lat, lon) or None if invalid."""
    if cell_int is None or cell_int == 0:
        return None
    try:
        cid = CellId(cell_int)
        if not cid.is_valid():
            return None
        ll = cid.to_lat_lng()
        lat = ll.lat().degrees
        lon = ll.lng().degrees
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except Exception:
        return None
    return None


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Add columns if they don't exist
    cur.execute("PRAGMA table_info(pokemon)")
    existing_cols = {r[1] for r in cur.fetchall()}
    if "lat" not in existing_cols:
        cur.execute("ALTER TABLE pokemon ADD COLUMN lat REAL")
    if "lon" not in existing_cols:
        cur.execute("ALTER TABLE pokemon ADD COLUMN lon REAL")
    conn.commit()

    cur.execute(
        "SELECT uid_hex, captured_cell_hex FROM pokemon WHERE captured_cell_hex IS NOT NULL"
    )
    rows = cur.fetchall()

    # Determine endianness on first 100 valid attempts
    be_wins = 0
    le_wins = 0
    sample = rows[:200]
    for uid, h in sample:
        be, le = hex_to_int_candidates(h)
        be_ll = try_decode(be)
        le_ll = try_decode(le)
        if be_ll and not le_ll:
            be_wins += 1
        elif le_ll and not be_ll:
            le_wins += 1
        elif be_ll and le_ll:
            # Both valid; prefer the one inside a populated continent
            # (US bounding box approx -125<lon<-66, 24<lat<50)
            be_us = -125 <= be_ll[1] <= -66 and 24 <= be_ll[0] <= 50
            le_us = -125 <= le_ll[1] <= -66 and 24 <= le_ll[0] <= 50
            if be_us and not le_us:
                be_wins += 1
            elif le_us and not be_us:
                le_wins += 1
    print(f"Endian probe (first 200 rows): big-endian wins={be_wins}, little-endian wins={le_wins}")
    use_be = be_wins >= le_wins
    print(f"Using {'big-endian' if use_be else 'little-endian'} interpretation.")

    updated = 0
    failed = 0
    failures_examples = []
    update_buf = []
    for uid, h in rows:
        be, le = hex_to_int_candidates(h)
        cell_int = be if use_be else le
        ll = try_decode(cell_int)
        if ll is None:
            # try the other endian as fallback
            ll = try_decode(le if use_be else be)
        if ll:
            update_buf.append((ll[0], ll[1], uid))
            updated += 1
        else:
            failed += 1
            if len(failures_examples) < 5:
                failures_examples.append(h)

    cur.executemany("UPDATE pokemon SET lat = ?, lon = ? WHERE uid_hex = ?", update_buf)
    conn.commit()

    print(f"\nRows with non-NULL captured_cell_hex: {len(rows)}")
    print(f"Updated lat/lon: {updated}")
    print(f"Failed to decode: {failed}")
    if failures_examples:
        print(f"Failure examples: {failures_examples}")

    # Sample 20 random
    print("\n--- Sample of 20 random (lat, lon, species) ---")
    cur.execute(
        "SELECT lat, lon, species_name FROM pokemon WHERE lat IS NOT NULL ORDER BY RANDOM() LIMIT 20"
    )
    for r in cur.fetchall():
        print(f"  {r[0]:>9.5f}, {r[1]:>10.5f}   {r[2]}")

    # Cluster by 0.1-degree bin
    cur.execute("SELECT lat, lon FROM pokemon WHERE lat IS NOT NULL")
    bins = Counter()
    for lat, lon in cur.fetchall():
        bins[(round(lat, 1), round(lon, 1))] += 1
    print(f"\nDistinct 0.1-deg bins: {len(bins)}")
    print("\n--- Top 10 lat/lon neighborhoods ---")
    for (lat, lon), n in bins.most_common(10):
        print(f"  ({lat:>7.2f}, {lon:>8.2f})  -> {n} pokemon")

    conn.close()


if __name__ == "__main__":
    main()
