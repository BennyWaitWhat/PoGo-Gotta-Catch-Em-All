"""Verify candidate offsets and find more."""
import json, struct, sqlite3
from collections import Counter, defaultdict
import math

data = json.load(open('pokemon_v3.json'))
db = sqlite3.connect('pokemon.db')
c = db.cursor()

c.execute('SELECT uid_hex, pokemon_id, species_name, is_traded, is_lucky, is_hatched_from_egg, is_best_buddy, '
          'level, alignment, alignment_name, costume, original_owner, special_bg_id, location_bg_id, cp '
          'FROM pokemon')
known = {row[0]: row for row in c.fetchall()}

paired = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 1000: continue
    bs = bytes.fromhex(raw)
    uid_int = struct.unpack_from('<Q', bs, 32)[0]
    uid_hex = f'{uid_int:016x}'
    if uid_hex not in known: continue
    paired.append((bs, known[uid_hex]))

# Check offset 268 (number ~404-411)
# The gen 9 pokemon might have these as form codes
# But more likely: could be related to "egg incubator type" or "trade timestamp partial"
# Actually 404-411 - looks like a small int. Let me check if it correlates with traded (it's 119 nz)
# and is the trade date span: 404-411 could be decimal-encoded MM-DD-YY?
# More likely: friendship/affinity points

# Look at offset 252 high-bit aligned: 121 nz, distinct=122. If it's an int64 it'd hash a string.
# Let me verify it's an int64 pointing somewhere meaningful.
print('=== Offset 252 inspection ===')
# Check if it correlates with traded (yes - 121 vs 120)
nz252 = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 252)[0] != 0)
nz252_64 = set(k[0] for bs, k in paired if struct.unpack_from('<q', bs, 252)[0] != 0)
traded = set(k[0] for bs, k in paired if k[3])

print(f'  i32 @252 nz: {len(nz252)}')
print(f'  i64 @252 nz: {len(nz252_64)}')
print(f'  Traded: {len(traded)}')
print(f'  i32 nz - traded: {len(nz252 - traded)}')
print(f'  traded - i32 nz: {len(traded - nz252)}')

# View as int64 - looks like hashed values
print('  Sample int64 @252 (treated as signed):')
for bs, k in paired[:5]:
    if k[3]:  # traded
        v = struct.unpack_from('<q', bs, 252)[0]
        print(f'    {k[2]} (traded from {k[11]}): {v}')

# Offset 252-260 might be 'originalLocation' tied with traded
# It's ALREADY at offset 248 according to current parser (originalLocation = i64(248))
# So 252 is the upper 4 bytes of the 248-byte int64
# Actually offset 248 is already mapped!
# The parse was: originalLocation = i64(248). With i32 view at 252 we see the high half.
# That makes 252 NOT a separate field, it's part of 248.

# But wait - 248 has 92 nz (special_bg related), and 252 has 121 nz. So 248-252 might be 8-byte
# but it has 121 distinct nz patterns. Let me check.

# Actually the build_final says originalLocation = i64(248). Look at it:
v248_64 = Counter()
for bs, k in paired:
    if 248 + 8 > len(bs): continue
    v = struct.unpack_from('<q', bs, 248)[0]
    if v != 0:
        v248_64[v] += 1
print(f'\n  i64 @248: {len(v248_64)} distinct values')

# Top samples
print(f'  samples: {list(v248_64)[:5]}')

# Now look at 268 numbers (407, 404, etc)
print('\n=== Offset 268 - 119 nz, values 404-411 ===')
v268 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 268)[0]
    if v != 0:
        v268[v] += 1
print(f'  All values: {sorted(v268.items())}')

# These could be trade levels? Or maybe dates? 407=April 7?
# Let me see what range of pokemon have them
print('  Species with each value:')
for val in sorted(v268):
    cnt = v268[val]
    species = []
    for bs, k in paired:
        if struct.unpack_from('<i', bs, 268)[0] == val:
            species.append(k[2])
            if len(species) >= 3: break
    print(f'    {val}: {cnt} - {species}')

# Check: maybe 268 is the high half of int64 264 (tradedTimeMs)?
# tradedTimeMs is at 264. As int64: 264. Let me check.
print('\n  i64 @264 (tradedTimeMs):')
v264_64 = Counter()
for bs, k in paired:
    if 264 + 8 > len(bs): continue
    v = struct.unpack_from('<q', bs, 264)[0]
    if v != 0:
        v264_64[v] += 1
