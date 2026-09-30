"""WORST PVP RANKINGS -- which KINDS of Pokemon in the bag are PvP dead weight, per league (user 2026-09-24: "Do an
analyse on which kinda of pokemon of that WORST PVP rankings for gl and ul and ml").

Rank here is the project's own per-STAGE IV-spread rank (pvp_iv_rule / rank_cache): 1 = the best of the 4,096 IV
spreads of that species+form at the league cap (level-50 ceiling), 4096 = the worst. ML rank is the stat product at
level 50, so it is the IV ladder; GL/UL rank rewards low attack / high bulk under the CP cap. A species that cannot
come near a league's cap has no usable copy there at all -- that is reported as 'cannot reach'.

Reads pokemon.db (in_bag=1), system/analysis/policy_reasons.json, pvpoke_gamemaster.json (viability). DB-only.
Writes system/analysis/pvp_worst.html and prints the summary.   python pvp_worst_report.py
"""
import collections
import html
import json
import os
import sqlite3
import sys
import time

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import keep_config
from pvp_iv_rule import maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN, chain_stage_ranks, pvid

BAD = 1000                       # a spread ranked past this is 'bad' for that league (top ~25% of the 4,096 is 'usable')
DEAD = 2048                      # bottom half

rs = {k: set(v) for k, v in json.load(open('system/analysis/policy_reasons.json', encoding='utf-8')).items() if isinstance(v, list)}
pile = set(open('system/analysis/tagsets/Transfer.txt').read().split())
c = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')]
GM = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in GM['pokemon']}
cap_total = None
try:
    cap_total = json.load(open('player_state.json', encoding='utf-8')).get('max_pokemon_storage')
except Exception:
    pass

BUCKET_ORDER = [('hundo', 'Hundo'), ('nundo', 'Nundo'), ('pvp_rank', 'GL/UL rank 1-5'), ('gl_iv', 'GL spread'), ('ul_iv', 'UL spread'),
                ('pvp_spread', 'Named spread'), ('pvp_best_gl', 'Best GL'), ('pvp_best_ul', 'Best UL'), ('pvp_best_ml', 'Best ML'),
                ('shadow_best', 'Shadow best'), ('adventure_effect', 'Adventure Effect'), ('mighty', 'Mighty'), ('protected', 'Protected'),
                ('favorite', 'Favorite'), ('origin', 'Traded / lucky'), ('legacy', 'Legacy moves'), ('rarity', 'Legendary / mythical'),
                ('xxl', 'XXL showcase'), ('location_card', 'Location card / background'), ('shiny', 'Shiny'), ('shiny_ladder', 'Shiny ladder'),
                ('evolve_1', 'Evolve pick'), ('evolve_2', 'Evolve pick (x2)'), ('variant_floor', 'Plain / costume / Max ladder'),
                ('dex_only_copy', 'Last copy of a form')]
PVP_REASONS = {'hundo', 'nundo', 'pvp_rank', 'gl_iv', 'ul_iv', 'pvp_spread', 'pvp_best_gl', 'pvp_best_ul', 'pvp_best_ml', 'shadow_best'}


def bucket(u):
    """The FIRST keep bucket in LAW order that applies (a mon can have several reasons)."""
    v = rs.get(u) or set()
    for k, name in BUCKET_ORDER:
        if k in v:
            return name
    return 'Transfer pile' if u in pile else 'unlabelled'


def can_reach(r, league):
    """Can ANY stage this copy can become come within the viability margin of the league cap? (species-level)"""
    cap = GL_CAP if league == 'gl' else UL_CAP
    try:
        for st, _rk in chain_stage_ranks(r, league):
            if maxcp(st, BS) > cap + VIABILITY_MARGIN:
                return True
    except Exception:
        return None
    return False


