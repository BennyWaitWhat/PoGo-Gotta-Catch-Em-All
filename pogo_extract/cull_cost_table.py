"""CULL COST TABLE (read-only): for every keep rule -- how many mons it keeps, how many it is the ONLY reason for,
and how many slots one tightening step would free. Run after a cull; prints a table.  python cull_cost_table.py"""
import collections
import json
import os
import sqlite3
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import evolvable_forms as ef
import granular_tags as gt
import size_line as sl
import keep_config
from costume_forms import is_costume_form

rs = {k: set(v) for k, v in json.load(open('system/analysis/policy_reasons.json', encoding='utf-8')).items() if isinstance(v, list)}
pile = set(open('system/analysis/tagsets/Transfer.txt').read().split())
TD = os.path.join('system', 'analysis', 'tagsets')
T = lambda n: set(open(os.path.join(TD, n + '.txt')).read().split()) if os.path.exists(os.path.join(TD, n + '.txt')) else set()
c = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row
rows = {r['uid_hex']: dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')}
kept = {u: r for u, r in rows.items() if u in rs}
base = gt._base_form_map(list(rows.values()))
cf = lambda r: r['form'] or base.get(r['pokemon_id'], 0)
cnt = collections.Counter(x for v in rs.values() for x in v if x != 'dex_only_copy')
sole = collections.Counter(next(iter(v - {'dex_only_copy'})) for v in rs.values() if len(v - {'dex_only_copy'}) == 1)
onlydex = sum(1 for v in rs.values() if v == {'dex_only_copy'})
S = lambda reason: {u for u, v in rs.items() if v - {'dex_only_copy'} == {reason}}
ivo = lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0), r['uid_hex'])


def ordinal_free(group_rows, keyf, order, cap_new, sole_set):
    g = collections.defaultdict(list)
    for r in group_rows:
        g[keyf(r)].append(r)
    n = 0
    for lst in g.values():
        lst = sorted(lst, key=order)
        n += sum(1 for i, r in enumerate(lst) if i >= cap_new and r['uid_hex'] in sole_set)
    return n


K = list(kept.values())
sw = keep_config.showcase_weights()
deco = lambda r: r['costume_decoration_id'] if (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0') else 0
spec = lambda r: bool((r['fresh_natural_art_bg'] or 0) or (r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0)) or (r['fresh_costume'] or 0)
                      or is_costume_form(r['fresh_form']) or is_costume_form(r['form']) or ef.max_axis(r['fresh_bread_mode']) or r['fresh_alignment'] == 1)
vkey = lambda r: (r['pokemon_id'], cf(r), r['fresh_costume'] or 0, r['fresh_natural_art_bg'] or 0, deco(r), r['fresh_bread_mode'] or 0)
out = []
v3 = T('Variant_#3') & S('variant_floor')
v2 = T('Variant_#2') & S('variant_floor')
out.append(('Plain ladder', '3 (middle 2)', cnt['variant_floor'], sole['variant_floor'], 'cap 2 (middle 1): frees %d [the Variant #3 chips]; cap 1: +%d more' % (len(v3), len(v2))))
shg = [r for r in K if r['fresh_shiny']]
plain_sh = [r for r in shg if not spec(r) and r['iv_total'] != 45]
_sfl = keep_config.shiny_floor_iv()
def _floor_free(floor):
    """plain shinies under `floor` that are sole-kept as shiny and not the best shiny of their form"""
    g = collections.defaultdict(list)
    for r in shg:
        g[(r['pokemon_id'], cf(r))].append(r)
    n = 0
    for lst in g.values():
        lst = sorted(lst, key=ivo)
        pl = [r for r in lst if not spec(r)]
        n += sum(1 for i, r in enumerate(pl) if i > 0 and (r['iv_total'] or 0) < floor and r['uid_hex'] in S('shiny'))
    return n
out.append(('Shiny', '6, at most 4 plain, plain floor %d/45' % _sfl, cnt['shiny'], sole['shiny'],
            'floor %d: frees %d; floor %d: frees %d  (special shinies in bag: %d)' % (_sfl + 3, _floor_free(_sfl + 3), _sfl + 5, _floor_free(_sfl + 5), sum(1 for r in shg if spec(r)))))
cos = [r for r in K if not r['fresh_shiny'] and r['fresh_alignment'] != 1 and r['iv_total'] != 45 and not ef.max_axis(r['fresh_bread_mode'])
       and ((r['fresh_costume'] or 0) or is_costume_form(r['fresh_form']) or is_costume_form(r['form']) or (r['fresh_natural_art_bg'] or 0) or deco(r))]
out.append(('Costume / background variants', '3 (Pikachu 4)', len(cos), len([r for r in cos if r['uid_hex'] in S('variant_floor')]),
            'cap 2: frees %d' % ordinal_free(cos, vkey, ivo, 2, S('variant_floor'))))
dm = [r for r in K if ef.max_axis(r['fresh_bread_mode']) == 'dynamax' and not r['fresh_shiny'] and r['iv_total'] != 45]
gm = [r for r in K if ef.max_axis(r['fresh_bread_mode']) == 'gigantamax' and not r['fresh_shiny'] and r['iv_total'] != 45]
out.append(('Dynamax', '3', len(dm), len([r for r in dm if r['uid_hex'] in S('variant_floor')]), 'cap 2: frees %d' % ordinal_free(dm, vkey, ivo, 2, S('variant_floor'))))
out.append(('Gigantamax', '6', len(gm), len([r for r in gm if r['uid_hex'] in S('variant_floor')]),
            'cap 4: frees %d; cap 3: frees %d' % (ordinal_free(gm, vkey, ivo, 4, S('variant_floor')), ordinal_free(gm, vkey, ivo, 3, S('variant_floor')))))
