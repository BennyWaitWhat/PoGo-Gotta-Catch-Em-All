"""
Deeper investigation:
- 192 (557 byte=1, 377 hatched + 180 others) - what other set?
- 277 (82 byte=1, 79 best buddies + 3) - what subset of BB?
- 424 (5369 nz, top=3, 5=130) - what scalar?
- 148 (19 byte=1) - related to mega? buddy?
- 176 (104 byte=1) - related to BB?
- list pointer for tagIds_
- mega expiry: not in 0-440 but maybe upper half/8-byte?
"""
import json, struct, sqlite3, math
from collections import Counter
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000
NOW_MS = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

data = json.load(open('pokemon_v3.json'))
all_bytes = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))
N = len(all_bytes)
all_uids = [struct.unpack_from('<Q', bs, 32)[0] for bs in all_bytes]

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

def s2u(v): return v if v >= 0 else v + (1 << 64)
uid_to_idx = {s2u(u): i for i, u in enumerate(all_uids)}  # all_uids is unsigned u64

# Wait, actually we have unsigned UIDs from the proto bytes.
# Let me rebuild properly:
uid_to_idx = {}
for i, u in enumerate(all_uids):
    uid_to_idx[u] = i

# DB pulls
def db_uid_set(where):
    rows = c.execute(f"SELECT uid FROM pokemon WHERE {where}").fetchall()
    s = set()
    for (uid_signed,) in rows:
        u = s2u(uid_signed)
        if u in uid_to_idx:
            s.add(uid_to_idx[u])
    return s

s_hatched = db_uid_set("is_hatched_from_egg=1")
s_traded = db_uid_set("is_traded=1")
s_lucky = db_uid_set("is_lucky=1")
s_bb = db_uid_set("is_best_buddy=1")
s_mega = db_uid_set("is_mega_evolved=1")
s_powered = db_uid_set("is_powered_up=1")
s_purified = db_uid_set("is_purified_flag=1")
s_shiny = db_uid_set("is_shiny=1")

# Pull full DB rows for examination
db_full = {}
rows = c.execute("""SELECT uid, species_name, level, cp, traded_time_ms, creation_time_ms,
    weather_boosted, num_additional_cpm, alignment, costume, form, original_owner,
    is_powered_up, num_upgrades_or_battles, num_poweredup_or_walks, buddy_km_walked, mega_cpm,
    is_mega_evolved, mega_evo_state, mega_cp, origin_detail
    FROM pokemon""").fetchall()
for r in rows:
    u = s2u(r[0])
    idx = uid_to_idx.get(u)
    if idx is None: continue
    db_full[idx] = r

# ==========================================================================
print("=" * 100)
print("OFFSET 192 DEEP DIVE - 557 byte=1, all 377 hatched are in this set")
print("=" * 100)

idx_off192 = set(i for i, bs in enumerate(all_bytes) if 192 < len(bs) and bs[192] == 1)
print(f"Total: {len(idx_off192)}")
print(f"   intersection with hatched: {len(idx_off192 & s_hatched)} (hatched total {len(s_hatched)})")
print(f"   intersection with traded: {len(idx_off192 & s_traded)}")
print(f"   intersection with lucky: {len(idx_off192 & s_lucky)}")
print(f"   intersection with shiny: {len(idx_off192 & s_shiny)}")
print(f"   intersection with bb: {len(idx_off192 & s_bb)}")
print(f"   non-hatched in 192: {len(idx_off192 - s_hatched)}")

# What are the 180 non-hatched ones with 192=1?
non_hatched_192 = idx_off192 - s_hatched
samples = list(non_hatched_192)[:20]
print(f"\nSamples of NON-HATCHED with 192=1 (= what flag is it?):")
for idx in samples:
    r = db_full.get(idx)
    if r:
        print(f"  uid={r[0]}  species={r[1]:15} lvl={r[2]:>5} traded={r[4]} owner={r[11]}")

