"""Dump raw bytes for several pokemon at all 8-byte aligned offsets to identify pointers vs data."""
import json, struct
from collections import defaultdict, Counter

data = json.load(open('pokemon_v3.json'))

# Pick samples: traded, mega-eligible, costume, lucky, normal, hatched
samples = []
def get_str(p, off):
    s = (p.get('strings') or {}).get(off)
    return s[1] if isinstance(s, list) else None

for p in data:
    if get_str(p, '0x100'):  # traded
        samples.append(('traded', p)); break
for p in data:
    if get_str(p, '0x40'):  # deployed
        samples.append(('deployed', p)); break
for p in data:
    if get_str(p, '0x130'):  # has season form string
        samples.append(('seasonform', p)); break
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 600:
        bs = bytes.fromhex(raw)
        if struct.unpack_from('<i', bs, 280)[0] != 0:
            samples.append(('off280', p)); break
# Mega - look for hasMegaEvolved candidate
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 600:
        bs = bytes.fromhex(raw)
        if bs[336] == 1:
            samples.append(('off336', p)); break
# Lucky
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 600:
        bs = bytes.fromhex(raw)
        if bs[272] == 1:
            samples.append(('lucky', p)); break

# Normal hundo candidate
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 600:
        bs = bytes.fromhex(raw)
        ivA = struct.unpack_from('<i', bs, 112)[0]
        ivD = struct.unpack_from('<i', bs, 116)[0]
        ivS = struct.unpack_from('<i', bs, 120)[0]
        if ivA == 15 and ivD == 15 and ivS == 15:
            samples.append(('hundo', p)); break

print("\n\n=== POKEMON HEX DUMPS ===")
for label, p in samples:
    raw = p.get('raw_proto', '')
    if len(raw) < 600: continue
    bs = bytes.fromhex(raw)
    print(f"\n--- {label} (id={p['pokemonId']}, addr={p.get('addr')}) ---")
    print(f"strings: {p.get('strings')}")
    for i in range(0, 512, 16):
        chunk = bs[i:i+16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        # Decode as i32x4 and f32x4
        i32s = struct.unpack_from('<iiii', bs, i)
        f32s = struct.unpack_from('<ffff', bs, i)
        # Format
        f_str = ' '.join(f'{f:.3f}' if abs(f) < 1e6 and abs(f) > 0.001 else '   .   ' for f in f32s)
        print(f'+{i:03d}/0x{i:03x}: {hex_str}  {ascii_str}  ints={i32s}')

# Now - aggregate "bytes that look like pointer high words" to identify pointer fields
# In ARM64 mono heap, pointers are typically 0x70-0x90 range upper bytes
print("\n\n=== POINTER FIELD DETECTION ===")
print("Offsets where bytes 6,7 are commonly 0x7b or 0x80 (heap pointer):")
ptr_offsets = []
for off in range(0, 504, 8):
    cnt_ptrs = 0
    for p in data:
        raw = p.get('raw_proto', '')
        if len(raw) < 1024: continue
        bs = bytes.fromhex(raw)
        if off+8 > len(bs): continue
        # Check upper 16 bits (bytes 6-7 LE)
        b6 = bs[off+6]
        b7 = bs[off+7]
        # Real pointer: high bits are 0x00007a or similar
        if b7 == 0 and b6 in (0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x7f, 0x80, 0x81, 0x82, 0x83):
            cnt_ptrs += 1
    if cnt_ptrs > 5:
        ptr_offsets.append((off, cnt_ptrs))
        print(f"  +{off:3d} (0x{off:03x}): {cnt_ptrs} pokemon have heap pointer")

print("\n\n=== STRING POINTERS ALREADY KNOWN ===")
# String offsets per the data: 0x40, 0xb8, 0x100, 0x130
# Convert to decimal
print(f"  0x40  = 64  (deployed fort)")
print(f"  0xb8  = 184 (nickname)")
print(f"  0x100 = 256 (original_owner)")
print(f"  0x130 = 304 (season form string)")
