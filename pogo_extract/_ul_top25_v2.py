"""For each PVPoke UL top 25, surface ALL relevant specimens the user owns:
  1) rank-1 IV match (PVPoke optimal)
  2) near-perfect (rank ≤ 50, still >99% stat product)
  3) hundo if any (suboptimal IV but maxed potential)

For each, tell met/needs-powerup against the target level."""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

MOVES = {int(k): v for k, v in json.load(open('move_id_to_name.json')).items()}
def pretty(m):
    if not m: return ''
    return MOVES.get(m, '').replace('_FAST', '').replace('_', ' ').title().replace('Of', 'of').replace('The', 'the')

# PVPoke UL top 25, in rank order
ul = [
    (1,  'Jellicent',          "species_name='Jellicent' AND fresh_alignment IN (0,2)",            95.5, 47.5),
    (2,  'Corviknight',        "species_name='Corviknight' AND fresh_alignment IN (0,2)",          95.4, 47.0),
    (3,  'Lapras',             "species_name='Lapras' AND fresh_alignment IN (0,2)",               95.4, 40.5),
    (4,  'Lapras Shadow',      "species_name='Lapras' AND fresh_alignment=1",                       95.0, 40.5),
    (5,  'Tinkaton',           "species_name='Tinkaton' AND fresh_alignment IN (0,2)",             94.9, 50.0),
    (6,  'Empoleon',           "species_name='Empoleon' AND fresh_alignment IN (0,2)",             94.4, 33.0),
    (7,  'Moltres Galarian',   "species_name='Moltres' AND form NOT IN (0,53)",                     94.3, 29.5),
    (8,  'Empoleon Shadow',    "species_name='Empoleon' AND fresh_alignment=1",                     94.2, 33.0),
    (9,  'Feraligatr Shadow',  "species_name='Feraligatr' AND fresh_alignment=1",                   93.9, 35.0),
    (10, 'Malamar Shadow',     "species_name='Malamar' AND fresh_alignment=1",                      93.3, 50.0),
    (11, 'Florges',            "species_name='Florges' AND fresh_alignment IN (0,2)",              93.2, 28.5),
    (12, 'Feraligatr',         "species_name='Feraligatr' AND fresh_alignment IN (0,2)",           93.1, 35.0),
    (13, 'Dondozo',            "species_name='Dondozo' AND fresh_alignment IN (0,2)",              93.0, 32.0),
    (14, 'Virizion',           "species_name='Virizion' AND fresh_alignment IN (0,2)",             92.7, 31.0),
    (15, 'Regidrago',          "species_name='Regidrago' AND fresh_alignment IN (0,2)",            92.5, 32.5),
    (16, 'Lickilicky',         "species_name='Lickilicky' AND fresh_alignment IN (0,2)",           92.3, 47.0),
    (17, 'Ludicolo',           "species_name='Ludicolo' AND fresh_alignment IN (0,2)",             92.3, 47.5),
    (18, 'Clefable',           "species_name='Clefable' AND fresh_alignment IN (0,2)",             92.1, 47.5),
    (19, 'Blastoise',          "species_name='Blastoise' AND fresh_alignment IN (0,2)",            91.7, 45.5),
    (20, 'Oranguru',           "species_name='Oranguru' AND fresh_alignment IN (0,2)",             91.7, 47.0),
    (21, 'Zygarde Complete',   "species_name='Zygarde'",                                            91.5, 24.0),
    (22, 'Malamar',            "species_name='Malamar' AND fresh_alignment IN (0,2)",              91.4, 50.0),
    (23, 'Dusknoir Shadow',    "species_name='Dusknoir' AND fresh_alignment=1",                     91.3, 48.5),
    (24, 'Ninetales Alolan',   "species_name='Ninetales' AND form=53 AND fresh_alignment IN (0,2)",91.3, 47.5),
    (25, 'Walrein',            "species_name='Walrein' AND fresh_alignment IN (0,2)",              91.3, 38.5),
]

