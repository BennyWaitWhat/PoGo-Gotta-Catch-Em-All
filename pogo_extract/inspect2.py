"""Inspect a fresh pokemon to map ALL fields including location/origin/fort."""
import subprocess, struct, json, sys

ADB = ['adb', '-s', '100.98.158.56:5555']

def adb_bin(cmd, timeout=30):
    return subprocess.run(ADB + ['exec-out', f'su -c "{cmd}"'], capture_output=True, timeout=timeout).stdout

def adb_text(cmd):
    return subprocess.run(ADB + ['shell', f'su -c "{cmd}"'], capture_output=True, text=True, timeout=15).stdout

pid = int(adb_text("pidof com.nianticlabs.pokemongo").strip().split()[0])
print(f"PID: {pid}")

# Find a CURRENT pokemon by re-scanning a small region
# Use the addr from our last full dump - they may still be valid
data = json.load(open('pokemon_full.json'))

# Find one that's interesting - has nickname, deployedFort, or non-default form
for p in data:
    if p.get('deployedFortId'):
        target = p
        print(f"Found deployed pokemon: species #{p['pokemonId']} CP {p['cp']} addr {p['addr']}")
        break

if 'target' not in dir():
    target = data[0]

# Read fresh data from the address
addr = int(target['addr'], 16)
page = (addr // 4096) * 4096
in_page = addr - page

# Read 3 pages (12KB) to capture object + nearby
buf = adb_bin(f"dd if=/proc/{pid}/mem bs=4096 skip={page // 4096} count=3 2>/dev/null", timeout=30)
print(f"Read {len(buf)} bytes")

if len(buf) < in_page + 400:
    print("Not enough data, address may be stale - trying recent pokemon")
    sys.exit(1)

obj = buf[in_page:in_page + 400]
print(f"\n=== Object at {hex(addr)} ===")

# Print all int32 and int64 and pointers and floats
for i in range(0, 400, 4):
    if i + 4 > len(obj): break
    v32 = struct.unpack_from('<i', obj, i)[0]
    f32 = struct.unpack_from('<f', obj, i)[0]
    note = []
    if v32 != 0:
        note.append(f'int={v32}')
    if 0.001 < abs(f32) < 1000000 and not (f32 != f32):
        note.append(f'f={f32:.4f}')
    # Check if 8 bytes here form a pointer
    if i % 8 == 0 and i + 8 <= len(obj):
        v64 = struct.unpack_from('<Q', obj, i)[0]
        if 0x70_00000000 < v64 < 0x90_00000000:
            note.append(f'PTR=0x{v64:x}')
        elif 0x4000000000000000 < v64 < 0xC000000000000000:
            note.append(f'CELLID=0x{v64:x}')
        elif 0 < v64 < 1e12 and i in [160, 168, 176]:
            note.append(f'large_int={v64}')
    if note:
        print(f'  +{i:03x}({i:3d}): {" | ".join(note)}')
