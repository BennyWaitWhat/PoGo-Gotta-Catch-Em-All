"""CHECK 2 + 3: apply the sensitive-mon checklist DIRECTLY to the 132 transfer
mons (independent of the keep engine), and profile composition."""
import sqlite3, json, os, sys
from collections import defaultdict, Counter

ROOT = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract'
DB = os.path.join(ROOT, 'pokemon.db')
sys.path.insert(0, ROOT)
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
AE_IDS = {483, 484, 646, 800, 888, 889}

out = []
def p(*a): out.append(' '.join(str(x) for x in a))

tf = os.path.join(ROOT, 'system', 'analysis', 'tagsets', '6_Transfer.txt')
transfer = set(open(tf).read().split())

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
tr = [r for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1") if r['uid_hex'] in transfer]
p('transfer rows loaded:', len(tr))

def flag(name, pred):
    hits = [r for r in tr if pred(r)]
    p(f'CHECK2 [{name}] in transfer (must be 0): {len(hits)}')
    for r in hits[:40]:
        p('   VIOLATION', name, r['uid_hex'], r['species_name'], 'pid', r['pokemon_id'],
          'iv', r['iv_total'], f"{r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}",
          'shiny', r['is_shiny'], 'fresh_shiny', r['fresh_shiny'])
    return hits

viol = {}
viol['is_shiny'] = flag('is_shiny=1', lambda r: r['is_shiny'] == 1)
viol['fresh_shiny'] = flag('fresh_shiny truthy', lambda r: bool(r['fresh_shiny']))
viol['hundo'] = flag('iv_total=45 hundo', lambda r: (r['iv_total'] or 0) == 45)
viol['rare_roster'] = flag('pid in RARE rosters', lambda r: r['pokemon_id'] in RARE_PIDS)
viol['is_legendary_col'] = flag('is_legendary col=1', lambda r: r['is_legendary'] == 1)
viol['is_mythical_col'] = flag('is_mythical col=1', lambda r: r['is_mythical'] == 1)
viol['is_ultra_beast_col'] = flag('is_ultra_beast col=1', lambda r: r['is_ultra_beast'] == 1)
viol['is_paradox_col'] = flag('is_paradox col=1', lambda r: r['is_paradox'] == 1)
viol['best_buddy'] = flag('was_best_buddy_badge=1', lambda r: r['was_best_buddy_badge'] == 1)
viol['nundo_spread'] = flag('0/15/15 spread', lambda r: r['iv_atk'] == 0 and r['iv_def'] == 15 and r['iv_sta'] == 15)
viol['is_zero'] = flag('is_zero=1 nundo', lambda r: r['is_zero'] == 1 and r['pokemon_id'])
viol['adv_effect'] = flag('adventure_effects_left>0 or AE pid', lambda r: (r['adventure_effects_left'] or 0) > 0 or r['pokemon_id'] in AE_IDS)
viol['location_card'] = flag('fresh_has_location_card=1', lambda r: r['fresh_has_location_card'] == 1)
viol['mighty'] = flag('fresh_is_strong=1 mighty', lambda r: r['fresh_is_strong'] == 1)
viol['origin'] = flag('origin ethanmateovz/florandez', lambda r: (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez'))

# Extra paranoia: ANY origin owner E/F regardless of traded flags
viol['origin_owner_any'] = flag('owner is E/F (any flag)', lambda r: (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez'))
# was_best_buddy alternate flag name check
# best buddy via is_best_buddy (noise col) - informational only, NOT a violation

total_viol = sum(len(v) for v in viol.values())
p('=== TOTAL CHECK2 violations across all categories:', total_viol, '===')

p('')
p('=== CHECK 3: composition of the transfer pile ===')
sp = Counter(r['species_name'] for r in tr)
p('distinct species in transfer:', len(sp))
p('top species:', sp.most_common(25))
# IV distribution
ivs = [r['iv_total'] or 0 for r in tr]
p('iv_total min/median/max:', min(ivs), sorted(ivs)[len(ivs)//2], max(ivs))
p('iv_total >= 37 count (would-be decent):', sum(1 for v in ivs if v >= 37))
p('iv_total = 45 count:', sum(1 for v in ivs if v == 45))
# CP distribution
cps = [r['cp'] or 0 for r in tr]
p('cp min/median/max:', min(cps), sorted(cps)[len(cps)//2], max(cps))
# Are these genuinely dupes? For each transfer mon, how many copies of (pid,form) total in bag?
allrows = list(c.execute("SELECT uid_hex,pokemon_id,form FROM pokemon WHERE in_bag=1"))
cnt = Counter((r['pokemon_id'], r['form'] or 0) for r in allrows)
solo = [r for r in tr if cnt[(r['pokemon_id'], r['form'] or 0)] == 1]
p('transfer mons that are the ONLY copy of their (pid,form) (should be 0 - dex rule):', len(solo))
for r in solo[:20]:
    p('   SOLO-TRANSFER', r['uid_hex'], r['species_name'], 'pid', r['pokemon_id'], 'form', r['form'])
# group-size distribution of transfer mons' species
grpsizes = [cnt[(r['pokemon_id'], r['form'] or 0)] for r in tr]
p('min group size of a transferred mon (copies in bag):', min(grpsizes))
p('mons in groups of >=5 copies:', sum(1 for g in grpsizes if g >= 5), '/ 132')

# cosmetic axes -- any transfer mon with a cosmetic flag set (should be captured by Event/variant)?
cos = [r for r in tr if (r['fresh_costume'] or 0) != 0 or (r['special_bg_id'] or 0) != 0 or (r['natural_art_background'] or 0) != 0 or (r['costume_decoration_id'] or 0) != 0]
p('transfer mons with ANY cosmetic axis set (costume/specialbg/art/decoration):', len(cos))
for r in cos[:20]:
    p('   COSMETIC-TRANSFER', r['uid_hex'], r['species_name'], 'costume', r['fresh_costume'],
      'specialbg', r['special_bg_id'], 'art', r['natural_art_background'], 'deco', r['costume_decoration_id'])
# bread mode (dynamax/gmax) in transfer
bread = [r for r in tr if (r['fresh_bread_mode'] or 0) != 0]
p('transfer mons with fresh_bread_mode != 0 (dynamax/gmax):', len(bread))
for r in bread[:20]:
    p('   BREAD-TRANSFER', r['uid_hex'], r['species_name'], 'bread', r['fresh_bread_mode'], 'iv', r['iv_total'])

open(os.path.join(ROOT, '_audit_sensitive_out.txt'), 'w', encoding='utf-8').write('\n'.join(out))
print('\n'.join(out))
