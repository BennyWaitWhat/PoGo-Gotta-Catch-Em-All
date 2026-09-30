"""Find buddy fields - friendship, partner, hatched_distance, etc."""
import json, struct, sqlite3
from collections import Counter, defaultdict
import math

data = json.load(open('pokemon_v3.json'))
db = sqlite3.connect('pokemon.db')
c = db.cursor()

c.execute('SELECT uid_hex, pokemon_id, species_name, is_traded, is_lucky, is_hatched_from_egg, is_best_buddy, '
          'level, alignment, alignment_name, costume, original_owner, special_bg_id, location_bg_id, cp, '
          'origin_detail_name, num_additional_cpm, deployed_fort_id '
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

# === HATCHED DISTANCE ===
# Hatched-from-egg pokemon should have a distance field
# We have eggKmWalkedTarget at offset 92 - that's the egg target (2km, 5km, 10km, etc)
# Look for: actual distance walked? maybe hatched timestamp?
hatched = [(bs, k) for bs, k in paired if k[5]]
print(f'Hatched: {len(hatched)}')

print('\n=== Hatched-from-egg specific offsets ===')
# Find offsets that are nonzero specifically for hatched pokemon
for off in range(0, 512, 4):
    nz_hatched = sum(1 for bs, k in hatched if struct.unpack_from('<i', bs, off)[0] != 0)
    nz_others = sum(1 for bs, k in paired if not k[5] and struct.unpack_from('<i', bs, off)[0] != 0)
    if nz_hatched > 100 and (nz_hatched / len(hatched)) > 0.7 and (nz_others / (len(paired) - len(hatched))) < 0.1:
        # Show what this looks like
        samples = []
        for bs, k in hatched[:5]:
            v_i = struct.unpack_from('<i', bs, off)[0]
            v_f = struct.unpack_from('<f', bs, off)[0]
            if v_i != 0:
                samples.append((v_i, v_f, k[2]))
        print(f'  +{off}: {nz_hatched}/{len(hatched)} hatched nz, {nz_others}/{len(paired)-len(hatched)} non-hatched. Samples: {samples}')

# === BEST BUDDY SPECIFIC ===
# Best buddies: 232 (I think build_final has is_best_buddy = num_additional_cpm > 0, which is 609)
# Let me check what the actual best buddy count is in our DB
print('\n=== Best buddy specific ===')
c.execute('SELECT COUNT(*) FROM pokemon WHERE num_additional_cpm > 0')
print(f'  num_additional_cpm > 0: {c.fetchone()[0]}')
# Real best buddy is determined by best_buddy_active = 1 OR by KEY_BEST_BUDDY_LEVEL > 0
# At offset 172 is num_additional_cpm. That might just be 'extra cpm' not best buddy specifically.

# Try finding "best_buddy_level" candidate offsets - small int 0-3 (Good Friend, Great Friend, Ultra Friend, Best Friend)
for off in range(0, 512):
    cnt_1 = sum(1 for bs, k in paired if bs[off] == 1)
    cnt_2 = sum(1 for bs, k in paired if bs[off] == 2)
    cnt_3 = sum(1 for bs, k in paired if bs[off] == 3)
    cnt_4 = sum(1 for bs, k in paired if bs[off] == 4)
    if cnt_4 > 0 and cnt_3 > 0 and cnt_2 > 0 and cnt_1 > 0 and cnt_1 + cnt_2 + cnt_3 + cnt_4 < 1000:
        print(f'  byte +{off}: 1={cnt_1}, 2={cnt_2}, 3={cnt_3}, 4={cnt_4} (could be friend level)')

# === FIND HATCHED_DISTANCE FIELD ===
# In hatched pokemon, look for floats that range 0-10
print('\n=== Hatched-only float candidates (range 0-15) ===')
for off in range(0, 512, 4):
    floats_hatched = []
    floats_other = []
    for bs, k in paired:
        v = struct.unpack_from('<f', bs, off)[0]
        if math.isnan(v) or math.isinf(v): continue
        if k[5]:  # hatched
            floats_hatched.append(v)
        else:
            floats_other.append(v)
    plausible_h = sum(1 for v in floats_hatched if 0.001 <= v <= 30)
    plausible_o = sum(1 for v in floats_other if 0.001 <= v <= 30)
    if plausible_h > 100 and plausible_o < 100:
        nz = [v for v in floats_hatched if 0.001 <= v <= 30]
        print(f'  +{off}: {plausible_h}/{len(hatched)} hatched plausible, {plausible_o}/non-hatched. min={min(nz):.3f} max={max(nz):.3f} samples={sorted(set(round(v, 3) for v in nz[:50]))[:10]}')

# === What does offset 200 buddy_km do for hatched-only ===
print('\n=== Offset 200 (buddy_km) by origin_detail ===')
# Maybe 200 is hatched_distance in some entries vs buddy_km in others?
by_origin = defaultdict(list)
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 200)[0]
    if v != 0 and not math.isnan(v) and not math.isinf(v):
        by_origin[k[15]].append((v, k[2], k[7]))

for orig, vals in sorted(by_origin.items(), key=lambda x: -len(x[1]))[:8]:
    print(f'  {orig}: {len(vals)} entries')
    if len(vals) > 5:
        vmax = max(v for v, _, _ in vals)
        vmin = min(v for v, _, _ in vals)
        print(f'    range: {vmin:.3f}-{vmax:.3f}')

