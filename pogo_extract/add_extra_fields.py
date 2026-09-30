"""Add newly-discovered proto fields to pokemon.db.

New columns added (from proto_offsets_discovered.md):
  buddy_km_walked          f32 @200
  is_purified_flag         i32 @296    (parallel to alignment-based purified)
  is_mega_evolved          byte @336
  mega_evo_state           byte @340   (0=none, 1=X, 2=Y)
  mega_cp                  i32 @344
  mega_extra_cpm           f32 @348
  mega_cpm                 f32 @352
  num_upgrades_or_battles  i32 @144    (MED conf: probably battles-attacked counter)
  num_poweredup_or_walks   i32 @196    (MED conf: probably buddy-walks-completed)
  costume_decoration_id    str @0x130  (e.g. 'season28_pancham')

Plus computed convenience flags:
  is_powered_up            BOOL  (numAdditionalCpMultiplier > 0)
"""
import sqlite3, struct, json, os

DB = 'pokemon.db'
JSON = 'pokemon_v3.json'

def i32(bs, o, n): return struct.unpack_from('<i', bs, o)[0] if o+4 <= n else 0
def f32(bs, o, n): return struct.unpack_from('<f', bs, o)[0] if o+4 <= n else 0.0
def byte(bs, o, n): return bs[o] if o < n else 0

print("Loading pokemon_v3.json (for string lookups at offset 0x130)...")
raw = json.load(open(JSON))
str_lookup = {}  # uid_signed -> seasonal_costume str
for p in raw:
    proto_hex = p.get('raw_proto', '')
    if not proto_hex or len(proto_hex) < 600: continue
    try:
        bs = bytes.fromhex(proto_hex)
        uid = struct.unpack_from('<Q', bs, 32)[0]
        if uid == 0: continue
        # signed conversion
        uid_s = uid if uid < 2**63 else uid - 2**64
        s = p.get('strings') or {}
        v = s.get('0x130')
        if isinstance(v, list) and v[1]:
            str_lookup[uid_s] = v[1]
    except: pass
print(f"  {len(str_lookup)} pokemon have seasonal costume string at 0x130")

print(f"\nOpening {DB}...")
conn = sqlite3.connect(DB)
c = conn.cursor()

# Add columns idempotently
new_cols = [
    ('buddy_km_walked',         'REAL'),
    ('is_purified_flag',        'INTEGER'),
    ('is_mega_evolved',         'INTEGER'),
    ('mega_evo_state',          'INTEGER'),
    ('mega_cp',                 'INTEGER'),
    ('mega_extra_cpm',          'REAL'),
    ('mega_cpm',                'REAL'),
    ('num_upgrades_or_battles', 'INTEGER'),
    ('num_poweredup_or_walks',  'INTEGER'),
    ('costume_decoration_id',   'TEXT'),
    ('is_powered_up',           'INTEGER'),
]
existing_cols = {row[1] for row in c.execute("PRAGMA table_info(pokemon)").fetchall()}
for col, typ in new_cols:
    if col not in existing_cols:
        c.execute(f"ALTER TABLE pokemon ADD COLUMN {col} {typ}")
        print(f"  added column: {col} {typ}")
    else:
        print(f"  exists:        {col}")
conn.commit()

print("\nParsing all 5413 pokemon and updating new columns...")
rows = c.execute("SELECT uid_hex, uid, raw_proto_hex, num_additional_cpm FROM pokemon").fetchall()
updates = 0
for uid_hex, uid_signed, proto_hex, num_addl_cpm in rows:
    if not proto_hex: continue
    try:
        bs = bytes.fromhex(proto_hex)
        n = len(bs)
        c.execute("""UPDATE pokemon SET
            buddy_km_walked=?,
            is_purified_flag=?,
            is_mega_evolved=?,
            mega_evo_state=?,
            mega_cp=?,
            mega_extra_cpm=?,
            mega_cpm=?,
            num_upgrades_or_battles=?,
            num_poweredup_or_walks=?,
            costume_decoration_id=?,
            is_powered_up=?
            WHERE uid_hex=?""", (
            f32(bs, 200, n),
            i32(bs, 296, n),
            byte(bs, 336, n),
            byte(bs, 340, n),
            i32(bs, 344, n),
            f32(bs, 348, n),
            f32(bs, 352, n),
            i32(bs, 144, n),
            i32(bs, 196, n),
            str_lookup.get(uid_signed),
            1 if (num_addl_cpm or 0) > 0 else 0,
            uid_hex
        ))
        updates += 1
    except Exception as e:
        print(f"  parse fail {uid_hex}: {e}")

conn.commit()
print(f"\n  {updates} rows updated")

# Index the new useful columns
for col in ['is_mega_evolved', 'is_powered_up', 'is_purified_flag']:
    try:
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_{col} ON pokemon({col})")
    except: pass
conn.commit()

# Quick stats sanity check
print("\n=== STATS ON NEW COLUMNS ===")
for col, typ in new_cols:
    if typ == 'TEXT':
        n = c.execute(f"SELECT COUNT(*) FROM pokemon WHERE {col} IS NOT NULL").fetchone()[0]
        print(f"  {col} not-null: {n}")
    else:
        n = c.execute(f"SELECT COUNT(*) FROM pokemon WHERE {col} IS NOT NULL AND {col} != 0").fetchone()[0]
        print(f"  {col} non-zero: {n}")

conn.close()
print("\nDone.")
