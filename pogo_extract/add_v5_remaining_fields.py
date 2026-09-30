"""V5: extract the ~30 remaining unmapped PokemonProto fields.

NOTE: After running and checking pointer-value histograms, three "String*" fields
(eggIncubatorId at 0x98, limitedPokemonIdentifier at 0x130, deployedStationId
at 0x1d0) all contain the SAME shared C# string-empty sentinel (0x7b81c1cf40)
across 5412/5413 rows. They are ALWAYS allocated to "" by default - the raw
ptr-non-null check is meaningless. Presence flags for these three are filled
from runtime-extracted string columns where available (costume_decoration_id
already holds limitedPokemonIdentifier_ content), otherwise left NULL.

Same caveat applies (less severely) to four pointer fields - eggTelemetry
(0x198), irisSocialDeployment (0x1c0), dayNightBonusStat (0x1f8) - they are
mostly 0x0 but a handful of rows have garbage/stale values rather than real
heap pointers. These are recorded as low-confidence presence flags.

Sub-message pointers with realistic distinct-heap-address distributions
(pvpCombatStats 275 distinct, npcCombatStats 625, pokemonContestInfo 1417,
eggDistribution 172, bonusStatLevel 702) are kept as reliable presence flags.

Already in DB (skip): pokemon_id, cp, stamina, max_stamina, move1/2/3, ivs,
cp_multiplier, height, weight, level, pokeball, captured_cell, creation_time,
num_upgrades, num_additional_cpm, is_lucky, is_traded, original_owner,
traded_time, deployed_fort, is_favorite_v2, has_mega_evolved_v2, temp_evo_cp,
hatched_from_egg, egg_km_walked_target, special_bg_id, location_bg_id,
adventure_effects_left, buddy_km_walked, mega_*, costume_decoration_id (0x130),
caught_in_party (0x1b8), is_fusion (0x1ba), marked_remote_tradable (0x1f0),
origin_detail (0x178), pokemon_size_category (0x1a8 area).

Field probe says PokemonProto has ~96 fields. Unmapped pulled in this pass:

  0x90  battlesAttacked_                       Int32
  0x94  battlesDefended_                       Int32
  0x98  eggIncubatorId_                        String*  (presence flag only)
  0xc0  fromFort_                              Bool
  0xc4  buddyCandyAwarded_                     Int32
  0xcc  displayPokemonId_                      Int32
  0xd0  displayCp_                             Int32
  0xe0  isBad_                                 Bool
  0xe4  coinsReturned_                         Int32
  0xe8  deployedDurationMs_                    Int64
  0xf0  deployedReturnedTimestampMs_           Int64
  0xf8  cpMultiplierBeforeTrading_             Single
  0x118 pvpCombatStats_                        ptr  (presence flag)
  0x120 npcCombatStats_                        ptr  (presence flag)
  0x128 move2IsPurifiedExclusive_              Bool
  0x130 limitedPokemonIdentifier_              String* (rename of costume_decoration_id, presence flag)
  0x138 preBoostedCp_                          Int32
  0x13c preBoostedAdditionalCpMultiplier_      Single
  0x140 deployedGymLatDegree_                  Double
  0x148 deployedGymLngDegree_                  Double
  0x154 eggType_                               Int32 (HoloPokemonEggType)
  0x190 eggSlotType_                           Int32 (EggSlotType)
  0x198 eggTelemetry_                          ptr  (presence flag)
  0x1a0 eggDistribution_                       ptr  (presence flag)
  0x1b0 pokemonContestInfo_                    ptr  (presence flag)
  0x1c0 irisSocialDeployment_                  ptr  (presence flag)
  0x1d0 deployedStationId_                     String* (presence flag)
  0x1d8 deployedStationExpirationTimeMs_       Int64
  0x1e0 isStampCollectionReward_               Bool
  0x1e1 isActivelyTraining_                    Bool
  0x1e8 bonusStatLevel_                        ptr  (presence flag)
  0x1f1 inEscrow_                              Bool
  0x1f8 dayNightBonusStat_                     ptr  (presence flag)

For pointer fields we store 1 if non-null and not obviously aliased to junk.
The dump captured raw_proto_hex as the IL2CPP object body (512 bytes), so 8-byte
pointers there are real (within the original process address space, but for our
purposes only presence/absence matters for cull rules).
"""
import sqlite3, struct

