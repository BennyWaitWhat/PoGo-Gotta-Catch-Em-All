"""Examine specific offsets relative to traded, lucky, hatched, best_buddy."""
import json, struct
from collections import Counter
from datetime import datetime, timezone

data = json.load(open('pokemon_v3.json'))
print(f"Loaded {len(data)} pokemon")

# Build cross-tabulations: for each pokemon, build feature vector
records = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 1024: continue
    bs = bytes.fromhex(raw)
    rec = {
        'uid': p['uid'],
        'pokemonId': p['pokemonId'],
        'cp': p['cp'],
        'cpm': p['cpm'],
        'is_hatched': bs[225] != 0,
        'has_egg_target': struct.unpack_from('<f', bs, 92)[0] > 0,
        'egg_target': struct.unpack_from('<f', bs, 92)[0],
        'tradedTimeMs': struct.unpack_from('<q', bs, 264)[0],
        'is_lucky': bs[272] != 0,
        'isBestBuddy': struct.unpack_from('<f', bs, 172)[0] > 0,
        'numAddCpm': struct.unpack_from('<f', bs, 172)[0],
        'creationMs': struct.unpack_from('<q', bs, 160)[0],
        'special_bg': struct.unpack_from('<i', bs, 440)[0],
        'location_bg': struct.unpack_from('<i', bs, 480)[0],
        'adv_effects_left': struct.unpack_from('<i', bs, 496)[0],
        # Candidates we want to dissect
        'off144': struct.unpack_from('<i', bs, 144)[0],
        'off148': struct.unpack_from('<i', bs, 148)[0],
        'off192': struct.unpack_from('<i', bs, 192)[0],
        'off196': struct.unpack_from('<i', bs, 196)[0],
        'off200': struct.unpack_from('<i', bs, 200)[0],
        'off200_f': struct.unpack_from('<f', bs, 200)[0],
        'off224': struct.unpack_from('<i', bs, 224)[0],
        'off268': struct.unpack_from('<i', bs, 268)[0],
        'off296': struct.unpack_from('<i', bs, 296)[0],
        'off336': struct.unpack_from('<i', bs, 336)[0],
        'off340': struct.unpack_from('<i', bs, 340)[0],
        'off344': struct.unpack_from('<i', bs, 344)[0],
        'off348_f': struct.unpack_from('<f', bs, 348)[0],
        'off352_f': struct.unpack_from('<f', bs, 352)[0],
        'off36_i64': struct.unpack_from('<q', bs, 36)[0],
        # 8-byte i64 candidate at 140 (was upper i64u)
        'off140_i64': struct.unpack_from('<q', bs, 140)[0],
        # int64 at 252
        'off252_i64': struct.unpack_from('<q', bs, 252)[0],
        # int32 at 256 lower of string ptr - wait, +256 is a string ptr
    }
    records.append(rec)

print(f"Built {len(records)} records\n")

# Now investigate +192 (558 non-zero, value 1 mostly, distinct 2) vs hatched cohort
print("=== +192 vs is_hatched ===")
print(Counter((r['off192'] != 0, r['is_hatched']) for r in records))
print("\n=== +192 vs has_egg_target ===")
print(Counter((r['off192'] != 0, r['has_egg_target']) for r in records))
print("\n=== +192 vs is_lucky ===")
print(Counter((r['off192'] != 0, r['is_lucky']) for r in records))

# +268 (404-411) check who has it
print("\n=== +268 distribution by is_traded, is_lucky ===")
for r in records:
    if r['off268'] != 0 and not (r['tradedTimeMs'] > 0):
        # Pokemon with off268 set but not traded
        print(f"  Non-traded with off268={r['off268']}: pokemonId={r['pokemonId']}, lucky={r['is_lucky']}, hatched={r['is_hatched']}")
        break

# +268 cross-tab with is_lucky and is_traded
print("\n=== +268 distribution ===")
for r in records:
    if r['off268'] != 0:
        # Show a few
        pass
ct = Counter((r['off268'] != 0, r['tradedTimeMs'] > 0, r['is_lucky']) for r in records)
print(f"  (off268_set, traded, lucky): {ct}")

