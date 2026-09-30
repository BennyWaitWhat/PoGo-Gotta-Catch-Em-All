"""
Final sweeping pass:
- Look at every aligned offset 0-508 (skipping known) and label them with hypothesis
- Find sub-message offsets with structure (e.g. mega substruct 336-352, capture details 264-296)
"""
import json, struct, sqlite3
from collections import Counter
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000

data = json.load(open('pokemon_v3.json'))
all_bytes = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))
N = len(all_bytes)

c = sqlite3.connect('pokemon.db').cursor()
def s2u(v): return v if v >= 0 else v + (1 << 64)
uid_to_idx = {}
for i, bs in enumerate(all_bytes):
    uid = struct.unpack_from('<Q', bs, 32)[0]
    uid_to_idx[uid] = i

# Build common subsets
def db_set(where):
    s = set()
    for (uid_signed,) in c.execute(f"SELECT uid FROM pokemon WHERE {where}").fetchall():
        u = s2u(uid_signed)
        if u in uid_to_idx:
            s.add(uid_to_idx[u])
    return s

# Things to check at 277:
# Maybe 277 = "has gym defender record"?
# 79 BB pokemon - those that have been deployed at gym for >= 1 hour?
# Niantic stores days_at_gym/total_battles_at_gym

# I wonder if 277 is something like 'has a buddy adventure event' — let's check it carefully
# Note bytes around 277 layout:
# 270 = 0
# 272 (already mapped: is_lucky)
# 276 = 0 (special_bg_id mapped here but stored as a separate i32)
# 277 = byte=1 for 82
# 278-279 = arbitrary i16 (e.g. 0x4f, 0x2b, 0x77, 0x30)
# 280-287 = i64 with values like c061c356740000 = pointer to managed object

# So 277 is byte 1 of a 4-byte field at 276
# Field at 276 = (byte276) (byte277=01) (byte278) (byte279)
# Where 276 was 'special_bg_id' i32. Re-read the stat: 276 nz=248 dist=109 range[0,493]
# Actually our existing reading of i32@276 got values like 70, 246, 103 - those are the LOWER byte!
# Wait, 'i32 little-endian' means LSB first. So i32@276 reads bytes 276,277,278,279.
# If byte 276=70 and byte 277=01 and others are 0, then i32 = 0x00000146 = 326.
# But the top says i32@276 nz=248 dist=109 range[0,493], top values 70=8, 246=7, 103=6
# So byte 276 is the low byte. 277=1 means high bit pattern 0x100.
# i32@276 = byte276 + (byte277<<8) + (byte278<<16) + (byte279<<24)

# Re-read 82 'byte277=1' pokemon's i32@276
print("Re-reading offset 276 i32 for the 82 pokemon with byte277=1:")
idx_277 = set(i for i, bs in enumerate(all_bytes) if 277 < len(bs) and bs[277] == 1)
i32_276_vals = []
for idx in idx_277:
    bs = all_bytes[idx]
    v = struct.unpack_from('<i', bs, 276)[0]
    i32_276_vals.append(v)
print(f"  {len(i32_276_vals)} values at i32@276 for 277=1 set; top: {Counter(i32_276_vals).most_common(10)}")

# Same for 277=0 set:
print()
print("i32@276 for byte277=0 pokemon:")
i32_276_zeros = [struct.unpack_from('<i', bs, 276)[0] for i, bs in enumerate(all_bytes) if not (277 < len(bs) and bs[277] == 1)]
print(f"  count={len(i32_276_zeros)} top={Counter(i32_276_zeros).most_common(10)}")

# Hmm, i32@276 for byte277=1 set should have value >= 256. Confirm.
# These look like 326, 343, 374, 304, etc. = i32 in 256-500 range
# The top values for byte277=0 are 70, 246, 103 = i32 < 256

# So i32@276 is REALLY the same field. byte277=1 just indicates value >= 256.
# So "offset 277=1" is actually "offset 276 (i32) has value >= 256".
# Which means it's the SAME field, not a new one. The OLD mapping at 276 to 'special_bg_id' may be incomplete.

# let me check all i32@276 distribution
print()
all_276 = [struct.unpack_from('<i', bs, 276)[0] for bs in all_bytes]
nz = sum(1 for v in all_276 if v != 0)
dist = len(set(all_276))
print(f"i32@276 entire pop: nz={nz} dist={dist}")
print(f"  top: {Counter(all_276).most_common(15)}")

