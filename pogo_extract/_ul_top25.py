"""For each PVPoke UL top 25 entry, find the user's rank-1 IV match
(if any), and tell them whether it's powered up to target level or what
it'll cost to finish.

DB columns used:
  ul_rank: 1 = optimal IV spread for that species in UL (2500 CP cap)
  ul_pct: stat-product percentage (100 = absolute best)
  ul_fits_at_current_level: 1 if specimen's CP ≤ 2500 at current level
"""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

MOVES = {int(k): v for k, v in json.load(open('move_id_to_name.json')).items()}
def pretty(m):
    if not m: return ''
    return MOVES.get(m, '').replace('_FAST', '').replace('_', ' ').title().replace('Of', 'of').replace('The', 'the')

# PVPoke UL top 25 with per-pick target level + rank-1 IV (from gamemaster.json)
# Format: (rank, label, where_clause, score, target_level, target_ivs, fast, c1, c2, notes)
ul = [
    (1,  'Jellicent',                "species_name='Jellicent' AND fresh_alignment IN (0,2)",            95.5, 47.5, (12,14,12),
        'Hex','Surf','Shadow Ball', ''),
    (2,  'Corviknight',              "species_name='Corviknight' AND fresh_alignment IN (0,2)",          95.4, 47.0, (4,14,13),
        'Sand Attack','Air Cutter','Payback', ''),
    (3,  'Lapras',                   "species_name='Lapras' AND fresh_alignment IN (0,2)",               95.4, 40.5, (4,15,15),
        'Psywave','Sparkling Aria','Ice Beam', 'Sparkling Aria = ETM or 2025-03 Lapras event'),
    (4,  'Lapras Shadow',            "species_name='Lapras' AND fresh_alignment=1",                       95.0, 40.5, (4,15,15),
        'Psywave','Sparkling Aria','Ice Beam', ''),
    (5,  'Tinkaton',                 "species_name='Tinkaton' AND fresh_alignment IN (0,2)",             94.9, 50.0, (12,15,15),
        'Fairy Wind','Gigaton Hammer','Bulldoze', 'Gigaton Hammer = April 2026 CD or ETM'),
    (6,  'Empoleon',                 "species_name='Empoleon' AND fresh_alignment IN (0,2)",             94.4, 33.0, (6,15,14),
        'Metal Sound','Hydro Cannon','Drill Peck', 'Hydro Cannon = CD legacy'),
    (7,  'Moltres Galarian',         "species_name='Moltres' AND fresh_alignment IN (0,2) AND form NOT IN (0,53)",  94.3, 29.5, (4,11,11),
        'Sucker Punch','Fly','Brave Bird', 'DAI exclusive, 90% flee'),
    (8,  'Empoleon Shadow',          "species_name='Empoleon' AND fresh_alignment=1",                     94.2, 33.0, (6,15,14),
        'Metal Sound','Hydro Cannon','Drill Peck', ''),
    (9,  'Feraligatr Shadow',        "species_name='Feraligatr' AND fresh_alignment=1",                   93.9, 35.0, (4,15,11),
        'Shadow Claw','Hydro Cannon','Ice Beam', 'Shadow > Normal for Gatr'),
    (10, 'Malamar Shadow',           "species_name='Malamar' AND fresh_alignment=1",                      93.3, 50.0, (4,13,15),
        'Psywave','Foul Play','Super Power', 'Shadow strongly preferred'),
    (11, 'Florges',                  "species_name='Florges' AND fresh_alignment IN (0,2)",              93.2, 28.5, (4,13,15),
        'Fairy Wind','Chilling Water','Disarming Voice', ''),
    (12, 'Feraligatr',               "species_name='Feraligatr' AND fresh_alignment IN (0,2)",           93.1, 35.0, (4,15,11),
        'Shadow Claw','Hydro Cannon','Ice Beam', ''),
    (13, 'Dondozo',                  "species_name='Dondozo' AND fresh_alignment IN (0,2)",              93.0, 32.0, (4,14,15),
        'Waterfall','Surf','Outrage', ''),
    (14, 'Virizion',                 "species_name='Virizion' AND fresh_alignment IN (0,2)",             92.7, 31.0, (6,15,11),
        'Double Kick','Leaf Blade','Sacred Sword', 'Sacred Sword = ETM only'),
    (15, 'Regidrago',                "species_name='Regidrago' AND fresh_alignment IN (0,2)",            92.5, 32.5, (5,12,14),
        'Dragon Breath','Dragon Energy','Vice Grip', 'Memories in Motion raids until Jun 2'),
    (16, 'Lickilicky',               "species_name='Lickilicky' AND fresh_alignment IN (0,2)",           92.3, 47.0, (4,13,13),
        'Rollout','Body Slam','Shadow Ball', 'Rollout = legacy Fast TM'),
    (17, 'Ludicolo',                 "species_name='Ludicolo' AND fresh_alignment IN (0,2)",             92.3, 47.5, (12,15,13),
        'Astonish','Weather Ball','Leaf Storm', ''),
    (18, 'Clefable',                 "species_name='Clefable' AND fresh_alignment IN (0,2)",             92.1, 47.5, (4,12,15),
        'Fairy Wind','Meteor Mash','Moonblast', ''),
    (19, 'Blastoise',                "species_name='Blastoise' AND fresh_alignment IN (0,2)",            91.7, 45.5, (5,15,15),
        'Rollout','Hydro Cannon','Skull Bash', 'Triple-legacy moveset'),
    (20, 'Oranguru',                 "species_name='Oranguru' AND fresh_alignment IN (0,2)",             91.7, 47.0, (4,14,14),
        'Confusion','Brutal Swing','Trailblaze', ''),
    (21, 'Zygarde Complete',         "species_name='Zygarde'",                                            91.5, 24.0, (13,10,15),
        'Dragon Tail','Crunch','Earthquake', '250 cells for Complete Forme'),
    (22, 'Malamar',                  "species_name='Malamar' AND fresh_alignment IN (0,2)",              91.4, 50.0, (4,13,15),
        'Psywave','Foul Play','Super Power', ''),
    (23, 'Dusknoir Shadow',          "species_name='Dusknoir' AND fresh_alignment=1",                     91.3, 48.5, (4,13,15),
        'Astonish','Dynamic Punch','Shadow Punch', 'Dynamic Punch = ETM only'),
    (24, 'Ninetales Alolan',         "species_name='Ninetales' AND form=53 AND fresh_alignment IN (0,2)",91.3, 47.5, (13,15,14),
        'Powder Snow','Weather Ball','Chilling Water', ''),
    (25, 'Walrein',                  "species_name='Walrein' AND fresh_alignment IN (0,2)",              91.3, 38.5, (4,13,14),
        'Powder Snow','Icicle Spear','Earthquake', 'Icicle Spear = Spheal CD legacy'),
]

