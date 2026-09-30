"""Validate candidate offsets against known DB counts and identify pointer fields."""
import json, struct, math, sqlite3, pickle
from collections import Counter

# Known counts from pokemon.db (validation truth)
KNOWN = {
    'hundos': 563,
    'shiny': 1066,
    'traded': 120,
    'best_buddy': 609,
    'costume': 25,
    'shadow': 228,
    'purified': 62,
    'lucky': 84,
    'deployed': 1,
    'nickname': 777,
    'weather': 1084,
    'hatched': 377,
    'adventure_fx': 21,
    'special_bg': 92,
    'location_bg': 10,
}

# String pointer detection: many proto fields are 8-byte pointers (libil2cpp.so addresses)
# These are recognizable: high bit set ~ 0x7b8... in upper bytes
def looks_like_pointer(u64_val):
    if u64_val == 0: return False
    # Pointers in this dump are around 0x7b81xxxxxxxx (very high values)
    # >= 4575657221408423936 (0x3F800000xxxxxxxx) is too low
    return u64_val > 0x100000000000  # > 2^44, reasonable for android pointers
    # Or zero. Real ints rarely have this magnitude.

# Empty string ptr
EMPTY_STR_PTR = 0x7b81c1cf40

print("Loading data + candidates...")
data = json.load(open('pokemon_v3.json'))
all_bytes = []
for p in data:
    h = p.get('raw_proto', '')
    if h and len(h) >= 1024:
        all_bytes.append(bytes.fromhex(h[:1024]))
N = len(all_bytes)
print(f"  {N} valid protos")

cand = pickle.load(open('offset_candidates.pkl', 'rb'))

# Already parsed offsets that consume bytes
PARSED_BYTES = set()
for o in [32, 136, 160, 248, 264]:
    for k in range(8): PARSED_BYTES.add(o+k)
for o in [40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128,
          168, 172, 276, 440, 480, 496]:
    for k in range(4): PARSED_BYTES.add(o+k)
for o in [225, 272]:
    PARSED_BYTES.add(o)

# === STEP 1: Identify pointer offsets (8-byte values that look like il2cpp pointers) ===
# These are typically string fields, repeated lists, or message references
print("\n=== POINTER DETECTION (8-byte pointer-like fields) ===")
print("Offsets where most values are 0 or pointer-like (>2^44).")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'ptr-like':>8} {'distinct':>8}  pattern")
ptr_offsets = []
for off in range(0, 504, 4):
    if any((off+i) in PARSED_BYTES for i in range(8)): continue
    vals = []
    for bs in all_bytes:
        v = struct.unpack_from('<Q', bs, off)[0]
        vals.append(v)
    nz = sum(1 for v in vals if v != 0)
    ptr_like = sum(1 for v in vals if looks_like_pointer(v))
    if nz < 50: continue
    if ptr_like / max(nz,1) > 0.9:
        distinct = len(set(vals))
        # samples with non-zero
        nz_vals = [v for v in vals if v != 0]
        cnt = Counter(nz_vals)
        most_common = cnt.most_common(3)
        # is it ALL the same pointer (= empty string)?
        all_same = (len(cnt) == 1)
        sample_str = ', '.join(f'0x{v:x}' for v,_ in most_common[:2])
        if all_same:
            tag = "STR-PTR (always empty)"
        elif distinct < 50:
            tag = "STR-PTR (small distinct)"
        else:
            tag = "STR/MSG-PTR"
        print(f"{off:>5} 0x{off:03x} {nz:>5} {ptr_like:>8} {distinct:>8}  {tag}: {sample_str}")
        ptr_offsets.append((off, nz, ptr_like, distinct, most_common, vals))

# Mark byte ranges of pointer offsets (8 bytes each)
PTR_BYTES = set()
for off, *_ in ptr_offsets:
    for k in range(8): PTR_BYTES.add(off+k)

# === STEP 2: True i32 candidates (excluding pointer halves) ===
print("\n\n=== i32 CANDIDATES (filtered: not part of pointers, real ints) ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5} {'min':>10} {'max':>12}  samples")
real_i32 = []
for off, nz, distinct, mn, mx, samples, vals in cand['i32']:
    if any((off+i) in PARSED_BYTES for i in range(4)): continue
    if any((off+i) in PTR_BYTES for i in range(4)): continue
    # exclude offsets that look like float-as-int (strange large values)
    sample_str = ', '.join(str(v) for v in samples[:5])
    print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5} {mn:>10} {mx:>12}  {sample_str}")
    real_i32.append((off, nz, distinct, mn, mx, samples, vals))

