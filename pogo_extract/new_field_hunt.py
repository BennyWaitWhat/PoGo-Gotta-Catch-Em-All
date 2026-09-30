"""
Targeted hunt for specific fields:
- buddyKmWalked (float, varies)
- friendship score (initial + added)
- move4 (cinematicMoves[3])
- hasMegaEvolved (bool)
- megaEvolvedForms (list/array)
- pokemonTagIds (list)
- candyToEvolve (int)
- numUpgrades / powerUpStardustPaid
- 0x130 string contents
"""
import json, struct
from collections import Counter, defaultdict

data = json.load(open('pokemon_v3.json'))
print(f"Loaded {len(data)} pokemon")

# Load raw bytes
def get_bs(p):
    raw = p.get('raw_proto', '')
    return bytes.fromhex(raw) if len(raw) >= 600 else None

# All non-zero offsets
print("\n=== All offsets with NONZERO i32 (whole proto, fine pass) ===")
nonzero_counts = defaultdict(int)
distinct_vals = defaultdict(set)
for p in data:
    bs = get_bs(p)
    if not bs: continue
    for off in range(0, min(508, len(bs)), 4):
        v = struct.unpack_from('<i', bs, off)[0]
        if v != 0:
            nonzero_counts[off] += 1
            if len(distinct_vals[off]) < 100:
                distinct_vals[off].add(v)

print(f"Total scanned: {sum(1 for p in data if get_bs(p))}")
print()
for off in sorted(nonzero_counts.keys()):
    cnt = nonzero_counts[off]
    n_distinct = len(distinct_vals[off])
    if cnt > 5:
        # Print summary
        sample = sorted(list(distinct_vals[off]))[:3]
        print(f"  +{off:3d} (0x{off:03x}): nonzero={cnt:5d} distinct~{n_distinct:5d}  sample={sample}")

# Print field categories
print("\n\n=== FIELD CATEGORY HUNT ===")

# 1) Search for buddyKmWalked - float w/ non-trivial values, often <500
print("\n1. buddyKmWalked candidates (floats 0.001-1500, varied):")
candidates = []
for off in range(0, 508, 4):
    cnt = 0
    samples = []
    n_distinct = 0
    seen_vals = set()
    for p in data:
        bs = get_bs(p)
        if not bs or off+4 > len(bs): continue
        v = struct.unpack_from('<f', bs, off)[0]
        if 0.001 < v < 1500 and v == v:
            cnt += 1
            seen_vals.add(round(v, 3))
            if len(samples) < 5:
                samples.append(round(v, 3))
    if 50 < cnt < 5000 and len(seen_vals) > 30:
        candidates.append((off, cnt, len(seen_vals), samples))
for off, cnt, distinct, samples in sorted(candidates):
    if off not in [104, 108, 124, 172, 92]:  # exclude known
        print(f"  +{off:3d}: {cnt} pokemon, ~{distinct} distinct, e.g. {samples}")

# 2) Friendship score - "initialFriendshipScore" (per spec)
# These are int32. Look for offsets with values that look like 0-1000 friendship pts
print("\n2. friendship score candidates (small int 0-1000, set on traded mostly):")
traded_uids = set()
not_traded_uids = set()
for p in data:
    s = (p.get('strings') or {}).get('0x100')
    is_t = isinstance(s, list) and s[1] is not None and s[1] != ''
    if is_t: traded_uids.add(id(p))
    else: not_traded_uids.add(id(p))

for off in range(0, 508, 4):
    in_traded_nonzero = 0
    in_other_nonzero = 0
    samples_t = []
    for p in data:
        bs = get_bs(p)
        if not bs or off+4 > len(bs): continue
        v = struct.unpack_from('<i', bs, off)[0]
        if 0 < v < 5000:
            if id(p) in traded_uids:
                in_traded_nonzero += 1
                if len(samples_t) < 5:
                    samples_t.append(v)
            else:
                in_other_nonzero += 1
    # Friendship is set even on non-traded (initial). Look for small ints
    if in_traded_nonzero > 30 and in_traded_nonzero/71 > 0.3:
        # Skip already known
        if off in [40, 44, 48, 52, 56, 60, 112, 116, 120, 128, 168, 276, 440, 480, 496]:
            continue
        print(f"  +{off:3d}: traded={in_traded_nonzero}/71 ({in_traded_nonzero/71*100:.0f}%), nontraded={in_other_nonzero}/{len(data)-71} ({in_other_nonzero/(len(data)-71)*100:.1f}%)  samples={samples_t}")

