"""Dig further into +36 (timestamps), +140 (large int), +200 (buddy km), +192."""
import json, struct
from collections import Counter
from datetime import datetime, timezone

data = json.load(open('pokemon_v3.json'))
records = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 1024: continue
    bs = bytes.fromhex(raw)
    rec = {
        'uid': p['uid'],
        'pokemonId': p['pokemonId'],
        'cp': p['cp'],
        'is_hatched': bs[225] != 0,
        'has_egg_target': struct.unpack_from('<f', bs, 92)[0] > 0,
        'tradedTimeMs': struct.unpack_from('<q', bs, 264)[0],
        'is_lucky': bs[272] != 0,
        'isBestBuddy': struct.unpack_from('<f', bs, 172)[0] > 0,
        'numAddCpm': struct.unpack_from('<f', bs, 172)[0],
        'creationMs': struct.unpack_from('<q', bs, 160)[0],
        'special_bg': struct.unpack_from('<i', bs, 440)[0],
        'location_bg': struct.unpack_from('<i', bs, 480)[0],
        'adv_effects_left': struct.unpack_from('<i', bs, 496)[0],
        'origin': struct.unpack_from('<i', bs, 168)[0],
        'off36_i64': struct.unpack_from('<q', bs, 36)[0],
        'off144': struct.unpack_from('<i', bs, 144)[0],
        'off192': struct.unpack_from('<i', bs, 192)[0],
        'off200_f': struct.unpack_from('<f', bs, 200)[0],
        'off224': struct.unpack_from('<i', bs, 224)[0],
        'off268': struct.unpack_from('<i', bs, 268)[0],
        'off280': struct.unpack_from('<i', bs, 280)[0],
        'off336': struct.unpack_from('<i', bs, 336)[0],
        'off340': struct.unpack_from('<i', bs, 340)[0],
        'off344': struct.unpack_from('<i', bs, 344)[0],
        'off348_f': struct.unpack_from('<f', bs, 348)[0],
        'off352_f': struct.unpack_from('<f', bs, 352)[0],
        'off416_i64': struct.unpack_from('<q', bs, 416)[0],
        'off416': struct.unpack_from('<i', bs, 416)[0],
    }
    records.append(rec)

# === +36 timestamp analysis ===
print("=== +36 (i64) timestamp analysis ===")
print(f"Total records: {len(records)}")
ts36_records = [r for r in records if 1.4e12 < r['off36_i64'] < 2e12]
print(f"Records with +36 looking like timestamp: {len(ts36_records)}")

# Cross-tab with origin types - might be specifically for specific origins
origin_dist = Counter(r['origin'] for r in ts36_records)
print(f"  Origin distribution of +36-as-ts: {origin_dist}")

# Cross-tab with lucky, hatched
print(f"  Of these, lucky: {sum(1 for r in ts36_records if r['is_lucky'])}, hatched: {sum(1 for r in ts36_records if r['is_hatched'])}")

# What does -862-day diff mean? Maybe original capture time before trade
# Check trade timestamp analysis
trade_diffs = []
for r in ts36_records:
    if r['tradedTimeMs'] > 0:
        diff_days = (r['off36_i64'] - r['tradedTimeMs']) / 86400000
        trade_diffs.append(diff_days)
print(f"  +36 vs traded time: of {len(trade_diffs)} traded, days diff median: {sorted(trade_diffs)[len(trade_diffs)//2] if trade_diffs else 'N/A'}")

# +36 vs creation
creation_diffs = []
for r in ts36_records:
    diff_hr = (r['creationMs'] - r['off36_i64']) / 3600000
    creation_diffs.append(diff_hr)
if creation_diffs:
    creation_diffs.sort()
    print(f"  Creation - +36 (hours): min={creation_diffs[0]:.0f}, p25={creation_diffs[len(creation_diffs)//4]:.0f}, median={creation_diffs[len(creation_diffs)//2]:.0f}, max={creation_diffs[-1]:.0f}")

# Is +36 the SAME timestamp for many pokemon caught at same time?
# Look for clusters
ts_counter = Counter(r['off36_i64'] for r in ts36_records)
print(f"  Most repeated +36 ts:")
for v, cnt in ts_counter.most_common(5):
    if cnt > 1:
        try:
            dt = datetime.fromtimestamp(v/1000, tz=timezone.utc).isoformat()
            print(f"    {dt}: {cnt} pokemon")
        except: pass

# Check: are pokemon with +36 ts those that are RAID origins?
print(f"\n  +36 set, by origin name:")
ORIGIN_NAMES = {0:'UNSET',1:'POKESTOP',2:'GYM',3:'PHOTOBOMBED',4:'GO_SNAPSHOT',5:'GO_BATTLE_LEAGUE',6:'BATTLE_RAID',7:'INCENSE',8:'GIFT',9:'ROUTE',10:'ADVENTURE_SYNC',11:'POKEMON_HOME',12:'BREAD',13:'TRADE',14:'EGG_HATCH',15:'TUTORIAL'}
for o, c in origin_dist.most_common():
    print(f"    {ORIGIN_NAMES.get(o, o)}: {c}")

# === +144 vs best_buddy + traded ===
print("\n=== +144 (numUpgrades?) ===")
high144 = [r for r in records if r['off144'] > 100]
print(f"  +144 > 100: {len(high144)} pokemon")
print(f"  +144 > 1000: {len([r for r in records if r['off144'] > 1000])}")
# Show examples
print(f"  Top values:")
for r in sorted(records, key=lambda x: -x['off144'])[:10]:
    print(f"    pokemon#{r['pokemonId']}: +144={r['off144']}, best_buddy={r['isBestBuddy']}, cp={r['cp']}")

