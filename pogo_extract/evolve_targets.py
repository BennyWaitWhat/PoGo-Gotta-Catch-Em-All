"""WHICH WAY TO EVOLVE (user 2026-09-24: "theres some that you dont tell me which to evolve it to").

Every mon in an evolve tag whose evolution the game lets go more than one way (Gloom -> Vileplume OR Bellossom,
Eevee -> 8 ways, Charcadet -> Armarouge OR Ceruledge), with the branch the cull meant. The branches, their gender
locks and their forms are the client game master's (evolvable_forms._tform); the targets are the ones each tag was
built from -- promises.json (Evolve Next / Twice / Gated), pvp_combup_labels.json (Evolve for GL / UL / Gated),
refresh_evolve_shiny (Evolve Shiny / Shiny Gated), sync_evolve_size (Evolve for Size). A tag whose line only goes
one way is left out: there is nothing to choose.

  python evolve_targets.py            # the lines full_audit prints after every cull
  python evolve_targets.py --selfcheck
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))

EVOLVE_TAGS = ('Evolve Once', 'Evolve Twice', 'Evolve Gated', 'Evolve for GL', 'Evolve for UL')   # the folds, 2026-09-29/30
# The Eevee name trick picks the eeveelution (once per account per name).
EEVEE_NAMES = {'vaporeon': 'Rainer', 'jolteon': 'Sparky', 'flareon': 'Pyro', 'espeon': 'Sakura', 'umbreon': 'Tamao',
               'leafeon': 'Linnea', 'glaceon': 'Rea', 'sylveon': 'Kira'}
REGIONS = ('GALARIAN', 'ALOLA', 'HISUIAN', 'PALDEA')
norm_uid = lambda u: format(int(u, 16), 'x')


def _opts(tform, key, gender):
    """[(target name, target form)] the game offers this source form / gender."""
    g = {1: 'MALE', 2: 'FEMALE'}.get(gender)
    return [(n, f) for n, lst in (tform.get(key) or {}).items() for f, greq in lst if not (greq and greq != g)]


def _match(f, want):
    return f.startswith(want) or want.startswith(f)          # evolvable_forms.target_forms' own rule


def _reaches(tform, key, want, gender, depth=4):
    seen, front = {key}, [key]
    for _ in range(depth):
        nxt = []
        for k in front:
            for _n, f in _opts(tform, k, gender):
                if _match(f, want):
                    return True
                if f not in seen:
                    seen.add(f); nxt.append(f)
        front = nxt
    return False


def path(tform, key, target, gender):
    """[(options at that step, the options that lead to target)] from `key` to `target`; None when the game master
    shows no way there."""
    want, steps = target.upper().replace('_', ''), []
    for _ in range(4):
        opts = _opts(tform, key, gender)
        hit = [o for o in opts if _match(o[1], want)]
        via = hit or [o for o in opts if _reaches(tform, o[1], want, gender)]
        if not via:
            return None
        steps.append((opts, via))
        if hit:
            return steps
        key = via[0][1]
    return None


def _nice(sid):
    """'slowking_galarian' -> 'Galarian Slowking', 'mr_mime' -> 'Mr. Mime'."""
    p = sid.split('_')
    reg = {'galarian': 'Galarian', 'alolan': 'Alolan', 'hisuian': 'Hisuian', 'paldean': 'Paldean'}
    if len(p) > 1 and p[-1] in reg:
        return reg[p[-1]] + ' ' + ' '.join(x.capitalize() for x in p[:-1])
    return {'mr_mime': 'Mr. Mime', 'mime_jr': 'Mime Jr.'}.get(sid, ' '.join(x.capitalize() for x in p))


def _disp(name, form):
    """A branch as the game shows it: ('slowbro', 'SLOWBROGALARIAN') -> 'Galarian Slowbro'."""
    reg = next((r for r in REGIONS if r in form), None)
    return {'GALARIAN': 'Galarian ', 'ALOLA': 'Alolan ', 'HISUIAN': 'Hisuian ', 'PALDEA': 'Paldean '}.get(reg, '') + _nice(name)


def _targets(members=None, pile=None):
    """uid -> {tags, fixed targets, split targets} from THE advice table (system/analysis/evolve_advice.json, written by
    build_tagsets from granular_tags.evolve_advice -- promises, PvP comb-ups, shiny upgrades and showcase picks in one
    place, 2026-09-29). `members` / `pile` are accepted for old callers and ignored: the table is the source."""
    import granular_tags
    try:
        adv = json.load(open(granular_tags.EVOLVE_ADVICE, encoding='utf-8'))
    except (OSError, ValueError):
        adv = {}
    out = {}
    for u, e in adv.items():
        tg = list(e.get('targets') or [])
        out[norm_uid(u)] = {'tags': set(e.get('tags') or []), 'fixed': tg if len(tg) == 1 else [],
                            'split': tuple(tg) if len(tg) > 1 else None}
    return out

def advice(members=None, pile=None):
    """One entry per tagged mon whose evolution can go more than one way:
    {uid, species, iv, gender, tags, target, kind ('choice' | 'random' | 'ivs' | 'either'), how}."""
    import sqlite3
    import evolvable_forms as ef
    from pvp_iv_rule import pvid
    ef._load()
    tform = ef._tform
    c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); c.row_factory = sqlite3.Row
    rows = {norm_uid(r['uid_hex']): r for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    c.close()
    out, groups = [], {}
    for u, e in _targets(members, pile).items():
        r = rows.get(u)
        if r is None:
            continue
        sid = pvid(r['species_name'], r['form'] or 0)
        key = next((k for k in (ef.form_name(r['fresh_form'] or r['form']), ef._norm(ef._gm_id(sid) or ''),
                                ef._norm(sid)) if k and k in tform), None)
        if key is None:
            continue
        # A form NAME shared by two species (NIDORAN_NORMAL is both Nidorans) merges their branches under one key:
        # when the key offers a target the species' own game-master branches do not, use the species key instead
        # (a female Nidoran was told "Nidorina, not Nidorino", 2026-09-24).
        _own = {ef._norm(k) for k in (ef._costs.get(ef._gm_id(sid) or '') or {})}
        tf = tform
        if _own and any(ef._norm(n) not in _own for n in (tform.get(key) or {})):
            tf = dict(tform)
            tf[key] = {n: v for n, v in tform[key].items() if ef._norm(n) in _own}
        cands = e['fixed'] or list(e['split'] or [])
        branched, kinds = False, set()
        for t in cands:
            for opts, via in (path(tf, key, t, r['gender']) or []):
                if len({f for _n, f in opts}) > 1:
                    branched = True
                    if len(via) > 1:
                        kinds.add('random')              # one target, several forms: the game picks (Dunsparce)
        # WHERE TO STOP (2026-09-26): an Evolve Next whose target can itself evolve again was read as "evolve it all the
        # way" twice -- an 87% Tympole promised to Palpitoad went to Seismitoad on 09-25 and again on 09-26 and fell
        # into the pile as an extra. Say the stop out loud whenever the promised stage is not the end of the line.
        stop = []
        if len(e['fixed']) == 1:
            _p = path(tf, key, e['fixed'][0], r['gender']) or []
            if _p and _p[-1][1]:
                stop = sorted({_nice(n) for n in (tf.get(_p[-1][1][0][1]) or {})
                               if ef._norm(n) != ef._norm(e['fixed'][0])})   # a Mega / form change is not a stage (2026-09-26)
        if not branched and not stop:
            continue
        base = {'uid': u, 'species': r['species_name'], 'iv': round((r['iv_total'] or 0) * 100 / 45),
                'ivs': '/'.join('?' if r[k] is None else str(r[k]) for k in ('iv_atk', 'iv_def', 'iv_sta')), 'cp': r['cp'],
                'gender': r['gender'], 'tags': sorted(e['tags']), 'src': sid, 'key': key,
                'own': sorted(_own) if tf is not tform else None, 'stop': stop}
        if e['fixed']:
            for t in e['fixed']:
                out.append(dict(base, target=t, kind=('random' if 'random' in kinds else 'choice') if branched else 'stop'))
        else:
            groups.setdefault((key, e['split']), []).append(base)
    # A SPLIT promise (Charcadet, Galarian Slowpoke, Wurmple, Tyrogue): every branch has room. Give each copy the
    # branch nobody else of that kind is headed for yet, so two Charcadets become one of each.
    for (key, split), lst in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        taken = [a['target'] for a in out if a['key'] == key]
        for b in sorted(lst, key=lambda x: (-x['iv'], x['uid'])):   # a tie never flips the advice between culls
            free = [t for t in split if t not in taken] or list(split)
            kind = 'ivs' if b['src'] == 'tyrogue' else 'random' if b['src'] in ('wurmple', 'toxel') else 'either'
            out.append(dict(b, target=free[0] if kind == 'either' else '/'.join(split), kind=kind))
            taken.append(free[0])
    for a in out:
        t = a['target'].split('/')[0]
        g = ef.gate_text(t, None if any(x in a['key'] for x in REGIONS) else a['src'])
        if a['src'] == 'eevee' and t in EEVEE_NAMES:
            g = (g + ', or ' if g else '') + 'name it %s first (works once per account)' % EEVEE_NAMES[t]
        a['how'] = g
    return sorted(out, key=lambda a: (a['species'], -a['iv']))


def lines(adv=None):
    """The report lines: 'Gloom 91% (Evolve Next) -> Vileplume, not Bellossom'."""
    import evolvable_forms as ef
    ef._load()
    out = []
    for a in (advice() if adv is None else adv):
        # the alternatives at the step that actually BRANCHES (Oddish -> Gloom -> Vileplume/Bellossom: "not Bellossom",
        # never "not Gloom"), and the stage it passes through on the way
        tf = ef._tform
        if a.get('own'):
            tf = dict(ef._tform)
            tf[a['key']] = {n: v for n, v in ef._tform[a['key']].items() if ef._norm(n) in set(a['own'])}
        steps = path(tf, a['key'], a['target'].split('/')[0], a['gender']) or []
        br = next(((o_, v_) for o_, v_ in steps if len({f for _n, f in o_}) > 1), None)
        others = sorted({_disp(n, f) for n, f in (br[0] if br else [])} - {_disp(n, f) for n, f in (br[1] if br else [])})
        via = [_disp(*v_[0]) for _o, v_ in steps[:-1]] if len(steps) > 1 else []
        if a['kind'] == 'ivs':
            what = 'the game picks by its IVs (every branch has room)'
        elif a['kind'] == 'random':
            what = 'the game picks at random (every outcome has room)'
        else:
            what = _nice(a['target']) + (' (via %s)' % ', '.join(via) if via else '') +                 (', not ' + ' / '.join(others) if others and len(others) <= 2 else '')
            if a['src'] == 'eevee':
                what = _nice(a['target']) + " -- don't press the plain Evolve button (random Vaporeon/Jolteon/Flareon)"
            if a.get('stop'):
                what += ', then STOP -- do not evolve it on to %s' % ' / '.join(a['stop'])
        g = {1: ' ♂', 2: ' ♀'}.get(a['gender'], '') if a['src'] in ('charcadet', 'kirlia', 'snorunt') else ''
        # WHICH COPY (2026-09-30): two 76% Smolivs printed the same line, so the second read as "standing, unchanged" --
        # the IVs and CP name the copy he can find in the game (and a Dolliv still wearing the tag reads as done)
        who = '%s %d%%%s' % (a['species'], a['iv'], g) + (' %s CP %s' % (a['ivs'], a.get('cp') or '?') if a.get('ivs') else '')
        out.append('%s (%s) -> %s%s' % (who, ', '.join(a['tags']), what, ('  [needs: %s]' % a['how']) if a['how'] else ''))
    return out


def _selfcheck():
    tf = {'GLOOMNORMAL': {'vileplume': [['VILEPLUMENORMAL', '']], 'bellossom': [['BELLOSSOMNORMAL', '']]},
          'ODDISHNORMAL': {'gloom': [['GLOOMNORMAL', '']]},
          'KIRLIANORMAL': {'gallade': [['GALLADENORMAL', 'MALE']], 'gardevoir': [['GARDEVOIRNORMAL', '']]},
          'DUNSPARCENORMAL': {'dudunsparce': [['DUDUNSPARCETWO', ''], ['DUDUNSPARCETHREE', '']]}}
    p = path(tf, 'ODDISHNORMAL', 'vileplume', 1)                       # two steps, the SECOND one branches
    assert [len(o) for o, _v in p] == [1, 2] and p[1][1] == [('vileplume', 'VILEPLUMENORMAL')], p
    assert len(path(tf, 'KIRLIANORMAL', 'gardevoir', 2)[0][0]) == 1     # a female Kirlia has no Gallade button
    assert len(path(tf, 'KIRLIANORMAL', 'gallade', 1)[0][0]) == 2
    assert len(path(tf, 'DUNSPARCENORMAL', 'dudunsparce', 1)[0][1]) == 2  # one target, two forms: random
    assert path(tf, 'GLOOMNORMAL', 'raichu', 1) is None
    assert _nice('slowking_galarian') == 'Galarian Slowking' and _nice('vileplume') == 'Vileplume'
    assert _disp('slowbro', 'SLOWBROGALARIAN') == 'Galarian Slowbro' and _disp('bellossom', 'BELLOSSOMNORMAL') == 'Bellossom'
    print('selfcheck ok')


if __name__ == '__main__':
    if '--selfcheck' in sys.argv:
        _selfcheck()
    else:
        for l in lines():
            print(l)
