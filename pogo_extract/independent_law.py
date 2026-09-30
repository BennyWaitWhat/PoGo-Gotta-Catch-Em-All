"""INDEPENDENT LAW RE-DERIVATIONS for the two keep rules the engine implements with ONE shared selector (H08, 2026-09-29).

WHY THIS FILE EXISTS. The Transfer pile is guarded by audits that RE-DERIVE each keep rule -- but for two rules every
"re-derivation" called the engine's own function:
  * LAW bucket 1, one nundo per look (the one caught farthest from Atlanta first): keep_policy, preflight_transfer and
    audit_cull all called trophy_pick.pick_nundos, and audit_tags_membership subtracts the pile before comparing the
    Nundo tag. 45 of the 47 kept nundos rest on that one function; a bug in its look() would release them and every
    gate would agree.
  * LAW bucket 2c, the PvP comb-up: keep_policy, preflight_transfer, audit_cull, _lawcheck, audit_tags_membership and
    audit_tag_truth all called pvp_combup.pick. A pick() that forgot a target would pile the copy and be unanimously
    blessed.
Both are re-derived here from LAW.md's own words. This module must NEVER import trophy_pick or pvp_combup (and never the
engine's selection code): audit_invariants I1.8 checks that by AST. What it shares with the engine is FACTS only -- the
DB row, the ranker's per-stage ranks, the evolution graph's reach, the CP/level helper -- passed in by the caller.

The checks look only at the PILE (the irreversible output). They never re-pick the engine's exact choice where LAW leaves
a tie open; they fail only when a pile member provably breaks the rule.

  python independent_law.py      # offline self-test on toy bags
"""
import math
from collections import defaultdict

ATLANTA = (33.749, -84.388)       # LAW bucket 1 (user 2026-09-23): "farthest from Atlanta, GA"


def _get(r, k):
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def atl_km(r):
    """Great-circle km from Atlanta to where this copy was caught; None when the catch place is unknown."""
    lat, lon = _get(r, 'lat'), _get(r, 'lon')
    if lat is None or lon is None:
        return None
    p1, p2 = math.radians(ATLANTA[0]), math.radians(lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon - ATLANTA[1]) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def nundo_look(r, cf, is_costume_form):
    """LAW bucket 1: "one per look -- species, form, shiny, shadow, costume, Max, background, XXL, lucky". The form is
    the species-normalised one (`cf`: a form-0 copy is its species' base form). A location card whose enum was never
    read is its OWN look (unknown data is never fodder, so it can never be the duplicate of anything)."""
    f = _get(r, 'fresh_form') or _get(r, 'form') or 0
    if _get(r, 'fresh_has_location_card') == 1:
        card = _get(r, 'fresh_loc_card_enum') or ('unread', _get(r, 'uid_hex'))
    else:
        card = 0
    return (_get(r, 'pokemon_id'), cf(r), bool(_get(r, 'fresh_shiny')), (_get(r, 'fresh_alignment') or 0) == 1,
            _get(r, 'fresh_costume') or 0, f if is_costume_form(f) else 0, _get(r, 'fresh_bread_mode') or 0, card,
            _get(r, 'fresh_natural_art_bg') or 0, (_get(r, 'pokemon_size_category') or 0) == 5, bool(_get(r, 'is_lucky')))


def is_nundo(r):
    return bool(_get(r, 'is_zero')) and bool(_get(r, 'pokemon_id'))


def nundo_violations(rows, pile, cap, cf, is_costume_form, tol_km=100.0):
    """Pile members that break LAW bucket 1's nundo rule. `rows`: the bag WITHOUT fused components (they hold no slot).
    A look keeps min(cap, copies) nundos, the ones caught FARTHEST from Atlanta: a piled copy caught at a known place is
    lawful only when at least that many KEPT copies were caught at a known place no nearer than it (`tol_km` is the tie
    band); an unknown catch place ranks last. A copy a look keeps for ANOTHER reason (a favourite, a legacy move, the
    engine's finer raw-form / purified look) is an extra: a nearer extra never makes a farther copy's release unlawful.
    -> [(uid, why)]"""
    groups = defaultdict(list)
    for r in rows:
        if is_nundo(r):
            groups[nundo_look(r, cf, is_costume_form)].append(r)
    out = []
    for look, lst in groups.items():
        kept = [r for r in lst if r['uid_hex'] not in pile]
        piled = [r for r in lst if r['uid_hex'] in pile]
        if not piled:
            continue
        need = min(cap, len(lst))
        if len(kept) < need:
            for p in piled:
                out.append((p['uid_hex'], 'its look keeps %d nundo(s), the law keeps %d' % (len(kept), need)))
            continue
        for p in piled:
            dp = atl_km(p)
            if dp is None:
                continue                                  # an unknown catch place ranks last: piling it is lawful
            # the law keeps the `need` farthest: count the KEPT copies at a known place at least as far as p. Testing
            # p against EVERY kept copy flagged a lawful pile whenever the look kept a nearer extra (R-A review).
            as_far = [k for k in kept if atl_km(k) is not None and atl_km(k) + tol_km >= dp]
            if len(as_far) < need:
                near = [atl_km(k) for k in kept if atl_km(k) is None or atl_km(k) + tol_km < dp]
                out.append((p['uid_hex'], 'caught %s km from Atlanta, yet only %d kept cop%s of its look %s caught at '
                            'least that far (the law keeps the %d farthest; kept instead: a copy caught %s away)'
                            % (int(dp), len(as_far), 'y' if len(as_far) == 1 else 'ies',
                               'was' if len(as_far) == 1 else 'were', need,
                               ('%s km' % int(near[0])) if near and near[0] is not None else 'an unknown distance')))
    return out


