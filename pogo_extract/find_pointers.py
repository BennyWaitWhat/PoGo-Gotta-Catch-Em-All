"""
Find heap pointers we haven't decoded.
A C# heap pointer on this device is in range 0x70_00000000 to 0x90_00000000.
That means low 4 bytes show big negative-or-large positive int32, high 4 bytes show small int (114/115/116/117/118/119/123).

Look for pairs of 8-byte aligned slots whose upper 4 bytes are in {114-123} (heap top byte).
"""
import json, struct
from collections import Counter, defaultdict
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000

KNOWN_STR_PTRS = {64, 184, 256, 304, 360, 384}  # 8-byte each
# Known i64s (timestamps, hashes): 32, 136, 160, 248, 264

data = json.load(open('pokemon_v3.json'))
all_bytes = [bytes.fromhex(p['raw_proto']) for p in data if len(p.get('raw_proto', '')) >= 1024]
N = len(all_bytes)
print(f"{N} pokemon\n")

print("=== Heap-pointer-like slots (upper4 in {114-123}, 8-byte aligned) ===")
print(f"{'Off':>5} {'Cnt':>5} {'DistL':>6} {'TopUpper4':<30}")
for off in range(0, 504, 8):
    if off in KNOWN_STR_PTRS: continue
    if off in {32, 136, 160, 248, 264}: continue  # known i64

    cnt = 0
    upper_counter = Counter()
    distinct_low = set()
    for bs in all_bytes:
        if off + 8 > len(bs): continue
        lo = struct.unpack_from('<i', bs, off)[0]
        hi = struct.unpack_from('<i', bs, off+4)[0]
        if 110 <= hi <= 130:
            cnt += 1
            upper_counter[hi] += 1
            distinct_low.add(lo)
    if cnt > 50:
        print(f"{off:>5} {cnt:>5} {len(distinct_low):>6} {dict(upper_counter.most_common(3))}")

print("\n=== Slots that look like nullable pointers (mostly empty-string sentinel -2118004928 / 0x81C1CF40) ===")
EMPTY_LO = -2118004928  # 0x81c1cf40 as signed
for off in range(0, 504, 8):
    if off in KNOWN_STR_PTRS: continue
    cnt_empty = 0
    for bs in all_bytes:
        if off + 8 > len(bs): continue
        lo = struct.unpack_from('<i', bs, off)[0]
        hi = struct.unpack_from('<i', bs, off+4)[0]
        if lo == EMPTY_LO and hi == 123:  # 0x7B 0x81C1CF40
            cnt_empty += 1
    if cnt_empty > 100:
        # this offset has the empty sentinel, so it's an unmapped string pointer slot
        print(f"  +{off}: {cnt_empty} pokemon have System.String.Empty here (UNMAPPED STRING)")
