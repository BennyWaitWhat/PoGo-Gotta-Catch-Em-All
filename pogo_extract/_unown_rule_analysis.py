"""Unown-rule collection-wide displacement analysis.

For each (pid, cf) form: if in-bag SHINIES (iv not in 0,45) counted toward the
per-form top-3 PLAIN cap, which plains kept ONLY by variant_floor get displaced?

Two independent derivations of the DISPLACEABLE set K:
  (A) policy_reasons.json: reason set EXACTLY {"variant_floor"}.
  (B) raw from-scratch replication of EVERY keep rule in keep_policy.py.
We assert A == B, then run the top-3 simulation.
"""
import sqlite3, json, os, sys
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from pvp_iv_rule import qualifies as pvp_iv_qualifies, pvid, GL_CAP, UL_CAP, maxcp as pvp_maxcp, READY_RANK, VIABILITY_MARGIN
from costume_forms import is_costume_form
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
DB = os.path.join(ROOT, 'pokemon.db')

AE_IDS = {483, 484, 646, 800, 888, 889, 890}
PROTECTED_KEEP_ALL = {172}
GL_FLOOR, UL_FLOOR = 1400, 2400


def topn(rows, n):
    return sorted(rows, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[:n]


# ---- replicate build_evo_graph exactly ----
def build_evo_graph(gm, seen_pids):
    by_sp = {p['speciesId']: p for p in gm['pokemon']}
    sp_to_dex = {p['speciesId']: p.get('dex') for p in gm['pokemon']}

    def _bst(sid):
        b = (by_sp.get(sid, {}) or {}).get('baseStats', {}) or {}
        return b.get('atk', 0) + b.get('def', 0) + b.get('hp', 0)

    EVO_FIX = {'poltchageist': ['sinistcha'], 'doublade': ['aegislash_shield']}

    def direct(sid):
        fixed = EVO_FIX.get(sid, [])
        evos = (((by_sp.get(sid, {}).get('family', {})) or {}).get('evolutions', []) or []) + fixed
        return [e for e in evos
                if sp_to_dex.get(e) in seen_pids
                and e in by_sp and (e in fixed or _bst(e) >= _bst(sid))]

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
        if depth > 6:
            return 0
        evos = direct(sid)
        return 1 + max((distance(e, depth + 1) for e in evos), default=-1) if evos else 0

    is_pre, term, dist = {}, {}, {}
    for sid in by_sp:
        is_pre[sid] = bool(direct(sid))
        term[sid] = terminals(sid)
        dist[sid] = distance(sid)
    return is_pre, term, dist, sp_to_dex


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
    gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    legacy = {e['uid_hex'] for e in json.load(open(os.path.join(ROOT, 'legacy_accurate.json'), encoding='utf-8'))}
    try:
        _seen_pids = {e['pid'] for e in json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json')))['entries']}
    except Exception:
        _seen_pids = set()
    is_pre_sp, term_sp, dist_sp, sp_to_dex = build_evo_graph(gm, _seen_pids)

    def _sid(r):
        return pvid(r['species_name'], r['form'] or 0)

    # ---- form fold cf(r) -- replicate exactly ----
    _REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
    def _is_regional_code(nm, f):
        return any(x in pvid(nm, f) for x in _REGSUF)
    _basecnt = defaultdict(Counter)
    for r in rows:
        _f = r['form'] or 0
        _reg = (r['form_region'] or '').strip().lower()
        if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], _f):
            _basecnt[r['pokemon_id']][_f] += 1
    base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}
    def cf(r):
        _f = r['form'] or 0
        return base_form.get(r['pokemon_id'], _f) if _f == 0 else _f

    GENDER_TERMINALS = {
        415: {1: set(), 2: {416}}, 757: {1: set(), 2: {758}},
        361: {1: {362}, 2: {478, 362}}, 281: {1: {475, 282}, 2: {282}},
        280: {1: {475, 282}, 2: {282}}, 412: {1: {414}, 2: {413}},
    }
    def reach(r):
        gt = GENDER_TERMINALS.get(r['pokemon_id'])
        if gt is not None:
            return gt.get(r['gender'], set())
        sid = _sid(r)
        return term_sp.get(sid, set()) if is_pre_sp.get(sid) else set()
    def _can_evo(r):
        return bool(reach(r))
    def _truly_plain(r):
        return (not (r['fresh_costume'] or 0) and not (r['special_bg_id'] or 0)
                and not (r['natural_art_background'] or 0)
                and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
                and (r['fresh_bread_mode'] or 0) not in (1, 2)
                and not is_costume_form(r['fresh_form']))

    # ===== RAW from-scratch keep replication (mirror keep_policy.main) =====
    keep = defaultdict(set)
    def mark(uid, why): keep[uid].add(why)

    shadows = [r for r in rows if r['fresh_alignment'] == 1]
    shinies = [r for r in rows if r['fresh_shiny']]
    plain = [r for r in rows if r['fresh_alignment'] != 1 and not r['fresh_shiny']]

    # 1a cosmetic variant floor
    vg = defaultdict(list)
    for r in plain:
        if _truly_plain(r):
            continue
        vg[(r['pokemon_id'], cf(r), r['fresh_costume'] or 0, r['special_bg_id'] or 0,
            r['natural_art_background'] or 0, r['costume_decoration_id'] or 0,
            (r['fresh_bread_mode'] if (r['fresh_bread_mode'] or 0) in (1, 2) else 0))].append(r)
    for key, lst in vg.items():
        cap = 8 if key[-1] in (1, 2) else int(os.environ.get('COSMETIC_CAP') or 3)
        for r in topn(lst, cap):
            mark(r['uid_hex'], 'variant_floor')

    # 1b plain per (stage,form) cap with Unown special
    LINE_CAP = 3
    _unown_shiny = Counter((r['pokemon_id'], cf(r)) for r in shinies
                           if r['pokemon_id'] == 201 and (r['iv_total'] or 0) != 45)
    def _line_cap(key):
        return max(0, LINE_CAP - _unown_shiny.get((key[0], key[1]), 0)) if key[0] == 201 else LINE_CAP
    def _stage_key(r):
        g = r['gender'] if r['pokemon_id'] in GENDER_TERMINALS else 0
        return (r['pokemon_id'], cf(r), g)
    stage_pool = defaultdict(list)
    for r in plain:
        if _truly_plain(r):
            stage_pool[_stage_key(r)].append(r)
    def _evo_ok(r):
        iv = r['iv_total'] or 0
        return _can_evo(r) and iv not in (0, 45) and r['pokemon_id'] not in RARE_PIDS
    evo_cands = []
    for _key, lst in stage_pool.items():
        _pool = [r for r in lst if (r['iv_total'] or 0) != 45] if _key[0] == 201 else lst
        for i, r in enumerate(topn(_pool, _line_cap(_key))):
            if i >= 1 and _evo_ok(r):
                evo_cands.append(r)
            else:
                mark(r['uid_hex'], 'variant_floor')
    term_best = defaultdict(lambda: -1)
    for r in plain:
        if _truly_plain(r) and not _can_evo(r):
            term_best[r['pokemon_id']] = max(term_best[r['pokemon_id']], r['iv_total'] or 0)
    for r in sorted(evo_cands, key=lambda x: -(x['iv_total'] or 0)):
        _riv = r['iv_total'] or 0
        _done = False
        for t in reach(r):
            if _riv > term_best[t]:
                mark(r['uid_hex'], f"evolve_{dist_sp.get(_sid(r), 1) or 1}")
                term_best[t] = _riv
                _done = True
                break
        if not _done:
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

    # 3 shiny top-20
    shg = defaultdict(list)
    for r in shinies:
        shg[(r['pokemon_id'], cf(r))].append(r)
    for lst in shg.values():
        for r in topn(lst, 20):
            mark(r['uid_hex'], 'shiny')

    # 4 hundo
    for r in rows:
        if (r['iv_total'] or 0) == 45: mark(r['uid_hex'], 'hundo')

    # 5 rarity
    rg = defaultdict(list); rgpf = defaultdict(list)
    for r in rows:
        if r['fresh_shiny']: continue
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
    LEGACY_SPECIES_CAP = {359: 10}
    _lcap = defaultdict(list)
    for r in rows:
        if r['uid_hex'] not in legacy: continue
        if r['pokemon_id'] in LEGACY_SPECIES_CAP:
            _lcap[r['pokemon_id']].append(r)
        else:
            mark(r['uid_hex'], 'legacy')
    for _pid, _lst in _lcap.items():
        _ks = set()
        for r in _lst:
            if (r['fresh_shiny'] or r['fresh_alignment'] == 1 or (r['fresh_costume'] or 0)
                    or is_costume_form(r['fresh_form']) or (r['iv_total'] or 0) == 45):
                _ks.add(r['uid_hex'])
        for _key in ('gl_rank', 'ul_rank'):
            _b = _best_by(_lst, _key)
            if _b: _ks.add(_b['uid_hex'])
        for r in topn([r for r in _lst if r['uid_hex'] not in _ks],
                      max(0, LEGACY_SPECIES_CAP[_pid] - len(_ks))):
            _ks.add(r['uid_hex'])
        for _u in _ks:
            mark(_u, 'legacy')

    # 7 xxl
    xg = defaultdict(list)
    for r in rows:
        if (r['pokemon_size_category'] or 0) == 5: xg[(r['pokemon_id'], cf(r))].append(r)
    for lst in xg.values():
        for metric, n in (('height_m', 2), ('weight_kg', 1)):
            for r in sorted(lst, key=lambda x: -(x[metric] or 0))[:n]: mark(r['uid_hex'], 'xxl')

    # 8-13 keep-all purposes
    for r in rows:
        if (r['adventure_effects_left'] or 0) > 0 or r['pokemon_id'] in AE_IDS: mark(r['uid_hex'], 'adventure_effect')
        if r['is_zero'] and r['pokemon_id']: mark(r['uid_hex'], 'nundo')
        if r['was_best_buddy_badge'] == 1: mark(r['uid_hex'], 'best_buddy')
        if (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and \
           (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez'): mark(r['uid_hex'], 'origin')
        if r['fresh_is_strong'] == 1: mark(r['uid_hex'], 'mighty')
        if r['fresh_has_location_card'] == 1: mark(r['uid_hex'], 'location_card')
        if r['pokemon_id'] in PROTECTED_KEEP_ALL: mark(r['uid_hex'], 'protected')

    # 14 dex only copy
    dg = defaultdict(list)
    for r in rows: dg[(r['pokemon_id'], cf(r))].append(r)
    for lst in dg.values():
        if len(lst) == 1: mark(lst[0]['uid_hex'], 'dex_only_copy')

    # 15 pvp iv
    for r in rows:
        if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'],
                            r['iv_sta'], r['gl_stage'], r['gl_rank'], GL_FLOOR, BS, r['cp'], GL_CAP):
            mark(r['uid_hex'], 'gl_iv')
        if pvp_iv_qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'],
                            r['iv_sta'], r['ul_stage'], r['ul_rank'], UL_FLOOR, BS, r['cp'], UL_CAP):
            mark(r['uid_hex'], 'ul_iv')
    for r in rows:
        if r['iv_atk'] == 0 and r['iv_def'] == 15 and r['iv_sta'] == 15:
            mark(r['uid_hex'], 'pvp_spread')

    # 15b pvp rank safety net
    def _viable(stage, cap):
        return bool(stage) and pvp_maxcp(stage, BS) > cap + VIABILITY_MARGIN
    for r in rows:
        if (r['gl_rank'] is not None and r['gl_rank'] <= READY_RANK and _viable(r['gl_stage'], GL_CAP)) or \
           (r['ul_rank'] is not None and r['ul_rank'] <= READY_RANK and _viable(r['ul_stage'], UL_CAP)):
            mark(r['uid_hex'], 'pvp_rank')

    # ===== K_raw: plains whose RAW reason set == EXACTLY {variant_floor} =====
    rowmap = {r['uid_hex']: r for r in rows}
    K_raw = {u for u, rs in keep.items() if rs == {'variant_floor'} and _truly_plain(rowmap[u])}

    # ===== K_reasons: from policy_reasons.json =====
    pr = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json')))
    K_reasons = {u for u, rs in pr.items() if rs == ['variant_floor']}
    # restrict to truly-plain in-bag (json may include cosmetic variant_floor singletons)
    K_reasons_plain = {u for u in K_reasons if u in rowmap and _truly_plain(rowmap[u])}

    print(f"# rows in_bag={len(rows)}")
    print(f"# K_raw (raw exactly-variant_floor & truly_plain)      = {len(K_raw)}")
    print(f"# K_reasons (json exactly [variant_floor])             = {len(K_reasons)}")
    print(f"# K_reasons_plain (json & truly_plain)                 = {len(K_reasons_plain)}")
    print(f"# K_raw == K_reasons_plain ?  {K_raw == K_reasons_plain}")
    only_raw = K_raw - K_reasons_plain
    only_rsn = K_reasons_plain - K_raw
    if only_raw: print(f"#   only in raw ({len(only_raw)}): {[ (rowmap[u]['species_name'], rowmap[u]['pokemon_id']) for u in list(only_raw)[:10]]}")
    if only_rsn: print(f"#   only in reasons ({len(only_rsn)}): {[ (rowmap[u]['species_name'], rowmap[u]['pokemon_id']) for u in list(only_rsn)[:10]]}")
    # also: how many json [variant_floor] are NOT truly_plain (cosmetic singletons)?
    cos = K_reasons - K_reasons_plain
    print(f"# json [variant_floor] that are cosmetic (not plain)  = {len(cos)}")

    # Use K_raw as authoritative (fully independent from-scratch).
    K = K_raw

    # The cap is enforced per _stage_key = (pid, cf, gender) -- gender splits the cap
    # ONLY for the GENDER_TERMINALS species; everything else uses gender=0. The Unown
    # rule ("shinies count toward the per-form top-3 plain cap") generalizes to: within
    # each cap unit, the new top-3 is taken over (plains-in-unit UNION shinies-in-unit).
    # Displacer shinies S keyed by the SAME _stage_key so a shiny competes in its own
    # gender bucket (a female shiny can't bump a male plain in a gender-split species).
    S = defaultdict(list)
    for r in shinies:
        if (r['iv_total'] or 0) not in (0, 45):
            S[_stage_key(r)].append(r)

    # group K by _stage_key (the cap unit)
    Kg = defaultdict(list)
    for u in K:
        r = rowmap[u]
        Kg[_stage_key(r)].append(r)

    # ===== simulate new top-3 of (K union S) per CAP UNIT; displaced = K not in top3 =====
    # Aggregate results to (pid, cf) for reporting (a gender-split species reports the
    # union of its per-gender displacements under one (pid,cf) instance).
    by_form = defaultdict(lambda: {'displaced': [], 'shinies_in': [], 'K': [], 'S': []})
    for key, kl in Kg.items():
        sl = S.get(key, [])
        pidcf = (key[0], key[1])
        by_form[pidcf]['K'].extend(kl)
        by_form[pidcf]['S'].extend(sl)
        if not sl:
            continue
        union = kl + sl
        new_top3 = topn(union, 3)
        top3_ids = {id(x) for x in new_top3}
        displaced = [r for r in kl if id(r) not in top3_ids]
        shinies_in_top3 = [r for r in new_top3 if id(r) in {id(s) for s in sl}]
        by_form[pidcf]['displaced'].extend(displaced)
        by_form[pidcf]['shinies_in'].extend(shinies_in_top3)

    instances = []
    total_displaced = 0
    for pidcf, d in sorted(by_form.items()):
        displaced = d['displaced']
        if not displaced:
            continue
        # best displacer = highest-IV shiny that actually took a top-3 slot in any unit
        if d['shinies_in']:
            best_disp_iv = max(r['iv_total'] or 0 for r in d['shinies_in'])
        else:
            best_disp_iv = max(r['iv_total'] or 0 for r in d['S'])
        lowest_disp_plain_iv = min(r['iv_total'] or 0 for r in displaced)
        sp = displaced[0]['species_name']
        instances.append({
            'species': sp,
            'pokemon_id': pidcf[0],
            'form': pidcf[1],
            'best_displacer_shiny_iv_pct': round(best_disp_iv / 45 * 100),
            'lowest_displaced_plain_iv_pct': round(lowest_disp_plain_iv / 45 * 100),
            'n_displaced': len(displaced),
            '_n_K': len(d['K']),
            '_n_S': len(d['S']),
            '_displaced_iv': sorted(r['iv_total'] for r in displaced),
            '_K_iv': sorted((r['iv_total'] for r in d['K']), reverse=True),
            '_S_iv': sorted((r['iv_total'] for r in d['S']), reverse=True),
        })
        total_displaced += len(displaced)

    print(f"\n# === RESULTS ===")
    print(f"# total_instances = {len(instances)}")
    print(f"# total_plain_displaced = {total_displaced}")
    print(f"# reasons_accumulate = True  (mark() uses keep[uid].add(why); defaultdict(set))")
    print(json.dumps(instances, indent=2))


if __name__ == '__main__':
    main()
