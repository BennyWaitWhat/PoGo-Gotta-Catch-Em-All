"""Determine +200 - is it a float field, a pointer, or what?"""
import json, struct
from collections import Counter

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
        'numAddCpm': struct.unpack_from('<f', bs, 172)[0],
        'isBestBuddy': struct.unpack_from('<f', bs, 172)[0] > 0,
        'tradedTimeMs': struct.unpack_from('<q', bs, 264)[0],
        'is_lucky': bs[272] != 0,
        'creationMs': struct.unpack_from('<q', bs, 160)[0],
        'origin': struct.unpack_from('<i', bs, 168)[0],
        # +200 as i32, f32, i64
        'off200': struct.unpack_from('<i', bs, 200)[0],
        'off200_f': struct.unpack_from('<f', bs, 200)[0],
        'off200_i64': struct.unpack_from('<q', bs, 200)[0],
        'off204': struct.unpack_from('<i', bs, 204)[0],
        'off204_f': struct.unpack_from('<f', bs, 204)[0],
        # +204 (next 4 bytes after +200)
    }
    records.append(rec)

# Show all 197 records with +200 set
nonzero_200 = [r for r in records if r['off200'] != 0 and r['off200'] != -1]
print(f"+200 nonzero: {len(nonzero_200)}")

# Is +204 always 0 when +200 is float? If yes, +200 is a true 4-byte float, not part of an 8-byte field.
print(f"\n+200 set AND +204 == 0: {sum(1 for r in nonzero_200 if r['off204'] == 0)}")
print(f"+200 set AND +204 != 0: {sum(1 for r in nonzero_200 if r['off204'] != 0)}")

# So +200 is independent of +204
# Float values
print(f"\n+200 as float, range:")
fvals = sorted(r['off200_f'] for r in nonzero_200 if 0.0001 < r['off200_f'] < 10000)
print(f"  N={len(fvals)}")
print(f"  Min: {fvals[0]:.4f}, p10: {fvals[len(fvals)//10]:.4f}, median: {fvals[len(fvals)//2]:.4f}, p90: {fvals[len(fvals)*9//10]:.4f}, max: {fvals[-1]:.4f}")

# Distribution buckets
print(f"\nBuckets:")
import math
buckets = [0, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500]
for i in range(len(buckets)-1):
    c = sum(1 for v in fvals if buckets[i] <= v < buckets[i+1])
    print(f"  [{buckets[i]}-{buckets[i+1]}): {c}")

# Cross-tab with isBestBuddy
print(f"\n+200 set vs isBestBuddy:")
print(f"  off200>0 AND BB: {sum(1 for r in nonzero_200 if r['isBestBuddy'])}")
print(f"  off200>0 NOT BB: {sum(1 for r in nonzero_200 if not r['isBestBuddy'])}")

# Cross-tab with origin
print(f"\n+200 set, by origin:")
ORIGIN_NAMES = {0:'UNSET',1:'POKESTOP',2:'GYM',3:'PHOTOBOMBED',4:'GO_SNAPSHOT',5:'GO_BATTLE_LEAGUE',6:'BATTLE_RAID',7:'INCENSE',8:'GIFT',9:'ROUTE',10:'ADVENTURE_SYNC',11:'POKEMON_HOME',12:'BREAD',13:'TRADE',14:'EGG_HATCH',15:'TUTORIAL'}
oc = Counter(r['origin'] for r in nonzero_200)
for o, c in oc.most_common():
    print(f"  {ORIGIN_NAMES.get(o, o)}: {c}")

# Lucky cross-tab
print(f"\n+200 set vs lucky:")
print(f"  +200>0 AND lucky: {sum(1 for r in nonzero_200 if r['is_lucky'])}")
print(f"  Lucky overall: {sum(1 for r in records if r['is_lucky'])}")

# Look at 197 set vs the 232 best buddies
# Best buddies that don't have +200 set: are they recently buddied or perma BB?
non_200_BB = [r for r in records if r['isBestBuddy'] and r['off200_f'] <= 0.001]
have_200_BB = [r for r in nonzero_200 if r['isBestBuddy']]
print(f"\nBest buddies WITH +200: {len(have_200_BB)}, WITHOUT +200: {len(non_200_BB)}")

# Look at +200 distribution among non-BB
non_BB_200 = [r for r in nonzero_200 if not r['isBestBuddy']]
print(f"\nNon-BB pokemon with +200 set: {len(non_BB_200)}")
# What range of values?
vals_non_BB = sorted(r['off200_f'] for r in non_BB_200)
if vals_non_BB:
    print(f"  Range: {vals_non_BB[0]:.4f} to {vals_non_BB[-1]:.4f}")
# Sample
for r in non_BB_200[:5]:
    print(f"    pokemon#{r['pokemonId']}: +200={r['off200_f']:.4f}, lucky={r['is_lucky']}, traded={r['tradedTimeMs']>0}")

# Possibly this is ACTUAL active-buddy KM. 197 matches "had buddy walks at any point".
# Or it's hatched-from-egg-distance (PoGo shows "hatched from 5km egg, walked X.YYkm")
# But hatched cohort = 374, not 197.
# What's 197? Could be "current buddy walk distance" - resetting to 0 on swap.
# OR it could be `buddyTotalKmWalked` for pokemon currently buddied.

# Let me check: does +200 correlate with buddy candy?
# Wait - we don't know buddy candy.

# Final check: what's +204 (might be int marker for has_+200 set)
print(f"\n+204 distribution: {Counter(r['off204'] for r in records).most_common(5)}")