# === STEP 3: True f32 candidates (filter: not part of pointer/i32) ===
print("\n\n=== f32 CANDIDATES (plausible float values 0..1e6) ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5} {'min':>14} {'max':>14}  samples")
real_f32 = []
for off, nz, distinct, mn, mx, samples, vals in cand['f32']:
    if any((off+i) in PARSED_BYTES for i in range(4)): continue
    if any((off+i) in PTR_BYTES for i in range(4)): continue
    plausible = [v for v in vals if v != 0 and not math.isnan(v) and not math.isinf(v) and 0 <= v < 1e6]
    if len(plausible) < 50: continue
    samp_p = list(set(round(v,4) for v in plausible))[:5]
    sample_str = ', '.join(f'{v:.4g}' for v in samp_p)
    print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5} {min(plausible):>14.4g} {max(plausible):>14.4g}  {sample_str}")
    real_f32.append((off, len(plausible), distinct, min(plausible), max(plausible), samp_p, vals))

# === STEP 4: byte/bool candidates ===
print("\n\n=== BYTE/BOOL CANDIDATES (filtered) ===")
print(f"{'off':>5} {'hex':>5} {'nz':>5} {'dist':>5}  values")
real_bytes = []
for off, nz, distinct, mn, mx, samples, vals in cand['byte']:
    if off in PARSED_BYTES or off in PTR_BYTES: continue
    if 50 <= nz <= 5400 and distinct <= 4:
        # must be 0/1 range mostly (real bool) or small enum
        if mx <= 32:  # plausible bool/small enum
            samp_str = str(samples)
            print(f"{off:>5} 0x{off:03x} {nz:>5} {distinct:>5}  {samp_str}")
            real_bytes.append((off, nz, distinct, mn, mx, samples, vals))

# === STEP 5: Match counts to known DB fields ===
print("\n\n=== COUNT MATCHING TO KNOWN FIELDS ===")
print(f"Known: hundos={KNOWN['hundos']}, shiny={KNOWN['shiny']}, traded={KNOWN['traded']},")
print(f"       best_buddy={KNOWN['best_buddy']}, costume={KNOWN['costume']}, shadow={KNOWN['shadow']},")
print(f"       purified={KNOWN['purified']}, lucky={KNOWN['lucky']}, deployed={KNOWN['deployed']},")
print(f"       nickname={KNOWN['nickname']}, weather={KNOWN['weather']}, hatched={KNOWN['hatched']},")
print(f"       adventure_fx={KNOWN['adventure_fx']}, special_bg={KNOWN['special_bg']}, loc_bg={KNOWN['location_bg']}")
print()

def find_close_count(nz):
    matches = []
    for k, v in KNOWN.items():
        ratio = abs(nz - v) / max(v, 1)
        if ratio < 0.20:  # within 20%
            matches.append((k, v, ratio))
    return matches

print("\nByte/bool candidates with KNOWN counts:")
for off, nz, distinct, mn, mx, samples, vals in real_bytes:
    matches = find_close_count(nz)
    if matches:
        print(f"  +{off} (0x{off:x}): nz={nz} | matches: {matches}")

print("\ni32 candidates with KNOWN counts:")
for off, nz, distinct, mn, mx, samples, vals in real_i32:
    matches = find_close_count(nz)
    if matches:
        print(f"  +{off} (0x{off:x}): nz={nz} dist={distinct} mn={mn} mx={mx} | matches: {matches}")

print("\nf32 candidates with KNOWN counts:")
for off, nz, distinct, mn, mx, samples, vals in real_f32:
    matches = find_close_count(nz)
    if matches:
        print(f"  +{off} (0x{off:x}): nz={nz} dist={distinct} | matches: {matches}")

print("\nPointer offsets with KNOWN counts (likely strings):")
for off, nz, ptr_like, distinct, most_common, vals in ptr_offsets:
    nonempty = sum(1 for v in vals if v != 0 and v != EMPTY_STR_PTR)
    matches = find_close_count(nonempty) if nonempty > 0 else []
    if matches:
        print(f"  +{off} (0x{off:x}): nonempty={nonempty} distinct={distinct} | matches: {matches}")

