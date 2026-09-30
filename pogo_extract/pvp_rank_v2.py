"""Compute GL/UL ranks using PvPoke's authoritative gamemaster data.

Pokemod uses the same algorithm. Map our pokemon to PvPoke speciesId, compute rank
including evolution-final-form rank for stages that aren't fully evolved.
"""
import json, sqlite3, math

with open('pvpoke_gamemaster.json') as f:
    gm = json.load(f)

# Build pokemon lookup by speciesId
pokemon_db = {p['speciesId']: p for p in gm['pokemon']}

# Build species name + form -> speciesId mapping
# PvPoke speciesId format: lowercase, e.g. 'feraligatr', 'meowth_galarian', 'charizard'
def to_species_id(species_name, form_code):
    """Map (species_name, form_code) -> PvPoke speciesId guess. Fallback to base name."""
    base = species_name.lower().replace(' ', '_').replace("'", "").replace('.', '').replace('-', '_')
    base = base.replace('é', 'e')  # Flabébé
    return base

# Common form name mappings (manually curated for forms in our data)
FORM_OVERRIDES = {
    # Galarian/Alolan/Hisuian/Paldean variants
    ('Meowth', 2335): 'meowth_galarian',
    ('Meowth', 64):   'meowth_alolan',
    ('Persian', 66):  'persian_alolan',
    ('Vulpix', 56):   'vulpix_alolan',
    ('Ninetales', 58): 'ninetales_alolan',
    ('Sandshrew', 52): 'sandshrew_alolan',
    ('Sandslash', 54): 'sandslash_alolan',
    ('Diglett', 60):  'diglett_alolan',
    ('Dugtrio', 62):  'dugtrio_alolan',
    ('Geodude', 68):  'geodude_alolan',
    ('Graveler', 70): 'graveler_alolan',
    ('Golem', 72):    'golem_alolan',
    ('Grimer', 74):   'grimer_alolan',
    ('Muk', 76):      'muk_alolan',
    ('Exeggutor', 78): 'exeggutor_alolan',
    ('Marowak', 80):  'marowak_alolan',
    ('Rattata', 46):  'rattata_alolan',
    ('Raticate', 48): 'raticate_alolan',
    ('Raichu', 50):   'raichu_alolan',
    ('Arcanine', 2793): 'arcanine_hisuian',
    ('Avalugg', 2795): 'avalugg_hisuian',
    ('Typhlosion', 2786): 'typhlosion_hisuian',
    ('Growlithe', 2792): 'growlithe_hisuian',
    ('Voltorb', 2728): 'voltorb_hisuian',
    ('Electrode', 2735): 'electrode_hisuian',
    ('Slowpoke', 2582): 'slowpoke_galarian',
    ('Slowbro', 2583): 'slowbro_galarian',
    ('Ponyta', 2336): 'ponyta_galarian',
    ('Rapidash', 2337): 'rapidash_galarian',
    ('Farfetch\'d', 2338): 'farfetchd_galarian',
    ('Mr. Mime', 2339): 'mr_mime_galarian',
    ('Darumaka', 2341): 'darumaka_galarian',
    ('Darmanitan', 2342): 'darmanitan_galarian_standard',
    ('Stunfisk', 2345): 'stunfisk_galarian',
    ('Tauros', 1086): 'tauros_combat',
    ('Tauros', 3008): 'tauros_blaze',
    ('Lapras', 322): 'lapras',
    ('Pikachu', 598): 'pikachu',
    ('Snorlax', 199): 'snorlax',
    ('Eevee', 1092): 'eevee',
    ('Magikarp', 253): 'magikarp',
    ('Gyarados', 256): 'gyarados',
}

def get_speciesid(species_name, form_code):
    if (species_name, form_code) in FORM_OVERRIDES:
        return FORM_OVERRIDES[(species_name, form_code)]
    return to_species_id(species_name, form_code)

# CPM
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

def compute_cp(ba, bd, bs, ia, idf, ista, cpm, shadow=False):
    atk_mult = 1.2 if shadow else 1.0
    def_mult = 5/6 if shadow else 1.0
    atk = (ba + ia) * cpm * atk_mult
    defe = (bd + idf) * cpm * def_mult
    sta_raw = (bs + ista) * cpm
    return max(10, int(atk * math.sqrt(defe) * math.sqrt(sta_raw) / 10))

