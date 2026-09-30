"""Final verification of remaining candidates."""
import json, struct, sqlite3, math
from collections import Counter, defaultdict

data = json.load(open('pokemon_v3.json'))
db = sqlite3.connect('pokemon.db')
c = db.cursor()

c.execute('SELECT uid_hex, pokemon_id, species_name, is_traded, is_lucky, is_hatched_from_egg, is_best_buddy, '
          'level, alignment, alignment_name, costume, original_owner, special_bg_id, location_bg_id, cp '
          'FROM pokemon')
known = {row[0]: row for row in c.fetchall()}

paired = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) < 1000: continue
    bs = bytes.fromhex(raw)
    uid_int = struct.unpack_from('<Q', bs, 32)[0]
    uid_hex = f'{uid_int:016x}'
    if uid_hex not in known: continue
    paired.append((bs, known[uid_hex]))

# === 196 + 200 + 144 - what's their relationship to buddy/levels ===
print('=== Offset 196 / 200 / 144 sample correlation ===')
print('  PID    Species             L     CP    BB  144     196   200(km)')
samples = []
for bs, k in paired:
    v144 = struct.unpack_from('<i', bs, 144)[0]
    v196 = struct.unpack_from('<i', bs, 196)[0]
    v200 = struct.unpack_from('<f', bs, 200)[0]
    if v200 != 0 and not math.isnan(v200):
        samples.append((k[1], k[2], k[7], k[14], k[6], v144, v196, v200))

# Show top 20 by buddy_km
for pid, sp, lvl, cp, bb, v144, v196, v200 in sorted(samples, key=lambda x: -x[7])[:25]:
    bbm = '*' if bb else ' '
    print(f'  {pid:4d}  {sp[:18]:18s}  {lvl or 0:5.1f} {cp:5d} {bbm} {v144:5d}   {v196:4d}   {v200:8.2f}')

# So 200 is buddy_km, 196 is small ints (powered up?), 144 is bigger numbers (max 4003)
# 196 max=198 - could be "candy_fed_count" (max ~200 berries to reach Best Buddy)
# 144 max=4003 - looks like accumulated buddy hearts? "buddy_score"? or stardust*100?

# ACTUALLY: PoGo records "best_buddy_level" 1-4 (Good/Great/Ultra/Best)
# But 144 is too varied - it must be a counter, not an enum

# Let me check 196 vs 200 ratio and 144
# In PoGo:
# - buddyKmWalked_ = float, accumulated km with this pokemon as buddy
# - hearts/candy_fed_count = int, hearts earned today
# - buddy_walked_mega_energy_award = total energy awarded for mega energy
# - num_powered_up = total times user pressed power-up button

# Try: maybe 144 = numUpgrades / numPoweredUp; max ~250 expected
# But 4003 max - too high for that.

# Maybe 144 = numerical "score" from gameplay (battles won? challenges?)

# WAIT - I just realized: 144 has 304 entries, but max is 4003. The bigger values are all
# best buddies that are heavily power-leveled. If user power-leveled a Kyurem from level 1
# to level 50, that's 100+ power-ups. 4003 doesn't match power-ups.

# Stardust spent? Level 1->50 with shiny legendary = ~4M stardust. 4003 is too low.
# Walks? 4003 walks could be 4k km of walks (1 walk = 1 km segment).

# Actually let me check: candy_x_le awarded -> hearts
# If user has been buddy with Kyurem 4003 days... yeah that's not it either.

# Let me see if 144 == 196 * X
print('\n=== Relationship 144 to 196 ===')
for bs, k in paired:
    v144 = struct.unpack_from('<i', bs, 144)[0]
    v196 = struct.unpack_from('<i', bs, 196)[0]
    if v144 > 0 and v196 > 0:
        ratio = v144 / v196
        if ratio > 1:
            pass

# Check 196 vs 144 strongly correlated?
both_nz = [(struct.unpack_from('<i', bs, 144)[0], struct.unpack_from('<i', bs, 196)[0]) for bs, k in paired
           if struct.unpack_from('<i', bs, 144)[0] != 0 and struct.unpack_from('<i', bs, 196)[0] != 0]
print(f'  Both nz: {len(both_nz)}')
print(f'  Sample (v144, v196):')
for v144, v196 in both_nz[:20]:
    print(f'    144={v144:5d}  196={v196:3d}  ratio={v144/v196:.2f}')

# === Look at what matches best_buddy=232 ===
# We have 609 num_additional_cpm > 0 in DB - that's "best buddy active boost"
# 232 should be the actual count of best buddies (BB level 4, Affection level 4)
# Look for offset where 232 pokemon match
print('\n=== Looking for best_buddy_level=4 (232 pokemon) ===')
for off in range(0, 512, 4):
    cnt = sum(1 for bs, k in paired if struct.unpack_from('<i', bs, off)[0] == 4)
    if 220 < cnt < 250:
        # Sample
        ex = []
        for bs, k in paired:
            if struct.unpack_from('<i', bs, off)[0] == 4:
                ex.append(k[2])
                if len(ex) >= 5: break
        print(f'  +{off} == 4: {cnt} matches. Samples: {ex}')

