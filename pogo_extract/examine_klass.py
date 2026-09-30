"""Look at the klass struct at 0x74f0247b40 - the Mono klass struct has the class name pointer at +0x10 typically."""
import gzip, struct

BASE = 0x74f0247000
TARGET = 0x74f0247b40
OFFSET = TARGET - BASE  # 0xb40

# Mono Il2CppClass structure (rough, abbreviated):
# +0x00 image_ptr
# +0x08 gc_desc
# +0x10 name_ptr (utf8 string)
# +0x18 namespace_ptr (utf8 string)
# +0x20 byval_arg
# +0x28 this_arg
# +0x30 element_class_ptr
# +0x38 cast_class_ptr
# ...

with gzip.open('klass_region.bin.gz', 'rb') as f:
    data = f.read()
print(f'Size: {len(data)}')

if OFFSET + 0x100 > len(data):
    print('Out of range')
else:
    print(f'\n=== klass at 0x{TARGET:x} ===')
    for i in range(0, 0x100, 16):
        chunk = data[OFFSET+i:OFFSET+i+16]
        hexstr = ' '.join(f'{b:02x}' for b in chunk)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f'  +{i:03x}: {hexstr}  |{asc}|')

    # Print pointers
    print('\nPointer interpretations:')
    for off in range(0, 0x100, 8):
        if OFFSET + off + 8 > len(data): break
        p = struct.unpack_from('<Q', data, OFFSET + off)[0]
        print(f'  +0x{off:02x}: 0x{p:x}')