# === STEP 6: Cross-reference offsets with database for direct validation ===
print("\n\n=== CROSS-REFERENCE: match offsets to per-pokemon DB attributes ===")
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

# Build raw_proto -> uid map by reading data
uid_to_idx = {}
for i, p in enumerate(data):
    h = p.get('raw_proto', '')
    if h and len(h) >= 1024:
        bs = bytes.fromhex(h[:1024])
        uid = struct.unpack_from('<Q', bs, 32)[0]
        if uid not in uid_to_idx:
            uid_to_idx[uid] = i  # first occurrence

# Pull DB field sets: which pokemon are hundos/lucky/shiny/traded/best_buddy
attrs = ['is_hundo','is_lucky','is_shiny','is_traded','is_best_buddy',
         'is_hatched_from_egg','adventure_effects_left','special_bg_id','location_bg_id',
         'costume','alignment','weather_boosted','is_deployed']
c.execute(f"SELECT uid, {', '.join(attrs)}, raw_proto_hex FROM pokemon")
db_rows = c.fetchall()
print(f"  Pulled {len(db_rows)} DB rows")

# For each candidate offset, build correlation with DB attribute
def attr_offset_match(attr_idx, attr_name, val_extractor):
    """For each i32 candidate offset, count how many of pokemon-with-attr have nonzero at offset."""
    correlations = []
    # Track raw bytes for each row by uid
    row_bytes = {}
    for row in db_rows:
        uid = row[0] if row[0] >= 0 else row[0] + 2**64
        proto_hex = row[-1]
        if proto_hex:
            row_bytes[uid] = bytes.fromhex(proto_hex[:1024])
    return row_bytes

row_bytes = attr_offset_match(0, '', None)
print(f"  Indexed {len(row_bytes)} rows by uid")

# For each interesting offset, analyze correlation with each attribute
def offset_vs_attr(off, fmt, size, attr_idx):
    """Return (attr_true_with_nonzero, attr_false_with_nonzero, attr_true, attr_false)"""
    a_t_nz = 0  # attr=true & offset nonzero
    a_t_z = 0
    a_f_nz = 0
    a_f_z = 0
    for row in db_rows:
        uid = row[0] if row[0] >= 0 else row[0] + 2**64
        bs = row_bytes.get(uid)
        if bs is None or off + size > len(bs): continue
        a = row[attr_idx + 1]  # +1 because uid is index 0
        try:
            v = struct.unpack_from(fmt, bs, off)[0]
            nz = v != 0 and not (isinstance(v, float) and math.isnan(v))
        except: continue
        if a:
            if nz: a_t_nz += 1
            else: a_t_z += 1
        else:
            if nz: a_f_nz += 1
            else: a_f_z += 1
    return (a_t_nz, a_t_z, a_f_nz, a_f_z)

# Check each candidate against each attribute
attr_names = attrs
print("\nChecking strong correlations (offset value tracks attribute):")
for off, nz, distinct, mn, mx, samples, vals in real_i32 + real_bytes:
    fmt, size = ('<i', 4) if (off, nz, distinct, mn, mx, samples, vals) in real_i32 else ('<B', 1)
    for ai, an in enumerate(attr_names):
        t_nz, t_z, f_nz, f_z = offset_vs_attr(off, fmt, size, ai)
        total_t = t_nz + t_z
        total_f = f_nz + f_z
        if total_t == 0: continue
        nz_rate_t = t_nz / total_t if total_t else 0
        nz_rate_f = f_nz / total_f if total_f else 0
        # strong correlation: nz_rate differs by 0.5+ between groups
        if abs(nz_rate_t - nz_rate_f) > 0.5 and total_t > 5:
            print(f"  +{off} (0x{off:x}) [{fmt}] vs {an}: T_nz={t_nz}/{total_t} ({nz_rate_t:.2f}) F_nz={f_nz}/{total_f} ({nz_rate_f:.2f})")

# Save for next step
pickle.dump({
    'real_i32': real_i32,
    'real_f32': real_f32,
    'real_bytes': real_bytes,
    'ptr_offsets': ptr_offsets,
    'row_bytes': row_bytes,
    'db_rows': db_rows,
    'attr_names': attr_names,
}, open('validated_candidates.pkl', 'wb'))
print("\nSaved validated_candidates.pkl")