# Probably buddy_km only - not hatched specific. Hatched_distance is likely
# tied to egg_km_walked_target (already mapped at 92)

# === LOOK FOR FRIENDSHIP / AFFINITY ===
# In PoGo, pokemon don't directly have friendship - that's per-trainer.
# But some pokemon have 'best_buddy_score' or 'partner_score'

# === CHECK 144 (304 nz, top values 1, 2, 3...) ===
print('\n=== Offset 144 - 304 nz ===')
v144 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 144)[0]
    if v != 0:
        v144[v] += 1
print(f'  Distribution: {sorted(v144.items())[:30]}')

# 144 - might be number of times power-upped, # of trades, candy used count, etc
# Try int64 at 140 (already i32)
v140_64 = Counter()
for bs, k in paired:
    if 140 + 8 > len(bs): continue
    v = struct.unpack_from('<q', bs, 140)[0]
    if v != 0:
        v140_64[v] += 1
print(f'  i64 @140: {len(v140_64)} distinct')

# Check 144 against candy/xp - not in our DB, but might match deployed pokemon (in gym)
deployed = set(k[0] for bs, k in paired if k[17])
nz144 = set(k[0] for bs, k in paired if struct.unpack_from('<i', bs, 144)[0] != 0)
print(f'  Deployed: {len(deployed)}, nz144: {len(nz144)}')
print(f'  144 ∩ deployed: {len(nz144 & deployed)}')
print(f'  144 NOT deployed: {len(nz144 - deployed)}')

# 144 has 304 nz. Top values 1, 2, 3, 4... That's a small enum/counter.
# Maybe number of times traded? Powered up count? Charge moves count?

# Maybe it's "number of times powered up using stardust" - power-up count
# Best buddies probably have many power-ups: cross-correlate
bb_set = set(k[0] for bs, k in paired if k[6])
print(f'  nz144 ∩ best_buddy: {len(nz144 & bb_set)} / {len(bb_set)}')

# Or coordinate with high-CP / level 50 pokemon
high_lvl = set(k[0] for bs, k in paired if k[7] and k[7] >= 40)
print(f'  nz144 ∩ level 40+: {len(nz144 & high_lvl)}')

# Check 144 average
v144_total = sum(struct.unpack_from('<i', bs, 144)[0] for bs, k in paired)
nz_count = sum(1 for bs, k in paired if struct.unpack_from('<i', bs, 144)[0] != 0)
print(f'  Total of nz: {v144_total}, count {nz_count}, avg: {v144_total/nz_count if nz_count else 0:.2f}')

# === CHECK 296 (52 with byte=1, expected 62 purified) ===
# Maybe byte 296 is "is_purified" but only the purified ones with full process complete?
purified = set(k[0] for bs, k in paired if k[8] == 2)
b296 = set(k[0] for bs, k in paired if bs[296] == 1)
print(f'\n=== Byte +296 (purified candidate) ===')
print(f'  Purified (alignment=2): {len(purified)}, byte+296=1: {len(b296)}')
print(f'  ∩ : {len(purified & b296)}')
print(f'  Purified NOT byte: {len(purified - b296)}')
print(f'  Byte NOT purified: {len(b296 - purified)}')
# Show the 10 missed - they should all be purified
extras = b296 - purified
print(f'  Sample extras (byte set, not purified):')
for uid in list(extras)[:5]:
    row = known[uid]
    print(f'    {row[2]} alignment={row[8]} ({row[9]})')

# Look at offset 488 (~700 nz) - maybe buddy related?
print('\n=== Offset 488 distribution (~700 nz) - probably pointer or float ===')
# Floats showed -0.0 mostly. Let me check more
v488_f = []
for bs, k in paired:
    v = struct.unpack_from('<f', bs, 488)[0]
    if v != 0 and not math.isnan(v):
        v488_f.append(v)
print(f'  Float min/max: {min(v488_f):.4f} / {max(v488_f):.4f}')
print(f'  Range: -ve count = {sum(1 for v in v488_f if v < 0)}, +ve: {sum(1 for v in v488_f if v > 0)}')
# Most floats are tiny negative numbers - likely garbage from string pointer reads?

# Check 488 as i64
v488_64 = []
for bs, k in paired:
    if 488 + 8 > len(bs): continue
    v = struct.unpack_from('<q', bs, 488)[0]
    if v != 0:
        v488_64.append(v)
nz = sorted(v488_64)
print(f'  i64: count={len(nz)}, min={nz[0]}, max={nz[-1]}')
# Likely a string pointer? Or addr leak. Let me see how many are pointer-like
ptr_like = sum(1 for v in v488_64 if 0x500000000000 <= abs(v) <= 0x800000000000)
print(f'  ptr-like (0x5..-0x8.. range): {ptr_like}/{len(v488_64)}')

# 488 is at 488. proto is 512. 488+8=496. So 488 is 8 bytes from end - it's probably the LAST
# field (or near). PokemonProto might end here. The bytes at 488-496 could be padding or end.
# Actually 480 has location_bg_id = i32, 488 = some int64, 496 = adventure_effects_left
# So 488-495 is 8 bytes between two known fields. Could be a pointer to STRING (last name reset?)

# Let me look at offset 480 byte data for postcards
print('\n=== Offset 480 - location_bg ===')
v480 = Counter()
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 480)[0]
    if v != 0:
        v480[v] += 1
print(f'  Top: {v480.most_common(20)}')