# DB stores it as `special_bg_id`. Let me check
print()
print("DB special_bg_id distribution (should match i32@276):")
db_bg = c.execute("SELECT special_bg_id, COUNT(*) FROM pokemon GROUP BY special_bg_id ORDER BY 2 DESC LIMIT 15").fetchall()
print(f"  DB bg: {db_bg}")

# So 276 = special_bg_id is correct. The 'byte277' stats were just bytes from i32@276 values >= 256.
# Wait but the original mapping says 276 = 'is_powered_up' (no, that's a derived flag at num_additional_cpm)
# Looking at proto_offsets_discovered.md, offset 276 is in already-mapped set.

# Let me re-verify what 276 means.
# DB column special_bg_id has values like 70, 246, 103 (small) but i32@276 has larger values.
# If special_bg_id is stored as i32 trimmed, the upper byte is 0x01 representing some flag.
# Actually we have byte_277 enums:
#   For 248/120 traded pokemon (we already examined)...
# wait, 277=1 corresponds to ONLY 82 pokemon, mostly best buddies. That's NOT trade-correlated.

# Hmm, I wonder if 277 IS a separate boolean field.
# Let me check: does i32@276 with value < 256 have byte_277=0? Yes.
# Does i32@276 with value >= 256 have byte_277=1? Yes (if no upper bytes).

# Wait what if i32@276 = special_bg_id. The Niantic SpecialBackgroundType enum has values like 0,1,2,3,4...
# Values like 70, 246 are weird. Let me check:
# Top: 70=8, 246=7, 103=6, 326=8, 304=4...

# Actually those look like POKEMON IDs, not enum values! Pokemon ID 70 = Weepinbell, 246 = Larvitar.
# Maybe special_bg_id != i32@276 alone. It might be:
#   bytes 273-276 = something else (like display.special_bg)
#   bytes 277-280 = byte=1 + i24 (something else)

# Let me look at 273, 274, 275 bytes
for off in [273, 274, 275, 276, 277, 278, 279, 280]:
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    nz = sum(1 for v in bvals if v != 0)
    eq1 = sum(1 for v in bvals if v == 1)
    if nz > 0:
        c_top = Counter(bvals).most_common(8)
        print(f"  byte{off}: nz={nz} eq1={eq1}  top={c_top[:5]}")

# Now let me look at the DB column special_bg_id again - maybe it's wrong
print()
print("DB special_bg_id raw values:")
all_bg = c.execute("SELECT special_bg_id FROM pokemon").fetchall()
bg_vals = [r[0] for r in all_bg]
print(f"  Total nz: {sum(1 for v in bg_vals if v != 0)}, distinct: {len(set(bg_vals))}")
print(f"  top: {Counter(bg_vals).most_common(10)}")

# Now: what does build_db.py actually say it reads?
print()
print("=" * 100)
print("LOOK FOR LAT/LON COORD - checking float pairs for capture location")
print("=" * 100)

# We have lat/lon columns. Find what offsets feed them
db_pos = {}
for (uid_s, lat, lon) in c.execute("SELECT uid, lat, lon FROM pokemon WHERE lat IS NOT NULL AND lat != 0").fetchall():
    u = s2u(uid_s)
    idx = uid_to_idx.get(u)
    if idx is None: continue
    db_pos[idx] = (lat, lon)

print(f"  pokemon with lat/lon: {len(db_pos)}")
# For each f64 offset, check correlation with lat
import math
for off in range(0, 504, 4):
    if off + 8 > 512: continue
    matches = 0
    for idx, (lat, lon) in db_pos.items():
        bs = all_bytes[idx]
        try:
            f64 = struct.unpack_from('<d', bs, off)[0]
            if f64 == f64 and abs(f64 - lat) < 0.0001:
                matches += 1
        except: pass
    if matches > 5:
        print(f"  off={off} (f64): {matches}/{len(db_pos)} match LAT")

# Try f32 too
for off in range(0, 508, 4):
    if off + 4 > 512: continue
    matches = 0
    for idx, (lat, lon) in db_pos.items():
        bs = all_bytes[idx]
        try:
            f32 = struct.unpack_from('<f', bs, off)[0]
            if f32 == f32 and abs(f32 - lat) < 0.001:
                matches += 1
        except: pass
    if matches > 5:
        print(f"  off={off} (f32): {matches}/{len(db_pos)} match LAT")

# Look at offset 8 area which I haven't examined
print()
print("=" * 100)
print("OFFSETS 0-32 deep look (these may have struct header data)")
print("=" * 100)
for off in range(0, 32):
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    nz = sum(1 for v in bvals if v != 0)
    if nz > 100:
        c_top = Counter(bvals).most_common(5)
        print(f"  byte{off}: nz={nz}  top={c_top}")
