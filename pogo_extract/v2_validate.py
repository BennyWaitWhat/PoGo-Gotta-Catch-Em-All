"""
Validate all candidate offsets and produce final examples.

Test all our hypotheses:
- 148 (i32 nz=23 1-18) = ???
- 176 (i32 nz=104 val=1) = ???
- 192 (byte=1 for 557) = ???
- 269 (byte=1 for 119/120 traded) = is_traded_flag
- 248 (f32) = addedFriendshipScore
- 252 (i32) = tradingOriginalOwnerHash
- 424 (i32) = pokemon_size_category
- 192 needs more investigation

Also: look for any leftover features in unmapped 4-byte offsets
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

c = sqlite3.connect('pokemon.db').cursor()
def s2u(v): return v if v >= 0 else v + (1 << 64)
uid_to_idx = {}
for i, bs in enumerate(all_bytes):
    uid = struct.unpack_from('<Q', bs, 32)[0]
    uid_to_idx[uid] = i

def db_set(where):
    s = set()
    for (uid_signed,) in c.execute(f"SELECT uid FROM pokemon WHERE {where}").fetchall():
        u = s2u(uid_signed)
        if u in uid_to_idx:
            s.add(uid_to_idx[u])
    return s

s_traded = db_set("is_traded=1")
s_bb = db_set("is_best_buddy=1")
s_powered = db_set("is_powered_up=1")
s_purified = db_set("is_purified_flag=1")
s_mega = db_set("is_mega_evolved=1")
s_hatched = db_set("is_hatched_from_egg=1")

# ==========================================================================
print("=" * 100)
print("OFFSET 269 VALIDATION (hypothesized = is_traded)")
print("=" * 100)

idx_269 = set(i for i, bs in enumerate(all_bytes) if 269 < len(bs) and bs[269] == 1)
overlap_traded = len(idx_269 & s_traded)
not_traded_269 = idx_269 - s_traded
traded_not_269 = s_traded - idx_269
print(f"269=1 set size: {len(idx_269)}")
print(f"Overlap with traded: {overlap_traded}/120")
print(f"269=1 but NOT traded: {len(not_traded_269)}")
print(f"Traded but 269=0: {len(traded_not_269)}")

# Show edge cases
if not_traded_269:
    for idx in list(not_traded_269)[:3]:
        bs = all_bytes[idx]
        uid = struct.unpack_from('<Q', bs, 32)[0]
        uid_signed = uid if uid < 2**63 else uid - 2**64
        row = c.execute("SELECT species_name, original_owner, traded_time_ms FROM pokemon WHERE uid=?", (uid_signed,)).fetchone()
        print(f"  269=1 NOT traded: {row}")
if traded_not_269:
    for idx in list(traded_not_269)[:3]:
        bs = all_bytes[idx]
        uid = struct.unpack_from('<Q', bs, 32)[0]
        uid_signed = uid if uid < 2**63 else uid - 2**64
        row = c.execute("SELECT species_name, original_owner, traded_time_ms FROM pokemon WHERE uid=?", (uid_signed,)).fetchone()
        print(f"  traded but 269=0: {row}")

# Confirmed 269 = is_traded_flag

# ==========================================================================
print()
print("=" * 100)
print("VALIDATE 248 = addedFriendshipScore (float bit-pattern of original_location_hash low half)")
print("=" * 100)

# Already validated. Specifically: f32@248 = friendship % added (0..0.7)
# Per-trader, the value varies per pokemon (varies 0 to 0.7)
print("Sample values per trader OyeBenny (44 pokemon):")
trades_to = []
for (uid_s, owner) in c.execute("SELECT uid, original_owner FROM pokemon WHERE original_owner='OyeBenny'").fetchall():
    u = s2u(uid_s)
    idx = uid_to_idx.get(u)
    if idx is None: continue
    bs = all_bytes[idx]
    f = struct.unpack_from('<f', bs, 248)[0]
    trades_to.append(f)
trades_to.sort()
print(f"  Sorted f@248 for OyeBenny: {[round(f, 4) for f in trades_to[::4]]}")  # every 4th

# These values range 0.0-0.7 - looks like cumulative friendship%

# ==========================================================================
print()
print("=" * 100)
print("VALIDATE 424 = pokemon_size_category (XS/S/N/L/XL/XXL)")
print("=" * 100)

# size 4 = heaviest avg. Confirm with actual game-known XL pokemon
# E.g. Gyarados has 6 with 424=1, 30 with 424=3
# Pumpkaboo: small/avg/large/super sizes (in PoGo) = 4 distinct values
pump_pump = list(c.execute("SELECT uid, weight_kg, height_m FROM pokemon WHERE species_name='Pumpkaboo' ORDER BY weight_kg"))
print(f"Pumpkaboo by weight (= small/avg/large/super-size form):")
for uid_s, w, h in pump_pump[:20]:
    u = s2u(uid_s)
    idx = uid_to_idx.get(u)
    if idx is None: continue
    bs = all_bytes[idx]
    v = struct.unpack_from('<i', bs, 424)[0]
    print(f"  weight={w:.2f} height={h:.3f} 424={v}")

# Mostly Pumpkaboo small (lightest) = 424=2 or 3
# Pumpkaboo super-size (heaviest) = 424=5

# Try all-time XL/XXL pokemon (Slugma? Scizor?)
print()

# ==========================================================================
print()
print("=" * 100)
print("OFFSET 268 - upper i32 of int64 traded_time_ms (already mapped)")
print("=" * 100)

# Already-mapped clarification: 264-271 are int64 traded_time_ms.
# 268 is upper 4 bytes. NOT a new field.

# ==========================================================================
print()
print("=" * 100)
print("OFFSET 192 FINAL HYPOTHESIS - is_acquired_via_trade_OR_egg_OR_special?")
print("=" * 100)

# 557 = 377 hatched + 180 special
# Of the 180 special: 117 shiny, 32 traded, 22 BB
# Cross-check: is 192 = (acquired by hatch OR a Niantic-special obtainment?)
# 'specialAcquisitionMethod' candidate

# Let me check if 192=1 corresponds to original_owner != null
idx_192 = set(i for i, bs in enumerate(all_bytes) if 192 < len(bs) and bs[192] == 1)
with_owner_192 = 0
with_special = 0
for idx in idx_192:
    bs = all_bytes[idx]
    uid = struct.unpack_from('<Q', bs, 32)[0]
    uid_signed = uid if uid < 2**63 else uid - 2**64
    row = c.execute("SELECT original_owner, special_bg_id, alignment, costume FROM pokemon WHERE uid=?", (uid_signed,)).fetchone()
    if row:
        if row[0]: with_owner_192 += 1
        if row[1]: with_special += 1

print(f"192=1 with original_owner != NULL: {with_owner_192}/{len(idx_192)}")
print(f"192=1 with special_bg_id > 0: {with_special}/{len(idx_192)}")

# Maybe 192 = is_obtained_special (1 = obtained from non-wild source)
# = (hatched OR traded OR research OR raid OR research_breakthrough OR special_event)
# Check ALL such DB pokemon and see overlap
not_wild = c.execute("""
    SELECT COUNT(*) FROM pokemon WHERE is_hatched_from_egg=1 OR is_traded=1
