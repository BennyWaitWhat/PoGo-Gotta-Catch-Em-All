"""Independent adversarial verifier for the 'edge cases pass' finding.
Re-runs the LIVE keep_policy engine but redirects its file writes to a temp dir
so the committed artifacts are untouched, then reconstructs the keep map FROM
SCRATCH and tests each claim with my own queries.
"""
import sqlite3, json, os, sys, tempfile
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'system', 'scripts'))

import keep_policy as KP

# ---- Rebuild the keep map by re-implementing main() inline (copied logic) so we
# ---- can inspect the in-memory `keep` dict directly, not stale JSON. We import the
# ---- helpers (build_evo_graph, topn) from the live module to guarantee identity.
DB = os.path.join(HERE, 'pokemon.db')
c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
legacy = {e['uid_hex'] for e in json.load(open(os.path.join(HERE, 'legacy_accurate.json'), encoding='utf-8'))}
is_preevo, term_of = KP.build_evo_graph(gm)
topn = KP.topn

keep = defaultdict(set)
def mark(uid, why): keep[uid].add(why)

shadows = [r for r in rows if r['fresh_alignment'] == 1]
shinies = [r for r in rows if r['fresh_shiny']]
plain = [r for r in rows if r['fresh_alignment'] != 1 and not r['fresh_shiny']]

_basecnt = defaultdict(Counter)
for r in rows:
    _f = r['form'] or 0
    _reg = (r['form_region'] or '').strip().lower()
    if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null'):
        _basecnt[r['pokemon_id']][_f] += 1
base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}
def cf(r):
    _f = r['form'] or 0
    return base_form.get(r['pokemon_id'], _f) if _f == 0 else _f

GENDER_TERMINALS = {
    415: {1: set(), 2: {416}},
    757: {1: set(), 2: {758}},
    361: {1: {362}, 2: {478, 362}},
    281: {1: {475, 282}, 2: {282}},
    280: {1: {475, 282}, 2: {282}},
    412: {1: {414}, 2: {413}},
}
def reach(r):
    gt = GENDER_TERMINALS.get(r['pokemon_id'])
    if gt is not None:
        return gt.get(r['gender'], set())
    return term_of.get(r['pokemon_id'], set()) if is_preevo.get(r['pokemon_id']) else set()
def _can_evo(r):
    return bool(reach(r))
def _truly_plain(r):
    return (not (r['fresh_costume'] or 0) and not (r['special_bg_id'] or 0)
            and not (r['natural_art_background'] or 0)
            and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
            and not (r['fresh_bread_mode'] or 0))

# 1a variant floor non-plain
vg = defaultdict(list)
for r in plain:
    if _truly_plain(r):
        continue
    vg[(r['pokemon_id'], cf(r), r['fresh_costume'] or 0, r['special_bg_id'] or 0,
        r['natural_art_background'] or 0, r['costume_decoration_id'] or 0,
        r['fresh_bread_mode'] or 0)].append(r)
for key, lst in vg.items():
    cap = 8 if key[-1] == 2 else 4
    for r in topn(lst, cap):
        mark(r['uid_hex'], 'variant_floor')

# 1b plain line cap
LINE_CAP = 3
_formreg = defaultdict(lambda: defaultdict(set))
for r in plain:
    if _truly_plain(r):
        _formreg[r['pokemon_id']][r['form_region'] or 'kantonian'].add(cf(r))
FORM_COLLECTIBLE = {pid for pid, regs in _formreg.items() if any(len(f) > 1 for f in regs.values())}
def _poolable(r):
    return (r['pokemon_id'] not in FORM_COLLECTIBLE
            and not any(t in FORM_COLLECTIBLE for t in reach(r)))

line_pool = defaultdict(list)
fc_pool = defaultdict(list)
for r in plain:
    if not _truly_plain(r):
        continue
    if _poolable(r):
        region = r['form_region'] or 'kantonian'
        terms = reach(r)
        if terms:
            for t in terms:
                line_pool[(t, region)].append(r)
        else:
            line_pool[(r['pokemon_id'], region)].append(r)
    else:
        fc_pool[(r['pokemon_id'], cf(r))].append(r)
for (_term, _region), lst in line_pool.items():
    cap = 1 if is_preevo.get(_term) else LINE_CAP
    for r in topn(lst, cap):
        if _can_evo(r) and (r['iv_total'] or 0) != 45:
            mark(r['uid_hex'], 'evolve')
        else:
            mark(r['uid_hex'], 'variant_floor')
for lst in fc_pool.values():
    for r in topn(lst, LINE_CAP):
        mark(r['uid_hex'], 'variant_floor')

# 2 shadow
sg = defaultdict(list)
for r in shadows: sg[(r['pokemon_id'], cf(r))].append(r)
def _best_by(lst, key):
    cand = [r for r in lst if r[key] is not None]
    return min(cand, key=lambda r: r[key]) if cand else None
