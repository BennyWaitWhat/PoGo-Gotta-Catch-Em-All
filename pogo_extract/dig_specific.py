"""Dig into specific offsets that look like candidates."""
import json, struct, sqlite3
from collections import Counter

data = json.load(open('pokemon_v3.json'))
db = sqlite3.connect('pokemon.db')
c = db.cursor()

# Build correlated data
c.execute('SELECT uid_hex, pokemon_id, species_name, is_traded, is_lucky, is_hatched_from_egg, is_best_buddy, '
          'level, alignment_name, costume, original_owner, traded_date, special_bg_id, location_bg_id '
          'FROM pokemon')
known = {row[0]: row for row in c.fetchall()}

print('=== Detailed inspection of specific offsets ===\n')

# Build ordered list of (proto_bytes, db_row)
paired = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 1000: continue
    bs = bytes.fromhex(raw)
    uid_int = struct.unpack_from('<Q', bs, 32)[0]
    uid_hex = f'{uid_int:016x}'
    if uid_hex not in known: continue
    paired.append((bs, known[uid_hex]))


# === OFFSET 200 (buddy_km_walked candidate) ===
print('=== Offset 200 (197 nz, floats 0.014-469) - candidate buddy_km_walked ===')
samples = []
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 200)[0]
    if v != 0:
        samples.append((v, k[2], k[7]))  # value, species, level

samples.sort(key=lambda x: -x[0])
print(f'Top 10 highest values:')
for v, sp, lvl in samples[:10]:
    print(f'  {v:.3f} km - {sp} (level {lvl})')
print(f'Bottom 10 lowest values:')
for v, sp, lvl in sorted(samples)[:10]:
    print(f'  {v:.3f} km - {sp} (level {lvl})')

# Count unique zero-vs-nonzero correlation with best_buddy
nz_set = set(k[0] for bs, k in paired if struct.unpack_from('<f', bs, 200)[0] != 0)
bb_set = set(k[0] for bs, k in paired if k[6])
print(f'\nNonzero @200 ∩ best_buddy: {len(nz_set & bb_set)}/{len(bb_set)}')
print(f'Nonzero @200 only (not best_buddy): {len(nz_set - bb_set)}')

# === OFFSET 348/352 - power-up multiplier stuff ===
print('\n=== Offset 348 + 352 - floats - 154 pokemon have these ===')
samples = []
for bs, k in paired:
    v348 = struct.unpack_from('<f', bs, 348)[0]
    v352 = struct.unpack_from('<f', bs, 352)[0]
    if v348 != 0 or v352 != 0:
        samples.append((v348, v352, k[2], k[7], k[1]))

print(f'Total: {len(samples)}')
for v348, v352, sp, lvl, pid in samples[:15]:
    print(f'  348={v348:.4f}  352={v352:.4f}  - PID {pid} {sp} (level {lvl})')

# Check what other field at 154 nz: 336 byte=1 had 154
print('\n=== Offset 336 (byte=1 = 154) ===')
b336 = sum(1 for bs, _ in paired if bs[336] == 1)
b340 = sum(1 for bs, _ in paired if bs[340] == 1)
b340_2 = sum(1 for bs, _ in paired if bs[340] == 2)
print(f'  byte 336=1: {b336}')
print(f'  byte 340=1: {b340}')
print(f'  byte 340=2: {b340_2}')

# Look at 344 (152 distinct values)
print('\n=== Offset 344 (152 distinct) ===')
vals = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 344)[0]
    if v != 0:
        vals[v] += 1
print(f'  Top values: {vals.most_common(10)}')

# Probably mega evolution data - check if pokemon with these are mega-eligible
# Mega-eligible: Beedrill, Blastoise, Charizard etc (PID 1, 3, 6, 9, 12, 15, 18, ...)
MEGA_PIDS = {3, 6, 9, 15, 18, 65, 80, 94, 115, 127, 130, 142, 150, 181, 208, 212, 214, 229, 248, 254, 257, 260, 282, 302, 303, 306, 308, 310, 319, 323, 334, 354, 359, 362, 373, 376, 380, 381, 384, 428, 445, 448, 460, 475, 531, 719}
mega_eligible_with_348 = 0
non_mega_with_348 = 0
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 348)[0]
    if v != 0:
        if k[1] in MEGA_PIDS:
            mega_eligible_with_348 += 1
        else:
            non_mega_with_348 += 1
print(f'  Pokemon with 348 nonzero: {mega_eligible_with_348} mega-eligible, {non_mega_with_348} not')

# Also check 348 with species name distribution
v348_species = Counter()
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 348)[0]
    if v != 0:
        v348_species[k[2]] += 1
print(f'  Top species with 348 nonzero: {v348_species.most_common(10)}')

