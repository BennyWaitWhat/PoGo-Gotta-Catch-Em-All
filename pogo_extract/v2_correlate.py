"""
Cross-correlate offset values with known DB columns.

Strategy: for each candidate offset (boolean or i32), build the set of UIDs
that have value=X. Compare with DB sets like is_traded, is_lucky, is_hatched, etc.

Score each pair by Jaccard similarity. Print best matches.
"""
import json, struct, pickle, sqlite3
from collections import Counter

with open('v2_scan_results.pkl', 'rb') as f:
    payload = pickle.load(f)
results = payload['results']
all_uids = payload['uids']  # uint64
N = payload['N']

print(f"Loaded {N} pokemon, {len(results)} offsets")

# Build map uid (uint64) -> index
uid_to_idx = {}
for i, u in enumerate(all_uids):
    uid_to_idx[u] = i

# Build maps from DB
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

# DB stores uid as signed int64. Convert to unsigned for matching.
def signed_to_unsigned(v):
    return v if v >= 0 else v + (1 << 64)

DB_FLAGS = ['is_lucky', 'is_traded', 'is_shiny', 'is_best_buddy',
            'is_hatched_from_egg', 'is_purified_flag', 'is_mega_evolved',
            'is_powered_up']

flag_sets = {}  # flagname -> set of indices in our all_bytes array
for flag in DB_FLAGS:
    rows = c.execute(f"SELECT uid FROM pokemon WHERE {flag}=1").fetchall()
    s = set()
    for (uid_signed,) in rows:
        uid_unsigned = signed_to_unsigned(uid_signed)
        if uid_unsigned in uid_to_idx:
            s.add(uid_to_idx[uid_unsigned])
    flag_sets[flag] = s
    print(f"  flag '{flag}': {len(s)}/{len(rows)} matched into proto array")

# Also extract continuous DB columns we want to correlate floats against
db_floats = {}  # colname -> list of (idx, value) where value is non-null/non-zero
for col in ['buddy_km_walked', 'mega_cpm', 'mega_cp', 'level', 'cp']:
    rows = c.execute(f"SELECT uid, {col} FROM pokemon WHERE {col} IS NOT NULL").fetchall()
    arr = []
    for uid_signed, val in rows:
        uid_unsigned = signed_to_unsigned(uid_signed)
        idx = uid_to_idx.get(uid_unsigned)
        if idx is not None:
            arr.append((idx, val))
    db_floats[col] = arr
    print(f"  col '{col}': {len(arr)} loaded")

# 1) Boolean correlations
print()
print("=" * 110)
print("BOOLEAN OFFSET vs DB FLAG correlations (Jaccard similarity, only top hits):")
print("=" * 110)
print(f"{'Off':>4} {'eq1ct':>5}  {'flag':<28}  {'Jacc':>5}  {'Match':>6}  {'OffOnly':>7}  {'FlagOnly':>8}")
for r in results:
    off = r['off']
    if not (5 <= r['b_eq1'] <= 1500): continue
    if r['b_distinct'] > 6: continue
    # Find indices where byte=1
    off_set = set()
    # need to re-decode? we have proto bytes... actually we don't, only stats. recompute.
    # Faster: just use the existing iteration structure - re-load the json
    # We'll do a separate pass below

# We need actual UID sets per offset. Re-compute by re-loading raw bytes.
print()
print("Re-loading raw bytes for UID-level correlation...")
data = json.load(open('pokemon_v3.json'))
all_bytes = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))

# For boolean offsets:
boolean_offsets = []
for r in results:
    off = r['off']
    if 5 <= r['b_eq1'] <= 1500 and r['b_distinct'] <= 6 and r['b_eq1'] >= r['b_eq2']:
        boolean_offsets.append(off)