# What is the alternate marker?
# Let's check for Eevee evolutions, costume specials, etc.
# Check origin_detail
od_counter = Counter(db_full[idx][20] for idx in non_hatched_192 if idx in db_full)
print(f"\norigin_detail counts among non-hatched 192=1: {od_counter.most_common(20)}")

# Also check if these have a specific costume
costume_counter = Counter(db_full[idx][9] for idx in non_hatched_192 if idx in db_full)
print(f"\ncostume counts: {costume_counter.most_common(10)}")

# Also check for is_lucky distribution
lucky_in_non_hatched_192 = len(non_hatched_192 & s_lucky)
print(f"\nlucky in non_hatched_192: {lucky_in_non_hatched_192}/{len(non_hatched_192)}")
shiny_in_non_hatched_192 = len(non_hatched_192 & s_shiny)
print(f"shiny in non_hatched_192: {shiny_in_non_hatched_192}/{len(non_hatched_192)}")

# Is offset 192 byte=1 maybe = "CAUGHT_BY_CAPTURE" vs "CAUGHT_BY_HATCH"? Or is_research_reward?
# Check creation date pattern
dates = [(idx, db_full[idx][5]) for idx in non_hatched_192 if idx in db_full and db_full[idx][5]]
date_counter = Counter()
for idx, ms in dates:
    # bin by year-month
    try:
        dt = datetime.fromtimestamp(ms/1000, tz=timezone.utc)
        date_counter[(dt.year, dt.month)] += 1
    except: pass
print(f"\ncreation YYYY-MM among non_hatched_192 (top 10):")
for ym, ct in date_counter.most_common(10):
    print(f"  {ym}: {ct}")

# ==========================================================================
print()
print("=" * 100)
print("OFFSET 277 DEEP DIVE - 82 byte=1, 79 are best buddies")
print("=" * 100)

idx_off277 = set(i for i, bs in enumerate(all_bytes) if 277 < len(bs) and bs[277] == 1)
non_bb_277 = idx_off277 - s_bb
print(f"Total off277: {len(idx_off277)}")
print(f"  intersection bb: {len(idx_off277 & s_bb)}/609 BB")
print(f"  non-BB in 277=1: {len(non_bb_277)}")
for idx in list(non_bb_277)[:10]:
    r = db_full.get(idx)
    if r:
        print(f"  uid={r[0]} species={r[1]} lvl={r[2]} buddy_km={r[15]}")

# What % of BB have 277=1?
bb_with_277 = len(s_bb & idx_off277) / len(s_bb) * 100
print(f"\n% of BB with 277=1: {bb_with_277:.1f}%")

# Are BB with 277=0 different? Maybe pokemon never deployed as buddy?
bb_without_277 = s_bb - idx_off277
print(f"BB without 277=1: {len(bb_without_277)}")
# Sample - have they walked km?
walked_count = sum(1 for idx in bb_without_277 if db_full[idx][15] and db_full[idx][15] > 0)
print(f"  of these, with buddy_km > 0: {walked_count}/{len(bb_without_277)}")
walked_count_277 = sum(1 for idx in (s_bb & idx_off277) if db_full[idx][15] and db_full[idx][15] > 0)
print(f"  of BB WITH 277=1, with buddy_km > 0: {walked_count_277}/{len(s_bb & idx_off277)}")

# Hypothesis: 277=1 means "has walked buddy distance" / "buddy_distance_completed"?
# BB requires 30km. Pokemon currently_set as buddy that haven't completed: 277=0?

# ==========================================================================
print()
print("=" * 100)
print("OFFSET 148 DEEP DIVE - 19 byte=1, looks tied to BB (74%)")
print("=" * 100)

idx_off148 = set(i for i, bs in enumerate(all_bytes) if 148 < len(bs) and bs[148] == 1)
print(f"Total: {len(idx_off148)}")
samples = list(idx_off148)[:20]
for idx in samples:
    r = db_full.get(idx)
    if r:
        print(f"  uid={r[0]} {r[1]:>15} lvl={r[2]:>5} cp={r[3]:>5} buddy_km={r[15]} mega={r[17]} mstate={r[18]}")

