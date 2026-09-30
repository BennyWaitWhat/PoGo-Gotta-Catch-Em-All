"""Decrypt all paranoid-obfuscated strings in iPogo's classes.dex launcher."""
import os, json
os.environ['LOGURU_LEVEL'] = 'CRITICAL'
from loguru import logger as _l
_l.remove()

# Reuse extracted chunk
with open('chunk0.json', 'r') as f:
    chunk_chars = json.load(f)['chars']
chunk_str = ''.join(chr(c) for c in chunk_chars)
chunks = [chunk_str]

M16 = 0xFFFF
M32 = 0xFFFFFFFF
M64 = 0xFFFFFFFFFFFFFFFF

def to_short(x):
    x &= M16
    if x >= 0x8000:
        return x - 0x10000
    return x

def rotl(s, n):
    v1 = s & M32
    shifted = (v1 << n) & M32
    rsh = (v1 & M32) >> (32 - n)
    out = (shifted | rsh) & M32
    return to_short(out & M16)

def next_(state):
    state &= M64
    v2 = to_short(state & M16)
    v4 = to_short((state >> 16) & M16)
    v5_a = to_short((v2 + v4) & M16)
    v5 = rotl(v5_a, 9)
    v5 = to_short((v5 + v2) & M16)
    v4_x = to_short(v4 ^ v2)
    v0 = rotl(v2, 13)
    v0 = to_short(v0 ^ v4_x)
    v0 = to_short(v0 ^ ((v4_x << 5) & M16))
    v4_r = rotl(v4_x, 10)
    v5_l = v5 & M16
    v4_l = v4_r & M16
    v0_l = v0 & M16
    v1 = ((v5_l << 16) | v4_l) & M32
    v4_full = ((v1 << 16) | v0_l) & M64
    return v4_full

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
    result = (((ch & M32) << 32) ^ (state & M64)) & M64
    return result, state

def get_string(id_, chunks):
    seed_in = id_ & M32
    state = seed(seed_in)
    state = next_(state)
    v3 = (state >> 32) & M16
    state = next_(state)
    v7 = (state >> 16) & 0xFFFFFFFFFFFF0000
    high32_id = (id_ >> 32) & M32
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

# Find all call sites
from androguard.core.dex import DEX
with open('classes.dex', 'rb') as f:
    dx = DEX(f.read())

hits = []
for c in dx.get_classes():
    cname = c.get_name()
    if 'app/ipogo' not in cname:
        continue
    for m in c.get_methods():
        code = m.get_code()
        if code is None:
            continue
        instrs = list(code.get_bc().get_instructions())
        regs = {}
        for ins in instrs:
            try:
                opname = ins.get_name()
            except Exception:
                opname = ''
            try:
                output = ins.get_output()
            except Exception:
                output = ''
            if opname in ('const-wide', 'const-wide/16', 'const-wide/32', 'const-wide/high16'):
                parts = output.split(',', 1)
                reg = parts[0].strip()
                try:
                    val = int(parts[1].strip())
                except Exception:
                    continue
                regs[reg] = val & M64
            elif opname.startswith('invoke') and 'paranoid/Deobfuscator' in output and 'getString' in output:
                args = output.split(',')
                # The signature is getString(J), so we look at the first arg that is a long-pair reg
                # the disasm shows e.g. "v3, v4, Lio/...->getString(J)..."
                reg_arg = args[0].strip()
                if reg_arg in regs:
                    hits.append((cname, m.get_name(), regs[reg_arg]))

print(f'getString call sites in app/ipogo classes: {len(hits)}')
unique_ids = sorted(set(h[2] for h in hits))
print(f'Unique IDs: {len(unique_ids)}')

decoded = {}
for id_ in unique_ids:
    try:
        s = get_string(id_, chunks)
        decoded[id_] = s
    except Exception as e:
        decoded[id_] = f'<err: {e}>'

with open('decoded_strings.txt', 'w', encoding='utf-8') as f:
    for id_, s in sorted(decoded.items()):
        f.write(f'{id_:#018x} -> {s!r}\n')
print(f'wrote decoded_strings.txt')
for id_ in unique_ids:
    print(f'{id_:#018x}  {decoded[id_]!r}')
