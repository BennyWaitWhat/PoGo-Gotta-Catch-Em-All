"""WINNING SHOWCASES (user 2026-09-19: "i just want to win showcases").

The game scores a showcase entry with a formula the server sends per contest -- ContestScoreComponentType
Height=1 / Weight=2 / Iv=3, each with its own CoefficientValue -- and the game master's default coefficients are
height 800, weight 150, iv 50. A focus can be a species, a family, a type, shiny-only, mega, a region or a class
(the client carries PokemonFocusFilter, PokemonFamilyFilter, TypeFocusFilter, ShinyFocusFilter, MegaFocusFilter,
RegionFocusFilter, PokemonClassFilter, PokemonAlignmentFilter, HatchedFocusFilter).

Height and weight are compared against the species' own baseline (pokedexHeightM / pokedexWeightKg), which is what
makes a score comparable between species in a type-wide or family-wide focus.

  best_entries()   your top entry per species+form, with its score
  evolve_to_win()  a pre-evo whose PROJECTED evolved score would beat your best entry at the later stage -- what you
                   would gain there, and what that stage of the line loses by consuming it

Advice only. Read-only: the bag DB, the client game master, form_enum.json.
"""
import collections, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import size_line
from pvp_iv_rule import pvid

W = {'height': 0.80, 'weight': 0.15, 'iv': 0.05}          # the game master's 800 / 150 / 50, normalised


def _rows():
    c = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'pokemon.db').replace('\\', '/'), uri=True)
    c.row_factory = sqlite3.Row
    try:
        return [__import__('keep_config').row_dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1 AND height_m IS NOT NULL AND COALESCE(is_component,0)=0')]
    finally:
        c.close()


def score(r):
    """The showcase POINTS of a real specimen -- the game's / Pokemod's number (size_line.showcase_points, 2026-09-23).
    None when the template is unknown."""
    return size_line.showcase_points(r)


def projected_score(r, target_sid):
    """The score the evolved copy would have at `target_sid`, if the size scale carries over."""
    p = size_line.project(r, target_sid)
    rec = size_line._rec_for_sid(target_sid)
    if not p or not rec or not rec[0] or not rec[1] or p[1] is None:
        return None
    pts = size_line.showcase_points_at(target_sid, p[0], p[1], r['iv_total'] or 0, size_line.stays_xxl(r, target_sid))
    return (None if pts is None else pts), p[2]


def best_entries(rows=None):
    """{stage speciesId: [rows, best first]} -- who you would enter for a focus on that stage."""
    rows = rows if rows is not None else _rows()
    by = collections.defaultdict(list)
    for r in rows:
        s = score(r)
        if s is not None:
            by[pvid(r['species_name'], r['form'] or 0)].append((s, r))
    return {k: [r for _, r in sorted(v, key=lambda x: -x[0])] for k, v in by.items()}


def evolve_to_win(rows=None):
    """Evolutions that would give you a BETTER showcase entry at the later stage than anything you own there."""
    rows = rows if rows is not None else _rows()
    gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    nxt = {p['speciesId']: (p.get('family') or {}).get('evolutions') or [] for p in gm['pokemon']}
    best = {k: v[0] for k, v in best_entries(rows).items()}
    bestscore = {k: score(v) for k, v in best.items()}
    out = []
    import evolvable_forms as _ef
    for r in rows:
        src = pvid(r['species_name'], r['form'] or 0)
        if _ef.row_can_evolve(r) is False:
            continue                      # a *Noevolve costume or a form with no branch at all
        for t in nxt.get(src, []):
            # THE GAME DECIDES WHAT THIS ONE CAN BECOME (2026-09-20). `nxt` is pvpoke's family.evolutions, which
            # carries branches PoGo does not have -- it offered "Scyther 2.40m -> kleavor" on this very page while
            # the client game master gives Scyther only SCIZOR. None means the game cannot say, and then we keep
            # the old behaviour rather than silently dropping an evolution.
            if _ef.can_reach(r['fresh_form'] or r['form'], t, src, r['gender']) is False:
                continue
            ps = projected_score(r, t)
            if not ps:
                continue
            s_new, z_new = ps
            cur = bestscore.get(t)
            if cur is not None and s_new <= cur:
                continue
            mine = score(r)
            src_best = bestscore.get(src)
            out.append({'uid': r['uid_hex'], 'species': r['species_name'], 'target': t,
                        'score_now': mine, 'score_after': s_new, 'z_after': z_new,
                        'beats': cur, 'is_my_best_there': src_best is not None and mine >= src_best - 1e-9,
                        'height_m': r['height_m'], 'iv': r['iv_total'], 'size': r['pokemon_size_category']})
    return sorted(out, key=lambda x: -((x['score_after'] or 0) - (x['beats'] or 0)))


if __name__ == '__main__':
    rows = _rows()
    be = best_entries(rows)
    print('species+form you can enter: %d' % len(be))
    ev = evolve_to_win(rows)
    print('evolutions that would beat your best entry at the later stage: %d' % len(ev))
    print('  (of those, %d would cost you the best entry at their OWN stage)' % sum(1 for e in ev if e['is_my_best_there']))
    print('\ntop 12 by how much they would beat what you have:')
    for e in ev[:12]:
        print('   %-12s %.3f m %3d%% %s-> %-14s score %.3f vs your %s  (z %.1f there)%s'
              % (e['species'], e['height_m'], (e['iv'] or 0) * 100 // 45,
                 'XXL ' if e['size'] == 5 else '    ', e['target'], e['score_after'],
                 ('%.3f' % e['beats']) if e['beats'] is not None else 'nothing',
                 e['z_after'], '  [your best there today]' if e['is_my_best_there'] else ''))
