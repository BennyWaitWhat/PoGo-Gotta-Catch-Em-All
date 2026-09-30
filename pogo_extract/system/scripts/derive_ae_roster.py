"""derive_ae_roster.py -- turn the game's LIVE Adventure-Effect registry into a species roster and check it
against what the cull actually protects. Offline; never touches the phone.

WHY (user, 2026-09-08: the AE roster "should be scanned every time"). keep_config.adventure_effect_pids was a
hand list. On 2026-09-08 the live registry (AdventureEffectService.adventureEffects, read in-walk by
pogo_pipeline.step_read_ae_registry into system/analysis/ae_registry_live.json) held 11 effects against the
9 the list knew: Mega Mewtwo X (Dynamic Punch+) and Mega Mewtwo Y (Future Sight+) were new. Mewtwo happened to
be protected by rarity keep-all, so nothing was exposed -- by luck, not by design. This script removes the luck.

HOW A MOVE BECOMES A SPECIES (three independent sources, unioned; every attribution is printed with its source):
  1. the registry's own desc_key ("dialga_move_content", "dusk_mane_move_content", "zacian_move_content"...)
  2. the HoloPokemonMove enum NAME for temp-evolution moves ("VmMoveTempEvolutionMegaXV0150PokemonMewtwo" -> 150)
  3. the PokeMiners / client game master: any pokemonSettings whose cinematicMoves / eliteCinematicMoves /
     nonTmCinematicMoves / formChange.moveReassignment.replacementMoves contain the move (by NAME or numeric id)

OUTPUT: system/analysis/ae_roster_derived.json {species:[dex...], by_species:{dex:[moves]}, unprotected:[dex...]}
EXIT: 0 = every derived species is protected (in adventure_effect_pids, or rarity_keep_all, or protected_keep_all)
      2 = a derived species is NOT protected by anything -> keep_config needs the pid (a human decision); the
          engine also unions the derived set defensively (see keep_policy AE_IDS), so this is belt AND braces.
      1 = no usable registry json (never guess a roster from memory)
"""
import sys, os, re, json, glob, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
REG = os.path.join(ROOT, 'system', 'analysis', 'ae_registry_live.json')
OUT = os.path.join(ROOT, 'system', 'analysis', 'ae_roster_derived.json')
MAX_AGE_DAYS = 14

# desc_key / enum-name hints -> dex. Kept tiny and obvious; source 3 does the general work.
HINTS = {'dialga': 483, 'palkia': 484, 'dusk_mane': 800, 'dawn_wings': 800, 'necrozma': 800, 'kyurem': 646,
         'ice_burn': 646, 'freeze_shock': 646, 'zacian': 888, 'zamazenta': 889, 'eternatus': 890, 'dynamax_cannon': 890,
         # Mega Mewtwo X / Y (2026-09-20). These used to resolve from the temp-evo ENUM NAME
         # ('VmMoveTempEvolutionMegaXV0150PokemonMewtwo' -> 150); the live read now returns a bare MOVE_495 / MOVE_496,
         # so that source went blind and Mewtwo silently dropped out of the derived roster. The desc_key still reads
         # correctly, so it is the fallback. (Mewtwo is rarity keep-all, so nothing was ever at risk.)
         'dynamic_punch_+': 150, 'future_sight_+': 150}


def load_gm():
    """Prefer the client game master PokeMiners publishes; fall back to nothing (source 3 then contributes 0)."""
    for cand in (os.path.join(ROOT, 'gamemaster_pokeminers.json'),
                 os.path.join(os.environ.get('SCRATCH', ''), 'gm_pokeminers.json')):
        if cand and os.path.exists(cand):
            try:
                return json.load(open(cand, encoding='utf-8'))
            except Exception:
                pass
    return []


def species_from_gm(gm, move_names, move_ids):
    hits = {}
    for t in gm:
        d = t.get('data', {}); ps = d.get('pokemonSettings')
        if not ps:
            continue
        m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
        if not m:
            continue
        dex = int(m.group(1))
        pool = set()
        for k in ('cinematicMoves', 'eliteCinematicMoves', 'nonTmCinematicMoves', 'eliteCinematicMove'):
            v = ps.get(k) or []
            pool |= set(v if isinstance(v, list) else [v])
        for fc in ps.get('formChange') or []:
            for mr in (fc.get('moveReassignment') or {}).get('cinematicMoves') or []:
                pool |= set(mr.get('replacementMoves') or []) | set(mr.get('existingMoves') or [])
        for mv in pool:
            if (isinstance(mv, str) and mv in move_names) or (isinstance(mv, int) and mv in move_ids):
                hits.setdefault(dex, set()).add(str(mv))
    return hits


