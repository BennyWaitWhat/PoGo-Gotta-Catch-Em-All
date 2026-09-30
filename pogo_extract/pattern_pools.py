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
