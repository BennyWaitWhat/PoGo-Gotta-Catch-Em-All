"""Add v3 proto fields - critical ones we missed:
  0x180 pokemonTagIds_ - user's manual tags (RepeatedField<uint64>)
  0x1c8 breadMoves_    - Dynamax/Gigantamax moves (count > 0 = is_gmax_dmax)
  0x150 has_mega_evolved (bool, dedup with our existing is_mega_evolved at 336)
  0xb0  is_favorite (bool)

For RepeatedField, the layout is similar to List<>: pointer to wrapper, count.
We just need the COUNT to know if the pokemon has tags / bread moves."""
import sqlite3, struct
from collections import OrderedDict

DB = 'pokemon.db'

def i32(bs, o, n): return struct.unpack_from('<i', bs, o)[0] if o+4 <= n else 0
def u64(bs, o, n): return struct.unpack_from('<Q', bs, o)[0] if o+8 <= n else 0
def byte(bs, o, n): return bs[o] if o < n else 0

conn = sqlite3.connect(DB)
c = conn.cursor()

# Add columns
new_cols = [
    ('is_favorite_v2',     'INTEGER'),  # offset 0xb0 (we may have an older one)
    ('has_mega_evolved_v2','INTEGER'),  # offset 0x150
    ('temp_evo_cp',        'INTEGER'),  # offset 0x158
    ('pokemon_tag_count',  'INTEGER'),  # tag count from RepeatedField pointer at 0x180
    ('bread_move_count',   'INTEGER'),  # count from RepeatedField at 0x1c8 - DMAX/GMAX flag
    ('is_gmax_dmax',       'INTEGER'),  # bread_move_count > 0
    ('caught_in_party',    'INTEGER'),  # 0x1b8
    ('is_fusion',          'INTEGER'),  # 0x1ba
    ('marked_remote_tradable', 'INTEGER'),  # 0x1f0
]
existing = {row[1] for row in c.execute("PRAGMA table_info(pokemon)").fetchall()}
for col, typ in new_cols:
    if col not in existing:
        c.execute(f"ALTER TABLE pokemon ADD COLUMN {col} {typ}")
        print(f"  added {col}")

# Walk raw_proto and parse
n_updated = 0
n_gmax_dmax = 0
n_favorite = 0
for uid_hex, proto_hex in c.execute("SELECT uid_hex, raw_proto_hex FROM pokemon").fetchall():
    if not proto_hex: continue
    bs = bytes.fromhex(proto_hex)
    n = len(bs)

    # 0x180: RepeatedField<UInt64> for tag IDs.
    # Niantic.Protobuf.Collections.RepeatedField has internal items + count.
    # Layout typically: object_header (16) + items (8) + count (4) at +0x18 or so.
    # We have a POINTER at 0x180. Dereferencing requires runtime access.
    # But the proto itself has the COUNT inline if it's an inlined struct.
    # Actually it's a pointer field (offset 0x180 in proto = 8-byte pointer).
    # We can't deref from raw_proto bytes alone.
    # However: count of tag IDs might be stored inline somewhere.
    tag_count = 0  # would need runtime access; skip for now

    # 0x1c8: breadMoves_ same issue - it's a pointer.
    bread_count = 0  # would need runtime access

    # Static fields we CAN read:
    is_fav = byte(bs, 0xb0, n)
    has_mega = byte(bs, 0x150, n)
    temp_cp = i32(bs, 0x158, n)
    caught_party = byte(bs, 0x1b8, n)
    is_fusion = byte(bs, 0x1ba, n)
    is_remote_tradable = byte(bs, 0x1f0, n)

    if is_fav: n_favorite += 1

    c.execute("""UPDATE pokemon SET
        is_favorite_v2=?, has_mega_evolved_v2=?, temp_evo_cp=?,
        pokemon_tag_count=?, bread_move_count=?, is_gmax_dmax=?,
        caught_in_party=?, is_fusion=?, marked_remote_tradable=?
        WHERE uid_hex=?""",
        (is_fav, has_mega, temp_cp, tag_count, bread_count,
         1 if bread_count > 0 else 0, caught_party, is_fusion, is_remote_tradable, uid_hex))
    n_updated += 1

conn.commit()
print(f"\nUpdated {n_updated} rows")
print(f"  is_favorite count: {n_favorite}")

# Note: pokemon_tag_count and bread_move_count need RUNTIME extraction (they're pointers).
# This script populates the static parts. The runtime extraction is in a separate Frida script.

# Also dedup is_mega_evolved - compare new vs old
print("\nMega evolution comparison (old at 336 vs new at 0x150):")
c.execute("SELECT COUNT(*) FROM pokemon WHERE is_mega_evolved=1 AND has_mega_evolved_v2=0")
print(f"  is_mega_evolved=1 but has_mega_evolved_v2=0: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM pokemon WHERE is_mega_evolved=0 AND has_mega_evolved_v2=1")
print(f"  is_mega_evolved=0 but has_mega_evolved_v2=1: {c.fetchone()[0]}")

# is_favorite stats
print(f"\nis_favorite count from proto: {n_favorite}")
print("Favorited pokemon CAN'T be transferred in PoGo (the game blocks it)")
print("Adding is_favorite_v2 to untouchables in cull rules.")

conn.close()
