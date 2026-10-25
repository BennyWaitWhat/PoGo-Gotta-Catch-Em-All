"""GAME-MASTER CONSISTENCY AUDIT (2026-09-17, user: "Learn more about what the game has for info and be comprehensive").

The engine still carries a few hand-kept rosters. Each is checked here against the client game master every pass, so
a new release that the hand list has not caught up with BLOCKS the sync instead of silently mis-keeping a mon:

  1. RARITY  -- every pokemonClass LEGENDARY / MYTHIC / ULTRA_BEAST species in the game is in references.py's
                LEGENDARY/PARADOX, MYTHICAL, ULTRA_BEAST sets (rarity cap, 3-star floor, never-evolve all hang off them).
  1b. CATCHER -- the same species are all in AutoCatcher's hand-kept skip list, CFG["legendary"] in catch_loop_fast.py (2026-09-30:
                six Paradox legendaries had been missing; the catcher auto-throws up to 12 balls at any species not listed). The
                list is read from the catcher's SOURCE TEXT with ast -- the catcher is never imported or run. Only 144 / 145 / 146
                are deliberately absent (the Galarian birds: CFG["priority"] opens them first and the skip runs before it).
  2. GENDER  -- every evolution the game locks to ONE gender (evolutionBranch.genderRequirement with no sibling branch
                for the other gender) is in evolvable_forms.GENDER_TERMINALS, which the ranker and the labels use.
  3. TRANSFER -- no mon the game marks isTransferable=false sits in the Transfer pile (the game would refuse, and the
                tag would be a false instruction).
  4. MOVES   -- move_id_to_name.json names every move id the bag holds (an unnamed id is treated as legacy -- safe,
                but a sign the map is stale).

Read-only. Exit 1 (BLOCK) on 1, 1b, 2 and 3; 4 is a WARN (1b also WARNs on a listed dex the game does not class so).
"""
import ast, json, os, re, sqlite3, sys
from collections import defaultdict
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts')); sys.path.insert(0, ROOT)
import evolvable_forms
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS

norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())

CATCHER = os.path.normpath(os.path.join(ROOT, os.pardir, 'AutoCatcher', 'system', 'scripts', 'game_write', 'catch_loop_fast.py'))
# Deliberately NOT in the catcher's skip list (2026-09-30): the Galarian birds. CFG["priority"] opens them first, at the best ball, and the
# catcher's walk checks CFG["legendary"] BEFORE priority -- listing them would skip them. Every other game-master LEGENDARY / MYTHIC /
# ULTRA_BEAST dex must be listed.
CATCHER_ALLOW = {144: 'Articuno', 145: 'Zapdos', 146: 'Moltres'}


def catcher_legendary(path=CATCHER):
    """CFG["legendary"] from the catcher's SOURCE TEXT: ast.literal_eval of its module-level CFG dict. The catcher attaches to the
    game, so it is never imported or run here."""
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read(), path)
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CFG' for t in n.targets):
            return [int(x) for x in ast.literal_eval(n.value)['legendary']]
    raise ValueError('no module-level CFG = {...} in %s' % path)


def catcher_gaps(cls, listed):
    """(missing, stray): the game-master LEGENDARY / MYTHIC / ULTRA_BEAST dex the catcher's list lacks (minus CATCHER_ALLOW), and the
    listed dex the game master does not class that way."""
    game = set()
    for c in ('POKEMON_CLASS_LEGENDARY', 'POKEMON_CLASS_MYTHIC', 'POKEMON_CLASS_ULTRA_BEAST'):
        game |= set(cls.get(c, ()))
    return sorted(game - set(listed) - set(CATCHER_ALLOW)), sorted(set(listed) - game)