kept = [r for r in rows if r['uid_hex'] in rs]
n_all, n_kept = len(rows), len(kept)
L = {'gl': 'gl_rank', 'ul': 'ul_rank', 'ml': 'ml_rank'}
stats = {}
for lg, col in L.items():
    vals = [r[col] for r in kept if r[col] is not None]
    bad = sum(1 for v in vals if v > BAD)
    dead = sum(1 for v in vals if v > DEAD)
    unr = 0
    if lg != 'ml':
        unr = sum(1 for r in kept if can_reach(r, lg) is False)
    stats[lg] = {'ranked': len(vals), 'null': n_kept - len(vals), 'bad': bad, 'dead': dead, 'cannot_reach': unr,
                 'median': sorted(vals)[len(vals) // 2] if vals else None}

# all-three-bad: kept copies with no PvP value in any league
def worst_rank(r):
    return max((r[col] or 0) for col in L.values())


def all_bad(r, thr=BAD):
    return all((r[col] or 0) > thr for col in L.values())


dead_all = [r for r in kept if all_bad(r)]
dead_all_deep = [r for r in kept if all_bad(r, DEAD)]

# by BUCKET: how much of each keep bucket is PvP-dead (all three leagues past BAD)
by_bucket = collections.OrderedDict()
for r in kept:
    b = bucket(r['uid_hex'])
    d = by_bucket.setdefault(b, {'kept': 0, 'dead': 0, 'deep': 0, 'iv': []})
    d['kept'] += 1
    d['iv'].append(r['iv_total'] or 0)
    if all_bad(r):
        d['dead'] += 1
    if all_bad(r, DEAD):
        d['deep'] += 1
bucket_rows = sorted(((b, d['kept'], d['dead'], d['deep'], round(sum(d['iv']) / len(d['iv']) * 100 / 45, 1)) for b, d in by_bucket.items()), key=lambda x: -x[2])

# by SPECIES (kind): species whose kept copies are PvP-dead -- weight = slots
by_sp = collections.defaultdict(lambda: {'kept': 0, 'dead': 0, 'best': {'gl': 99999, 'ul': 99999, 'ml': 99999}, 'reach': {}, 'buckets': collections.Counter(), 'iv': []})
for r in kept:
    d = by_sp[r['species_name']]
    d['kept'] += 1
    d['iv'].append(r['iv_total'] or 0)
    d['buckets'][bucket(r['uid_hex'])] += 1
    for lg, col in L.items():
        if r[col] is not None:
            d['best'][lg] = min(d['best'][lg], r[col])
    if all_bad(r):
        d['dead'] += 1
    for lg in ('gl', 'ul'):
        if lg not in d['reach']:
            d['reach'][lg] = can_reach(r, lg)
species_rows = []
for sp, d in by_sp.items():
    species_rows.append({'species': sp, 'kept': d['kept'], 'dead': d['dead'], 'best_gl': d['best']['gl'], 'best_ul': d['best']['ul'], 'best_ml': d['best']['ml'],
                         'reach_gl': d['reach'].get('gl'), 'reach_ul': d['reach'].get('ul'),
                         'iv': round(sum(d['iv']) / len(d['iv']) * 100 / 45, 1), 'why': ', '.join('%s %d' % (k, v) for k, v in d['buckets'].most_common(3))})
worst_species = sorted([s for s in species_rows if s['dead'] >= 2], key=lambda s: (-s['dead'], -s['kept']))[:40]
unreachable_both = sorted([s for s in species_rows if s['reach_gl'] is False and s['reach_ul'] is False], key=lambda s: -s['kept'])

# per-league worst kept copies (own-stage rank), excluding the PvP buckets themselves
per_league_worst = {}
for lg, col in L.items():
    cand = [r for r in kept if r[col] is not None and not (rs.get(r['uid_hex']) & PVP_REASONS)]
    cand.sort(key=lambda r: -r[col])
    per_league_worst[lg] = [{'species': r['species_name'], 'iv': round((r['iv_total'] or 0) * 100 / 45), 'cp': r['cp'], 'rank': r[col], 'bucket': bucket(r['uid_hex']),
                             'shiny': bool(r['fresh_shiny'])} for r in cand[:15]]

# rank histograms per league (kept, 8 bins of 512)
hist = {lg: [0] * 8 for lg in L}
for r in kept:
    for lg, col in L.items():
        v = r[col]
        if v:
            hist[lg][min(7, (v - 1) // 512)] += 1

# how many slots are 'PvP-dead AND kept only by a cosmetic/collection rule' -- the honest 'could go' number
COSMETIC = {'shiny', 'shiny_ladder', 'xxl', 'location_card', 'rarity', 'legacy', 'variant_floor', 'dex_only_copy', 'evolve_1', 'evolve_2', 'origin', 'favorite', 'protected', 'adventure_effect', 'mighty'}
dead_cosmetic = collections.Counter()
for r in dead_all:
    v = rs.get(r['uid_hex']) or set()
    if not (v & PVP_REASONS):
        dead_cosmetic[bucket(r['uid_hex'])] += 1

summary = {
    'generated': time.strftime('%Y-%m-%d %H:%M'), 'bag': n_all, 'kept': n_kept, 'cap': cap_total, 'BAD': BAD, 'DEAD': DEAD,
    'leagues': stats, 'dead_all': len(dead_all), 'dead_all_deep': len(dead_all_deep), 'dead_cosmetic': dict(dead_cosmetic),
    'dead_cosmetic_total': sum(dead_cosmetic.values()),
    'buckets': bucket_rows, 'worst_species': worst_species, 'unreachable_both': unreachable_both[:40], 'per_league_worst': per_league_worst, 'hist': hist,
    'unreachable_both_total_slots': sum(s['kept'] for s in unreachable_both),
}
json.dump(summary, open(os.path.join('system', 'analysis', 'pvp_worst.json'), 'w', encoding='utf-8'), indent=1)

# ---------------------------------------------------------------- page
CSS = """
:root{--bg:#f3f6f5;--surface:#ffffff;--ink:#16211f;--mut:#5f6f6b;--line:#dfe6e3;--accent:#0f7c7a;--accent-soft:#d6ecea;
--gl:#3a6fb0;--ul:#7a4fb0;--ml:#b0563a;--bad:#c8455e;--bad-soft:#f8dbe1;--ok:#2f8f5b;--warn:#b7791f;
--font-display:'Sora',system-ui,sans-serif;--font-body:'IBM Plex Sans',system-ui,sans-serif;--font-mono:'IBM Plex Mono',ui-monospace,Menlo,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0f1615;--surface:#172020;--ink:#e6eeec;--mut:#94a5a1;--line:#263331;
--accent:#3fb8b2;--accent-soft:#163533;--gl:#7aa6e0;--ul:#b08fe0;--ml:#e08f7a;--bad:#ea6f86;--bad-soft:#43202a;--ok:#5fc78b;--warn:#e0a33a}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0f1615;--surface:#172020;--ink:#e6eeec;--mut:#94a5a1;--line:#263331;
--accent:#3fb8b2;--accent-soft:#163533;--gl:#7aa6e0;--ul:#b08fe0;--ml:#e08f7a;--bad:#ea6f86;--bad-soft:#43202a;--ok:#5fc78b;--warn:#e0a33a}
body{background:var(--bg);color:var(--ink);font-family:var(--font-body);font-size:14px;line-height:1.45;margin:0}
.wrap{max-width:1080px;margin:0 auto;padding-block:22px 40px;padding-inline:16px}
h1{font-family:var(--font-display);font-size:26px;margin:0;letter-spacing:-.01em;text-wrap:balance}
.sub{color:var(--mut);margin:4px 0 18px;font-size:13px;max-width:70ch}
h2{font-family:var(--font-display);font-size:15px;margin:0 0 10px}
.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:18px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:4px}
.kpi .v{font-family:var(--font-mono);font-size:26px;font-weight:500;line-height:1.1;font-variant-numeric:tabular-nums}
.kpi .d{font-size:12px;color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-bottom:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;min-width:0}
.card.wide{grid-column:1/-1}
.chart{position:relative;height:230px;width:100%}
.note{color:var(--mut);font-size:12px;margin:8px 0 0;max-width:80ch}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}th{color:var(--mut);font-weight:600;font-size:12px}
td.num,th.num{text-align:right}.tbl{overflow-x:auto}
.bad{color:var(--bad);font-weight:600}.ok{color:var(--ok)}.mut{color:var(--mut)}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--bad);vertical-align:middle;margin-right:6px}
.pill{display:inline-block;border-radius:999px;padding:1px 8px;font-size:11px;background:var(--bad-soft);color:var(--bad);font-weight:600}
.pill.ok{background:var(--accent-soft);color:var(--accent)}
"""


def esc(x):
    return html.escape(str(x))


def rank_cell(v, reach=None):
    if reach is False:
        return '<td class="num mut">cannot reach</td>'
    if v is None or v >= 99999:
        return '<td class="num mut">-</td>'
    cls = 'bad' if v > BAD else ('ok' if v <= 100 else '')
    return '<td class="num %s">%s</td>' % (cls, v)


lg_name = {'gl': 'Great', 'ul': 'Ultra', 'ml': 'Master'}
kp = []
for lg in ('gl', 'ul', 'ml'):
    s = stats[lg]
    kp.append('<div class="kpi"><div class="eyebrow">%s League</div><div class="v">%d</div><div class="d">kept copies ranked past %d of 4,096%s</div></div>'
              % (lg_name[lg], s['bad'], BAD, ('; %d cannot reach the cap at any stage' % s['cannot_reach']) if lg != 'ml' else ''))
kp.append('<div class="kpi"><div class="eyebrow">All three leagues</div><div class="v">%d</div><div class="d">kept copies bad in GL, UL and ML at once (%d in the bottom half everywhere)</div></div>' % (len(dead_all), len(dead_all_deep)))
kp.append('<div class="kpi"><div class="eyebrow">Kept by a non-PvP rule only</div><div class="v">%d</div><div class="d">of those %d -- what PvP would call dead weight, held for collection reasons</div></div>' % (summary['dead_cosmetic_total'], len(dead_all)))

bucket_html = ''.join('<tr><td>%s</td><td class="num">%d</td><td class="num %s">%d</td><td class="num">%d</td><td class="num">%s%%</td><td><span class="bar" style="width:%dpx"></span>%d%%</td></tr>'
                      % (esc(b), k, 'bad' if d else '', d, deep, iv, int(120 * d / max(1, k)), round(100 * d / max(1, k))) for b, k, d, deep, iv in bucket_rows)
sp_html = ''.join('<tr><td>%s</td><td class="num">%d</td><td class="num bad">%d</td>%s%s%s<td class="num">%s%%</td><td class="mut">%s</td></tr>'
                  % (esc(s['species']), s['kept'], s['dead'], rank_cell(s['best_gl'], s['reach_gl']), rank_cell(s['best_ul'], s['reach_ul']), rank_cell(s['best_ml']), s['iv'], esc(s['why'])) for s in worst_species)
unr_html = ''.join('<tr><td>%s</td><td class="num">%d</td>%s<td class="num">%s%%</td><td class="mut">%s</td></tr>'
                   % (esc(s['species']), s['kept'], rank_cell(s['best_ml']), s['iv'], esc(s['why'])) for s in unreachable_both[:40])
worst_html = {lg: ''.join('<tr><td>%s%s</td><td class="num">%d%%</td><td class="num">%s</td><td class="num bad">%d</td><td class="mut">%s</td></tr>'
                          % (esc(w['species']), ' <span class="pill">shiny</span>' if w['shiny'] else '', w['iv'], w['cp'], w['rank'], esc(w['bucket'])) for w in per_league_worst[lg]) for lg in L}
dc_html = ''.join('<tr><td>%s</td><td class="num bad">%d</td></tr>' % (esc(k), v) for k, v in sorted(dead_cosmetic.items(), key=lambda kv: -kv[1]))

page = """<title>PvP Dead Weight</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap">
<style>%(css)s</style>
<div class="wrap">
  <h1>PvP Dead Weight</h1>
  <p class="sub">Which kinds of Pokemon in the bag have the worst Great, Ultra and Master League rankings -- and what keeps them. Rank = this copy's IV spread among the 4,096 possible for its species and form at the league's cap (1 best, 4096 worst; Master League = the IV ladder). "Bad" = past %(bad)d; "bottom half" = past %(dead)d. Bag %(bag)s, kept %(kept)s, generated %(gen)s.</p>
  <div class="kpis">%(kpis)s</div>
  <div class="grid">
    <div class="card wide"><div class="eyebrow">Rank spread</div><h2>Where the kept copies rank, per league</h2><div class="chart"><canvas id="c_hist"></canvas></div>
      <p class="note">Each bar is a band of 512 ranks. Master League is the IV ladder, so its shape is the bag's IV shape; Great and Ultra reward low-attack spreads, so a hundo often ranks in the middle there.</p></div>
    <div class="card wide"><div class="eyebrow">By keep bucket</div><h2>How much of each bucket is PvP-dead in all three leagues</h2>
      <div class="tbl"><table><tr><th>Bucket (first that applies, LAW order)</th><th class="num">Kept</th><th class="num">Dead in all 3</th><th class="num">Bottom half in all 3</th><th class="num">Avg IV</th><th>Share dead</th></tr>%(buckets)s</table></div>
      <p class="note">Collection buckets are SUPPOSED to hold PvP-dead copies -- a shiny or a card is kept for what it is, not for battle. The point of this table is the size of each pool.</p></div>
    <div class="card"><div class="eyebrow">Dead weight, by the rule that keeps it</div><h2>Bad in all three leagues, and kept by a non-PvP rule only</h2><div class="tbl"><table><tr><th>Rule</th><th class="num">Copies</th></tr>%(dc)s</table></div></div>
    <div class="card"><div class="eyebrow">Species that can enter neither Great nor Ultra</div><h2>%(unr_n)d species, %(unr_slots)d kept copies</h2><div class="tbl"><table><tr><th>Species</th><th class="num">Kept</th><th class="num">Best ML</th><th class="num">Avg IV</th><th>Kept by</th></tr>%(unr)s</table></div>
      <p class="note">No stage of these lines gets within the viability margin of 1,500 / 2,500 CP -- their only PvP league is Master, where rank is the IV ladder.</p></div>
    <div class="card wide"><div class="eyebrow">Worst kinds</div><h2>Species with the most PvP-dead kept copies</h2>
      <div class="tbl"><table><tr><th>Species</th><th class="num">Kept</th><th class="num">Dead in all 3</th><th class="num">Best GL</th><th class="num">Best UL</th><th class="num">Best ML</th><th class="num">Avg IV</th><th>Kept by</th></tr>%(species)s</table></div></div>
    <div class="card"><div class="eyebrow">Great League</div><h2>Worst-ranked kept copies (non-PvP keepers)</h2><div class="tbl"><table><tr><th>Mon</th><th class="num">IV</th><th class="num">CP</th><th class="num">GL rank</th><th>Kept by</th></tr>%(wgl)s</table></div></div>
    <div class="card"><div class="eyebrow">Ultra League</div><h2>Worst-ranked kept copies (non-PvP keepers)</h2><div class="tbl"><table><tr><th>Mon</th><th class="num">IV</th><th class="num">CP</th><th class="num">UL rank</th><th>Kept by</th></tr>%(wul)s</table></div></div>
    <div class="card"><div class="eyebrow">Master League</div><h2>Worst-ranked kept copies (non-PvP keepers)</h2><div class="tbl"><table><tr><th>Mon</th><th class="num">IV</th><th class="num">CP</th><th class="num">ML rank</th><th>Kept by</th></tr>%(wml)s</table></div></div>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const H = %(hist)s;
const tok = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const labels = ['1-512','513-1024','1025-1536','1537-2048','2049-2560','2561-3072','3073-3584','3585-4096'];
new Chart(document.getElementById('c_hist'), {type:'bar', data:{labels, datasets:[
  {label:'Great', data:H.gl, backgroundColor:tok('--gl'), borderRadius:3},
  {label:'Ultra', data:H.ul, backgroundColor:tok('--ul'), borderRadius:3},
  {label:'Master', data:H.ml, backgroundColor:tok('--ml'), borderRadius:3}]},
  options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{position:'top', labels:{color:tok('--ink')}}},
    scales:{x:{grid:{display:false}, ticks:{color:tok('--mut'), font:{size:11}}}, y:{grid:{color:tok('--line')}, ticks:{color:tok('--mut')}, title:{display:true, text:'kept copies', color:tok('--mut')}}}}});
</script>
""" % {'css': CSS, 'bad': BAD, 'dead': DEAD, 'bag': n_all, 'kept': n_kept, 'gen': summary['generated'], 'kpis': ''.join(kp), 'buckets': bucket_html, 'dc': dc_html,
       'unr_n': len(unreachable_both), 'unr_slots': summary['unreachable_both_total_slots'], 'unr': unr_html, 'species': sp_html,
       'wgl': worst_html['gl'], 'wul': worst_html['ul'], 'wml': worst_html['ml'], 'hist': json.dumps(hist)}
out = os.path.join('system', 'analysis', 'pvp_worst.html')
open(out, 'w', encoding='utf-8').write(page)

print('bag %d kept %d | dead in all 3 leagues (rank>%d): %d (bottom half everywhere: %d) | of which kept by a non-PvP rule only: %d'
      % (n_all, n_kept, BAD, len(dead_all), len(dead_all_deep), summary['dead_cosmetic_total']))
for lg in ('gl', 'ul', 'ml'):
    s = stats[lg]
    print('  %s: ranked %d, bad %d, bottom-half %d, median %s%s' % (lg.upper(), s['ranked'], s['bad'], s['dead'], s['median'], (', cannot reach %d' % s['cannot_reach']) if lg != 'ml' else ''))
print('dead weight by keep rule:', dict(dead_cosmetic.most_common()))
print('species that reach neither GL nor UL: %d species / %d kept copies; top: %s' % (len(unreachable_both), summary['unreachable_both_total_slots'],
      ', '.join('%s %d' % (s['species'], s['kept']) for s in unreachable_both[:12])))
print('worst kinds (most PvP-dead kept copies):', ', '.join('%s %d/%d' % (s['species'], s['dead'], s['kept']) for s in worst_species[:15]))
print('wrote', out)