# Check byte 4 too
print('  Byte=4 candidates:')
for off in range(0, 512):
    cnt = sum(1 for bs, k in paired if bs[off] == 4)
    if 220 < cnt < 250:
        print(f'  byte +{off} == 4: {cnt}')

# Maybe best_buddy_level is at the same offset as alignment in display - we know
# that's at +36 in display. Best buddy might also be in display proto.
# Or it could be at a small int offset where 232 of them have value 4

# Check offset 268 area where the 119/120 found - smaller fields
# For traded: 268 is upper half of i64 264 (already mapped)

# === DEPLOYMENT FORT search ===
# 1 pokemon has deployed_fort. Check which offset relates
# We have str at 0x40 = deployed_fort, 0xb8 = nickname, 0x100 = original_owner
# Already covered

# === FINAL: let me check 0x168 and 0x180 strings (always empty) ===
# These are STRING POINTERS that always point to empty string
# Offset 0x168 = 360 decimal, 0x180 = 384 decimal
# At those offsets in raw_proto: probably more string fields
# Already shown 0 with content - they're all empty for our user

# === FINAL: 196 = maybe `numUpgradesByCharacter` but values look like num_power_ups
# (Hubbard's max 200). Let me check: PoGo wiki says max ~200 power-ups from L1 to L51
print('\n=== Offset 196 max distribution by level ===')
by_lvl = defaultdict(list)
for bs, k in paired:
    v = struct.unpack_from('<i', bs, 196)[0]
    if v != 0 and k[7]:
        by_lvl[k[7]].append(v)

for lvl in sorted(by_lvl):
    if len(by_lvl[lvl]) > 0:
        print(f'  L{lvl}: max={max(by_lvl[lvl])}, samples={by_lvl[lvl][:3]}')

# === Confirmed buddy_km at 200; what about offset 196 and 144?
# 196 max=198, count=121
# 200 is buddy_km - distance walked together
# 196 might be "num_buddy_walks" (one per km, but max 198 fits)
# 144 might be cumulative stardust? Or candy?

# Since 196 max ~ 200 ~ km of walking, 196 might literally be int buddy distance (but truncated?)
# Or 196 = "buddy_personality_score"

# Show 196 vs 200 (buddy_km) per pokemon:
print('\n=== 196 vs 200 side-by-side (top buddies) ===')
print('  Species              196   200(km)  ratio  level')
for bs, k in paired:
    v196 = struct.unpack_from('<i', bs, 196)[0]
    v200 = struct.unpack_from('<f', bs, 200)[0]
    if v196 > 5 and v200 > 1:
        ratio = v200 / v196 if v196 > 0 else 0
        print(f'  {k[2][:20]:20s}  {v196:3d}    {v200:7.2f}   {ratio:5.2f}   L{k[7]}')

# Now look more closely at offset 144 - max 4003.
# 4003 / Kyurem -> could be related to power-up count but very excessive
# Let me see: PoGo "stardust_spent" lifetime - tracked?
# Actually... it could be INCREMENTAL HP healed during battles? Or candy fed.

# Total candy fed is per pokemon-line, not per individual pokemon. So that's out.

# Hmm. The values fit a pattern of power-leveling:
# - L1 to L50 takes 250+ power-ups
# - Kyurem is the user's most-leveled pokemon at 4003 - that's WAY more than power-ups
# - But it could be "total_xp_gained_from_pokemon" or "total_hearts_with_buddy"

# In PoGo, you can earn up to 30 hearts per day with your buddy.
# If user has had Kyurem as buddy for ~133 days (4003/30 = 133), that's plausible

# Offset 144 might be `numHeartsAwarded` or `buddyHearts` cumulative
# 4003 / 30 = 134 days of buddy walking. Plausible for top buddy.

# === Check offset 348 (mega_extra_cpm = 1.0) and 352 (cpm-like) ===
print('\n=== 348/352 detailed ===')
for bs, k in paired[:50]:
    v336 = bs[336]
    v340 = bs[340]
    v344 = struct.unpack_from('<i', bs, 344)[0]
    v348 = struct.unpack_from('<f', bs, 348)[0]
    v352 = struct.unpack_from('<f', bs, 352)[0]
    if v336 == 1:
        # Calculate mega level from 352 (cpm)
        from build_final import cpm_to_level, CPM_TABLE
        lvl_from_352 = cpm_to_level(v352)
        print(f'  PID {k[1]} {k[2]} CP={k[14]} L={k[7]}: mega_byte={v336}, val_340={v340}, mega_cp={v344}, cpm_a={v348:.4f}, cpm_b={v352:.4f} (lvl from cpm_b: {lvl_from_352})')
