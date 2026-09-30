"""INDEPENDENT verifier (Blanco).
Re-derives the keep map from the CURRENT pokemon.db using keep_policy's own
algorithm, WITHOUT calling keep_policy.main() (so the on-disk artifacts are NOT
overwritten). Then diffs my keep-map against the ON-DISK policy_reasons.json,
6_Transfer.txt, and every derived tagset file under system/analysis/tagsets/.

Goal: confirm/refute the finding "on-disk tagsets exactly match an independent
re-derivation of keep_policy". I rebuild the evo graph independently and recompute
all 15 rules + the line cap, then compare to what is already on disk.
"""
import sqlite3, json, os, sys, hashlib
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pvp_iv_rule import qualifies as pvp_iv_qualifies
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS

RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
AE_IDS = {483, 484, 646, 800, 888, 889}
GL_FLOOR, UL_FLOOR = 1400, 2400
LINE_CAP = 3
CPM50 = 0.84029999

DB = os.path.join(HERE, 'pokemon.db')
TD = os.path.join(HERE, 'system', 'analysis', 'tagsets')


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16] if os.path.exists(path) else None


print("DB sha:", sha(DB))
print("on-disk policy_reasons.json sha:", sha(os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json')))
print("on-disk 6_Transfer.txt sha:", sha(os.path.join(TD, '6_Transfer.txt')))


def topn(rows, n):
    return sorted(rows, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[:n]


c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
legacy = {e['uid_hex'] for e in json.load(open(os.path.join(HERE, 'legacy_accurate.json'), encoding='utf-8'))}

# ---- evo graph (rebuilt independently, same semantics) ----
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
    return ((by_sp.get(sid, {}).get('family', {})) or {}).get('evolutions', []) or []


def terminals(sid, seen=None):
    if seen is None:
        seen = set()
    evos = direct(sid)
    if not evos:
        d = sp_to_dex.get(sid)
        return {d} if d else set()
    out = set()
    for e in evos:
        if e in seen:
            continue
        seen.add(e)
        out |= terminals(e, seen)
    return out


is_preevo, term_of = {}, {}
for d, sid in dex_to_sp.items():
    is_preevo[d] = bool(direct(sid))
    term_of[d] = terminals(sid)

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
def _can_evo(r): return bool(reach(r))
def _truly_plain(r):
    return (not (r['fresh_costume'] or 0) and not (r['special_bg_id'] or 0)
            and not (r['natural_art_background'] or 0)
            and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
            and not (r['fresh_bread_mode'] or 0))

# 1a non-plain variants
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
for r in shadows:
    sg[(r['pokemon_id'], cf(r))].append(r)
def _best_by(lst, key):
    cand = [r for r in lst if r[key] is not None]
    return min(cand, key=lambda r: r[key]) if cand else None
for lst in sg.values():
    mark(topn(lst, 1)[0]['uid_hex'], 'shadow_best')
    for key in ('gl_rank', 'ul_rank'):
        b = _best_by(lst, key)
        if b:
            mark(b['uid_hex'], 'shadow_best')

# 3 shiny
for r in shinies:
    mark(r['uid_hex'], 'shiny')

# 4 hundo
for r in rows:
    if (r['iv_total'] or 0) == 45:
        mark(r['uid_hex'], 'hundo')

# 5 rarity
rg = defaultdict(list)
rgpf = defaultdict(list)
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
    for r in topn(lst, n):
        mark(r['uid_hex'], 'rarity')
for lst in rgpf.values():
    for key in ('gl_rank', 'ul_rank'):
        b = _best_by(lst, key)
        if b:
            mark(b['uid_hex'], 'rarity')

# 6 legacy
lg = defaultdict(list)
for r in rows:
    if r['uid_hex'] in legacy:
        lg[(r['pokemon_id'], cf(r))].append(r)
for lst in lg.values():
    for r in topn(lst, 3):
        mark(r['uid_hex'], 'legacy')

# 7 xxl
xg = defaultdict(list)
for r in rows:
    if (r['pokemon_size_category'] or 0) == 5:
        xg[(r['pokemon_id'], cf(r))].append(r)
for lst in xg.values():
    for metric, n in (('height_m', 2), ('weight_kg', 1)):
        for r in sorted(lst, key=lambda x: -(x[metric] or 0))[:n]:
            mark(r['uid_hex'], 'xxl')

# 8-13
for r in rows:
    if (r['adventure_effects_left'] or 0) > 0 or r['pokemon_id'] in AE_IDS:
        mark(r['uid_hex'], 'adventure_effect')
    if r['is_zero'] and r['pokemon_id']:
        mark(r['uid_hex'], 'nundo')
    if r['was_best_buddy_badge'] == 1:
        mark(r['uid_hex'], 'best_buddy')
    if (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and \
       (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez'):
        mark(r['uid_hex'], 'origin')
    if r['fresh_is_strong'] == 1:
        mark(r['uid_hex'], 'mighty')
    if r['fresh_has_location_card'] == 1:
        mark(r['uid_hex'], 'location_card')

# 14 dex
dg = defaultdict(list)
for r in rows:
    dg[(r['pokemon_id'], cf(r))].append(r)
for lst in dg.values():
    if len(lst) == 1:
        mark(lst[0]['uid_hex'], 'dex_only_copy')

# 15 pvp
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

allu = {r['uid_hex'] for r in rows}
keepu = set(keep)
transu = allu - keepu
print("\n=== MY re-derivation ===")
print("in_bag=%d KEEP=%d TRANSFER=%d" % (len(allu), len(keepu), len(transu)))

# ---------- COMPARE TO ON-DISK ARTIFACTS ----------
shipped = json.load(open(os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json')))
shipped = {u: set(v) for u, v in shipped.items()}
mine = {u: set(v) for u, v in keep.items()}

sk, mk = set(shipped), set(mine)
print("\n=== A. policy_reasons.json fidelity ===")
print("shipped keep uids:", len(sk), " mine:", len(mk))
print("only in shipped:", len(sk - mk), sorted(sk - mk)[:5])
print("only in mine:", len(mk - sk), sorted(mk - sk)[:5])
mismatch = [u for u in (sk & mk) if shipped[u] != mine[u]]
print("reason-set MISMATCHES:", len(mismatch))
for u in mismatch[:10]:
    print("   ", u, "shipped=", sorted(shipped[u]), "mine=", sorted(mine[u]))

# B. 6_Transfer.txt fidelity (this is what keep_policy actually writes)
disk_transfer = set(open(os.path.join(TD, '6_Transfer.txt')).read().split())
print("\n=== B. 6_Transfer.txt fidelity ===")
print("disk transfer:", len(disk_transfer), " mine:", len(transu))
print("transu == disk_transfer:", transu == disk_transfer)
print("only on disk:", len(disk_transfer - transu), sorted(disk_transfer - transu)[:5])
print("only mine:", len(transu - disk_transfer), sorted(transu - disk_transfer)[:5])

# partition sanity
print("\n=== C. partition sanity ===")
print("in_bag=%d keep=%d transfer=%d  keep&transfer=%d  keep|transfer covers bag=%s"
      % (len(allu), len(keepu), len(transu), len(keepu & transu), (keepu | transu) == allu))
empty_reason = [u for u in keepu if not mine[u]]
print("keep uids with EMPTY reason list:", len(empty_reason))
keep_not_in_bag = keepu - allu
trans_not_in_bag = transu - allu
print("keep uids not in bag:", len(keep_not_in_bag), " transfer not in bag:", len(trans_not_in_bag))

# D. derived tagsets fidelity (rebuild each KEEP tag from my keep-map and the SQL rules)
print("\n=== D. derived tagset files fidelity ===")
# rebuild reason->tagfile per build_tagsets mapping, MINUS transfer
def load_tag(fn):
    p = os.path.join(TD, fn)
    return set(open(p).read().split()) if os.path.exists(p) else set()

# Evolve.txt = uids with 'evolve' reason, minus transfer
my_evolve = {u for u, rs in mine.items() if 'evolve' in rs} - transu
disk_evolve = load_tag('Evolve.txt')
print("Evolve: mine=%d disk=%d equal=%s" % (len(my_evolve), len(disk_evolve), my_evolve == disk_evolve))

# Hundo.txt = SQL iv_total=45 in_bag=1 MINUS transfer
hundo_sql = {r['uid_hex'] for r in rows if (r['iv_total'] or 0) == 45} - disk_transfer
disk_hundo = load_tag('Hundo.txt')
print("Hundo: rule=%d disk=%d equal=%s" % (len(hundo_sql), len(disk_hundo), hundo_sql == disk_hundo))

# Nundo
nundo_sql = {r['uid_hex'] for r in rows if r['is_zero'] == 1 and r['pokemon_id'] != 0} - disk_transfer
print("Nundo: rule=%d disk=%d equal=%s" % (len(nundo_sql), len(load_tag('Nundo.txt')), nundo_sql == load_tag('Nundo.txt')))

# Event = costume/special_bg/art_bg/location_card MINUS transfer
event_sql = {r['uid_hex'] for r in rows if (r['fresh_costume'] or 0) != 0 or (r['special_bg_id'] or 0) != 0
             or (r['natural_art_background'] or 0) != 0 or r['fresh_has_location_card'] == 1} - disk_transfer
print("Event: rule=%d disk=%d equal=%s" % (len(event_sql), len(load_tag('Event.txt')), event_sql == load_tag('Event.txt')))

# Best Buddy
bb_sql = {r['uid_hex'] for r in rows if r['was_best_buddy_badge'] == 1} - disk_transfer
print("Best_Buddy: rule=%d disk=%d equal=%s" % (len(bb_sql), len(load_tag('Best_Buddy.txt')), bb_sql == load_tag('Best_Buddy.txt')))

# Traded by E+F
ef_sql = {r['uid_hex'] for r in rows if (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1)
          and (r['original_owner_name'] or '').lower() in ('ethanmateovz', 'florandez')} - disk_transfer
print("Traded_by_E+F: rule=%d disk=%d equal=%s" % (len(ef_sql), len(load_tag('Traded_by_E+F.txt')), ef_sql == load_tag('Traded_by_E+F.txt')))

# GL IV / UL IV
gl_sql = {r['uid_hex'] for r in rows if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['gl_stage'], r['gl_rank'], GL_FLOOR, BS)} - disk_transfer
ul_sql = {r['uid_hex'] for r in rows if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['ul_stage'], r['ul_rank'], UL_FLOOR, BS)} - disk_transfer
print("GL_IV: rule=%d disk=%d equal=%s" % (len(gl_sql), len(load_tag('GL_IV.txt')), gl_sql == load_tag('GL_IV.txt')))
print("UL_IV: rule=%d disk=%d equal=%s" % (len(ul_sql), len(load_tag('UL_IV.txt')), ul_sql == load_tag('UL_IV.txt')))

# XXL (top-2 height + top-1 weight per (pid, form or 0)) MINUS transfer
xxl_groups = defaultdict(list)
for r in rows:
    if (r['pokemon_size_category'] or 0) == 5:
        xxl_groups[(r['pokemon_id'], r['form'] or 0)].append(r)
xxl_set = set()
for k, lst in xxl_groups.items():
    for metric, nn in (('height_m', 2), ('weight_kg', 1)):
        for r in sorted(lst, key=lambda x: -(x[metric] or 0))[:nn]:
            xxl_set.add(r['uid_hex'])
xxl_set -= disk_transfer
print("XXL: rule=%d disk=%d equal=%s" % (len(xxl_set), len(load_tag('XXL.txt')), xxl_set == load_tag('XXL.txt')))

# Legacy Moves (top-3 by IV per (pid, form or 0) among legacy) MINUS transfer
lgb = defaultdict(list)
for r in rows:
    if r['uid_hex'] in legacy:
        lgb[(r['pokemon_id'], r['form'] or 0)].append(r)
leg_set = set()
for grp in lgb.values():
    for r in sorted(grp, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))[:3]:
        leg_set.add(r['uid_hex'])
leg_set -= disk_transfer
print("Legacy_Moves: rule=%d disk=%d equal=%s" % (len(leg_set), len(load_tag('Legacy_Moves.txt')), leg_set == load_tag('Legacy_Moves.txt')))

# Transfer.txt vs 6_Transfer.txt (build_tagsets re-emits)
print("Transfer.txt == 6_Transfer.txt:", load_tag('Transfer.txt') == disk_transfer)

c.close()
print("\nDONE")
