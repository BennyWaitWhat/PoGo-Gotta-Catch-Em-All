"""pattern_pools.py -- evolution lines whose FORM is a collectible that SURVIVES evolution.

A Jungle Scatterbug becomes a Jungle Spewpa becomes a Jungle Vivillon: the pattern is the collectible, the
three stages are steps. For these lines the user's rule (2026-09-08: "Fix Scatterbug so there's the top 3 of
each region type only for its whole evo line") is ONE plain cap of keep_config caps.plain_line per PATTERN
across the WHOLE line -- Scatterbug + Spewpa + Vivillon of that pattern compete for the same 3 slots --
instead of the general per-(species, form) cap (2 for a still-evolvable stage, 3 for a final).

WHY A SEPARATE RULE. The general engine keys the plain cap on (species, form) and the evolve comb-up on the
PvPoke speciesId. PvPoke has ONE id for all 20 Vivillon patterns, so before this the comb-up asked "is a
Vivillon slot free?" across every pattern at once: a Jungle Scatterbug was judged against Continental Vivillon
copies (the Rapidash bug of 2026-07-26, one level deeper), and two Scatterbugs sat in the pile although the
user owned zero Vivillon of their pattern.

Roster: keep_config.pattern_line_pools -> [{"name": "vivillon", "pids": [664, 665, 666]}]. Only listed lines
are pooled; every other line keeps the per-stage cap. The pattern is read from the LIVE Form enum name
(form_enum.json via costume_forms.form_name): 'ScatterbugJungle' -> 'Jungle', 'VivillonJungle' -> 'Jungle'.
A form whose enum name does not start with its species name, or an unknown / 0 form, is NOT pooled -- that
row falls back to the per-(species, form) rule. That is the SAFE direction: fewer merges can only keep MORE.

pool_key(pid, species_name, form) -> (('pool', line_name), pattern, 0)  or None
    A 3-tuple on purpose: keep_policy's stage keys are (pid, cf, gender) and its consumers index key[0] /
    key[1] / key[2] and test key[0] == 201 (Unown). A tuple in key[0] can never collide with a dex number.

Consumers (keep in step, per the capped-vs-keep-all lesson): keep_policy rule 1b, granular_tags (Variant
ordinals), _lawcheck.py, _evocheck.py. Everything reads the roster through keep_config -- never hardcode pids.
"""
import re
import keep_config
import costume_forms

_NORM = re.compile(r"[^a-z0-9]")


def _norm(s):
    s = (s or '').lower().replace('é', 'e').replace('è', 'e')
    return _NORM.sub('', s)


def roster():
    """{pid: line_name} from keep_config.pattern_line_pools (validated there; bad entries dropped)."""
    out = {}
    for ent in keep_config.pattern_line_pools():
        for pid in ent.get('pids', []):
            out[int(pid)] = str(ent['name'])
    return out


def pooled_pids():
    return sorted(roster())


def is_pooled(pid):
    return keep_config.line_pool_all() or int(pid or 0) in roster()


def pattern(species_name, form):
    """The pattern suffix of a form-enum name ('ScatterbugJungle' -> 'Jungle'), or None if the enum has no
    name for the form or the name does not start with the species (never guess a pattern)."""
    nm = costume_forms.form_name(form or 0)
    if not nm:
        return None
    sp = _norm(species_name)
    if not sp or not _norm(nm).startswith(sp):
        return None
    # cut the species prefix off the ORIGINAL name (case preserved) by matching normalised lengths
    cut = 0
    acc = ''
    for ch in nm:
        acc += ch
        cut += 1
        if _norm(acc) == sp:
            break
    suffix = nm[cut:]
    return suffix or None


_FAM = None


def _families():
    """(evolutions, parents) over pvpoke speciesIds -- the same families the engine's graph starts from."""
    global _FAM
    if _FAM is None:
        import json, os
        gm = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pvpoke_gamemaster.json'), encoding='utf-8'))
        evos = {p['speciesId']: list((p.get('family') or {}).get('evolutions') or []) for p in gm['pokemon']}
        parents = {}
        for s, es in evos.items():
            for e in es:
                parents.setdefault(e, []).append(s)
        _FAM = (evos, parents)
    return _FAM


def line_root(sid):
    """The first stage of sid's LINE: walk back while there is one parent that evolves ONLY into this stage. A branch
    child (Vaporeon, Vileplume, Alolan Raichu) starts its own line; the stages before the split share one. Regional
    speciesIds are their own chains (zigzagoon_galarian -> linoone_galarian -> obstagoon)."""
    evos, parents = _families()
    if sid not in evos:
        return None
    cur, seen = sid, set()
    while cur not in seen:
        seen.add(cur)
        ps = parents.get(cur) or []
        if len(ps) != 1 or len(evos.get(ps[0]) or []) != 1:
            return cur
        cur = ps[0]
    return cur