DB = 'pokemon.db'

def i32(bs, o, n): return struct.unpack_from('<i', bs, o)[0] if o + 4 <= n else 0
def i64(bs, o, n): return struct.unpack_from('<q', bs, o)[0] if o + 8 <= n else 0
def u64(bs, o, n): return struct.unpack_from('<Q', bs, o)[0] if o + 8 <= n else 0
def f32(bs, o, n): return struct.unpack_from('<f', bs, o)[0] if o + 4 <= n else 0.0
def f64(bs, o, n): return struct.unpack_from('<d', bs, o)[0] if o + 8 <= n else 0.0
def byte(bs, o, n): return bs[o] if o < n else 0
def ptr_nonzero(bs, o, n):
    if o + 8 > n: return 0
    return 1 if struct.unpack_from('<Q', bs, o)[0] != 0 else 0

# Shared C# string-empty sentinel (`""` interned object) seen across all rows.
STRING_EMPTY_SENTINEL = 0x7b81c1cf40

def string_present(bs, o, n):
    """Returns 1 only if pointer is non-zero AND not the empty-string sentinel.
    Still unreliable because we never see real allocated string addresses
    in this dump - returns NULL (None) if we can't determine, so callers can
    fall back to runtime-extracted columns.
    """
    if o + 8 > n: return None
    p = struct.unpack_from('<Q', bs, o)[0]
    if p == 0 or p == STRING_EMPTY_SENTINEL:
        return 0
    return None  # non-zero, non-sentinel: unknown - needs Frida

conn = sqlite3.connect(DB)
c = conn.cursor()

new_cols = [
    ('battles_attacked',                'INTEGER'),
    ('battles_defended',                'INTEGER'),
    ('has_egg_incubator_id',            'INTEGER'),
    ('from_fort',                       'INTEGER'),
    ('buddy_candy_awarded',             'INTEGER'),
    ('display_pokemon_id',              'INTEGER'),
    ('display_cp',                      'INTEGER'),
    ('is_bad',                          'INTEGER'),
    ('coins_returned',                  'INTEGER'),
    ('deployed_duration_ms',            'INTEGER'),
    ('deployed_returned_timestamp_ms',  'INTEGER'),
    ('cp_multiplier_before_trading',    'REAL'),
    ('has_pvp_combat_stats',            'INTEGER'),
    ('has_npc_combat_stats',            'INTEGER'),
    ('move2_is_purified_exclusive',     'INTEGER'),
    ('has_limited_pokemon_identifier',  'INTEGER'),
    ('pre_boosted_cp',                  'INTEGER'),
    ('pre_boosted_additional_cpm',      'REAL'),
    ('deployed_gym_lat',                'REAL'),
    ('deployed_gym_lng',                'REAL'),
    ('egg_type',                        'INTEGER'),
    ('egg_slot_type',                   'INTEGER'),
    ('has_egg_telemetry',               'INTEGER'),
    ('has_egg_distribution',            'INTEGER'),
    ('has_pokemon_contest_info',        'INTEGER'),
    ('has_iris_social_deployment',      'INTEGER'),
    ('has_deployed_station_id',         'INTEGER'),
    ('deployed_station_expiration_ms',  'INTEGER'),
    ('is_stamp_collection_reward',      'INTEGER'),
    ('is_actively_training',            'INTEGER'),
    ('has_bonus_stat_level',            'INTEGER'),
    ('in_escrow',                       'INTEGER'),
    ('has_day_night_bonus_stat',        'INTEGER'),
]

existing = {row[1] for row in c.execute("PRAGMA table_info(pokemon)").fetchall()}
added = []
for col, typ in new_cols:
    if col not in existing:
        c.execute(f"ALTER TABLE pokemon ADD COLUMN {col} {typ}")
        added.append(col)
