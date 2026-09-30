"""
Inspect a known PokemonProto in memory to map all fields.
Reads 600 bytes at a known address and shows the structure.
"""
import subprocess, struct, sys

ADB = ['adb', '-s', '100.98.158.56:5555']

def read_mem(pid, start, size):
    bs = 4096
    skip = start // bs
    count = (size + bs - 1) // bs
    cmd = f"dd if=/proc/{pid}/mem bs={bs} skip={skip} count={count} 2>/dev/null"
    return subprocess.run(ADB + ['exec-out', f'su -c "{cmd}"'], capture_output=True, timeout=30).stdout

def get_pid():
    out = subprocess.run(ADB + ['shell', 'su -c "pidof com.nianticlabs.pokemongo"'], capture_output=True, text=True).stdout
    return int(out.strip().split()[0])

# Read 600 bytes at first known pokemon address
import json
data = json.load(open('pokemon_dump.json'))
# Find a known-good pokemon (with valid creation_time)
for p in data:
    if p['creationTimeMs'] > 1467590400000 and p['uid'] != 0:
        sample = p
        break

addr = int(sample['addr'], 16)
print(f"Sample: species=#{sample['pokemonId']} cp={sample['cp']} addr={hex(addr)}")
print(f"  IVs: {sample['ivAtk']}/{sample['ivDef']}/{sample['ivSta']}")
print(f"  cpm: {sample['cpMultiplier']}, lucky: {sample['isLucky']}")
print()

pid = get_pid()
# Read 4KB centered on the pokemon (page-aligned)
page_addr = (addr // 4096) * 4096
offset_in_page = addr - page_addr
buf = read_mem(pid, page_addr, 4096)
if len(buf) < 4096:
    print(f"WARN: short read {len(buf)} bytes")

# Dump the PokemonProto
poke_size = 320
poke_data = buf[offset_in_page:offset_in_page + poke_size]
print(f"PokemonProto bytes (offset 0x00 to 0x{poke_size:x}):")
for i in range(0, len(poke_data), 16):
    hex_str = ' '.join(f'{b:02x}' for b in poke_data[i:i+16])
    asc_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in poke_data[i:i+16])
    # Decode known fields at this offset
    note = ''
    if i == 0: note = '[klass ptr]'
    elif i == 16: note = '[monitor]'
    elif i == 32: note = '[uid (int64)]'
    elif i == 40: note = '[pokemonId | cp]'
    elif i == 48: note = '[stamina | staminaMax?]'
    elif i == 56: note = '[move1 | move2]'
    elif i == 64: note = '[deployedFortId ptr]'
    elif i == 72: note = '[?]'
    elif i == 96: note = '[?]'
    elif i == 104: note = '[heightM (f32) | weightKg (f32)]'
    elif i == 112: note = '[ivAtk | ivDef]'
    elif i == 120: note = '[ivSta | cpm (f32)]'
    elif i == 128: note = '[pokeball]'
    elif i == 160: note = '[creationTimeMs (int64)]'
    elif i == 184: note = '[nickname ptr]'
    elif i == 216: note = '[pokemonDisplay ptr]'
    elif i == 272: note = '[isLucky | move3]'
    print(f'  +{i:03x}: {hex_str}  {asc_str} {note}')

# Try reading ALL int32 fields at every 4-byte offset to find more numeric fields
print("\nint32 values at each 4-byte offset:")
for i in range(0, poke_size, 4):
    val = struct.unpack_from('<i', poke_data, i)[0]
    fval = struct.unpack_from('<f', poke_data, i)[0]
    note = ''
    if 0 < val < 1100: note += f' (small uint)'
    if 0.05 < fval < 1000: note += f' (f={fval:.3f})'
    print(f'  +{i:03x}: int={val:11d} ({val:#010x}){note}')

# Pointer fields (every 8 bytes)
print("\npointer values at each 8-byte offset (where bits 47-63 match heap):")
for i in range(0, poke_size, 8):
    p = struct.unpack_from('<q', poke_data, i)[0]
    if p & 0xFFFFFFFFFFFF != 0 and (p >> 32) > 0x70 and (p >> 32) < 0x90:
        print(f'  +{i:03x}: ptr=0x{p:016x}')

# Try following pokemonDisplay pointer
display_ptr = struct.unpack_from('<Q', poke_data, 216)[0]
print(f"\npokemonDisplay ptr at +216: 0x{display_ptr:x}")
if display_ptr > 0x100000:
    page_addr2 = (display_ptr // 4096) * 4096
    offset_in_page2 = display_ptr - page_addr2
    buf2 = read_mem(pid, page_addr2, 4096)
    if len(buf2) >= offset_in_page2 + 200:
        disp_data = buf2[offset_in_page2:offset_in_page2 + 200]
        print(f"PokemonDisplayProto bytes:")
        for i in range(0, len(disp_data), 16):
            hex_str = ' '.join(f'{b:02x}' for b in disp_data[i:i+16])
            asc_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in disp_data[i:i+16])
            print(f'  +{i:03x}: {hex_str}  {asc_str}')
        print("\nint32 values in display:")
        for i in range(0, len(disp_data), 4):
            val = struct.unpack_from('<i', disp_data, i)[0]
            note = ''
            if val == 0 or val == 1: note = ' (bool?)'
            elif 0 < val < 100: note = ' (small enum)'
            print(f'  +{i:03x}: int={val:11d}{note}')

# Try following nickname
nickname_ptr = struct.unpack_from('<Q', poke_data, 184)[0]
print(f"\nnickname ptr at +184: 0x{nickname_ptr:x}")
if nickname_ptr > 0x100000:
    page_addr3 = (nickname_ptr // 4096) * 4096
    offset_in_page3 = nickname_ptr - page_addr3
    buf3 = read_mem(pid, page_addr3, 4096)
    if len(buf3) >= offset_in_page3 + 100:
        nick_bytes = buf3[offset_in_page3:offset_in_page3 + 100]
        # IL2CPP string: [klass(8)][monitor(8)][len(int32 at +0x10)][chars at +0x14]
        if len(nick_bytes) >= 24:
            nlen = struct.unpack_from('<i', nick_bytes, 0x10)[0]
            print(f"  nickname length: {nlen}")
            if 0 < nlen < 50:
                try:
                    name = nick_bytes[0x14:0x14 + nlen*2].decode('utf-16-le', errors='replace')
                    print(f"  nickname: '{name}'")
                except: pass