def _stages(r, lg):
    """[(stage, rank)] from the ranker's <lg>_chain_ranks column ('raboot:7(99.82%);cinderace:1(100.00%)')."""
    out = []
    for part in str(_get(r, lg + '_chain_ranks') or '').split(';'):
        if ':' not in part:
            continue
        s, rest = part.split(':', 1)
        try:
            out.append((s.strip(), int(rest.split('(')[0])))
        except ValueError:
            continue
    return out


def combup_uncovered(rows, pile, labels, *, own_of, later_fn, fits_fn, reaches_fn, caps, floor, rare_pids,
                     legacy_uids, protected_pids, cf):
    """Pile members that are a LAW bucket 2c opportunity nobody kept. -> [(uid, league, target, rank, why)]

    LAW 2c: for every Great / Ultra League TARGET stage (shadow or not), the copy that would be a better copy of that
    stage than any you own AFTER EVOLVING -- it can become the stage (form, costume, gender: `later_fn`), still fits the
    league there at its true level (`fits_fn`), and its rank there beats yours -- inside the Best GL/UL floor (the
    legendary roster exempt). One copy per target. Never a copy evolving would destroy: your best at its OWN stage in
    either league, an own-stage top-5 spread, a legacy move, the last copy or only shiny of its form, a protected
    species. Every pick is KEPT.

    So a PILED copy that can do that for (league, target, shadow-or-not) is lawful only when a KEPT copy already covers
    that target: `labels` (the engine's pvp_combup_labels.json: uid -> {target, leagues}) names it, and ITS OWN rank
    there -- read from its own row, not from the label -- is at least as good. `rows`: the bag without fused components.
    `reaches_fn(stage, cap)`: the stage reaches the league cap (LAW: a maxed hundo within 100 CP of it)."""
    by = {r['uid_hex']: r for r in rows}
    sh = lambda r: 1 if (_get(r, 'fresh_alignment') or 0) == 1 else 0
    forms, shinies = defaultdict(int), defaultdict(int)
    for r in rows:
        forms[(_get(r, 'pokemon_id'), cf(r))] += 1
        if _get(r, 'fresh_shiny'):
            shinies[(_get(r, 'pokemon_id'), cf(r))] += 1
    # what you own AS each stage in each league: the best own-stage rank of a copy that can play there now
    owned, own_best = {}, set()
    for lg, cap in caps.items():
        best = {}
        for r in rows:
            o = own_of(r)
            for st, rk in _stages(r, lg):
                if st == o and reaches_fn(st, cap) and fits_fn(r, st, cap):
                    k = (st, sh(r))
                    if k not in best or (rk, r['uid_hex']) < best[k]:
                        best[k] = (rk, r['uid_hex'])
        owned[lg] = best
        own_best |= {u for _rk, u in best.values()}

    def destroyed_by_evolving(r):
        if r['uid_hex'] in own_best or r['uid_hex'] in legacy_uids or _get(r, 'pokemon_id') in protected_pids:
            return True
        key = (_get(r, 'pokemon_id'), cf(r))
        if forms[key] <= 1 or (_get(r, 'fresh_shiny') and shinies[key] <= 1):
            return True
        o = own_of(r)
        return any(st == o and rk <= 5 and reaches_fn(st, cap) and fits_fn(r, st, cap)
                   for lg, cap in caps.items() for st, rk in _stages(r, lg))

    cover = defaultdict(list)                        # (league, target, shadow) -> [kept copies the engine assigned]
    for u, lab in (labels or {}).items():
        if u in pile or u not in by or not isinstance(lab, dict):
            continue
        for lg in lab.get('leagues') or ():
            cover[(lg, lab.get('target'), sh(by[u]))].append(by[u])
    out = []
    for u in sorted(pile):
        p = by.get(u)
        if p is None or destroyed_by_evolving(p):
            continue
        later = later_fn(p)                              # None = no graph: every ranked later stage counts (can only alarm)
        later = None if later is None else set(later)
        for lg, cap in caps.items():
            for st, rk in _stages(p, lg):
                if st == own_of(p) or (later is not None and st not in later) or not reaches_fn(st, cap) \
                        or not fits_fn(p, st, cap):
                    continue
                if rk > floor and _get(p, 'pokemon_id') not in rare_pids:
                    continue
                mine = owned[lg].get((st, sh(p)))
                if mine is not None and rk >= mine[0]:
                    continue                             # you already own a copy of that stage at least this good
                ok = [k for k in cover[(lg, st, sh(p))]
                      if any(s2 == st and r2 <= rk for s2, r2 in _stages(k, lg))]
                if not ok:
                    out.append((u, lg, st, rk, 'evolving it gives a %s #%d %s%s (you own %s) and no kept copy covers that '
                                'target' % (lg.upper(), rk, st, ' (shadow)' if sh(p) else '',
                                            ('#%d there' % mine[0]) if mine else 'none')))
    return out


