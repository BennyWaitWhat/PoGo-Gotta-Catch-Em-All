"""Bag Pulse -> system/analysis/collection_stats.html: the collection as a dashboard (the last 30 culls pass by pass with
PvP standing, KPIs, day trends with a projection, IV bands, shinies, missing hundos, regions, showcase winners). Read-only; run after a cull. Supersedes the table page
gen_collection_stats.py wrote (2026-09-23). Since 2026-09-30 the Transfer pile also shows as sprites and location cards, in the game's own names
(bag_art.py + pogo_display.py; display only, never fails the page; BAG_ART=0 renders the page as it was).

Every number comes from the same sources the cull uses: pokemon.db (in_bag=1), policy_reasons.json, the tagsets,
ladder_history.json, pokedex_hundos_live.json and size_line.showcase_points -- so the page agrees with the phone.
"""
import collections
import json
import math
import os
import sqlite3
import sys
import time

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
import keep_config
import size_line as sl
import evolvable_forms as ef
from pvp_iv_rule import pvid
# PICTURES + THE GAME'S OWN NAMES (2026-09-30, docs/memory/pogo-bag-pulse-sprites.md): the Transfer pile as sprites (form, costume,
# gender, shiny, background card) and official species / form names. DISPLAY ONLY, and the page must never fail for it: this
# import is guarded, bag_art.prepare never raises, and BAG_ART=0 gives back the page as it was, byte for byte.
try:
    import bag_art
    import pogo_display
    NAMES = pogo_display.Names.load() if bag_art.enabled() else pogo_display.Names.empty()
except Exception as _e:
    bag_art = pogo_display = None
    print('bag_art unavailable (%s) -- text-only page' % _e)

    class _Plain:                                                  # today's names: whatever the walk stored
        species = staticmethod(lambda dex, fallback='': fallback)
        label = staticmethod(lambda r: r['species_name'])
        fix_stamped = staticmethod(lambda t: t)
        learn = staticmethod(lambda rows: None)
    NAMES = _Plain()
ART_ON = bag_art is not None and bag_art.enabled()

con = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
con.row_factory = sqlite3.Row
rows = [keep_config.row_dict(r) for r in con.execute('SELECT * FROM pokemon WHERE in_bag=1')]
con.close()
reasons = {k: set(v) for k, v in json.load(open('system/analysis/policy_reasons.json', encoding='utf-8')).items() if isinstance(v, list)}
TD = os.path.join('system', 'analysis', 'tagsets')
tag = lambda n: set(open(os.path.join(TD, n)).read().split()) if os.path.exists(os.path.join(TD, n)) else set()
pile = tag('Transfer.txt')
# THE LIVE STORAGE CAP (2026-09-26, "normalize the bag size in the alt bag pulse"): the walk writes player_state.json at
# the project root as max_pokemon_storage. This read the wrong path AND the wrong key, so it always fell back to a
# hardcoded 5850 -- a 1,000-slot account showed 5,000+ free. Never a hardcoded capacity: no reading, no page.
try:
    cap_total = int(json.load(open('player_state.json', encoding='utf-8'))['max_pokemon_storage'])
except Exception as _e:
    raise SystemExit('%s: live storage cap unreadable from player_state.json (%s) -- run a walk first' % (__file__, _e))