# === OFFSET 252/268 - traded-related second fields ===
print('\n=== Offsets 252 and 268 - traded-related ===')
print('Offset 252 distinct values:')
v252 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 252)[0]
    if v != 0:
        v252[v] += 1
print(f'  {v252.most_common(10)}')

print('Offset 268 distinct values:')
v268 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 268)[0]
    if v != 0:
        v268[v] += 1
print(f'  {v268.most_common(10)}')

# Treat 252 as int64 - it could be original owner ID
print('\nOffset 252 as int64:')
v252_64 = Counter()
for bs, k in paired:
    if 252 + 8 > len(bs): continue
    v = struct.unpack_from('<q', bs, 252)[0]
    if v != 0:
        v252_64[v] += 1
print(f'  Distinct: {len(v252_64)}')
print(f'  Samples: {list(v252_64)[:5]}')

# Look for is_lucky_friend (traded with lucky friend = lucky)
print('\nLucky vs Traded check at byte 269:')
lucky_set = set(k[0] for bs, k in paired if k[4])  # is_lucky
b269_set = set(k[0] for bs, k in paired if bs[269] == 1)
print(f'  Lucky: {len(lucky_set)}, byte+269: {len(b269_set)}')
print(f'  Lucky AND byte+269: {len(lucky_set & b269_set)}')
print(f'  Lucky NOT byte+269: {len(lucky_set - b269_set)}')
print(f'  byte+269 NOT Lucky: {len(b269_set - lucky_set)}')

# === OFFSET 296 - is_purified ===
print('\n=== Offset 296 - purified candidate ===')
purified_set = set(k[0] for bs, k in paired if k[8] == 'PURIFIED')
o296_byte = set(k[0] for bs, k in paired if bs[296] == 1)
print(f'  Purified: {len(purified_set)}, byte+296=1: {len(o296_byte)}')
print(f'  Purified ∩ byte: {len(purified_set & o296_byte)}')
# If purified count is 62 and 296 has 52 byte=1, maybe not perfect. Actually our DB shows 62 purified.
# The known is alignment in display proto, but this field 296 in proto would be related
# Actually check the value at 296 (could be int32)
v296 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 296)[0]
    if v != 0:
        v296[v] += 1
print(f'  Distinct values @296: {v296.most_common(5)}')

# === OFFSET 488/492 - ~700 nonzero ===
print('\n=== Offset 488/492 - 699 nonzero ===')
v488 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 488)[0]
    if v != 0:
        v488[round(v, 4)] += 1
print(f'  488 as float top: {v488.most_common(10)}')

v492 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 492)[0]
    if v != 0:
        v492[v] += 1
print(f'  492 as int32 top: {v492.most_common(10)}')

# Try as int64 at 488 - timestamp?
v488_64 = Counter()
ts_match = 0
for bs, k in paired:
    if 488 + 8 > len(bs): continue
    v = struct.unpack_from('<q', bs, 488)[0]
    if v != 0:
        v488_64[v] += 1
        if 1467590400000 <= v <= 1800000000000:
            ts_match += 1
print(f'  488 as int64: {len(v488_64)} distinct, timestamps: {ts_match}')
samples_488 = list(v488_64)[:5]
print(f'  samples: {samples_488}')

# Distribution: maybe it's a secondary pokemon id (mega base id, partner id)?
# Check what values look like
print('  Top int32 @488:')
v488_i = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 488)[0]
    if v != 0:
        v488_i[v] += 1
print(f'  {v488_i.most_common(10)}')

# === OFFSET 144 - 304 nonzero ===
print('\n=== Offset 144 - 304 nonzero ===')
v144 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 144)[0]
    if v != 0:
        v144[v] += 1
print(f'  Top: {v144.most_common(10)}')
# Check correlation with anything specific
v144_set = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 144)[0] != 0)
deployed_set = set(k[0] for k_, k in [(k[0], k) for bs, k in paired]
                    if False)  # need deployed_fort field
print(f'  144 nonzero count: {len(v144_set)}')

# === OFFSET 416 - 171 nonzero floats ===
print('\n=== Offset 416 - 171 nonzero ===')
v416_f = Counter()
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 416)[0]
    if v != 0 and not (v != v):
        v416_f[round(v, 4)] += 1
print(f'  As float top: {v416_f.most_common(10)}')

v416_i = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 416)[0]
    if v != 0:
        v416_i[v] += 1
print(f'  As int32 top: {v416_i.most_common(10)}')

# Try int64 at 412 (8-byte aligned)
v412_64 = Counter()
ts_match = 0
for bs, k in paired:
    if 412 + 8 > len(bs): continue
    v = struct.unpack_from('<q', bs, 412)[0]
    if v != 0:
        v412_64[v] += 1
        if 1467590400000 <= v <= 1800000000000:
            ts_match += 1
print(f'  412 as int64: {len(v412_64)} distinct, ts: {ts_match}')
print(f'  samples: {list(v412_64)[:5]}')
