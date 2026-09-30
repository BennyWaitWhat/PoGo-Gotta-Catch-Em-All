"""Final round of digging."""
import json, struct, sqlite3, math
from collections import Counter, defaultdict

data = json.load(open('pokemon_v3.json'))
db = sqlite3.connect('pokemon.db')
c = db.cursor()

c.execute('SELECT uid_hex, pokemon_id, species_name, is_traded, is_lucky, is_hatched_from_egg, is_best_buddy, '
          'level, alignment, alignment_name, costume, original_owner, special_bg_id, location_bg_id, cp, '
          'origin_detail_name, num_additional_cpm, deployed_fort_id, weather_boosted '
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

# === VERIFY MEGA EVOLUTION AT 336+ ===
# 336=is_mega_evolved (byte=1, 154 entries)
# 340=mega_level (1 or 2, 17/19 entries)
# 344=mega_cp (int, varies)
# 348=mega_cpm_extra (float, ~1.0)
# 352=mega_cpm (CPM-like float)
print('=== MEGA EVOLUTION cluster (336-352) ===')
print('  336 byte=1:')
for bs, k in paired[:5]:
    if bs[336] == 1:
        v336 = bs[336]
        v340 = bs[340]
        v344 = struct.unpack_from('<i', bs, 344)[0]
        v348 = struct.unpack_from('<f', bs, 348)[0]
        v352 = struct.unpack_from('<f', bs, 352)[0]
        # Display info
        print(f'    PID {k[1]} {k[2]} CP={k[14]}: mega_byte={v336}, mega_level={v340}, mega_cp={v344}, cpm_a={v348:.4f}, cpm_b={v352:.4f}')

# Show 5 samples from each variant
mega_pokemon = [(bs, k) for bs, k in paired if bs[336] == 1]
print(f'  Total mega: {len(mega_pokemon)}')

# Check 340: levels (1 = mega 1, 2 = mega 2?)
v340_dist = Counter()
for bs, k in mega_pokemon:
    v340_dist[bs[340]] += 1
print(f'  340 dist for mega: {dict(v340_dist)}')

# What's the 'expires_at' for mega? After temporary mega, this would be a timestamp.
# Mega expires after 8 hours - should be a future timestamp
# Look at int64 in 336+
for off in [336, 344, 352, 360, 368, 376, 384, 392, 400, 408]:
    ts_count = 0
    for bs, k in mega_pokemon:
        if off + 8 > len(bs): continue
        v = struct.unpack_from('<q', bs, off)[0]
        if 1700000000000 <= v <= 1900000000000:  # plausible recent timestamps in ms
            ts_count += 1
    if ts_count > 5:
        print(f'  +{off} as i64 ts: {ts_count}/{len(mega_pokemon)} look like timestamps')

# === FOR HATCHED POKEMON: find hatched_distance/start ===
hatched = [(bs, k) for bs, k in paired if k[5]]
print(f'\n=== Hatched-only floats (looking for KM remaining or start) ===')
# Test a few specific offsets that showed promise
for off in [88, 92, 96, 100, 200, 416, 488]:
    nz_h = 0
    nz_oth = 0
    for bs, k in paired:
        v = struct.unpack_from('<f', bs, off)[0]
        if v != 0 and not math.isnan(v) and not math.isinf(v) and 0.1 <= v <= 1000:
            if k[5]: nz_h += 1
            else: nz_oth += 1
    print(f'  +{off}: hatched_nz={nz_h}/377, others_nz={nz_oth}')

# === OFFSET 144 - 304 nz, counter ===
# It's a counter from 1 to 200ish, with 137 average.
# Suspect: total_buddy_distance_km (cumulative) - a few have ridiculous numbers
# Actually wait, offset 144 max was 4003. Sum was 41824.
# Let me look at it again specifically
print('\n=== Offset 144 FULL distribution ===')
v144 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 144)[0]
    if v != 0:
        v144[v] += 1
