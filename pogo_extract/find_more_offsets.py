"""
Find offsets for tradedTimeMs, buddyKmWalked, numUpgrades, battle stats.
Cross-reference: traded pokemon (71) should have tradedTimeMs set.
"""
import json, struct
from collections import defaultdict, Counter

data = json.load(open('pokemon_v3.json'))

# 1. Find traded pokemon (those with originalOwnerNickname at offset 0x100)
EMPTY_STR_PTR = '0x7b81c1cf40'

def is_traded(p):
    s = (p.get('strings') or {}).get('0x100')
    return isinstance(s, list) and s[1] is not None and s[1] != ''

traded = [p for p in data if is_traded(p)]
not_traded = [p for p in data if not is_traded(p)]
print(f"Traded: {len(traded)}, Not traded: {len(not_traded)}")

# 2. Find offsets where traded pokemon differ from not-traded
# tradedTimeMs (int64) should be 0 for non-traded, non-zero for traded
# Look for int64 offsets with this signature
print("\n=== int64 offsets where traded pokemon have data, others don't ===")
int64_traded_set = defaultdict(int)
int64_other_set = defaultdict(int)
for p in traded:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue
    bs = bytes.fromhex(raw)
    for off in range(0, min(504, len(bs)), 8):
        v = struct.unpack_from('<q', bs, off)[0]
        if v != 0:
            int64_traded_set[off] += 1
for p in not_traded:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue
    bs = bytes.fromhex(raw)
    for off in range(0, min(504, len(bs)), 8):
        v = struct.unpack_from('<q', bs, off)[0]
        if v != 0:
            int64_other_set[off] += 1

# Score: high "set in traded" + low "set in others" = trade-specific field
candidates = []
for off in int64_traded_set:
    in_traded = int64_traded_set[off] / len(traded)
    in_others = int64_other_set.get(off, 0) / len(not_traded)
    if in_traded > 0.3 and in_others < 0.05:
        candidates.append((off, in_traded, in_others, int64_traded_set[off]))
print("Trade-specific int64 offsets (>30% in traded, <5% in non-traded):")
for off, t_pct, o_pct, cnt in sorted(candidates):
    print(f"  +{off}: {cnt}/{len(traded)} traded ({t_pct*100:.0f}%), {int64_other_set.get(off, 0)}/{len(not_traded)} others ({o_pct*100:.1f}%)")
    # Show sample int64 value
    if traded:
        for p in traded[:3]:
            raw = p.get('raw_proto', '')
            if len(raw) >= 600:
                bs = bytes.fromhex(raw)
                if off + 8 <= len(bs):
                    v = struct.unpack_from('<q', bs, off)[0]
                    if v > 0:
                        if 1.4e12 < v < 2e12:
                            from datetime import datetime, timezone
                            dt = datetime.fromtimestamp(v/1000, tz=timezone.utc).isoformat()
                            print(f"    Sample: {v} ({dt}) species #{p['pokemonId']}")
                        else:
                            print(f"    Sample: {v} species #{p['pokemonId']}")
                        break

# 3. Find FLOAT fields - likely buddyKmWalked
print("\n=== Float fields with buddy-walk-like values (positive, 0-2000 km) ===")
float_patterns = defaultdict(int)
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue
    bs = bytes.fromhex(raw)
    for off in range(280, min(508, len(bs)), 4):
        if off + 4 > len(bs): break
        v = struct.unpack_from('<f', bs, off)[0]
        if 0.001 < v < 50000 and v == v:  # finite positive
            float_patterns[off] += 1

for off in sorted(float_patterns.keys()):
    cnt = float_patterns[off]
    if 30 < cnt < 5000:
        # Sample some values
        samples = []
        for p in data[:5000]:
            raw = p.get('raw_proto', '')
            if len(raw) >= 600:
                bs = bytes.fromhex(raw)
                if off + 4 <= len(bs):
                    v = struct.unpack_from('<f', bs, off)[0]
                    if 0.001 < v < 50000 and v == v:
                        samples.append(v)
                        if len(samples) >= 5: break
        print(f"  +{off}: {cnt} pokemon. Samples: {samples}")

# 4. Find INT32 fields likely numUpgrades, battlesAttacked, battlesDefended
print("\n=== Int32 fields after offset 280 ===")
int32_dist = defaultdict(Counter)
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue
    bs = bytes.fromhex(raw)
    for off in range(280, min(508, len(bs)), 4):
        if off + 4 > len(bs): break
        v = struct.unpack_from('<i', bs, off)[0]
        # Look for small positive integers (counts)
        if 0 < v < 1000:
            int32_dist[off][v] += 1

for off in sorted(int32_dist.keys()):
    counter = int32_dist[off]
    total = sum(counter.values())
    if 50 < total < 5000:
        top = counter.most_common(5)
        print(f"  +{off}: {total} pokemon. Top values: {top}")
