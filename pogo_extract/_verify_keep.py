"""Independent re-derivation of the keep policy -- written from scratch (does NOT
import keep_policy.main) and diffed PER REASON against keep_policy's own output
(system/analysis/policy_reasons.json), plus invariant checks. A clean run proves
the engine does exactly what it claims, with no over/under-keep from the edits."""
import sqlite3, json, os, sys
from collections import defaultdict
ROOT = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, ROOT); os.chdir(ROOT)
from pvp_iv_rule import qualifies as pvpq
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
AE_IDS = {483, 484, 646, 800, 888, 889}; GLF, ULF = 1400, 2400
gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
legacy = {e['uid_hex'] for e in json.load(open('legacy_accurate.json', encoding='utf-8'))}
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
by = {r['uid_hex']: r for r in rows}

def topn(lst, n): return sorted(lst, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[:n]
def bestby(lst, k):
    cand = [r for r in lst if r[k] is not None]
    return min(cand, key=lambda r: r[k]) if cand else None

reasons = defaultdict(set)
def mark(u, w): reasons[u].add(w)
shadows = [r for r in rows if r['fresh_alignment'] == 1]
shinies = [r for r in rows if r['fresh_shiny']]
plain   = [r for r in rows if r['fresh_alignment'] != 1 and not r['fresh_shiny']]

vg = defaultdict(list)
for r in plain: vg[(r['pokemon_id'], r['form'] or 0, r['fresh_costume'] or 0, r['fresh_bread_mode'] or 0)].append(r)
for lst in vg.values():
    for r in topn(lst, 4): mark(r['uid_hex'], 'variant_floor')

sg = defaultdict(list)
for r in shadows: sg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in sg.values():
    mark(topn(lst, 1)[0]['uid_hex'], 'shadow_best')
    for k in ('gl_rank', 'ul_rank'):
        b = bestby(lst, k)
        if b: mark(b['uid_hex'], 'shadow_best')

for r in shinies: mark(r['uid_hex'], 'shiny')
for r in rows:
    if (r['iv_total'] or 0) == 45: mark(r['uid_hex'], 'hundo')

rg = defaultdict(list); rgpf = defaultdict(list)
for r in rows:
    if r['fresh_shiny']: continue
    if r['pokemon_id'] in RARE or r['is_legendary'] or r['is_mythical'] or r['is_ultra_beast'] or r['is_paradox']:
        rg[(r['pokemon_id'], r['form'] or 0, 1 if r['fresh_alignment'] == 1 else 0, r['fresh_bread_mode'] or 0)].append(r)
        rgpf[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in rg.values():
    for r in topn(lst, 4): mark(r['uid_hex'], 'rarity')
for lst in rgpf.values():
    for k in ('gl_rank', 'ul_rank'):
        b = bestby(lst, k)
        if b: mark(b['uid_hex'], 'rarity')

lg = defaultdict(list)
for r in rows:
    if r['uid_hex'] in legacy: lg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in lg.values():
    for r in topn(lst, 4): mark(r['uid_hex'], 'legacy')

xg = defaultdict(list)
for r in rows:
    if (r['pokemon_size_category'] or 0) == 5: xg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in xg.values():
    for metric in ('weight_kg', 'height_m'):
        for r in sorted(lst, key=lambda x: -(x[metric] or 0))[:2]: mark(r['uid_hex'], 'xxl')

for r in rows:
    if (r['adventure_effects_left'] or 0) > 0 or r['pokemon_id'] in AE_IDS: mark(r['uid_hex'], 'adventure_effect')
    if r['is_zero'] and r['pokemon_id']: mark(r['uid_hex'], 'nundo')
    if r['was_best_buddy_badge'] == 1: mark(r['uid_hex'], 'best_buddy')
    if (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and \
       (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez'): mark(r['uid_hex'], 'origin')
    if r['fresh_is_strong'] == 1: mark(r['uid_hex'], 'mighty')
    if r['fresh_has_location_card'] == 1: mark(r['uid_hex'], 'location_card')

dg = defaultdict(list)
for r in rows: dg[(r['pokemon_id'], r['form'] or 0)].append(r)
for lst in dg.values():
    if len(lst) == 1: mark(lst[0]['uid_hex'], 'dex_only_copy')

for r in rows:
    if pvpq(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['gl_stage'], r['gl_rank'], GLF, BS): mark(r['uid_hex'], 'gl_iv')
    if pvpq(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['ul_stage'], r['ul_rank'], ULF, BS): mark(r['uid_hex'], 'ul_iv')
    if r['iv_atk'] == 0 and r['iv_def'] == 15 and r['iv_sta'] == 15: mark(r['uid_hex'], 'pvp_spread')

keepu = set(reasons); allu = {r['uid_hex'] for r in rows}; transu = allu - keepu
pp = json.load(open('system/analysis/policy_reasons.json', encoding='utf-8'))
pol = defaultdict(set); ind = defaultdict(set)
for u, rs in pp.items():
    for w in rs: pol[w].add(u)
for u, rs in reasons.items():
    for w in rs: ind[w].add(u)

print('=== PER-REASON DIFF (independent reimpl vs keep_policy) ===')
allok = True
for w in sorted(set(pol) | set(ind)):
    a, b = ind[w], pol[w]
    if a != b:
        allok = False
        print(f'  MISMATCH {w}: indep={len(a)} policy={len(b)} | only-indep={sorted(a-b)[:3]} only-policy={sorted(b-a)[:3]}')
    else:
        print(f'  OK  {w:16} {len(a)}')
print(f'KEEP set exact match: {keepu == set(pp)}  (indep {len(keepu)} / policy {len(pp)})')

print('\n=== INVARIANTS ===')
tfile = set(open('system/analysis/tagsets/6_Transfer.txt').read().split())
print(f'  [{"PASS" if tfile == transu else "FAIL"}] 6_Transfer.txt == in_bag - KEEP  (file {len(tfile)} / computed {len(transu)})')
print(f'  [{"PASS" if not any(by[u]["fresh_shiny"] for u in tfile) else "FAIL"}] no shiny in transfer')
viol = [b['uid_hex'] for lst in rgpf.values() for k in ('gl_rank', 'ul_rank') if (b := bestby(lst, k)) and b['uid_hex'] in tfile]
print(f'  [{"PASS" if not viol else "FAIL"}] no legendary best-GL/UL in transfer  (violations {len(viol)})')
capbad = sum(1 for lst in vg.values() if len([r for r in lst if 'variant_floor' in reasons.get(r['uid_hex'], set())]) > 4)
print(f'  [{"PASS" if capbad == 0 else "FAIL"}] variant_floor keeps <=4 per group  (over-cap groups {capbad})')
sbad = sum(1 for lst in sg.values() if len([r for r in lst if 'shadow_best' in reasons.get(r['uid_hex'], set())]) > 3)
print(f'  [{"PASS" if sbad == 0 else "FAIL"}] shadow_best keeps <=3 per group  (over {sbad})')
hund_tr = [u for u in tfile if (by[u]['iv_total'] or 0) == 45]
print(f'  [{"PASS" if not hund_tr else "FAIL"}] no hundo in transfer  ({len(hund_tr)})')
print(f'\nOVERALL: {"ALL PASS" if (allok and keepu == set(pp) and tfile == transu and not viol and capbad == 0 and sbad == 0 and not hund_tr) else "SEE FAILURES ABOVE"}')
