"""READ-ONLY Hoenn (252-386) audit harness. Mirrors keep_policy.py exactly,
but instruments the line-cap so we can see WHY each Hoenn mon is kept/transferred."""
import sqlite3, json, os, sys
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from pvp_iv_rule import qualifies as pvp_iv_qualifies
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
DB = os.path.join(ROOT, 'pokemon.db')
AE_IDS = {483, 484, 646, 800, 888, 889}
PVP_RANK = 5
GL_FLOOR, UL_FLOOR = 1400, 2400
CPM50 = 0.84029999


def topn(rows, n):
    return sorted(rows, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[:n]


def build_evo_graph(gm, seen_pids):
    by_sp = {p['speciesId']: p for p in gm['pokemon']}
    sp_to_dex = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
    dex_to_sp = {}
    for p in gm['pokemon']:
        sid, d = p['speciesId'], p.get('dex')
        if not d or any(x in sid for x in ('_shadow', '_mega', '_xl')):
            continue
        if d not in dex_to_sp or '_' not in sid:
            dex_to_sp[d] = sid

    def direct(sid):
        evos = ((by_sp.get(sid, {}).get('family', {})) or {}).get('evolutions', []) or []
        return [e for e in evos if sp_to_dex.get(e) in seen_pids]

    def terminals(sid, seen=None):
        if seen is None: seen = set()
        evos = direct(sid)
        if not evos:
            d = sp_to_dex.get(sid)
            return {d} if d else set()
        out = set()
        for e in evos:
            if e in seen: continue
            seen.add(e)
            out |= terminals(e, seen)
        return out

    def distance(sid, depth=0):
        if depth > 6: return 0
        evos = direct(sid)
        return 1 + max((distance(e, depth + 1) for e in evos), default=-1) if evos else 0

    is_pre, term, dist = {}, {}, {}
    for d, sid in dex_to_sp.items():
        is_pre[d] = bool(direct(sid))
        term[d] = terminals(sid)
        dist[d] = distance(sid)
    return is_pre, term, dist, dex_to_sp, sp_to_dex, by_sp


c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
legacy = {e['uid_hex'] for e in json.load(open(os.path.join(ROOT, 'legacy_accurate.json'), encoding='utf-8'))}
try:
    _seen_pids = {e['pid'] for e in json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json')))['entries']}
except Exception:
    _seen_pids = set()
is_preevo, term_of, evo_dist, dex_to_sp, sp_to_dex, by_sp = build_evo_graph(gm, _seen_pids)

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

# 1a non-plain variants
vg = defaultdict(list)
for r in plain:
    if _truly_plain(r): continue
    vg[(r['pokemon_id'], cf(r), r['fresh_costume'] or 0, r['special_bg_id'] or 0,
        r['natural_art_background'] or 0, r['costume_decoration_id'] or 0,
        r['fresh_bread_mode'] or 0)].append(r)
for key, lst in vg.items():
    cap = 8 if key[-1] == 2 else 4
    for r in topn(lst, cap):
        mark(r['uid_hex'], 'variant_floor')

# form-collectibles
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
    if not _truly_plain(r): continue
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
    seen_stage = set()
    for r in topn(lst, cap):
        stage = (r['pokemon_id'], cf(r))
        if stage in seen_stage and _can_evo(r) and (r['iv_total'] or 0) != 45:
            _d = evo_dist.get(r['pokemon_id'], 1) or 1
            mark(r['uid_hex'], f'evolve_{_d}')
        else:
            mark(r['uid_hex'], 'variant_floor')
        seen_stage.add(stage)
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
        rg[(r['pokemon_id'], cf(r), 1 if r['fresh_alignment'] == 1 else 0, r['fresh_bread_mode'] or 0)].append(r)
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
for r in rows:
    if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['gl_stage'], r['gl_rank'], GL_FLOOR, BS):
        mark(r['uid_hex'], 'gl_iv')
    if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['ul_stage'], r['ul_rank'], UL_FLOOR, BS):
        mark(r['uid_hex'], 'ul_iv')
for r in rows:
    if r['iv_atk'] == 0 and r['iv_def'] == 15 and r['iv_sta'] == 15:
        mark(r['uid_hex'], 'pvp_spread')

allu = {r['uid_hex'] for r in rows}
keepu = set(keep)
transu = allu - keepu

# ===== compare to stored policy_reasons.json =====
stored = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json')))
stored_keep = set(stored)
mismatch_keep = (keepu - stored_keep) | (stored_keep - keepu)
print("MY keep:", len(keepu), "STORED keep:", len(stored_keep), "keep-set mismatch:", len(mismatch_keep))

# ===== Hoenn focus =====
hoenn = [r for r in rows if 252 <= r['pokemon_id'] <= 386]
hmap = {r['uid_hex']: r for r in hoenn}
print("\nHoenn held:", len(hoenn))
print("Hoenn TRANSFER:", sum(1 for r in hoenn if r['uid_hex'] in transu))

# expose useful globals for the REPL by dumping to json
out = {
  'keep': {u: sorted(rs) for u, rs in keep.items() if u in hmap},
  'transfer': sorted(u for u in transu if u in hmap),
  'FORM_COLLECTIBLE_hoenn': sorted(p for p in FORM_COLLECTIBLE if 252 <= p <= 386),
}
json.dump(out, open(os.path.join(ROOT, '_hoenn_out.json'), 'w'))
print("FORM_COLLECTIBLE (Hoenn):", out['FORM_COLLECTIBLE_hoenn'])

# Dump evo-graph facts for Hoenn pids
print("\n--- evo graph facts (Hoenn) ---")
for pid in range(252, 387):
    sid = dex_to_sp.get(pid)
    if not sid: continue
    if pid in {r['pokemon_id'] for r in hoenn}:
        print(f"{pid} {sid:14s} is_pre={int(bool(is_preevo.get(pid)))} term={sorted(term_of.get(pid,set()))} dist={evo_dist.get(pid)}")
