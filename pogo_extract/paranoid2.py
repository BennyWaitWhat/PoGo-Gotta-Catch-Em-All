"""Paranoid string decryption with stricter Java semantics."""
import os, json, struct
os.environ['LOGURU_LEVEL'] = 'CRITICAL'
from loguru import logger as _l
_l.remove()

with open('chunk0.json', 'r') as f:
    chunk_chars = json.load(f)['chars']
chunks = [''.join(chr(c) for c in chunk_chars)]

M16 = 0xFFFF
M32 = 0xFFFFFFFF
M64 = 0xFFFFFFFFFFFFFFFF

def i32(v):
    """Cast Python int to Java int (32-bit signed via two's complement representation as Python int >=0 OR negative)."""
    v &= M32
    if v >= 0x80000000:
        v -= 0x100000000
    return v

def i64(v):
    v &= M64
    if v >= 0x8000000000000000:
        v -= 0x10000000000000000
    return v

def short(v):
    """Java short cast: take low 16 bits, sign-extend to int."""
    v &= M16
    if v >= 0x8000:
        v -= 0x10000
    return v

def long_to_int(v):
    return i32(v & M32)

def int_to_long(v):
    """Sign-extending int -> long."""
    if v < 0:
        # Already negative, just mask to 64-bit two's complement when needed
        return i64(v)
    return v

def rotl(s, n):
    """rotl(short, int) -> short. Bytecode: shl v1<<n; rsub 32-n; ushr v1>>>(32-n); or; int-to-short."""
    # s is short (signed 16-bit value as Python int possibly negative)
    # In bytecode, s is in an int register, so convert to int repr
    v1 = i32(s)  # treat as 32-bit signed int
    shifted = i32((v1 & M32) << n & M32)  # signed shift
    rsh = (v1 & M32) >> (32 - n)  # unsigned shift
    out = i32(((shifted & M32) | rsh) & M32)
    return short(out)

def next_(state):
    state = i64(state & M64)
    state_u = state & M64
    # v2 = (short) (state & 0xFFFF)
    v2 = short(state_u & M16)
    # ushr 16
    state_u = (state_u & M64) >> 16
    state_u &= M16  # AND 0xFFFF
    v4 = short(state_u)
    # v5 = (short)(v2 + v4)
    v5 = short(v2 + v4)
    # v5 = rotl(v5, 9)
    v5 = rotl(v5, 9)
    # v5 = (short)(v5 + v2)  -- but bytecode says add-int/2addr v5,v2 then int-to-short
    v5 = short(v5 + v2)
    # v4 = (short)(v4 ^ v2)
    v4 = short(v4 ^ v2)
    # tmp = rotl(v2, 13)
    v0 = rotl(v2, 13)
    # v0 = (short)(v0 ^ v4)
    v0 = short(v0 ^ v4)
    # v1 = v4 << 5  (int operation)
    v1 = i32((v4 & M32) << 5 & M32)
    # v0 = (short)(v0 ^ v1)
    v0 = short(v0 ^ v1)
    # v4 = rotl(v4, 10)
    v4 = rotl(v4, 10)
    # Combine: (long)v5 << 16 | (long)v4 -> v1; v1 <<= 16; (long)v0; v4 = v1 | v0
    v5_l = int_to_long(v5)
    v4_l = int_to_long(v4)
    v0_l = int_to_long(v0)
    v1l = i64(((v5_l & M64) << 16) & M64) | (v4_l & M64)
    v1l &= M64
    v1l = (v1l << 16) & M64
    out = (v1l | (v0_l & M64)) & M64
    return out

def seed(s):
    s &= M64
    s = (s ^ (s >> 33)) & M64
    s = (s * 7109453100751455733) & M64
    s = (s ^ (s >> 28)) & M64
    s = (s * ((-3808689974395783757) & M64)) & M64
    s = (s >> 32) & M64
    return s

def get_char_at(idx, chunks, state):
    state = next_(state)
    chunk_idx = idx // 8191
    pos = idx % 8191
    ch = ord(chunks[chunk_idx][pos])
    # Bytecode: int-to-long ch (actually char->int->long); shl 32; xor state
    result = (((ch & M32) << 32) ^ (state & M64)) & M64
    return result, state

def get_string(id_, chunks):
    seed_in = id_ & M32
    state = seed(seed_in)
    state = next_(state)
    v3 = (state & M64) >> 32
    v3 &= M16
    state = next_(state)
    # v7 = state >>> 16; v7 &= 0xFFFFFFFFFFFF0000  (-65536 as 64-bit)
    v7 = (state & M64) >> 16
    v7 &= 0xFFFFFFFFFFFF0000
    high32_id = (id_ & M64) >> 32
    high32_id &= M32  # mask -- shouldn't change anything since we did >>32
    v11 = (high32_id ^ v3 ^ v7) & M64
    v12 = v11 & M32
    if v12 & 0x80000000:
        v12 = v12 - 0x100000000
    val, state = get_char_at(v12, chunks, state)
    length_val = (val >> 32) & M16
    chars = []
    for i in range(length_val):
        idx = v12 + i + 1
        val, state = get_char_at(idx, chunks, state)
        c = (val >> 32) & M16
        chars.append(chr(c))
    return ''.join(chars)

# Test on first ID
test = 0xfffffd7559751514
try:
    print(repr(get_string(test, chunks)))
except Exception as e:
    print('err:', e)

# All IDs
ids = [0xfffffd7559751514, 0xfffffd9659751514, 0xfffffde859751514, 0xfffffe3f59751514,
       0xfffffe6959751514, 0xfffffe7259751514, 0xfffffe9b59751514, 0xfffffea959751514,
       0xfffffeb059751514, 0xffffff1659751514, 0xffffff2959751514, 0xffffff4459751514,
       0xffffff4b59751514, 0xffffff5d59751514, 0xffffff9359751514, 0xffffffc059751514,
       0xffffffcc59751514, 0xffffffcd59751514, 0xffffffce59751514, 0xffffffff59751514]
for id_ in ids:
    try:
        s = get_string(id_, chunks)
        print(f'{id_:#018x} -> {s!r}')
    except Exception as e:
        print(f'{id_:#018x} -> ERR: {e}')
