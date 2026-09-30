"""Generate a self-contained HTML 'why is everything kept' report for an evolution line.
Usage: python gen_line_report.py 1,2,3   (pids)  ->  writes line_report.html
Shows, per stage, every mon with its keep-axis chips + an axis legend explaining each rule."""
import json, sqlite3, base64, os, sys, html
sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # Windows console is cp1252; the arrow in the final print crashed (2026-06-09)
import studio_data as sd
from costume_forms import COSTUME_FORMS

def is_costume_form(f):
    return (f or 0) in COSTUME_FORMS

PIDS = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else '1,2,3').split(',')]
ROOT = os.path.dirname(os.path.abspath(__file__))
pol = json.load(open(os.path.join(ROOT, 'system/analysis/policy_reasons.json')))
pile = set(open(os.path.join(ROOT, 'system/analysis/tagsets/Transfer.txt')).read().split())
con = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); con.row_factory = sqlite3.Row
rows = [r for r in con.execute(sd._SELECT) if r['pokemon_id'] in PIDS]
names = {r['pokemon_id']: r['species_name'] for r in rows}

# axis -> (label, color, why-it-keeps)
AX = {
    'variant_floor': ('Variant floor', '#6aa0ff', 'Top-3 of each form, PLUS every distinct costume / Dynamax / Gmax / background keeps its own top-N. This is your base + cosmetic collection.'),
    'shiny':         ('Shiny', '#ffd23f', 'Every shiny is kept (up to top-20 highest-IV per form).'),
    'hundo':         ('Hundo 100%', '#ff6ad5', 'Perfect 15/15/15 — always kept.'),
    'nundo':         ('Nundo 0%', '#b07cf0', 'Perfect 0/0/0 trophy — always kept.'),
    'legacy':        ('Legacy move', '#2ecc71', 'Knows a legacy/exclusive move (e.g. Frenzy Plant) — keep-all.'),
    'gl_iv':         ('Great League', '#3fe0c4', 'Top-5 Great League IV spread for its species.'),
    'ul_iv':         ('Ultra League', '#4ca8ff', 'Top-5 Ultra League IV spread for its species.'),
    'pvp_rank':      ('PvP rank', '#7fb3ff', 'Ranks in the top competitive PvP spreads.'),
    'pvp_spread':    ('0-15-15', '#7fb3ff', 'A trophy stat spread you chose to keep.'),
    'pvp_best_gl':   ('Best GL', '#7fb3ff', 'The best Great League copy of its species and battle form (non-shadow) that can actually ENTER Great League: ranked only at a stage it can evolve into and still be at or under 1500 CP at its current level.'),
    'pvp_best_ul':   ('Best UL', '#7fb3ff', 'The best Ultra League copy of its species and battle form (non-shadow) that can actually ENTER Ultra League: ranked only at a stage it can evolve into and still be at or under 2500 CP at its current level.'),
    'pvp_best_ml':   ('Best ML', '#7fb3ff', 'The best Master League copy of its species and battle form (non-shadow).'),
    'xxl':           ('XXL', '#e67e22', 'XXL size — showcase keeper (top by showcase score).'),
    'shadow_best':   ('Shadow', '#9b59b6', 'Best shadow form by IV.'),
    'location_card': ('Location card', '#d35400', 'Carries a location-card collectible — keep-all.'),
    'rarity':        ('Rare/Legendary', '#e74c3c', 'Legendary/mythical/rare — kept by the rarity cap.'),
    'evolve_1':      ('Evolve', '#16a085', 'Kept to evolve up and fill/beat a final-form slot.'),
    'evolve_2':      ('Evolve', '#16a085', 'Kept to evolve up and fill/beat a final-form slot.'),
    'mighty':        ('Mighty', '#c0392b', 'Mighty origin (L40+, 13/13/13) — keep-all.'),
    'adventure_effect': ('Adventure FX', '#27ae60', 'Adventure-Effect species — keep-all.'),
    'origin':        ('Lucky/Traded', '#f1c40f', 'Lucky or traded from your origin friends — keep-all.'),
    'protected':     ('Protected', '#95a5a6', 'On your protected keep-all list.'),
    'dex_only_copy': ('Only copy', '#1abc9c', 'Your only copy of this form — kept for the dex.'),
}

def kind(r):
    p = []
    if r['fresh_shiny']: p.append('shiny')
    if (r['iv_total'] or 0) == 45: p.append('100%')
    _ax = sd.evolvable_forms.max_axis(r['fresh_bread_mode'])
    if _ax == 'gigantamax': p.append('Gmax')
    elif _ax == 'dynamax': p.append('Dmax')
    if (r['fresh_costume'] or 0) or is_costume_form(r['fresh_form']): p.append('costume')
    if r['special_bg_id']: p.append('bg')
    if r['fresh_alignment'] == 1: p.append('shadow')
    if (r['pokemon_size_category'] or 0) == 5: p.append('XXL')
    return p or ['plain']

def sprite_uri(pid):
    fn = sd.sprite_rel(pid, 0)
    p = sd.sprite_path(fn) if fn else None
    if p and os.path.isfile(p):
        b = base64.b64encode(open(p, 'rb').read()).decode()
        return 'data:image/jpeg;base64,' + b
    return ''

from collections import Counter
line_axis = Counter()
for r in rows:
    if r['uid_hex'] not in pile:
        for a in pol.get(r['uid_hex'], []):
            line_axis[a] += 1

tot = len(rows); kept = sum(1 for r in rows if r['uid_hex'] not in pile); xfer = tot - kept
linename = ' → '.join(names.get(p, str(p)) for p in PIDS)

def chip(a):
    lab, col, _ = AX.get(a, (a, '#888', ''))
    return '<span class="chip" style="background:%s22;color:%s;border-color:%s55">%s</span>' % (col, col, col, html.escape(lab))

