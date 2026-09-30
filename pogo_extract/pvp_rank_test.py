"""Compute GL/UL rank for the 13 test pokemon. Compare against Pokemod UI.

Standard PvP IV ranking algorithm:
1. For each pokemon, find max level where CP <= cap
2. Compute stat product = atk_eff * def_eff * floor(sta_eff)
3. Compare to all 4096 IV combos for the same species
4. Rank by stat product desc
"""
import sqlite3, math

# CPM table from PoGo
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
# Index 0 = level 1.0, 1 = 1.5, ... 100 = 51.0

# Base stats from PoGo GameMaster - hardcoded for the 13 test pokemon's species/forms
# Format: (base_atk, base_def, base_sta)
BASE_STATS = {
    # (pokemon_id, form): (atk, def, sta)
    (160, 0):    (205, 197, 198),  # Feraligatr
    ( 59, 283):  (227, 158, 180),  # Arcanine f283 (default form)
    (713, 0):    (178, 246, 216),  # Avalugg default
    (713, 2795): (178, 246, 216),  # Avalugg Hisuian form
    (  6, 178):  (223, 173, 186),  # Charizard f178
    (  4, 172):  (116,  96, 118),  # Charmander f172
    (157, 2786): (223, 173, 186),  # Typhlosion Hisuian (same stats as regular per PoGo)
    (282, 298):  (237, 195, 169),  # Gardevoir f298
    ( 21, 971):  (102,  78, 120),  # Spearow f971
    (462, 661):  (238, 205, 172),  # Magnezone f661
    ( 52, 2335): (115,  91, 137),  # Meowth Galarian f2335
}

# Note: Hisuian Typhlosion has different stats actually
BASE_STATS[(157, 2786)] = (210, 178, 169)  # Hisuian Typhlosion

def compute_cp(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cpm):
    """Compute CP at given CPM. Returns floor."""
    atk = (base_atk + iv_atk) * cpm
    defe = (base_def + iv_def) * cpm
    sta = (base_sta + iv_sta) * cpm
    cp = max(10, int(atk * math.sqrt(defe) * math.sqrt(sta) / 10))
    return cp

def compute_stat_product(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cpm, shadow=False, purified=False):
    """Compute stat product at given CPM."""
    atk_mult = 1.2 if shadow else 1.0
    def_mult = 5/6 if shadow else 1.0
    atk = (base_atk + iv_atk) * cpm * atk_mult
    defe = (base_def + iv_def) * cpm * def_mult
    sta = math.floor((base_sta + iv_sta) * cpm)
    return atk * defe * sta

def find_max_level_under_cap(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cap, shadow=False):
    """Find highest CPM index such that CP <= cap."""
    atk_mult = 1.2 if shadow else 1.0
    def_mult = 5/6 if shadow else 1.0
    # Binary search
    best = -1
    for i in range(len(CPM) - 1, -1, -1):
        cpm = CPM[i]
        atk = (base_atk + iv_atk) * cpm * atk_mult
        defe = (base_def + iv_def) * cpm * def_mult
        sta_raw = (base_sta + iv_sta) * cpm  # CP uses raw sta, not floored
        cp = max(10, int(atk * math.sqrt(defe) * math.sqrt(sta_raw) / 10))
        if cp <= cap:
            best = i
            break
    return best

def get_stat_product_at_cap(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cap, shadow=False, max_level_idx=100):
    """Find max level under cap, return stat product."""
    idx = find_max_level_under_cap(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cap, shadow)
    if idx < 0: return 0
    if idx > max_level_idx: idx = max_level_idx
    cpm = CPM[idx]
    return compute_stat_product(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cpm, shadow=shadow), idx

def compute_rank(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cap, shadow=False, max_level_idx=100):
    """Compute rank (1-4096) by stat product among all IV combos."""
    target_sp, target_idx = get_stat_product_at_cap(base_atk, base_def, base_sta, iv_atk, iv_def, iv_sta, cap, shadow, max_level_idx)

    # Compute SP for all IV combos
    all_sp = []
    for a in range(16):
        for de in range(16):
            for s in range(16):
                sp, idx = get_stat_product_at_cap(base_atk, base_def, base_sta, a, de, s, cap, shadow, max_level_idx)
                all_sp.append((sp, a, de, s, idx))
    all_sp.sort(key=lambda x: -x[0])

    # Find rank of target IVs
    target_key = (iv_atk, iv_def, iv_sta)
    for i, (sp, a, de, s, idx) in enumerate(all_sp):
        if (a, de, s) == target_key:
            level = idx * 0.5 + 1.0
            return {'rank': i+1, 'sp': sp, 'level': level, 'percent': sp / all_sp[0][0] * 100 if all_sp[0][0] else 0}
    return {'rank': -1, 'sp': 0}

# Process test tag pokemon
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
rows = c.execute("""SELECT uid_hex, species_name, pokemon_id, form, fresh_costume, cp,
    iv_atk, iv_def, iv_sta, iv_pct, level, fresh_alignment, is_powered_up
    FROM pokemon WHERE in_bag=1 AND auth_tag_names LIKE '%test%'""").fetchall()

print(f"=== {len(rows)} test pokemon — computed GL/UL ranks ===\n")
print(f"{'Species':16s} {'IVs':>10s}  {'CP':>5s}  L      GL  Rank   UL  Rank")
print('-' * 90)
for r in rows:
    uid, sp, pid, form, cost, cp, ia, idf, ista, iv_pct, lvl, align, powered = r
    key = (pid, form or 0)
    if key not in BASE_STATS:
        # Try without form
        key = (pid, 0)
    if key not in BASE_STATS:
        print(f"  {sp:14s} {ia}/{idf}/{ista}  CP{cp}  - NO BASE STATS")
        continue
    ba, bd, bs = BASE_STATS[key]
    shadow = (align == 1)
    # GL = 1500 cap
    gl = compute_rank(ba, bd, bs, ia, idf, ista, 1500, shadow=shadow)
    # UL = 2500 cap
    ul = compute_rank(ba, bd, bs, ia, idf, ista, 2500, shadow=shadow)
    sh = ' [SHADOW]' if shadow else ''
    print(f"  {sp:14s} {ia:>2}/{idf:>2}/{ista:>2}  CP{cp:>5} L{lvl:>4.1f}{sh}")
    print(f"    GL: rank #{gl['rank']:>4}/4096  CP@{gl.get('level',0):.1f}  SP={gl.get('sp',0):.0f}  ({gl.get('percent',0):.2f}%)")
    print(f"    UL: rank #{ul['rank']:>4}/4096  CP@{ul.get('level',0):.1f}  SP={ul.get('sp',0):.0f}  ({ul.get('percent',0):.2f}%)")
    print()
