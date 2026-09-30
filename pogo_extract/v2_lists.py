"""
Look for list/repeated proto fields.
- pokemonTagIds_ would be a repeated int64 - typically encoded as a pointer to a contiguous buffer.
- buddyWalkedMegaEnergyAwards_ - same.
- moves_attached - same.

In a 512-byte struct backing a proto, repeated fields often appear as:
  +N+0 = pointer (8 bytes) to repeating buffer (or address-like int)
  +N+8 = count int32

Look at all 8-byte aligned spots where:
  - upper 32 bits look like a pointer (large int with structured pattern)
  - lower 32 bits + 8 bytes ahead is a small count
"""
import json, struct, sqlite3
from collections import Counter

data = json.load(open('pokemon_v3.json'))
all_bytes = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))
N = len(all_bytes)

# For each 8-byte slot, count how often the i64 is in "address space" range
# x86-64 small object pointers typically aren't great clue, but in C# the IL2CPP arrays would have pointers
# We can also look for repeated pattern: per-pokemon i64 changes (per-instance address)

# Field counts to find:
# moves_attached array - if only 2 distinct values across 5413 = NOT a list
# Tag IDs - 0..K integers between 1-1000

# Look for offsets where the value is a count: small int 0-10
print("=" * 100)
print("LIST COUNT CANDIDATES (i32 with values 0-20)")
print("=" * 100)
for off in range(0, 509, 4):
    if off + 4 > 512: continue
    vals = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes]
    in_range = sum(1 for v in vals if 0 <= v <= 20)
    nz = sum(1 for v in vals if 0 < v <= 20)
    if nz > 100 and in_range > 5400:
        # Distribution
        c_top = Counter(v for v in vals if 0 < v <= 20).most_common(8)
        # Skip if same value dominates 90%+ (it's a single field, not a count)
        first_count = c_top[0][1] if c_top else 0
        # If the values look discrete and small
        print(f"  off={off}: nz={nz} in[0,20]={in_range}  top={c_top}")

print()
print("=" * 100)
print("addedFriendshipScore_ search - look for INT or float, a small number, present mostly on TRADED pokemon")
print("=" * 100)

# For each 4-byte aligned offset, check if traded pokemon have nonzero values that small ones don't
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
def s2u(v): return v if v >= 0 else v + (1 << 64)

uid_to_idx = {}
for i, bs in enumerate(all_bytes):
    uid = struct.unpack_from('<Q', bs, 32)[0]
    uid_to_idx[uid] = i

s_traded = set()
for (uid_signed,) in c.execute("SELECT uid FROM pokemon WHERE is_traded=1"):
    u = s2u(uid_signed)
    if u in uid_to_idx:
        s_traded.add(uid_to_idx[u])

# Look for offsets where most/all of s_traded have a value, and most non-traded don't
for off in range(0, 509, 4):
    if off + 4 > 512: continue
    vals_i = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes]
    vals_f = [struct.unpack_from('<f', bs, off)[0] for bs in all_bytes]

    # i32 in range 0-100
    nz_traded_low = sum(1 for i in s_traded if 0 < vals_i[i] <= 100)
    nz_non_traded_low = sum(1 for i in range(N) if i not in s_traded and 0 < vals_i[i] <= 100)
    if nz_traded_low > 50 and nz_traded_low > nz_non_traded_low * 5 + 20:
        c_top = Counter(vals_i[i] for i in s_traded if vals_i[i] != 0).most_common(8)
        print(f"  off={off}: i32 traded_in[1,100]={nz_traded_low}/{len(s_traded)}  non_traded={nz_non_traded_low}  top={c_top}")

    # f32 in range 0-200
    nz_traded_f = sum(1 for i in s_traded if 0.001 < vals_f[i] < 200)
    nz_non_traded_f = sum(1 for i in range(N) if i not in s_traded and 0.001 < vals_f[i] < 200)
    if nz_traded_f > 50 and nz_traded_f > nz_non_traded_f * 5 + 20:
        samples = [round(vals_f[i], 4) for i in list(s_traded)[:5] if vals_f[i] > 0]
        print(f"  off={off}: f32 traded_in[0,200]={nz_traded_f}/{len(s_traded)}  non_traded={nz_non_traded_f}  samples={samples}")

print()
print("=" * 100)
print("Looking at ALL offsets that are nonzero on traded pokemon: i32, range 1-1000")
print("=" * 100)

for off in range(0, 509, 4):
    if off + 4 > 512: continue
    vals = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes]
    nz_in_traded = sum(1 for i in s_traded if vals[i] != 0)
    if nz_in_traded >= 100:
        # Check if also nz in non-traded
        nz_total = sum(1 for v in vals if v != 0)
        if nz_in_traded > nz_total * 0.8:
            c_top = Counter(vals[i] for i in s_traded if vals[i] != 0).most_common(5)
            print(f"  off={off}: traded_nz={nz_in_traded}/120, total_nz={nz_total}  top={c_top}")

# Look at the 192 question more carefully - what do those 180 non-hatched have in common?
print()
print("=" * 100)
print("OFFSET 192 = 1 BUT NOT HATCHED - what other byte/i32 also = 1?")
print("=" * 100)

idx_192_not_hatched = set()
for i, bs in enumerate(all_bytes):
    if 192 < len(bs) and bs[192] == 1:
        # Get UID
        uid = struct.unpack_from('<Q', bs, 32)[0]
        # Check DB if hatched
        uid_signed = uid if uid < 2**63 else uid - 2**64
        row = c.execute("SELECT is_hatched_from_egg FROM pokemon WHERE uid=?", (uid_signed,)).fetchone()
        if row and row[0] == 0:
            idx_192_not_hatched.add(i)

print(f"Pokemon with 192=1 but NOT hatched: {len(idx_192_not_hatched)}")

# At each other byte offset, check if ALL of these have byte=1 (subset signal)
for off in range(0, 509):
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    eq1_in_subset = sum(1 for i in idx_192_not_hatched if bvals[i] == 1)
    eq1_total = sum(1 for v in bvals if v == 1)
    if eq1_in_subset >= 80 and eq1_in_subset > eq1_total * 0.4:
        print(f"  off={off}: subset eq1={eq1_in_subset}/{len(idx_192_not_hatched)}  total eq1={eq1_total}")

# Maybe these are ALL caught with curveball/excellent throw?
# Check if any consistent 4-byte aligned i32 distinguishes them
print()
print("Looking for any consistent value at any offset for the 180 'special non-hatched' subset:")
for off in range(0, 509, 1):
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    # Most common in subset
    c_subset = Counter(bvals[i] for i in idx_192_not_hatched).most_common(3)
    # Check if subset has unusually high count of one byte vs rest
    if c_subset and c_subset[0][1] > 150:  # at least 80% of subset
        v0, ct = c_subset[0]
        # Check count outside subset
        outside_count = sum(1 for i in range(N) if i not in idx_192_not_hatched and bvals[i] == v0)
        # If ratio inside-subset is much higher than outside
        in_pct = ct / len(idx_192_not_hatched)
        out_pct = outside_count / (N - len(idx_192_not_hatched))
        if in_pct > out_pct * 2 and v0 != 0:
            print(f"  off={off}: subset top byte = {v0} ({ct}/{len(idx_192_not_hatched)} = {in_pct*100:.0f}%) vs outside {out_pct*100:.0f}%")

conn.close()