print(f'  Distinct: {len(v264_64)}')
print(f'  Samples: {sorted(v264_64.keys())[:3]}')
# A timestamp 1735191487993 -> 268 high 32 bits = 1735191487993 >> 32 = 404
print(f'  Test: 1735191487993 / 4294967296 = {1735191487993 / 4294967296:.2f}')
# So 268 is the upper half of tradedTimeMs - already mapped via i64(264)

# === MORE OFFSET ANALYSIS ===
# At offset 192 (558 nz) and 196 (121 nz)
print('\n=== Offset 192 (558 nz) ===')
v192_i = Counter()
v192_f = Counter()
for bs, k in paired:
    vi = struct.unpack_from('<i', bs, 192)[0]
    vf = struct.unpack_from('<f', bs, 192)[0]
    if vi != 0:
        v192_i[vi] += 1
        if not math.isnan(vf) and not math.isinf(vf):
            v192_f[round(vf, 4)] += 1
print(f'  As i32 top: {v192_i.most_common(10)}')
print(f'  As float top: {v192_f.most_common(10)}')

# 558 is close to ~600 (best buddy? 609 best buddies) - maybe it's a buddy distance counter
nz192 = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 192)[0] != 0)
bb_set = set(k[0] for bs, k in paired if k[6])
print(f'  192 nz ∩ best_buddy: {len(nz192 & bb_set)}/{len(bb_set)}')
print(f'  192 nz - best_buddy: {len(nz192 - bb_set)}')

# Float distribution: let's look closely
print('\n=== Offset 192 float distribution ===')
floats = []
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 192)[0]
    if not math.isnan(v) and not math.isinf(v) and v != 0:
        floats.append(v)
print(f'  Count: {len(floats)}, min={min(floats):.4f}, max={max(floats):.4f}, mean={sum(floats)/len(floats):.4f}')
# Histogram-like
buckets = [0]*10
for v in floats:
    if 0 < v < 1: buckets[0] += 1
    elif v < 10: buckets[1] += 1
    elif v < 50: buckets[2] += 1
    elif v < 100: buckets[3] += 1
    elif v < 500: buckets[4] += 1
    elif v < 1000: buckets[5] += 1
    elif v < 5000: buckets[6] += 1
    else: buckets[7] += 1
print(f'  Buckets [<1, <10, <50, <100, <500, <1000, <5000, >=]: {buckets}')

# Let me also check offset 196 (121 nz, very close to traded count)
print('\n=== Offset 196 (121 nz) - close to traded 120 ===')
v196 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 196)[0]
    if v != 0:
        v196[v] += 1
print(f'  Top values: {v196.most_common(10)}')
nz196 = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 196)[0] != 0)
print(f'  nz196 ∩ traded: {len(nz196 & traded)}/{len(traded)}')
# Hmm, 196 is 1 offset from 192, not 4-byte aligned... could be int8 or int16
# Actually 196 is 4-byte aligned (192+4=196). It's a separate int32 field.

# Let me check 192 more carefully - maybe it's "buddy candy awarded" int
# or buddy_total_km (lifetime distance) vs 200 = buddy_distance_walked (per buddy)
# In PoGo: buddy_total_km_walked = total per pokemon, lifetime
# Actually checking: PoGo proto has only one buddy distance - maybe 192 is buddy partner ID?
# Top values of 192 as float showed mostly large numbers - maybe pointer leak

# Look at 192 as raw bytes
print('\n=== Offset 192 raw bytes for nz examples ===')
shown = 0
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 192)[0]
    if v != 0 and v < 100:
        print(f'  PID {k[1]} {k[2]}: 192={v} 196={struct.unpack_from("<i", bs, 196)[0]}, raw[192:200]={bs[192:200].hex()}')
        shown += 1
        if shown >= 10: break

# Let me also look at "buddy_pokemon_id" / "current_buddy" candidate
# Probably a bool/byte - check single byte offsets
print('\n=== Single byte distribution between 280-510 ===')
byte_counts = Counter()
for off in range(280, 512):
    cnt_1 = sum(1 for bs, _ in paired if bs[off] == 1)
    cnt_2 = sum(1 for bs, _ in paired if bs[off] == 2)
    cnt_other = sum(1 for bs, _ in paired if bs[off] not in (0, 1, 2, 0x12, 0x18, 0x20, 0x28, 0x30, 0x40, 0x42, 0x4a, 0x52, 0x5a, 0x62, 0x6a, 0x72, 0x7a, 0x82))
    if cnt_1 > 5 or cnt_2 > 5:
        print(f'  byte +{off}: =1: {cnt_1}, =2: {cnt_2}')