# 3) move4? Look at offsets near move1/2/3 (56,60,276)
# move4 = quickMove or maybe an "elite" tracker
print("\n3. move4 / elite move candidates (int near move offsets):")
known_moves = {56, 60, 276}
for off in range(0, 508, 4):
    if off in known_moves: continue
    cnt = 0
    distinct_vals = set()
    samples = []
    for p in data:
        bs = get_bs(p)
        if not bs or off+4 > len(bs): continue
        v = struct.unpack_from('<i', bs, off)[0]
        if 0 < v < 500:  # move IDs are typically 0-400
            cnt += 1
            distinct_vals.add(v)
            if len(samples) < 5: samples.append(v)
    if 5 < cnt < 500 and 5 < len(distinct_vals) < 200:
        # Could be an elite move (rare: ~70-200), tag, or evolution form
        print(f"  +{off:3d}: {cnt} pokemon, {len(distinct_vals)} distinct, e.g. {samples}")

# 4) hasMegaEvolved bool - mega-eligible species only (Charizard, Beedrill, etc)
# Should be only mega evolutions (rare: maybe 10-50)
print("\n4. hasMegaEvolved bool candidates (rare bool, byte=1):")
known_bool_offs = {225, 272}
for off in range(0, 512):
    cnt = 0
    for p in data:
        bs = get_bs(p)
        if not bs or off >= len(bs): continue
        if bs[off] == 1:
            cnt += 1
    if 5 < cnt < 250 and off not in known_bool_offs:
        # Check if it's a true bool (only 0/1)
        all_vals = set()
        for p in data[:500]:
            bs = get_bs(p)
            if not bs or off >= len(bs): continue
            all_vals.add(bs[off])
        if all_vals.issubset({0, 1}):
            print(f"  +{off:3d}: {cnt} pokemon  (pure 0/1 bool)")

# 5) megaEvolvedForms - probably a list/repeated. Could see a count
# Actually could be on the same byte alignment. Look for small ints (1-3)
print("\n5. megaEvolvedForms count candidates (small int 1-5):")
for off in range(0, 508, 4):
    if off in [40, 44, 48, 52, 56, 60, 112, 116, 120, 128, 168, 276, 440, 480, 496]: continue
    cnt = 0
    val_counter = Counter()
    for p in data:
        bs = get_bs(p)
        if not bs or off+4 > len(bs): continue
        v = struct.unpack_from('<i', bs, off)[0]
        if v != 0:
            cnt += 1
            val_counter[v] += 1
    if 5 < cnt < 250:
        top = val_counter.most_common(5)
        # Filter: small distinct values (1-5)
        if all(0 < v[0] < 100 for v in top):
            print(f"  +{off:3d}: {cnt} pokemon, top values: {top}")

# 6) String at offset 0x130 - already known (season strings)
print("\n6. All distinct strings at 0x130:")
strings_130 = []
for p in data:
    s = (p.get('strings') or {}).get('0x130')
    if isinstance(s, list) and s[1]:
        strings_130.append(s[1])
print(f"  Total: {len(strings_130)}")
print(f"  Distinct: {len(set(strings_130))}")
for s in set(strings_130):
    print(f"    '{s}'")

# 7) Pointer offsets - find list pointers (e.g., for pokemonTagIds, megaEvolvedForms, cinematicMoves)
# IL2CPP arrays are typically pointers. Look for 8-byte pointer fields with heap addresses
print("\n7. Likely pointer/list fields (8-byte aligned with heap-like values):")
for off in range(0, 504, 8):
    cnt = 0
    for p in data:
        bs = get_bs(p)
        if not bs or off+8 > len(bs): continue
        v = struct.unpack_from('<Q', bs, off)[0]
        # Heap pointers in PoGo memory are typically 0x70-0x80 prefix high word
        if v != 0 and (v >> 40) >= 0x70 and (v >> 40) <= 0x90:
            cnt += 1
    if 5 < cnt < 5400:
        print(f"  +{off:3d}: {cnt} pokemon have a non-null pointer here")
