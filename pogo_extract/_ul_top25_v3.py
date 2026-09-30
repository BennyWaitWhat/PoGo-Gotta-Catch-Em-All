"""UL top 25 — strict rank-1 matches + hundo callouts, with proper
MET / OVERSHOT / NEEDS-POWERUP logic based on ul_fits_at_current_level.

Status reasoning:
  ul_fits_at_current_level = 1  → CP currently under 2500
  ul_fits_at_current_level = 0  → CP currently OVER 2500 (specimen overshot)
"""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

# UL top 25 + Dusknoir Normal (#27)
# (rank, label, where, score, target_lvl_for_rank1_iv)
ul = [
    (1,  'Jellicent',           "species_name='Jellicent' AND fresh_alignment IN (0,2)",            95.5, 47.5),
    (2,  'Corviknight',         "species_name='Corviknight' AND fresh_alignment IN (0,2)",          95.4, 47.0),
    (3,  'Lapras',              "species_name='Lapras' AND fresh_alignment IN (0,2)",               95.4, 40.5),
    (4,  'Lapras Shadow',       "species_name='Lapras' AND fresh_alignment=1",                       95.0, 40.5),
    (5,  'Tinkaton',            "species_name='Tinkaton' AND fresh_alignment IN (0,2)",             94.9, 50.0),
    (6,  'Empoleon',            "species_name='Empoleon' AND fresh_alignment IN (0,2)",             94.4, 33.0),
    (7,  'Moltres Galarian',    "species_name='Moltres' AND form NOT IN (0,53)",                     94.3, 29.5),
    (8,  'Empoleon Shadow',     "species_name='Empoleon' AND fresh_alignment=1",                     94.2, 33.0),
    (9,  'Feraligatr Shadow',   "species_name='Feraligatr' AND fresh_alignment=1",                   93.9, 35.0),
    (10, 'Malamar Shadow',      "species_name='Malamar' AND fresh_alignment=1",                      93.3, 50.0),
    (11, 'Florges',             "species_name='Florges' AND fresh_alignment IN (0,2)",              93.2, 28.5),
    (12, 'Feraligatr',          "species_name='Feraligatr' AND fresh_alignment IN (0,2)",           93.1, 35.0),
    (13, 'Dondozo',             "species_name='Dondozo' AND fresh_alignment IN (0,2)",              93.0, 32.0),
    (14, 'Virizion',            "species_name='Virizion' AND fresh_alignment IN (0,2)",             92.7, 31.0),
    (15, 'Regidrago',           "species_name='Regidrago' AND fresh_alignment IN (0,2)",            92.5, 32.5),
    (16, 'Lickilicky',          "species_name='Lickilicky' AND fresh_alignment IN (0,2)",           92.3, 47.0),
    (17, 'Ludicolo',            "species_name='Ludicolo' AND fresh_alignment IN (0,2)",             92.3, 47.5),
    (18, 'Clefable',            "species_name='Clefable' AND fresh_alignment IN (0,2)",             92.1, 47.5),
    (19, 'Blastoise',           "species_name='Blastoise' AND fresh_alignment IN (0,2)",            91.7, 45.5),
    (20, 'Oranguru',            "species_name='Oranguru' AND fresh_alignment IN (0,2)",             91.7, 47.0),
    (21, 'Zygarde Complete',    "species_name='Zygarde'",                                            91.5, 24.0),
    (22, 'Malamar',             "species_name='Malamar' AND fresh_alignment IN (0,2)",              91.4, 50.0),
    (23, 'Dusknoir Shadow',     "species_name='Dusknoir' AND fresh_alignment=1",                     91.3, 48.5),
    (24, 'Ninetales Alolan',    "species_name='Ninetales' AND form=58 AND fresh_alignment IN (0,2)",91.3, 47.5),
    (25, 'Walrein',             "species_name='Walrein' AND fresh_alignment IN (0,2)",              91.3, 38.5),
    (27, 'Dusknoir',            "species_name='Dusknoir' AND fresh_alignment IN (0,2)",             91.2, 48.5),
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
met = []
need = []
overshot = []
not_owned = []

for rank, label, where, score, tgt in ul:
    # Look for rank-1 IV first
    r = c.execute(f'''SELECT uid_hex, cp, iv_atk, iv_def, iv_sta, iv_total, level,
                            ul_rank, ul_pct, ul_fits_at_current_level
                     FROM pokemon WHERE in_bag=1 AND ({where}) AND ul_rank=1
                     ORDER BY level DESC LIMIT 1''').fetchone()
    kind = 'rank-1'
    if not r:
        # Fall back to best IV in the bag for this species/form
        r = c.execute(f'''SELECT uid_hex, cp, iv_atk, iv_def, iv_sta, iv_total, level,
                                ul_rank, ul_pct, ul_fits_at_current_level
                         FROM pokemon WHERE in_bag=1 AND ({where}) AND ul_rank IS NOT NULL
                         ORDER BY ul_rank ASC, ul_pct DESC LIMIT 1''').fetchone()
        kind = 'best-IV'
    if not r:
        not_owned.append((rank, label, score))
        continue
    uid, cp, a, d, s, ivt, lvl, urank, upct, ufits = r
    iv = f'{a}/{d}/{s}'
    flag = '★' if ivt == 45 else '+' if ivt >= 42 else ' '

    # Status:
    # ufits=0 → over 2500 already
    # ufits=1 AND level ≈ target → MET
    # ufits=1 AND level < target → need powerup
    if ufits == 0:
        status = 'OVERSHOT (>2500cp)'
        bucket = overshot
    elif ufits == 1 and lvl >= tgt - 0.25:
        status = 'MET'
        bucket = met
    else:
        # Estimate cost — use target for rank-1 only; for non-rank-1 hundos
        # we'd need per-IV simulation, but the cost to get to PVPoke's target
        # is a useful lower-bound.
        status = f'need +{tgt-lvl:.1f} levels'
        bucket = need

    bucket.append((rank, label, score, kind, urank, upct, lvl, tgt, cp, iv, flag, ufits))

# ---- Print ----
def fmt(row):
    rank, label, score, kind, urank, upct, lvl, tgt, cp, iv, flag, ufits = row
    pct = f'{upct:.1f}%' if upct is not None else '—'
    rk = f'rk{urank}' if urank and urank < 9999 else 'rk-'
    return f'  {rank:>2}. {score:>4}  {flag} {label:<22} ({kind:<7}) L{lvl}/{tgt}  cp={cp:<5} IV={iv:<8} {rk:<6} {pct}'

print('=== MET — at the cap with rank-1 IV (ready to play) ===')
for r in sorted(met, key=lambda x: x[0]):
    print(fmt(r))
if not met: print('  (none)')

print('\n=== NEEDS POWERUP — rank-1 IV, still room to grow under cap ===')
for r in sorted(need, key=lambda x: x[0]):
    rank, label, score, kind, urank, upct, lvl, tgt, cp, iv, flag, ufits = r
    xl = xl_between(lvl, tgt)
    dust = dust_between(lvl, tgt)
    cost = f'~{xl}XL + ~{dust:,}dust' if xl else f'~{dust:,}dust'
    print(fmt(r) + f'    → {cost} (L{lvl}→L{tgt})')
if not need: print('  (none)')

print('\n=== OVERSHOT — already over 2500 CP, only usable as ML/no-cap ===')
for r in sorted(overshot, key=lambda x: x[0]):
    print(fmt(r))
if not overshot: print('  (none)')

print('\n=== NOT OWNED — no rank-1 or best-IV match in bag ===')
for rank, label, score in sorted(not_owned, key=lambda x: x[0]):
    print(f'  {rank:>2}. {score:>4}  {label}')
if not not_owned: print('  (none)')

c.close()
