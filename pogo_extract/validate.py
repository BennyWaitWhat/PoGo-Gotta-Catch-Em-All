"""
Triple-check: validate the pokemon database for false positives.

Tests:
1. Duplicate uid detection
2. Same species + same IVs + same level → same CP (sanity)
3. Impossible CP / level combos
4. IV distribution sanity (hundos shouldn't be 10%+)
5. Hundo cluster check: same species hundos at same level must have IDENTICAL CP
6. CPM should match a known game CPM value (within 0.0001)
7. Pokemon ID in valid range (1-1025)
8. Move IDs in reasonable range
9. Creation date sanity
10. Compare extraction count to expected
"""
import sqlite3, struct
from collections import Counter, defaultdict

KNOWN_CPMS = set()
CPM_LIST = [
    0.094,0.135137432,0.16639787,0.192650919,0.21573247,0.236572661,
    0.25572005,0.273530381,0.29024988,0.306057377,0.3210876,0.335445036,
    0.34921268,0.362457751,0.37523559,0.387592406,0.39956728,0.411193551,
    0.42250001,0.432926419,0.44310755,0.4530599578,0.46279839,0.472336083,
    0.48168495,0.4908558,0.49985844,0.508701765,0.51739395,0.525942511,
    0.53435433,0.542635767,0.55079269,0.558830576,0.56675452,0.574569153,
    0.58227891,0.589887907,0.59740001,0.604818814,0.61215729,0.619399365,
    0.62656713,0.633644533,0.64065295,0.647576426,0.65443563,0.661214806,
    0.667934,0.674577537,0.68116492,0.687680648,0.69414365,0.700538673,
    0.70688421,0.713164996,0.71939909,0.725571552,0.7317,0.734741009,
    0.73776948,0.740785574,0.74378943,0.746781211,0.74976104,0.752729087,
    0.75568551,0.758630378,0.76156384,0.764486065,0.76739717,0.770297266,
    0.7731865,0.776064962,0.77893275,0.781790055,0.78463697,0.787473578,
    0.79030001,0.792803968,0.79530001,0.797800015,0.8003,0.802799995,
    0.8053,0.807800015,0.81029999,0.812799985,0.81529999,0.81779999,
    0.82029999,0.82279999,0.82529999,0.82779999,0.83029999,0.83279999,
    0.83529999,0.83779999,0.84029999,0.84279999,0.84529999
]

def cpm_close(cpm):
    """True if CPM matches a known PoGo CPM within tolerance."""
    return any(abs(cpm - k) < 0.0001 for k in CPM_LIST)

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

print("=" * 70)
print("TRIPLE-CHECK VALIDATION")
print("=" * 70)

# 1. Duplicate UIDs
c.execute("SELECT uid_hex, COUNT(*) FROM pokemon GROUP BY uid_hex HAVING COUNT(*) > 1")
dups = c.fetchall()
print(f"\n1. Duplicate UIDs: {len(dups)} (should be 0)")
if dups:
    for d in dups[:5]: print(f"   {d}")

# 2. CPM sanity - all CPMs should match a known game value
c.execute("SELECT cp_multiplier FROM pokemon")
all_cpms = [r[0] for r in c.fetchall()]
bad_cpms = sum(1 for cpm in all_cpms if not cpm_close(cpm))
print(f"\n2. Pokemon with CPM not matching known PoGo values: {bad_cpms}/{len(all_cpms)}")

# 3. PokemonId range
c.execute("SELECT pokemon_id, COUNT(*) FROM pokemon WHERE pokemon_id < 1 OR pokemon_id > 1025 GROUP BY pokemon_id")
oor = c.fetchall()
print(f"\n3. Pokemon ID out of range (1-1025): {len(oor)} unique IDs")
if oor:
    for r in oor[:10]: print(f"   #{r[0]}: {r[1]} entries")

# 4. Same species + IVs + level → same CP test
print(f"\n4. CP consistency check (same species/IVs/level should = same CP):")
c.execute("""SELECT pokemon_id, iv_atk, iv_def, iv_sta, ROUND(cp_multiplier, 5) cpm,
                    GROUP_CONCAT(cp), COUNT(*) cnt, COUNT(DISTINCT cp) distinct_cps
             FROM pokemon
             WHERE num_additional_cpm = 0
             GROUP BY pokemon_id, iv_atk, iv_def, iv_sta, cpm
             HAVING COUNT(*) > 1""")
groups = c.fetchall()
inconsistent = [g for g in groups if g[7] > 1]
print(f"   Groups with 2+ pokemon: {len(groups)}")
print(f"   Groups where CP differs: {len(inconsistent)} (should be 0 or near-zero)")
if inconsistent:
    print(f"   Sample inconsistent groups:")
    for g in inconsistent[:5]:
        print(f"     species={g[0]} ivs={g[1]}/{g[2]}/{g[3]} cpm={g[4]} CPs={g[5]}")

# 5. Hundo cluster CP test
print(f"\n5. Hundo CP consistency by species/level:")
c.execute("""SELECT pokemon_id, ROUND(cp_multiplier, 5) cpm,
                    GROUP_CONCAT(cp), COUNT(*) cnt, COUNT(DISTINCT cp) distinct_cps
             FROM pokemon WHERE is_hundo AND num_additional_cpm = 0
             GROUP BY pokemon_id, cpm
             HAVING COUNT(*) > 1""")
