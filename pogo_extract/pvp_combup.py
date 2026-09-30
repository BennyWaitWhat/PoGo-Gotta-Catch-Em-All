"""PvP COMB-UP -- the copy to EVOLVE for a better Great / Ultra League copy of a stage (user 2026-09-24: "im basically
asking for the scan to be expanded to everyone so all ul and gl get combed up" + "I don't want to waste time catching
pokemon just to lose opportunities").

Best GL / UL (keep_policy 15d) keeps ONE copy per PvP identity: the best at ANY stage it can reach. On a branching or
multi-stage line that one copy covers one target: the Eevee that makes the best Jolteon is not the one that makes the
best Umbreon, and the other stages' opportunities rode on luck (a plain IV slot, the shiny cap) -- 9 GL targets did on
2026-09-24 (three Eevees, a Kadabra, a Murkrow, three shinies). This keeps, and labels, the right copy for EVERY stage.

For each league (GL, UL) and each TARGET (a PvP stage, shadow or not -- a shadow evolves into a shadow):
  * candidates = copies whose chain reaches the target (rank_cache's per-stage ranks) AND that can actually become it
    (later_fn: keep_policy.pvp_later_stages -- form, costume, gender), whose target stage can reach the league cap,
    and that would still FIT the league there at their true level (pvp_iv_rule.fits -- CP only goes up);
  * it is a comb-up when the best candidate's rank at the target beats the best copy you already own AS the target
    that can enter the league (or you own none), and the rank is inside the Best GL/UL floor (keep_config
    pvp.best_rank_floor) -- the legendary roster is exempt, exactly as for Best GL/UL;
  * NEVER a candidate (evolving would destroy something): the copy that is your best at its OWN stage in either league,
    an own-stage top-5 spread, a copy with a legacy move (moves reroll on evolution), the only copy of its form, the
    only shiny of its form ("do not cull my only shinies" -- evolving it would leave that stage with none), a
    protected species. The next-best candidate is considered instead;
  * ONE copy, ONE target: targets are filled best-rank first and a copy already promised to another stage is skipped
    (an Eevee can become one eeveelution), so every opportunity has its own copy.

ONE definition: keep_policy (reasons pvp_combup_gl / pvp_combup_ul -> tags 'Evolve for GL' / 'Evolve for UL'),
preflight_transfer, audit_cull, _lawcheck, audit_tags_membership and audit_tag_truth all call pick() on the same inputs.
"""
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LEAGUES = ('gl', 'ul')


def _g(r, k):
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def pick(rows, later_fn, BS, floor, rare_pids, legacy_uids=(), protected_pids=()):
    """{'gl': {uid: (target_stage, rank_there, your_best_rank_there_or_None)}, 'ul': {...}} -- see the module doc.
    `rows` may be sqlite3.Row or dict; the form grouping is computed HERE (granular_tags._base_form_map, keep_policy's
    form-0 normalisation), never taken from the caller, so every caller gets the identical answer."""
    from pvp_iv_rule import pvid, chain_stage_ranks, fits, maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN
    import keep_config, granular_tags
    caps = {'gl': GL_CAP, 'ul': UL_CAP}
    rows = [r if isinstance(r, dict) else keep_config.row_dict(r) for r in rows]
    _base = granular_tags._base_form_map(rows)
    cf = lambda r: (r.get('form') or 0) or _base.get(r.get('pokemon_id'), 0)
    legacy_uids, protected_pids = set(legacy_uids), set(protected_pids)
    reach_cap = {}

    def viable(st, cap):
        k = (st, cap)
        if k not in reach_cap:
            reach_cap[k] = maxcp(st, BS) > cap + VIABILITY_MARGIN
        return reach_cap[k]

    form_count, shiny_count = defaultdict(int), defaultdict(int)
    for r in rows:
        form_count[(_g(r, 'pokemon_id'), cf(r))] += 1
        if _g(r, 'fresh_shiny'):
            shiny_count[(_g(r, 'pokemon_id'), cf(r))] += 1
    own_of = {r['uid_hex']: pvid(_g(r, 'species_name'), _g(r, 'form') or 0) for r in rows}
    sh_of = {r['uid_hex']: 1 if _g(r, 'fresh_alignment') == 1 else 0 for r in rows}
    chains = {lg: {r['uid_hex']: chain_stage_ranks(r, lg) for r in rows} for lg in LEAGUES}

    # pass 1: what you already own AS each stage (own-stage rank, entering the league), and who holds that best
    owned = {lg: {} for lg in LEAGUES}
    for lg in LEAGUES:
        cap = caps[lg]
        for r in rows:
            u = r['uid_hex']
            for st, rk in chains[lg][u]:
                if st != own_of[u] or not viable(st, cap) or not fits(r, st, cap, BS):
                    continue
                k = (st, sh_of[u])
                if k not in owned[lg] or (rk, u) < owned[lg][k]:
                    owned[lg][k] = (rk, u)
    own_best = {u for lg in LEAGUES for (_rk, u) in owned[lg].values()}

    def blocked(r):
        u = r['uid_hex']
        if u in own_best or u in legacy_uids or _g(r, 'pokemon_id') in protected_pids:
            return True
        if form_count[(_g(r, 'pokemon_id'), cf(r))] == 1:
            return True
        if _g(r, 'fresh_shiny') and shiny_count[(_g(r, 'pokemon_id'), cf(r))] == 1:
            return True                                  # the only shiny of its form stays where it is
        for lg in LEAGUES:                               # an own-stage top-5 spread is an asset where it stands
            for st, rk in chains[lg][u]:
                if st == own_of[u] and rk <= 5 and viable(st, caps[lg]) and fits(r, st, caps[lg], BS):
                    return True
        return False

    # pass 2: every candidate per (league, target), best rank first
    cands = {lg: defaultdict(list) for lg in LEAGUES}
    later_cache = {}
    for r in rows:
        u = r['uid_hex']
        if blocked(r):
            continue
        for lg in LEAGUES:
            cap = caps[lg]
            for st, rk in chains[lg][u]:
                if st == own_of[u] or not viable(st, cap):
                    continue
                if u not in later_cache:
                    later_cache[u] = set(later_fn(r) or ())
                if st not in later_cache[u] or not fits(r, st, cap, BS):
                    continue
                cands[lg][(st, sh_of[u])].append((rk, u, r))
    # assignment: targets in order of their best achievable rank; one copy serves one target STAGE (the same stage in
    # both leagues is one evolution, so it may serve both)
    todo = []
    for lg in LEAGUES:
        for k, lst in cands[lg].items():
            lst.sort(key=lambda x: (x[0], x[1]))
            todo.append((lst[0][0], lg, k[0], k[1], lst))
    todo.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    promised = {}                                        # uid -> the stage it is promised to become
    out = {lg: {} for lg in LEAGUES}
    for _best, lg, st, sh, lst in todo:
        cur = owned[lg].get((st, sh))
        for rk, u, r in lst:
            if cur is not None and rk >= cur[0]:
                break                                    # no candidate left that beats what you own there
            if rk > floor and _g(r, 'pokemon_id') not in rare_pids:
                break                                    # outside the top-15% cut (candidates are rank-sorted)
            if promised.get(u, st) != st:
                continue                                 # already promised to another stage -- next-best copy
            promised[u] = st
            out[lg][u] = (st, rk, cur[0] if cur else None)
            break
    return out