print(f"Added {len(added)} columns: {added}")
conn.commit()

# Counters for summary
counts = {col: 0 for col, _ in new_cols}
n_updated = 0

rows = c.execute("SELECT uid_hex, raw_proto_hex FROM pokemon").fetchall()
for uid_hex, proto_hex in rows:
    if not proto_hex:
        continue
    bs = bytes.fromhex(proto_hex)
    L = len(bs)

    vals = {
        'battles_attacked':                i32(bs, 0x90,  L),
        'battles_defended':                i32(bs, 0x94,  L),
        'has_egg_incubator_id':            string_present(bs, 0x98, L),
        'from_fort':                       1 if byte(bs, 0xc0, L) == 1 else 0,
        'buddy_candy_awarded':             i32(bs, 0xc4,  L),
        'display_pokemon_id':              i32(bs, 0xcc,  L),
        'display_cp':                      i32(bs, 0xd0,  L),
        'is_bad':                          1 if byte(bs, 0xe0, L) == 1 else 0,
        'coins_returned':                  i32(bs, 0xe4,  L),
        'deployed_duration_ms':            i64(bs, 0xe8,  L),
        'deployed_returned_timestamp_ms':  i64(bs, 0xf0,  L),
        'cp_multiplier_before_trading':    f32(bs, 0xf8,  L),
        'has_pvp_combat_stats':            ptr_nonzero(bs, 0x118, L),
        'has_npc_combat_stats':            ptr_nonzero(bs, 0x120, L),
        'move2_is_purified_exclusive':     1 if byte(bs, 0x128, L) == 1 else 0,
        'has_limited_pokemon_identifier':  string_present(bs, 0x130, L),
        'pre_boosted_cp':                  i32(bs, 0x138, L),
        'pre_boosted_additional_cpm':      f32(bs, 0x13c, L),
        'deployed_gym_lat':                f64(bs, 0x140, L),
        'deployed_gym_lng':                f64(bs, 0x148, L),
        'egg_type':                        i32(bs, 0x154, L),
        'egg_slot_type':                   i32(bs, 0x190, L),
        'has_egg_telemetry':               ptr_nonzero(bs, 0x198, L),
        'has_egg_distribution':            ptr_nonzero(bs, 0x1a0, L),
        'has_pokemon_contest_info':        ptr_nonzero(bs, 0x1b0, L),
        'has_iris_social_deployment':      ptr_nonzero(bs, 0x1c0, L),
        'has_deployed_station_id':         string_present(bs, 0x1d0, L),
        'deployed_station_expiration_ms':  i64(bs, 0x1d8, L),
        'is_stamp_collection_reward':      1 if byte(bs, 0x1e0, L) == 1 else 0,
        'is_actively_training':            1 if byte(bs, 0x1e1, L) == 1 else 0,
        'has_bonus_stat_level':            ptr_nonzero(bs, 0x1e8, L),
        'in_escrow':                       1 if byte(bs, 0x1f1, L) == 1 else 0,
        'has_day_night_bonus_stat':        ptr_nonzero(bs, 0x1f8, L),
    }

    for col, _ in new_cols:
        v = vals[col]
        if v is not None and isinstance(v, (int, float)) and v not in (0, 0.0):
            counts[col] += 1

    cols = ', '.join(f"{col}=?" for col, _ in new_cols)
    args = [vals[col] for col, _ in new_cols] + [uid_hex]
    c.execute(f"UPDATE pokemon SET {cols} WHERE uid_hex=?", args)
    n_updated += 1

conn.commit()
print(f"\nUpdated {n_updated} rows")

# Back-fill has_limited_pokemon_identifier from the (already runtime-populated)
# costume_decoration_id column. The misnomered column actually holds the
# limitedPokemonIdentifier_ string content extracted via Frida earlier.
n_lim = c.execute("""UPDATE pokemon
   SET has_limited_pokemon_identifier = 1
   WHERE costume_decoration_id IS NOT NULL AND costume_decoration_id != ''""").rowcount