""").fetchone()[0]
print(f"DB hatched OR traded: {not_wild}")

# Test: idx_192 vs (s_hatched ∪ s_traded)
hatched_or_traded = s_hatched | s_traded
print(f"hatched OR traded set: {len(hatched_or_traded)}")
print(f"  intersection with 192=1: {len(idx_192 & hatched_or_traded)}")
print(f"  192=1 but NOT (hatched OR traded): {len(idx_192 - hatched_or_traded)}")

# So 192 isn't just 'hatched OR traded' (180 - 32 = 148 are not traded either)
# Theory abandoned. Mark as 'unknown distinctive field; possibly is_special_acquisition'

# ==========================================================================
# Other candidates to check - i32 unaligned = part of larger field, but the BYTE @277 might be its own bool
# Let me check if there's any VALUE distinct to those 79 BB
# These BB pokemon all have move3 set. So 277=1 is just 'move3 ID >= 256'.
# Let's verify:
print()
print("=" * 100)
print("Confirm 277 = move3 high byte (NOT a new field)")
print("=" * 100)

idx_277 = set(i for i, bs in enumerate(all_bytes) if 277 < len(bs) and bs[277] == 1)
for idx in list(idx_277)[:5]:
    bs = all_bytes[idx]
    uid = struct.unpack_from('<Q', bs, 32)[0]
    uid_signed = uid if uid < 2**63 else uid - 2**64
    move3 = struct.unpack_from('<i', bs, 276)[0]
    row = c.execute("SELECT species_name, move1, move2 FROM pokemon WHERE uid=?", (uid_signed,)).fetchone()
    print(f"  move3={move3}: {row}")

# Yes - move3 IDs are 256-500 range for BB pokemon (newer moves like Aerial Ace = 333, etc.)

# ==========================================================================
# Final sweep - look for any aligned offset I missed
print()
print("=" * 100)
print("FINAL SWEEP - 4-byte aligned offsets with NZ count >= 50 not mapped")
print("=" * 100)

ALREADY_MAPPED = {32, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128, 136, 144, 160, 168, 172,
                  196, 200, 225, 248, 252, 264, 268, 272, 276, 296, 336, 340, 344, 348, 352, 424, 440, 480, 496}
KNOWN_STR_PTR = {64, 184, 256, 304, 360, 384}

candidates = []
for off in range(0, 509, 4):
    if off in ALREADY_MAPPED: continue
    if any(off >= sp and off < sp + 8 for sp in KNOWN_STR_PTR): continue
    if off + 4 > 512: continue
    ivals = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes]
    nz = sum(1 for v in ivals if v != 0)
    if nz >= 50:
        candidates.append((off, nz, len(set(ivals))))

print(f"  candidates with NZ >= 50:")
for off, nz, dist in candidates:
    print(f"    off={off}: nz={nz} dist={dist}")