def shiny_ladder_violations(rows, pile, *, own_of, next_of, can_evolve, cap_of, plain_cap_of, floor_iv,
                            is_collectible, protected_pids):
    """Piled shinies LAW's shiny ladder HOLDS. -> [(uid, why)]

    LAW (Shiny ladder): "a spare shiny gets Evolve Shiny whenever evolving it earns a shiny spot at the next stage -- an
    open spot under the shiny cap, or it beats the weakest of a full top-N ... A shiny past the shiny cap is held (reason
    shiny_ladder) when it earns such a spot. A stage's best shiny never moves; collectible, trophy and shadow shinies are
    never advised to evolve." -- and (Candy) "A copy that earns a slot at a later stage but cannot pay for it today is HELD
    ... never released". Candy, items and game gates therefore do NOT enter this test: they decide the LABEL, never
    whether the copy lives. Bucket 4: at most `plain_cap_of` PLAIN shinies, and a plain shiny under `floor_iv` takes no
    plain spot unless the stage has no plain shiny yet.

    `rows`: the bag without fused components. `next_of(sid)`: the stages one evolution up. A split line must earn a spot
    on every branch this copy can land on (a random tap). KEPT spares at least as good -- of the same stage, or of any
    stage that lands on the same target -- are assumed to climb first (they take spots before this one) -- so this can
    only under-report, never invent a hold."""
    sh = [r for r in rows if _get(r, 'fresh_shiny')]
    at = defaultdict(list)                                  # stage -> IVs of the shinies there (pile included: stricter bar)
    at_plain = defaultdict(list)
    stage_best = {}
    for r in sh:
        s = own_of(r)
        at[s].append(_get(r, 'iv_total') or 0)
        if not is_collectible(r) and (_get(r, 'fresh_alignment') or 0) != 1:
            at_plain[s].append(_get(r, 'iv_total') or 0)
        k = (_get(r, 'pokemon_id'), s)
        if k not in stage_best or ((_get(r, 'iv_total') or 0), r['uid_hex']) > stage_best[k]:
            stage_best[k] = ((_get(r, 'iv_total') or 0), r['uid_hex'])
    spare = lambda r: ((_get(r, 'fresh_alignment') or 0) != 1 and (_get(r, 'iv_total') or 0) not in (0, 45)
                       and not is_collectible(r) and _get(r, 'pokemon_id') not in protected_pids and can_evolve(r)
                       and stage_best.get((_get(r, 'pokemon_id'), own_of(r)), (None, None))[1] != r['uid_hex'])
    out = []
    # every KEPT spare and the stages it can land on: a spare of ANOTHER own stage that lands on the same target (Burmy
    # cloaks -> one Mothim, a form-0 vs NORMAL stage split) competes for that target's spots too (R-A review)
    kept_sp = [k for k in sh if k['uid_hex'] not in pile and spare(k)]
    lands = {k['uid_hex']: set(next_of(k) or ()) for k in kept_sp}
    for u in sorted(pile):
        p = next((r for r in sh if r['uid_hex'] == u), None)
        if p is None or not spare(p):
            continue
        iv = _get(p, 'iv_total') or 0
        branches = sorted(next_of(p) or ())
        if not branches:
            continue

        def earns(t):
            cap = cap_of(t)
            ahead = [(_get(k, 'iv_total') or 0) for k in kept_sp if k['uid_hex'] != u and (_get(k, 'iv_total') or 0) >= iv
                     and (own_of(k) == own_of(p) or t in lands[k['uid_hex']])]
            h = sorted(at.get(t, []) + ahead, reverse=True)
            if cap <= 0 or not (len(h) < cap or iv > h[cap - 1]):
                return False
            hp = sorted(at_plain.get(t, []) + ahead, reverse=True)
            if iv < floor_iv and hp:
                return False                                   # under the shiny floor: only a stage's first plain shiny
            pcap = plain_cap_of(t)
            return pcap > 0 and (len(hp) < pcap or iv > hp[pcap - 1])
        if all(earns(t) for t in branches):
            out.append((u, 'a spare shiny that earns a shiny spot at %s (%d shiny there, cap %d) is in the pile -- LAW '
                           'holds it (candy, items and gates decide the label, never the release)'
                        % ('/'.join(branches), len(at.get(branches[0], [])), cap_of(branches[0]))))
    return out