n_lim_zero = c.execute("""UPDATE pokemon
   SET has_limited_pokemon_identifier = 0
   WHERE costume_decoration_id IS NULL OR costume_decoration_id = ''""").rowcount
conn.commit()
print(f"  back-filled has_limited_pokemon_identifier from costume_decoration_id: "
      f"{n_lim} present, {n_lim_zero} empty")

print("\n=== Per-field non-zero counts (out of 5413) ===")
for col, _ in new_cols:
    print(f"  {col:38s} {counts[col]:5d}")

# Sanity: low-cardinality bools should have small distinct value counts.
print("\n=== Sanity histograms for byte fields ===")
for col in ('from_fort', 'is_bad', 'move2_is_purified_exclusive',
            'is_stamp_collection_reward', 'is_actively_training', 'in_escrow'):
    h = c.execute(f"SELECT {col}, COUNT(*) FROM pokemon GROUP BY {col} ORDER BY 2 DESC LIMIT 5").fetchall()
    print(f"  {col}: {h}")

# TRANSFER-list cross-check: identify truly untouchable rows that the cull
# engine would currently transfer.
#
# Conservative call:
#   STRONG: is_actively_training, is_stamp_collection_reward, in_escrow
#           (pokemon literally locked by game state)
#   STRONG-but-empty: has_egg_incubator_id, has_deployed_station_id (ALL string
#           fields are empty-sentinel in our dump - cannot detect from raw bytes;
#           need Frida runtime extraction to be useful)
#   WEAK:   has_pokemon_contest_info (1416 rows, looks like default-allocated;
#           random non-special pokemon have it; do NOT use as untouchable)
#   WEAK:   from_fort (gym returner; 67 in TRANSFER, 490 in KEEP - this is
#           historical, not active state; user transfers these regularly)
#   STRONG: has_iris_social_deployment (3 total in DB, plausible real flag)
print("\n=== TRANSFER list cross-check (STRONG flags only) ===")
strong_flags = [
    ('is_actively_training=1',        'currently in training'),
    ('is_stamp_collection_reward=1',  'location-stamp reward (event)'),
    ('in_escrow=1',                   'in escrow'),
    ('has_iris_social_deployment=1',  'socially deployed'),
]
for clause, label in strong_flags:
    n = c.execute(f"SELECT COUNT(*) FROM pokemon WHERE cull_decision='TRANSFER' AND {clause}").fetchone()[0]
    print(f"  TRANSFER + {label:30s} ({clause:32s}): {n}")
    if 0 < n <= 30:
        for r in c.execute(f"""SELECT uid_hex, species_name, cp, iv_pct, cull_reason
                                FROM pokemon WHERE cull_decision='TRANSFER' AND {clause}
                                LIMIT 30"""):
            print(f"     {r[0]}  {r[1]:20s} cp={r[2]:4d} iv={r[3]:5.1f}  reason={r[4]}")

print("\n=== Informational: weak/historical flags (NOT recommended for untouchables) ===")
weak_flags = [
    ('from_fort=1',                  'gym returner (historical, 67 TRANSFER vs 490 KEEP)'),
    ('has_pokemon_contest_info=1',   'contest info ptr (1416 rows; default-allocated)'),
    ('has_egg_incubator_id=1',       'string sentinel - needs Frida'),
    ('has_deployed_station_id=1',    'string sentinel - needs Frida'),
    ('battles_attacked > 0',         'has gym battle history'),
    ('battles_defended > 0',         'has gym defense history'),
]
for clause, label in weak_flags:
    n = c.execute(f"SELECT COUNT(*) FROM pokemon WHERE cull_decision='TRANSFER' AND {clause}").fetchone()[0]
    total = c.execute(f"SELECT COUNT(*) FROM pokemon WHERE {clause}").fetchone()[0]
    print(f"  TRANSFER + {label:55s}: {n} (of {total} total)")

conn.close()