# +268 == lucky_friend_id?
# 404-411 is a tight range. Could be "trade IV regenerated time"?
# Actually 404-411 looks like a small_int, perhaps the player level of the trader?
# 119 traded with the value, so this MIGHT be the trader's level at time of trade, OR be the player's own level when they got the trade.
# Or could be lucky_pokemon_id_of_trade.
# Show distribution alongside trade time
print("\n=== +268 values by year of trade ===")
year_268 = Counter()
for r in records:
    if r['off268'] != 0 and r['tradedTimeMs'] > 0:
        ts = r['tradedTimeMs']
        try:
            yr = datetime.fromtimestamp(ts/1000, tz=timezone.utc).year
            year_268[(yr, r['off268'])] += 1
        except: pass
for (yr, v), c in sorted(year_268.items()):
    print(f"  Year {yr} value {v}: {c}")

# +144 (304 set, range 1-4003) - check vs is_best_buddy
print("\n=== +144 (range 1-4003) vs best_buddy ===")
ct144 = Counter((r['off144'] > 0, r['isBestBuddy']) for r in records)
print(f"  (off144_set, best_buddy): {ct144}")
# Show distribution of off144 values
print("\n  Top 20 values at +144:")
val_counter = Counter(r['off144'] for r in records if r['off144'] > 0)
for v, c in val_counter.most_common(20):
    print(f"    {v}: {c}")

# +200 - 197 set, 196 distinct, looks float - could be size_height or size?
print("\n=== +200 as float ===")
floats_200 = [r['off200_f'] for r in records if r['off200_f'] > 0.001 and r['off200_f'] < 1000]
print(f"  Float-valid count: {len(floats_200)}")
print(f"  Min: {min(floats_200) if floats_200 else None}, Max: {max(floats_200) if floats_200 else None}")
print(f"  Samples: {sorted(floats_200)[:10]}")
print(f"  Top: {sorted(floats_200)[-10:]}")

# +36 interpreted as i64 - 433 timestamps. Check vs creationTime
print("\n=== +36 (i64) timestamps ===")
ts36_count = 0
for r in records:
    if 1.5e12 < r['off36_i64'] < 2e12:
        ts36_count += 1
print(f"  Looks-like-timestamp count: {ts36_count}")
# Check vs creationTime
diffs = []
for r in records:
    if 1.5e12 < r['off36_i64'] < 2e12:
        diffs.append((r['off36_i64'] - r['creationMs']) / 86400000)
if diffs:
    print(f"  Days diff (off36 - creation): min={min(diffs):.0f}, max={max(diffs):.0f}, median={sorted(diffs)[len(diffs)//2]:.0f}")

# Check vs traded
ts36_traded = sum(1 for r in records if 1.5e12 < r['off36_i64'] < 2e12 and r['tradedTimeMs'] > 0)
print(f"  Of 433 with ts at +36, in traded cohort: {ts36_traded}")

# +140 (i64) - 1261 distinct, 5410 set
print("\n=== +140 (i64) ===")
val_140 = Counter()
for r in records:
    if r['off140_i64'] != 0:
        val_140[r['off140_i64']] += 1
print(f"  Top 10: {val_140.most_common(10)}")
# Treat as bool? no.
print(f"  Total nonzero: {sum(val_140.values())}, distinct: {len(val_140)}")

# +252 (i64) - 121 set
print("\n=== +252 (i64) ===")
val_252 = Counter()
for r in records:
    if r['off252_i64'] != 0:
        val_252[r['off252_i64']] += 1
ts_count_252 = sum(1 for r in records if 1.5e12 < r['off252_i64'] < 2e12)
print(f"  Total: {sum(val_252.values())}, distinct: {len(val_252)}, ts-like: {ts_count_252}")
# Check correlation with traded
ts_252_traded = sum(1 for r in records if r['off252_i64'] > 0 and r['tradedTimeMs'] > 0)
print(f"  Of nonzero, in traded cohort: {ts_252_traded}")
# Show samples
print(f"  Samples: {list(val_252)[:5]}")
for r in records:
    if r['off252_i64'] != 0:
        print(f"    sample uid={r['uid']}: val={r['off252_i64']}, traded={r['tradedTimeMs']>0}, lucky={r['is_lucky']}")
        break

# Check: which pokemon have +296 set but are not best buddy?
print("\n=== +296 cross-tab ===")
ct296 = Counter((r['off296'] != 0, r['isBestBuddy']) for r in records)
print(f"  (off296_set, best_buddy): {ct296}")
# +296 != 0, with sample
for r in records:
    if r['off296'] != 0 and not r['isBestBuddy']:
        print(f"  off296={r['off296']} but NOT best buddy: pokemonId={r['pokemonId']}, lucky={r['is_lucky']}, traded={r['tradedTimeMs']>0}")
        break