ranges = [(0, 10, 0), (10, 50, 0), (50, 100, 0), (100, 500, 0), (500, 1000, 0), (1000, 5000, 0)]
for v in v144:
    cnt = v144[v]
    for i, (lo, hi, _) in enumerate(ranges):
        if lo <= v < hi:
            ranges[i] = (lo, hi, ranges[i][2] + cnt)
            break
print(f'  Buckets: {[(r[0], r[1], r[2]) for r in ranges]}')

# Show top values
print(f'  Top 30 values: {sorted(v144.items(), key=lambda x: -x[1])[:30]}')
print(f'  Top 10 max values: {sorted(v144.keys(), reverse=True)[:10]}')

# Check correlation with is_best_buddy more specifically
nz144 = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 144)[0] != 0)
bb = set(k[0] for bs, k in paired if k[6])
print(f'  nz144 = {len(nz144)}, bb = {len(bb)}')
print(f'  nz144 ∩ bb: {len(nz144 & bb)}')
print(f'  nz144 - bb: {len(nz144 - bb)}')

# Show the 40 highest 144 values with context
print('\n  Highest 144 values:')
sorted_pairs = []
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 144)[0]
    if v != 0:
        sorted_pairs.append((v, k[2], k[7], k[6], k[14]))  # value, species, level, is_bb, cp
for v, sp, lvl, bb, cp in sorted(sorted_pairs, reverse=True)[:20]:
    print(f'    {v} - {sp} L{lvl} BB={bb} CP={cp}')

# === OFFSETS 416+ - 171 nz - what fields? ===
print('\n=== Offset 412/416 cluster (171 nz) ===')
# Try int64 at 408, 416
for off in [408, 412, 416, 420]:
    nz = 0
    samples = []
    for bs, k in paired:
        if off + 8 > len(bs): continue
        v = struct.unpack_from('<q', bs, off)[0]
        if v != 0:
            nz += 1
            if len(samples) < 5: samples.append(v)
    print(f'  +{off} i64: nz={nz}, samples: {samples}')

# As int32
for off in [408, 412, 416, 420, 424]:
    nz = 0
    distinct = set()
    for bs, k in paired:
        if off + 4 > len(bs): continue
        v = struct.unpack_from('<i', bs, off)[0]
        if v != 0:
            nz += 1
            distinct.add(v)
    print(f'  +{off} i32: nz={nz}, distinct={len(distinct)}')

# === STRING POINTER AT 488/120 ETC ===
# Check if 488 is a STRING pointer
print('\n=== Offset 488 analysis ===')
ptrs = []
for bs, k in paired:
    if 488 + 8 > len(bs): continue
    v = struct.unpack_from('<Q', bs, 488)[0]
    if v != 0:
        ptrs.append(v)
print(f'  Total nonzero pointers: {len(ptrs)}')
print(f'  Top byte distribution:')
top_bytes = Counter()
for p in ptrs:
    top_bytes[(p >> 32) & 0xFF] += 1
print(f'  {top_bytes.most_common(10)}')
# If many start with 0x70-0x7F, they're stack/heap pointers

# Try float interpretation again - very small positive values?
print('  As float distribution:')
floats_488 = []
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 488)[0]
    if not math.isnan(v) and not math.isinf(v) and v != 0:
        floats_488.append(v)
small = sum(1 for v in floats_488 if 0.001 <= abs(v) <= 1)
medium = sum(1 for v in floats_488 if 1 <= abs(v) <= 100)
large = sum(1 for v in floats_488 if 100 < abs(v) <= 100000)
huge = sum(1 for v in floats_488 if abs(v) > 100000)
print(f'  small/medium/large/huge: {small}/{medium}/{large}/{huge}')

# It's likely garbage - 488 might just be uninitialized memory near the end
# Pokemon proto might end at 480, with 488-512 being padding/unused

