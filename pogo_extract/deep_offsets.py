"""Deep dive on specific offsets: +192, +224, +268, +280, +296, +336, +340, +344, +348, +352, +416, +420, +432."""
import json, struct
from collections import Counter
from datetime import datetime, timezone

data = json.load(open('pokemon_v3.json'))
all_bytes = [bytes.fromhex(p['raw_proto']) for p in data if len(p.get('raw_proto', '')) >= 1024]
all_p = [p for p in data if len(p.get('raw_proto', '')) >= 1024]
N = len(all_bytes)

def show(off, label, kind='i32', bytes_list=all_bytes):
    print(f"\n=== +{off} ({label}, {kind}) ===")
    counter = Counter()
    raw_vals = []
    for bs in bytes_list:
        if off + 8 > len(bs): continue
        if kind == 'i32':
            v = struct.unpack_from('<i', bs, off)[0]
        elif kind == 'u32':
            v = struct.unpack_from('<I', bs, off)[0]
        elif kind == 'f32':
            v = struct.unpack_from('<f', bs, off)[0]
            if v != v: continue  # NaN
            v = round(v, 4)
        elif kind == 'i64':
            v = struct.unpack_from('<q', bs, off)[0]
        elif kind == 'u64':
            v = struct.unpack_from('<Q', bs, off)[0]
        elif kind == 'bool':
            v = bs[off]
        if v != 0:
            counter[v] += 1
            raw_vals.append(v)
    print(f'  Total non-zero: {len(raw_vals)}, distinct: {len(counter)}')
    print(f'  Top 10: {counter.most_common(10)}')
    if raw_vals:
        print(f'  Min: {min(raw_vals)}, Max: {max(raw_vals)}')
        # If float-like
        if kind == 'f32':
            sorted_vals = sorted(raw_vals)
            print(f'  Range distribution: 5%={sorted_vals[len(sorted_vals)//20]}, 50%={sorted_vals[len(sorted_vals)//2]}, 95%={sorted_vals[-len(sorted_vals)//20]}')

# +192: covers hatched (378 = exactly) but set=558
show(192, "hatched-related?", 'i32')
show(192, "as f32?", 'f32')
show(192, "as bool", 'bool')

# +224: 378 set, top value 256
show(224, "hatched marker?", 'i32')
show(224, "as f32", 'f32')
show(224, "as bool byte", 'bool')

# +268: covers traded
show(268, "traded reference?", 'i32')

# +280: 273 set
show(280, "best buddy related?", 'i32')

# +432: 1416 set, looks like float
show(432, "big cohort", 'i32')
show(432, "as f32", 'f32')

# +336 and +344, +348, +352 (154 each) - check best_buddy
show(336, "?", 'i32')
show(340, "?", 'i32')
show(344, "?", 'i32')
show(344, "?", 'f32')
show(348, "?", 'f32')
show(352, "?", 'f32')

# +416, 420 - float?
show(416, "?", 'f32')
show(420, "?", 'f32')

# +488 (698 set)
show(488, "?", 'i32')
show(488, "?", 'f32')

# +144 (304 set, 1-4003 range) - upgrades?
show(144, "numUpgrades?", 'i32')