def registry_vs_walk(reg, db=os.path.join(ROOT, 'pokemon.db')):
    """(read_this_walk, walk_stamp, read_local): was ae_registry_live.json written by the walk being judged? (H04)

    The in-walk read is fail-soft -- a failed read leaves the OLD json in place -- and this script rewrites
    ae_roster_derived.json on every pass, so the derived file's age (all audit_invariants looked at) proved nothing and
    the last line said "every live Adventure-Effect species is protected" over a registry of any age. The walk stamp is
    pokemon.db MAX(last_scanned) (local time, taken before the registry step of the same walk); 'generated' is UTC.
    None = cannot tell (no walk stamp / unparseable time). Third value: the registry read time in LOCAL time."""
    try:
        import calendar, sqlite3
        _c = sqlite3.connect('file:%s?mode=ro' % db.replace(chr(92), '/'), uri=True)
        try:
            ws = _c.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0]
        finally:
            _c.close()
        if not ws:
            return None, None, None
        w = time.mktime(time.strptime(str(ws)[:19], '%Y-%m-%dT%H:%M:%S'))
        try:
            g = calendar.timegm(time.strptime(str(reg.get('generated'))[:19], '%Y-%m-%dT%H:%M:%S'))
        except Exception:
            return None, str(ws), None                   # the walk's time is known; the registry's is not (R-B review)
        return g >= w - 5, str(ws), time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(g))
    except Exception:
        return None, None, None