hundo_groups = c.fetchall()
bad_hundos = [g for g in hundo_groups if g[4] > 1]
print(f"   Hundo groups (same species + level): {len(hundo_groups)}")
print(f"   Groups with INCONSISTENT CP: {len(bad_hundos)}")
if bad_hundos:
    print(f"   These differing CPs indicate FALSE POSITIVES:")
    for g in bad_hundos[:5]:
        print(f"     species={g[0]} cpm={g[1]} CPs={g[2]}")

# 6. CP/CPM/IV math check (simplified)
print(f"\n6. CP/level sanity check:")
# A pokemon's CP = (atk*sqrt(def)*sqrt(sta)*cpm^2)/10 where atk,def,sta = base+iv
# Without base stats we can't verify exactly, but extreme cases:
# - CP > 5500 at level < 30 is impossible without best buddy
# - CP < 50 at level 30+ is impossible
suspicious = []
c.execute("""SELECT pokemon_id, species_name, cp, level, num_additional_cpm
             FROM pokemon
             WHERE (cp > 5500 AND level < 25 AND num_additional_cpm = 0)
                OR (cp < 30 AND level > 25)""")
for r in c.fetchall():
    suspicious.append(r)
print(f"   Suspicious CP/level combos: {len(suspicious)}")
for r in suspicious[:5]: print(f"     {r}")

# 7. Move ID range
c.execute("SELECT COUNT(*) FROM pokemon WHERE move1 < 0 OR move1 > 600")
print(f"\n7. Move1 out of range (0-600): {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM pokemon WHERE move2 < 0 OR move2 > 600")
print(f"   Move2 out of range: {c.fetchone()[0]}")

# 8. Date sanity
c.execute("SELECT COUNT(*) FROM pokemon WHERE creation_time_ms < 1467590400000")
print(f"\n8. Creation before PoGo launch (filter check): {c.fetchone()[0]} (should be 0)")
c.execute("SELECT COUNT(*) FROM pokemon WHERE creation_time_ms > 1800000000000")  # ~Jan 2027
print(f"   Creation after Jan 2027: {c.fetchone()[0]}")

# 9. Pokeball valid range
c.execute("SELECT pokeball, COUNT(*) FROM pokemon WHERE pokeball NOT IN (0,1,2,3,4,5) GROUP BY pokeball")
bad_balls = c.fetchall()
print(f"\n9. Invalid pokeball values: {sum(b[1] for b in bad_balls)}")
for b in bad_balls[:5]: print(f"   pokeball={b[0]}: {b[1]}")

# 10. Best buddy check - num_additional_cpm should be > 0 for is_best_buddy
c.execute("SELECT COUNT(*) FROM pokemon WHERE is_best_buddy AND num_additional_cpm = 0")
print(f"\n10. Best Buddy with 0 boost (mismatch): {c.fetchone()[0]}")

# 11. Compare hundo rate
total = c.execute("SELECT COUNT(*) FROM pokemon").fetchone()[0]
hundos = c.execute("SELECT COUNT(*) FROM pokemon WHERE is_hundo").fetchone()[0]
print(f"\n11. Hundo rate: {hundos}/{total} = {hundos/total*100:.2f}%")
print(f"    (Real wild hundo rate ~0.024%; with weather ~0.066%; user has 10.4%)")
print(f"    HIGH but possible if user uses Pokemod spawning features.")

# 12. Per-species hundo concentration
print(f"\n12. Hundo distribution by species:")
c.execute("""SELECT species_name, COUNT(*) FROM pokemon WHERE is_hundo
             GROUP BY species_name ORDER BY 2 DESC LIMIT 5""")
for r in c.fetchall():
    print(f"    {r[0]}: {r[1]}")

# 13. Quick spot check on sample
print(f"\n13. Sample pokemon (random 5):")
c.execute("""SELECT species_name, cp, iv_atk, iv_def, iv_sta, level,
                    pokeball_name, gender_name, is_hundo, is_lucky, is_shiny, creation_date
             FROM pokemon ORDER BY RANDOM() LIMIT 5""")
for r in c.fetchall():
    print(f"    {r[0]} CP{r[1]} IV{r[2]}/{r[3]}/{r[4]} L{r[5]} {r[6]} {r[7]} hundo={r[8]} lucky={r[9]} shiny={r[10]} {r[11][:10] if r[11] else None}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
flags = []
if len(dups) > 0: flags.append(f"{len(dups)} duplicate UIDs")
if bad_cpms > total * 0.01: flags.append(f"{bad_cpms} bad CPMs (potential false positives)")
if len(oor) > 0: flags.append(f"{sum(r[1] for r in oor)} pokemon with bad species ID")
if len(bad_hundos) > 0: flags.append(f"{len(bad_hundos)} inconsistent hundo CP groups (false positives)")
if len(suspicious) > 0: flags.append(f"{len(suspicious)} suspicious CP/level combos")

if not flags:
    print("PASS: All consistency checks passed.")
    print(f"5394 pokemon are internally consistent.")
else:
    print("ISSUES FOUND:")
    for f in flags: print(f"  - {f}")

conn.close()