# ==========================================================================
print()
print("=" * 100)
print("OFFSET 176 DEEP DIVE - 104 byte=1, 62% best buddy + 38% other (mega?)")
print("=" * 100)

idx_off176 = set(i for i, bs in enumerate(all_bytes) if 176 < len(bs) and bs[176] == 1)
non_bb_176 = idx_off176 - s_bb
print(f"Total: {len(idx_off176)}")
print(f"  in BB: {len(idx_off176 & s_bb)}/{len(s_bb)} ({len(idx_off176 & s_bb)/len(s_bb)*100:.0f}% of BB)")
print(f"  non-BB samples (n={len(non_bb_176)}):")
for idx in list(non_bb_176)[:15]:
    r = db_full.get(idx)
    if r:
        print(f"  uid={r[0]} {r[1]:>15} lvl={r[2]:>5} cp={r[3]:>5} buddy_km={r[15]} mega={r[17]} powered={r[12]} upg={r[13]}")

# ==========================================================================
print()
print("=" * 100)
print("OFFSET 424 DEEP DIVE - i32 nz=5369 dist=8 top=[3=4970, 5=130, 2=123, 4=53, 0=...]")
print("=" * 100)

vals_424 = [struct.unpack_from('<i', bs, 424)[0] if 424+4<=len(bs) else 0 for bs in all_bytes]
val_counter = Counter(vals_424)
print(f"All values: {val_counter.most_common(15)}")

# What pokemon have value other than 3?
print("\nSamples by value:")
by_val = {}
for idx, v in enumerate(vals_424):
    by_val.setdefault(v, []).append(idx)
for v, idxs in sorted(by_val.items()):
    if v == 0: continue
    print(f"  val={v}: count={len(idxs)}, samples=[")
    for idx in idxs[:5]:
        r = db_full.get(idx)
        if r:
            print(f"      uid={r[0]} {r[1]:>15} lvl={r[2]:>5} weather={r[6]} costume={r[9]} form={r[10]}")

# ==========================================================================
# 8-byte data hunt: at every aligned offset, see if i64 values are timestamps/large ints
print()
print("=" * 100)
print("MEGA EXPIRY HUNT - all 8-byte aligned in 360-440 zone")
print("=" * 100)

for off in range(360, 444, 4):
    if off + 8 > 512: continue
    qvals = [struct.unpack_from('<q', bs, off)[0] for bs in all_bytes]
    in_mega_set = [qvals[i] for i in s_mega if qvals[i] != 0]
    if not in_mega_set: continue
    # If TS-like
    ts_in_mega = sum(1 for v in in_mega_set if POGO_LAUNCH_MS < v < NOW_MS + 7*86400000 + 86400000*365)
    # Future TS (mega expiry would be max 8h after activation, but if we read inactive expired ones, 0)
    print(f"  off={off}: {len(in_mega_set)} nonzero in mega set ({len(s_mega)} mega total)")

# Mega sub-struct may extend beyond 352. Let's look near offset 412-432
print()
print("=" * 100)
print("ZOOM ON 408-440 (post-mega struct)")
print("=" * 100)

for off in range(404, 444):
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    bnz = sum(1 for v in bvals if v != 0)
    eq1 = sum(1 for v in bvals if v == 1)
    if bnz > 5:
        c_top = Counter(bvals).most_common(5)
        # Cross with mega
        idx_eq1 = set(i for i, bs in enumerate(all_bytes) if off < len(bs) and bs[off] == 1)
        mega_overlap = len(idx_eq1 & s_mega)
        print(f"  off={off}: nz={bnz} eq1={eq1} mega_eq1={mega_overlap}/{len(s_mega)}  top={c_top}")

# ==========================================================================
print()
print("=" * 100)
print("HATCH DISTANCE: hatched pokemon should have a kmDistanceToHatch_ value (2/5/7/10/12 km)")
print("=" * 100)