# Hmm, max 4003 - looks like a number field. NumUpgrades=4003 makes no sense.
# Could be XL candy count? or duration in seconds since... ?
# Actually let's check if +144 is uint32
# Top values look like they could be timestamps in seconds since some epoch
# Or could be powerUpProgress in range 0-4003

# Actually, max =4003. and there's also a tail at 70, 11, 9, 8...
# This pattern matches "candy spent" or "candy XL" used.
# Also matches power-up cost in candy.

# === +200 (buddy_km) histogram ===
print("\n=== +200 (buddy km candidate) histogram ===")
buddy_km = sorted(r['off200_f'] for r in records if 0.001 < r['off200_f'] < 1000)
print(f"  Total: {len(buddy_km)}")
buckets = [0, 1, 5, 10, 25, 50, 100, 200, 500, 1000]
for i in range(len(buckets)-1):
    lo, hi = buckets[i], buckets[i+1]
    cnt = sum(1 for v in buddy_km if lo <= v < hi)
    print(f"  {lo}-{hi}km: {cnt}")
print(f"  Max: {max(buddy_km):.2f}km")
# Sanity: best buddies are 30km. So pokemon with > 30 should include all best buddies
print(f"  >= 30km: {sum(1 for v in buddy_km if v >= 30)}")
# but only 197 have data here, vs 232 best buddies - why?
# Some best buddies might have walked under 30km (got it via berries/etc) - but BB requires 30km buddyhood
# The 197/232 discrepancy is odd. Maybe +200 is currentBuddyKm (only set when currently buddied), not lifetimeKm?
print(f"  Best buddies but +200 = 0: {sum(1 for r in records if r['isBestBuddy'] and r['off200_f'] <= 0.001)}")

# === +268 (404-411) deeper ===
print("\n=== +268 distribution ===")
# Are these distinct trade events?
v268 = Counter(r['off268'] for r in records if r['off268'] != 0)
for v, c in v268.most_common():
    print(f"  value {v}: {c} pokemon")
# Note value range is 404-411.
# Could it be: trader player level? But >50 makes no sense.
# Could be the partner's player level multiplied by some factor?
# Or could be "lucky friend giftSequenceNumber" / "tradeId modulo something"
# Actually traded pokemon = 120, off268 set in 119/120 - ALL lucky pokemon (traded ones)
# Lucky pokemon must have traded date.
# Note: NOT all lucky are traded - lucky from special events.
# 84 lucky - 83 of them have +268. 1 lucky doesn't have +268.
# (True, True, True): 83  [+268 set, traded, lucky]
# (True, True, False): 36 [+268 set, traded, NOT lucky]
# So +268 = trade-related but only 36 non-lucky traded have it.
# Of 120 traded, 119 have +268. 84 lucky pokemon, 83 have +268.
# So +268 ≈ "is traded" indicator (119 vs 120 cohort).
# Values 404-411 with most-common 407...
# Could this be "tradeFlavor" or "tradeOriginalLat" hashed?
# Check: maybe it's related to which "season / event" the trade happened.
# Look at years: all 2024-2025 trades.

# === +280 - 273 set, 273 distinct ===
# This is a heap pointer (we saw earlier)

# === Mega evolution candidate group +336/340/344/348/352 ===
print("\n=== Mega evolution candidate (+336-352) ===")
mega_set = [r for r in records if r['off336'] != 0 or r['off344'] != 0]
print(f"  Pokemon with mega-cluster set: {len(mega_set)}")
# Cross-correlate with mega-capable species
# Mega-capable in PoGO: Charizard, Blastoise, Venusaur, Beedrill, Pidgeot, Slowbro, Houndoom, Manectric, Aerodactyl, Ampharos, Gengar, Kangaskhan, Gyarados, Scizor, Heracross, Garchomp, Latias, Latios, Diancie, Audino, Steelix, Sceptile, Swampert, Lopunny, Altaria, Salamence, Banette, Absol, Mawile, Glalie, Tyranitar, Abomasnow, Pinsir, Rayquaza
MEGA_CAPABLE_IDS = {3, 6, 9, 15, 18, 80, 94, 115, 130, 142, 181, 208, 212, 214, 248, 254, 257, 282, 302, 306, 308, 310, 319, 334, 359, 362, 373, 376, 380, 381, 384, 428, 445, 460, 475, 531}
mega_pokemon_ids = [r['pokemonId'] for r in mega_set]
mega_in_capable = sum(1 for pid in mega_pokemon_ids if pid in MEGA_CAPABLE_IDS)
print(f"  Of those, in mega-capable species list: {mega_in_capable}/{len(mega_set)}")
# Distribution of pokemon IDs in mega cluster
print(f"  Top species in mega cluster: {Counter(mega_pokemon_ids).most_common(15)}")
# +336 is always 1 (when set). +340 is 1 or 2. +344 is mega CP (47-6672), +348 is CPM ~1, +352 is original CPM (0.094-0.86)
# Scatter +344 (CP) vs +352 (CPM - which level)
print(f"\n  +344 (mega CP) samples vs +352 (CPM):")
for r in mega_set[:10]:
    print(f"    pokemon#{r['pokemonId']}: +344={r['off344']}, +352_cpm={r['off352_f']:.4f}, +348_f={r['off348_f']:.4f}, +340={r['off340']}, +336={r['off336']}")
