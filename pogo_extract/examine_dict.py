"""Look at the FULL 256KB region containing 0x7943a09f40 - find the Dictionary entries array."""
import gzip, struct, sqlite3, json

BASE = 0x7943a05000
TARGET = 0x7943a09f40

# Load known UIDs
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
c.execute('SELECT uid, pokemon_id, species_name, cp FROM pokemon')
UID_MAP = {uid: (pid, sp, cp) for uid, pid, sp, cp in c.fetchall()}

with open('tag_definitions.json') as f:
    TAG_DEFS = json.load(f)

with gzip.open('pogo_extra_7943a05000.bin.gz', 'rb') as f:
    data = f.read()

print(f'File size: {len(data)} bytes (region 0x{BASE:x}-0x{BASE+len(data):x})')

# Look for klass 0x74f0247b40 - real bindings
KLASS = 0x74f0247b40
KLASS_BYTES = struct.pack('<Q', KLASS)
MARKER = 0x3f0473ee

# Find all bindings in this region
hits = []
pos = 0
while True:
    idx = data.find(KLASS_BYTES, pos)
    if idx < 0: break
    if idx + 0x40 <= len(data):
        marker = struct.unpack_from('<I', data, idx + 0x1c)[0]
        if marker == MARKER:
            uid = struct.unpack_from('<q', data, idx + 0x10)[0]
            tag_id = struct.unpack_from('<i', data, idx + 0x18)[0]
            hits.append((BASE + idx, uid, tag_id))
    pos = idx + 1

print(f'\nReal PokemonTagBinding objects in this region: {len(hits)}')
for addr, uid, tid in hits:
    sp = UID_MAP.get(uid, ('?', '?', '?'))[1]
    tag_name = TAG_DEFS.get(str(tid), {'name': '?'})['name']
    print(f'  0x{addr:x}: uid={uid:016x} ({sp}) tag={tid} ({tag_name})')

# Find KLASS occurrences (without marker filter)
all_klass = []
pos = 0
while True:
    idx = data.find(KLASS_BYTES, pos)
    if idx < 0: break
    all_klass.append(idx)
    pos = idx + 1
print(f'\nAll PokemonTagBinding klass-ptr appearances in this region: {len(all_klass)}')

# Look at strings in the region (klass 0x74f02486a0 = System.String)
STR_KLASS = 0x74f02486a0
SBYTES = struct.pack('<Q', STR_KLASS)
str_locs = []
pos = 0
while True:
    idx = data.find(SBYTES, pos)
    if idx < 0: break
    str_locs.append(idx)
    pos = idx + 1
print(f'String objects: {len(str_locs)}')

# Look for arrays - klass pointers right before KLASS_BYTES patterns
# Actually let's find 'Dictionary<long, ...>' related klasses or List<PokemonTagBinding> klass
# A List<T> has klass + monitor + items_array_ptr + size + version
# An Array has klass + monitor + bounds + max_length + ... + elements

# Look for any klass ptr that ends in 0x74XXXXXX (libil2cpp range)
# At every 8-byte aligned offset, dump klass-like pointers
# Particularly: scan for arrays-of-pointers TO our 5 known binding addresses
known_addrs = set([0x737f2c22a0, 0x737f2c24e0, 0x737f2c2960, 0x737f2c2ba0, 0x737f2c2de0])
known_addr_bytes = [struct.pack('<Q', a) for a in known_addrs]
for ka_b, ka in zip(known_addr_bytes, known_addrs):
    pos = 0
    while True:
        idx = data.find(ka_b, pos)
        if idx < 0: break
        addr = BASE + idx
        # Show 0x40 bytes around
        print(f'\n--- Found ptr to 0x{ka:x} at 0x{addr:x} ---')
        s = max(0, idx - 0x20)
        e = min(len(data), idx + 0x40)
        for i in range(s, e, 16):
            chunk = data[i:i+16]
            hexstr = ' '.join(f'{b:02x}' for b in chunk)
            asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            mark = '<<<' if s+(idx-s) <= i < idx+8 else ''
            print(f'  0x{BASE+i:010x}: {hexstr}  |{asc}| {mark}')
        pos = idx + 1
