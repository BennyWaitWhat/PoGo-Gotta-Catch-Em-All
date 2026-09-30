"""Deeper investigation: what makes 14/15/15 land at rank 635?

Pokemod displays UL635 (96.40%). The percentage matches mine, but rank doesn't.
Hypothesis 1: Pokemod uses a different SP calc that produces same %
Hypothesis 2: Pokemod uses a different rank calc (e.g., considers level fitting differently)
Hypothesis 3: PvPoke's rank uses *un-shadow* base stats differently
Hypothesis 4: Pokemod may show "hundo would be UL rank N" or something - unlikely
Hypothesis 5: Critical - maybe Pokemod uses a different stat-product algorithm
              like the OLD PvPoke formula (atk * def * sta / 10) where sta is unfloored
"""
import math
from collections import Counter

CPM = [
    0.094, 0.135137432, 0.16639787, 0.192650919, 0.21573247, 0.236572661,
    0.25572005, 0.273530381, 0.29024988, 0.306057377, 0.3210876, 0.335445036,
    0.34921268, 0.362457751, 0.37523559, 0.387592406, 0.39956728, 0.411193551,
    0.42250001, 0.432926419, 0.44310755, 0.4530599578, 0.46279839, 0.472336083,
    0.48168495, 0.4908558, 0.49985844, 0.508701765, 0.51739395, 0.525942511,
    0.53435433, 0.542635767, 0.55079269, 0.558830576, 0.56675452, 0.574569153,
    0.58227891, 0.589887907, 0.59740001, 0.604818814, 0.61215729, 0.619399365,
    0.62656713, 0.633644533, 0.64065295, 0.647576426, 0.65443563, 0.661214806,
    0.667934, 0.674577537, 0.68116492, 0.687680648, 0.69414365, 0.700538673,
    0.7068842, 0.713164996, 0.71939909, 0.725571552, 0.7317, 0.734741009,
    0.73776948, 0.740785574, 0.74378943, 0.746781211, 0.74976104, 0.752729087,
    0.7556855, 0.758630378, 0.76156384, 0.764486065, 0.76739717, 0.770297266,
    0.7731865, 0.776064962, 0.77893275, 0.781790055, 0.78463697, 0.787473578,
    0.79030001, 0.792803968, 0.79530001, 0.797800015, 0.8003, 0.802799995,
    0.8053, 0.807800014, 0.81029999, 0.812799985, 0.81529999, 0.81779999,
    0.82029998, 0.82279998, 0.82529997, 0.82779996, 0.83029996, 0.83279996,
    0.83529995, 0.83779995, 0.84029995, 0.84279995, 0.84529994
]

BA, BD, BS = 195, 162, 172
CAP = 2500
TARGET_IV = (14, 15, 15)

def compute_cp(ia, idf, ista, cpm):
    atk = (BA + ia) * cpm
    defe = (BD + idf) * cpm
    sta_raw = (BS + ista) * cpm
    return max(10, int(atk * math.sqrt(defe) * math.sqrt(sta_raw) / 10))

def find_max_level_idx(ia, idf, ista, cap):
    for i in range(len(CPM) - 1, -1, -1):
        if compute_cp(ia, idf, ista, CPM[i]) <= cap:
            return i
    return -1

# Try multiple stat product variants
def sp_floor(ia, idf, ista, cpm):
    """floor(sta) - PvPoke current"""
    atk = (BA + ia) * cpm
    defe = (BD + idf) * cpm
    sta = math.floor((BS + ista) * cpm)
    return atk * defe * sta

def sp_unfloor(ia, idf, ista, cpm):
    """no floor"""
    atk = (BA + ia) * cpm
    defe = (BD + idf) * cpm
    sta = (BS + ista) * cpm
    return atk * defe * sta

def sp_round_hp(ia, idf, ista, cpm):
    """round-half-down (Pokemon GO actually uses floor for HP)"""
    atk = (BA + ia) * cpm
    defe = (BD + idf) * cpm
    sta = math.floor((BS + ista) * cpm + 0.5)  # round
    return atk * defe * sta

def sp_floor_atk_def_too(ia, idf, ista, cpm):
    """Some formulas floor everything"""
    atk = math.floor((BA + ia) * cpm)
    defe = math.floor((BD + idf) * cpm)
    sta = math.floor((BS + ista) * cpm)
    return atk * defe * sta

def sp_int_hp_only(ia, idf, ista, cpm):
    """sta as int - same as floor for positive"""
    atk = (BA + ia) * cpm
    defe = (BD + idf) * cpm
    sta = int((BS + ista) * cpm)
    return atk * defe * sta

# For each variant, compute rank of target
variants = {
    'floor (current)': sp_floor,
    'no floor (raw)': sp_unfloor,
    'rounded HP': sp_round_hp,
    'floor everything': sp_floor_atk_def_too,
    'int hp only': sp_int_hp_only,
}

print("=" * 80)
print("STAT PRODUCT VARIANT TEST")
print("=" * 80)
for name, sp_fn in variants.items():
    results = []
    for a in range(16):
        for de in range(16):
            for s in range(16):
                idx = find_max_level_idx(a, de, s, CAP)
                if idx < 0:
                    sp = 0
                else:
                    sp = sp_fn(a, de, s, CPM[idx])
                results.append({'iv': (a, de, s), 'sp': sp})
    sr = sorted(results, key=lambda r: -r['sp'])
    max_sp = sr[0]['sp']
    for i, r in enumerate(sr):
        if r['iv'] == TARGET_IV:
            pct = r['sp']/max_sp*100 if max_sp else 0
            print(f"  {name:30s}: rank={i+1}, sp={r['sp']:.4f}, pct={pct:.4f}%")
            break

