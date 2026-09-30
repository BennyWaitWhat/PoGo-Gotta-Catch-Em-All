"""Collection stats -> system/analysis/collection_stats.html (self-contained). Read-only. Run after a cull.

Everything is computed from pokemon.db (in_bag=1), policy_reasons.json, the tagsets, ladder_history.json and
size_line.showcase_points -- the same sources the cull uses, so the page agrees with the phone.
"""
import collections
import html
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
from costume_forms import is_costume_form
from pvp_iv_rule import pvid

con = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute('SELECT * FROM pokemon WHERE in_bag=1')]
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
today = time.strftime('%Y-%m-%d')
tday = [e for e in hist if e['ts'].startswith(today)]

P = lambda r: round((r['iv_total'] or 0) / 45 * 100)
N = len(rows)
kept = [r for r in rows if r['uid_hex'] not in pile]
shiny = [r for r in rows if r['fresh_shiny']]
shadow = [r for r in rows if r['fresh_alignment'] == 1]
purified = [r for r in rows if r['fresh_alignment'] == 2]
hundo = [r for r in rows if r['iv_total'] == 45]
nundo = [r for r in rows if r['iv_total'] == 0]
lucky = [r for r in rows if r['is_lucky']]
costume = [r for r in rows if (r['fresh_costume'] or 0) or is_costume_form(r['fresh_form']) or is_costume_form(r['form'])]
card = [r for r in rows if r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0)]
bg = [r for r in rows if r['fresh_natural_art_bg']]
dmax = [r for r in rows if ef.max_axis(r['fresh_bread_mode']) == 'dynamax']
gmax = [r for r in rows if ef.max_axis(r['fresh_bread_mode']) == 'gigantamax']
sizes = collections.Counter(r['pokemon_size_category'] or 0 for r in rows)
xxl = [r for r in rows if (r['pokemon_size_category'] or 0) == 5]
xxl_pts = sorted([((sl.showcase_points(r) or 0), r) for r in xxl], key=lambda x: -x[0])
ident = collections.defaultdict(list)
for r in rows:
    ident[pvid(r['species_name'], r['form'] or 0)].append(r)
species = {r['pokemon_id'] for r in rows}
lvl = collections.Counter()
for r in rows:
    l = r['level'] or 0
    lvl['L50+' if l >= 50 else 'L40-49.5' if l >= 40 else 'L30-39.5' if l >= 30 else 'L20-29.5' if l >= 20 else '<L20'] += 1
gl5 = [r for r in rows if r['gl_rank'] and r['gl_rank'] <= 5]
ul5 = [r for r in rows if r['ul_rank'] and r['ul_rank'] <= 5]
gl1 = [r for r in rows if r['gl_rank'] == 1]
ul1 = [r for r in rows if r['ul_rank'] == 1]
reason_ct = collections.Counter(x for v in reasons.values() for x in v if x != 'dex_only_copy')
sole = collections.Counter(next(iter(v - {'dex_only_copy'})) for v in reasons.values() if len(v - {'dex_only_copy'}) == 1)
tags = {}
for f in sorted(os.listdir(TD)):
    if f.endswith('.txt') and not f[0].isdigit():
        tags[f[:-4].replace('_', ' ')] = len(tag(f))