_DEFAULT = []


def pick_default(rows):
    """pick() with the pipeline's standard inputs -- the evolution graph keep_policy builds (pvp_later_stages over
    pvpoke_gamemaster.json + the live dex), legacy_accurate.json, keep_config's floor and protected species, the
    legendary roster. Mirrors (preflight, audits) call this; keep_policy passes its own graph (same two files)."""
    import sys
    if not _DEFAULT:
        scr = os.path.join(HERE, 'system', 'scripts')
        if scr not in sys.path:
            sys.path.insert(0, scr)
        import keep_config, keep_policy
        from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
        gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
        seen = {e['pid'] for e in json.load(open(os.path.join(HERE, 'pokedex_hundos_live.json')))['entries']}
        graph = keep_policy.build_evo_graph(gm, seen, with_all=True)
        _DEFAULT.append(dict(
            later_fn=lambda r: keep_policy.pvp_later_stages(r, graph),
            BS={p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']},
            floor=keep_config.pvp('best_rank_floor'),
            rare=LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS,
            legacy={e['uid_hex'] for e in json.load(open(os.path.join(HERE, 'legacy_accurate.json'), encoding='utf-8'))},
            protected=keep_config.protected_pids()))
    d = _DEFAULT[0]
    return pick(rows, d['later_fn'], d['BS'], d['floor'], d['rare'], d['legacy'], d['protected'])


if __name__ == '__main__':
    # self-check on a toy line: two pre-evos, one target; the better one is picked, a blocked one never is, and a
    # copy cannot be promised to two different stages.
    import pvp_iv_rule as P
    BS = {'a': {'atk': 100, 'def': 100, 'hp': 100}, 'b': {'atk': 200, 'def': 200, 'hp': 200}, 'c': {'atk': 190, 'def': 190, 'hp': 190}}
    real = (P.fits, P.maxcp)
    P.fits = lambda r, st, cap, bs: True
    P.maxcp = lambda st, bs: 9999
    try:
        mk = lambda u, ch, pid=1: {'uid_hex': u, 'pokemon_id': pid, 'species_name': 'A', 'form': 0, 'fresh_alignment': 0,
                                   'gl_chain_ranks': ch, 'ul_chain_ranks': ''}
        rows = [mk('x1', 'a:100(9%);b:40(99%)'),   # x1 is your best A itself -> never a candidate
                mk('x2', 'a:800(9%);b:20(99%);c:30(99%)'), mk('x3', 'a:700(9%);b:10(99%)'),
                dict(mk('own_b', 'b:300(90%)'), species_name='B', pokemon_id=2),
                dict(mk('own_b2', 'b:400(90%)'), species_name='B', pokemon_id=2)]
        res = pick(rows, lambda r: {'b', 'c'}, BS, 614, set(), legacy_uids={'x3'})
        assert res['gl'] == {'x2': ('b', 20, 300)}, res            # x3 (legacy) blocked; x2 beats x1; c only via x2 -> taken
        res = pick(rows, lambda r: {'b', 'c'}, BS, 614, set())
        assert res['gl']['x3'] == ('b', 10, 300) and res['gl']['x2'] == ('c', 30, None), res   # x3 -> b, x2 freed for c
        res = pick(rows, lambda r: {'b', 'c'}, BS, 15, set())
        assert res['gl'] == {'x3': ('b', 10, 300)}, res            # the floor stops rank 30
    finally:
        P.fits, P.maxcp = real
    print('pvp_combup self-check OK')
