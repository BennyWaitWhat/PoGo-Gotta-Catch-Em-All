"""Find remaining fields: location_bg=14, current_buddy=232, mega/dynamax/gmax."""
import json, struct
from collections import Counter

data = json.load(open('pokemon_v3.json'))

def search(target, tol, source='proto'):
    """Search for offsets where any value occurs target±tol times."""
    found = []
    rng = range(0, 600 if source == 'proto' else 200)
    for off in rng:
        # bytes
        cnt_byte_1 = 0
        for p in data:
            raw = p.get('raw_proto' if source == 'proto' else 'display_raw') or ''
            if len(raw) < 100: continue
            bs = bytes.fromhex(raw)
            if off < len(bs) and bs[off] == 1:
                cnt_byte_1 += 1
        if target - tol <= cnt_byte_1 <= target + tol:
            found.append((source, off, 'byte=1', cnt_byte_1))
    return found

# Targets
for label, tgt, tol in [('location_bg', 14, 3), ('current_buddy', 232, 5), ('gigantamax', 84, 5), ('mega_capable_active', 282, 8)]:
    print(f'\n=== {label}={tgt}±{tol} ===')
    f = search(tgt, tol, 'proto') + search(tgt, tol, 'display')
    for src, off, typ, cnt in f[:5]:
        print(f'  {src} +{off} {typ}: {cnt}')

# Also int32 nonzero search across whole proto
print('\n=== Int32 NONZERO matching targets ===')
for off in range(0, 508, 4):
    cnt = 0
    for p in data:
        raw = p.get('raw_proto', '')
        if len(raw) < 600: continue
        bs = bytes.fromhex(raw)
        if off + 4 > len(bs): continue
        v = struct.unpack_from('<i', bs, off)[0]
        if v != 0: cnt += 1
    for label, tgt, tol in [('location_bg', 14, 3), ('current_buddy', 232, 5), ('gigantamax', 84, 5), ('mega_active', 282, 8)]:
        if tgt - tol <= cnt <= tgt + tol:
            samples = []
            for p in data:
                raw = p.get('raw_proto', '')
                if len(raw) < 600: continue
                bs = bytes.fromhex(raw)
                if off + 4 > len(bs): continue
                v = struct.unpack_from('<i', bs, off)[0]
                if v != 0: samples.append(v)
                if len(samples) >= 3: break
            print(f'  +{off} ({label}={tgt}): {cnt}, samples: {samples}')

# Search display int32 nonzero
print('\n=== Display int32 NONZERO matching targets ===')
for off in range(0, 200, 4):
    cnt = 0
    for p in data:
        raw = p.get('display_raw') or ''
        if len(raw) < 100: continue
        bs = bytes.fromhex(raw)
        if off + 4 > len(bs): continue
        v = struct.unpack_from('<i', bs, off)[0]
        if v != 0: cnt += 1
    for label, tgt, tol in [('location_bg', 14, 3), ('current_buddy', 232, 5), ('gigantamax', 84, 5), ('mega_active', 282, 8)]:
        if tgt - tol <= cnt <= tgt + tol:
            print(f'  display +{off} ({label}={tgt}): {cnt}')
