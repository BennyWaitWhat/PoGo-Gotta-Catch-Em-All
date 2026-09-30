"""
Comprehensive offset scan - for every 4-byte aligned offset NOT in the known set,
report stats so we can identify candidate fields.
"""
import json, struct, math
from collections import Counter, defaultdict
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000
NOW_MS = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

KNOWN_OFFSETS = {32, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128, 136, 160, 168, 172, 225, 248, 264, 272, 276, 440, 480, 496}
# Also +0xb8(184), +0x100(256), +0x130(304), +0x40(64), +0x168(360), +0x180(384) are 8-byte string ptrs.

KNOWN_STR_PTR_OFFSETS_8B = {64, 184, 256, 304, 360, 384}  # 8-byte each

print("Loading pokemon_v3.json...")
data = json.load(open('pokemon_v3.json'))
print(f"  {len(data)} pokemon\n")

# Pre-decode all proto bytes
all_bytes = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))
print(f"  {len(all_bytes)} pokemon with full 512-byte proto\n")

N = len(all_bytes)

# For each 4-byte offset, gather stats
offset_stats = {}  # offset -> {nonzero_count, distinct_int, min, max, ...}

for off in range(0, 508, 4):
    if off in KNOWN_OFFSETS: continue
    # Skip string-ptr lower halves (since 8-byte ptrs span +0..+4)
    is_in_strptr = any(off == sp or off == sp + 4 for sp in KNOWN_STR_PTR_OFFSETS_8B)

    # Also skip the upper halves of known 8-byte i64 fields
    is_in_known_i64 = any(off == k + 4 for k in {32, 136, 160, 248, 264})

    int_vals = []
    float_vals = []
    nonzero_int = 0
    distinct_int = set()
    int_min, int_max = None, None

    for bs in all_bytes:
        if off + 4 > len(bs):
            continue
        iv = struct.unpack_from('<i', bs, off)[0]
        fv = struct.unpack_from('<f', bs, off)[0]
        int_vals.append(iv)
        float_vals.append(fv)
        if iv != 0:
            nonzero_int += 1
            distinct_int.add(iv)
            if int_min is None or iv < int_min: int_min = iv
            if int_max is None or iv > int_max: int_max = iv

    # Float-likeness: count of finite, positive in 0..50000 range
    float_finite_pos = sum(1 for v in float_vals if v == v and 0.001 < v < 50000 and not math.isinf(v))

    # Timestamp-likeness: as a 4-byte field this would be a UNIX seconds. Try millis interpretations.
    # int64 read from this 8-byte position
    ts_count = 0
    ts_samples = []
    for bs in all_bytes:
        if off + 8 > len(bs): continue
        v = struct.unpack_from('<q', bs, off)[0]
        if POGO_LAUNCH_MS < v < NOW_MS + 86400000:
            ts_count += 1
            if len(ts_samples) < 3:
                ts_samples.append(v)

    # Sample int values (most common)
    int_counter = Counter(v for v in int_vals if v != 0)
    top_int = int_counter.most_common(5)

    # Sample float values
    float_samples = []
    for v in float_vals:
        if v == v and 0.001 < v < 50000:
            float_samples.append(v)
            if len(float_samples) >= 5: break

    offset_stats[off] = {
        'is_strptr_overlap': is_in_strptr,
        'is_known_i64_upper': is_in_known_i64,
        'nonzero_int': nonzero_int,
        'distinct_int': len(distinct_int),
        'int_min': int_min,
        'int_max': int_max,
        'top_int': top_int,
        'float_finite_pos': float_finite_pos,
        'float_samples': float_samples[:5],
        'ts_count': ts_count,
        'ts_samples': ts_samples[:3],
    }

# Output
print("=== OFFSET STATS (excluding known) ===\n")
print(f"{'Offset':>6} {'NZ':>5} {'Dist':>5} {'IntMin':>12} {'IntMax':>12}  {'FloatPos':>8} {'TS':>5}  Top values")
for off, s in sorted(offset_stats.items()):
    if s['is_strptr_overlap'] or s['is_known_i64_upper']:
        flag = '*PTR*' if s['is_strptr_overlap'] else '*I64u*'
    else:
        flag = ''
    if s['nonzero_int'] == 0 and s['float_finite_pos'] == 0:
        # all zero, skip detail
        print(f"{off:>6} {s['nonzero_int']:>5} {s['distinct_int']:>5} {'-':>12} {'-':>12}  {'-':>8} {'-':>5}  ALL_ZERO {flag}")
        continue
    top_str = ' '.join(f'{v}={c}' for v, c in s['top_int'][:3])
    print(f"{off:>6} {s['nonzero_int']:>5} {s['distinct_int']:>5} {str(s['int_min']):>12} {str(s['int_max']):>12}  {s['float_finite_pos']:>8} {s['ts_count']:>5}  {top_str} {flag}")
    if s['float_samples'] and s['float_finite_pos'] > 30:
        print(f"        Float samples: {[round(v,3) for v in s['float_samples']]}")
    if s['ts_samples']:
        for ts in s['ts_samples']:
            try:
                dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat()
                print(f"        TS sample (i64 from this off): {ts} ({dt})")
            except: pass