def scan_client_gm(gm):
    """(cls, dex_of, tf_form, tf_pid, gender_branch) of a client game master template list. PURE (2026-09-30): the
    rarity classes, isTransferable tables and gender-locked branches this audit judges, so gm_guard can judge a
    CANDIDATE game master the same way before it is installed."""
    cls, dex_of, tf_form, tf_pid, gender_branch = defaultdict(set), {}, {}, {}, defaultdict(set)
    for t in gm:
        s = (t.get('data') or {}).get('pokemonSettings')
        m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
        if not s or not m:
            continue
        d = int(m.group(1)); dex_of.setdefault(s['pokemonId'], d)
        if s.get('pokemonClass'):
            cls[s['pokemonClass']].add(d)
    # ABSENT = FALSE (2026-09-30, PokeMiners deep dive): the client game master prints these flags only when true -- 0 literal
    # false in 18,812 templates, while Mew/Celebi/Jirachi/Kyurem B-W (untransferable) and Deoxys (untradable) simply lack them.
    # Reading a missing flag as True made check 3 blind (it printed 0 locked; the bag holds 21) and offered 2 Deoxys for trade.
        if s.get('form'):
            tf_form[norm(s['form'])] = bool(s.get('isTransferable'))
        else:
            tf_pid.setdefault(d, bool(s.get('isTransferable')))
        for b in s.get('evolutionBranch') or []:
            if b.get('evolution'):
                gender_branch[(d, b['evolution'])].add(b.get('genderRequirement') or 'ANY')
    return cls, dex_of, tf_form, tf_pid, gender_branch


def row_transferable(r, enum, tf_form, tf_pid):
    """False when the game master marks this row's form (else its species) isTransferable=false. ONE definition for
    check 3 below and gm_guard (2026-09-30)."""
    f = r['fresh_form'] or r['form'] or 0
    v = tf_form.get(norm(enum.get(f, ''))) if f else None
    if v is None:
        v = tf_pid.get(r['pokemon_id'], True)
    return v