rar = [r for r in K if 'rarity' in rs[r['uid_hex']] and not r['fresh_shiny'] and r['fresh_alignment'] != 1]
out.append(('Legendary / mythical / UB', '6 per variant', cnt['rarity'], sole['rarity'],
            'cap 5: frees %d; cap 4: frees %d; cap 3: frees %d' % tuple(ordinal_free(rar, lambda r: (r['pokemon_id'], cf(r)), ivo, n, S('rarity')) for n in (5, 4, 3))))
lc = [r for r in K if r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0) and r['iv_total'] != 45
      and not __import__('costume_forms').card_folds_into_costume(r)]   # costume copies ride the costume ladder (2026-09-24)
lkey = lambda r: (r['pokemon_id'], cf(r), r['fresh_loc_card_enum'])
_lcc = keep_config.cap('location_card')
out.append(('Location card', '%d per card' % _lcc, cnt['location_card'], sole['location_card'],
            'cap %d: frees %d; cap %d: frees %d' % (_lcc - 1, ordinal_free(lc, lkey, ivo, _lcc - 1, S('location_card')), _lcc - 2, ordinal_free(lc, lkey, ivo, max(0, _lcc - 2), S('location_card')))))
leg = [r for r in K if 'legacy' in rs[r['uid_hex']]]
out.append(('Legacy moves', '9 per species', cnt['legacy'], sole['legacy'],
            'cap 6: frees %d; cap 4: frees %d' % (ordinal_free(leg, lambda r: r['pokemon_id'], ivo, 6, S('legacy')), ordinal_free(leg, lambda r: r['pokemon_id'], ivo, 4, S('legacy')))))
xx = [r for r in K if 'xxl' in rs[r['uid_hex']]]
pts = {r['uid_hex']: (sl.best_points(r) or 0) for r in xx}   # the XXL keep's points: evolution counts (2026-09-24)
out.append(('XXL showcase winners', '>= %d pts, best 2' % int(sw['min_points']), cnt['xxl'], sole['xxl'],
            '>= 1000: frees %d; >= 1050: frees %d; best 1: frees %d' % (sum(1 for r in xx if r['uid_hex'] in S('xxl') and pts[r['uid_hex']] < 1000),
                                                                        sum(1 for r in xx if r['uid_hex'] in S('xxl') and pts[r['uid_hex']] < 1050),
                                                                        ordinal_free(xx, lambda r: r['pokemon_id'], lambda r: (-pts[r['uid_hex']], r['uid_hex']), 1, S('xxl')))))
sh_sole = S('shadow_best')
out.append(('Shadow (best ML + GL + UL)', '1 + 1 + 1, rank <= %d' % keep_config.pvp('shadow_rank_floor'), cnt['shadow_best'], sole['shadow_best'],
            'best ML only: frees up to %d' % sum(1 for r in K if r['uid_hex'] in sh_sole and (r['ml_rank'] or 99999) > 1)))
out.append(('Best ML (non-hundo copies)', 'rule', cnt['pvp_best_ml'], sole['pvp_best_ml'], 'drop it: frees %d' % sole['pvp_best_ml']))
out.append(('Best GL / Best UL (usable only)', 'rule', cnt['pvp_best_gl'] + cnt['pvp_best_ul'], sole['pvp_best_gl'] + sole['pvp_best_ul'],
            'sole-kept: GL %d, UL %d' % (sole['pvp_best_gl'], sole['pvp_best_ul'])))
out.append(('GL/UL rank 1-5 spreads', 'rule', cnt['pvp_rank'] + cnt['gl_iv'] + cnt['ul_iv'], sole['pvp_rank'] + sole['gl_iv'] + sole['ul_iv'], '-'))
nsp = len({rows[u]['pokemon_id'] for u, v in rs.items() if 'nundo' in v})
out.append(('Nundo', '1 per look', cnt['nundo'], sole['nundo'], '1 per species: frees ~%d' % max(0, cnt['nundo'] - nsp)))
out.append(('Last copy of a form', 'keep', onlydex, onlydex, 'off: frees %d' % onlydex))
out.append(('Evolve picks (held to evolve)', '-', cnt['evolve_1'] + cnt['evolve_2'] + cnt['shiny_ladder'], sole['evolve_1'] + sole['evolve_2'] + sole['shiny_ladder'], 'evolve them, then re-cull'))
out.append(('AE / Mighty / E+F / Protected / Favorite', 'keep', cnt['adventure_effect'] + cnt['mighty'] + cnt['origin'] + cnt['protected'] + cnt['favorite'],
            sole['adventure_effect'] + sole['mighty'] + sole['origin'] + sole['protected'] + sole['favorite'], '-'))
print('%-36s %-20s %6s %6s  %s' % ('RULE', 'CAP', 'KEEPS', 'ONLY', 'ONE STEP TIGHTER -> SLOTS FREED'))
for name, cap, k, so, tight in out:
    print('%-36s %-20s %6d %6d  %s' % (name, cap, k, so, tight))
print('\nbag %d | kept %d | pile %d | hundos %d (always kept)' % (len(rows), len(kept), len(pile), sum(1 for r in rows.values() if r['iv_total'] == 45)))