HOME = (33.749, -84.388)
def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))
located = [r for r in rows if r['lat'] is not None and r['lon'] is not None]
far = sorted(located, key=lambda r: -km(HOME, (r['lat'], r['lon'])))[:8]
near_home = sum(1 for r in located if km(HOME, (r['lat'], r['lon'])) < 100)
abroad = sum(1 for r in located if not (24.4 <= r['lat'] <= 49.4 and -125.0 <= r['lon'] <= -66.9) and not (18.8 <= r['lat'] <= 22.4 and -160.5 <= r['lon'] <= -154.6) and not (51.0 <= r['lat'] <= 71.5 and (r['lon'] <= -129.0 or r['lon'] >= 172.0)))
bread_lvls = collections.Counter(r['bread_max_level'] for r in rows if r['bread_max_level'])
bonus = [r for r in rows if (r['fresh_bonus_atk'] or 0) + (r['fresh_bonus_def'] or 0) + (r['fresh_bonus_sta'] or 0) > 0]
S = lambda k: sum(e.get(k, 0) or 0 for e in tday[1:])
first, last = (tday[0], tday[-1]) if tday else ({}, {})
caps = keep_config.CFG['caps']
sw = keep_config.showcase_weights()
plainish = [r for r in kept if not r['fresh_shiny'] and r['fresh_alignment'] != 1 and r['iv_total'] != 45]
mean = lambda xs: (sum(xs) / len(xs)) if xs else 0

def row(*cells):
    return '<tr>' + ''.join('<td>%s</td>' % html.escape(str(c)) for c in cells) + '</tr>'

def table(head, body_rows):
    return '<table><tr>%s</tr>%s</table>' % (''.join('<th>%s</th>' % html.escape(h) for h in head), ''.join(body_rows))

def sect(title, inner):
    return '<h2>%s</h2>%s' % (html.escape(title), inner)

parts = []
parts.append(sect('Storage', table(['', 'Count'], [
    row('Bag', '%d / %d (%d free)' % (N, cap_total, cap_total - N)),
    row('Kept by the rules', len(kept)), row('Tagged Transfer (release by hand)', len(pile)),
    row('Species', len(species)), row('Species + battle form (PvP identities)', len(ident)),
    row('Stages with a hundo', last.get('stages_with_hundo', '-')), row('Stages tracked', last.get('stages', '-'))])))
parts.append(sect('Trophies and specials', table(['Kind', 'Count', 'Cap / rule'], [
    row('Hundo (15/15/15)', len(hundo), 'all kept'), row('Nundo (0/0/0)', len(nundo), '1 per look, farthest from Atlanta'),
    row('Shiny', len(shiny), 'best %d per species+form, at most %d plain (Gyarados %d)' % (caps['shiny'], caps['shiny_plain'], keep_config.species_cap('shiny', 130, caps['shiny']))),
    row('Shadow', len(shadow), 'best ML + best GL + best UL per PvP identity'), row('Purified', len(purified), 'compete as plain'),
    row('Lucky', len(lucky), '-'), row('Costume / costume form', len(costume), 'best %d per variant (Pikachu %d)' % (caps['cosmetic'], keep_config.species_cap('cosmetic', 25, caps['cosmetic']))),
    row('Location card', len(card), 'best %d per card' % caps['location_card']), row('Natural-art background', len(bg), 'cosmetic cap'),
    row('Dynamax', len(dmax), 'best %d' % caps['dynamax']), row('Gigantamax', len(gmax), 'best %d' % caps['gigantamax']),
    row('Legacy-move holders', tags.get('Legacy Moves', 0), 'kept (client game master decides)'), row('Adventure Effect (knows the move)', tags.get('Adventure Effect', 0), 'kept'),
    row('Item-boosted IVs', len(bonus), ', '.join('%s +%d/+%d/+%d' % (r['species_name'], r['fresh_bonus_atk'] or 0, r['fresh_bonus_def'] or 0, r['fresh_bonus_sta'] or 0) for r in bonus))])))
