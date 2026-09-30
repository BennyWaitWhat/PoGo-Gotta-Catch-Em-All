"""
Cross-correlate offset patterns with known cohorts to identify field meanings.

Cohorts from build_final.py / database:
- traded: tradedTimeMs > 0  (~ 120)
- best buddy: numAdditionalCpMultiplier > 0  (~ 232)
- hatched: byte at 225 == 1  (~ 374)
- adventure_effects_left > 0 at +496  (~ 21)
- special_bg_id > 0 at +440  (~ 92)
- location_bg_id > 0 at +480  (~ 14)
"""
import json, struct
from collections import Counter, defaultdict

EMPTY_LO = -2118004928

data = json.load(open('pokemon_v3.json'))
all_bytes = [bytes.fromhex(p['raw_proto']) for p in data if len(p.get('raw_proto', '')) >= 1024]
N = len(all_bytes)
print(f"{N} pokemon\n")

# Compute cohort masks for each pokemon
def is_traded(bs):
    return struct.unpack_from('<q', bs, 264)[0] > 0
def is_best_buddy(bs):
    return struct.unpack_from('<f', bs, 172)[0] > 0
def is_hatched(bs):
    return bs[225] != 0
def has_adv_effect(bs):
    return struct.unpack_from('<i', bs, 496)[0] > 0
def has_special_bg(bs):
    return struct.unpack_from('<i', bs, 440)[0] > 0
def has_location_bg(bs):
    return struct.unpack_from('<i', bs, 480)[0] > 0
def is_lucky(bs):
    return bs[272] != 0
def is_shadow(bs):
    # Need display alignment - skip in this proto-only context
    return False
def has_egg_target(bs):
    return struct.unpack_from('<f', bs, 92)[0] > 0

cohorts = {
    'traded': [is_traded(bs) for bs in all_bytes],
    'best_buddy': [is_best_buddy(bs) for bs in all_bytes],
    'hatched': [is_hatched(bs) for bs in all_bytes],
    'adv_effect': [has_adv_effect(bs) for bs in all_bytes],
    'special_bg': [has_special_bg(bs) for bs in all_bytes],
    'location_bg': [has_location_bg(bs) for bs in all_bytes],
    'lucky': [is_lucky(bs) for bs in all_bytes],
    'has_egg_target': [has_egg_target(bs) for bs in all_bytes],
}
for cn, mask in cohorts.items():
    print(f'  cohort {cn}: {sum(mask)}')
print()

# For each unmapped offset, count how many pokemon are nonzero AND in each cohort
KNOWN_OFFSETS = {32, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128, 136, 160, 168, 172, 225, 248, 264, 272, 276, 440, 480, 496}
# 8-byte known: 64, 184, 256, 304, 360, 384 (string ptrs); 216 (display ptr); 32, 136, 160, 248, 264 (i64s)
KNOWN_PTR_OFFSETS = {64, 184, 256, 304, 360, 384, 216}

# An offset is "set" if int32 nonzero
candidates = []
for off in range(0, 508, 4):
    if off in KNOWN_OFFSETS: continue
    if off in KNOWN_PTR_OFFSETS or off+4 in KNOWN_PTR_OFFSETS: continue  # skip ptr halves

    set_mask = []
    for bs in all_bytes:
        if off + 4 > len(bs):
            set_mask.append(False)
            continue
        v = struct.unpack_from('<i', bs, off)[0]
        # for 8-byte ptr slots, treat empty-string sentinel as "not set"
        if v == EMPTY_LO:
            set_mask.append(False)
            continue
        set_mask.append(v != 0)

    set_count = sum(set_mask)
    if set_count < 5 or set_count > N - 5:
        continue

    # Compute conditional probabilities
    line = f"+{off:>3} (set={set_count:>4}): "
    for cn, mask in cohorts.items():
        cohort_size = sum(mask)
        if cohort_size == 0: continue
        # P(set | cohort) and P(cohort | set)
        both = sum(1 for i in range(N) if set_mask[i] and mask[i])
        pcs = both / cohort_size if cohort_size else 0
        pcoh_given_set = both / set_count if set_count else 0
        if pcs > 0.5 or pcoh_given_set > 0.5:
            line += f" {cn}={both}/{cohort_size}({pcs*100:.0f}%) "
    print(line)