# Try level cap variants
print()
print("=" * 80)
print("LEVEL CAP VARIANT TEST (different max levels)")
print("=" * 80)
def find_max_level_idx_capped(ia, idf, ista, cap, max_idx):
    """Cap level at max_idx (e.g. level 50 = idx 98, level 51 = idx 100)"""
    upper = min(max_idx, len(CPM) - 1)
    for i in range(upper, -1, -1):
        if compute_cp(ia, idf, ista, CPM[i]) <= cap:
            return i
    return -1

# Default search uses index up to len(CPM)-1 = 100 (level 51).
# Maybe Pokemod caps at level 50 (idx 98)?
# Or 51 (idx 100)? Or does PvPoke cap at level 50 and Pokemod at level 51?
# PvPoke gamemaster has levelCap field - let me check
import json
with open('pvpoke_gamemaster.json') as f:
    gm = json.load(f)
print(f"PvPoke level caps: {gm.get('levelCaps', '(none)')}")
# Look for any level cap settings
keys = sorted(gm.keys())
print(f"GM keys: {keys[:30]}")

for max_lvl_idx in [80, 98, 100, 96]:  # idx 80 = lvl 41, 98=50, 100=51, 96=49
    results = []
    for a in range(16):
        for de in range(16):
            for s in range(16):
                idx = find_max_level_idx_capped(a, de, s, CAP, max_lvl_idx)
                if idx < 0:
                    sp = 0
                else:
                    sp = sp_floor(a, de, s, CPM[idx])
                results.append({'iv': (a, de, s), 'sp': sp})
    sr = sorted(results, key=lambda r: -r['sp'])
    max_sp = sr[0]['sp']
    for i, r in enumerate(sr):
        if r['iv'] == TARGET_IV:
            pct = r['sp']/max_sp*100 if max_sp else 0
            level = (find_max_level_idx_capped(*r['iv'], CAP, max_lvl_idx) * 0.5 + 1)
            print(f"  max_lvl_idx={max_lvl_idx} (lvl {max_lvl_idx*0.5+1}): rank={i+1}, sp={r['sp']:.4f}, pct={pct:.4f}%, target lvl={level}")
            break

# Hmm interesting let me also see what rank 635 looks like under each scheme
print()
print("Rank 635 in default scheme: (11, 15, 13) sp=3682236.14 pct=96.78%")
print("That's NOT 96.40%! So Pokemod isn't using the same algorithm as ours for all entries")

# Wait - maybe Pokemod uses level cap 50 (no XL candy)?
# That would change which IV combos rank highest because not all can hit 2500 at lvl 50
print()
print("=" * 80)
print("LEVEL CAP 50 (no XL): cap level at 50.0, max idx = 98")
print("=" * 80)
results_l50 = []
for a in range(16):
    for de in range(16):
        for s in range(16):
            idx = find_max_level_idx_capped(a, de, s, CAP, 98)  # level 50
            if idx < 0:
                sp = 0
                lvl = 0
                cp = 0
            else:
                sp = sp_floor(a, de, s, CPM[idx])
                lvl = idx * 0.5 + 1.0
                cp = compute_cp(a, de, s, CPM[idx])
            results_l50.append({'iv': (a, de, s), 'sp': sp, 'level': lvl, 'cp': cp})
sr_l50 = sorted(results_l50, key=lambda r: -r['sp'])
max_sp_l50 = sr_l50[0]['sp']
print(f"Max SP at L50: {max_sp_l50}")
for i, r in enumerate(sr_l50):
    if r['iv'] == TARGET_IV:
        pct = r['sp']/max_sp_l50*100 if max_sp_l50 else 0
        print(f"  Target rank: {i+1}, sp={r['sp']:.4f}, pct={pct:.4f}%, level={r['level']}, CP={r['cp']}")
        break

# Print rank 635 and target under L50 cap
print()
print("Rank 600-700 under L50 cap:")
for i in range(599, 700):
    r = sr_l50[i]
    pct = r['sp']/max_sp_l50*100
    marker = ' <-- TARGET' if r['iv'] == TARGET_IV else ''
    if i+1 in [625,630,634,635,636,640,645,650] or r['iv'] == TARGET_IV:
        print(f"  rank={i+1} iv={r['iv']} sp={r['sp']:.4f} pct={pct:.4f}% L{r['level']} CP{r['cp']}{marker}")

# Try level 51 (XL allowed)
print()
print("=" * 80)
print("LEVEL CAP 51 (XL allowed): cap level at 51.0, max idx = 100")
print("=" * 80)
results_l51 = []
for a in range(16):
    for de in range(16):
        for s in range(16):
            idx = find_max_level_idx_capped(a, de, s, CAP, 100)
            if idx < 0:
                sp = 0
                lvl = 0
                cp = 0
            else:
                sp = sp_floor(a, de, s, CPM[idx])
                lvl = idx * 0.5 + 1.0
                cp = compute_cp(a, de, s, CPM[idx])
            results_l51.append({'iv': (a, de, s), 'sp': sp, 'level': lvl, 'cp': cp})
sr_l51 = sorted(results_l51, key=lambda r: -r['sp'])
max_sp_l51 = sr_l51[0]['sp']
print(f"Max SP at L51: {max_sp_l51}")
for i, r in enumerate(sr_l51):
    if r['iv'] == TARGET_IV:
        pct = r['sp']/max_sp_l51*100 if max_sp_l51 else 0
        print(f"  Target rank: {i+1}, sp={r['sp']:.4f}, pct={pct:.4f}%, level={r['level']}, CP={r['cp']}")
        break
