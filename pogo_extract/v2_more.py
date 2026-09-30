"""
More targeted investigation:
- 192: investigate Jigglypuff outlier; could be is_event_pokemon
- 277: 79 BB but only 13% - what subset specifically?
- 424: rarity / pokemon class enum
- Look at offsets 320-336 (4 bytes nz) - maybe rare flag or buddy adventure data
- Look at 412-440 (mega energy?)
"""
import json, struct, sqlite3
from collections import Counter
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000
NOW_MS = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

data = json.load(open('pokemon_v3.json'))
all_bytes = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))
N = len(all_bytes)

c = sqlite3.connect('pokemon.db').cursor()
def s2u(v): return v if v >= 0 else v + (1 << 64)
uid_to_idx = {}
for i, bs in enumerate(all_bytes):
    uid = struct.unpack_from('<Q', bs, 32)[0]
    uid_to_idx[uid] = i

def db_set(where):
    s = set()
    for (uid_signed,) in c.execute(f"SELECT uid FROM pokemon WHERE {where}").fetchall():
        u = s2u(uid_signed)
        if u in uid_to_idx:
            s.add(uid_to_idx[u])
    return s

s_hatched = db_set("is_hatched_from_egg=1")
s_traded = db_set("is_traded=1")
s_lucky = db_set("is_lucky=1")
s_bb = db_set("is_best_buddy=1")
s_mega = db_set("is_mega_evolved=1")
s_powered = db_set("is_powered_up=1")
s_purified = db_set("is_purified_flag=1")
s_shiny = db_set("is_shiny=1")

# All db data
db_full = {}
rows = c.execute("""SELECT uid, species_name, level, cp, traded_time_ms, creation_time_ms,
    weather_boosted, num_additional_cpm, alignment, costume, form, original_owner,
    is_powered_up, num_upgrades_or_battles, num_poweredup_or_walks, buddy_km_walked, mega_cpm,
    is_mega_evolved, mega_evo_state, mega_cp, origin_detail, pokeball, gender, pokemon_id,
    is_legendary, is_mythical, can_mega_evolve
    FROM pokemon""").fetchall()
for r in rows:
    u = s2u(r[0])
    idx = uid_to_idx.get(u)
    if idx is None: continue
    db_full[idx] = r

# Investigate 277
print("=" * 100)
print("OFFSET 277 - intersection analysis")
print("=" * 100)

idx_277 = set(i for i, bs in enumerate(all_bytes) if 277 < len(bs) and bs[277] == 1)
# Maybe these are pokemon that have been used in at least N battles? Or have completed first BB walk?
# Check num_upgrades_or_battles / num_poweredup_or_walks
print(f"277 set size: {len(idx_277)}")
ub_in_277 = [db_full[i][13] for i in idx_277 if i in db_full]
ub_not_277 = [db_full[i][13] for i in s_bb - idx_277 if i in db_full]
print(f"  num_upgrades values in 277=1 set: top {Counter(ub_in_277).most_common(5)}")
print(f"  num_upgrades values in BB-but-not-277: top {Counter(ub_not_277).most_common(5)}")

# Check buddy_km
km_in_277 = [db_full[i][15] for i in idx_277 if i in db_full]
km_not_277 = [db_full[i][15] for i in s_bb - idx_277 if i in db_full]
nz_km_in = sum(1 for v in km_in_277 if v and v > 0)
nz_km_not = sum(1 for v in km_not_277 if v and v > 0)
print(f"  buddy_km > 0 in 277=1 set: {nz_km_in}/{len(km_in_277)}")
print(f"  buddy_km > 0 in BB-but-not-277: {nz_km_not}/{len(km_not_277)}")

# What % of mega-eligible are in 277?
mega_eligible = sum(1 for i in idx_277 if i in db_full and db_full[i][26])
print(f"  can_mega_evolve in 277 set: {mega_eligible}/{len(idx_277)}")