# === Check OFFSET 192 byte ===
# 192 i32 = 1 for 557 pokemon. byte 192 = 1 also.
# What's at offset 192 in the proto? Could be hatched_from_egg flag (alternative path)
# Or could be a 'is_in_inventory' marker
# 558 nz at 192 - bit too many for hatched (377).
# Let me check who is in this 558 minus hatched
nz192 = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 192)[0] != 0)
hatched_set = set(k[0] for bs, k in paired if k[5])
print(f'\n=== Offset 192 ===')
print(f'  nz192={len(nz192)}, hatched={len(hatched_set)}')
print(f'  nz192 ∩ hatched: {len(nz192 & hatched_set)}')
print(f'  nz192 - hatched: {len(nz192 - hatched_set)}')  # 181 not hatched
extras = nz192 - hatched_set
print(f'  Sample non-hatched-but-nz192:')
for uid in list(extras)[:10]:
    row = known[uid]
    print(f'    PID {row[1]} {row[2]} - origin={row[15]}')

# === 0x130 string offset (304 in raw) - COSTUME_DECORATION ===
# Already known: only 2 pokemon have 'season28_pancham' / 'season28_gyamask'
# Note pancham is 674 (correct), gyamask = "gyamask" likely Yamask/Phantump variant?
# YIKES - PID 562 is YAMASK base (Galarian + non-Galarian), so 'season28_gyamask' = season 28 yamask costume
# Actually this is offset 304 in raw proto = field "costume_id_string" or "season_decoration_id"

# === CHECK 280-300 cluster (most non-zero offsets) ===
print('\n=== Cluster around 280-300 ===')
# Looking at scan: 280=274 nz, 284=274 nz, 288=624 nz, 292=623 nz
# 280/284 might be int64; 288/292 might be int64
for off in [280, 288]:
    samples = []
    for bs, k in paired:
        if off + 8 > len(bs): continue
        v = struct.unpack_from('<q', bs, off)[0]
        if v != 0:
            samples.append(v)
    print(f'  +{off} i64: nz={len(samples)}')
    # Top byte
    top = Counter()
    for v in samples:
        top[(v >> 56) & 0xFF] += 1
    print(f'    high byte: {top.most_common(5)}')
    print(f'    samples: {samples[:5]}')

# === OFFSET 488 / 492 cluster - 700 nz ===
# 492 byte values are 114, 116, 118 - those are ASCII for 'r', 't', 'v'
# 488 nz = 699, 492 nz = 701 (basically same)
# 488-499 could be a string pointer + length + flag
# Let me check raw bytes at 488
print('\n=== Offset 488 raw byte patterns ===')
patterns = Counter()
for bs, k in paired:
    if 488 + 8 > len(bs): continue
    pattern = bs[488:496].hex()
    patterns[pattern] += 1
print(f'  Top patterns: {patterns.most_common(5)}')

# Looking at offset 432 (1416 nz, 8 distinct higher bytes = pointers)
print('\n=== Offset 432 (1416 nz) - high value count ===')
v432_64 = Counter()
top_byte = Counter()
for bs, k in paired:
    if 432 + 8 > len(bs): continue
    v = struct.unpack_from('<Q', bs, 432)[0]
    if v != 0:
        v432_64[v] += 1
        top_byte[(v >> 32) & 0xFFFFFFFF] += 1
print(f'  Distinct: {len(v432_64)}, top high32: {top_byte.most_common(5)}')

# === 200-280 range ===
print('\n=== 200-280 range cluster ===')
# 196 (121 nz int32 top values 1, 2, 5, 4...)
# 200 = buddy_km_walked confirmed
# Let me look at 196 more carefully
print('Offset 196 distribution:')
v196 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 196)[0]
    if v != 0:
        v196[v] += 1
print(f'  Top: {v196.most_common(20)}')
print(f'  Range: {min(v196)} to {max(v196)}')

# 196 has small ints 1-19 - could be num_powered_up or num_powered_up_count
# Strong correlation with 200 (buddy_km)?
nz196 = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 196)[0] != 0)
nz200 = set(k[0] for bs, k in paired if struct.unpack_from('<f', bs, 200)[0] != 0 and not math.isnan(struct.unpack_from('<f', bs, 200)[0]))
print(f'  nz196 ∩ nz200: {len(nz196 & nz200)}/{len(nz196)}')

# Probably 196 is "buddy candy awarded" or "num_buddy_walks_completed"
