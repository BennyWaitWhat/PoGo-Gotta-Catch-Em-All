"""Comprehensive offset analysis on pokemon_v3.json - find candidate fields."""
import json, struct, math
from collections import Counter, defaultdict

POGO_LAUNCH_MS = 1467590400000  # 2016-07-06
NOW_MS = 1746662400000  # ~2025

KNOWN = {32, 36, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128, 132,
         136, 140, 144, 160, 164, 168, 172, 224, 248, 252, 264, 268, 272, 276,
         440, 480, 496}
# also string pointers at: 0x40=64, 0xb8=184, 0x100=256, 0x130=304, 0x168=360, 0x180=384

print('Loading pokemon_v3.json...')
data = json.load(open('pokemon_v3.json'))
print(f'Loaded {len(data)} pokemon')

# Build raw_proto bytes list
protos = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 1000: continue  # 512 bytes hex = 1024 chars
    protos.append(bytes.fromhex(raw))
print(f'Valid protos: {len(protos)}')

PROTO_LEN = 512

# For each 4-byte offset, gather stats
print('\n=== Per-offset 4-byte analysis ===')
print('off |  nzcnt | distinct |       min      max | floats? | tstamp? | sample')

results = []
for off in range(0, PROTO_LEN, 4):
    int_vals = []
    float_vals = []
    nz = 0
    distinct = set()
    for bs in protos:
        if off + 4 > len(bs): continue
        i = struct.unpack_from('<i', bs, off)[0]
        f = struct.unpack_from('<f', bs, off)[0]
        int_vals.append(i)
        float_vals.append(f)
        if i != 0: nz += 1
        distinct.add(i)
    if nz == 0: continue

    nzint = [v for v in int_vals if v != 0]
    minv, maxv = min(nzint), max(nzint)

    # Float plausibility: all non-zero values look like reasonable floats?
    nzfloat = [f for i, f in zip(int_vals, float_vals) if i != 0]
    plausible_float = 0
    for f in nzfloat:
        if math.isnan(f) or math.isinf(f): continue
        if 0.001 <= abs(f) <= 1e6:
            plausible_float += 1
    float_pct = plausible_float / len(nzfloat) if nzfloat else 0

    # Timestamp plausibility: int64 at this offset OR int32 millis since launch?
    # Also check int64 at this offset

    samples = sorted(distinct - {0})[:5]
    floats_sample = sorted([round(f, 3) for f in set(float_vals) if f != 0 and not math.isnan(f) and not math.isinf(f)])[:5]

    results.append({
        'off': off,
        'nz': nz,
        'distinct': len(distinct),
        'min': minv,
        'max': maxv,
        'float_pct': float_pct,
        'samples': samples,
        'floats': floats_sample,
    })

    flag = '*' if off in KNOWN else ' '
    print(f'{flag}{off:3d} | {nz:6d} | {len(distinct):8d} | {minv:10d} {maxv:10d} | {float_pct*100:5.1f}% | {samples[:3]} | floats: {floats_sample[:3]}')

# Now i64 offsets
print('\n=== Per-offset 8-byte (int64) analysis ===')
i64_results = []
for off in range(0, PROTO_LEN, 4):
    if off + 8 > PROTO_LEN: break
    i64_vals = []
    nz = 0
    distinct = set()
    for bs in protos:
        if off + 8 > len(bs): continue
        v = struct.unpack_from('<q', bs, off)[0]
        i64_vals.append(v)
        if v != 0: nz += 1
        distinct.add(v)
    if nz == 0: continue

    nzv = [v for v in i64_vals if v != 0]
    minv, maxv = min(nzv), max(nzv)

    # Timestamp candidates
    ts_count = sum(1 for v in nzv if POGO_LAUNCH_MS <= v <= NOW_MS)

    samples = sorted(distinct - {0})[:3]

    if ts_count > 5 or len(distinct) > 10:
        flag = '*' if off in KNOWN else ' '
        print(f'{flag}+{off:3d} | nz={nz:5d} | distinct={len(distinct):6d} | ts_match={ts_count:5d} | min/max={minv}/{maxv}')
        if ts_count > 5:
            print(f'        samples: {samples}')

# String offsets
print('\n=== String pointer scanner: any offset that holds 0x70..-aligned ptr ===')
# String pointers are 8-byte aligned and look like 0x7xxxxxxxxx
ptr_offset_counts = defaultdict(int)
for bs in protos:
    for off in range(0, len(bs), 8):
        if off + 8 > len(bs): break
        v = struct.unpack_from('<Q', bs, off)[0]
        # Heuristic: pointer in lib region (top byte 0x7b or 0x7c or 0x7d or 0x7e or 0x7f)
        if 0x700000000000 <= v <= 0x800000000000:
            ptr_offset_counts[off] += 1
print('Offsets where pointer-like values appear most often:')
for off, cnt in sorted(ptr_offset_counts.items()):
    if cnt > 100:
        print(f'  +{off}: {cnt} pointer-like values')
