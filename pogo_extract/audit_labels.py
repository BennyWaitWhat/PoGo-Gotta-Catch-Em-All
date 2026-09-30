"""LABEL LAW AUDIT -- every advisory evolve label (Evolve Once / Evolve Twice / Evolve Gated, Evolve for GL / UL beside them)
must obey the bucket rules in LAW.md. A label asks the user to CONSUME a copy, so a copy kept as a trophy or collectible
must never carry one. Read-only, DB + policy_reasons + the evolve advice table; no device contact. Exit 1 (BLOCK) on any
violation. Written 2026-09-16 after four incidents in one day (protected Pichus, card Charmanders, legacy Primeapes, Pikachu key).
2026-09-26: 'Power Up to 1500/2500' and 'Unlock 2nd Move' are advice on a kept #1.
2026-09-29 (the fold): every producer -- engine promise, PvP comb-up, shiny upgrade, showcase pick -- is one table
(evolve_advice.json) and the law judges them all; the count in the tag is where he stops.
"""
import collections, json, os, sqlite3, sys
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts')); sys.path.insert(0, ROOT)
import keep_config
import evolvable_forms
import granular_tags
from pvp_iv_rule import pvid, maxcp, GL_CAP, UL_CAP, READY_RANK, VIABILITY_MARGIN, fits

CONSUMED = {'protected', 'legacy', 'location_card', 'xxl', 'mighty', 'dex_only_copy', 'rarity', 'adventure_effect',
            'shadow_best', 'hundo', 'nundo',        # keep axes that evolving would destroy or that never evolve
            'fused'}     # (2026-09-26) fused components hold no ladder slot: held inside a Kyurem, never advised to evolve
# EACH PRODUCER UNDER ITS OWN BUCKET'S LAW (2026-09-29, the fold) -- LAW.md: a copy belongs to the FIRST bucket that applies.
# A showcase pick (bucket 8) evolves an XXL for its size: 'xxl' is its point, not consumed (the badge carries through
# evolution). A PvP comb-up (bucket 2c) comes BEFORE the legendary (3), card (5), shadow (7) and XXL (8) buckets ("shadow or
# not", "legendary roster exempt"), so only a bucket 0/1 keep is consumed by one. An engine promise (bucket 9) and a shiny
# upgrade ("collectible, trophy and shadow shinies are never advised to evolve") keep the whole set.
CONSUMED_BY = {'size': CONSUMED - {'xxl'},
               'combup': CONSUMED - {'rarity', 'location_card', 'shadow_best', 'xxl'}}


