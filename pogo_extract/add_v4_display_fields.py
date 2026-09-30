"""Extract ALL PokemonDisplayProto fields from display_raw_hex bytes.

Layout (from runtime probe of Holoholo.Rpc.PokemonDisplayProto class):
  0x10 Costume                   int (Costume enum)
  0x14 Gender                    int
  0x18 Shiny                     bool (1 byte)
  0x1c Form                      int
  0x20 WeatherBoostedCondition   int
  0x24 Alignment                 int (Normal/Shadow/Purified)
  0x28 PokemonBadge              int
  0x2c CurrentTempEvolution      int (currently mega-evolved into form X)
  0x30 TemporaryEvolutionFinishMs i64
  0x38 TempEvolutionIsLocked     bool
  0x3c LockedTempEvolution       int
  0x40 OriginalCostume           int
  0x48 DisplayId                 i64
  0x50 MegaEvolutionLevel        ptr  (sub-message, non-null = has mega level)
  0x58 LocationCard              ptr  (sub-message, non-null = has location card!)
  0x60 BreadModeEnum             int (Dynamax/Gigantamax mode - 0=none)
  0x64 IsStrongPokemon           bool (special strong marker)
  0x68 ShinyRate                 float
  0x6c LocationCardRate          float
  0x70 NaturalArtType            int
  0x74 NaturalArtBackgroundAsset int
  0x78 NaturalArtUseFullScene    bool
  0x7c DayNightType              int
"""
import sqlite3, struct

DB = 'pokemon.db'

def i32(bs, o, n): return struct.unpack_from('<i', bs, o)[0] if o+4 <= n else 0
def i64(bs, o, n): return struct.unpack_from('<q', bs, o)[0] if o+8 <= n else 0
def f32(bs, o, n): return struct.unpack_from('<f', bs, o)[0] if o+4 <= n else 0.0
def byte(bs, o, n): return bs[o] if o < n else 0
def ptr_nonzero(bs, o, n):
    if o+8 > n: return 0
    return 1 if struct.unpack_from('<Q', bs, o)[0] != 0 else 0

conn = sqlite3.connect(DB)
c = conn.cursor()

# Add columns
new_cols = [
    ('display_costume',         'INTEGER'),
    ('display_form',            'INTEGER'),  # may differ from form column
    ('display_alignment',       'INTEGER'),
    ('display_pokemon_badge',   'INTEGER'),
    ('current_temp_evolution',  'INTEGER'),  # current mega state
    ('original_costume',        'INTEGER'),
    ('display_id',              'INTEGER'),  # i64
    ('has_mega_evolution_level','INTEGER'),  # 1 if MegaEvolutionLevel ptr != null
    ('has_location_card',       'INTEGER'),  # 1 if LocationCard ptr != null - SPECIAL
    ('bread_mode',              'INTEGER'),  # Dmax/Gmax mode
    ('is_strong_pokemon',       'INTEGER'),  # SPECIAL marker
    ('shiny_rate',              'REAL'),
    ('location_card_rate',      'REAL'),
    ('natural_art_type',        'INTEGER'),
    ('natural_art_background',  'INTEGER'),
    ('natural_art_use_full_scene','INTEGER'),
    ('day_night_type',          'INTEGER'),
]
existing = {row[1] for row in c.execute("PRAGMA table_info(pokemon)").fetchall()}
for col, typ in new_cols:
    if col not in existing:
        c.execute(f"ALTER TABLE pokemon ADD COLUMN {col} {typ}")
        print(f"  added {col}")

# Parse all display_raw_hex
n = 0
counts = {col: 0 for col, _ in new_cols}
for uid_hex, dh in c.execute("SELECT uid_hex, display_raw_hex FROM pokemon").fetchall():
    if not dh: continue
    bs = bytes.fromhex(dh)
    L = len(bs)

    costume         = i32(bs, 0x10, L)
    display_form    = i32(bs, 0x1c, L)
    display_align   = i32(bs, 0x24, L)
    badge           = i32(bs, 0x28, L)
    cur_temp_evo    = i32(bs, 0x2c, L)
    orig_costume    = i32(bs, 0x40, L)
    display_id      = i64(bs, 0x48, L)
    has_mega_lvl    = ptr_nonzero(bs, 0x50, L)
    has_loc_card    = ptr_nonzero(bs, 0x58, L)
    bread           = i32(bs, 0x60, L)
    is_strong       = byte(bs, 0x64, L)
    shiny_rate      = f32(bs, 0x68, L)
    loc_card_rate   = f32(bs, 0x6c, L)
    nat_art_type    = i32(bs, 0x70, L)
    nat_art_bg      = i32(bs, 0x74, L)
    nat_art_full    = byte(bs, 0x78, L)
    day_night       = i32(bs, 0x7c, L)

    if costume != 0:        counts['display_costume'] += 1
    if has_loc_card:        counts['has_location_card'] += 1
    if bread != 0:          counts['bread_mode'] += 1
    if is_strong:           counts['is_strong_pokemon'] += 1
    if cur_temp_evo != 0:   counts['current_temp_evolution'] += 1
    if has_mega_lvl:        counts['has_mega_evolution_level'] += 1

    c.execute("""UPDATE pokemon SET
        display_costume=?, display_form=?, display_alignment=?, display_pokemon_badge=?,
        current_temp_evolution=?, original_costume=?, display_id=?,
        has_mega_evolution_level=?, has_location_card=?, bread_mode=?, is_strong_pokemon=?,
        shiny_rate=?, location_card_rate=?, natural_art_type=?, natural_art_background=?,
        natural_art_use_full_scene=?, day_night_type=?
        WHERE uid_hex=?""", (
        costume, display_form, display_align, badge, cur_temp_evo, orig_costume,
        display_id, has_mega_lvl, has_loc_card, bread, is_strong,
        shiny_rate, loc_card_rate, nat_art_type, nat_art_bg, nat_art_full, day_night,
        uid_hex))
    n += 1

conn.commit()
print(f"\nUpdated {n} rows")
print("\n=== Special-marker counts ===")
print(f"  display_costume != 0:          {counts['display_costume']}")
print(f"  has_location_card:             {counts['has_location_card']}  <-- LocationCard pokemon (SPECIAL)")
print(f"  bread_mode != 0 (Dmax/Gmax):   {counts['bread_mode']}")
print(f"  is_strong_pokemon:             {counts['is_strong_pokemon']}")
print(f"  current_temp_evolution != 0:   {counts['current_temp_evolution']}")
print(f"  has_mega_evolution_level:      {counts['has_mega_evolution_level']}")

# Quick check: find any Spheal with costume != 0
print("\n=== Spheals with non-zero costume ===")
for r in c.execute("SELECT uid_hex, cp, iv_pct, display_costume, cull_decision FROM pokemon WHERE species_name='Spheal' AND display_costume != 0"):
    print(f"  {r}")

conn.close()
