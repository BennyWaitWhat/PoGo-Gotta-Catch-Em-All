"""WHICH WAY TO EVOLVE (user 2026-09-24: "theres some that you dont tell me which to evolve it to").

Every mon in an evolve tag whose evolution the game lets go more than one way (Gloom -> Vileplume OR Bellossom,
Eevee -> 8 ways, Charcadet -> Armarouge OR Ceruledge), with the branch the cull meant. The branches, their gender
locks and their forms are the client game master's (evolvable_forms._tform); the targets are the ones each tag was
built from -- promises.json (Evolve Next / Twice / Gated), pvp_combup_labels.json (Evolve for GL / UL / Gated),
refresh_evolve_shiny (Evolve Shiny / Shiny Gated), sync_evolve_size (Evolve for Size). A tag whose line only goes
one way is left out: there is nothing to choose.

THE GAME PICKS (2026-11-10). Two or more branches of one step that need candy alone (Wurmple -> Silcoon / Cascoon, Clamperl ->
Huntail / Gorebyss, Tyrogue's three) are not a choice: the client game master lists them with no condition and the game picks.
A FIXED target behind such a step (a PvP comb-up, a showcase pick) was printed as one -- "Wurmple 62% -> Beautifly (via
Silcoon), not Cascoon" (13:22, 2026-11-10; it came out a Silcoon by luck). The line now says who picks and what to do with
each outcome; a Tyrogue's outcome is read from its IVs (highest of attack / defence / HP -> Hitmonlee / Hitmonchan / Hitmontop,
a tie is a coin flip). And a target two steps away behind 'Evolve Needs Item / Task' gets a line too: that tag does not say
where it ends (LAW "WHERE IT ENDS"; a showcase pick names its last stage since 2026-11-10).

  python evolve_targets.py            # the lines full_audit prints after every cull
  python evolve_targets.py --selfcheck
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))

EVOLVE_TAGS = ('Evolve to Mid', 'Evolve to Final', 'Evolve Needs Item', 'Evolve Needs Task', 'Evolve for GL', 'Evolve for UL')   # 2026-10-25
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


def tyrogue_outcomes(atk, dfn, sta):
    """The stage(s) the game can make of a Tyrogue with these IVs: its highest IV decides, a tie is a coin flip."""
    v = {'hitmonlee': atk or 0, 'hitmonchan': dfn or 0, 'hitmontop': sta or 0}
    return sorted(n for n, x in v.items() if x == max(v.values()))


def _free_fn(ef):
    """free((target name, target form)): that branch is a plain candy tap -- nothing the player does picks it."""
    gn = {ef._norm(k): v for k, v in (ef._gated or {}).items() if v}

    def free(o):
        f = o[1][:-6] if o[1].endswith('NORMAL') else o[1]
        return not (gn.get(f) or (not any(x in f for x in REGIONS) and gn.get(ef._norm(o[0]))))
    return free


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
                            'split': tuple(tg) if len(tg) > 1 else None, 'source': e.get('source')}
    return out

def advice(members=None, pile=None):
    """One entry per tagged mon whose evolution can go more than one way:
    {uid, species, iv, gender, tags, target, kind ('choice' | 'random' | 'ivs' | 'either' | 'luck' | 'through' | 'stop'), how}.
    'luck': a FIXED target behind a step the game picks; 'through': a target two steps away behind a Needs tag."""
    import sqlite3
    import evolvable_forms as ef
    from pvp_iv_rule import pvid
    ef._load()
    tform = ef._tform
    c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); c.row_factory = sqlite3.Row
    rows = {norm_uid(r['uid_hex']): r for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    c.close()
    out, groups, free = [], {}, _free_fn(ef)
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
        branched, kinds, luck = False, set(), None
        for t in cands:
            for opts, via in (path(tf, key, t, r['gender']) or []):
                if len({f for _n, f in opts}) > 1:
                    branched = True
                    if len(via) > 1:
                        kinds.add('random')              # one target, several forms: the game picks (Dunsparce)
                    elif e['fixed'] and sid != 'eevee' and free(via[0]) and any(o != via[0] and free(o) for o in opts):
                        # the wanted branch and another one are both plain candy taps: the game picks (module doc). Eevee
                        # keeps its own line -- the name trick does choose, once per name.
                        luck = [_disp(*via[0])] + sorted(_disp(*o) for o in opts if o != via[0] and free(o))
        # WHERE TO STOP (2026-09-26): an Evolve Next whose target can itself evolve again was read as "evolve it all the
        # way" twice -- an 87% Tympole promised to Palpitoad went to Seismitoad on 09-25 and again on 09-26 and fell
        # into the pile as an extra. Say the stop out loud whenever the promised stage is not the end of the line.
        stop = []
        if len(e['fixed']) == 1:
            _p = path(tf, key, e['fixed'][0], r['gender']) or []
            if _p and _p[-1][1]:
                stop = sorted({_nice(n) for n in (tf.get(_p[-1][1][0][1]) or {})
                               if ef._norm(n) != ef._norm(e['fixed'][0])})   # a Mega / form change is not a stage (2026-09-26)
        # ... and where a NEEDS tag ends: 'Evolve Needs Item / Task' names the gate, not the last stage
        _far = (len(e['fixed']) == 1 and not branched and not stop and len(path(tf, key, e['fixed'][0], r['gender']) or []) > 1
                and bool(set(e['tags']) & {'Evolve Needs Item', 'Evolve Needs Task'}))
        if not branched and not stop and not _far:
            continue
        base = {'uid': u, 'species': r['species_name'], 'iv': round((r['iv_total'] or 0) * 100 / 45),
                'ivs': '/'.join('?' if r[k] is None else str(r[k]) for k in ('iv_atk', 'iv_def', 'iv_sta')), 'cp': r['cp'],
                'gender': r['gender'], 'tags': sorted(e['tags']), 'src': sid, 'key': key,
                'own': sorted(_own) if tf is not tform else None, 'stop': stop, 'luck': luck, 'source': e.get('source'),
                'ivpick': tyrogue_outcomes(r['iv_atk'], r['iv_def'], r['iv_sta']) if sid == 'tyrogue' else None}
        if e['fixed']:
            for t in e['fixed']:
                out.append(dict(base, target=t, kind=('random' if 'random' in kinds else 'luck' if luck else 'choice')
                                if branched else 'through' if _far else 'stop'))
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
        _tf = tform if not a.get('own') else dict(tform, **{a['key']: {n: v for n, v in tform[a['key']].items()
                                                                       if ef._norm(n) in set(a['own'])}})
        _st = path(_tf, a['key'], t, a['gender']) or [] if a['kind'] in ('choice', 'stop', 'through', 'luck') else []
        if len(_st) > 1:
            # TWO STEPS: every gate on the way, each at the stage that needs it. gate_text(target, the mon's own stage) found
            # no item for a stage two steps up -- an Oddish for Bellossom printed no Sun Stone (2026-11-10).
            _reg, _prev, _gs = any(x in a['key'] for x in REGIONS), a['src'], []
            for _o, _v in _st:
                _w = ef.gate_text(_v[0][0], None if _reg else _prev)
                if _w:
                    _gs.append('%s: %s' % (_disp(*_v[0]), _w))
                _prev = _v[0][0]
            g = '; '.join(_gs)
        if a['src'] == 'eevee' and t in EEVEE_NAMES:
            g = (g + ', or ' if g else '') + 'name it %s first (works once per account)' % EEVEE_NAMES[t]
        a['how'] = g
    return sorted(out, key=lambda a: (a['species'], -a['iv']))


def lines(adv=None):
    """The report lines: 'Gloom 91% (Evolve Next) -> Vileplume, not Bellossom'."""
    import evolvable_forms as ef
    ef._load()
    out = []
    try:                                                 # the lifetime shiny Pokedex (2026-11-11, "D2"): display only
        import json as _j
        import os as _o
        _h = _o.path.dirname(_o.path.abspath(__file__))
        _dx = {p['speciesId']: p.get('dex') for p in _j.load(open(_o.path.join(_h, 'pvpoke_gamemaster.json'), encoding='utf-8'))['pokemon']}
        _sh = {e['pid'] for e in _j.load(open(_o.path.join(_h, 'pokedex_hundos_live.json'), encoding='utf-8'))['entries'] if e.get('shiny')}
    except Exception:
        _dx, _sh = {}, set()
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
        # A SHINY HE NEVER REGISTERED (2026-11-11, "D2"): say so, and never print "not <the other branch>" when that branch
        # is a missing entry too (one shiny Charcadet: Armarouge or Ceruledge, his pick)
        _new = bool(a.get('source') == 'shiny' and _sh and all(_dx.get(t) is not None and _dx.get(t) not in _sh
                                                               for t in str(a['target']).split('/')))
        _alts = [o_ for o_ in (br[0] if br else []) if o_ not in (br[1] if br else [])]
        _altnew = bool(_new and a['kind'] in ('choice', 'either') and a['src'] != 'eevee' and 0 < len(_alts) <= 2
                       and all(_dx.get(n) is not None and _dx.get(n) not in _sh for n, _f in _alts))
        how = a['how']
        if a['kind'] == 'ivs':
            what = 'the game picks by its IVs (every branch has room)'
        elif a['kind'] == 'random':
            what = 'the game picks at random (every outcome has room)'
        elif a['kind'] == 'luck':
            tgt, want, alts = _nice(a['target']), a['luck'][0], ' / '.join(a['luck'][1:])
            on = '' if want == tgt else ' -> evolve it on to ' + tgt
            pick = a.get('ivpick')
            if pick and [a['target']] == pick:
                what = '%s -- its IVs decide, and they make it a %s' % (tgt, tgt)
            elif pick and a['target'] not in pick:
                what = 'CANNOT become %s: its IVs make it a %s -- do not evolve it for this' % (tgt, ' / '.join(_nice(x) for x in pick))
            else:
                what = ('the game picks %s or %s, you cannot choose: a %s%s; a %s -> STOP, it is not the upgrade'
                        % (want, alts, want, on or ' is the upgrade', alts))
        elif a['kind'] == 'through':
            what = _nice(a['target']) + (' (via %s)' % ', '.join(via) if via else '') + ' -- all the way'
        else:
            what = _nice(a['target']) + (' (via %s)' % ', '.join(via) if via else '') +                 (', not ' + ' / '.join(others) if others and len(others) <= 2 else '')
            if a['src'] == 'eevee':
                what = _nice(a['target']) + " -- don't press the plain Evolve button (random Vaporeon/Jolteon/Flareon)"
            if _altnew:
                what = '%s or %s -- one copy, your pick: neither shiny was ever registered' % (
                    _nice(a['target']), ' / '.join(_disp(*o_) for o_ in _alts))
                _src = None if any(x in a['key'] for x in REGIONS) else a['src']
                how = '; '.join('%s: %s' % (n_, w_) for n_, w_ in [(_nice(a['target']), a['how'])] + [
                    (_disp(*o_), ef.gate_text(o_[0], _src)) for o_ in _alts] if w_)
            if a.get('stop'):
                what += _stop_text(a.get('source'), a['stop'])
        g = {1: ' ♂', 2: ' ♀'}.get(a['gender'], '') if a['src'] in ('charcadet', 'kirlia', 'snorunt') else ''
        # WHICH COPY (2026-09-30): two 76% Smolivs printed the same line, so the second read as "standing, unchanged" --
        # the IVs and CP name the copy he can find in the game (and a Dolliv still wearing the tag reads as done)
        who = '%s %d%%%s' % (a['species'], a['iv'], g) + (' %s CP %s' % (a['ivs'], a.get('cp') or '?') if a.get('ivs') else '')
        out.append('%s (%s) -> %s%s%s' % (who, ', '.join(a['tags']), what, ('  [needs: %s]' % how) if how else '',
                                          '  [a shiny you have never registered]' if _new and not _altnew else ''))
    return out


def dex_lines():
    """NEW SHINY POKEDEX ENTRIES (user 2026-11-11, pick "D2": "yesterday i found a shiny i could evolve that i never had on my
    dex. i expect you to do better."). Every shiny the rule sends -- or holds -- toward a shiny that was NEVER registered, the
    one-way lines too (lines() only prints an evolution with a choice). Straight from the rule (compute_target); display only.
    One line per new entry: the copy to evolve, what it costs or needs, how many other copies could do it instead."""
    import sqlite3
    import keep_config
    if not keep_config.rule_enabled('shiny_dex_evolve'):
        return []
    import evolvable_forms as ef
    import refresh_evolve_shiny as res
    from pvp_iv_rule import pvid
    gmj = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))['pokemon']
    dx = {p['speciesId']: p.get('dex') for p in gmj}
    nm = {}
    for p in gmj:
        nm.setdefault(p.get('dex'), str(p.get('speciesName') or p['speciesId']).split(' (')[0])
    evo = {p['speciesId']: (p.get('family') or {}).get('evolutions') or [] for p in gmj}
    sh = {e['pid'] for e in json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json'), encoding='utf-8'))['entries']
          if e.get('shiny')}
    new = lambda t: dx.get(t) is not None and dx[t] not in sh
    g, h, d = {}, {}, {}
    res.compute_target(gated=g, held=h, detail=d)
    c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); c.row_factory = sqlite3.Row
    rows = {r['uid_hex']: r for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    c.close()
    candy = ef.candy_now(walk=max((str(r['last_scanned']) for r in rows.values() if r['last_scanned']), default=None))
    by = {}                                          # the new entry's dex number -> [(order, iv, line)]
    for u in sorted(set(d) | set(g) | set(h)):
        r = rows.get(u)
        tg = d.get(u) or ([g[u]['target']] if u in g else h.get(u)) or []
        if r is None or not tg or not all(new(t) for t in tg):
            continue
        src = pvid(r['species_name'], r['form'] or 0)
        who = '%s %d%% %s CP %s' % (r['species_name'], round((r['iv_total'] or 0) * 100 / 45),
                                    '/'.join('?' if r[k] is None else str(r[k]) for k in ('iv_atk', 'iv_def', 'iv_sta')), r['cp'] or '?')
        cost = max((ef.step_cost(src, t) or 0) for t in tg)
        fam = ef.family(src)
        if u in d:
            order, what = 0, 'ready now%s' % (' (%d candy)' % cost if cost else '')
        elif u in g:
            order, what = 1, 'needs %s' % (g[u].get('need') or 'more than candy')
        else:
            have = None if candy is None or fam is None else candy.get(fam, 0)
            order, what = 2, ('short on candy -- %d needed, you hold %s' % (cost, have) if have is not None
                              else 'its candy was not read this walk (%d needed)' % cost)
        alts = sorted({nm.get(dx[t]) for t in (h.get(u) or []) if new(t) and dx[t] != dx[tg[0]]} - {None})
        on = sorted({nm.get(dx[x]) for t in tg for x in evo.get(t, []) if new(x) and dx[x] != dx[t]} - {None})
        by.setdefault(dx[tg[0]], []).append((order, -(r['iv_total'] or 0), '%s <- %s: %s%s%s' % (
            nm.get(dx[tg[0]]) or tg[0], who, what,
            (' (or %s, also new: one copy, your pick)' % ' / '.join(alts)) if alts else '',
            ('; then on to %s, also new' % ' / '.join(on)) if on else '')))
    out = []
    for _dexno, lst in by.items():
        lst.sort()
        out.append((lst[0][0], lst[0][2] + (' (+%d more cop%s could instead)' % (len(lst) - 1, 'y' if len(lst) == 2 else 'ies')
                                            if len(lst) > 1 else '')))
    return [l for _o, l in sorted(out)]


def _stop_text(source, stops):
    """What to say when the target evolves again. A shiny upgrade climbs one stage per cull (refresh_evolve_shiny names
    the last stage itself when it can), so the next cull may send it on: never call that a STOP (2026-11-10)."""
    return (', then leave it there -- the next cull says if it goes on to %s' if source == 'shiny'
            else ', then STOP -- do not evolve it on to %s') % ' / '.join(stops)


def _selfcheck():
    assert _stop_text('promise', ['Golem']) == ', then STOP -- do not evolve it on to Golem'
    assert 'STOP' not in _stop_text('shiny', ['Golem']) and _stop_text('shiny', ['Golem']).startswith(', then leave it')
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
    # the game picks (2026-11-10): two plain candy branches are not a choice; an item branch beside a candy one is

    class _Ef:
        _gated = {'bellossom': ['evolutionItemRequirement'], 'slowbro_galarian': ['questDisplay'], 'huntail': []}
        _norm = staticmethod(lambda x: ''.join(c for c in str(x).upper() if c.isalnum()))
    fr = _free_fn(_Ef)
    assert fr(('silcoon', 'SILCOONNORMAL')) and fr(('cascoon', 'CASCOONNORMAL')) and fr(('huntail', 'HUNTAILNORMAL'))
    assert fr(('vileplume', 'VILEPLUMENORMAL')) and not fr(('bellossom', 'BELLOSSOMNORMAL'))
    assert fr(('slowbro', 'SLOWBRONORMAL')) and not fr(('slowbro', 'SLOWBROGALARIAN'))   # a regional gate is the regional form's
    assert tyrogue_outcomes(15, 14, 14) == ['hitmonlee'] and tyrogue_outcomes(13, 15, 14) == ['hitmonchan']
    assert tyrogue_outcomes(3, 9, 15) == ['hitmontop'] and tyrogue_outcomes(15, 2, 15) == ['hitmonlee', 'hitmontop']
    print('selfcheck ok')


if __name__ == '__main__':
    if '--selfcheck' in sys.argv:
        _selfcheck()
    else:
        for l in lines():
            print(l)
        for l in dex_lines():
            print('new shiny dex entry: ' + l)