parts.append(sect('Size and showcases', table(['', 'Count'], [
    row('XXS / XS / M / XL / XXL', '%d / %d / %d / %d / %d' % (sizes[1], sizes[2], sizes[3], sizes[4], sizes[5])),
    row('XXL tagged as showcase winners', '%d (XXL, >= %d pts, best %d per species)' % (tags.get('XXL', 0), int(sw['min_points']), caps['xxl'])),
    row('XXL points: min / median / max', '%d / %d / %d' % (min(p for p, _ in xxl_pts), xxl_pts[len(xxl_pts) // 2][0], max(p for p, _ in xxl_pts)) if xxl_pts else '-'),
    row('Max-move levels 1 / 2 / 3', '%d / %d / %d' % (bread_lvls.get(1, 0), bread_lvls.get(2, 0), bread_lvls.get(3, 0)))]))
    + '<p class="mut">Top 10 showcase entries you own</p>' + table(['Species', 'IV', 'Height', 'Weight', 'Points'],
    [row(r['species_name'], '%d%%' % P(r), '%.2f m' % (r['height_m'] or 0), '%.2f kg' % (r['weight_kg'] or 0), p) for p, r in xxl_pts[:10]]))
parts.append(sect('PvP', table(['', 'Count'], [
    row('Great League rank 1', len(gl1)), row('Great League rank 1-5', len(gl5)), row('Ultra League rank 1', len(ul1)), row('Ultra League rank 1-5', len(ul5)),
    row('Best GL / Best UL / Best ML tags', '%d / %d / %d' % (tags.get('Best GL', 0), tags.get('Best UL', 0), tags.get('Best ML', 0))),
    row('0-15-15 trophy spreads', tags.get('0-15-15', 0))])))
parts.append(sect('Ladder quality', table(['', 'Value'], [
    row('Average IV of plain slot holders', '%.1f%%' % (mean([P(r) for r in plainish if 'variant_floor' in reasons.get(r['uid_hex'], ())]))),
    row('Average IV of the best copy per stage', '%s%%' % last.get('best_per_stage_mean_iv', '-')),
    row('Average shiny IV', '%.1f%%' % mean([P(r) for r in shiny])), row('3-star shiny stages', '%s of %s' % (last.get('shiny_stages_3star', '-'), last.get('shiny_stages', '-'))),
    row('Level bands', ', '.join('%s: %d' % kv for kv in sorted(lvl.items())))])))

# ---------------------------------------------------------------- analyst sections (user 2026-09-23: "iv of non pvp ones
# avg and how its been progressing and going to progress. ivs for shinies, etc, missing hundos etc.")
def svg_line(series, ymin=None, ymax=None, fmt='%.1f'):
    """series: [(label, value)] -> a small inline SVG line chart with min/max labels. No libraries."""
    vals = [v for _, v in series if v is not None]
    if len(vals) < 2:
        return '<p class="mut">not enough history yet</p>'
    lo = min(vals) if ymin is None else ymin
    hi = max(vals) if ymax is None else ymax
    if hi - lo < 1e-9:
        hi = lo + 1
    W, H, L, B = 640, 160, 44, 22
    pts = []
    for i, (lab, v) in enumerate(series):
        if v is None:
            continue
        x = L + (W - L - 8) * i / max(1, len(series) - 1)
        y = 8 + (H - B - 8) * (1 - (v - lo) / (hi - lo))
        pts.append((x, y, lab, v))
    path = ' '.join('%s%.1f,%.1f' % ('M' if i == 0 else 'L', x, y) for i, (x, y, _, _) in enumerate(pts))
    dots = ''.join('<circle cx="%.1f" cy="%.1f" r="2.5" fill="var(--head)"><title>%s: %s</title></circle>' % (x, y, html.escape(lab), fmt % v) for x, y, lab, v in pts)
    labels = '<text x="2" y="14" class="ax">%s</text><text x="2" y="%d" class="ax">%s</text>' % (fmt % hi, H - B, fmt % lo)
    xl = '<text x="%d" y="%d" class="ax">%s</text><text x="%d" y="%d" class="ax" text-anchor="end">%s</text>' % (L, H - 4, html.escape(series[0][0]), W - 8, H - 4, html.escape(series[-1][0]))
    return '<svg viewBox="0 0 %d %d" width="100%%" style="max-width:640px;display:block"><path d="%s" fill="none" stroke="var(--head)" stroke-width="2"/>%s%s%s</svg>' % (W, H, path, dots, labels, xl)

def trend(series):
    """least-squares slope per day over (day_index, value) -> (slope, intercept, n) or None."""
    pts = [(i, v) for i, (_, v) in enumerate(series) if v is not None]
    n = len(pts)
    if n < 3:
        return None
    mx = sum(i for i, _ in pts) / n
    my = sum(v for _, v in pts) / n
    sxx = sum((i - mx) ** 2 for i, _ in pts)
    if sxx == 0:
        return None
    slope = sum((i - mx) * (v - my) for i, v in pts) / sxx
    return slope, my - slope * mx, n

bydays = collections.OrderedDict()
for e in hist:
    bydays[e['ts'][:10]] = e                       # last pass of each day
days = list(bydays.keys())
ser = lambda k: [(d[5:], bydays[d].get(k)) for d in days]
pvp_reasons = {'pvp_rank', 'gl_iv', 'ul_iv', 'pvp_spread', 'pvp_best_gl', 'pvp_best_ul', 'pvp_best_ml', 'shadow_best'}
nonpvp = [r for r in kept if r['iv_total'] != 45 and not r['fresh_shiny'] and r['fresh_alignment'] != 1
          and 'variant_floor' in reasons.get(r['uid_hex'], set()) and not (reasons.get(r['uid_hex'], set()) & pvp_reasons)]
nonpvp_iv = mean([P(r) for r in nonpvp])
allkept_iv = mean([P(r) for r in kept if r['fresh_alignment'] != 1])
res_t = trend(ser('resident_mean_iv'))
proj = ''
if res_t:
    slope, icpt, n = res_t
    cur = bydays[days[-1]].get('resident_mean_iv') or 0
    def eta(target):
        if slope <= 0 or target <= cur:
            return '-'
        d = (target - cur) / slope
        return '%d days (%s)' % (round(d), time.strftime('%b %d', time.localtime(time.time() + d * 86400)))
    ceiling = bydays[days[-1]].get('best_per_stage_mean_iv') or 0
    proj = table(['Projection at the last %d days pace (%+.2f pts/day)' % (n, slope), 'ETA'], [
        row('89.5%', eta(89.5)), row('90%', eta(90.0)), row('91%', eta(91.0)),
        row('Ceiling', 'about %.1f%% -- the average of the BEST copy at every stage; the ladder cannot pass it without better catches' % ceiling)]) + \
        '<p class="mut">Extrapolation from %d days of history; the average moves only when a better copy replaces a slot holder (catches, evolutions, releases).</p>' % n
ivh = collections.Counter()
for r in kept:
    ivh[min(9, P(r) // 10)] += 1
ivh_s = collections.Counter(min(9, P(r) // 10) for r in shiny)
bands = ['0-9', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80-89', '90-100']
shiny_kept = [r for r in shiny if r['uid_hex'] not in pile]
sh_stage_best = collections.defaultdict(int)
for r in shiny:
    k = ef.stage_of(pvid(r['species_name'], r['form'] or 0), r['form'] or 0)
    sh_stage_best[k] = max(sh_stage_best[k], P(r))
parts.append(sect('IV of the non-PvP keepers (the plain ladder)', table(['', 'Now'], [
    row('Plain ladder keepers (no hundo, no shiny, no shadow, no PvP reason)', len(nonpvp)),
    row('Their average IV', '%.1f%%' % nonpvp_iv),
    row('Average IV of every kept non-shadow mon', '%.1f%%' % allkept_iv),
    row('Ladder slot-holder average (the daily series below)', '%s%%' % bydays[days[-1]].get('resident_mean_iv'))])
    + '<p class="mut">Slot-holder average IV by day</p>' + svg_line(ser('resident_mean_iv'), fmt='%.1f')
    + '<p class="mut">Best copy per stage, average IV by day</p>' + svg_line(ser('best_per_stage_mean_iv'), fmt='%.1f') + proj))
parts.append(sect('Shinies', table(['', 'Value'], [
    row('Shinies in bag / kept', '%d / %d' % (len(shiny), len(shiny_kept))),
    row('Average shiny IV (all / kept)', '%.1f%% / %.1f%%' % (mean([P(r) for r in shiny]), mean([P(r) for r in shiny_kept]))),
    row('Shiny hundos', sum(1 for r in shiny if r['iv_total'] == 45)),
    row('Stages with a shiny', len(sh_stage_best)), row('...whose best shiny is 3-star (>= 82%)', sum(1 for v in sh_stage_best.values() if v >= 82)),
    row('...whose best shiny is under 50%', sum(1 for v in sh_stage_best.values() if v < 50))])
    + '<p class="mut">Average shiny IV by day</p>' + svg_line(ser('shiny_mean_iv'), fmt='%.1f')
    + '<p class="mut">3-star shiny stages by day</p>' + svg_line([(d[5:], (bydays[d].get('shiny_stages_3star') or 0)) for d in days], fmt='%.0f')
    + '<p class="mut">IV bands: kept mons vs shinies</p>' + table(['IV band', 'Kept mons', 'Shinies'], [row(bands[i], ivh.get(i, 0), ivh_s.get(i, 0)) for i in range(10)])))
# ---- missing hundos / shinies, from the POKEDEX (lifetime) and the bag
dex = json.load(open('pokedex_hundos_live.json', encoding='utf-8'))
ents = {e['pid']: e for e in dex.get('entries', [])}
names = {}
for r in rows:
    names.setdefault(r['pokemon_id'], r['species_name'])
ever_hundo = {pid for pid, e in ents.items() if e.get('hundo')}
never_hundo = sorted((e.get('times', 0), pid) for pid, e in ents.items() if not e.get('hundo'))
bag_hundo = {r['pokemon_id'] for r in hundo}
bag_no_hundo = sorted({r['pokemon_id'] for r in rows} - bag_hundo)
bag_shiny = {r['pokemon_id'] for r in shiny}
bag_no_shiny = sorted({r['pokemon_id'] for r in rows} - bag_shiny)
times = {pid: e.get('times', 0) for pid, e in ents.items()}
nm = lambda pid: names.get(pid, '#%d' % pid)
parts.append(sect('Missing hundos and shinies', table(['', 'Count', 'Most-caught examples (catches)'], [
    row('Species ever caught (Pokedex)', len(ents), ''),
    row('Species with a hundo EVER (Pokedex flag)', len(ever_hundo), ''),
    row('Species caught but NEVER a hundo', len(never_hundo), ', '.join('%s (%d)' % (nm(p), t) for t, p in sorted(never_hundo, reverse=True)[:15])),
    row('Species in bag with no hundo IN THE BAG now', len(bag_no_hundo), ', '.join('%s (%d)' % (nm(p), times.get(p, 0)) for p in sorted(bag_no_hundo, key=lambda p: -times.get(p, 0))[:15])),
    row('Shiny hundos ever (Pokedex flag)', sum(1 for e in ents.values() if e.get('shinyHundo')), ''),
    row('Species in bag with no shiny in the bag', len(bag_no_shiny), ', '.join('%s (%d)' % (nm(p), times.get(p, 0)) for p in sorted(bag_no_shiny, key=lambda p: -times.get(p, 0))[:15])),
    row('Stages with a hundo (today / tracked)', '%s / %s' % (bydays[days[-1]].get('stages_with_hundo'), bydays[days[-1]].get('stages')), '')])
    + '<p class="mut">Stages with a hundo, by day</p>' + svg_line([(d[5:], bydays[d].get('stages_with_hundo')) for d in days], fmt='%.0f')))
# ---- by region
GENS = [(1, 151, 'Kanto'), (152, 251, 'Johto'), (252, 386, 'Hoenn'), (387, 493, 'Sinnoh'), (494, 649, 'Unova'), (650, 721, 'Kalos'), (722, 809, 'Alola'), (810, 905, 'Galar'), (906, 1025, 'Paldea')]
grows = []
for a, b, g in GENS:
    inb = [r for r in rows if a <= (r['pokemon_id'] or 0) <= b]
    if not inb:
        continue
    sp = {r['pokemon_id'] for r in inb}
    with_h = len([p for p in sp if p in ever_hundo])
    grows.append(row(g, len(inb), len(sp), sum(1 for r in inb if r['iv_total'] == 45), sum(1 for r in inb if r['fresh_shiny']),
                     '%.1f%%' % mean([P(r) for r in inb if r['uid_hex'] not in pile and r['fresh_alignment'] != 1]), with_h, len(sp) - with_h))
parts.append(sect('By region', table(['Region', 'Mons', 'Species', 'Hundos', 'Shinies', 'Avg IV (kept)', 'Species w/ hundo ever', 'Species never hundo'], grows)))

parts.append(sect('Why things are kept (a mon can have several reasons)', table(['Reason', 'Mons', 'Sole reason for'],
    [row(k, reason_ct[k], sole.get(k, 0)) for k, _ in reason_ct.most_common()])))
parts.append(sect('Tags on the phone', table(['Tag', 'Members'], [row(k, v) for k, v in sorted(tags.items(), key=lambda kv: -kv[1])])))
parts.append(sect('Where they were caught', table(['', 'Value'], [
    row('Catch location known', '%d of %d' % (len(located), N)), row('Within 100 km of Atlanta', near_home), row('Caught outside the US', abroad),
    row('Farthest catches', '; '.join('%s %d%% (%.0f km)' % (r['species_name'], P(r), km(HOME, (r['lat'], r['lon']))) for r in far))])))
if tday:
    parts.append(sect('Today (%d culls, %s -> %s)' % (len(tday), first['ts'][11:], last['ts'][11:]), table(['', 'Value'], [
        row('Caught', S('caught')), row('Released', S('released')), row('Evolved', '%d (%d were Evolve picks, %d broken)' % (S('evolved'), S('promises_kept'), S('promises_broken'))),
        row('Stages whose best copy improved', S('stage_best_improved')), row('New hundos', S('new_hundos')),
        row('Slot-holder average IV', '%s%% -> %s%%' % (first.get('resident_mean_iv', '-'), last.get('resident_mean_iv', '-')))])))
css = """:root{--bg:#ffffff;--fg:#111827;--mut:#5b6472;--head:#1a5fb4;--line:#e5e7eb}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0f1115;--fg:#e6e6e6;--mut:#9aa4b2;--head:#9ecbff;--line:#262a33}}
:root[data-theme="dark"]{--bg:#0f1115;--fg:#e6e6e6;--mut:#9aa4b2;--head:#9ecbff;--line:#262a33}
body{font-family:system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:24px 16px;max-width:900px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 6px;color:var(--head);text-transform:uppercase;letter-spacing:.04em}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600}.mut{color:var(--mut);font-size:13px;margin:8px 0 2px}.ax{font-size:11px;fill:var(--mut)}"""
doc = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Collection Stats</title><style>%s</style></head><body><h1>Collection stats</h1><p class="mut">%s -- from the last scan; every number is what the cull itself uses.</p>%s</body></html>' % (css, time.strftime('%Y-%m-%d %H:%M'), ''.join(parts))
out = os.path.join('system', 'analysis', 'collection_stats.html')
open(out, 'w', encoding='utf-8').write(doc)
print('wrote', out, '%d KB' % (len(doc) // 1024))
print('bag %d/%d | kept %d | pile %d | species %d | identities %d | hundo %d nundo %d shiny %d shadow %d lucky %d | XXL %d (winners %d) | GL1-5 %d UL1-5 %d' % (
    N, cap_total, len(kept), len(pile), len(species), len(ident), len(hundo), len(nundo), len(shiny), len(shadow), len(lucky), len(xxl), tags.get('XXL', 0), len(gl5), len(ul5)))
