"""
Focus on 4-byte aligned offsets only (proto fields would be aligned).
Investigate hatch_distance, friendship_score, mega_expiry, list pointers.
"""
import json, struct, sqlite3, math
from collections import Counter
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000
NOW_MS = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

print("Loading pokemon_v3.json + db...")
data = json.load(open('pokemon_v3.json'))
all_bytes = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))
N = len(all_bytes)

# UIDs
all_uids = [struct.unpack_from('<Q', bs, 32)[0] for bs in all_bytes]

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

def signed_to_unsigned(v):
    return v if v >= 0 else v + (1 << 64)

uid_to_idx = {}
for i, u in enumerate(all_uids):
    uid_to_idx[u] = i

# Build subsets
def db_idx_set(where_clause):
    rows = c.execute(f"SELECT uid FROM pokemon WHERE {where_clause}").fetchall()
    s = set()
    for (uid_signed,) in rows:
        u = signed_to_unsigned(uid_signed)
        if u in uid_to_idx:
            s.add(uid_to_idx[u])
    return s

s_hatched = db_idx_set("is_hatched_from_egg=1")
s_traded = db_idx_set("is_traded=1")
s_lucky = db_idx_set("is_lucky=1")
s_bb = db_idx_set("is_best_buddy=1")
s_mega = db_idx_set("is_mega_evolved=1")
s_powered = db_idx_set("is_powered_up=1")
s_purified = db_idx_set("is_purified_flag=1")

print(f"  hatched={len(s_hatched)}  traded={len(s_traded)}  lucky={len(s_lucky)}  bb={len(s_bb)}  mega={len(s_mega)}")

# Pull DB scalars for matching
db_pokemon = {}  # idx -> dict
rows = c.execute("""SELECT uid, species_name, level, cp, traded_time_ms, creation_time_ms,
    weather_boosted, num_additional_cpm, alignment, original_owner, costume, form, original_location_hash,
    is_powered_up, num_upgrades_or_battles, num_poweredup_or_walks, buddy_km_walked, mega_cpm,
    is_mega_evolved, mega_evo_state
    FROM pokemon""").fetchall()
for row in rows:
    uid_signed = row[0]
    u = signed_to_unsigned(uid_signed)
    idx = uid_to_idx.get(u)
    if idx is None: continue
    db_pokemon[idx] = {
        'uid': uid_signed,
        'name': row[1], 'lvl': row[2], 'cp': row[3], 'traded_ms': row[4], 'creation_ms': row[5],
        'weather': row[6], 'num_addl_cpm': row[7], 'align': row[8], 'orig_owner': row[9],
        'costume': row[10], 'form': row[11], 'orig_loc_hash': row[12],
        'powered': row[13], 'upg': row[14], 'walks': row[15], 'buddy_km': row[16], 'mcpm': row[17],
        'mega': row[18], 'mstate': row[19],
    }

print()
print("=" * 100)
print("ALIGNED 4-BYTE OFFSETS - FULL STATS")
print("=" * 100)
print(f"{'Off':>4} {'NZ':>5} {'Dist':>5} {'Min':>10} {'Max':>10}  TopVals")

ALREADY_MAPPED = {32, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128, 136, 144, 160, 168, 172,
                  196, 200, 225, 248, 264, 272, 276, 296, 336, 340, 344, 348, 352, 440, 480, 496}
KNOWN_STR_PTR = {64, 184, 256, 304, 360, 384}

# 4-byte aligned offsets
aligned_results = {}
for off in range(0, 509, 4):
    if off in ALREADY_MAPPED: continue
    in_strptr = any(off >= sp and off < sp + 8 for sp in KNOWN_STR_PTR)
    in_known_i64_upper = any(off == k + 4 for k in {32, 136, 160, 248, 264})

    ivals = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes if off+4<=len(bs)]
    fvals = [struct.unpack_from('<f', bs, off)[0] for bs in all_bytes if off+4<=len(bs)]

    nz = sum(1 for v in ivals if v != 0)
    dist = len(set(ivals))

    # Float plausibility: positive finite, not NaN, in [0, 100000]
    f_pos = sum(1 for v in fvals if v == v and 0.0001 < v < 100000 and not math.isinf(v))

    # Top integer values
    top = Counter(v for v in ivals if v != 0).most_common(5)

    # Range
    nz_ivals = [v for v in ivals if v != 0]
    imin = min(nz_ivals) if nz_ivals else 0
    imax = max(nz_ivals) if nz_ivals else 0

    flag_marker = ''
    if in_strptr: flag_marker += '(str)'
    if in_known_i64_upper: flag_marker += '(i64hi)'

    aligned_results[off] = {
        'ivals': ivals, 'fvals': fvals,
        'nz': nz, 'dist': dist, 'top': top,
        'imin': imin, 'imax': imax,
        'f_pos': f_pos, 'flag': flag_marker,
    }

    if nz == 0:
        print(f"{off:>4}: ALL ZERO  {flag_marker}")
    else:
        topstr = ' '.join(f'{v}={c}' for v, c in top[:3])
        print(f"{off:>4}: nz={nz:>5} dist={dist:>5} range=[{imin},{imax}]  fpos={f_pos:>5}  top={topstr}  {flag_marker}")

# Now look at specific aligned candidates that might be hatch_distance, friendship_score, mega_expiry
print()
print("=" * 100)
print("HATCH DISTANCE candidate search")
print("=" * 100)

