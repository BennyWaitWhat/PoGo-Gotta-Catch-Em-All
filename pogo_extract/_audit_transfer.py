"""Independent transfer-integrity audit. Re-derives keep rules from scratch and
checks the 6_Transfer pile against them + the sensitive-mon checklist."""
import sqlite3, json, os, sys
from collections import defaultdict

ROOT = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract'
DB = os.path.join(ROOT, 'pokemon.db')
sys.path.insert(0, ROOT)
from pvp_iv_rule import qualifies as pvp_iv_qualifies
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS

AE_IDS = {483, 484, 646, 800, 888, 889}
GL_FLOOR, UL_FLOOR = 1400, 2400
CPM50 = 0.84029999

out = []
def p(*a): out.append(' '.join(str(x) for x in a))

tf = os.path.join(ROOT, 'system', 'analysis', 'tagsets', '6_Transfer.txt')
transfer = set(open(tf).read().split())
pr = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json')))

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
by_uid = {r['uid_hex']: r for r in rows}
allu = set(by_uid)

# ---- Independent keep re-derivation (mirrors keep_policy.py but built fresh) ----
gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {pp['speciesId']: pp.get('baseStats', {}) for pp in gm['pokemon']}
legacy = {e['uid_hex'] for e in json.load(open(os.path.join(ROOT, 'legacy_accurate.json'), encoding='utf-8'))}

keep = defaultdict(set)
def mark(uid, why): keep[uid].add(why)
def topn(rows_, n):
    return sorted(rows_, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[:n]
def best_by(lst, key):
    cand = [r for r in lst if r[key] is not None]
    return min(cand, key=lambda r: r[key]) if cand else None

shadows = [r for r in rows if r['fresh_alignment'] == 1]
shinies = [r for r in rows if r['fresh_shiny']]
plain = [r for r in rows if r['fresh_alignment'] != 1 and not r['fresh_shiny']]

# 1 variant floor
vg = defaultdict(list)
for r in plain:
    key = (r['pokemon_id'], r['form'] or 0, r['fresh_costume'] or 0,
           r['special_bg_id'] or 0, r['natural_art_background'] or 0,
           r['costume_decoration_id'] or 0, r['fresh_bread_mode'] or 0)
    vg[key].append(r)
for key, lst in vg.items():
    for r in topn(lst, 8 if key[-1] == 2 else 4):
        mark(r['uid_hex'], 'variant_floor')
# 2 shadow
sg = defaultdict(list)
for r in shadows: sg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in sg.values():
    mark(topn(lst, 1)[0]['uid_hex'], 'shadow_best')
    for key in ('gl_rank', 'ul_rank'):
        b = best_by(lst, key)
        if b: mark(b['uid_hex'], 'shadow_best')
# 3 shiny
for r in shinies: mark(r['uid_hex'], 'shiny')
# 4 hundo
for r in rows:
    if (r['iv_total'] or 0) == 45: mark(r['uid_hex'], 'hundo')
# 5 rarity
rg = defaultdict(list); rgpf = defaultdict(list)
for r in rows:
    if r['fresh_shiny']: continue
    if (r['pokemon_id'] in RARE_PIDS or r['is_legendary'] or r['is_mythical']
            or r['is_ultra_beast'] or r['is_paradox']):
        rg[(r['pokemon_id'], r['form'] or 0, 1 if r['fresh_alignment'] == 1 else 0,
            r['fresh_bread_mode'] or 0)].append(r)
        rgpf[(r['pokemon_id'], r['form'] or 0)].append(r)
for key, lst in rg.items():
    n = len(lst) if key[0] == 150 else 8
    for r in topn(lst, n): mark(r['uid_hex'], 'rarity')
for lst in rgpf.values():
    for key in ('gl_rank', 'ul_rank'):
        b = best_by(lst, key)
        if b: mark(b['uid_hex'], 'rarity')
# 6 legacy
lg = defaultdict(list)
for r in rows:
    if r['uid_hex'] in legacy: lg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in lg.values():
    for r in topn(lst, 3): mark(r['uid_hex'], 'legacy')
# 7 xxl
xg = defaultdict(list)
for r in rows:
    if (r['pokemon_size_category'] or 0) == 5: xg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in xg.values():
    for metric, n in (('height_m', 2), ('weight_kg', 1)):
        for r in sorted(lst, key=lambda x: -(x[metric] or 0))[:n]: mark(r['uid_hex'], 'xxl')
# 8-13 keep-all
for r in rows:
    if (r['adventure_effects_left'] or 0) > 0 or r['pokemon_id'] in AE_IDS: mark(r['uid_hex'], 'adventure_effect')
    if r['is_zero'] and r['pokemon_id']: mark(r['uid_hex'], 'nundo')
    if r['was_best_buddy_badge'] == 1: mark(r['uid_hex'], 'best_buddy')
    if (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and \
       (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez'): mark(r['uid_hex'], 'origin')
    if r['fresh_is_strong'] == 1: mark(r['uid_hex'], 'mighty')
    if r['fresh_has_location_card'] == 1: mark(r['uid_hex'], 'location_card')
# 14 dex only copy
dg = defaultdict(list)
for r in rows: dg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in dg.values():
    if len(lst) == 1: mark(lst[0]['uid_hex'], 'dex_only_copy')
# 15 pvp iv
for r in rows:
    if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'],
                        r['iv_sta'], r['gl_stage'], r['gl_rank'], GL_FLOOR, BS):
        mark(r['uid_hex'], 'gl_iv')
    if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'],
                        r['iv_sta'], r['ul_stage'], r['ul_rank'], UL_FLOOR, BS):
        mark(r['uid_hex'], 'ul_iv')
for r in rows:
    if r['iv_atk'] == 0 and r['iv_def'] == 15 and r['iv_sta'] == 15:
        mark(r['uid_hex'], 'pvp_spread')

keepu = set(keep)
my_transfer = allu - keepu

p('=== CHECK A: structural cross-check ===')
p('transfer uids appearing in policy_reasons.json (must be 0):', len(transfer & set(pr.keys())))
p('=== CHECK B: independent re-derivation ===')
p('my re-derived KEEP count:', len(keepu), ' my re-derived TRANSFER count:', len(my_transfer))
p('committed transfer count:', len(transfer))
# Transfer mons that MY engine says should be KEPT (false transfers = sensitive!)
false_transfers = transfer & keepu
p('committed transfers that MY engine would KEEP (must be 0):', len(false_transfers))
for u in sorted(false_transfers):
    r = by_uid[u]
    p('   FALSE-TRANSFER', u, r['species_name'], 'pid', r['pokemon_id'],
      'iv', r['iv_total'], 'reasons=', sorted(keep[u]))
# Mons MY engine transfers but committed keeps (the other direction; informational)
extra_in_committed_keep = my_transfer - transfer  # I say transfer, they say keep
p('mons MY engine transfers but committed KEEPS:', len(extra_in_committed_keep))
for u in sorted(extra_in_committed_keep)[:30]:
    r = by_uid[u]
    p('   committed-keeps-I-transfer', u, r['species_name'], 'pid', r['pokemon_id'],
      'iv', r['iv_total'], 'committed_reasons=', pr.get(u))
# Does my transfer set EXACTLY equal the committed one?
p('MY transfer set == committed transfer set:', my_transfer == transfer)

open(os.path.join(ROOT, '_audit_out.txt'), 'w', encoding='utf-8').write('\n'.join(out))
print('\n'.join(out))