XL_CUM = {50.0:0, 49.5:20, 49.0:40, 48.5:57, 48.0:74, 47.5:91, 47.0:108, 46.5:123, 46.0:138,
          45.5:153, 45.0:168, 44.5:181, 44.0:194, 43.5:207, 43.0:220, 42.5:232, 42.0:244,
          41.5:256, 41.0:268, 40.5:279, 40.0:290}

def xl_between(cur, target):
    if cur >= target or target <= 40.0: return 0
    cur_xl = XL_CUM.get(max(cur, 40.0), 290)
    tgt_xl = XL_CUM.get(target, 0)
    return max(0, cur_xl - tgt_xl)

def dust_between(cur, target):
    if cur >= target: return 0
    halves = (target - cur) * 2
    avg = 25000 if target > 45 else 19000 if target > 40 else 13000 if target > 35 else 10000
    return int(halves * avg)

c = sqlite3.connect('pokemon.db')
print(f'{"#":<3}{"Sc":>5}  {"Pokemon":<22} {"Spec":<35} {"L/Tgt":<10} {"CP":<5} {"IVs":<8} {"Rk":<6} {"Pct":<6} Status / Cost')
print('-'*155)

for rank, label, where, score, tgt_lvl in ul:
    # Pull up to 3 specimens that matter: best rank, hundo (if any), highest level
    best_rank = c.execute(f'''SELECT uid_hex, cp, iv_atk, iv_def, iv_sta, iv_total, level,
                                     ul_rank, ul_pct, ul_fits_at_current_level, fresh_alignment
                              FROM pokemon WHERE in_bag=1 AND ({where}) AND ul_rank IS NOT NULL
                              ORDER BY ul_rank ASC, ul_pct DESC LIMIT 1''').fetchone()
    if not best_rank:
        print(f'{rank:<3}{score:>5}  {label:<22} {"-- none in bag --":<35}')
        continue
    # Best rank-1 entry summary
    candidates = []
    candidates.append(('best-IV', best_rank))
    # If best is not a hundo, find hundo separately
    if best_rank[5] != 45:
        hundo = c.execute(f'''SELECT uid_hex, cp, iv_atk, iv_def, iv_sta, iv_total, level,
                                     ul_rank, ul_pct, ul_fits_at_current_level, fresh_alignment
                              FROM pokemon WHERE in_bag=1 AND ({where}) AND iv_total=45
                              ORDER BY level DESC, cp DESC LIMIT 1''').fetchone()
        if hundo:
            candidates.append(('hundo', hundo))

    for tag, r in candidates:
        uid, cp, a, d, s, ivt, lvl, urank, upct, ufits, fa = r
        iv = f'{a}/{d}/{s}'
        pur = ' P' if fa == 2 else (' S' if fa == 1 else '')
        spec_tag = f'{tag}{pur}'
        # status
        if lvl >= tgt_lvl - 0.25 and ufits == 1:
            status = 'MET'
            cost = ''
        elif lvl > tgt_lvl + 0.25 and ufits == 0:
            status = 'OVERSHOT (>2500cp)'
            cost = ''
        else:
            xl = xl_between(lvl, tgt_lvl)
            dust = dust_between(lvl, tgt_lvl)
            status = f'need +{tgt_lvl-lvl:.1f}L'
            cost = f'  ~{xl}XL +{dust:,}dust' if xl else f'  ~{dust:,}dust'
        flag = '★' if ivt == 45 else '+' if ivt >= 42 else ' '
        rank_disp = f'rk{urank}' if urank < 9999 else 'rk-'
        pct_disp = f'{upct:.1f}%' if upct is not None else '—'
        print(f'{rank:<3}{score:>5}  {label:<22} {flag}{spec_tag:<33} L{lvl}/{tgt_lvl}  {cp:<5} {iv:<8} {rank_disp:<6} {pct_disp:<6} {status}{cost}')

c.close()
