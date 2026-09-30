"""Examine 0x7943a09f40 directly."""
import gzip, struct

BASE = 0x7943a05000
TARGET = 0x7943a09f40

with gzip.open('pogo_extra_7943a05000.bin.gz', 'rb') as f:
    data = f.read()
print(f'File size: {len(data)} bytes (region 0x{BASE:x}-0x{BASE+len(data):x})')

off = TARGET - BASE
print(f'Target offset in file: 0x{off:x}')
if off + 0x100 > len(data):
    print('OUT OF RANGE')
else:
    print(f'\n=== 0x100 bytes at 0x{TARGET:x} ===')
    for i in range(0, 0x200, 16):
        if off + i + 16 > len(data): break
        chunk = data[off+i:off+i+16]
        hexstr = ' '.join(f'{b:02x}' for b in chunk)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        ptr_hex = struct.unpack_from('<Q', data, off + i)[0] if i+8 <= 0x200 else 0
        print(f'  +{i:03x}: {hexstr}  |{asc}|')

# Also show 0x100 BEFORE
print(f'\n=== 0x100 bytes BEFORE 0x{TARGET:x} ===')
for i in range(-0x100, 0, 16):
    if off + i < 0: continue
    chunk = data[off+i:off+i+16]
    hexstr = ' '.join(f'{b:02x}' for b in chunk)
    asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
    print(f'  -0x{-i:03x}: {hexstr}  |{asc}|')

# Decode pointer at 0x7943a09f40 + several offsets
print(f'\n=== Pointer scan at 0x{TARGET:x} ===')
for delta in range(0, 0x80, 8):
    p = struct.unpack_from('<Q', data, off + delta)[0]
    print(f'  +{delta:02x}: 0x{p:016x}')