def main():
    gm = json.load(open('gamemaster_pokeminers.json', encoding='utf-8'))
    enum = {int(k): v for k, v in json.load(open('form_enum.json', encoding='utf-8')).items()}
    block, warn = [], []

    cls, dex_of, tf_form, tf_pid, gender_branch = scan_client_gm(gm)

    # 1. rarity
    for cname, ours, label in (('POKEMON_CLASS_LEGENDARY', set(LEGENDARY_IDS) | set(PARADOX_IDS), 'LEGENDARY/PARADOX'),
                               ('POKEMON_CLASS_MYTHIC', set(MYTHICAL_IDS), 'MYTHICAL'),
                               ('POKEMON_CLASS_ULTRA_BEAST', set(ULTRA_BEAST_IDS), 'ULTRA_BEAST')):
        gap = sorted(cls.get(cname, set()) - ours)
        if gap:
            block.append('%s: the game classes dex %s as %s but references.py does not -- rarity keep rules miss them'
                         % (label, gap, cname))
    # 1b. the catcher's own hand-kept skip list (2026-09-30: it had missed six Paradox legendaries, 1009 1010 1020-1023)
    listed = None
    try:
        listed = catcher_legendary(CATCHER)
    except (OSError, SyntaxError, ValueError, KeyError, TypeError) as e:
        block.append('CATCHER: cannot read CFG["legendary"] from catch_loop_fast.py (%s: %s) -- its skip list is unchecked against the game master'
                     % (type(e).__name__, e))
    if listed is not None:
        gap, stray = catcher_gaps(cls, listed)
        if gap:
            block.append('CATCHER: dex %s are LEGENDARY / MYTHIC / ULTRA_BEAST in the game master but missing from catch_loop_fast.py '
                         'CFG["legendary"] -- the catcher would auto-throw up to 12 balls at each; list them (only %s are deliberately absent)'
                         % (gap, sorted(CATCHER_ALLOW)))
        if stray:
            warn.append('CATCHER: CFG["legendary"] lists dex %s that the game master does not class LEGENDARY / MYTHIC / ULTRA_BEAST '
                        '(a newer client may; otherwise a typo skips a normal species)' % stray)
    # 2. gender
    for (d, target), genders in gender_branch.items():
        if genders & {'ANY'} or len(genders) != 1:
            continue                                   # both genders reach it (or a gendered FORM pair): not a lock
        g = {'MALE': 1, 'FEMALE': 2}[next(iter(genders))]
        other = 3 - g
        rule = evolvable_forms.GENDER_TERMINALS.get(d)
        tdex = dex_of.get(target)
        if rule is None or tdex in rule.get(other, set()) or tdex not in rule.get(g, set()):
            block.append('GENDER: dex %d -> %s is %s-only in the game but GENDER_TERMINALS does not say so'
                         % (d, target, next(iter(genders))))
    # 3. transferability of the pile
    pile = set(open(os.path.join('system', 'analysis', 'tagsets', '6_Transfer.txt')).read().split())
    c = sqlite3.connect('file:pokemon.db?mode=ro', uri=True); c.row_factory = sqlite3.Row
    rows = [__import__('keep_config').row_dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')]
    c.close()
    locked = 0
    for r in rows:
        v = row_transferable(r, enum, tf_form, tf_pid)
        if v is False:
            locked += 1
            if r['uid_hex'] in pile:
                block.append('TRANSFER: %s %s is isTransferable=false in the game but sits in the Transfer pile'
                             % (r['species_name'], r['uid_hex'][:8]))
    # 4. move names
    names = json.load(open('move_id_to_name.json', encoding='utf-8'))
    unk = sorted({m for r in rows for m in (r['move1'], r['move2'], r['move3']) if m and str(m) not in names})
    if unk:
        warn.append('MOVES: move ids %s are not in move_id_to_name.json (held mons are kept as legacy -- regenerate the map)' % unk)

    # PVPOKE MUST STILL AGREE WITH THE CLIENT'S OWN GAME MASTER (2026-09-20). reconcile_gamemaster.py copies the
    # game's evolution edges into pvpoke's file; a fresh pvpoke download, a hand-edit or a failed refresh silently
    # undoes that, and the loss is invisible -- rank_cache._reachable() only ever REMOVES stages, so a missing
    # edge is a later stage that is simply never scored (a Galarian Corsola ranked as if Cursola did not exist).
    # --dry-run makes no changes; it just reports what would still need doing.
    import subprocess as _sub
    _r = _sub.run([sys.executable, os.path.join(ROOT, 'reconcile_gamemaster.py'), '--dry-run'],
                  capture_output=True, text=True, timeout=900)
    _out = (_r.stdout or '') + (_r.stderr or '')
    if _r.returncode != 0:
        block.append('RECONCILE: reconcile_gamemaster.py --dry-run failed rc=%d -- pvpoke cannot be checked '
                     'against the game' % _r.returncode)
    else:
        _pend = [int(m) for m in re.findall(r'(?:corrected from the game|dropped \(the game declares the '
                                            r'opposite direction\)|added \(additive only, never removed\)): '
                                            r'(\d+)', _out)]
        if sum(_pend) if _pend else 1:
            block.append('RECONCILE: pvpoke_gamemaster.json has DRIFTED from the client game master -- %s. '
                         'Run: python reconcile_gamemaster.py'
                         % '; '.join(l.strip() for l in _out.splitlines()
                                     if l.strip().startswith(('BASE STATS', 'REVERSED', 'EVOLUTION'))))

    # MULTI-FORM STAGES MUST BE NAMEABLE (2026-09-20). One pvpoke speciesId can cover several plain forms --
    # 28 Unown letters, 5 Florges colours, 2 Gastrodon seas, 4 Sawsbuck seasons -- and every pool that answers
    # "do I already have one of these" must split them, or one colour answers for another. The split relies on
    # the GAME naming which form a pre-evo becomes; where it does not, the code falls back to the whole
    # speciesId, which is the old, wrong behaviour. Surface any such stage instead of letting it fall back
    # silently: a newly released split family shows up here the cycle it appears.
    import rank_cache as _rc
    _pdb = {p['speciesId']: p for p in
            json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))['pokemon']}
    _enum2 = {int(k): v for k, v in json.load(open(os.path.join(ROOT, 'form_enum.json'), encoding='utf-8')).items()}
    _forms_at, _src_of = defaultdict(set), defaultdict(set)
    for r in rows:
        _f = r['form'] or 0
        _sd = _rc.to_pvpoke_id(r['species_name'], _f, 0)
        if not _sd:
            continue
        _cn = evolvable_forms.canon_form(_sd, evolvable_forms.form_name(_f))
        if _cn:
            _forms_at[_sd].add(_cn)
        for _t in _rc.get_evolutions(_pdb, _sd)[1:]:
            _src_of[_t].add((r['species_name'], _f, r['gender']))
    _blind = []
    for _sd, _fs in sorted(_forms_at.items()):
        if len(_fs) < 2 or _sd not in _src_of:
            continue
        for _sp, _f, _g in sorted(_src_of[_sd]):
            if not evolvable_forms.target_form(_f, _sd, _rc.to_pvpoke_id(_sp, _f, 0), _g):
                _blind.append('%s form %s -> %s (%d forms held)'
                              % (_sp, _enum2.get(_f, _f), _sd, len(_fs)))
    if _blind:
        warn.append('MULTI-FORM STAGE the game does not name a target form for -- these pool by speciesId and one '
                    'form answers for another: %s' % '; '.join(sorted(set(_blind))[:8]))

    # 5. MAX MODES -- every bag mon's breadModeEnum value must name a mode the game master lists for that species, or
    # evolvable_forms.BREAD_MODES maps the enum wrong and Max copies are capped on the wrong axis (or read as plain).
    _bm_of = defaultdict(set)
    def _bwalk(o, d):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == 'breadMode' and isinstance(v, str):
                    _bm_of[d].add(v)
                _bwalk(v, d)
        elif isinstance(o, list):
            for x in o:
                _bwalk(x, d)
    for t in gm:
        m = re.match(r'(?:EXTENDED_)?V(\d{4})_POKEMON_', t.get('templateId', ''))
        if m:
            _bwalk(t.get('data') or {}, int(m.group(1)))
    _listed = set().union(*_bm_of.values()) if _bm_of else set()
    _bad, _newer = defaultdict(int), defaultdict(int)
    for r in rows:
        b = r['fresh_bread_mode'] or 0
        if b and evolvable_forms.BREAD_MODES.get(b) not in _bm_of.get(r['pokemon_id'], ()):
            _k = '%s mode %d (%s; game lists %s)' % (r['species_name'], b, evolvable_forms.BREAD_MODES.get(b, 'UNKNOWN'),
                                                     sorted(_bm_of.get(r['pokemon_id'], ())) or 'none')
            # 2026-10-24: a species with NO Max entry at all in this batch, holding a mode whose name IS the one the game lists
            # for other species, is a Max release newer than the batch (3 Dynamax Azelf vs the 0.427.0 batch; 212 other mode-1
            # mons prove the map), not a wrong BREAD_MODES. A species that lists other modes, or an unlisted name, stays BLOCK.
            if not _bm_of.get(r['pokemon_id']) and evolvable_forms.BREAD_MODES.get(b) in _listed:
                _newer[_k] += 1
            else:
                _bad[_k] += 1
    if _bad:
        block.append('MAX MODE the game master does not list for the species -- evolvable_forms.BREAD_MODES is wrong: %s'
                     % '; '.join('%s x%d' % kv for kv in sorted(_bad.items())[:8]))
    if _newer:
        warn.append('MAX MODE NEWER THAN THE GAME MASTER -- no Max entry for the species in this batch, but the mode name is the '
                    'one the game lists for other species (a Max release after the batch): %s'
                    % '; '.join('%s x%d' % kv for kv in sorted(_newer.items())[:8]))
    _nmax = sum(1 for r in rows if r['fresh_bread_mode'])

    # 6. COSTUME FLAGS (2026-09-30, user: "do whats best and not lazy" -> costume option 5; LAW.md "WHAT COUNTS AS A COSTUME").
    # costume_forms calls a form-encoded costume what its enum NAME says OR what the game itself flags (formSettings.forms[].isCostume),
    # add only. Re-derived here from the RAW game master -- never through costume_forms' cache or parser -- so a stale cache, a parser
    # reading the wrong field or a dropped union cannot vouch for itself:
    #   BLOCK  a form the game flags isCostume that costume_forms does not treat as a costume: the game-master layer failed, and every
    #          copy of that form would be judged PLAIN again (a costume in the irreversible pile) -- or a BASE form (<Species>Normal) the
    #          game flags: add-only applies it as written, and a plain form read as a costume empties its species' plain ladder (the
    #          shape of the 2026-09-02 +62-into-the-pile incident), so a human looks first
    #   WARN   the flags were not loaded although the file exists (the name rule alone decides), or come from the STALE cache of an
    #          older game master (the file was unreadable when costume_forms loaded): costume status rests on an old verdict, or none
    #   INFO   how many costumes only the name rule knows (the add-only direction at work: the game master lags the enum and leaves
    #          isCostume unset on some event skins) -- a line to read, never a verdict
    import costume_forms as _cfm
    _cflag = {}
    for t in gm:
        for _cf in (((t.get('data') or {}).get('formSettings') or {}).get('forms') or []):
            if _cf.get('form'):
                _cflag[norm(_cf['form'])] = bool(_cf.get('isCostume'))
    _cgame = [(_k, _n) for _k, _n in _cfm.FORM_ENUM.items() if _cflag.get(norm(_n))]          # enum codes the game flags
    _clost = sorted(_n for _k, _n in _cgame if _k not in _cfm.COSTUME_FORMS)
    if _clost:
        block.append('COSTUME FLAGS: the game master flags %d form(s) isCostume that costume_forms does not treat as costumes -- the '
                     'game-master layer failed (stale cache? load error? a dropped union?) and their copies would be judged PLAIN: %s'
                     % (len(_clost), ', '.join(_clost[:8])))
    _cbase = sorted(_n for _k, _n in _cgame if _cfm.classify(_n) == 'base')
    if _cbase:
        block.append('COSTUME FLAGS: the game master flags the BASE form(s) %s isCostume -- a plain form read as a costume empties its '
                     "species' plain ladder (a game-master error, or a new meaning): look before syncing; the flag is applied as written"
                     % ', '.join(_cbase[:8]))
    _csrc = getattr(_cfm, 'GM_SOURCE', None)
    if _csrc == 'stale_cache':
        warn.append('COSTUME FLAGS: costume_forms runs from the STALE CACHE of an older game master, not from '
                    'gamemaster_pokeminers.json (%s)' % getattr(_cfm, 'GM_NOTE', None))
    elif _csrc != 'game_master':
        warn.append('COSTUME FLAGS: costume_forms loaded NO game-master flags although gamemaster_pokeminers.json exists (%s)'
                    % (getattr(_cfm, 'GM_NOTE', None) or 'GM_SOURCE=%r -- the name rule alone decides costume status' % _csrc))
    if not _cflag:
        warn.append('COSTUME FLAGS: gamemaster_pokeminers.json lists no formSettings forms at all (a format change?) -- nothing to check the '
                    'costume layer against')
    _conly = [_n for _k, _n in _cfm.FORM_ENUM.items() if _cfm.classify(_n) == 'costume' and not _cflag.get(norm(_n))]
    _cunl = sum(1 for _n in _conly if norm(_n) not in _cflag)
    print('  INFO  costume flags: the game master flags %d forms isCostume (%d of them in the enum, %d costumes here); %d costumes only the '
          'name rule catches (%d the game does not list yet, %d it lists unflagged); game-master layer source: %s'
          % (sum(1 for _v in _cflag.values() if _v), len(_cgame), len(_cgame) - len(_clost), len(_conly), _cunl, len(_conly) - _cunl, _csrc))

    print('game master: %d legendary, %d mythic, %d ultra beast; %d one-gender evolutions; %d non-transferable in bag'
          % (len(cls.get('POKEMON_CLASS_LEGENDARY', ())), len(cls.get('POKEMON_CLASS_MYTHIC', ())),
             len(cls.get('POKEMON_CLASS_ULTRA_BEAST', ())),
             sum(1 for g in gender_branch.values() if 'ANY' not in g and len(g) == 1), locked))
    if listed is not None and not catcher_gaps(cls, listed)[0]:
        print('catcher skip list: %d dex in CFG["legendary"]; every game-master LEGENDARY / MYTHIC / ULTRA_BEAST dex is covered except the '
              'deliberate %s' % (len(set(listed)), sorted(CATCHER_ALLOW)))
    for w in warn:
        print('  *** WARN  ' + w)
    for b in block:
        print('  *** BLOCK ' + b)
    print('VERDICT: %s' % ('GAME MASTER CONSISTENT' if not block else '%d GAME-MASTER GAP(S) -- do not sync' % len(block)))
    return 1 if block else 0


if __name__ == '__main__':
    sys.exit(main())