# XL candy cumulative from level L to 50 (going through 40+)
XL_CUM = {50.0:0, 49.5:20, 49.0:40, 48.5:57, 48.0:74, 47.5:91, 47.0:108, 46.5:123, 46.0:138,
          45.5:153, 45.0:168, 44.5:181, 44.0:194, 43.5:207, 43.0:220, 42.5:232, 42.0:244,
          41.5:256, 41.0:268, 40.5:279, 40.0:290}

def xl_between(cur, target):
    """XL candy cost from cur level to target level (both rounded to 0.5)"""
    if cur >= target: return 0
    if target <= 40.0: return 0  # below L40 only normal candy needed
    cur_xl = XL_CUM.get(max(cur, 40.0), 290)
    tgt_xl = XL_CUM.get(target, 0)
    return max(0, cur_xl - tgt_xl)

def candy_dust_between(cur, target):
    """Rough normal-candy + stardust between two levels (no XL component)."""
    if cur >= target: return 0, 0
    # approx 13 candy + 12,000 dust per half-level avg for L20-40 range
    halves = (target - cur) * 2
    return int(halves * 13), int(halves * 12000)

c = sqlite3.connect('pokemon.db')

met_rows = []
need_rows = []
missing = []

for rank, label, where, score, tgt_lvl, tgt_iv, f, c1, c2, note in ul:
    # Get best rank-1 IV match (or fallback to highest stat product if no exact rank-1)
    q = (f"SELECT uid_hex, cp, iv_atk, iv_def, iv_sta, level, ul_rank, ul_pct, "
         f"ul_fits_at_current_level, move1, move2, move3, fresh_alignment "
         f"FROM pokemon WHERE in_bag=1 AND ({where}) AND ul_rank=1 "
         f"ORDER BY ul_pct DESC, level DESC, cp DESC LIMIT 1")
    r = c.execute(q).fetchone()
    if not r:
        # Try ANY ul_rank<=5 match as fallback
        q2 = (f"SELECT uid_hex, cp, iv_atk, iv_def, iv_sta, level, ul_rank, ul_pct, "
              f"ul_fits_at_current_level, move1, move2, move3, fresh_alignment "
              f"FROM pokemon WHERE in_bag=1 AND ({where}) AND ul_rank<=5 "
              f"ORDER BY ul_rank, ul_pct DESC, level DESC LIMIT 1")
        r = c.execute(q2).fetchone()
        if not r:
            missing.append((rank, label, score, note))
            continue
    uid, cp, a, d, s, lvl, urank, upct, ufits, m1, m2, m3, fa = r
    pur = ' (Purified)' if fa == 2 else ''
    moves_now = [pretty(m) for m in (m1, m2, m3) if m]
    moves_ideal = (f, c1, c2)
    tm_needed = [m for m in moves_ideal if m not in moves_now]
    # status
    at_target = abs(lvl - tgt_lvl) < 0.25
    overlevelled = lvl > tgt_lvl + 0.25
    if at_target or (overlevelled and ufits == 1):
        status = 'MET'
    elif overlevelled and ufits == 0:
        status = 'OVERSHOT (>2500 CP)'
    else:
        status = f'+{tgt_lvl - lvl:.1f} lvls'
    row = (rank, label+pur, score, urank, upct, lvl, tgt_lvl, status, a, d, s, cp,
           moves_now, moves_ideal, tm_needed, note)
    if status == 'MET':
        met_rows.append(row)
    else:
        need_rows.append(row)