print(f"\n{'Off':>4} {'eq1':>5}  {'best_flag':<25}  {'Jacc':>5}  {'in_both':>7}  {'OnlyOff':>7}  {'OnlyFlag':>8}")
for off in boolean_offsets:
    off_set = set(i for i, bs in enumerate(all_bytes) if off < len(bs) and bs[off] == 1)

    # Compare to each flag
    best_flag = None
    best_score = 0
    best_meta = None
    for flag, fset in flag_sets.items():
        inter = off_set & fset
        union = off_set | fset
        if not union: continue
        j = len(inter) / len(union)
        if j > best_score:
            best_score = j
            best_flag = flag
            best_meta = (len(inter), len(off_set - fset), len(fset - off_set))

    if best_meta:
        ib, oo, fo = best_meta
        marker = '*' if off in {32, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128, 136, 144, 160, 168, 172, 196, 200, 225, 248, 264, 272, 276, 296, 336, 340, 344, 348, 352, 440, 480, 496} else ''
        print(f"{off:>4}{marker} {len(off_set):>5}  {best_flag:<25}  {best_score:.3f}  {ib:>7}  {oo:>7}  {fo:>8}")

# 2) FLOAT offset correlations - especially for buddy_km_walked
print()
print("=" * 110)
print("FLOAT OFFSET correlations with continuous DB columns:")
print("=" * 110)

# We need to find offsets whose float values match db values exactly or proportionally.
# Focus on f32 offsets we identified as float-y.
import math
float_offsets_to_check = [200, 248, 348, 352, 104, 108, 124, 172, 184, 216, 360, 368, 376, 384, 392, 456]
# Also unaligned sweeping floats may be misaligned, so try only aligned

# For each candidate, check if the float values track buddy_km_walked etc.
for off in [104, 108, 124, 172, 184, 216, 248, 360, 368, 376, 384, 392, 456]:
    if off + 4 > 512: continue
    fvals = [struct.unpack_from('<f', bs, off)[0] if off+4<=len(bs) else float('nan') for bs in all_bytes]
    # Compare to buddy_km_walked
    matches = 0
    nz_at_off = 0
    for idx, db_val in db_floats['buddy_km_walked']:
        v = fvals[idx]
        if v == v and v > 0:
            nz_at_off += 1
            if abs(v - db_val) < 0.01:
                matches += 1
    if nz_at_off > 0:
        print(f"  off={off:>3} buddy_km_walked: {matches}/{nz_at_off} match exactly")

print()
# Try integer offsets vs cp (they might be 'cpForRanking' or similar)
for off in [44, 48, 56]:  # known mapping
    pass

# 3) For offset 269 (119 boolean), 277 (82), 192 (557): check correlations
print()
print("=" * 110)
print("DETAILED CHECK on suspicious boolean offsets:")
print("=" * 110)

for off in [49, 53, 57, 148, 176, 192, 269, 272, 277, 296, 440, 441, 442, 480, 496]:
    if off >= 512: continue
    off1_set = set(i for i, bs in enumerate(all_bytes) if off < len(bs) and bs[off] == 1)
    if not off1_set: continue
    print(f"\noffset {off}: {len(off1_set)} set to byte=1")
    # Get sample UIDs
    samples = list(off1_set)[:8]
    for idx in samples:
        uid = all_uids[idx]
        # Look up in DB
        uid_signed = uid if uid < 2**63 else uid - 2**64
        row = c.execute("""SELECT species_name, level, is_lucky, is_traded, is_shiny, is_hatched_from_egg,
                          is_purified_flag, is_mega_evolved, is_best_buddy, is_powered_up,
                          buddy_km_walked, num_upgrades_or_battles, num_poweredup_or_walks,
                          weather_boosted, costume, form, alignment, traded_time_ms
                          FROM pokemon WHERE uid=?""", (uid_signed,)).fetchone()
        if row:
            print(f"  uid={uid_signed}  {row}")

    # Tally each DB flag overlap with this off=1 set
    print(f"  DB flag overlap counts:")
    for flag, fset in flag_sets.items():
        ib = len(off1_set & fset)
        if ib > 0:
            pct_off = ib / len(off1_set) * 100
            pct_flag = ib / len(fset) * 100 if fset else 0
            print(f"    {flag}: {ib} / off={pct_off:.0f}% / flag={pct_flag:.0f}%")

conn.close()
print("\nDone.")