def stat_product(ba, bd, bs, ia, idf, ista, cpm, shadow=False):
    atk_mult = 1.2 if shadow else 1.0
    def_mult = 5/6 if shadow else 1.0
    atk = (ba + ia) * cpm * atk_mult
    defe = (bd + idf) * cpm * def_mult
    sta = math.floor((bs + ista) * cpm)
    return atk * defe * sta

def find_max_level_idx(ba, bd, bs, ia, idf, ista, cap, shadow=False):
    for i in range(len(CPM) - 1, -1, -1):
        if compute_cp(ba, bd, bs, ia, idf, ista, CPM[i], shadow) <= cap:
            return i
    return -1

def compute_rank(species_id, ia, idf, ista, cap, shadow=False):
    p = pokemon_db.get(species_id)
    if not p: return None
    bs = p['baseStats']
    ba, bd, hp = bs['atk'], bs['def'], bs['hp']
    target_idx = find_max_level_idx(ba, bd, hp, ia, idf, ista, cap, shadow)
    if target_idx < 0: return None
    target_sp = stat_product(ba, bd, hp, ia, idf, ista, CPM[target_idx], shadow)

    # Compute SP for all 4096 IV combos
    all_sp = []
    for a in range(16):
        for de in range(16):
            for s in range(16):
                idx = find_max_level_idx(ba, bd, hp, a, de, s, cap, shadow)
                if idx < 0:
                    all_sp.append(0)
                    continue
                sp = stat_product(ba, bd, hp, a, de, s, CPM[idx], shadow)
                all_sp.append(sp)
    all_sp_sorted = sorted(all_sp, reverse=True)
    max_sp = all_sp_sorted[0] if all_sp_sorted else 1

    # Find rank of target IVs (binary search by index)
    target_idx_in_combos = ia * 256 + idf * 16 + ista
    target_sp_v = all_sp[target_idx_in_combos]
    rank = all_sp_sorted.index(target_sp_v) + 1
    pct = target_sp_v / max_sp * 100 if max_sp else 0
    level = target_idx * 0.5 + 1.0
    return {'rank': rank, 'sp': target_sp_v, 'level': level, 'pct': pct}

def get_evolutions(species_id):
    """Get list of all evolution stages from current onward. Recurses into family.evolutions."""
    p = pokemon_db.get(species_id)
    if not p: return [species_id]
    chain = [species_id]
    family = p.get('family', {})
    evos = family.get('evolutions', [])
    for evo in evos:
        if evo not in chain:
            chain.append(evo)
            sub = get_evolutions(evo)
            for s in sub[1:]:
                if s not in chain: chain.append(s)
    return chain

# Process test pokemon
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
rows = c.execute("""SELECT uid_hex, species_name, pokemon_id, form, fresh_costume, cp,
    iv_atk, iv_def, iv_sta, iv_pct, level, fresh_alignment
    FROM pokemon WHERE in_bag=1 AND auth_tag_names LIKE '%test%'""").fetchall()

print(f"=== {len(rows)} test pokemon — recomputed with PvPoke base stats + evolutions ===\n")
for r in rows:
    uid, sp, pid, form, cost, cp, ia, idf, ista, iv_pct, lvl, align = r
    shadow = (align == 1)
    sid = get_speciesid(sp, form or 0)
    chain = get_evolutions(sid)
    sh = ' [SHADOW]' if shadow else ''
    print(f"  {sp} {ia}/{idf}/{ista} CP{cp} L{lvl:.1f}{sh}  -> chain: {chain}")
    for stage_id in chain:
        gl = compute_rank(stage_id, ia, idf, ista, 1500, shadow)
        ul = compute_rank(stage_id, ia, idf, ista, 2500, shadow)
        gl_str = f"GL{gl['rank']}({gl['pct']:.2f}%)" if gl else "GL-"
        ul_str = f"UL{ul['rank']}({ul['pct']:.2f}%)" if ul else "UL-"
        print(f"    {stage_id:30s}: {gl_str}  {ul_str}")
    print()