for lst in sg.values():
    mark(topn(lst, 1)[0]['uid_hex'], 'shadow_best')
    for key in ('gl_rank', 'ul_rank'):
        b = _best_by(lst, key)
        if b: mark(b['uid_hex'], 'shadow_best')

# 3 shiny
for r in shinies:
    mark(r['uid_hex'], 'shiny')

# 4 hundo
for r in rows:
    if (r['iv_total'] or 0) == 45: mark(r['uid_hex'], 'hundo')

# 5 rarity
RARE_PIDS = KP.RARE_PIDS
rg = defaultdict(list); rgpf = defaultdict(list)
for r in rows:
    if r['fresh_shiny']:
        continue
    if (r['pokemon_id'] in RARE_PIDS or r['is_legendary'] or r['is_mythical']
            or r['is_ultra_beast'] or r['is_paradox']):
        rg[(r['pokemon_id'], cf(r), 1 if r['fresh_alignment'] == 1 else 0,
            r['fresh_bread_mode'] or 0)].append(r)
        rgpf[(r['pokemon_id'], cf(r))].append(r)
for key, lst in rg.items():
    n = len(lst) if key[0] == 150 else 12
    for r in topn(lst, n): mark(r['uid_hex'], 'rarity')
for lst in rgpf.values():
    for key in ('gl_rank', 'ul_rank'):
        b = _best_by(lst, key)
        if b: mark(b['uid_hex'], 'rarity')

# 6 legacy
lg = defaultdict(list)
for r in rows:
    if r['uid_hex'] in legacy: lg[(r['pokemon_id'], cf(r))].append(r)
for lst in lg.values():
    for r in topn(lst, 3): mark(r['uid_hex'], 'legacy')

# 7 xxl
xg = defaultdict(list)
for r in rows:
    if (r['pokemon_size_category'] or 0) == 5: xg[(r['pokemon_id'], cf(r))].append(r)
for lst in xg.values():
    for metric, n in (('height_m', 2), ('weight_kg', 1)):
        for r in sorted(lst, key=lambda x: -(x[metric] or 0))[:n]: mark(r['uid_hex'], 'xxl')

