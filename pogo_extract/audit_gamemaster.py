"""GAME-MASTER CONSISTENCY AUDIT (2026-09-17, user: "Learn more about what the game has for info and be comprehensive").

The engine still carries a few hand-kept rosters. Each is checked here against the client game master every pass, so
a new release that the hand list has not caught up with BLOCKS the sync instead of silently mis-keeping a mon:

  1. RARITY  -- every pokemonClass LEGENDARY / MYTHIC / ULTRA_BEAST species in the game is in references.py's
                LEGENDARY/PARADOX, MYTHICAL, ULTRA_BEAST sets (rarity cap, 3-star floor, never-evolve all hang off them).
  2. GENDER  -- every evolution the game locks to ONE gender (evolutionBranch.genderRequirement with no sibling branch
                for the other gender) is in evolvable_forms.GENDER_TERMINALS, which the ranker and the labels use.
  3. TRANSFER -- no mon the game marks isTransferable=false sits in the Transfer pile (the game would refuse, and the
                tag would be a false instruction).
  4. MOVES   -- move_id_to_name.json names every move id the bag holds (an unnamed id is treated as legacy -- safe,
                but a sign the map is stale).

Read-only. Exit 1 (BLOCK) on 1-3; 4 is a WARN.
"""
import json, os, re, sqlite3, sys
from collections import defaultdict
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts')); sys.path.insert(0, ROOT)
import evolvable_forms
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS

norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())


def main():
    gm = json.load(open('gamemaster_pokeminers.json', encoding='utf-8'))
    enum = {int(k): v for k, v in json.load(open('form_enum.json', encoding='utf-8')).items()}
    block, warn = [], []

    cls, dex_of, tf_form, tf_pid, gender_branch = defaultdict(set), {}, {}, {}, defaultdict(set)
    for t in gm:
        s = (t.get('data') or {}).get('pokemonSettings')
        m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
        if not s or not m:
            continue
        d = int(m.group(1)); dex_of.setdefault(s['pokemonId'], d)
        if s.get('pokemonClass'):
            cls[s['pokemonClass']].add(d)
        if s.get('form'):
            tf_form[norm(s['form'])] = s.get('isTransferable', True)
        else:
            tf_pid.setdefault(d, s.get('isTransferable', True))
        for b in s.get('evolutionBranch') or []:
            if b.get('evolution'):
                gender_branch[(d, b['evolution'])].add(b.get('genderRequirement') or 'ANY')

    # 1. rarity
    for cname, ours, label in (('POKEMON_CLASS_LEGENDARY', set(LEGENDARY_IDS) | set(PARADOX_IDS), 'LEGENDARY/PARADOX'),
                               ('POKEMON_CLASS_MYTHIC', set(MYTHICAL_IDS), 'MYTHICAL'),
                               ('POKEMON_CLASS_ULTRA_BEAST', set(ULTRA_BEAST_IDS), 'ULTRA_BEAST')):
        gap = sorted(cls.get(cname, set()) - ours)
        if gap:
            block.append('%s: the game classes dex %s as %s but references.py does not -- rarity keep rules miss them'
                         % (label, gap, cname))
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
        f = r['fresh_form'] or r['form'] or 0
        v = tf_form.get(norm(enum.get(f, ''))) if f else None
        if v is None:
            v = tf_pid.get(r['pokemon_id'], True)
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
    _bad = defaultdict(int)
    for r in rows:
        b = r['fresh_bread_mode'] or 0
        if b and evolvable_forms.BREAD_MODES.get(b) not in _bm_of.get(r['pokemon_id'], ()):
            _bad['%s mode %d (%s; game lists %s)' % (r['species_name'], b, evolvable_forms.BREAD_MODES.get(b, 'UNKNOWN'),
                                                     sorted(_bm_of.get(r['pokemon_id'], ())) or 'none')] += 1
    if _bad:
        block.append('MAX MODE the game master does not list for the species -- evolvable_forms.BREAD_MODES is wrong: %s'
                     % '; '.join('%s x%d' % kv for kv in sorted(_bad.items())[:8]))
    _nmax = sum(1 for r in rows if r['fresh_bread_mode'])

    print('game master: %d legendary, %d mythic, %d ultra beast; %d one-gender evolutions; %d non-transferable in bag'
          % (len(cls.get('POKEMON_CLASS_LEGENDARY', ())), len(cls.get('POKEMON_CLASS_MYTHIC', ())),
             len(cls.get('POKEMON_CLASS_ULTRA_BEAST', ())),
             sum(1 for g in gender_branch.values() if 'ANY' not in g and len(g) == 1), locked))
    for w in warn:
        print('  *** WARN  ' + w)
    for b in block:
        print('  *** BLOCK ' + b)
    print('VERDICT: %s' % ('GAME MASTER CONSISTENT' if not block else '%d GAME-MASTER GAP(S) -- do not sync' % len(block)))
    return 1 if block else 0


if __name__ == '__main__':
    sys.exit(main())