# Show all 82 with key info
print(f"\nAll 82 pokemon with 277=1:")
counts_by = Counter()
for idx in idx_277:
    if idx not in db_full: continue
    r = db_full[idx]
    counts_by[r[1]] += 1
print(f"Species distribution in 277: {counts_by.most_common(20)}")

# Check whether 277=1 corresponds to a 'pokemon currently/ever set as buddy' indicator
# by checking nondb dataset properties
# Actually let me check - these pokemon often have very high CP / level. Avg level
levels_277 = [db_full[i][2] for i in idx_277 if i in db_full]
print(f"Avg lvl in 277: {sum(levels_277)/len(levels_277):.1f}, range: {min(levels_277)}-{max(levels_277)}")

# Investigate 192 outliers by what they have in common
print()
print("=" * 100)
print("OFFSET 192 outlier investigation (180 non-hatched)")
print("=" * 100)

idx_192 = set(i for i, bs in enumerate(all_bytes) if 192 < len(bs) and bs[192] == 1)
non_hatched = idx_192 - s_hatched
print(f"180 non-hatched with 192=1.")

# Check origin_detail counter again, carefully
od_counter = Counter()
form_counter = Counter()
costume_counter = Counter()
pokeball_counter = Counter()
for i in non_hatched:
    if i not in db_full: continue
    r = db_full[i]
    od_counter[r[20]] += 1
    form_counter[r[10]] += 1
    costume_counter[r[9]] += 1
    pokeball_counter[r[21]] += 1

print(f"  origin_detail among 180: {od_counter.most_common(15)}")
print(f"  pokeball: {pokeball_counter.most_common(5)}")
print(f"  costume top: {costume_counter.most_common(5)}")
print(f"  form top: {form_counter.most_common(10)}")

# Maybe these are quest/research rewards? Niantic special spawns?
# Or "POI/raid encounters"?
# Show all specs
species_in_192 = Counter(db_full[i][1] for i in non_hatched if i in db_full)
print(f"  species (top 20): {species_in_192.most_common(20)}")

# Investigate 424 (large pop with values 1-5)
print()
print("=" * 100)
print("OFFSET 424 stratification")
print("=" * 100)

vals_424 = [struct.unpack_from('<i', bs, 424)[0] if 424+4<=len(bs) else 0 for bs in all_bytes]

# Cross-tab with species pid groups (legendaries / mythicals?)
val_3_legendary = sum(1 for i in range(N) if vals_424[i]==3 and i in db_full and db_full[i][24])
val_3_mythical = sum(1 for i in range(N) if vals_424[i]==3 and i in db_full and db_full[i][25])
val_3_mega = sum(1 for i in range(N) if vals_424[i]==3 and i in db_full and db_full[i][26])
print(f"Legendary in 424=3: {val_3_legendary}")
print(f"Mythical in 424=3: {val_3_mythical}")
print(f"Mega-eligible in 424=3: {val_3_mega}")

# Look at val=2/4/5 species specifically
for v in [1, 2, 4, 5]:
    species = Counter(db_full[i][1] for i in range(N) if vals_424[i]==v and i in db_full)
    pids = Counter(db_full[i][23] for i in range(N) if vals_424[i]==v and i in db_full)
    print(f"  val={v}: {species.most_common(15)}")

# ===========================================================
# Look for `currentTempEvolutionExpiryMs`
# Mega expiry: 8 hours after activation.
# If currently mega, expiry is in future. If expired, value is 0 OR last-used timestamp.
# Maybe i64 starting at offset 332 or 360 area?

print()
print("=" * 100)
print("LOOK FOR MEGA EXPIRY - check non-zero i64 values across mega-evolved pokemon")
print("Specifically: i64 at every offset 0..512, check distribution among 154 mega")
print("=" * 100)