# ----- Print -----
def print_row(r):
    rank, label, score, urank, upct, lvl, tgt, status, a, d, s, cp, mn, mi, tm, note = r
    iv = f'{a}/{d}/{s}'
    pct = f'{upct:.1f}%' if upct is not None else '—'
    tm_disp = ('TM: ' + ', '.join(tm)) if tm else 'moves ok'
    extra = f' -- {note}' if note else ''
    print(f"  {rank:>2}. {score:>4}  {label:<26} rk{urank}/{pct:<6}  L{lvl:<4} cp={cp:<5} IV={iv:<8}  {status:<18}  {tm_disp}{extra}")

print('=== MET (already at UL target level, ul_rank=1 IV) ===')
if not met_rows: print('  (none)')
for r in sorted(met_rows, key=lambda x: x[0]): print_row(r)

print('\n=== NEEDS POWERUP (you have rank-1 IV, just under target level) ===')
print(f'  {"":>2}  {"Sc":>4}  {"Pokemon":<26} {"Rank/Pct":<14} {"Lv→Target":<13} {"CP":<7} {"IVs":<8}  Status               Action')
if not need_rows: print('  (none)')
total_xl = 0; total_dust = 0
for r in sorted(need_rows, key=lambda x: x[0]):
    rank, label, score, urank, upct, lvl, tgt, status, a, d, s, cp, mn, mi, tm, note = r
    xl = xl_between(lvl, tgt)
    # dust estimate
    halves = (tgt - lvl) * 2
    # ~10k under L30, 13k L30-35, 19k L35-40, 25k L40-45, 35k L45+
    avg_dust = 25000 if tgt > 45 else 19000 if tgt > 40 else 13000 if tgt > 35 else 10000
    dust = int(halves * avg_dust)
    total_xl += xl; total_dust += dust
    print_row(r)
    print(f'        → ~{xl} XL + ~{dust:,} dust  (L{lvl} → L{tgt})')
print(f'\n  TOTAL to finish all: ~{total_xl} XL  +  ~{total_dust:,} dust')

print('\n=== NOT OWNED (PVPoke top 25 you have NO rank-1 or near-rank-1 IV of) ===')
for rank, label, score, note in missing:
    extra = f' -- {note}' if note else ''
    print(f'  {rank:>2}. {score:>4}  {label:<26}{extra}')

c.close()
