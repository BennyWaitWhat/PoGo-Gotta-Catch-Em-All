"""Correlate offset stats with known field counts to nail down candidate fields."""
import json, struct, sqlite3
from collections import Counter

print('Loading...')
data = json.load(open('pokemon_v3.json'))
db = sqlite3.connect('pokemon.db')
c = db.cursor()

# Build uid -> known fields map
known = {}
c.execute('SELECT uid_hex, is_traded, is_lucky, is_hatched_from_egg, special_bg_id, location_bg_id, '
          'adventure_effects_left, costume, alignment, is_shiny, is_best_buddy, gender, weather_boosted, '
          'cp_multiplier, num_additional_cpm, level FROM pokemon')
for row in c.fetchall():
    uid_hex = row[0]
    known[uid_hex] = {
        'is_traded': bool(row[1]),
        'is_lucky': bool(row[2]),
        'is_hatched': bool(row[3]),
        'special_bg': row[4],
        'location_bg': row[5],
        'adv_left': row[6],
        'costume': row[7],
        'alignment': row[8],
        'is_shiny': bool(row[9]),
        'is_best_buddy': bool(row[10]),
        'gender': row[11],
        'weather_boosted': row[12],
        'cpm': row[13],
        'num_addl_cpm': row[14],
        'level': row[15],
    }
print(f'Known: {len(known)}')

# Pair each pokemon's raw_proto with its known fields
paired = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 1000: continue
    uid = p.get('uid')
    if not uid: continue
    # uid in DB is uid_signed; raw uid is unsigned. Compute uid_hex from u64
    bs = bytes.fromhex(raw)
    uid_int = struct.unpack_from('<Q', bs, 32)[0]
    uid_hex = f'{uid_int:016x}'
    if uid_hex not in known: continue
    paired.append((bs, known[uid_hex]))
print(f'Paired: {len(paired)}')

# For each known field, find offsets whose value correlates
# Approach: for each candidate offset, partition pokemon by nonzero@offset.
# Then check overlap with known fields.

PROTO_LEN = 512

def correlate(field_name, getter, expected_count):
    """For each offset, see what value at offset has best Jaccard with the boolean partition."""
    # field-positive set
    field_pos = set(i for i, (bs, k) in enumerate(paired) if getter(k))
    if len(field_pos) < 5:
        print(f'  Skip {field_name}: too few positive')
        return
    print(f'\n=== {field_name}: {len(field_pos)} positive (expected ~{expected_count}) ===')

    # Try each 4-byte int offset
    candidates = []
    for off in range(0, PROTO_LEN, 4):
        # Set of indexes with nonzero at offset
        offset_pos = set()
        for i, (bs, k) in enumerate(paired):
            if off + 4 > len(bs): continue
            v = struct.unpack_from('<i', bs, off)[0]
            if v != 0:
                offset_pos.add(i)
        if not offset_pos: continue

        intersect = len(field_pos & offset_pos)
        union = len(field_pos | offset_pos)
        if union == 0: continue
        jaccard = intersect / union
        # Also check if offset_pos is subset of field_pos or vice versa
        in_field = intersect / len(field_pos)
        in_offset = intersect / len(offset_pos) if offset_pos else 0

        if jaccard > 0.5 or (in_field > 0.7 and in_offset > 0.7):
            candidates.append((off, jaccard, len(offset_pos), in_field, in_offset))

    candidates.sort(key=lambda x: -x[1])
    for off, j, opcount, inf, ino in candidates[:10]:
        print(f'  +{off}: jaccard={j:.3f}, |offset|={opcount}, in_field={inf:.2f}, in_offset={ino:.2f}')

    # Also try bytes (booleans)
    print(f'  -- byte=1 candidates --')
    bcand = []
    for off in range(0, PROTO_LEN):
        offset_pos = set()
        for i, (bs, k) in enumerate(paired):
            if off >= len(bs): continue
            if bs[off] == 1:
                offset_pos.add(i)
        if not offset_pos: continue
        intersect = len(field_pos & offset_pos)
        union = len(field_pos | offset_pos)
        if union == 0: continue
        jaccard = intersect / union
        if jaccard > 0.5:
            bcand.append((off, jaccard, len(offset_pos)))
    bcand.sort(key=lambda x: -x[1])
    for off, j, oc in bcand[:5]:
        print(f'  byte +{off}: jaccard={j:.3f}, |offset|={oc}')

# Run correlations
correlate('is_traded', lambda k: k['is_traded'], 120)
correlate('is_lucky', lambda k: k['is_lucky'], 1)  # ?
correlate('is_hatched', lambda k: k['is_hatched'], 374)
correlate('has_special_bg (postcard)', lambda k: k['special_bg'] > 0, 92)
correlate('has_location_bg', lambda k: k['location_bg'] > 0, 14)
correlate('has_adv_effects', lambda k: k['adv_left'] > 0, 21)
correlate('is_best_buddy', lambda k: k['is_best_buddy'], 232)
correlate('is_shadow', lambda k: k['alignment'] == 1, 229)
correlate('is_purified', lambda k: k['alignment'] == 2, 63)

# Now look for offsets that have FLOAT distributions that match buddy_km_walked
# Buddy walked: 0 for most, small floats for a few
print('\n\n=== FLOAT distribution analysis - buddy_km_walked candidates ===')
for off in range(0, PROTO_LEN, 4):
    floats = []
    for bs, k in paired:
        if off + 4 > len(bs): continue
        v = struct.unpack_from('<f', bs, off)[0]
        floats.append(v)
    if not floats: continue
    nz_pos = [v for v in floats if v != 0 and not (v != v) and abs(v) < 1e10]
    if not nz_pos: continue

    # Plausible buddy: nonzero range 0.01 to 1000
    plausible = [v for v in nz_pos if 0.001 <= v <= 1000]
    plausible_pct = len(plausible) / len(nz_pos)

    # Distinguishing buddy_km from CPM: CPM ranges 0.094-0.85, buddy can go higher
    if plausible_pct > 0.95 and len(nz_pos) > 50:
        max_v = max(plausible) if plausible else 0
        # Check distribution
        small = sum(1 for v in plausible if v < 1)
        med = sum(1 for v in plausible if 1 <= v < 10)
        large = sum(1 for v in plausible if v >= 10)
        print(f'  +{off}: {len(nz_pos)} nz, max={max_v:.2f}, dist(small/med/large): {small}/{med}/{large}, samples: {sorted(set(round(v, 4) for v in plausible))[:5]}')