def main():
    con = sqlite3.connect('file:pokemon.db?mode=ro', uri=True); con.row_factory = sqlite3.Row
    rows = {r['uid_hex']: keep_config.row_dict(r) for r in con.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    pol = {u: set(v) for u, v in json.load(open('system/analysis/policy_reasons.json')).items() if not u.startswith('_')}
    gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8')); BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
    viable = lambda sid, cap: bool(sid) and sid in BS and maxcp(sid, BS) > cap + VIABILITY_MARGIN
    prot = keep_config.protected_pids()
    # THE USABLE WINNING STAGE of a Best GL / Best UL copy: the best stage it can REACH (the engine's ONE evolution
    # graph -- a fact), viable first, then rank, then the ranker's chain order (own stage first) -- CP-BLIND PER STAGE
    # once it can ENTER the league at SOME reachable stage (pvp_iv_rule.fits, the ONE CP/level helper), else None.
    # LAW 2b EVOLUTION COUNTS EVERYWHERE (user 2026-09-24): this audit still demanded a fit at the winning stage itself
    # (the 09-23 rule) and failed the gate on a 9/13/15 Zorua that wins as Zoroark GL #79 but is over 1,500 there
    # (2026-09-25). Re-derived here, not read from the engine. Graph unavailable -> the ranker's chain as it stands.
    try:
        import keep_policy as _kp
        _graph = _kp.build_evo_graph(gm, {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']},
                                     with_all=True)
        _later = lambda r: _kp.pvp_later_stages(r, _graph)
    except Exception as e:
        print('evolution graph unavailable (%s) -- Best GL/UL stages judged on the ranker\'s chain as it stands' % e)
        _later = lambda r: None
        _graph = None

    def usable_stage(r, lg, cap):
        own, later, best, enters = pvid(r['species_name'], r['form'] or 0), _later(r), None, False
        for pos, part in enumerate(x for x in str(r[lg + '_chain_ranks'] or '').split(';') if ':' in x):
            s = part.split(':')[0].strip()
            try:
                k = int(part.split(':')[1].split('(')[0])
            except ValueError:
                continue
            if s != own and later is not None and s not in later:
                continue
            enters = enters or fits(r, s, cap, BS)
            key = (0 if viable(s, cap) else 1, k, pos)
            if best is None or key < best[0]:
                best = (key, s)
        return best[1] if best and enters else None
    # THE ADVICE TABLE (2026-09-29, the fold): every evolve label -- an engine promise, a PvP comb-up, a shiny upgrade, a
    # showcase pick -- is one row of system/analysis/evolve_advice.json (build_tagsets' record of granular_tags.evolve_advice),
    # TRUSTED for each copy's target(s) and producer the way promises.json was; the tag files the phone gets
    # are checked against it below, and everything else is re-derived here.
    CAP = {'gl': GL_CAP, 'ul': UL_CAP}
    # THE FACTS EVOLVING WOULD DESTROY, read from the bag -- never only from policy_reasons (H08, 2026-09-29): a legacy
    # move (legacy_accurate.json -- evolving rerolls it; a copy past the legacy cap carries no 'legacy' reason), Mighty,
    # an Adventure-Effect move (the live registry), the last copy of its form. Unreadable legacy source -> BLOCK below.
    import ae_moves
    try:
        _LEGACY_UIDS = {e['uid_hex'] for e in json.load(open('legacy_accurate.json', encoding='utf-8'))}
    except Exception as _le:
        _LEGACY_UIDS = None
        bad_pre = ['legacy_accurate.json unreadable (%s) -- a legacy mover advised to evolve cannot be seen' % _le]
    else:
        bad_pre = []
    _AE_IDS = ae_moves.move_ids()
    _base0 = granular_tags._base_form_map(list(rows.values()))
    _cf0 = lambda r: (r['form'] or 0) or _base0.get(r['pokemon_id'], 0)
    _form_n = collections.Counter((r['pokemon_id'], _cf0(r)) for r in rows.values() if not keep_config.is_fused_component(r))
    # EVERY-LINE POOLS (keep_config.line_pool_all, florandez; 2026-09-30): a form may leave the bag while its LINE keeps copies
    # -- the Pokedex is lifetime, and audit_cull's FORMS-wiped layer exempts pooled forms the same way -- so for a pooled copy
    # the fact is "the last copy of its POOL", not of its form (the first line-pool cull since this check existed failed the
    # gate on Pikipek / Pidgey / Grubbin comb-up promises whose lines keep 3-5 copies).
    if keep_config.line_pool_all():
        import pattern_pools as _ppl
        _plk = lambda r: _ppl.pool_key(r['pokemon_id'], r['species_name'], r['form'] or 0, r.get('gender'))
        _pool_n = collections.Counter(_plk(r) for r in rows.values() if _plk(r))
    else:
        _plk, _pool_n = (lambda r: None), collections.Counter()

    # The three switchable keep-all axes (keep_config rules) are facts only while their rule is ON: with a rule OFF the
    # engine no longer keeps by it (audit_cull's _R does the same), so the copy may lawfully be promoted -- ignoring the
    # switch turned every promise of such a copy into a BLOCK (R-A review, 2026-09-29).
    _RULE = {k: keep_config.rule_enabled(k) for k in ('mighty', 'adventure_effect', 'dex_only')}

    def _facts(u, r):
        f = []
        if _LEGACY_UIDS is not None and u in _LEGACY_UIDS:
            f.append('a legacy move (legacy_accurate.json)')
        if _RULE['mighty'] and r['fresh_is_strong'] == 1:
            f.append('Mighty')
        if _RULE['adventure_effect'] and _AE_IDS and ae_moves.known(r, _AE_IDS):
            f.append('an Adventure-Effect move')
        if _RULE['dex_only'] and _form_n[(r['pokemon_id'], _cf0(r))] <= 1 and not (_plk(r) and _pool_n[_plk(r)] > 1):
            f.append('the last copy of its form')
        return f
    _tagfile = lambda t: os.path.join('system', 'analysis', 'tagsets', granular_tags.filename(t))
    _members = lambda t: set(open(_tagfile(t)).read().split()) if os.path.exists(_tagfile(t)) else set()
    pile = _members('Transfer')
    bad = list(bad_pre)
    try:
        adv = {format(int(u, 16), '016x'): e
               for u, e in json.load(open(granular_tags.EVOLVE_ADVICE, encoding='utf-8')).items()}
    except (OSError, ValueError) as e:
        adv = None
        bad.append('evolve_advice.json unreadable (%s) -- no evolve label can be judged; run build_tagsets' % e)
    worn = {}                                         # uid -> the evolve tags it wears (the files the phone gets)
    for t in granular_tags.EVOLVE_TAGS:
        for u in _members(t):
            worn.setdefault(u, set()).add(t)
    n_src = collections.Counter()
    for u, r in rows.items():
        reasons = pol.get(u, set()); own = pvid(r['species_name'], r['form'] or 0)
        evo = {x for x in reasons if x.startswith('evolve_')}
        ad, tags = (adv or {}).get(u), worn.get(u, set())
        if not evo and ad is None and not tags:
            continue
        src = ad['source'] if ad else 'promise' if evo else 'untabled'   # the producer picks the bucket law (2026-09-29)
        n_src[src] += 1
        name = '%s %d%% [%s] (%s)' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45,
                                      ', '.join(sorted(tags)) or ','.join(sorted(evo)), src)
        if r['pokemon_id'] in prot:
            bad.append(name + ': PROTECTED species advised to evolve')
        if (r['iv_total'] or 0) in (0, 45):
            bad.append(name + ': trophy (hundo/nundo) advised to evolve')
        hit = reasons & CONSUMED_BY.get(src, CONSUMED)
        if hit:
            bad.append(name + ': kept as %s, evolving consumes it' % '/'.join(sorted(hit)))
        else:
            _f = _facts(u, r)                         # (H08) the bag's own facts, whatever the engine's reasons say
            if _f:
                bad.append(name + ': has %s -- evolving consumes it (read from the bag; policy_reasons does not say so)'
                           % ' and '.join(_f))
        if src == 'shiny' and r['fresh_alignment'] == 1:
            bad.append(name + ': shadow advised to evolve')
        own_pvp = ((r['gl_stage'] == own and r['gl_rank'] is not None and r['gl_rank'] <= READY_RANK and viable(own, GL_CAP))
                   or (r['ul_stage'] == own and r['ul_rank'] is not None and r['ul_rank'] <= READY_RANK and viable(own, UL_CAP)))
        if own_pvp:                                   # every producer (2026-09-29): bucket 2 comes first; 2c names it too
            bad.append(name + ': own-stage PvP asset (rank <= %d) advised to evolve' % READY_RANK)
        # a Best GL / Best UL copy (rule 15d) whose USABLE winning stage is its OWN stage is never advised to evolve --
        # by any producer (user 2026-09-23). Mirrors keep_policy's _own_pvp and refresh_evolve_shiny.
        # A Best copy with no usable stage at all reads as own-stage (it could not have won; never consume it).
        if (('pvp_best_gl' in reasons and usable_stage(r, 'gl', GL_CAP) in (own, None))
                or ('pvp_best_ul' in reasons and usable_stage(r, 'ul', UL_CAP) in (own, None))):
            bad.append(name + ': Best GL/UL copy at its own stage advised to evolve')
        if evolvable_forms.row_can_evolve(r) is False:
            bad.append(name + ': this FORM has no evolution branch in the game master (%s)' % (r['fresh_form'] or r['form']))
        if evo and r['fresh_shiny']:
            bad.append(name + ': shiny carries an engine plain-ladder promise (a shiny climbs the shiny ladder)')
        if src == 'shiny' and not r['fresh_shiny']:
            bad.append(name + ': a shiny upgrade on a non-shiny')
    # A LATER-STAGE RANK CHIP MUST BE TRUE FOR THE MON ON SCREEN (2026-09-17): it names a rank only a LATER stage reaches,
    # so the same two gates apply. A PikachuGofest2026CapYellow wore "Evo GL Rank 1" for a Raichu it can never become.
    # Since 2026-09-30 (THE SECOND FOLD) the chips are '<league> 1-5 No Evolve' and, on the copy to evolve, 'Evolve for
    # <league>'; the two never sit on one copy (checked right after).
    DEX = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
    n_rank = 0
    for fn, lg in (('GL_1-5_No_Evolve', 'gl'), ('UL_1-5_No_Evolve', 'ul'),
                   ('Evolve_for_GL', 'gl'), ('Evolve_for_UL', 'ul')):      # rule 15e comb-up chips (2026-09-24)
        p = os.path.join('system', 'analysis', 'tagsets', fn + '.txt')
        if not os.path.exists(p):
            continue
        for u in open(p).read().split():
            r = rows.get(u)
            if r is None:
                continue                                  # released mid-sync: prune's own reconcile owns that
            n_rank += 1
            nm = '%s %d%% [%s]' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, fn.replace('_', ' '))
            if evolvable_forms.row_can_evolve(r) is False:
                bad.append(nm + ': this FORM has no evolution branch -- it can never reach that later stage')
                continue
            stages = [x.split(':')[0].strip() for x in (r[lg + '_chain_ranks'] or '').split(';') if ':' in x]
            later = [x for x in stages if x != pvid(r['species_name'], r['form'] or 0)]
            if later and not any(evolvable_forms.gender_allows(r['pokemon_id'], r['gender'], DEX.get(x)) for x in later):
                bad.append(nm + ': this gender reaches no later stage of the line')
    # THE BEST SHINY OF A LOOK NEVER EVOLVES (2026-09-30, user: "you dont keep my only anything when evolving shinies. for
    # example the costumed whimsicott i evolved, not theres no costumed cottonee."): a look = species + form (form 0 folded
    # into a species' single form) + costume + the gender where the game draws the two differently; its best in-bag
    # shiny (IV, then uid) is the look's trophy at that stage, whatever the producer.
    _fc0 = collections.defaultdict(set)
    for _r in rows.values():
        if (_r['form'] or 0) != 0:
            _fc0[_r['pokemon_id']].add(_r['form'])
    def _look(_r):
        _f = _r['form'] or 0
        if _f == 0 and len(_fc0.get(_r['pokemon_id'], ())) == 1:
            _f = next(iter(_fc0[_r['pokemon_id']]))
        return (_r['pokemon_id'], _f, _r['fresh_costume'] or 0,          # fresh_costume: the legacy `costume` holds junk
                evolvable_forms.gender_key(_r['pokemon_id'], _r['gender']))
    _look_best = {}
    for _u, _r in rows.items():
        if _r['fresh_shiny'] and not keep_config.is_fused_component(_r):
            _k = _look(_r)
            if _k not in _look_best or ((_r['iv_total'] or 0), _u) > _look_best[_k]:
                _look_best[_k] = ((_r['iv_total'] or 0), _u)
    for u in sorted(worn):
        r = rows.get(u)
        if r is not None and r['fresh_shiny'] and _look_best.get(_look(r), (None, None))[1] == u:
            bad.append('%s %d%% [%s]: the best shiny of its look (form %s, costume %s, gender %s) advised to evolve'
                       % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, ', '.join(sorted(worn[u])), r['form'],
                          r['fresh_costume'] or 0, r['gender']))
    # NEVER "evolve" AND "No Evolve" ON ONE COPY (2026-09-30, user: "The tag is the bug")
    _noev = set().union(*(_members(granular_tags.NO_EVOLVE_FMT % _l) for _l in ('GL', 'UL')))
    for u in sorted(_noev & set(worn)):
        r = rows.get(u)
        if r is not None:
            bad.append('%s %d%% [%s]: told to evolve AND No Evolve' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45,
                                                                      ', '.join(sorted(worn[u]))))
    # THE EVOLVE TAGS (2026-09-29, the fold -- LAW "THE EVOLVE VOCABULARY"): 'Evolve Once' / 'Evolve Twice' by the number of
    # evolutions to the advised target -- the count IS the stop, so an Evolve Once whose target evolves again is right (a
    # Tympole promised Palpitoad: the old Tympole trap) -- 'Evolve Gated' instead when the game blocks it, 'Evolve for GL' /
    # 'Evolve for UL' only BESIDE one of those. Each copy's advice is judged by the law above; here: the files are exactly the
    # table's tags, never on a pile mon or a fused component, every target a stage THIS copy can become (the engine's ONE
    # graph: form, costume, gender), and the count true -- counted on that graph, not read from the table: an Evolve Twice
    # one evolution away, an Evolve Once two away, or a count tag with a game gate anywhere on the way is a mislabel.
    COUNT = {granular_tags.EVOLVE_ONCE: 1, granular_tags.EVOLVE_TWICE: 2, granular_tags.EVOLVE_GATED: None}
    _reach = _graph[4] if _graph is not None else {}

    def _way(own, t):
        if t in _reach.get(own, ()):                  # the stages he evolves through, t included, on the engine's graph
            return [x for x in _reach[own] if t in _reach.get(x, ())] + [t]
        return granular_tags.path_between(own, t)     # a stage the graph does not name (a gendered form): the table's rule
    n_evo = 0
    for u in sorted(set(worn) | set(adv or ())):
        r = rows.get(u)
        if r is None:
            continue                                  # released mid-sync: prune's own reconcile owns that
        n_evo += 1
        tags, ad = worn.get(u, set()), (adv or {}).get(u)
        nm = '%s %d%% [%s]' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, ', '.join(sorted(tags)) or 'no tag')
        counts = sorted(t for t in tags if t in COUNT)
        if tags and not counts:
            bad.append(nm + ': Evolve for GL/UL with no Evolve Once / Twice / Gated beside it -- a marker with no evolution')
        elif len(counts) > 1:
            bad.append(nm + ': two counts at once -- exactly one of Evolve Once / Twice / Gated')
        if u in pile:
            bad.append(nm + ': advice to evolve on a mon tagged for Transfer')
        if keep_config.is_fused_component(r):
            bad.append(nm + ': a fused component (held inside a Kyurem) advised to evolve')
        if adv is None:
            continue
        if ad is None or not ad.get('targets'):
            bad.append(nm + ': an evolve tag with no advice behind it (evolve_advice.json names no target)')
            continue
        if set(ad.get('tags') or ()) != tags:
            bad.append(nm + ': the table says [%s] -- the tag files and evolve_advice.json disagree'
                       % ', '.join(sorted(ad.get('tags') or ())))
        own, later = pvid(r['species_name'], r['form'] or 0), _later(r)
        want = COUNT[counts[0]] if len(counts) == 1 else None
        for t in ad['targets']:
            if later is not None and t not in later:
                bad.append(nm + ': %s is not a stage this copy can become' % t)
                continue
            way = _way(own, t)
            if want is not None and len(way) != want:
                bad.append(nm + ': %s is %s -- a mislabel (the count is where he stops)'
                           % (t, '%d evolution(s) away' % len(way) if way else 'on no evolution path the game master shows'))
            gate = [g for s in way for g in (evolvable_forms.gate_reason(s) or [])]
            if want is not None and gate:
                bad.append(nm + ': the game gates the way to %s (%s) -- that is Evolve Gated' % (t, ', '.join(dict.fromkeys(gate))))
    # POWER UP / UNLOCK 2ND MOVE (2026-09-26): advice for dust / a TM on a kept #1 -- never an evolution, never a keep
    # reason. True for the copy on screen: its OWN stage is #1 there and can reach the cap (Power Up: still under it;
    # 2nd Move: none yet). Never on a pile or fused mon, never beside an evolve label (it would ride along onto a stage
    # where it is false), never 'Power Up to 2500' on a Great League keeper (Best GL, or own-stage GL rank 1-5 under
    # 1,500): powering it past 1,500 burns it.
    n_adv = 0
    for tag, lgs in ((granular_tags.POWER_UP_GL, ('gl',)), (granular_tags.POWER_UP_UL, ('ul',)),
                     (granular_tags.SECOND_MOVE, ('gl', 'ul'))):
        for u in _members(tag):
            r = rows.get(u)
            if r is None:
                continue
            n_adv += 1
            own, rs = pvid(r['species_name'], r['form'] or 0), pol.get(u, set())
            nm = '%s %d%% [%s]' % (r['species_name'], (r['iv_total'] or 0) * 100 // 45, tag)
            if u in pile:
                bad.append(nm + ': advice on a mon tagged for Transfer')
            if keep_config.is_fused_component(r):
                bad.append(nm + ': a fused component (held inside a Kyurem)')
            if u in worn:
                bad.append(nm + ': also wears %s -- it would ride along onto a stage where it is false' % ', '.join(sorted(worn[u])))
            _ar = keep_config.pvp('action_rank')          # rank 1-N since 2026-09-29 (user: "only Rank 1-5"), was #1
            if not any(r[lg + '_stage'] == own and (r[lg + '_rank'] or 9999) <= _ar and viable(own, CAP[lg]) for lg in lgs):
                bad.append(nm + ': not rank 1-%d at its OWN stage in %s (a stage that can reach the cap)' % (_ar, '/'.join(x.upper() for x in lgs)))
            if tag == granular_tags.SECOND_MOVE:
                if r['move3']:
                    bad.append(nm + ': it already has a second charged move')
            elif (r['cp'] or 0) > CAP[lgs[0]]:
                bad.append(nm + ': already over %d CP' % CAP[lgs[0]])
            if tag == granular_tags.POWER_UP_UL and ('pvp_best_gl' in rs or (
                    r['gl_stage'] == own and r['gl_rank'] is not None and r['gl_rank'] <= READY_RANK and (r['cp'] or 0) <= GL_CAP)):
                bad.append(nm + ': a Great League keeper -- powering it past 1,500 burns it')
    print('labels checked: %d evolve advice cop(ies) (%s) + %d Evo rank tag(s) + %d Power Up / 2nd Move'
          % (n_evo, ', '.join('%s %d' % kv for kv in sorted(n_src.items())) or 'none', n_rank, n_adv))
    for b in bad:
        print('  *** ' + b)
    print('VERDICT: %s' % ('ALL LABELS LAWFUL' if not bad else '%d LABEL(S) BREAK THE LAW -- do not sync' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
