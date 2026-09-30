"""
For each 8-byte slot that holds a heap pointer (upper4 in {114-123}),
count how many pokemon have NON-empty pointers there (i.e., actual data).
These are unmapped object/list/string pointers.
"""
import json, struct
from collections import Counter

KNOWN_STR_PTRS = {64, 184, 256, 304, 360, 384}
KNOWN_I64 = {32, 136, 160, 248, 264}
EMPTY_LO = -2118004928  # 0x81c1cf40

data = json.load(open('pokemon_v3.json'))
all_bytes = [bytes.fromhex(p['raw_proto']) for p in data if len(p.get('raw_proto', '')) >= 1024]
N = len(all_bytes)

# Also note the displayPtr at offset 216 is the PokemonDisplay pointer (already known)
KNOWN_OBJ_PTRS = {216}

print(f"Cohort sizes: {N} total pokemon")
print(f"For 8-byte aligned slots NOT in known set, look for heap-pointer pattern.\n")

print("=== Heap-pointer slots (upper4 = heap signature) ===")
print(f"{'Off':>5} {'Heap':>5} {'NonEmpty':>9} {'Empty':>6} {'Null':>6}  Notes")

for off in range(0, 504, 8):
    if off in KNOWN_STR_PTRS or off in KNOWN_I64 or off in KNOWN_OBJ_PTRS:
        continue
    n_heap = 0
    n_nonempty = 0
    n_empty = 0
    n_null = 0
    for bs in all_bytes:
        if off + 8 > len(bs): continue
        lo = struct.unpack_from('<i', bs, off)[0]
        hi = struct.unpack_from('<i', bs, off+4)[0]
        ptr = struct.unpack_from('<Q', bs, off)[0]
        if ptr == 0:
            n_null += 1
        elif 110 <= hi <= 130:
            n_heap += 1
            if lo == EMPTY_LO and hi == 123:
                n_empty += 1
            else:
                n_nonempty += 1
    if n_heap < 30:
        continue
    note = ''
    if n_empty > 100:
        note = f'STRING SLOT ({n_empty} empty + {n_nonempty} content)'
    elif n_nonempty > 100:
        note = f'OBJECT SLOT ({n_nonempty} have non-null content)'
    print(f"{off:>5} {n_heap:>5} {n_nonempty:>9} {n_empty:>6} {n_null:>6}  {note}")