hist = json.load(open('system/analysis/ladder_history.json', encoding='utf-8'))
import datetime as _dt
_cut = (_dt.datetime.now() - _dt.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')
tday = [e for e in hist if e['ts'] >= _cut]          # the last 24 hours, not the calendar day
bydays = collections.OrderedDict()
for e in hist:
    bydays[e['ts'][:10]] = e
days = list(bydays.keys())

P = lambda r: round((r['iv_total'] or 0) / 45 * 100)
mean = lambda xs: (sum(xs) / len(xs)) if xs else 0
N = len(rows)
kept = [r for r in rows if r['uid_hex'] not in pile]
shiny = [r for r in rows if r['fresh_shiny']]
shiny_kept = [r for r in shiny if r['uid_hex'] not in pile]
shadow = [r for r in rows if r['fresh_alignment'] == 1]
hundo = [r for r in rows if r['iv_total'] == 45]
nundo = [r for r in rows if r['iv_total'] == 0]
lucky = [r for r in rows if r['is_lucky']]
xxl = [r for r in rows if (r['pokemon_size_category'] or 0) == 5]
xxl_pts = sorted([((sl.showcase_points(r) or 0), r) for r in xxl], key=lambda x: -x[0])
sizes = collections.Counter(r['pokemon_size_category'] or 0 for r in rows)
species = {r['pokemon_id'] for r in rows}
ident = {pvid(r['species_name'], r['form'] or 0) for r in rows}
tags = {}
for f in sorted(os.listdir(TD)):
    if f.endswith('.txt') and not f[0].isdigit():
        tags[f[:-4].replace('_', ' ')] = len(tag(f))
sw = keep_config.showcase_weights()
pvp_reasons = {'pvp_rank', 'gl_iv', 'ul_iv', 'pvp_spread', 'pvp_best_gl', 'pvp_best_ul', 'pvp_best_ml', 'shadow_best'}
nonpvp = [r for r in kept if r['iv_total'] != 45 and not r['fresh_shiny'] and r['fresh_alignment'] != 1
          and 'variant_floor' in reasons.get(r['uid_hex'], set()) and not (reasons.get(r['uid_hex'], set()) & pvp_reasons)]
reason_ct = collections.Counter(x for v in reasons.values() for x in v if x != 'dex_only_copy')
sole = collections.Counter(next(iter(v - {'dex_only_copy'})) for v in reasons.values() if len(v - {'dex_only_copy'}) == 1)
REASON_NAMES = {'variant_floor': 'Plain ladder slot', 'shiny': 'Shiny', 'pvp_best_ml': 'Best ML', 'pvp_best_ul': 'Best UL', 'pvp_best_gl': 'Best GL',
                'hundo': 'Hundo', 'rarity': 'Legendary / rare', 'legacy': 'Legacy move', 'location_card': 'Location card', 'xxl': 'XXL showcase winner',
                'shadow_best': 'Best shadow', 'pvp_rank': 'GL/UL rank 1-5', 'gl_iv': 'GL spread', 'ul_iv': 'UL spread', 'evolve_1': 'Evolve next',
                'evolve_2': 'Evolve twice', 'nundo': 'Nundo', 'adventure_effect': 'Adventure Effect', 'origin': 'Traded by E+F', 'protected': 'Protected species',
                'pvp_spread': '0-15-15 spread', 'shiny_ladder': 'Evolve shiny', 'mighty': 'Mighty', 'favorite': 'Favorite',
                'pvp_combup_gl': 'GL comb-up (evolve)', 'pvp_combup_ul': 'UL comb-up (evolve)'}


def trend(vals):
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    n = len(pts)
    if n < 3:
        return None
    mx = sum(i for i, _ in pts) / n
    my = sum(v for _, v in pts) / n
    sxx = sum((i - mx) ** 2 for i, _ in pts) or 1
    return sum((i - mx) * (v - my) for i, v in pts) / sxx, n


ser = lambda k: [bydays[d].get(k) for d in days]
res = ser('resident_mean_iv')
t = trend(res)
slope = t[0] if t else 0
cur = res[-1] or 0
proj_days = [7, 14, 21, 28]
proj_vals = [round(cur + slope * d, 2) for d in proj_days]


def eta(target):
    if slope <= 0 or target <= cur:
        return None
    d = (target - cur) / slope
    return {'days': round(d), 'date': time.strftime('%b %d', time.localtime(time.time() + d * 86400))}


ceiling = bydays[days[-1]].get('best_per_stage_mean_iv') or 0
day_labels = [d[5:].replace('-', '/') for d in days]
bands = ['0-9', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80-89', '90-100']
ivh = collections.Counter(min(9, P(r) // 10) for r in kept)
ivh_s = collections.Counter(min(9, P(r) // 10) for r in shiny)
sh_stage_best = collections.defaultdict(int)
for r in shiny:
    k = ef.stage_of(pvid(r['species_name'], r['form'] or 0), r['form'] or 0)
    sh_stage_best[k] = max(sh_stage_best[k], P(r))
dex = json.load(open('pokedex_hundos_live.json', encoding='utf-8'))
ents = {e['pid']: e for e in dex.get('entries', [])}
names = {}
for r in rows:
    names.setdefault(r['pokemon_id'], NAMES.species(r['pokemon_id'], r['species_name']))
nm = lambda pid: names[pid] if pid in names else NAMES.species(pid, '#%d' % pid)      # the game's own spelling: Mr. Mime, Nidoran♀
NAMES.learn(rows)
ever_hundo = {pid for pid, e in ents.items() if e.get('hundo')}
never_hundo = sorted(((e.get('times', 0), pid) for pid, e in ents.items() if not e.get('hundo')), reverse=True)
bag_hundo = {r['pokemon_id'] for r in hundo}
bag_no_hundo = sorted({r['pokemon_id'] for r in rows} - bag_hundo, key=lambda p: -ents.get(p, {}).get('times', 0))
bag_shiny = {r['pokemon_id'] for r in shiny}
bag_no_shiny = sorted({r['pokemon_id'] for r in rows} - bag_shiny, key=lambda p: -ents.get(p, {}).get('times', 0))
times = {pid: e.get('times', 0) for pid, e in ents.items()}
GENS = [(1, 151, 'Kanto'), (152, 251, 'Johto'), (252, 386, 'Hoenn'), (387, 493, 'Sinnoh'), (494, 649, 'Unova'), (650, 721, 'Kalos'), (722, 809, 'Alola'), (810, 905, 'Galar'), (906, 1025, 'Paldea')]
regions = []
for a, b, g in GENS:
    inb = [r for r in rows if a <= (r['pokemon_id'] or 0) <= b]
    if not inb:
        continue
    sp = {r['pokemon_id'] for r in inb}
    regions.append({'name': g, 'mons': len(inb), 'species': len(sp), 'hundos': sum(1 for r in inb if r['iv_total'] == 45),
                    'shinies': sum(1 for r in inb if r['fresh_shiny']), 'avg_iv': round(mean([P(r) for r in inb if r['uid_hex'] not in pile and r['fresh_alignment'] != 1]), 1),
                    'hundo_species': len([p for p in sp if p in ever_hundo])})
HOME = (33.749, -84.388)


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


located = [r for r in rows if r['lat'] is not None and r['lon'] is not None]
far = sorted(located, key=lambda r: -km(HOME, (r['lat'], r['lon'])))[:6]
near_home = sum(1 for r in located if km(HOME, (r['lat'], r['lon'])) < 100)
abroad = sum(1 for r in located if not (24.4 <= r['lat'] <= 49.4 and -125.0 <= r['lon'] <= -66.9)
             and not (18.8 <= r['lat'] <= 22.4 and -160.5 <= r['lon'] <= -154.6) and not (51.0 <= r['lat'] <= 71.5 and (r['lon'] <= -129.0 or r['lon'] >= 172.0)))
S = lambda k: sum(e.get(k, 0) or 0 for e in tday[1:])
first_iv = bydays[days[0]].get('resident_mean_iv')

# ---- per-pass cull log (every pass, newest first)
_con2 = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
_con2.row_factory = sqlite3.Row
_uids = sorted({u for e in hist[-40:] for u in (e.get('_pile') or [])})
_nm = {}
for i in range(0, len(_uids), 400):
    _chunk = _uids[i:i + 400]
    for r in _con2.execute('SELECT uid_hex, species_name, iv_total, in_bag, pokemon_id, form, fresh_form FROM pokemon WHERE uid_hex IN (%s)' % ','.join('?' * len(_chunk)), _chunk):
        _nm[r['uid_hex']] = (r['species_name'], round((r['iv_total'] or 0) * 100 / 45), r['in_bag'], r['pokemon_id'], r['form'], r['fresh_form'])
_con2.close()
NAMES.learn([{'species_name': v[0], 'pokemon_id': v[3]} for v in _nm.values()])
_lab = lambda u: NAMES.label({'pokemon_id': _nm[u][3], 'species_name': _nm[u][0], 'form': _nm[u][4], 'fresh_form': _nm[u][5]})
passes, _ents = [], []
for e in reversed(hist[-40:]):
    pl = e.get('_pile') or []
    _pn = e.get('_pile_names') or {}                       # stamped by ladder_report at write time (released rows leave the DB)
    # (uid, text): the text keeps today's shape ('<name> <iv>%'), with the game's own name; the uid lets the sprite step
    # find the mon again. A stamped name is '<DB spelling> <iv>%': fix_stamped only respells the prefix (Nidoran F -> Nidoran♀)
    ent = [(u, ('%s %d%%' % (_lab(u), _nm[u][1])) if u in _nm else (NAMES.fix_stamped(_pn[u]) + ' (released)')) for u in pl if u in _nm or u in _pn]
    labs = [t for _u, t in ent]
    _ents.append((ent[:14], len(ent) > 14))
    passes.append({'ts': e['ts'], 'bag': e.get('bag'), 'free': (cap_total - e['bag']) if e.get('bag') else None, 'pile': len(pl),
                   'caught': e.get('caught', 0), 'released': e.get('released', 0), 'evolved': e.get('evolved', 0), 'picks': e.get('promises_kept', 0),
                   'improved': e.get('stage_best_improved', 0), 'hundos': e.get('new_hundos', 0), 'ladder': e.get('resident_mean_iv'),
                   'pile_list': ', '.join(labs[:14]) + (' ...' if len(labs) > 14 else '')})
# CULL BY CULL (2026-09-29, user: "i cant really tell the trend in iv improvement and pvp improvement"): the day-level
# charts hide it -- the ladder moves 0.1 a day and PvP standing was not recorded at all. So: the last 30 passes as a
# series (IV, best copy per stage, PvP forms at #1 / top 5 / top 100 -- ladder_report.pvp_metrics, backfilled from the
# walk snapshots), what each pass found, and the window's totals. Cumulative wins climb even when an average does not.
PP = hist[-30:]
_s = lambda k: [e.get(k) for e in PP]
def _cum(*ks):
    out, s = [], 0
    for e in PP:
        s += sum(e.get(k) or 0 for k in ks); out.append(s)
    return out
def _fl(k, nd=None):
    a, b = PP[0].get(k), PP[-1].get(k)
    return {'from': a, 'to': b, 'd': None if a is None or b is None else (round(b - a, nd) if nd is not None else b - a)}
_sum = lambda k: sum(e.get(k) or 0 for e in PP)
WINDOW = {
    'n': len(PP), 'from': PP[0]['ts'], 'to': PP[-1]['ts'], 'labels': [e['ts'][5:16].replace('-', '/') for e in PP],
    'ladder': _fl('resident_mean_iv', 1), 'best': _fl('best_per_stage_mean_iv', 1), 'shiny': _fl('shiny_mean_iv', 1),
    'gl5': _fl('pvp_gl_top5'), 'ul5': _fl('pvp_ul_top5'), 'gl1': _fl('pvp_gl_rank1'), 'ul1': _fl('pvp_ul_rank1'),
    'gl100': _fl('pvp_gl_top100'), 'ul100': _fl('pvp_ul_top100'), 'hundo_stages': _fl('stages_with_hundo'),
    'sum': {'improved': _sum('stage_best_improved'), 'hundos': _sum('new_hundos'), 'gl1': _sum('new_gl1'), 'ul1': _sum('new_ul1'),
            'evolved': _sum('evolved'), 'picks': _sum('promises_kept'), 'broken': _sum('promises_broken'), 'caught': _sum('caught'), 'released': _sum('released')},
    'series': {'ladder': _s('resident_mean_iv'), 'best': _s('best_per_stage_mean_iv'), 'gl5': _s('pvp_gl_top5'), 'ul5': _s('pvp_ul_top5'),
               'gl1': _s('pvp_gl_rank1'), 'ul1': _s('pvp_ul_rank1'), 'gl100': _s('pvp_gl_top100'), 'ul100': _s('pvp_ul_top100'),
               'improved': _s('stage_best_improved'), 'hundos': _s('new_hundos'), 'pvp1': [(e.get('new_gl1') or 0) + (e.get('new_ul1') or 0) for e in PP]},
    'cum': {'improved': _cum('stage_best_improved'), 'hundos': _cum('new_hundos'), 'pvp1': _cum('new_gl1', 'new_ul1'), 'picks': _cum('promises_kept')},
}
for i, p in enumerate(passes):                       # newest first: hist[-1-i]; its delta is against the pass before it
    _e, _p = hist[-1 - i], (hist[-2 - i] if len(hist) >= i + 2 else None)
    p['ladder_d'] = None if not _p or _e.get('resident_mean_iv') is None or _p.get('resident_mean_iv') is None else round(_e['resident_mean_iv'] - _p['resident_mean_iv'], 1)
    p['gl5'], p['ul5'] = _e.get('pvp_gl_top5'), _e.get('pvp_ul_top5')
    p['gl1'], p['ul1'] = _e.get('new_gl1', 0), _e.get('new_ul1', 0)
# THE PILE AS PICTURES (2026-09-30, user: seeing each pile mon's exact look next to its name finds the right copy faster --
# he releases the pile by hand). The current Transfer pile first, then the mons of the pass log that are still in the bag;
# bag_art.prepare fetches / caches / thumbnails and NEVER raises, so anything that goes wrong here is today's text page.
# Past passes whose mons left the bag keep text: 921 of the last 973 pile uids are gone from the DB, a picture cannot help find them.
byuid = {r['uid_hex']: r for r in rows}
pile_rows = [byuid[u] for u in sorted(pile) if u in byuid]
art, pile_html = None, ''
if ART_ON:
    try:
        _seen = {r['uid_hex'] for r in pile_rows}
        _spr_uids = [r['uid_hex'] for r in pile_rows]
        for _ent, _more in _ents:
            for _u, _t in _ent:
                if _u in byuid and _u not in _seen:
                    _seen.add(_u)
                    _spr_uids.append(_u)
        art = bag_art.prepare(rows, _spr_uids, [r['uid_hex'] for r in pile_rows])
        pile_html = bag_art.pile_card_html(art, pile_rows, NAMES, ef.gender_key, ef.max_axis, unknown=len(pile) - len(pile_rows))
        for p, (_ent, _more) in zip(passes, _ents):
            items = []
            for _u, _t in _ent:
                it = {'t': _t}
                _k = art.sprite_key(_u) if _u in byuid else None
                if _k:
                    it['k'], it['n'] = _k, NAMES.label(byuid[_u])
                    if art.match[_u].approx:
                        it['a'] = 1
                items.append(it)
            if any('k' in it for it in items):               # a pass with no picture keeps the plain text cell
                p['pile_items'], p['pile_more'] = items, _more
    except Exception as _e:
        art, pile_html = None, ''
        for p in passes:
            p.pop('pile_items', None)
            p.pop('pile_more', None)
        print('art step skipped (%s: %s) -- text-only page' % (type(_e).__name__, _e))
DATA = {
    'window': WINDOW,
    'generated': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime('pokemon.db'))), 'history_from': days[0], 'history_to': days[-1],
    'kpi': {'bag': N, 'cap': cap_total, 'kept': len(kept), 'pile': len(pile), 'species': len(species), 'identities': len(ident),
            'hundos': len(hundo), 'hundos_today': S('new_hundos'), 'shinies': len(shiny), 'shiny_iv': round(mean([P(r) for r in shiny]), 1),
            'ladder_iv': cur, 'ladder_iv_delta': round(cur - first_iv, 1) if first_iv is not None else None,
            'nonpvp_iv': round(mean([P(r) for r in nonpvp]), 1), 'nonpvp_n': len(nonpvp),
            'best_stage_iv': ceiling, 'xxl_winners': tags.get('XXL', 0), 'xxl_min': int(sw['min_points']),
            'shadows': len(shadow), 'nundos': len(nundo), 'lucky': len(lucky), 'legacy': tags.get('Legacy Moves', 0), 'ae': tags.get('Adventure Effect', 0),
            'gl5': hist[-1].get('pvp_gl_top5'), 'ul5': hist[-1].get('pvp_ul_top5'), 'gl1': hist[-1].get('pvp_gl_rank1'), 'ul1': hist[-1].get('pvp_ul_rank1')},
    'trend': {'labels': day_labels, 'ladder': res, 'best_stage': ser('best_per_stage_mean_iv'), 'shiny_iv': ser('shiny_mean_iv'),
              'shiny3': ser('shiny_stages_3star'), 'hundo_stages': ser('stages_with_hundo'), 'stages': ser('stages'),
              'gl5': ser('pvp_gl_top5'), 'ul5': ser('pvp_ul_top5'), 'gl100': ser('pvp_gl_top100'), 'ul100': ser('pvp_ul_top100'),
              'proj_labels': ['+%dd' % d for d in proj_days], 'proj': proj_vals, 'slope': round(slope, 3), 'n': t[1] if t else 0,
              'eta': {'89.5': eta(89.5), '90': eta(90.0), '91': eta(91.0)}, 'ceiling': ceiling},
    'bands': {'labels': bands, 'kept': [ivh.get(i, 0) for i in range(10)], 'shiny': [ivh_s.get(i, 0) for i in range(10)]},
    'shiny': {'total': len(shiny), 'kept': len(shiny_kept), 'avg': round(mean([P(r) for r in shiny]), 1), 'avg_kept': round(mean([P(r) for r in shiny_kept]), 1),
              'hundos': sum(1 for r in shiny if r['iv_total'] == 45), 'stages': len(sh_stage_best),
              'stages_3star': sum(1 for v in sh_stage_best.values() if v >= 82), 'stages_under50': sum(1 for v in sh_stage_best.values() if v < 50)},
    'sizes': [sizes.get(1, 0), sizes.get(2, 0), sizes.get(3, 0), sizes.get(4, 0), sizes.get(5, 0)],
    'reasons': [{'name': REASON_NAMES.get(k, k), 'mons': v, 'sole': sole.get(k, 0)} for k, v in reason_ct.most_common(14)],
    'dex': {'species_ever': len(ents), 'hundo_ever': len(ever_hundo), 'never_hundo': len(never_hundo),
            'never_hundo_top': [{'name': nm(p), 'times': t_} for t_, p in never_hundo[:24]],
            'bag_no_hundo': len(bag_no_hundo), 'bag_no_hundo_top': [{'name': nm(p), 'times': times.get(p, 0)} for p in bag_no_hundo[:24]],
            'shiny_hundo_ever': sum(1 for e in ents.values() if e.get('shinyHundo')),
            'bag_no_shiny': len(bag_no_shiny), 'bag_no_shiny_top': [{'name': nm(p), 'times': times.get(p, 0)} for p in bag_no_shiny[:24]],
            'hundo_stages': bydays[days[-1]].get('stages_with_hundo'), 'stages': bydays[days[-1]].get('stages')},
    'regions': regions,
    'showcase': [{'name': NAMES.label(r), 'iv': P(r), 'h': round(r['height_m'] or 0, 2), 'w': round(r['weight_kg'] or 0, 2), 'pts': p} for p, r in xxl_pts[:10]],
    'places': {'known': len(located), 'near_home': near_home, 'abroad': abroad,
               'far': [{'name': NAMES.label(r), 'iv': P(r), 'km': round(km(HOME, (r['lat'], r['lon'])))} for r in far]},
    'today': {'culls': len(tday), 'caught': S('caught'), 'released': S('released'), 'evolved': S('evolved'), 'picks': S('promises_kept'),
              'broken': S('promises_broken'), 'improved': S('stage_best_improved')} if tday else None,
    'tags': sorted(tags.items(), key=lambda kv: -kv[1]),
    'passes': passes,
}
if art is not None:                                          # absent with BAG_ART=0, so the DATA (and the page) are today's
    DATA['spr'] = dict(sorted(art.sprites.items()))          # icon file name (or 'c:' + card stem) -> data: URI; sorted: a stable page
    DATA['art'] = art.page_stats()                           # what the art step did (no local paths): for whoever debugs the artifact

TEMPLATE = r'''<title>Bag Pulse</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lilita+One&family=Manrope:wght@300;500;600;700&family=Nunito:wght@400;600;700;800&family=IBM+Plex+Mono:wght@500&display=swap">
<style>
/* Night Pokedex: the README banner's world -- deep navy into plum, Poke Ball red, shiny gold. One dark look on purpose. */
:root{color-scheme:dark;
--bg:#080b14;--surface:#0f1629;--surface-2:#141d36;--ink:#eef1fb;--mut:#8e9bbd;--line:#1f2b4b;
--accent:#ff6b81;--accent-soft:rgba(255,107,129,.16);--shiny:#ffc15e;--shiny-soft:rgba(255,193,94,.16);
--hundo:#7ee0b0;--hundo-soft:rgba(126,224,176,.16);--pvp:#8fb3ff;--warn:#c3a6ff;--proj:#6b7899;
--ball-red:#ff3b5c;--grid:rgba(142,155,189,.10);--font-num:'Manrope','Nunito',system-ui,sans-serif;
--hero-a:#0a0f1f;--hero-b:#14224a;--hero-c:#2a0f2e;--ball-white:#e9edf8;--glow-violet:rgba(185,140,255,.10);
--font-display:'Lilita One','Nunito',system-ui,sans-serif;--font-body:'Nunito',system-ui,sans-serif;--font-mono:'IBM Plex Mono',ui-monospace,Menlo,monospace}
body{background:var(--bg);background-image:radial-gradient(900px 520px at 100% -10%,var(--accent-soft),transparent 60%),radial-gradient(760px 520px at -10% 110%,var(--glow-violet),transparent 60%);background-attachment:fixed;color:var(--ink);font-family:var(--font-body);font-size:14px;line-height:1.45;margin:0}
.wrap{max-width:1080px;margin:0 auto;padding-block:22px 40px;padding-inline:16px}
.hero{display:flex;align-items:center;gap:16px;background:linear-gradient(120deg,var(--hero-a),var(--hero-b) 55%,var(--hero-c));border:1px solid var(--line);border-radius:18px;padding:18px 20px;margin-bottom:16px;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;right:-70px;top:-70px;width:230px;height:230px;border-radius:50%;border:10px solid var(--ball-red);opacity:.16;pointer-events:none}
.hero > div{min-width:0}
.ball{flex:none;width:46px;height:46px;border-radius:50%;position:relative;background:linear-gradient(var(--ball-red) 0 44%,var(--bg) 44% 56%,var(--ball-white) 56%);box-shadow:0 0 0 3px var(--bg),0 0 26px var(--accent-soft)}
.ball::after{content:"";position:absolute;left:50%;top:50%;width:14px;height:14px;transform:translate(-50%,-50%);border-radius:50%;background:var(--ball-white);box-shadow:0 0 0 4px var(--bg)}
h1{font-family:var(--font-display);font-weight:400;font-size:34px;line-height:1;margin:0;letter-spacing:.01em;text-wrap:balance}
.sub{color:var(--mut);margin:6px 0 0;font-size:13px}
h2{font-family:var(--font-num);font-weight:600;font-size:17px;margin:0 0 10px;letter-spacing:-.005em;text-wrap:balance}
.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--mut);font-weight:700}
.hero .eyebrow,.card > .eyebrow{color:var(--shiny)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:14px 16px;display:flex;flex-direction:column;gap:6px;transition:border-color .2s}
.kpi:hover{border-color:var(--accent)}
.kpi .v{font-family:var(--font-num);font-size:30px;font-weight:300;line-height:1.05;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.rings{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:12px}
.ring{background:var(--surface);border:1px solid var(--line);border-radius:22px;padding:16px 10px 14px;display:flex;flex-direction:column;align-items:center;gap:4px;text-align:center;min-width:0}
.ring .dial{position:relative;width:118px;height:118px}.ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.ring .num{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-family:var(--font-num);font-weight:300;font-size:30px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.ring .num small{font-size:14px;font-weight:500;color:var(--mut);margin-left:1px}
.ring .l{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--mut);font-weight:700;margin-top:4px}
.ring .s{font-size:12px;color:var(--mut)}
.kpi .d{font-size:12px;color:var(--mut)}.up{color:var(--hundo);font-weight:700}.hu{color:var(--hundo)}.sh{color:var(--shiny)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--shiny))}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-bottom:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:14px 16px;min-width:0}
.card.wide{grid-column:1/-1}
.chart{position:relative;height:220px;width:100%}.chart.tall{height:260px}
.note{color:var(--mut);font-size:12px;margin:8px 0 0}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}th{color:var(--mut);font-weight:700;font-size:12px}
tr:hover td{background:var(--surface-2)}
td.num,th.num{text-align:right}.tbl{overflow-x:auto}
.mini{display:inline-block;height:8px;border-radius:4px;background:var(--accent);vertical-align:middle;margin-right:6px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:12px;background:var(--surface-2)}
.chip b{font-family:var(--font-mono);font-weight:500;color:var(--mut);margin-left:4px}
.eta{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.eta div{background:var(--surface-2);border-radius:10px;padding:8px 10px}
.eta .t{font-size:12px;color:var(--mut)}.eta .w{font-family:var(--font-mono);font-size:15px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-bottom:6px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
a{color:var(--shiny)}
:focus-visible{outline:2px solid var(--shiny);outline-offset:2px}
@media (max-width:480px){.eta{grid-template-columns:1fr}.kpi .v{font-size:22px}h1{font-size:28px}.ball{width:38px;height:38px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
__ART_CSS__</style>
<div class="wrap">
  <header class="hero"><span class="ball" aria-hidden="true"></span><div><h1>Bag Pulse</h1><p class="sub" id="sub"></p></div></header>
  <div class="rings" id="rings"></div>
  <div class="kpis" id="kpis"></div>
  <div class="grid">
    __PILE_CARD__<div class="card wide">
      <div class="eyebrow">Cull by cull</div><h2 id="win_h2"></h2>
      <p class="note" id="win_note" style="margin:0 0 10px"></p>
      <div class="kpis" id="win_kpis" style="margin-bottom:12px"></div>
      <div class="grid" style="margin-bottom:0">
        <div class="card" style="padding:10px 12px"><div class="eyebrow">IV, every pass</div>
          <div class="legend"><span><i style="background:var(--accent)"></i>ladder average (left)</span><span><i style="background:var(--hundo)"></i>best copy per stage (right)</span></div>
          <div class="chart"><canvas id="c_pp_iv"></canvas></div></div>
        <div class="card" style="padding:10px 12px"><div class="eyebrow">PvP standing, every pass</div>
          <div class="legend"><span><i style="background:var(--pvp)"></i>GL forms in the top 5</span><span><i style="background:var(--warn)"></i>UL forms in the top 5</span><span>dashed: forms at #1</span></div>
          <div class="chart"><canvas id="c_pp_pvp"></canvas></div></div>
        <div class="card wide" style="padding:10px 12px"><div class="eyebrow">Wins, adding up</div>
          <div class="legend"><span><i style="background:var(--accent)"></i>stage bests beaten</span><span><i style="background:var(--hundo)"></i>new hundos</span><span><i style="background:var(--pvp)"></i>GL / UL #1 found</span><span><i style="background:var(--shiny)"></i>evolve picks done</span></div>
          <div class="chart"><canvas id="c_pp_cum"></canvas></div>
          <p class="note">Each line is a running total over these culls: a stage best is a new plain copy better than any you had at that stage; a pick is an Evolve label you followed. Flat stretches are culls that only released.</p></div>
      </div>
    </div>
    <div class="card wide">
      <div class="eyebrow">Non-PvP keepers</div><h2>Plain ladder average IV, and where it's heading</h2>
      <div class="legend"><span><i style="background:var(--accent)"></i>slot-holder average</span><span><i style="background:var(--proj)"></i>projection at the current pace</span><span><i style="background:var(--hundo)"></i>ceiling: best copy per stage</span></div>
      <div class="chart tall"><canvas id="c_ladder"></canvas></div>
      <div class="eta" id="eta"></div>
      <p class="note" id="ladder_note"></p>
    </div>
    <div class="card"><div class="eyebrow">Shinies</div><h2>Average shiny IV</h2><div class="chart"><canvas id="c_shiny"></canvas></div><p class="note" id="shiny_note"></p></div>
    <div class="card"><div class="eyebrow">Shinies</div><h2>Stages whose best shiny is 3-star</h2><div class="chart"><canvas id="c_shiny3"></canvas></div></div>
    <div class="card"><div class="eyebrow">Hundos</div><h2>Stages with a hundo</h2><div class="chart"><canvas id="c_hundo"></canvas></div><p class="note" id="hundo_note"></p></div>
    <div class="card"><div class="eyebrow">PvP</div><h2>Battle forms with a copy in the top 100, per day</h2>
      <div class="legend"><span><i style="background:var(--pvp)"></i>Great League</span><span><i style="background:var(--warn)"></i>Ultra League</span></div>
      <div class="chart"><canvas id="c_pvp_day"></canvas></div><p class="note" id="pvp_note"></p></div>
    <div class="card"><div class="eyebrow">Distribution</div><h2>IV bands: kept mons vs shinies</h2><div class="chart"><canvas id="c_bands"></canvas></div></div>
    <div class="card"><div class="eyebrow">Why things are kept</div><h2>Keep reasons (a mon can have several)</h2><div class="chart tall"><canvas id="c_reasons"></canvas></div></div>
    <div class="card"><div class="eyebrow">Sizes</div><h2>Size badges in the bag</h2><div class="chart"><canvas id="c_sizes"></canvas></div><p class="note" id="size_note"></p></div>
    <div class="card wide"><div class="eyebrow">Missing hundos</div><h2>Species you've caught but never as a hundo</h2><p class="note" id="dex_note" style="margin:0 0 8px"></p><div class="chips" id="never_hundo"></div>
      <p class="note" style="margin-top:12px">Species in the bag with no hundo in it right now (most caught first)</p><div class="chips" id="bag_no_hundo"></div></div>
    <div class="card wide"><div class="eyebrow">Missing shinies</div><h2>Species in the bag with no shiny in it</h2><p class="note" id="shiny_dex_note" style="margin:0 0 8px"></p><div class="chips" id="bag_no_shiny"></div></div>
    <div class="card wide"><div class="eyebrow">By region</div><h2>Where the collection is deep</h2><div class="tbl"><table id="regions"></table></div></div>
    <div class="card"><div class="eyebrow">Showcases</div><h2>Your top entries</h2><div class="tbl"><table id="showcase"></table></div><p class="note" id="show_note"></p></div>
    <div class="card"><div class="eyebrow">Places</div><h2>Where they were caught</h2><table id="places"></table></div>
    <div class="card wide"><div class="eyebrow">Last 24 hours</div><h2>What the culls did</h2><div class="kpis" id="today" style="margin:0"></div></div>
    <div class="card wide"><div class="eyebrow">Cull log</div><h2>Every pass, newest first</h2><div class="chart"><canvas id="c_passes"></canvas></div><div class="tbl"><table id="passes"></table></div></div>
    <div class="card wide"><div class="eyebrow">Tags on the phone</div><h2>Every managed tag and its size</h2><div class="chips" id="tags"></div></div>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const D = __DATA__;
__ART_JS__const css = getComputedStyle(document.documentElement);
const tok = n => css.getPropertyValue(n).trim();
const el = id => document.getElementById(id);
const pct = v => (v == null ? '-' : (typeof v === 'number' ? v.toFixed(1) : v) + '%');
const num = v => v == null ? '-' : v.toLocaleString();
const k = D.kpi;
el('sub').textContent = 'From the ' + D.generated + ' scan. History ' + D.history_from + ' to ' + D.history_to + '. Every figure is what the cull itself uses.';
const ring = (val, max, color, big, unit, label, sub) => {
  const r = 50, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, (val || 0) / max));
  return '<div class="ring"><div class="dial"><svg viewBox="0 0 120 120" aria-hidden="true">' +
    '<circle cx="60" cy="60" r="' + r + '" fill="none" stroke="' + tok('--line') + '" stroke-width="9"/>' +
    '<circle cx="60" cy="60" r="' + r + '" fill="none" stroke="' + color + '" stroke-width="9" stroke-linecap="round" stroke-dasharray="' + (c * f).toFixed(1) + ' ' + c.toFixed(1) + '"/>' +
    '</svg><div class="num">' + big + (unit ? '<small>' + unit + '</small>' : '') + '</div></div>' +
    '<div class="l">' + label + '</div><div class="s">' + sub + '</div></div>';
};
const fx = v => v == null ? '-' : v.toFixed(1);
el('rings').innerHTML = [
  ring(k.ladder_iv, 100, tok('--accent'), fx(k.ladder_iv), '%', 'Ladder IV', k.ladder_iv_delta == null ? 'average of the ladder' : '<span class="up">' + (k.ladder_iv_delta >= 0 ? '+' : '') + k.ladder_iv_delta + ' pts</span> since ' + D.history_from.slice(5).replace('-', '/')),
  ring(k.nonpvp_iv, 100, tok('--pvp'), fx(k.nonpvp_iv), '%', 'Non-PvP keepers', num(k.nonpvp_n) + ' plain slot holders'),
  ring(k.shiny_iv, 100, tok('--shiny'), fx(k.shiny_iv), '%', 'Shiny IV', num(k.shinies) + ' shinies'),
  ring(k.bag, k.cap, k.cap - k.bag < 50 ? tok('--accent') : tok('--hundo'), (100 * k.bag / k.cap).toFixed(0), '%', 'Storage', num(k.bag) + ' / ' + num(k.cap) + ' · ' + (k.cap - k.bag) + ' free'),
].join('');
el('kpis').innerHTML = [
  ['Hundos', '<span class="hu">' + num(k.hundos) + '</span>', (k.hundos_today ? '+' + k.hundos_today + ' today' : 'none new today'), ''],
  ['Shinies', '<span class="sh">' + num(k.shinies) + '</span>', 'average ' + pct(k.shiny_iv), ''],
  ['XXL winners', num(k.xxl_winners), '≥ ' + k.xxl_min + ' pts, best 2 per species', ''],
  ['PvP top-5 forms', '<span style="color:var(--pvp)">' + num(k.gl5) + '</span> · <span style="color:var(--warn)">' + num(k.ul5) + '</span>', 'GL · UL, at #1: ' + num(k.gl1) + ' · ' + num(k.ul1), ''],
  ['Transfer pile', num(k.pile), 'release by hand', ''],
  ['Species', num(k.species), num(k.identities) + ' battle forms', ''],
].map(([t, v, d, x]) => '<div class="kpi"><div class="eyebrow">' + t + '</div><div class="v">' + v + '</div><div class="d">' + d + '</div>' + x + '</div>').join('');

Chart.defaults.color = tok('--mut'); Chart.defaults.borderColor = tok('--grid'); Chart.defaults.font.family = tok('--font-body');
Chart.defaults.elements.bar.borderRadius = 6; Chart.defaults.plugins.tooltip.backgroundColor = tok('--surface-2');
Chart.defaults.plugins.tooltip.borderColor = tok('--line'); Chart.defaults.plugins.tooltip.borderWidth = 1; Chart.defaults.plugins.tooltip.padding = 10;
const rgba = (hex, a) => { const h = hex.replace('#', ''); if (h.length !== 6) return hex;
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')'; };
Chart.register({id: 'softFill', beforeDatasetsDraw(chart) {
  const a = chart.chartArea; if (!a) return;
  chart.data.datasets.forEach(ds => { if (!ds.fill || typeof ds.borderColor !== 'string' || ds.borderColor[0] !== '#') return;
    const g = chart.ctx.createLinearGradient(0, a.top, 0, a.bottom);
    g.addColorStop(0, rgba(ds.borderColor, .32)); g.addColorStop(1, rgba(ds.borderColor, 0)); ds.backgroundColor = g; });
}});
const mono = {family: tok('--font-mono'), size: 11};
const ax = extra => Object.assign({grid: {color: tok('--grid')}, border: {display: false}, ticks: {font: mono}}, extra || {});
const pctAx = extra => Object.assign({grid: {color: tok('--grid')}, border: {display: false}, ticks: {font: mono, callback: v => +(+v).toFixed(2) + '%'}}, extra || {});
const line = (id, labels, datasets, scales) => new Chart(el(id), {type: 'line', data: {labels, datasets}, options: {
  responsive: true, maintainAspectRatio: false, interaction: {mode: 'index', intersect: false}, plugins: {legend: {display: false}},
  scales: scales || {x: ax(), y: ax()}, elements: {point: {radius: 0, hoverRadius: 4}, line: {tension: .4, borderWidth: 2.5, borderCapStyle: 'round'}}}});
const W = D.window, WS = W.series;
const sgn = (v, nd) => v == null ? '—' : (v > 0 ? '+' : '') + (nd == null ? v : v.toFixed(nd));
const dcls = v => v > 0 ? 'up' : (v < 0 ? 'hu' : '');
const arrow = (o, unit) => o.from == null || o.to == null ? '—' : o.from + unit + ' → ' + o.to + unit;
el('win_h2').textContent = 'The last ' + W.n + ' culls: what moved';
el('win_note').textContent = W.from.slice(5).replace('-', '/') + ' to ' + W.to.slice(5).replace('-', '/') + '. Per-pass numbers; the day charts below smooth these out.';
el('win_kpis').innerHTML = [
  ['Ladder average IV', arrow(W.ladder, '%'), '<span class="' + dcls(W.ladder.d) + '">' + sgn(W.ladder.d, 1) + ' pts</span>'],
  ['Best copy per stage', arrow(W.best, '%'), '<span class="' + dcls(W.best.d) + '">' + sgn(W.best.d, 1) + ' pts</span>'],
  ['GL forms in the top 5', arrow(W.gl5, ''), '<span class="' + dcls(W.gl5.d) + '">' + sgn(W.gl5.d) + '</span> · at #1 ' + arrow(W.gl1, '')],
  ['UL forms in the top 5', arrow(W.ul5, ''), '<span class="' + dcls(W.ul5.d) + '">' + sgn(W.ul5.d) + '</span> · at #1 ' + arrow(W.ul1, '')],
  ['Forms in the top 100', arrow(W.gl100, '') + ' GL', arrow(W.ul100, '') + ' UL'],
  ['Stage bests beaten', W.sum.improved, 'new best plain copy at a stage'],
  ['New hundos', '<span class="hu">' + W.sum.hundos + '</span>', 'GL #1 found ' + W.sum.gl1 + ' · UL #1 found ' + W.sum.ul1],
  ['Evolved / caught / released', W.sum.evolved + ' / ' + W.sum.caught + ' / ' + W.sum.released, W.sum.picks + ' evolutions were picks' + (W.sum.broken ? ', ' + W.sum.broken + ' wasted' : '')],
].map(([t, v, d]) => '<div class="kpi"><div class="eyebrow">' + t + '</div><div class="v" style="font-size:20px">' + v + '</div><div class="d">' + d + '</div></div>').join('');
const tight = (vals, pad) => { const v = vals.filter(x => x != null); return {min: Math.min(...v) - pad, max: Math.max(...v) + pad}; };
const ppx = {grid: {display: false}, ticks: {font: {size: 10}, maxRotation: 60, autoSkip: true, maxTicksLimit: 12}};
const T = D.trend;
const lab = T.labels.concat(T.proj_labels);
const actual = T.ladder.concat(T.proj_labels.map(() => null));
const proj = T.ladder.map((v, i) => i === T.ladder.length - 1 ? v : null).concat(T.proj);
const ceil = lab.map(() => T.ceiling);
const yl = Math.min(...T.ladder.filter(v => v != null)) - 0.4, yh = Math.max(T.ceiling, ...T.proj) + 0.3;
line('c_ladder', lab, [
  {data: actual, borderColor: tok('--accent'), backgroundColor: tok('--accent-soft'), fill: true, borderWidth: 2.5},
  {data: proj, borderColor: tok('--proj'), borderDash: [6, 5], borderWidth: 2, pointStyle: 'rectRot', pointRadius: 4},
  {data: ceil, borderColor: tok('--hundo'), borderDash: [2, 4], borderWidth: 1.5, pointRadius: 0, fill: false}],
  {x: ax(), y: pctAx({min: Math.floor(yl * 2) / 2, max: Math.ceil(yh * 2) / 2})});
const etaTxt = e => e ? e.days + ' days · ' + e.date : '—';
{ const a = tight(WS.ladder, 0.15), b = tight(WS.best, 0.15);
  new Chart(el('c_pp_iv'), {type: 'line', data: {labels: W.labels, datasets: [
    {data: WS.ladder, borderColor: tok('--accent'), backgroundColor: tok('--accent-soft'), fill: true, borderWidth: 2.5, pointRadius: 0, yAxisID: 'y'},
    {data: WS.best, borderColor: tok('--hundo'), borderDash: [4, 4], borderWidth: 2, pointRadius: 0, yAxisID: 'y2'}]},
    options: {responsive: true, maintainAspectRatio: false, interaction: {mode: 'index', intersect: false}, plugins: {legend: {display: false}},
      scales: {x: ppx, y: pctAx({min: a.min, max: a.max}), y2: {position: 'right', grid: {display: false}, min: b.min, max: b.max, ticks: {font: mono, callback: v => +(+v).toFixed(2) + '%'}}},
      elements: {line: {tension: .25}}}}); }
new Chart(el('c_pp_pvp'), {type: 'line', data: {labels: W.labels, datasets: [
  {label: 'GL top 5', data: WS.gl5, borderColor: tok('--pvp'), borderWidth: 2.5, pointRadius: 2},
  {label: 'UL top 5', data: WS.ul5, borderColor: tok('--warn'), borderWidth: 2.5, pointRadius: 2},
  {label: 'GL #1', data: WS.gl1, borderColor: tok('--pvp'), borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0},
  {label: 'UL #1', data: WS.ul1, borderColor: tok('--warn'), borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0}]},
  options: {responsive: true, maintainAspectRatio: false, interaction: {mode: 'index', intersect: false}, plugins: {legend: {display: false}},
    scales: {x: ppx, y: ax(Object.assign({title: {display: true, text: 'battle forms'}}, tight([].concat(WS.gl5, WS.ul5, WS.gl1, WS.ul1), 2)))}, elements: {line: {tension: .2}}}});
new Chart(el('c_pp_cum'), {type: 'line', data: {labels: W.labels, datasets: [
  {label: 'stage bests beaten', data: W.cum.improved, borderColor: tok('--accent'), borderWidth: 2.5, stepped: true, pointRadius: 0},
  {label: 'new hundos', data: W.cum.hundos, borderColor: tok('--hundo'), borderWidth: 2.5, stepped: true, pointRadius: 0},
  {label: 'GL / UL #1 found', data: W.cum.pvp1, borderColor: tok('--pvp'), borderWidth: 2.5, stepped: true, pointRadius: 0},
  {label: 'evolve picks done', data: W.cum.picks, borderColor: tok('--shiny'), borderWidth: 2, stepped: true, pointRadius: 0}]},
  options: {responsive: true, maintainAspectRatio: false, interaction: {mode: 'index', intersect: false}, plugins: {legend: {display: false}},
    scales: {x: ppx, y: ax({beginAtZero: true, title: {display: true, text: 'running total'}})}}});
el('eta').innerHTML = [['89.5%', T.eta['89.5']], ['90%', T.eta['90']], ['91%', T.eta['91']]].map(([t, e]) => '<div><div class="t">reach ' + t + '</div><div class="w">' + etaTxt(e) + '</div></div>').join('');
el('ladder_note').textContent = 'Pace: ' + (T.slope >= 0 ? '+' : '') + T.slope.toFixed(2) + ' points per day over ' + T.n + ' days. The dashed line just continues that pace; the real ceiling is about ' + T.ceiling + '% — the average of the best copy you own at every stage — and only better catches move it.';
line('c_shiny', T.labels, [{data: T.shiny_iv, borderColor: tok('--shiny'), backgroundColor: tok('--shiny-soft'), fill: true, borderWidth: 2.5}], {x: ax(), y: pctAx()});
el('shiny_note').textContent = D.shiny.total + ' shinies (' + D.shiny.kept + ' kept), average ' + D.shiny.avg + '%. ' + D.shiny.hundos + ' shiny hundos. ' + D.shiny.stages + ' stages have a shiny; ' + D.shiny.stages_3star + ' of them a 3-star one, ' + D.shiny.stages_under50 + ' only an under-50% one.';
line('c_shiny3', T.labels, [{data: T.shiny3, borderColor: tok('--shiny'), backgroundColor: tok('--shiny-soft'), fill: true, borderWidth: 2.5}]);
line('c_hundo', T.labels, [{data: T.hundo_stages, borderColor: tok('--hundo'), backgroundColor: tok('--hundo-soft'), fill: true, borderWidth: 2.5}]);
new Chart(el('c_pvp_day'), {type: 'line', data: {labels: T.labels, datasets: [
  {label: 'GL', data: T.gl100, borderColor: tok('--pvp'), borderWidth: 2.5, pointRadius: 2.5, spanGaps: false},
  {label: 'UL', data: T.ul100, borderColor: tok('--warn'), borderWidth: 2.5, pointRadius: 2.5, spanGaps: false}]},
  options: {responsive: true, maintainAspectRatio: false, interaction: {mode: 'index', intersect: false}, plugins: {legend: {display: false}},
    scales: {x: ax(), y: ax(Object.assign({title: {display: true, text: 'battle forms'}}, tight([].concat(T.gl100, T.ul100), 3)))}, elements: {line: {tension: .2}}}});
{ const g = T.gl100.filter(v => v != null), u = T.ul100.filter(v => v != null);
  el('pvp_note').textContent = 'A form counts once, by the best kept copy\'s own-stage rank, at a stage that reaches the league (2,400+ UL / 1,400+ GL). Recorded since ' + (T.labels[T.gl100.findIndex(v => v != null)] || '?') + ': GL ' + g[0] + ' → ' + g[g.length - 1] + ', UL ' + u[0] + ' → ' + u[u.length - 1] + '.'; }
el('hundo_note').textContent = D.dex.hundo_stages + ' of ' + D.dex.stages + ' tracked stages have a hundo (' + (100 * D.dex.hundo_stages / D.dex.stages).toFixed(0) + '%).';
new Chart(el('c_bands'), {type: 'bar', data: {labels: D.bands.labels, datasets: [
  {label: 'Kept mons', data: D.bands.kept, backgroundColor: tok('--accent'), borderRadius: 3},
  {label: 'Shinies', data: D.bands.shiny, backgroundColor: tok('--shiny'), borderRadius: 3}]},
  options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'top'}}, scales: {x: ax({title: {display: true, text: 'IV %'}}), y: ax()}}});
new Chart(el('c_reasons'), {type: 'bar', data: {labels: D.reasons.map(r => r.name), datasets: [
  {label: 'Mons with this reason', data: D.reasons.map(r => r.mons), backgroundColor: tok('--accent'), borderRadius: 3},
  {label: 'Kept only for this', data: D.reasons.map(r => r.sole), backgroundColor: tok('--pvp'), borderRadius: 3}]},
  options: {indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'top'}}, scales: {x: ax(), y: {grid: {display: false}, ticks: {font: {size: 11}}}}}});
new Chart(el('c_sizes'), {type: 'doughnut', data: {labels: ['XXS', 'XS', 'M', 'XL', 'XXL'], datasets: [{data: D.sizes, backgroundColor: [tok('--pvp'), tok('--proj'), tok('--line'), tok('--shiny'), tok('--hundo')], borderWidth: 0}]},
  options: {responsive: true, maintainAspectRatio: false, cutout: '62%', plugins: {legend: {position: 'right'}}}});
el('size_note').textContent = D.sizes[4] + ' XXL in the bag; ' + k.xxl_winners + ' are showcase winners (≥ ' + k.xxl_min + ' points).';
const chips = (id, list) => el(id).innerHTML = list.map(x => '<span class="chip">' + x.name + '<b>' + x.times + '</b></span>').join('');
el('dex_note').textContent = D.dex.species_ever + ' species caught in your life; ' + D.dex.hundo_ever + ' have produced a hundo, ' + D.dex.never_hundo + ' never have. The number is how many times you have caught it — the most-caught ones are the best odds.';
chips('never_hundo', D.dex.never_hundo_top); chips('bag_no_hundo', D.dex.bag_no_hundo_top);
el('shiny_dex_note').textContent = D.dex.bag_no_shiny + ' species in the bag have no shiny copy (' + D.dex.shiny_hundo_ever + ' shiny hundos ever, per the Pokédex).';
chips('bag_no_shiny', D.dex.bag_no_shiny_top);
const maxIv = Math.max(...D.regions.map(r => r.avg_iv));
el('regions').innerHTML = '<tr><th>Region</th><th class="num">Mons</th><th class="num">Species</th><th class="num">Hundos</th><th class="num">Shinies</th><th>Avg IV (kept)</th><th>Species with a hundo ever</th></tr>' +
  D.regions.map(r => '<tr><td><b>' + r.name + '</b></td><td class="num">' + num(r.mons) + '</td><td class="num">' + r.species + '</td><td class="num hu">' + r.hundos + '</td><td class="num sh">' + r.shinies + '</td>' +
  '<td><span class="mini" style="width:' + (90 * r.avg_iv / maxIv).toFixed(0) + 'px"></span>' + r.avg_iv + '%</td>' +
  '<td><span class="mini" style="width:' + (90 * r.hundo_species / r.species).toFixed(0) + 'px;background:var(--hundo)"></span>' + r.hundo_species + ' / ' + r.species + '</td></tr>').join('');
el('showcase').innerHTML = '<tr><th>Species</th><th class="num">IV</th><th class="num">Height</th><th class="num">Weight</th><th class="num">Points</th></tr>' +
  D.showcase.map(s => '<tr><td>' + s.name + '</td><td class="num">' + s.iv + '%</td><td class="num">' + s.h.toFixed(2) + ' m</td><td class="num">' + s.w.toFixed(2) + ' kg</td><td class="num"><b>' + s.pts + '</b></td></tr>').join('');
el('show_note').textContent = 'The game\'s formula: height and weight against the species\' own size bounds, 800/150/50 weights, +178 for XXL.';
el('places').innerHTML = [['Catch place known', num(D.places.known) + ' of ' + num(k.bag)], ['Within 100 km of Atlanta', num(D.places.near_home)], ['Caught outside the US', num(D.places.abroad)],
  ['Farthest catches', D.places.far.map(f => f.name + ' ' + f.iv + '% (' + num(f.km) + ' km)').join(', ')]].map(([a, b]) => '<tr><td>' + a + '</td><td>' + b + '</td></tr>').join('');
if (D.today) { const t = D.today; el('today').innerHTML = [['Culls', t.culls], ['Caught', t.caught], ['Released', t.released], ['Evolved', t.evolved + ' <span class="d">(' + t.picks + ' were picks, ' + t.broken + ' wasted)</span>'], ['Stages improved', t.improved]]
  .map(([a, b]) => '<div class="kpi"><div class="eyebrow">' + a + '</div><div class="v" style="font-size:22px">' + b + '</div></div>').join(''); }
el('tags').innerHTML = D.tags.map(([n, c]) => '<span class="chip">' + n + '<b>' + c + '</b></span>').join('');
const PS = D.passes;
el('passes').innerHTML = '<tr><th>Pass</th><th class="num">Bag</th><th class="num">Free</th><th class="num">Pile</th><th class="num">Caught</th><th class="num">Released</th><th class="num">Evolved</th><th class="num">Ladder IV</th><th class="num">Δ</th><th class="num">Top-5 GL · UL</th><th>Tagged for Transfer</th></tr>' +
  PS.map(p => '<tr><td style="white-space:nowrap">' + p.ts.slice(5, 16).replace('-', '/') + (p.hundos ? ' <span class="hu">+' + p.hundos + ' hundo</span>' : '') + (p.improved ? ' <span class="up">' + p.improved + ' stage best</span>' : '') + '</td>' +
    '<td class="num">' + num(p.bag) + '</td><td class="num">' + num(p.free) + '</td><td class="num"><b>' + p.pile + '</b></td><td class="num">' + p.caught + '</td><td class="num">' + p.released + '</td>' +
    '<td class="num">' + p.evolved + (p.picks ? ' <span class="d">(' + p.picks + ' picks)</span>' : '') + '</td><td class="num">' + (p.ladder == null ? '-' : p.ladder + '%') + '</td>' +
    '<td class="num ' + dcls(p.ladder_d) + '">' + (p.ladder_d == null ? '-' : sgn(p.ladder_d, 1)) + '</td>' +
    '<td class="num">' + (p.gl5 == null ? '-' : p.gl5 + ' · ' + p.ul5) + (p.gl1 || p.ul1 ? ' <span class="up">+' + (p.gl1 + p.ul1) + ' #1</span>' : '') + '</td>' +
    '<td style="font-size:12px;color:var(--mut)">' + __PILE_CELL__ + '</td></tr>').join('');
const PR = PS.slice().reverse();
new Chart(el('c_passes'), {type: 'bar', data: {labels: PR.map(p => p.ts.slice(5, 16).replace('-', '/')), datasets: [
  {type: 'bar', label: 'Pile', data: PR.map(p => p.pile), backgroundColor: tok('--hundo'), borderRadius: 3, yAxisID: 'y'},
  {type: 'line', label: 'Free slots', data: PR.map(p => p.free), borderColor: tok('--accent'), backgroundColor: tok('--accent-soft'), fill: false, borderWidth: 2, pointRadius: 2, yAxisID: 'y2'}]},
  options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'top'}}, scales: {x: {grid: {display: false}, ticks: {font: {size: 10}, maxRotation: 60}},
    y: ax({title: {display: true, text: 'pile'}}), y2: {position: 'right', grid: {display: false}, ticks: {font: mono}, title: {display: true, text: 'free slots'}}}}});
</script>
'''
if bag_art is not None:
    doc = bag_art.assemble(TEMPLATE, DATA, art, pile_html, on=art is not None)     # on=False: every hook empty = the page as it was
else:                                                        # bag_art would not import: the page as it was before pictures
    doc = (TEMPLATE.replace('__ART_CSS__', '').replace('__PILE_CARD__', '').replace('__ART_JS__', '')
           .replace('__PILE_CELL__', 'p.pile_list').replace('__DATA__', json.dumps(DATA, ensure_ascii=False)))
out = os.path.join('system', 'analysis', 'collection_stats.html')
open(out, 'w', encoding='utf-8').write(doc)
print('wrote', out, '%d KB' % (len(doc) // 1024))
if art is not None:
    print(art.line([r['uid_hex'] for r in pile_rows]))
print('ladder %.1f%% (%+.1f since %s, %+.2f/day) | non-PvP keepers %.1f%% | hundos %d | shinies %d avg %.1f%% | never-hundo species %d | ETA 90%%: %s' % (
    cur, cur - (first_iv or cur), days[0], slope, DATA['kpi']['nonpvp_iv'], len(hundo), len(shiny), DATA['kpi']['shiny_iv'], len(never_hundo), DATA['trend']['eta']['90']))