if __name__ == '__main__':
    base = dict(pokemon_id=7, form=181, fresh_form=181, fresh_shiny=0, fresh_alignment=0, fresh_costume=0,
                fresh_bread_mode=0, fresh_has_location_card=0, fresh_loc_card_enum=0, fresh_natural_art_bg=0,
                pokemon_size_category=3, is_lucky=0, is_zero=1, lat=33.75, lon=-84.39)
    cf = lambda r: r['form'] or 181
    no_cos = lambda f: False
    rows = [dict(base, uid_hex='atl'), dict(base, uid_hex='tokyo', lat=35.68, lon=139.69)]
    assert nundo_violations(rows, {'atl'}, 1, cf, no_cos) == [], 'Tokyo kept, Atlanta piled: lawful'
    assert nundo_violations(rows, {'tokyo'}, 1, cf, no_cos)[0][0] == 'tokyo', 'the farther one was piled'
    cos = [dict(base, uid_hex='plain'), dict(base, uid_hex='hat', fresh_costume=11)]
    assert nundo_violations(cos, {'plain'}, 1, cf, no_cos)[0][0] == 'plain', 'a costume is its own look'
    luck = [dict(base, uid_hex='a'), dict(base, uid_hex='b', is_lucky=1)]
    assert nundo_violations(luck, {'a'}, 1, cf, no_cos), 'lucky is its own look'
    unread = [dict(base, uid_hex='c'), dict(base, uid_hex='d', fresh_has_location_card=1, fresh_loc_card_enum=0)]
    assert nundo_violations(unread, {'c'}, 1, cf, no_cos), 'an unread card is never a duplicate'
    assert nundo_violations([dict(base, uid_hex='e', lat=None, lon=None), dict(base, uid_hex='f')], {'f'}, 1, cf, no_cos), \
        'an unknown catch place ranks last'
    fav = rows + [dict(base, uid_hex='paris', lat=48.86, lon=2.35)]          # Tokyo = the law's pick, Atlanta kept as a favourite
    assert nundo_violations(fav, {'paris'}, 1, cf, no_cos) == [], 'a nearer extra kept for another reason is no violation'
    assert nundo_violations(fav, {'tokyo'}, 1, cf, no_cos)[0][0] == 'tokyo', 'but the farthest one may never go'
    unk_fav = [dict(base, uid_hex='tok', lat=35.68, lon=139.69), dict(base, uid_hex='unk', lat=None, lon=None),
               dict(base, uid_hex='par', lat=48.86, lon=2.35)]
    assert nundo_violations(unk_fav, {'par'}, 1, cf, no_cos) == [], 'an unknown-place extra does not outrank a lawful pile'
    raw = [dict(base, uid_hex='f0_tok', form=0, lat=35.68, lon=139.69), dict(base, uid_hex='f0_par', form=0, lat=48.86, lon=2.35),
           dict(base, uid_hex='f181_atl', lat=33.75, lon=-84.39)]         # the engine keeps one per RAW form (0 and 181)
    assert nundo_violations(raw, {'f0_par'}, 1, cf, no_cos) == [], 'a finer engine look keeping one more is no violation'
    # comb-up: two Eevee-like pre-evos, two targets; x1 is your best at its own stage (never a candidate)
    mk = lambda u, gl, **kw: dict(dict(uid_hex=u, pokemon_id=133, form=0, species_name='Eevee', fresh_shiny=0,
                                       fresh_alignment=0, gl_chain_ranks=gl, ul_chain_ranks=''), **kw)
    bag = [mk('x1', 'eevee:3(99%);umbreon:10(99%)'), mk('x2', 'eevee:40(95%);umbreon:12(99%);espeon:8(99%)'),
           mk('x3', 'eevee:50(94%);umbreon:30(97%)')]
    kw = dict(own_of=lambda r: 'eevee', later_fn=lambda r: {'umbreon', 'espeon'}, fits_fn=lambda r, s, c: True,
              reaches_fn=lambda s, c: True, caps={'gl': 1500}, floor=55, rare_pids=set(), legacy_uids=set(),
              protected_pids=set(), cf=lambda r: 0)
    miss = combup_uncovered(bag, {'x2'}, {'x3': {'target': 'umbreon', 'leagues': ['gl']}}, **kw)
    assert {(m[0], m[2]) for m in miss} == {('x2', 'umbreon'), ('x2', 'espeon')}, miss   # x3 covers umbreon only at #30
    assert combup_uncovered(bag, {'x3'}, {'x2': {'target': 'umbreon', 'leagues': ['gl']}}, **kw) == [], 'x3 covered by x2 (#12)'
    assert combup_uncovered(bag, {'x2'}, {'x2': {'target': 'espeon', 'leagues': ['gl']},
                                          'x3': {'target': 'umbreon', 'leagues': ['gl']}}, **kw), 'a piled pick covers nothing'
    assert combup_uncovered(bag, {'x2'}, {}, **dict(kw, legacy_uids={'x2'})) == [], 'a legacy mover is never a candidate'
    assert combup_uncovered(bag, {'x2'}, {}, **dict(kw, floor=5)) == [], 'outside the floor'
    # shiny ladder: a spare shiny past the cap that would take an open shiny spot one stage up is HELD, whatever the candy
    sb = lambda u, s, iv, **kw: dict(dict(uid_hex=u, pokemon_id=532 if s == 'timburr' else 533, species_name=s, form=0,
                                          fresh_shiny=1, fresh_alignment=0, iv_total=iv), **kw)
    bag = [sb('t1', 'timburr', 40), sb('t2', 'timburr', 23), sb('g1', 'gurdurr', 30)]
    kws = dict(own_of=lambda r: r['species_name'], next_of=lambda r: {'gurdurr'} if r['species_name'] == 'timburr' else set(),
               can_evolve=lambda r: True, cap_of=lambda t: 2, plain_cap_of=lambda t: 2, floor_iv=18,
               is_collectible=lambda r: False, protected_pids=set())
    assert shiny_ladder_violations(bag, {'t2'}, **kws)[0][0] == 't2', 'Gurdurr has 1 of 2 shinies: t2 is held'
    assert shiny_ladder_violations(bag, {'t1'}, **kws) == [], 't1 is the stage best shiny: never a spare'
    assert shiny_ladder_violations(bag + [sb('g2', 'gurdurr', 44)], {'t2'}, **kws) == [], 'full, and 23 beats no one'
    assert shiny_ladder_violations(bag, {'t2'}, **dict(kws, is_collectible=lambda r: r['uid_hex'] == 't2')) == [],         'a collectible shiny never climbs'
    assert shiny_ladder_violations([sb('t1', 'timburr', 40), sb('t2', 'timburr', 10)], {'t2'}, **kws)[0][0] == 't2',         'no plain shiny at the next stage yet: the floor does not apply'
    # two OWN stages land on one target (Burmy cloaks -> Mothim): the better kept spare of the OTHER stage takes the open spot
    bm = lambda u, s, iv: dict(uid_hex=u, pokemon_id=412 if s != 'mothim' else 414, species_name=s, form=0, fresh_shiny=1,
                               fresh_alignment=0, iv_total=iv)
    burmy = [bm('pb', 'burmy_plant', 44), bm('p2', 'burmy_plant', 40), bm('sb', 'burmy_sandy', 44), bm('s2', 'burmy_sandy', 30),
             bm('m1', 'mothim', 35)]
    kwb = dict(kws, next_of=lambda r: {'mothim'} if r['species_name'].startswith('burmy') else set(), cap_of=lambda t: 2,
               plain_cap_of=lambda t: 2)
    assert shiny_ladder_violations(burmy, {'s2'}, **kwb) == [], 'p2 (40, another stage, kept) takes the one open Mothim spot'
    print('independent_law self-check OK')