# Find offsets where the 377 hatched pokemon have nonzero values
# kmDistanceToHatch should be 2.0/5.0/7.0/10.0/12.0 km targets
for off in sorted(aligned_results.keys()):
    if off + 4 > 512: continue
    fvals = aligned_results[off]['fvals']
    nz_in_hatched = sum(1 for i in s_hatched if fvals[i] == fvals[i] and 0.5 < fvals[i] < 13)
    if nz_in_hatched > 100:
        # what values?
        v_counter = Counter(round(fvals[i], 2) for i in s_hatched if fvals[i] == fvals[i] and 0.5 < fvals[i] < 13)
        # check non-hatched have 0 or out-of-range values
        nz_in_non_hatched = sum(1 for i in range(N) if i not in s_hatched and fvals[i] == fvals[i] and 0.5 < fvals[i] < 13)
        print(f"  off={off:>3}  hatched_in_range={nz_in_hatched}/377  non_hatched_in_range={nz_in_non_hatched}  top: {v_counter.most_common(8)}")

print()
print("=" * 100)
print("FRIENDSHIP SCORE candidate search (i32 in range 0-100; or float in [0,100])")
print("=" * 100)

# friendship buddy levels: 0-700K xp, but score (0/1/2/3/4) is 0=stranger 1=good 2=great 3=ultra 4=best
# initialFriendshipScore_ - score added when traded (0-100 representing %)
# addedFriendshipScore_ - bonus from gifts
for off in sorted(aligned_results.keys()):
    if off + 4 > 512: continue
    ivals = aligned_results[off]['ivals']
    fvals = aligned_results[off]['fvals']
    # Score range 0-100 i32
    nz_low = sum(1 for v in ivals if 1 <= v <= 100)
    nz_traded = sum(1 for i in s_traded if 1 <= ivals[i] <= 100)
    if nz_traded > 5:
        v_counter = Counter(ivals[i] for i in s_traded if ivals[i] != 0)
        print(f"  off={off:>3}  i32 traded_nz_in[1,100]={nz_traded}/120  total_in[1,100]={nz_low}  top: {v_counter.most_common(8)}")

print()
print("=" * 100)
print("MEGA EXPIRY candidate (timestamps) - look for i64 around 360-440")
print("=" * 100)

for off in range(0, 509, 4):
    if off + 8 > 512: continue
    qvals = [struct.unpack_from('<q', bs, off)[0] for bs in all_bytes]
    ts_count = sum(1 for v in qvals if POGO_LAUNCH_MS < v < NOW_MS + 86400000)
    if ts_count >= 5:
        # Check correlation with mega-evolved
        mega_with_ts = sum(1 for i in s_mega if POGO_LAUNCH_MS < qvals[i] < NOW_MS + 86400000)
        non_mega_with_ts = ts_count - mega_with_ts
        # Get ranges
        ts_samples = [qvals[i] for i in s_mega if POGO_LAUNCH_MS < qvals[i] < NOW_MS + 86400000][:5]
        marker = '*' if off in ALREADY_MAPPED else ''
        if ts_count > 0:
            print(f"  off={off:>3} {marker} ts_count={ts_count} mega_with_ts={mega_with_ts}/154 non_mega={non_mega_with_ts}")
            for ts in ts_samples:
                try:
                    dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat()
                    print(f"     mega TS sample: {ts} ({dt})")
                except: pass

print()
print("=" * 100)
print("LIST POINTER candidates: 8-byte fields where high half = nonzero only when low half nonzero (typical struct-ptr)")
print("Look for offsets where i32 values are in repeatable address-like ranges across pokemon")
print("=" * 100)

# Lists in protobuf get a separate count field nearby. Look for small i32 that looks like a count.
# pokemonTagIds_ - if this is repeated int64, count would be 0/1/2/3.
for off in sorted(aligned_results.keys()):
    if off + 4 > 512: continue
    ivals = aligned_results[off]['ivals']
    nz = sum(1 for v in ivals if v != 0)
    distinct = len(set(v for v in ivals if v != 0))
    if 5 <= nz <= 1500 and distinct <= 10 and aligned_results[off]['imax'] <= 20 and aligned_results[off]['imin'] > 0:
        top = aligned_results[off]['top']
        print(f"  off={off:>3} nz={nz} dist={distinct} top={top[:8]}  {aligned_results[off]['flag']}")

# Check 0x80=128 specifically since user mentioned it
print()
print("=" * 100)
print("UNALIGNED STRING POINTER CHECKS for 0x40, 0x60, 0x80, 0xa0, 0xc0, 0xe0, 0x108, 0x118, 0x130, 0x140, 0x150, 0x158, 0x168, 0x180")
print("=" * 100)

# Strings in pokemon_v3 are at offsets like 0x40 (=64). The 'strings' dict in JSON likely has them
strings_per_uid_at_off = {}  # off_hex -> count
str_offset_keys = set()
for p in data:
    s = p.get('strings') or {}
    for k in s:
        str_offset_keys.add(k)

print(f"  All keys present in strings dict: {sorted(str_offset_keys)}")
for off_hex in sorted(str_offset_keys):
    nonempty = 0
    samples = []
    for p in data:
        s = p.get('strings') or {}
        v = s.get(off_hex)
        if isinstance(v, list) and len(v) > 1 and v[1]:
            nonempty += 1
            if len(samples) < 5:
                samples.append(v[1])
    print(f"  {off_hex}: {nonempty} nonempty   samples={samples}")
