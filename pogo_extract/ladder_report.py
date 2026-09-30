"""Collection ladder: is the bag climbing? One block per cull pass, with the delta vs the previous pass.

Reads pokemon.db + system/analysis/policy_reasons.json (+ the previous walk from the newest-but-one .db_snapshots
before_sync gzip, and the previous pass's Evolve labels from ladder_history.json). Appends one entry to
system/analysis/ladder_history.json. DB-only, never touches the phone. User 2026-09-13: "i also want to see how my
pokemon collection improved after each cull to see if the right mindset is still growing".
"""
import sys as _sys
try:      # a species name like Flabebe must never silently kill a report line on a cp1252 pipe
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import collections, glob, gzip, json, os, re, shutil, sqlite3, sys, tempfile, time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts')); sys.path.insert(0, ROOT)
from pvp_iv_rule import pvid
import evolvable_forms   # BREAD_MODES / max_axis: the game's own Max-mode names
HIST = os.path.join('system', 'analysis', 'ladder_history.json')


def load_rows(path):
    c = sqlite3.connect('file:%s?mode=ro' % path.replace('\\', '/'), uri=True); c.row_factory = sqlite3.Row
    out = {r['uid_hex']: __import__('keep_config').row_dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    c.close(); return out


def plain(r):
    return not r['fresh_shiny'] and r['fresh_alignment'] != 1 and not (r['fresh_costume'] or 0) and not evolvable_forms.max_axis(r['fresh_bread_mode'])


_BS = None


def pvp_metrics(rows, kept_uids):
    """PvP STANDING per pass (2026-09-29, user: "i cant really tell the trend in iv improvement and pvp improvement").
    Per PvP IDENTITY (species + battle form, pvid) the best OWN-stage Great / Ultra League rank among its kept,
    non-shadow copies, at a stage that reaches the league -- the rank tags' own viability test (keep_config
    pvp.viability_margin), applied with TODAY's rule to every pass (--backfill-pvp) so the series is comparable
    across the cut-off changes. CP-blind, like the GL/UL Rank 1-5 keep. Counts per league: identities judged, at #1,
    in the top 5, in the top 100."""
    global _BS
    from pvp_iv_rule import chain_stage_ranks, maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN
    if _BS is None:
        _BS = {p['speciesId']: p.get('baseStats', {}) for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
    best = {'gl': {}, 'ul': {}}
    for u, r in rows.items():
        if u not in kept_uids or r['fresh_alignment'] == 1:
            continue
        own = pvid(r['species_name'], r['form'] or 0)
        if own not in _BS:
            continue
        for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
            if not maxcp(own, _BS) > cap + VIABILITY_MARGIN:
                continue
            rk = next((k for s, k in chain_stage_ranks(r, lg) if s == own), None)
            if rk is not None and rk < best[lg].get(own, 10 ** 9):
                best[lg][own] = rk
    out = {}
    for lg in ('gl', 'ul'):
        b = list(best[lg].values())
        out['pvp_%s_ident' % lg] = len(b)
        out['pvp_%s_rank1' % lg] = sum(1 for k in b if k == 1)
        out['pvp_%s_top5' % lg] = sum(1 for k in b if k <= 5)
        out['pvp_%s_top100' % lg] = sum(1 for k in b if k <= 100)
    return out


def metrics(rows, reasons):
    kept = {u: set(v) for u, v in reasons.items() if u in rows}
    orc = json.load(open('system/analysis/fodder_oracle.json')); is_pre = orc['is_pre']
    stages = collections.defaultdict(list)                       # (species, form) -> kept copies (any kind)
    for u, r in rows.items():
        if u in kept:
            stages[(r['species_name'], r['form'] or 0)].append(r)
    with_hundo = sum(1 for lst in stages.values() if any((r['iv_total'] or 0) == 45 for r in lst))
    residents = [r for u, r in rows.items() if u in kept and 'variant_floor' in kept[u] and plain(r) and (r['iv_total'] or 0) != 45]
    best = [max((r['iv_total'] or 0) for r in lst if plain(r)) for lst in stages.values() if any(plain(r) for r in lst)]
    shinies = [r for u, r in rows.items() if u in kept and r['fresh_shiny']]
    shiny_stages = collections.defaultdict(int)
    for r in shinies:
        k = (r['species_name'], r['form'] or 0); shiny_stages[k] = max(shiny_stages[k], r['iv_total'] or 0)
    pct = lambda vals: round(sum(vals) / len(vals) / 45 * 100, 1) if vals else 0.0
    labels = {u: (2 if 'evolve_2' in v else 1) for u, v in kept.items() if 'evolve_1' in v or 'evolve_2' in v}
    return {
        'bag': len(rows), 'kept': len(kept), 'stages': len(stages), 'stages_with_hundo': with_hundo,
        'resident_mean_iv': pct([r['iv_total'] or 0 for r in residents]), 'residents': len(residents),
        'best_per_stage_mean_iv': pct(best), 'shiny_mean_iv': pct([r['iv_total'] or 0 for r in shinies]),
        'shiny_stages_3star': sum(1 for v in shiny_stages.values() if v >= 37), 'shiny_stages': len(shiny_stages),
        'labels': len(labels), '_labels': labels,
        **pvp_metrics(rows, set(kept)),
    }


def _walk_of(rows):
    return max((r.get('last_scanned') or '' for r in rows.values()), default='')


def previous_walk(cur_rows=None, recorded=()):
    """The walk to count "since" from: normally the newest-but-one before_sync snapshot. R-B review: a walk that was SYNCED
    TWICE (2026-09-29 20:09:00 and 20:10:13 -- two snapshots of ONE walk) made the second pass compare the walk with itself:
    "evolved 0, caught 0 ... pile 55 = 55 no longer kept (a rule or data change)" while the cull report, counting from its own
    saved state, said evolved 7 / caught 86 -- and those 86 catches never reached ladder_history. A snapshot of the SAME walk
    that has no history entry of its own (its deltas were never recorded) is stepped over; one that WAS recorded is kept
    (zeros, so nothing is counted twice)."""
    snaps = sorted(glob.glob(os.path.join('.db_snapshots', 'pokemon.db.*.before_sync.*.gz')))
    if '--prev' in sys.argv:
        cands = [sys.argv[sys.argv.index('--prev') + 1]]
    elif len(snaps) < 2:
        return None, None
    else:
        cands = snaps[-2::-1]                             # the newest-but-one first, then older ones
    cur_t = _walk_of(cur_rows) if cur_rows else None
    tmp = os.path.join(tempfile.gettempdir(), 'ladder_prev.db')
    rows = stamp = None
    for i, prev in enumerate(cands):
        with gzip.open(prev, 'rb') as f, open(tmp, 'wb') as g:
            shutil.copyfileobj(f, g)
        rows, stamp = load_rows(tmp), re.search(r'(\d{4}-\d\d-\d\d_\d{6})', prev).group(1)
        if not (cur_t and _walk_of(rows) == cur_t and stamp not in recorded and i + 1 < len(cands)):
            break                                         # a different walk, a recorded one, or nothing older to step to
    return rows, stamp


def backfill_pvp():
    """Add the pvp_* standing to every past entry whose walk snapshot still exists (kept = the walk's bag minus that
    pass's own pile). Re-runnable; entries already carrying pvp_gl_top5 are skipped unless --force."""
    hist = json.load(open(HIST))
    snaps = {re.search(r'(\d{4}-\d\d-\d\d_\d{6})', p).group(1): p
             for p in glob.glob(os.path.join('.db_snapshots', 'pokemon.db.*.before_sync.*.gz'))}
    tmp = os.path.join(tempfile.gettempdir(), 'ladder_backfill.db')
    n = 0
    for e in hist:
        if ('pvp_gl_top5' in e and '--force' not in sys.argv) or e.get('walk') not in snaps:
            continue
        with gzip.open(snaps[e['walk']], 'rb') as f, open(tmp, 'wb') as g:
            shutil.copyfileobj(f, g)
        rows = load_rows(tmp)
        e.update(pvp_metrics(rows, set(rows) - set(e.get('_pile') or [])))
        n += 1
        print('  %s  GL #1 %d top5 %d top100 %d / %d | UL #1 %d top5 %d top100 %d / %d' % (
            e['ts'], e['pvp_gl_rank1'], e['pvp_gl_top5'], e['pvp_gl_top100'], e['pvp_gl_ident'],
            e['pvp_ul_rank1'], e['pvp_ul_top5'], e['pvp_ul_top100'], e['pvp_ul_ident']))
    json.dump(hist, open(HIST, 'w'), indent=0)
    print('backfilled %d entr%s (%d without a snapshot)' % (n, 'y' if n == 1 else 'ies', sum(1 for e in hist if 'pvp_gl_top5' not in e)))


def main():
    if '--backfill-pvp' in sys.argv:
        return backfill_pvp()
    rows = load_rows('pokemon.db')
    reasons = {u: v for u, v in json.load(open('system/analysis/policy_reasons.json')).items() if not u.startswith('_')}
    pile = set(open('system/analysis/tagsets/6_Transfer.txt').read().split())
    hist = json.load(open(HIST)) if os.path.exists(HIST) else []
    m = metrics(rows, reasons)
    prev_rows, prev_stamp = previous_walk(rows, {e.get('walk') for e in hist if e.get('walk')})
    # WHICH ENTRY IS "LAST" (2026-09-18). The labels to match evolutions against are the ones the user saw when the
    # PREVIOUS walk was taken -- not hist[-1], which is this same pass's own entry (or a manual re-run's) and therefore
    # already missing every mon he went on to evolve. Old entries carry only prev_walk; their own walk is the next
    # snapshot after it.
    stamps = [re.search(r'(\d{4}-\d\d-\d\d_\d{6})', p).group(1)
              for p in sorted(glob.glob(os.path.join('.db_snapshots', 'pokemon.db.*.before_sync.*.gz')))]
    cur_walk = stamps[-1] if stamps else None

    def own_walk(e):
        if e.get('walk'):
            return e['walk']
        pw = e.get('prev_walk')
        return stamps[stamps.index(pw) + 1] if pw in stamps and stamps.index(pw) + 1 < len(stamps) else None
    # prev_stamp None (fewer than 2 snapshots) must match NOTHING: a legacy entry whose prev_walk was pruned also has
    # own_walk None, so None == None picked the 2026-09-18 21:42 entry as "last" for the 2026-09-23 16:51 run.
    _prev = [e for e in hist if prev_stamp and own_walk(e) == prev_stamp]
    last = _prev[-1] if _prev else next((e for e in reversed(hist) if own_walk(e) != cur_walk), None)
    # The previous pass's labels AND pile come ONLY from that pass's ladder_history entry (2026-09-23). The old
    # fallback read system/analysis/_reasons_prev_pass.json / _pile_prev_pass.txt -- one-off hand copies made before a
    # 2026-09-17 pass that NOTHING writes -- so it substituted a six-day-old label set when no entry was found, and
    # re-read the stale pile after every zero-pile pass. An EMPTY _pile is a real answer (nothing was piled), not
    # "unknown"; with no previous entry at all the split is unknown and the report says so below.
    prev_labels = (last or {}).get('_labels') or {}
    prev_pile = set((last or {}).get('_pile') or [])
    kept_p = broken_p = evolved = released = caught = 0; bumped = fresh = leftover = 0
    if prev_rows:
        sig = lambda r: (r['iv_atk'], r['iv_def'], r['iv_sta'], r['creation_date'])
        new_by_sig = collections.defaultdict(list)
        for u in set(rows) - set(prev_rows):
            new_by_sig[sig(rows[u])].append(u)
        gone = set(prev_rows) - set(rows)
        broken_names = []
        for u in gone:
            cands = [v for v in new_by_sig.get(sig(prev_rows[u]), []) if rows[v]['pokemon_id'] != prev_rows[u]['pokemon_id']]
            if cands:
                v = cands[0]; new_by_sig[sig(prev_rows[u])].remove(v); evolved += 1
                if u in prev_labels:
                    if v in pile:
                        broken_p += 1
                        broken_names.append('%s %d%% -> %s' % (prev_rows[u]['species_name'], (prev_rows[u]['iv_total'] or 0) * 100 // 45, rows[v]['species_name']))
                    else: kept_p += 1
            else:
                released += 1
        caught = sum(len(v) for v in new_by_sig.values())
        # H05-5: 'caught' is only what is left once the walk's own proto flags name the rest -- tradedTimeMs_ first (a
        # traded mon keeps its first owner's hatch flag), then hatchedFromEgg_
        _left = {u for v in new_by_sig.values() for u in v}
        traded_in = sum(1 for u in _left if (rows[u].get('traded_time_ms') or 0) > 0 or rows[u].get('is_traded') == 1)
        hatched = sum(1 for u in _left if not ((rows[u].get('traded_time_ms') or 0) > 0 or rows[u].get('is_traded') == 1)
                      and (rows[u].get('hatched_from_egg') or rows[u].get('is_hatched_from_egg')))
        caught -= traded_in + hatched
        # H05-7: the same uids with the same CP as the previous walk, re-read at a different time = nothing happened at
        # all -- or the walk read a FROZEN copy of the game (2026-09-29 05:06 / 05:09 / 05:11 read the 04:59 graph)
        _lt = lambda rr: max((x.get('last_scanned') or '' for x in rr.values()), default='')
        frozen = (set(rows) == set(prev_rows) and all(rows[u]['cp'] == prev_rows[u]['cp'] for u in rows)
                  and _lt(rows) != _lt(prev_rows))
        # NEW TROPHIES among the arrivals (user 2026-09-16: "Surprised you didn't initially report things like GL UL
        # and ML #1s"): hundos (= ML #1), own-stage GL/UL #1 and #2-5 at a stage that can reach the league cap,
        # and stages whose best plain copy just got beaten by a new one.
        from pvp_iv_rule import maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN
        gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8')); BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
        arrivals = [u for u in rows if u not in prev_rows]
        troph = collections.defaultdict(list)
        for u in arrivals:
            r = rows[u]; own = pvid(r['species_name'], r['form'] or 0)
            # an EVOLVED hundo is the same hundo at a new stage -- "new trophies: hundos 12" after evolving 12 of them
            # (2026-09-29 02:30) counted none that was new (H05-11). Only the walk's non-evolved arrivals are new hundos.
            if (r['iv_total'] or 0) == 45 and u in _left: troph['hundo'].append(r['species_name'])
            for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
                m_ = re.search(r'(?:^|;)%s:(\d+)\(' % re.escape(own), r[lg + '_chain_ranks'] or '')
                if m_ and own in BS and maxcp(own, BS) > cap + VIABILITY_MARGIN:
                    k = int(m_.group(1))
                    if k == 1: troph[lg.upper() + ' #1'].append(r['species_name'])
                    elif k <= 5: troph[lg.upper() + ' #2-5'].append(r['species_name'])
        prev_best = collections.defaultdict(int)
        # keyed by STAGE, not raw form: a form-0 arrival was compared against a form-0 record that did not exist,
        # so "stage best beaten" named stages where nothing had improved (2026-09-19, same bug as _arr_sp).
        # ...and a STAGE is a (speciesId, FORM) (2026-09-20): pvpoke calls every Florges colour 'florges' and all
        # 28 Unown letters 'unown', so a new FlorgesRed was measured against the best Florges of ANY colour.
        import evolvable_forms as _ef
        _stg = lambda r: _ef.stage_of(pvid(r['species_name'], r['form'] or 0), r['form'] or 0)
        for r in prev_rows.values():
            if plain(r): k = _stg(r); prev_best[k] = max(prev_best[k], r['iv_total'] or 0)
        improved = sorted({rows[u]['species_name'] for u in arrivals if plain(rows[u])
                           and (rows[u]['iv_total'] or 0) > prev_best.get(_stg(rows[u]), -1)
                           and _stg(rows[u]) in prev_best})
        # keyed by STAGE (speciesId), not (name, raw form): an evolved copy stored with form 0 lands on the same stage
        # as its Normal-form siblings -- raw forms called the Hattrem it pushed out a 'rule change' (2026-09-18)
        # a KEPT arrival of the same PvP identity, in ANY look (R-B review of H05-3): the plain-only, IV-only test filed a pile
        # mon under "a rule or data change" when a same-IV copy with more CP, a better shiny / Dynamax / costume copy (1b)
        # or a better-ranked Best took its place -- 2026-09-29 17:19: the 84% Impidimp beaten on CP by the just-hatched 84%
        # (the report says so). Only an arrival that itself went to the pile pushes nothing out.
        _arr_sp = {pvid(rows[x]['species_name'], rows[x]['form'] or 0) for x in rows if x not in prev_rows and x not in pile}
        _arr_best = collections.defaultdict(int)          # best PLAIN arrival per stage -- what did the pushing
        for x in rows:
            if x not in prev_rows and plain(rows[x]) and x not in pile:   # H05-3: a copy in the pile pushes nothing out
                k = pvid(rows[x]['species_name'], rows[x]['form'] or 0)
                _arr_best[k] = max(_arr_best[k], rows[x]['iv_total'] or 0)
        rule_change = 0
        combup = []                                       # (species, IV that left, IV that replaced it)
        for u in pile:
            if u in prev_rows and u not in prev_pile and pvid(rows[u]['species_name'], rows[u]['form'] or 0) not in _arr_sp:
                # kept last walk and no new copy of its kind was KEPT: a rule or data change moved it
                rule_change += 1; continue
            if u not in prev_rows: fresh += 1            # arrived since the last walk (caught or evolved)
            elif u in prev_pile: leftover += 1          # already in the previous pass's pile, still not released
            else:
                bumped += 1                               # was kept last walk, pushed out by something better
                _r = rows[u]
                combup.append((_r['species_name'], (_r['iv_total'] or 0),
                               _arr_best.get(pvid(_r['species_name'], _r['form'] or 0), 0)))
    entry = {'ts': time.strftime('%Y-%m-%d %H:%M'), 'walk': cur_walk, 'prev_walk': prev_stamp, **{k: v for k, v in m.items() if not k.startswith('_')},
             'pile': len(pile), 'evolved': evolved, 'released': released, 'caught': caught,
             'promises_kept': kept_p, 'promises_broken': broken_p, 'pile_bumped': bumped, 'pile_fresh': fresh, 'pile_leftover': leftover,
             '_labels': m['_labels'], '_pile': sorted(pile),
             # names captured NOW: a released row is dropped from pokemon.db, so the cull log could never name
             # a past pile from the DB (Bag Pulse, 2026-09-24)
             '_pile_names': {u: '%s %d%%' % (rows[u]['species_name'], round((rows[u]['iv_total'] or 0) * 100 / 45)) for u in sorted(pile) if u in rows}}
    if prev_rows:
        entry['new_hundos'] = len(troph['hundo']); entry['new_gl1'] = len(troph['GL #1']); entry['new_ul1'] = len(troph['UL #1']); entry['stage_best_improved'] = len(improved)
        # H05-5 narrowed 'caught' (hatches and trades-in are no longer in it): store them, and say which meaning this entry
        # has, so the history -- and Bag Pulse, which still sums only 'caught' -- does not silently lose them (R-B review)
        entry['hatched'], entry['traded_in'], entry['caught_excludes_hatched'] = hatched, traded_in, True
        entry['frozen'] = bool(frozen)          # H05-7's verdict, for the history readers
    if '--dry' not in sys.argv:
        if hist and own_walk(hist[-1]) == cur_walk:
            hist[-1] = entry                 # the same walk re-reported: replace, never stack a second "last"
        else:
            hist.append(entry)
        json.dump(hist, open(HIST, 'w'), indent=0)
    d = lambda k, f='%+d': ('' if not last or k not in last else ' (' + (f % (entry[k] - last[k])) + ')')
    print('LADDER %s vs %s' % (entry['ts'], (last or {}).get('ts', 'first run')))
    print('  bag %d%s | stages with a hundo %d/%d%s | full-stage residents mean IV %.1f%%%s | best copy per stage mean %.1f%%%s'
          % (entry['bag'], d('bag'), entry['stages_with_hundo'], entry['stages'], d('stages_with_hundo'), entry['resident_mean_iv'], d('resident_mean_iv', '%+.1f'),
             entry['best_per_stage_mean_iv'], d('best_per_stage_mean_iv', '%+.1f')))
    print('  shinies mean IV %.1f%%%s | stages with a 3-star shiny %d/%d%s | Evolve promises open %d%s'
          % (entry['shiny_mean_iv'], d('shiny_mean_iv', '%+.1f'), entry['shiny_stages_3star'], entry['shiny_stages'], d('shiny_stages_3star'), entry['labels'], d('labels')))
    if prev_rows:
        print('  since the %s walk: evolved %d (promises kept %d, broken %d), released or traded away %d, caught %d%s | pile %d = %d pushed out by better + %d fresh fodder + %d leftover%s'
              % (prev_stamp[11:13] + ':' + prev_stamp[13:15], evolved, kept_p, broken_p, released, caught,
                 ''.join(', %s %d' % (k, n) for k, n in (('hatched', hatched), ('traded to you', traded_in)) if n),
                 len(pile), bumped, fresh, leftover,
                 (' + %d no longer kept, and no new copy of its kind was kept (a rule or data change)' % rule_change) if rule_change else ''))
        if frozen:
            print('  *** nothing in the bag changed since the %s walk -- not one catch, hatch, evolution, release or power-up. '
                  'If you did any of those in between, this walk read a FROZEN copy of the game: do not act on this pass. ***'
                  % (prev_stamp[11:13] + ':' + prev_stamp[13:15]))
        if last is None:                              # no earlier ladder entry: nothing to attribute against
            print('  (no earlier ladder entry -- promises kept/broken and the pushed-out/leftover split are UNKNOWN this pass, not zero)')
        elif not _prev:                               # the previous walk never got a ladder entry of its own (a sync run
            # outside the cull): its labels and pile are unknown, so the ones used above are an OLDER pass's
            print('  (no ladder entry for the %s walk -- promises kept/broken and the pushed-out/leftover split are measured '
                  'against the %s pass, so they are APPROXIMATE)' % (prev_stamp[11:13] + ':' + prev_stamp[13:15], last['ts']))
        # only a real rise is a comb-up, and the count is of the SAME list, every entry printed (R-B review: with the
        # `inn > out` filter inside the join, "combed up at 5 stage(s)" listed 4 once a same-IV / special displacement
        # counts as pushed out; the [:6] cut made the count and the list disagree past 6)
        _cu = sorted((t for t in combup if t[2] > t[1]), key=lambda t: -(t[2] - t[1]))
        if _cu:
            print('  combed up at %d stage(s): %s' % (len(_cu), ', '.join(
                '%s %d%%->%d%%' % (sp, out * 100 // 45, inn * 100 // 45) for sp, out, inn in _cu)))
        try:
            _cs = json.load(open(os.path.join('system', 'analysis', 'candy_short.json')))
            if _cs:
                print('  held back for candy (would earn a slot, family cannot afford it now): %d -- %s'
                      % (len(_cs), ', '.join('%s %d%%' % (c['species'], (c['iv'] or 0) * 100 // 45) for c in sorted(_cs, key=lambda c: -(c['iv'] or 0))[:6])))
        except Exception as _e:                 # R-B review: the only hold line that vanished without a word (H06-7's family)
            print('  (candy-hold line unavailable: %r)' % (_e,))
        try:                                   # held for an ITEM he does not hold (2026-09-17: "i just dont have the stone")
            _is = json.load(open(os.path.join('system', 'analysis', 'item_short.json')))
            _by = collections.defaultdict(list)
            for c in sorted(_is, key=lambda c: -(c['iv'] or 0)):
                _by[c['item_name']].append('%s %d%%' % (c['species'], (c['iv'] or 0) * 100 // 45))
            for _it, _who in sorted(_by.items(), key=lambda kv: -len(kv[1])):
                print('  waiting on a %s (you have 0): %d -- %s' % (_it, len(_who), ', '.join(_who[:6])))
        except Exception as _e:
            print('  (item-hold line unavailable: %r)' % (_e,))
        try:                                   # shiny upgrades that need more than candy (2026-09-17)
            _sg = json.load(open(os.path.join('system', 'analysis', 'shiny_gated.json')))
            _WORDS = {'kmBuddyDistanceRequirement': 'a buddy walk', 'mustBeBuddy': 'a buddy walk',
                      'questDisplay': 'a task', 'lureItemRequirement': 'a lure module',
                      'onlyDaytime': 'daytime', 'onlyNighttime': 'night', 'onlyUpsideDown': 'the phone upside down'}
            _by = collections.defaultdict(list)
            for g in sorted(_sg, key=lambda g: -(g['iv'] or 0)):
                _need = (g.get('need') or g['item'] or ' + '.join(dict.fromkeys(_WORDS.get(w, w) for w in (g['why'] or [])))
                         or 'a trade or a random branch the label cannot name')
                _by[_need].append('%s %d%%' % (g['species'], (g['iv'] or 0) * 100 // 45))
            for _need, _who in sorted(_by.items(), key=lambda kv: -len(kv[1])):
                print('  shiny upgrade that is not a candy tap -- needs %s: %d (%s)' % (_need, len(_who), ', '.join(_who[:6])))
        except Exception as _e:
            print('  (shiny-gated line unavailable: %r)' % (_e,))
        try:                                   # showcase entries (user 2026-09-19 "i just want to win showcases")
            import showcase_plan as _sp, size_line as _sl
            _rw = _sp._rows()
            _big = [e for e in _sp.evolve_to_win(_rw) if e['size'] == 5]   # the badge carries through evolution (measured)
            if _big:
                _keep = [e for e in _big if not e['is_my_best_there']]
                print('  showcase: %d evolution(s) would out-score your best entry at the later stage (%d without '
                      'giving up your best at their own stage) -- top: %s'
                      % (len(_big), len(_keep), ', '.join('%s %.2fm -> %s (z %.1f)' % (e['species'], e['height_m'], e['target'], e['z_after'])
                                                          for e in sorted(_big, key=lambda x: -x['z_after'])[:3])))
        except Exception as _e:
            print('  (showcase line unavailable: %r)' % (_e,))
        try:                                   # what the game master makes visible (2026-09-17 "learn more about what the game has")
            import game_opportunities as _go
            _p = _go.purify_to_hundo()                   # reads the bag itself: every column it needs
            if _p:
                print('  purify into a HUNDO at a stage that has none: %d -- %s' % (len(_p), ', '.join(
                    '%s %d/%d/%d (%s dust + %s candy)' % (x['species'], *x['ivs'], format(x['dust'] or 0, ','), x['candy'])
                    for x in _p[:5])))
            import keep_config as _kc, granular_tags as _gt
            _live = [r for u, r in rows.items() if u not in pile]
            _tagged = _gt.second_move_ones(_live)             # the SAME set the Unlock 2nd Move tag holds (meta gate included)
            _sm = [x for x in _go.second_moves(_live) if x['uid'] in _tagged]
            if _sm:
                print('  Unlock 2nd Move (rank 1-%d, pvpoke top %d): %d -- cheapest: %s' % (_kc.pvp('action_rank'), _kc.pvp('unlock_meta_top'), len(_sm), ', '.join(
                    '%s %s (%s dust + %s candy)' % (x['species'], x['league'][0] + 'L', format(x['dust'] or 0, ','), x['candy'])
                    for x in sorted(_sm, key=lambda x: (x['dust'] or 0, x['candy'] or 0))[:5])))
        except Exception as _e:
            print('  (game-opportunity lines unavailable: %r)' % (_e,))
        # PvP CHECK, SHOWN EVERY CULL (user 2026-09-17 "it should always be checked....thats happening right?"). The engine
        # keeps any mon ranked 1-5 at a stage that reaches the league cap and the pre-flight re-checks every stage of
        # every pile mon; this line makes that visible and names the pile mon that came closest.
        try:
            from pvp_iv_rule import maxcp as _mcp, GL_CAP as _GL, UL_CAP as _UL, VIABILITY_MARGIN as _VM, READY_RANK as _RR
            _gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8')); _BS = {q['speciesId']: q.get('baseStats', {}) for q in _gm['pokemon']}
            _close = []
            for u in pile:
                r = rows[u]
                for lg, cap, nm in (('gl', _GL, 'Great'), ('ul', _UL, 'Ultra')):
                    for m_ in re.finditer(r'([a-z0-9_]+):(\d+)\(', r[lg + '_chain_ranks'] or ''):
                        if m_.group(1) in _BS and _mcp(m_.group(1), _BS) > cap + _VM:
                            _close.append((int(m_.group(2)), '%s %d/%d/%d, %s League #%s as %s' % (r['species_name'], r['iv_atk'], r['iv_def'], r['iv_sta'], nm, m_.group(2), m_.group(1))))
            _close.sort()
            _hits = [c for c in _close if c[0] <= _RR]
            if pile:
                print('  PvP check on the pile: %d checked, %s%s' % (len(pile), ('*** %d IN A TOP %d: %s' % (len(_hits), _RR, '; '.join(c[1] for c in _hits))) if _hits else 'none in any top %d' % _RR,
                                                                   ('' if _hits or not _close else ' (closest: %s)' % _close[0][1])))
        except Exception as _e:
            print('  PvP check on the pile could not run: %s' % _e)
        try:                                          # what you have to spend (user 2026-09-17 "read everything")
            _ip = os.path.join('system', 'analysis', 'inventory.json')
            _inv = json.load(open(_ip))
            _it = _inv.get('items') or {}
            _g = lambda *ks: next((v for k, v in _it.items() if any(x in k.lower() for x in ks)), None)
            # NOT THIS WALK'S (2026-09-29, H06-7): a failed in-walk read (pogo_pipeline.step_read_candy) leaves the PREVIOUS
            # inventory.json in place, and this line printed its stardust as if it had just been read. Same freshness rule
            # the engine's candy / item budget uses (evolvable_forms._walk_fresh: written by this walk, or not trusted).
            _wk = max((r.get('last_scanned') or '' for r in rows.values()), default='') or None
            if not evolvable_forms._walk_fresh(_ip, 7200, _wk):
                print('  inventory: NOT READ THIS WALK -- the numbers below are from %s (the walk\'s inventory read '
                      'failed; see the recrawl warnings)' % (_inv.get('read_at') or 'an older walk'))
            print('  inventory: stardust %s | coins %s | Rare Candy %s | Rare XL Candy %s | player level %s'
                  % ('{:,}'.format(_inv['stardust']) if isinstance(_inv.get('stardust'), int) else
                     ('unknown this walk (last read {:,} at {})'.format((_inv.get('currency_last_good') or {}).get('stardust') or 0,
                                                                      (_inv.get('currency_last_good') or {}).get('at'))
                      if (_inv.get('currency_last_good') or {}).get('stardust') else 'unknown'),
                     _inv.get('coins') if _inv.get('coins') is not None else 'unknown',
                     _it.get('ItemRareCandy', _g('rarecandy')), _it.get('ItemXlRareCandy', _g('xlrarecandy')), (_inv.get('player') or {}).get('Level')))
        except Exception as _ie:                      # H06-7: say it -- the line used to vanish without a word
            print('  inventory: unreadable (%s: %s)' % (type(_ie).__name__, _ie))
        if broken_names:
            print('  BROKEN PROMISES (investigate): ' + '; '.join(broken_names))
        _old = []                                         # leftovers: how long has each sat in the pile?
        for u in pile:
            first = None
            for h in reversed(hist[:-1] if '--dry' not in sys.argv else hist):
                if u in (h.get('_pile') or []): first = h['ts']
                else: break
            if first and first[:10] < entry['ts'][:10]:
                _old.append('%s %d%% (since %s)' % (rows[u]['species_name'], (rows[u]['iv_total'] or 0) * 100 // 45, first[5:16]))
        if _old:
            print('  NOT RELEASED for a day or more (locked in a gym/showcase, or keep it?): ' + '; '.join(_old))
        fmt = lambda k: ('%d (%s)' % (len(troph[k]), ', '.join(sorted(set(troph[k]))))) if troph[k] else '0'
        print('  new trophies: hundos %s | GL #1 %s | UL #1 %s | GL/UL #2-5 %d | stage best beaten at %d stage(s)%s'
              % (fmt('hundo'), fmt('GL #1'), fmt('UL #1'), len(troph['GL #2-5']) + len(troph['UL #2-5']), len(improved), (': ' + ', '.join(improved[:8]) + (' ...' if len(improved) > 8 else '')) if improved else ''))


if __name__ == '__main__':
    main()
