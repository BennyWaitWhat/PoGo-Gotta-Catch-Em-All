"""Read klass names: read +0x10 (name_ptr) and +0x18 (namespace_ptr) and dereference."""
import subprocess

KLASSES = [
    0x74f02486a0,  # claimed: System.String
    0x74f0246f60,  # sibling klass found at +0x20 of suspect bindings
    0x74f0247b40,  # UInt64 (real)
    0x74f3d35d40,
    0x74f3d35de0,
    0x74f3d35e40,
    0x74f0257ae0,
]

def adb_read(addr, n):
    """Read n bytes at addr from PID 12581 mem via /proc/PID/mem."""
    page_addr = addr & ~0xfff
    offset_in_page = addr - page_addr
    end_addr = addr + n
    end_page = ((end_addr - 1) | 0xfff) + 1
    pages = (end_page - page_addr) // 0x1000
    cmd = [
        'adb', '-s', '100.98.158.56:5555', 'shell',
        f"su -c 'dd if=/proc/12581/mem bs=4096 skip={page_addr // 0x1000} count={pages} status=none 2>/dev/null | base64'"
    ]
    import os
    env = os.environ.copy()
    env['MSYS_NO_PATHCONV'] = '1'
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
    import base64
    out = r.stdout.replace('\n', '').replace('\r', '')
    raw = base64.b64decode(out)
    return raw[offset_in_page:offset_in_page + n]

for k in KLASSES:
    print(f'\n=== klass 0x{k:x} ===')
    klass_data = adb_read(k, 0x40)
    if not klass_data:
        print('  could not read')
        continue
    # +0x00: image, +0x08: gc_desc, +0x10: name, +0x18: namespace
    import struct
    ptrs = struct.unpack('<8Q', klass_data[:0x40])
    name_ptr = ptrs[2]
    ns_ptr = ptrs[3]
    print(f'  name_ptr=0x{name_ptr:x}, ns_ptr=0x{ns_ptr:x}')
    if name_ptr:
        try:
            name_data = adb_read(name_ptr, 128)
            null = name_data.find(b'\x00')
            name = name_data[:null if null >= 0 else 64].decode('utf-8', errors='replace')
            print(f'  name: {name!r}')
        except Exception as e:
            print(f'  name read err: {e}')
    if ns_ptr:
        try:
            ns_data = adb_read(ns_ptr, 128)
            null = ns_data.find(b'\x00')
            ns = ns_data[:null if null >= 0 else 64].decode('utf-8', errors='replace')
            print(f'  ns: {ns!r}')
        except Exception as e:
            print(f'  ns read err: {e}')
