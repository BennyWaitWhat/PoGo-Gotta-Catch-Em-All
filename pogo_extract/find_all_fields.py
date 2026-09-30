"""
Find offsets for ALL remaining fields by matching known PoGO counts:
- 374 hatched (hatchedFromEgg_)
- 284 event/costume
- 232 current best buddy
- 89 special background
- 19 adventure effect
- 14 location background
- buddyKmWalked_ (float)
- numUpgrades_ (int)
- battlesAttacked_, battlesDefended_ (int)
"""
import json, struct
from collections import Counter, defaultdict

data = json.load(open('pokemon_v3.json'))
print(f"Loaded {len(data)} pokemon")

TARGETS = [
    ('hatched', 374, 30),
    ('event', 284, 20),
    ('current_best_buddy', 232, 30),
    ('special_bg', 89, 15),
    ('gigantamax_capable', 84, 10),
    ('shadow', 229, 10),  # already known: alignment+1=SHADOW at +36, but might be cross-check
    ('mega_capable', 282, 30),
    ('dynamax', 224, 25),
    ('purified', 63, 10),
    ('adventure_effect', 19, 5),
    ('location_bg', 14, 4),
]

def search_byte_value(target, tol, val, source='proto'):
    """Find byte offsets where exactly `val` appears `target±tol` times."""
    found = []
    for off in range(0, 600 if source == 'proto' else 200):
        cnt = 0
        for p in data:
            raw = p.get('raw_proto' if source == 'proto' else 'display_raw') or ''
            if len(raw) < 100: continue
            bs = bytes.fromhex(raw)
            if off < len(bs) and bs[off] == val:
                cnt += 1
        if target - tol <= cnt <= target + tol:
            found.append((off, cnt))
    return found

def search_int32(target, tol, val=None, source='proto'):
    """Find int32 offsets where value matches target count."""
    found = []
    rng = range(0, 600 if source == 'proto' else 200, 4)
    for off in rng:
        if val is not None:
            cnt = 0
            for p in data:
                raw = p.get('raw_proto' if source == 'proto' else 'display_raw') or ''
                if len(raw) < 100: continue
                bs = bytes.fromhex(raw)
                if off + 4 > len(bs): continue
                v = struct.unpack_from('<i', bs, off)[0]
                if v == val: cnt += 1
            if target - tol <= cnt <= target + tol:
                found.append((off, cnt))
        else:
            # Find offsets with NONZERO count near target
            cnt = 0
            for p in data:
                raw = p.get('raw_proto' if source == 'proto' else 'display_raw') or ''
                if len(raw) < 100: continue
                bs = bytes.fromhex(raw)
                if off + 4 > len(bs): continue
                v = struct.unpack_from('<i', bs, off)[0]
                if v != 0: cnt += 1
            if target - tol <= cnt <= target + tol:
                found.append((off, cnt))
    return found

print("\n=== Bool fields in PROTO (byte=1) ===")
for label, tgt, tol in TARGETS:
    matches = search_byte_value(tgt, tol, 1, 'proto')
    if matches:
        print(f"  [{label}={tgt}±{tol}]:")
        for off, cnt in matches[:5]:
            print(f"    PROTO byte +{off} == 1: {cnt}")

print("\n=== Bool fields in DISPLAY (byte=1) ===")
for label, tgt, tol in TARGETS:
    matches = search_byte_value(tgt, tol, 1, 'display')
    if matches:
        print(f"  [{label}={tgt}±{tol}]:")
        for off, cnt in matches[:3]:
            print(f"    DISPLAY byte +{off} == 1: {cnt}")

print("\n=== Int32=1 in PROTO ===")
for label, tgt, tol in TARGETS:
    matches = search_int32(tgt, tol, 1, 'proto')
    if matches:
        print(f"  [{label}={tgt}±{tol}]:")
        for off, cnt in matches[:3]:
            print(f"    PROTO int32 +{off} == 1: {cnt}")

print("\n=== Int32 NONZERO in PROTO (after offset 280) ===")
for label, tgt, tol in TARGETS:
    matches = []
    for off in range(280, 600, 4):
        cnt = 0
        for p in data:
            raw = p.get('raw_proto', '')
            if len(raw) < 600: continue
            bs = bytes.fromhex(raw)
            if off + 4 > len(bs): continue
            v = struct.unpack_from('<i', bs, off)[0]
            if v != 0: cnt += 1
        if tgt - tol <= cnt <= tgt + tol:
            matches.append((off, cnt))
    if matches:
        print(f"  [{label}={tgt}±{tol}]:")
        for off, cnt in matches[:3]:
            print(f"    PROTO int32 NONZERO +{off}: {cnt}")

# Also look for floats (buddy km walked - varies 0-thousands)
print("\n=== FLOAT fields with positive values (potential buddyKmWalked) ===")
float_offsets = defaultdict(int)
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue
    bs = bytes.fromhex(raw)
    for off in range(0, min(508, len(bs)), 4):
        if off in [104, 108, 124, 172, 348, 352, 376, 384]: continue  # known floats
        v = struct.unpack_from('<f', bs, off)[0]
        if 0.001 < v < 50000 and v == v:
            float_offsets[off] += 1

print("Float offsets with 30-1000 set values:")
for off, cnt in sorted(float_offsets.items()):
    if 30 < cnt < 1000:
        # Sample
        samples = []
        for p in data:
            raw = p.get('raw_proto', '')
            if len(raw) < 600: continue
            bs = bytes.fromhex(raw)
            if off + 4 > len(bs): continue
            v = struct.unpack_from('<f', bs, off)[0]
            if 0.001 < v < 50000 and v == v:
                samples.append(round(v, 3))
                if len(samples) >= 5: break
        print(f"  +{off}: {cnt} pokemon. Samples: {samples}")
