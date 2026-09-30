"""
Final pass: gather all the offsets we've identified and finalize hypotheses.

Also:
1. Look at the bytes adjacent to byte=1 fields to identify multi-byte field structures.
2. Investigate offset 268 more (pulled out earlier - "411=49, 404=42" as upper of int64 traded_time_ms)
3. Look at 280, 288 which were "all distinct" upper-bytes - could be timestamps for events
4. Check 220 - has 5412 nz with byte values 114-118 (looks like part of pointer)
5. Check 252 i32 vs known hash and confirm as 'tradingOriginalOwnerHash_'
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

# Check whether the 248-252 packing matches the original_location_hash hex stored in DB
print("=" * 100)
print("VALIDATE original_location_hash from i32@252 + i32@248 packing")
print("=" * 100)
mismatches = 0
matches = 0
for (uid_signed, hash_hex) in c.execute("SELECT uid, original_location_hash FROM pokemon WHERE is_traded=1 LIMIT 30"):
    u = s2u(uid_signed)
    idx = uid_to_idx.get(u)
    if idx is None: continue
    bs = all_bytes[idx]
    i32_252 = struct.unpack_from('<i', bs, 252)[0] & 0xFFFFFFFF
    i32_248 = struct.unpack_from('<i', bs, 248)[0] & 0xFFFFFFFF
    # Format as hex64
    expected = f"{i32_252:08x}{i32_248:08x}"
    # The DB stores it as signed -> may be negative ints. Just compare numeric.
    # The hash_hex is signed-int64 in hex (e.g. -663fbe9ec16b645e)
    actual_int = int(hash_hex, 16) if hash_hex.startswith('-') else int(hash_hex, 16)
    if hash_hex.startswith('-'):
        actual_int = -int(hash_hex[1:], 16)
    # Convert to unsigned 64
    if actual_int < 0:
        actual_int += 1 << 64
    actual_hex = f"{actual_int:016x}"
    if expected == actual_hex:
        matches += 1
    else:
        if mismatches < 3:
            print(f"  MISMATCH: db={hash_hex} (={actual_hex}) vs constructed={expected}")
        mismatches += 1
print(f"  matches={matches} mismatches={mismatches}")

# Now: look at offset 248 vs 252 more carefully
# i32@248 looks like float (0.5974, 0.297, etc.)
# Pull all traded pokemon to check correlation between f@248 value and (a) original_owner length, (b) trade time
print()
print("=" * 100)
print("DOES f32@248 = number of POKEMON traded between same pair (cumulative count)?")
print("=" * 100)

# Or, is it just a hash of trade transaction id?
# Look at distribution of f@248 in traded pokemon
trade_floats = []
for (uid_signed, owner) in c.execute("SELECT uid, original_owner FROM pokemon WHERE is_traded=1"):
    u = s2u(uid_signed)
    idx = uid_to_idx.get(u)
    if idx is None: continue
    bs = all_bytes[idx]
    f = struct.unpack_from('<f', bs, 248)[0]
    trade_floats.append((owner, f, uid_signed))

owner_floats = {}
for o, f, uid in trade_floats:
    owner_floats.setdefault(o, []).append((f, uid))

# Show all per owner
print("Per-owner f@248 spread:")
for owner, items in sorted(owner_floats.items(), key=lambda x: x[0] or '<None>')[:10]:
    fs = [f for f, _ in items]
    print(f"  {owner!r:25}  {len(items)} pokemon, f range [{min(fs):.4f},{max(fs):.4f}], sample: {[round(f, 4) for f, _ in items[:6]]}")

# 4969 pokemon have offset 424 = 3, 130=5, 123=2, 114=4, 30=1, 44=0
# Top 6 species by val: 5=Pumpkaboo (15), Magikarp (12), 4=Unown (6), Pikachu (3), 2=Pikachu (4), 1=Gyarados (6)
# Maybe 424 = pokemon "rarity tier" or "battle league tier"

# Hypothesis: 424 = `evolutionaryLevelStage` or some categorical
# Looking at the val distribution, val=2 has Pikachu/Spinda/Marill (cute small) - maybe stage 1 evolution
# val=3 majority = stage 2 evolution
# val=4 = stage 1 of some special line
# val=5 = stage 0 (Pumpkaboo, Magikarp, Ralts) = unevolved
# Wait but Magikarp can evolve into Gyarados - how is Magikarp also val=5?

# Check correlation between 424 and pokemon's evolution state in DB
print()
print("=" * 100)
print("OFFSET 424 hypothesis check")
print("=" * 100)
vals_424 = [struct.unpack_from('<i', bs, 424)[0] if 424+4<=len(bs) else 0 for bs in all_bytes]

# Check if all baby/unevolved pokemon = val 5 or 2?
# Family analysis: try to use buddy_distance (which is per family)
# Niantic encodes buddy walk distance per pokedex entry - this is a constant per species
# Like Gyarados has buddy distance=1km, Magikarp=1km, Pikachu=3km, Pumpkaboo=3km, Eevee=5km
# Or maybe 424 = candy tier / family rank

# Check what val Gyarados has across multiple individuals
species_to_val = {}
for idx, v in enumerate(vals_424):
    uid = struct.unpack_from('<Q', all_bytes[idx], 32)[0]
    uid_signed = uid if uid < 2**63 else uid - 2**64
    row = c.execute("SELECT species_name, pokemon_id FROM pokemon WHERE uid=?", (uid_signed,)).fetchone()
    if row:
        species_to_val.setdefault(row[0], Counter())[v] += 1

# Print species where 424 is variable per individual (= per-pokemon attribute)
# vs constant per species (= per-species attribute)
constant_species = 0
variable_species = 0
for s, ctr in species_to_val.items():
    if len(ctr) == 1:
        constant_species += 1
    else:
        variable_species += 1
print(f"  Species with single 424 value (=species attribute): {constant_species}")
print(f"  Species with multiple 424 values (=per-pokemon): {variable_species}")

# Show 5 species where 424 varies
samples = [(s, ctr) for s, ctr in species_to_val.items() if len(ctr) > 1]
print("\nSpecies where 424 varies (sample 10):")
for s, ctr in samples[:10]:
    print(f"  {s}: {dict(ctr)}")

# So if 424 varies per individual, it's a per-pokemon flag
# But if constant per species, it's a species-tier classifier (buddy distance category 1/3/5/20km)

# Check: Gyarados val=1 only? Pikachu has val 1,2,3,4,5?
print()
print("Specific species val tally (most common species):")
for s in ['Pikachu', 'Magikarp', 'Eevee', 'Gyarados', 'Snorlax', 'Pidgey', 'Caterpie', 'Mewtwo', 'Mew', 'Rayquaza']:
    if s in species_to_val:
        print(f"  {s}: {dict(species_to_val[s])}")

# Look at offsets we haven't analyzed yet, like 488 (700 distinct)
# and the 16-20 range bytes
print()
print("=" * 100)
print("PER-INDEX 16-20 byte view (these are hex padding before alignment)")
print("=" * 100)
for off in [16, 17, 18, 19, 20, 21, 22, 23]:
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    nz = sum(1 for v in bvals if v != 0)
    if nz >= 5400:
        c_top = Counter(bvals).most_common(8)
        print(f"  off={off}: nz={nz} top={c_top}")

# Investigate offset 16 - this is unique per pokemon (5377 distinct)?
# Maybe = pointer or ID
print()
i16 = [struct.unpack_from('<i', bs, 16)[0] for bs in all_bytes]
i20 = [struct.unpack_from('<i', bs, 20)[0] for bs in all_bytes]
print(f"i32@16 sample: {i16[:5]}")
print(f"i32@20 sample: {i20[:5]}")

# i32@16 has 2154 distinct values - could be a hash bucket / tag.
# Show raw bytes at 16-31 to see what's there
print()
print("Bytes 0-31 of first 5 pokemon:")
for i, bs in enumerate(all_bytes[:5]):
    print(f"  idx{i}: {bs[:32].hex()}")
print()
print("Bytes 0-31 + 32-63 of pokemon at idx 100:")
print(f"  {all_bytes[100][:64].hex()}")

# Bytes 0-7 are likely a vtable pointer for the C# object. Bytes 8-15 might be hashcode/etc.
# Bytes 16-23 could be data: a count/ID/pointer.

# Check Niantic.Holoholo.Pokemon.PokemonProto field for this offset.
# An IL2CPP managed object in C# has a header of 16 bytes (klass pointer + monitor).
# Then field data starts. Field 1 = pokemon_id_ (int32), Field 2 = cp_, etc.

# Let me check if i32@16 (read as float) is a meaningful 32-bit value:
vals16_f = [struct.unpack_from('<f', bs, 16)[0] for bs in all_bytes]
finite_f = sum(1 for v in vals16_f if v == v and -1e10 < v < 1e10)
print(f"\nf32@16 finite count: {finite_f}")

# Also check 20: this had 5377 nz, dist=9, range 114-1688 - this is mostly small ints (114-119)
# 114-118 = ASCII 'r'-'v' - these are PROBABLY high bytes of pointers
print(f"i32@20 distinct values: {len(set(i20))}")
for v, ct in Counter(i20).most_common(10):
    print(f"  {v} ({hex(v)}): {ct}")

# It seems like i32@16 + i32@20 = 8 bytes that often = a pointer (vtable / klass pointer)
# So this is C# object header data, NOT proto fields. Skip.

# Investigate offset 280 specifically (274 nz, all distinct)
print()
print("=" * 100)
print("OFFSET 280-292 zone - 274/623 sets")
print("=" * 100)
for off in [280, 284, 288, 292]:
    if off+4 > 512: continue
    ivals = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes]
    fvals = [struct.unpack_from('<f', bs, off)[0] for bs in all_bytes]
    nz = sum(1 for v in ivals if v != 0)
    print(f"  off={off}: nz={nz} top_i32={Counter(ivals).most_common(5)}")
    # Read as i64 at that offset
    if off+8 <= 512:
        qvals = [struct.unpack_from('<q', bs, off)[0] for bs in all_bytes]
        ts_count = sum(1 for v in qvals if POGO_LAUNCH_MS < v < NOW_MS + 86400000)
        print(f"    as i64: ts_count={ts_count}")
        if ts_count > 0:
            sample = next(v for v in qvals if POGO_LAUNCH_MS < v < NOW_MS + 86400000)
            print(f"    sample TS: {datetime.fromtimestamp(sample/1000, tz=timezone.utc).isoformat()}")

# Quick crosstabs: are 280 and 288 byte=1 sets correlated with our DB flags?
for off in [280, 288]:
    nz_idx = set(i for i, bs in enumerate(all_bytes) if struct.unpack_from('<i', bs, off)[0] != 0)
    for flag, sql in [('hatched', 'is_hatched_from_egg=1'), ('traded', 'is_traded=1'),
                      ('powered_up', 'is_powered_up=1'), ('mega', 'is_mega_evolved=1')]:
        rows = c.execute(f"SELECT uid FROM pokemon WHERE {sql}").fetchall()
        ext_set = set()
        for (uid_s,) in rows:
            u = s2u(uid_s)
            if u in uid_to_idx: ext_set.add(uid_to_idx[u])
        intersect = len(nz_idx & ext_set)
        if intersect > 0:
            print(f"  off={off} non-zero set ({len(nz_idx)}) overlap with {flag} ({len(ext_set)}): {intersect}")

# Lastly: 448 i32 (nz=3 only) and 452 i32 (nz=3) - probably uninitialized
# 192 = byte=1 for HATCHED + 180 special. Let me see more clearly what these 180 share
# Try checking the 180 against the byte at 192=1 + check whether they were previously deployed at gym
# (deployedFortId would imply 'returned from gym defense')
print()
print("=" * 100)
print("OFFSET 192 final hypothesis: returned_from_gym? deployed_at_gym? captured_with_AR?")
print("=" * 100)

idx_192 = set(i for i, bs in enumerate(all_bytes) if 192 < len(bs) and bs[192] == 1)

# Cross with: deployed_fort_id non-empty OR captured with AR
deployed_count = 0
ar_caught_count = 0
for idx in idx_192:
    bs = all_bytes[idx]
    uid = struct.unpack_from('<Q', bs, 32)[0]
    uid_signed = uid if uid < 2**63 else uid - 2**64
    row = c.execute("SELECT deployed_fort_id, weather_boosted FROM pokemon WHERE uid=?", (uid_signed,)).fetchone()
    if row:
        if row[0]: deployed_count += 1
        if row[1]: ar_caught_count += 1
print(f"  deployed_fort_id NN: {deployed_count}/{len(idx_192)}")
print(f"  weather_boosted NN: {ar_caught_count}/{len(idx_192)}")

# Compare to total pop
total_deployed = c.execute("SELECT COUNT(*) FROM pokemon WHERE deployed_fort_id IS NOT NULL AND deployed_fort_id != ''").fetchone()[0]
total_weather = c.execute("SELECT COUNT(*) FROM pokemon WHERE weather_boosted > 0").fetchone()[0]
print(f"  total pop deployed: {total_deployed}, total weather: {total_weather}")

c.close()
print("\nDone.")