_LINE_DEX = {}


def line_dex(root):
    """Dex numbers of every stage whose line_root is `root`."""
    if root not in _LINE_DEX:
        import json, os
        gm = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pvpoke_gamemaster.json'), encoding='utf-8'))
        _LINE_DEX[root] = {p.get('dex') for p in gm['pokemon'] if line_root(p['speciesId']) == root and p.get('dex')}
    return _LINE_DEX[root]


def pool_key(pid, species_name, form, gender=None):
    line = roster().get(int(pid or 0))
    if line is None:
        # EVERY LINE (keep_config.line_pool_all, user 2026-09-26 on florandez): one plain pool per (line, look, gender).
        # The look is the form's pattern suffix ('BulbasaurNormal' -> 'Normal'; form 0 = the plain 'Normal'); a form
        # with no readable pattern is NOT pooled (per-stage fallback -- fewer merges only keep MORE).
        if not keep_config.line_pool_all():
            return None
        if form and costume_forms.is_costume_form(form):
            return None     # a FORM-encoded costume (Pikachu Anniversary 2026) is a costume ladder, not a plain line
        from pvp_iv_rule import pvid
        import evolvable_forms
        root = line_root(pvid(species_name, form or 0))
        look = pattern(species_name, form) if form else 'Normal'
        if root is None or look is None:
            return None
        # GENDER SPLITS THE WHOLE LINE when any stage of it looks different by gender (Phanpy is not dimorphic, Donphan
        # is): the key must survive evolution, or an evolved copy lands in another pool (audit_promises, 2026-09-26).
        g = 0
        if gender in (1, 2) and any(evolvable_forms.gender_key(p, gender) for p in line_dex(root)):
            g = gender
        return (('pool', 'line:' + root), look, g)
    pat = pattern(species_name, form)
    if pat is None:
        return None
    return (('pool', line), pat, 0)


def is_pool_key(key):
    return isinstance(key, tuple) and len(key) == 3 and isinstance(key[0], tuple) and key[0][:1] == ('pool',)


def describe():
    """Human-readable roster for logs/docs."""
    r = roster()
    lines = {}
    for pid, nm in r.items():
        lines.setdefault(nm, []).append(pid)
    return '; '.join('%s: dex %s' % (nm, ','.join(str(p) for p in sorted(ps))) for nm, ps in sorted(lines.items())) or '(none)'


_PLAIN_TAIL = ('Normal', 'Female', 'Male')   # the plain form and the gender forms (the gender looks rule), read off the ENUM name
_SHARED = None


def min_group(pid, species_name, form):
    """The group keep_config caps.pattern_min counts: one PATTERN of a pattern-pooled line (Scatterbug + Spewpa + Vivillon of
    that pattern together; user 2026-11-07 "for those two, I want 2 of each at a min"), or one named form of one species that
    the species minimum counts as one kind with other forms, because its pvpoke speciesId does not tell them apart: each
    Unown letter, Spinda pattern, Flabebe color, Deerling season, Furfrou trim, Shellos sea, Minior core ... (user 2026-11-07,
    "....yes."; 2026-11-15 "Should be 3....just like other many formed ones").
    A FORM IS ITS OWN KIND UNLESS THE DATA PROVES OTHERWISE (user 2026-11-15: "you need to future proof yourself even for
    pokemon that i dont have or seen yet"). None only for form 0, a costume form (look_keep holds them), the plain / gender
    forms (_PLAIN_TAIL, read off the game's enum name) and a form the curated table gives a speciesId no other form id
    shares (Burmy cloaks, Lycanroc: the species minimum already keeps 3 of each). Everything else -- a form the enum does not
    name, a species the table has never heard of, a display name that does not match the enum -- counts by its own form id.
    Until 2026-11-15 the kind was read by cutting the species NAME off the enum name: the bag calls dex 774 'Minior (Core)',
    'MiniorYellow' did not start with it, "unreadable" was treated like the plain form, and 5 of 6 Yellow-core Minior went
    to the pile while every audit (which group by this function too) agreed. No display name is parsed here any more.
    ONE definition: keep_policy, preflight_transfer and audit_cull all group by it."""
    global _SHARED
    pid = int(pid or 0)
    line = roster().get(pid)
    if line is not None:
        return ('pattern', line, pattern(species_name, form) or 'form %s' % (form or 0))
    if not form or costume_forms.is_costume_form(form) or (costume_forms.form_name(form) or '').endswith(_PLAIN_TAIL):
        return None
    from pvp_iv_rule import pvid
    from form_overrides_complete import FORM_OVERRIDES
    if _SHARED is None:     # speciesId -> the named, non-costume form ids that map to it, under ANY display name
        _SHARED = {}
        for (_s, f), v in FORM_OVERRIDES.items():
            if f and costume_forms.form_name(f) and not costume_forms.is_costume_form(f):
                _SHARED.setdefault(v, set()).add(f)
    sid = pvid(species_name, form)
    alone = (species_name, form) in FORM_OVERRIDES and sid != pvid(species_name, 0) and len(_SHARED.get(sid, ())) <= 1
    return None if alone else ('form', pid, int(form))


