"""Integrate v2 proto offsets into pokemon.db.

V2 fields (from proto_offsets_discovered_v2.md):
  248 f32  added_friendship_score      0.0-0.73 range
  252 i32  trading_original_owner_hash one-per-trader
  269 byte is_traded_flag              cleaner than derived is_traded
  424 i32  pokemon_size_category       1=XXS, 2=XS, 3=NORMAL, 4=L, 5=XL/XXL
  192 byte is_special_acquisition_flag MED conf, ~hatched + extras
"""
import sqlite3, struct, json

DB = 'pokemon.db'

def i32(bs, o, n): return struct.unpack_from('<i', bs, o)[0] if o+4 <= n else 0
def f32(bs, o, n): return struct.unpack_from('<f', bs, o)[0] if o+4 <= n else 0.0
def byte(bs, o, n): return bs[o] if o < n else 0

conn = sqlite3.connect(DB)
c = conn.cursor()

new_cols = [
    ('added_friendship_score',      'REAL'),
    ('trading_original_owner_hash', 'INTEGER'),
    ('is_traded_flag_v2',           'INTEGER'),
    ('pokemon_size_category',       'INTEGER'),
    ('is_special_acquisition',      'INTEGER'),
]
existing = {row[1] for row in c.execute("PRAGMA table_info(pokemon)").fetchall()}
for col, typ in new_cols:
    if col not in existing:
        c.execute(f"ALTER TABLE pokemon ADD COLUMN {col} {typ}")
        print(f"  added {col}")
conn.commit()

print("\nParsing 5413 raw_proto for v2 fields...")
rows = c.execute("SELECT uid_hex, raw_proto_hex FROM pokemon").fetchall()
n_updated = 0
for uid_hex, proto_hex in rows:
    if not proto_hex: continue
    try:
        bs = bytes.fromhex(proto_hex)
        n = len(bs)
        c.execute("""UPDATE pokemon SET
            added_friendship_score=?,
            trading_original_owner_hash=?,
            is_traded_flag_v2=?,
            pokemon_size_category=?,
            is_special_acquisition=?
            WHERE uid_hex=?""", (
            f32(bs, 248, n),
            i32(bs, 252, n),
            byte(bs, 269, n),
            i32(bs, 424, n),
            byte(bs, 192, n),
            uid_hex
        ))
        n_updated += 1
    except Exception as e:
        print(f"  parse fail {uid_hex}: {e}")

conn.commit()
print(f"  updated {n_updated} rows")

# Index size_category since we'll filter on it
c.execute("CREATE INDEX IF NOT EXISTS idx_size_category ON pokemon(pokemon_size_category)")
conn.commit()

print("\n=== Distribution of pokemon_size_category ===")
for size, n in c.execute("""SELECT pokemon_size_category, COUNT(*) FROM pokemon
                             GROUP BY pokemon_size_category ORDER BY 1"""):
    label = {1:'XXS', 2:'XS', 3:'NORMAL', 4:'L', 5:'XL/XXL'}.get(size, f'?{size}')
    print(f"  {size} ({label}): {n}")

print("\n=== Trading-owner-hash → original_owner crosscheck ===")
for owner, n_unique_hash in c.execute("""SELECT original_owner, COUNT(DISTINCT trading_original_owner_hash)
                                          FROM pokemon WHERE original_owner IS NOT NULL
                                          GROUP BY original_owner LIMIT 10""").fetchall():
    print(f"  {owner}: {n_unique_hash} distinct hash(es)")

conn.close()
print("\nDone.")