# Need: all 154 mega pokemon should have a non-zero i64 representing expiry
# Should be > now (if active) or 0 (if expired). Since none of these are likely 'active',
# look for i64 values that are PoGo-launch-era timestamps in only the mega set.
for off in range(0, 504, 4):
    qvals = [struct.unpack_from('<q', bs, off)[0] for bs in all_bytes if off+8<=len(bs)]
    if len(qvals) < N: continue
    # In mega set, count valid TS
    mega_ts = sum(1 for i in s_mega if POGO_LAUNCH_MS < qvals[i] < NOW_MS + 86400*365*1000)
    non_mega_ts = sum(1 for i in range(N) if i not in s_mega and POGO_LAUNCH_MS < qvals[i] < NOW_MS + 86400*365*1000)
    if mega_ts >= 50 and mega_ts > non_mega_ts:
        print(f"  off={off}: mega_with_ts={mega_ts}/154 non_mega_ts={non_mega_ts}")

# Also try: mega pokemon's i32 in expiry-time format (seconds since 2010, etc.)
# Or 'last_used_mega_evo' timestamp tied to specifc pokemon
# Buddy walked mega energy awards

# Also check specific: 376, 384, 392 are aligned 4-byte fields with high distinct values
print()
print("=" * 100)
print("UNIQUE POINTERS at 360, 368, 376, 384, 392, 432, 456, 488 (all dist=N suggest pointers)")
print("=" * 100)
for off in [360, 368, 376, 384, 392, 432, 456, 488]:
    if off + 8 > 512: continue
    qvals = [struct.unpack_from('<Q', bs, off)[0] for bs in all_bytes]
    nz = sum(1 for v in qvals if v != 0)
    distinct = len(set(qvals))
    print(f"  off={off}: u64 nz={nz} dist={distinct}")
    # show 3 samples
    for i in range(0, 5):
        print(f"    idx{i}: u64={qvals[i]:>20} hex=0x{qvals[i]:016x}")

# These are likely C# object pointers (heap addresses)

# Let me focus: which offsets have unique value PER pokemon (suggesting object pointer)?
print()
print("Offsets where i32 is unique-per-pokemon (= heap pointer):")
for off in range(0, 509, 4):
    if off + 4 > 512: continue
    ivals = [struct.unpack_from('<I', bs, off)[0] for bs in all_bytes]
    nz = sum(1 for v in ivals if v != 0)
    dist = len(set(ivals))
    if nz >= N * 0.9 and dist >= N * 0.9:
        # All distinct AND mostly nonzero - looks like a pointer
        print(f"  off={off:>3}: nz={nz} dist={dist}  sample={hex(ivals[0])}")

print()
print("Now using those pointer offsets, check WHICH OFFSETS are sets that vary 90%+:")

# Try to dig differently: look at which 4-byte aligned offsets have ALL different values across 5413
all_diff = []
for off in range(0, 509, 4):
    if off + 4 > 512: continue
    ivals = [struct.unpack_from('<I', bs, off)[0] for bs in all_bytes]
    dist = len(set(ivals))
    nz = sum(1 for v in ivals if v != 0)
    if dist > N * 0.95 and nz > N * 0.95:
        all_diff.append((off, dist, nz))
print(f"All-distinct offsets: {all_diff}")

# These are pointer-like fields. The byte after them (off+1, off+2, off+3) often has the same byte = 0x73 (115) or 0x77 (119) which is a high address byte.
# Looking at off=360..392 pattern: the second 4-byte slot (e.g. off=364) has values mostly in 114-119 range = 0x72-0x77 = high pointer byte. So 360,368... are all 8-byte pointers to objects.

# These are likely C# string/object pointers. They reveal where strings are pointed to.
# Niantic.Holoholo.Pokemon.PokemonProto fields with reference type:
# - nickname_, deployedFortId_, pokemonDisplay_, captureMs_, etc.
# - originalOwnerNickname_
# - pokemonDisplay_ (a sub-message)
# - move1_, move2_ are enums (small int, NOT object)
# - currentTempEvolution_ (sub-message) - this is at +336 area

# So 360, 368, 376, 384, 392 might be sub-messages or repeated sub-messages.
# The pokemonDisplay_ is one. There's also captureWeatherCondition_ etc.

c.close()