def min_count(g):
    """How many copies the pattern minimum keeps for a min_group: keep_config caps.pattern_min, or the species' own number
    for a lumped form (per_species_caps.pattern_min {pid: n}; user 2026-11-12 of Unown: "i need at least 3 of each letter").
    A pattern-pooled line spans several species and uses the global number, and so does g=None (the number to print).
    0 when the minimum is off. ONE definition: keep_policy, preflight_transfer and audit_cull all count by it."""
    import keep_config
    n = keep_config.cap('pattern_min')
    return keep_config.species_cap('pattern_min', g[1], n) if n and g and g[0] == 'form' else n


def _selftest():
    """The form rules hold for Pokemon he does not have and forms the tool has never seen (user 2026-11-15: "you need to future
    proof yourself even for pokemon that i dont have or seen yet"). Runs over the game's WHOLE form enum, not the bag."""
    import json
    import os
    from form_overrides_complete import FORM_OVERRIDES
    here = os.path.dirname(os.path.abspath(__file__))
    fe = {int(k): v for k, v in json.load(open(os.path.join(here, 'form_enum.json'), encoding='utf-8')).items()}
    assert len(fe) > 1000, 'the form enum is short: %d' % len(fe)
    named = [f for f, nm in fe.items() if f and not costume_forms.is_costume_form(f) and not nm.endswith(_PLAIN_TAIL)]
    assert len(named) > 300, 'too few named forms to test: %d' % len(named)
    # 1. the 2026-11-15 case: every Minior color, under both names the bag has carried for dex 774
    for f in (2707, 2708, 2709, 2710, 2711, 2712, 2713, 2714, 2739, 2740, 2741, 2742, 2743, 2744):
        for nm in ('Minior (Core)', 'Minior'):
            assert min_group(774, nm, f) == ('form', 774, f), (nm, f, min_group(774, nm, f))
    # 2. a species the tool has never heard of, under a name that matches nothing: every named form of the enum is its own kind
    bad = [f for f in named if min_group(99999, 'Never Seen (Any Form)', f) != ('form', 99999, f)]
    assert not bad, 'an unknown species lost %d form(s): %s' % (len(bad), [(f, fe[f]) for f in bad[:8]])
    # 3. a form id the enum does not name yet (a game update the tool has not read) is held as a costume form: missing data =
    #    protected (costume_forms.is_costume_form, 2026-09-02) -- so it never reaches the plain rules at all
    assert costume_forms.is_costume_form(987654) and min_group(25, 'Pikachu', 987654) is None
    # 4. every curated (name, form): its own kind, or a speciesId NO other form id shares (the species minimum counts it alone)
    by = {}
    for (_s, f), v in FORM_OVERRIDES.items():
        if f and fe.get(f) and not costume_forms.is_costume_form(f):
            by.setdefault(v, set()).add(f)
    hole = [(s, f, v) for (s, f), v in FORM_OVERRIDES.items()
            if f in named and min_group(99999, s, f) is None and len(by.get(v, ())) > 1]
    assert not hole, '%d curated form(s) share a speciesId and have no minimum of their own: %s' % (len(hole), hole[:8])
    lone = sum(1 for (s, f), v in FORM_OVERRIDES.items() if f in named and min_group(99999, s, f) is None)
    # 5. the plain form and the gender forms stay with the species minimum / the gender ladder; a costume form with look_keep
    assert min_group(29, 'Nidoran F', 776) is None and min_group(19, 'Rattata', 0) is None and min_group(19, 'Rattata', None) is None
    print('pattern_pools selftest OK: %d named forms in the enum each their own kind for an unknown species; %d curated forms '
          'ride the species minimum alone, none shares its speciesId' % (len(named), lone))


if __name__ == '__main__':
    import sys
    if '--selftest' in sys.argv:
        _selftest()