def main():
    if not os.path.exists(REG):
        print('NO REGISTRY: %s missing -- run a recrawl (pogo_pipeline reads it in-walk). Refusing to guess.' % REG)
        return 1
    reg = json.load(open(REG, encoding='utf-8'))
    age = (time.time() - os.path.getmtime(REG)) / 86400.0
    effects = reg.get('effects', [])
    print('registry: %d effects, %.1f days old (generated %s)' % (len(effects), age, reg.get('generated')))
    if age > MAX_AGE_DAYS:
        print('  WARN registry older than %d days -- a recrawl refreshes it' % MAX_AGE_DAYS)
    _this_walk, _walk, _read_local = registry_vs_walk(reg)
    # the line full_audit shows is the LAST one: a registry the judged walk did not re-read must say so THERE
    _stale = ('WARN: AE registry NOT read by this walk (registry %s, walk %s)'
              % ((_read_local or '?')[:16], (_walk or '?')[:16])) if _this_walk is False else (
        # CANNOT TELL IS NOT "OK" EITHER (R-B review): no walk stamp, or no parseable 'generated' in the registry
        'WARN: AE registry vs walk: cannot tell (generated %s, walk %s)' % (str(reg.get('generated'))[:20], (_walk or '?')[:16])
        if _this_walk is None else '')
    if _stale:
        print('  %s. The in-walk read is fail-soft: look for "[ae_registry] read FAILED" in the recrawl log.' % _stale)

    by_species = {}
    def attr(dex, move, src):
        by_species.setdefault(dex, set()).add('%s [%s]' % (move, src))

    move_names = set(); move_ids = set()
    _eff_names = []                                   # gm_name per effect, to find the ones nothing claims
    for e in effects:
        mv = e.get('move') or ('MOVE_%s' % e.get('move_id')); mid = e.get('move_id')
        move_ids.add(mid)
        # normalise the live enum name (V0394MoveRoarOfTime) to the game-master id (ROAR_OF_TIME)
        gm_name = re.sub(r'^V\d{4}Move', '', mv)
        gm_name = re.sub(r'(?<!^)(?=[A-Z])', '_', gm_name).upper()
        _eff_names.append((e, gm_name))
        move_names.add(gm_name); move_names.add(mv)
        # source 1: desc_key hints
        dk = (e.get('desc_key') or '').lower()
        for hint, dex in HINTS.items():
            if hint in dk or hint in gm_name.lower():
                attr(dex, gm_name, 'desc_key' if hint in dk else 'move-name')
        # source 2: temp-evo enum names carry the dex
        m = re.search(r'V(\d{4})Pokemon', mv)
        if m:
            attr(int(m.group(1)), mv, 'enum-name')

    gm = load_gm()
    for dex, moves in species_from_gm(gm, move_names, move_ids).items():
        for mv in moves:
            attr(dex, mv, 'game-master')
    print('game master templates consulted: %d' % len(gm))

    # FORM LEVEL (user 2026-09-09: "if it doesnt have the adventure effect, i dont want it tagged"). The in-game
    # 'Adventure Effect' filter counts the FORMS that carry the effect (Origin Dialga/Palkia, Black/White Kyurem,
    # Crowned Zacian/Zamazenta, Dusk Mane/Dawn Wings Necrozma, Eternatus), not every copy of the species: an
    # Altered Dialga can know Roar of Time and still has no effect. PvPoke's game master lists the effect move
    # only in the movepool of the form that has it, so: speciesIds whose charged/elite/legacy pool contains a
    # live-registry move = the AE-capable forms. keep_policy / preflight / audit_cull key rule 8 on THIS set
    # (via pvid(species, form)) and fall back to the species list only when this file is missing or stale.
    species_ids = {}
    try:
        _pv = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
        for p in _pv['pokemon']:
            pool = set(p.get('chargedMoves') or []) | set(p.get('eliteMoves') or []) | set(p.get('legacyMoves') or [])
            hit = sorted(pool & move_names)
            if hit:
                species_ids[p['speciesId']] = hit
    except Exception as _e:
        print('WARN: could not derive form-level speciesIds from pvpoke_gamemaster.json (%s)' % _e)
    print('\nADVENTURE-EFFECT FORMS (PvPoke speciesIds, %d):' % len(species_ids))
    for s, mv in sorted(species_ids.items()):
        print('   %-26s %s' % (s, ', '.join(mv)))

    import keep_config as kc
    ae = set(kc.ae_pids())
    rk = set(getattr(kc, 'rarity_keep_all', lambda: [])()) | set(getattr(kc, 'rarity_ladder_pids', lambda: [])())   # Mewtwo's
    #      league ladder (2026-09-26) keeps every special copy; its "effects" are the Mega X/Y evolutions no copy knows
    pk = set(getattr(kc, 'protected_pids', lambda: [])())
    derived = sorted(by_species)
    unprotected = [d for d in derived if d not in ae and d not in rk and d not in pk]
    print('\nDERIVED ADVENTURE-EFFECT SPECIES (%d):' % len(derived))
    for d in derived:
        tag = 'AE roster' if d in ae else ('rarity keep-all' if d in rk else ('protected keep-all' if d in pk else '*** UNPROTECTED ***'))
        print('   #%-4d %-22s %s' % (d, tag, '; '.join(sorted(by_species[d]))[:110]))
    stale = sorted(ae - set(derived))
    if stale:
        print('in keep_config but NOT derived from the live registry (review, over-protection only): %s' % stale)
    json.dump({'schema': 2, 'generated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'registry_generated': reg.get('generated'),
               'species': derived, 'by_species': {str(k): sorted(v) for k, v in by_species.items()},
               'species_ids': species_ids,          # FORM level: PvPoke speciesId -> AE moves (schema 2, 2026-09-09)
               'unprotected': unprotected, 'configured': sorted(ae),
               'registry_this_walk': _this_walk, 'walk': _walk},     # H04: False = judged on an older registry read
              open(OUT, 'w', encoding='utf-8'), indent=1)
    print('-> %s' % os.path.relpath(OUT, ROOT))
    if unprotected:
        print('*** %d derived species have NO protection in keep_config: %s -- add to adventure_effect_pids ***' % (len(unprotected), unprotected))
        return 2
    # AN ENTRY NOTHING CLAIMS IS UNCHECKED, NOT PROTECTED (2026-09-20). `unprotected` can only list species this
    # script managed to map, so a live effect whose move maps to NO species never reached it -- and the OK below
    # printed anyway. It first fired on MOVE_495/496 -- Mega Mewtwo X/Y's moves, which had only lost their enum NAME;
    # a desc_key HINT fixed that. (I first mis-called them 'moves no species learns yet': normal learnsets never list
    # temp-evolution moves, so searching them proves nothing.) A future unmapped entry gets the same treatment:
    # WARN every pass so a HINT gets added; BLOCK only when something in the bag actually carries one.
    _claimed = {v.split(' [')[0] for vs in by_species.values() for v in vs}
    _orph = [e for e, gn in _eff_names if gn not in _claimed]
    if _orph:
        _ids = sorted({int(e['move_id']) for e in _orph if e.get('move_id') is not None})
        print('*** WARN: %d live Adventure-Effect entr%s map to NO species, so protection cannot be checked: %s'
              % (len(_orph), 'y' if len(_orph) == 1 else 'ies',
                 ', '.join('%s (%s)' % (e.get('move') or e.get('move_id'), e.get('desc_key')) for e in _orph)))
        try:
            import sqlite3
            _c = sqlite3.connect('file:%s?mode=ro' % os.path.join(ROOT, 'pokemon.db').replace(chr(92), '/'), uri=True)
            _q = ','.join('?' * len(_ids))
            _n = _c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (move1 IN (%s) OR move2 IN (%s) OR move3 IN (%s))'
                            % (_q, _q, _q), _ids * 3).fetchone()[0] if _ids else 0
            _c.close()
        except Exception as _e:
            print('*** cannot check bag exposure (%s) -- treating as exposed' % _e); _n = 1
        if _n:
            print('*** %d in-bag mon(s) CARRY an unmapped Adventure-Effect move -- add a HINT for it before culling ***' % _n)
            return 2
        # The LAST line is the only one full_audit.py shows, so the warning has to BE that line or nobody sees it
        # (2026-09-20: it printed above an 'OK' and was swallowed every cull).
        print('WARN: %d Adventure-Effect entr%s unmapped (%s) -- not carried by any bag mon; add a HINT'
              % (len(_orph), 'y' if len(_orph) == 1 else 'ies', ', '.join(str(i) for i in _ids)))
        if _stale:
            print('%s +%d unmapped' % (_stale, len(_orph)))           # <= 110 chars: full_audit cuts there
        return 0
    if _stale:                                   # NOT "every LIVE species": the judged walk did not read the registry
        print(_stale)                                              # <= 110 chars: full_audit cuts there
        return 0
    print('OK: every live Adventure-Effect species is protected.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