# 8-13
AE_IDS = KP.AE_IDS
for r in rows:
    if (r['adventure_effects_left'] or 0) > 0 or r['pokemon_id'] in AE_IDS: mark(r['uid_hex'], 'adventure_effect')
    if r['is_zero'] and r['pokemon_id']: mark(r['uid_hex'], 'nundo')
    if r['was_best_buddy_badge'] == 1: mark(r['uid_hex'], 'best_buddy')
    if (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and \
       (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez'): mark(r['uid_hex'], 'origin')
    if r['fresh_is_strong'] == 1: mark(r['uid_hex'], 'mighty')
    if r['fresh_has_location_card'] == 1: mark(r['uid_hex'], 'location_card')

# 14 dex
dg = defaultdict(list)
for r in rows: dg[(r['pokemon_id'], cf(r))].append(r)
for lst in dg.values():
    if len(lst) == 1: mark(lst[0]['uid_hex'], 'dex_only_copy')

# 15 pvp iv
from pvp_iv_rule import qualifies as pvp_iv_qualifies
GL_FLOOR, UL_FLOOR = 1400, 2400
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

# ---- map uid -> row for lookups
row_by_uid = {r['uid_hex']: r for r in rows}
allu = set(row_by_uid)
keepu = set(keep)
transu = allu - keepu

rc = Counter()
for rs in keep.values():
    for w in rs: rc[w]+=1
print("REPRO per-rule:", dict(sorted(rc.items(), key=lambda x:-x[1])))
print("REPRO KEEP=", len(keepu), "TRANSFER=", len(transu))

# Compare against committed policy_reasons.json
committed = json.load(open(os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json')))
mine = {u: sorted(rs) for u, rs in keep.items()}
print("MATCHES committed policy_reasons:", mine == committed, "| committed n=", len(committed), "mine n=", len(mine))
if mine != committed:
    only_mine = set(mine) - set(committed)
    only_com = set(committed) - set(mine)
    print("  only in mine:", len(only_mine), "only in committed:", len(only_com))
    diffr = [u for u in (set(mine)&set(committed)) if mine[u]!=committed[u]]
    print("  reason-diff uids:", len(diffr))
    for u in diffr[:10]:
        print("   ", u, "mine=", mine[u], "committed=", committed[u])

# ===================== CLAIM CHECKS =====================
print("\n========== CLAIM 1: illegitimate evolve tags ==========")
evolve_uids = [u for u,rs in keep.items() if 'evolve' in rs]
print("total evolve-tagged:", len(evolve_uids))
illegit_empty_reach = [u for u in evolve_uids if not reach(row_by_uid[u])]
illegit_hundo = [u for u in evolve_uids if (row_by_uid[u]['iv_total'] or 0)==45]
print("evolve with EMPTY reach():", len(illegit_empty_reach))
print("evolve that are HUNDO (iv_total==45):", len(illegit_hundo))

print("\n========== CLAIM 2: gender dead-ends ==========")
for pid in (415, 757):
    males = [r for r in rows if r['pokemon_id']==pid and r['gender']==1]
    males_evo = [r for r in males if 'evolve' in keep.get(r['uid_hex'], set())]
    print(f"pid{pid}: males={len(males)} tagged_evolve={len(males_evo)}")
# gender-locked species tagged evolve with EMPTY reachable set
glocked = set(GENDER_TERMINALS)
glocked_evolve_empty = [u for u in evolve_uids
                        if row_by_uid[u]['pokemon_id'] in glocked and not reach(row_by_uid[u])]
print("gender-locked mons tagged evolve with EMPTY reachable set:", len(glocked_evolve_empty))
# also: any NULL-gender member of a gender-locked species tagged evolve?
glocked_null_evolve = [u for u in evolve_uids
                       if row_by_uid[u]['pokemon_id'] in glocked and row_by_uid[u]['gender'] not in (1,2)]
print("gender-locked mons with gender NOT in {1,2} tagged evolve:", len(glocked_null_evolve))

print("\n========== CLAIM 3: hundo pre-evos ==========")
# hundo pre-evos = iv_total==45 AND is a pre-evo (can evolve further per evo graph, ignoring gender locks first)
hundo_preevo = [r for r in rows if (r['iv_total'] or 0)==45 and is_preevo.get(r['pokemon_id'])]
print("hundo pre-evos (is_preevo by graph):", len(hundo_preevo))
hp_in_transfer = [r for r in hundo_preevo if r['uid_hex'] in transu]
hp_evolve_only = [r for r in hundo_preevo if keep.get(r['uid_hex'], set())=={'evolve'}]
print("  hundo pre-evos in TRANSFER:", len(hp_in_transfer))
print("  hundo pre-evos with reasons=={'evolve'} only:", len(hp_evolve_only))
# Also test using reach() (gender-aware) as alt definition of pre-evo
hundo_preevo_reach = [r for r in rows if (r['iv_total'] or 0)==45 and reach(r)]
print("ALT hundo pre-evos (reach() non-empty):", len(hundo_preevo_reach),
      "in_transfer:", len([r for r in hundo_preevo_reach if r['uid_hex'] in transu]),
      "evolve-only:", len([r for r in hundo_preevo_reach if keep.get(r['uid_hex'],set())=={'evolve'}]))

print("\n========== CLAIM 4: form-collectibles ==========")
print("FORM_COLLECTIBLE pid count:", len(FORM_COLLECTIBLE))
print("sample FC pids:", sorted(FORM_COLLECTIBLE)[:30])
for pid in (201,327,412,413,666):
    print("  contains pid", pid, ":", pid in FORM_COLLECTIBLE)
# none keep >3 plain per form: count plain kept (variant_floor reason) per (pid,form) for FC pids
fc_kept = defaultdict(int)
for r in plain:
    if not _truly_plain(r): continue
    if r['pokemon_id'] in FORM_COLLECTIBLE and 'variant_floor' in keep.get(r['uid_hex'], set()):
        fc_kept[(r['pokemon_id'], cf(r))] += 1
over3 = {k:v for k,v in fc_kept.items() if v>3}
print("FC (pid,form) keeping >3 plain via variant_floor:", len(over3), dict(list(over3.items())[:10]))
# stricter: count ALL kept truly-plain per (pid,form) regardless of reason
fc_kept_any = defaultdict(int)
for r in plain:
    if not _truly_plain(r): continue
    if r['pokemon_id'] in FORM_COLLECTIBLE and r['uid_hex'] in keepu:
        fc_kept_any[(r['pokemon_id'], cf(r))] += 1
over3_any = {k:v for k,v in fc_kept_any.items() if v>3}
print("FC (pid,form) with >3 truly-plain KEPT (any reason):", len(over3_any), dict(list(over3_any.items())[:10]))

print("\n========== CLAIM 5: gmax-8 cap ==========")
for pid in (68, 9):
    grp = [r for r in rows if r['pokemon_id']==pid]
    kept = [r for r in grp if r['uid_hex'] in keepu]
    print(f"pid{pid}: total={len(grp)} kept={len(kept)}")
    # break down kept by gmax(bread==2) variant_floor vs shiny
    # gmax variant_floor pool: non-shiny non-shadow with fresh_bread_mode==2
    for r in kept:
        rs = sorted(keep.get(r['uid_hex'], set()))
        print(f"    uid={r['uid_hex'][:12]} form={r['form']} cf={cf(r)} bread={r['fresh_bread_mode']} shiny={r['fresh_shiny']} ivt={r['iv_total']} reasons={rs}")