def badge(k):
    cols = {'shiny': '#ffd23f', '100%': '#ff6ad5', 'Gmax': '#e74c3c', 'Dmax': '#e67e22', 'costume': '#9b59b6', 'bg': '#d35400', 'shadow': '#8e44ad', 'XXL': '#e67e22', 'plain': '#667'}
    c = cols.get(k, '#667')
    return '<span class="bdg" style="color:%s;border-color:%s55">%s</span>' % (c, c, html.escape(k))

parts = []
parts.append('<!doctype html><meta charset="utf-8"><title>' + html.escape(linename) + ' &mdash; keep analysis</title>')
parts.append('''<style>
:root{--bg:#0d1017;--card:#161b26;--line:#232b3a;--txt:#e6ebf5;--mut:#8893a7}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:26px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:0}
.mut{color:var(--mut)} .wrap{max-width:1080px;margin:0 auto}
.hero{display:flex;align-items:center;gap:16px;margin-bottom:18px}
.hero img{width:54px;height:54px;border-radius:10px;background:#0a0d13;object-fit:contain}
.kpis{display:flex;gap:10px;margin:14px 0 22px;flex-wrap:wrap}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 16px}
.kpi .v{font-size:22px;font-weight:700} .kpi .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px}
.legend{display:grid;grid-template-columns:1fr 1fr;gap:8px 22px}
.lrow{display:flex;gap:10px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--line)}
.dot{width:12px;height:12px;border-radius:3px;margin-top:4px;flex:0 0 auto}
.lrow b{display:block} .lrow .why{color:var(--mut);font-size:12.5px}
.cnt{margin-left:auto;color:var(--mut);font-variant-numeric:tabular-nums}
.stage{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.stage img{width:44px;height:44px;border-radius:9px;background:#0a0d13;object-fit:contain}
table{width:100%;border-collapse:collapse} td,th{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
.ivbar{display:inline-block;width:64px;height:7px;border-radius:4px;background:#222a39;overflow:hidden;vertical-align:middle;margin-right:8px}
.ivbar i{display:block;height:100%}
.chip{display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid;margin:1px 2px;font-weight:600}
.bdg{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:5px;border:1px solid;margin:1px 2px;background:#0a0d13}
.xfer{color:#ff6b6b} .n{text-align:right;font-variant-numeric:tabular-nums}
</style><div class="wrap">''')

parts.append('<div class="hero">' + ''.join('<img src="%s">' % sprite_uri(p) for p in PIDS) +
             '<div><h1>%s</h1><div class="mut">Why every kept mon is kept &mdash; live from your bag</div></div></div>' % html.escape(linename))
parts.append('<div class="kpis"><div class="kpi"><div class="v">%d</div><div class="l">in bag</div></div>'
             '<div class="kpi"><div class="v" style="color:#2ecc71">%d</div><div class="l">kept</div></div>'
             '<div class="kpi"><div class="v" style="color:#ff6b6b">%d</div><div class="l">to transfer</div></div></div>' % (tot, kept, xfer))

# legend (only axes that actually appear)
parts.append('<div class="card"><h2>The keep axes in play</h2><div class="mut" style="font-size:12.5px;margin:4px 0 12px">Each mon stays because it hits at least one of these. A mon can hit several (that\'s the overlap).</div><div class="legend">')
for a, n in line_axis.most_common():
    lab, col, why = AX.get(a, (a, '#888', ''))
    parts.append('<div class="lrow"><span class="dot" style="background:%s"></span><div><b>%s</b><span class="why">%s</span></div><span class="cnt">%d</span></div>' % (col, html.escape(lab), html.escape(why), n))
parts.append('</div></div>')

# per stage
for pid in PIDS:
    st = [r for r in rows if r['pokemon_id'] == pid]
    if not st: continue
    k = [r for r in st if r['uid_hex'] not in pile]
    x = [r for r in st if r['uid_hex'] in pile]
    parts.append('<div class="card"><div class="stage"><img src="%s"><div><h2>%s</h2><div class="mut">%d in bag &middot; %d kept &middot; %d transfer</div></div></div>' % (sprite_uri(pid), html.escape(names.get(pid, str(pid))), len(st), len(k), len(x)))
    parts.append('<table><tr><th>IV</th><th>CP</th><th>What it is</th><th>Kept because</th></tr>')
    for r in sorted(k, key=lambda r: -(r['iv_total'] or 0)):
        pct = (r['iv_total'] or 0) / 45 * 100
        col = '#2ecc71' if pct >= 90 else ('#f1c40f' if pct >= 70 else '#8893a7')
        rs = sorted(pol.get(r['uid_hex'], []))
        parts.append('<tr><td><span class="ivbar"><i style="width:%d%%;background:%s"></i></span>%d%%</td><td class="n">%s</td><td>%s</td><td>%s</td></tr>' % (
            int(pct), col, round(pct), r['cp'], ''.join(badge(b) for b in kind(r)), ''.join(chip(a) for a in rs) or '<span class="mut">—</span>'))
    for r in sorted(x, key=lambda r: -(r['iv_total'] or 0)):
        pct = (r['iv_total'] or 0) / 45 * 100
        parts.append('<tr style="opacity:.75"><td>%d%%</td><td class="n">%s</td><td>%s</td><td class="xfer">→ transfer (cap excess, no other axis)</td></tr>' % (round(pct), r['cp'], ''.join(badge(b) for b in kind(r))))
    parts.append('</table></div>')

parts.append('</div>')
open(os.path.join(ROOT, 'line_report.html'), 'w', encoding='utf-8').write('\n'.join(parts))
print('wrote line_report.html for', linename, '(%d mons)' % tot)