# Try all f32 offsets
KNOWN_VALS = [2.0, 3.0, 5.0, 7.0, 10.0, 12.0]
for off in range(0, 509):
    if off + 4 > 512: continue
    fvals = [struct.unpack_from('<f', bs, off)[0] for bs in all_bytes if off+4<=len(bs)]
    # In hatched set, count values that match known km distances
    hatched_match = 0
    hatched_distinct = Counter()
    for idx in s_hatched:
        v = fvals[idx]
        if v == v and v > 0:
            for kv in KNOWN_VALS:
                if abs(v - kv) < 0.01:
                    hatched_match += 1
                    hatched_distinct[kv] += 1
                    break
    if hatched_match >= 100:
        # Also check non-hatched distribution at same offset
        non_hatched_match = sum(1 for i in range(N) if i not in s_hatched and fvals[i] in [2.0, 5.0, 7.0, 10.0, 12.0, 3.0])
        print(f"  off={off}: {hatched_match}/{len(s_hatched)} hatched match km distance, distribution: {dict(hatched_distinct)}, non-hatched match: {non_hatched_match}")

# Try i32 - some encodings are int km*1000
for off in range(0, 509, 4):
    if off + 4 > 512: continue
    ivals = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes]
    hatched_set = [ivals[i] for i in s_hatched]
    # Look for values like 2000, 5000, 7000, 10000, 12000 (km * 1000)
    match = sum(1 for v in hatched_set if v in [2000, 5000, 7000, 10000, 12000])
    if match >= 100:
        print(f"  off={off}(i32): {match}/{len(s_hatched)} match km*1000 values")

# Also 224 is interesting: 378 nz, top=256=377 - what is the 1 outlier?
# off=224 nz=378 dist=3 top=256=377  -> all hatched + 1?
print()
print("=" * 100)
print("Offset 224 (i32 nz=378, top=256) - exactly 1 more than hatched!")
print("=" * 100)

vals_224 = [struct.unpack_from('<i', bs, 224)[0] if 224+4<=len(bs) else 0 for bs in all_bytes]
idx_224_eq256 = set(i for i, v in enumerate(vals_224) if v == 256)
overlap_hatched = len(idx_224_eq256 & s_hatched)
print(f"  256 count: {len(idx_224_eq256)}, hatched overlap: {overlap_hatched}/{len(s_hatched)}")
extra = idx_224_eq256 - s_hatched
print(f"  extras (not hatched, value=256): {len(extra)}")
for idx in list(extra)[:5]:
    r = db_full.get(idx)
    if r:
        print(f"    uid={r[0]} {r[1]} origin={r[20]}")

# What about value=33?
idx_224_eq33 = set(i for i, v in enumerate(vals_224) if v == 33)
print(f"\n  33 count: {len(idx_224_eq33)}, hatched overlap: {len(idx_224_eq33 & s_hatched)}")
for idx in list(idx_224_eq33)[:5]:
    r = db_full.get(idx)
    if r:
        print(f"    uid={r[0]} {r[1]} origin={r[20]}")

# 1-byte view of 224
b224 = [bs[224] for bs in all_bytes if 224<len(bs)]
print(f"\noff 224 1-byte top: {Counter(b224).most_common(5)}")
# 224, 225, 226 - might be a 32-bit field but only 1 byte holds info
b225 = [bs[225] for bs in all_bytes if 225<len(bs)]
print(f"off 225 1-byte top: {Counter(b225).most_common(5)}")  # already known is hatchedFromEgg
b226 = [bs[226] for bs in all_bytes if 226<len(bs)]
print(f"off 226 1-byte top: {Counter(b226).most_common(5)}")
b227 = [bs[227] for bs in all_bytes if 227<len(bs)]
print(f"off 227 1-byte top: {Counter(b227).most_common(5)}")

print()
print("Now checking near 224: all bytes 220-234 distribution")
for off in range(220, 240):
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    nz = sum(1 for v in bvals if v != 0)
    if nz > 0:
        print(f"  off={off}: nz={nz}, top={Counter(bvals).most_common(5)}")

conn.close()
print("Done.")
