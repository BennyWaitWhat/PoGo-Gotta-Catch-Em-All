"""Discover unparsed PokemonProto offsets by scanning all 5413 raw_proto bytes."""
import json, struct, math
from collections import Counter

PARSED = {32, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128,
          136, 160, 168, 172, 225, 248, 264, 272, 276, 440, 480, 496}

# Mark all bytes consumed by an already-parsed field
PARSED_BYTES = set()
# u64 fields (8 bytes)
for o in [32, 136, 160, 248, 264]:
    for k in range(8): PARSED_BYTES.add(o+k)
# i32/f32 fields (4 bytes)
for o in [40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128,
          168, 172, 276, 440, 480, 496]:
    for k in range(4): PARSED_BYTES.add(o+k)
# bool (1 byte)
for o in [225, 272]:
    PARSED_BYTES.add(o)

print("Loading pokemon_v3.json...")
data = json.load(open('pokemon_v3.json'))
print(f"  {len(data)} entries")

# Convert all hex strings to bytes once
all_bytes = []
for p in data:
    h = p.get('raw_proto', '')
    if h and len(h) >= 1024:
        all_bytes.append(bytes.fromhex(h[:1024]))
print(f"  {len(all_bytes)} valid 512-byte protos")

N = len(all_bytes)
PROTO_LEN = 512

def stats_for_offset(offset, fmt, size):
    """Return (nonzero, distinct, min, max, samples) for an offset/format."""
    vals = []
    for bs in all_bytes:
        if offset + size > len(bs): continue
        try:
            v = struct.unpack_from(fmt, bs, offset)[0]
            vals.append(v)
        except: pass
    if not vals: return None
    nz = sum(1 for v in vals if v != 0 and not (isinstance(v,float) and math.isnan(v)))
    distinct = len(set(vals))
    nonzero_vals = [v for v in vals if v != 0 and not (isinstance(v,float) and math.isnan(v))]
    if not nonzero_vals:
        return (nz, distinct, 0, 0, [], vals)
    mn = min(nonzero_vals); mx = max(nonzero_vals)
    cnt = Counter(vals)
    samples = [v for v,_ in cnt.most_common(5)]
    return (nz, distinct, mn, mx, samples, vals)

# Scan every i32 / f32 / i64 / u64 / byte offset
results_i32 = {}
results_f32 = {}
results_i64 = {}
results_u64 = {}
results_byte = {}

print("\nScanning i32...")
for off in range(0, PROTO_LEN-3, 4):
    r = stats_for_offset(off, '<i', 4)
    if r and r[0] >= 50:
        results_i32[off] = r

print("Scanning f32...")
for off in range(0, PROTO_LEN-3, 4):
    r = stats_for_offset(off, '<f', 4)
    if r and r[0] >= 50:
        # filter floats: must have plausible values not NaN/inf, range reasonable
        nz, distinct, mn, mx, samples, vals = r
        plausible = [v for v in vals if v != 0 and not math.isnan(v) and not math.isinf(v) and -1e10 < v < 1e10]
        if len(plausible) >= 50:
            results_f32[off] = r

print("Scanning i64...")
for off in range(0, PROTO_LEN-7, 4):
    r = stats_for_offset(off, '<q', 8)
    if r and r[0] >= 50:
        results_i64[off] = r

print("Scanning u64...")
for off in range(0, PROTO_LEN-7, 4):
    r = stats_for_offset(off, '<Q', 8)
    if r and r[0] >= 50:
        results_u64[off] = r

print("Scanning bytes (boolean candidates)...")
# byte (bool) - check every offset
for off in range(0, PROTO_LEN):
    if off in PARSED_BYTES: continue
    vals = [bs[off] for bs in all_bytes if off < len(bs)]
    if not vals: continue
    nz = sum(1 for v in vals if v != 0)
    distinct = len(set(vals))
    if nz >= 50 and distinct <= 4:
        results_byte[off] = (nz, distinct, min(v for v in vals if v), max(vals), Counter(vals).most_common(5), vals)

# Filter parsed offsets
def is_unparsed(off, size):
    return all((off+i) not in PARSED_BYTES for i in range(size))

# Helper to dump nicely
def fmt_samples(samples, type_label):
    if type_label == 'f32':
        return ', '.join(f'{v:.4g}' for v in samples)
    return ', '.join(str(v) for v in samples)

print("\n\n=== UNPARSED i32 CANDIDATES (nonzero >= 50) ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5} {'min':>12} {'max':>14} samples")
i32_candidates = []
for off in sorted(results_i32):
    if not is_unparsed(off, 4): continue
    nz, distinct, mn, mx, samples, vals = results_i32[off]
    print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5} {mn:>12} {mx:>14} {fmt_samples(samples,'i32')}")
    i32_candidates.append((off, nz, distinct, mn, mx, samples, vals))

print("\n=== UNPARSED f32 CANDIDATES ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5} {'min':>14} {'max':>14} samples")
f32_candidates = []
for off in sorted(results_f32):
    if not is_unparsed(off, 4): continue
    nz, distinct, mn, mx, samples, vals = results_f32[off]
    # only keep "plausible float"
    plausible = [v for v in vals if v != 0 and not math.isnan(v) and not math.isinf(v) and -1e10 < v < 1e10]
    if len(plausible) < 50: continue
    samp_p = list(set(plausible))[:5]
    print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5} {min(plausible):>14.4g} {max(plausible):>14.4g} {fmt_samples(samp_p,'f32')}")
    f32_candidates.append((off, nz, distinct, min(plausible), max(plausible), samp_p, vals))

print("\n=== UNPARSED i64 CANDIDATES ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5} {'min':>20} {'max':>20}")
i64_candidates = []
for off in sorted(results_i64):
    if not is_unparsed(off, 8): continue
    nz, distinct, mn, mx, samples, vals = results_i64[off]
    print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5} {mn:>20} {mx:>20}")
    i64_candidates.append((off, nz, distinct, mn, mx, samples, vals))

print("\n=== UNPARSED u64 CANDIDATES (high distinct = uid/cell, low = enum) ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5} {'min':>22} {'max':>22}")
u64_candidates = []
for off in sorted(results_u64):
    if not is_unparsed(off, 8): continue
    # already covered in i64 mostly but useful for unsigned reads
    nz, distinct, mn, mx, samples, vals = results_u64[off]
    if nz >= 50 and distinct >= 20:
        print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5} {mn:>22} {mx:>22}")
        u64_candidates.append((off, nz, distinct, mn, mx, samples, vals))

print("\n=== UNPARSED BYTE/BOOL CANDIDATES ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5} samples")
byte_candidates = []
for off in sorted(results_byte):
    nz, distinct, mn, mx, samples, vals = results_byte[off]
    print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5} {samples}")
    byte_candidates.append((off, nz, distinct, mn, mx, samples, vals))

# Save candidates to file for later analysis
import pickle
pickle.dump({
    'i32': i32_candidates,
    'f32': f32_candidates,
    'i64': i64_candidates,
    'u64': u64_candidates,
    'byte': byte_candidates,
    'all_bytes_len': len(all_bytes),
}, open('offset_candidates.pkl', 'wb'))
print("\nSaved offset_candidates.pkl")
