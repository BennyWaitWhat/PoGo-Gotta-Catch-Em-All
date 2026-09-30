"""Render the Pokemon Master plan (wf_master.json from the master-plan workflow) into a
self-contained master_plan.html. Rerun after a new workflow run to refresh the page.
Usage: python gen_master_plan.py [path-to-wf_master.json]"""
import json, os, sys, html, datetime
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), 'wf_master.json')
m = json.load(open(SRC, encoding='utf-8'))['master']

CAT = {  # category -> chip color
    'engine-safety': '#95a5a6', 'hundo-dex': '#ff6ad5', 'events': '#3fe0c4', 'curation': '#6aa0ff',
    'trades': '#f1c40f', 'pvp': '#7fb3ff', 'max': '#e74c3c', 'catch-dex': '#2ecc71',
    'shiny-dex': '#ffd23f', 'tooling': '#b07cf0',
}
def cat_color(c):
    for k, v in CAT.items():
        if k in (c or '').lower():
            return v
    return '#8893a7'

E = html.escape
p = []
p.append('<!doctype html><meta charset="utf-8"><title>Pokemon Master Plan — ' +
         datetime.date.today().isoformat() + '</title>')
p.append('''<style>
:root{--bg:#0d1017;--card:#161b26;--line:#232b3a;--txt:#e6ebf5;--mut:#8893a7;--gold:#ffd23f}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);font:14.5px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;padding:28px}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:26px;margin:0} h2{font-size:18px;margin:26px 0 10px;color:var(--gold)}
.mut{color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px;margin-top:14px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;font-size:13.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin-bottom:10px}
.rank{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:#0a0d13;border:1px solid var(--line);font-weight:700;margin-right:10px;flex:0 0 auto}
.head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.chip{display:inline-block;font-size:11px;padding:2px 9px;border-radius:20px;border:1px solid;font-weight:600}
.when{font-size:12px;color:var(--mut);margin-left:auto;text-align:right}
.why{color:var(--mut);font-size:13px;margin:7px 0 4px}
ol.steps{margin:6px 0 2px 18px;padding:0} ol.steps li{margin:3px 0}
.cal{border-left:3px solid var(--line);padding-left:14px}
.cal .d{margin:9px 0} .cal b{color:var(--gold)}
ul.lg{margin:8px 0 0 18px} ul.lg li{margin:6px 0}
.foot{margin-top:26px;padding-top:12px;border-top:1px solid var(--line);font-size:12.5px;color:var(--mut)}
</style><div class="wrap">''')

p.append('<h1>&#127942; Pokemon Master Plan</h1><div class="mut">Generated ' + datetime.date.today().isoformat() +
         ' &middot; from a fresh recrawl + 10-agent deep analysis &middot; Trainer L80, NYC, Forever Forward season</div>')

p.append('<h2>Where you stand</h2><div class="grid">')
for s in m['snapshot']:
    p.append('<div class="stat">' + E(s) + '</div>')
p.append('</div>')

p.append('<h2>The plan — ranked by impact</h2>')
for it in sorted(m['plan'], key=lambda x: x['rank']):
    c = cat_color(it['category'])
    p.append('<div class="card"><div class="head"><span class="rank">%d</span>' % it['rank'])
    p.append('<span class="chip" style="color:%s;border-color:%s55;background:%s18">%s</span>' % (c, c, c, E(it['category'])))
    p.append('<b>%s</b><span class="when">%s</span></div>' % (E(it['title']), E(it['when'])))
    p.append('<div class="why">%s</div>' % E(it['why']))
    if it.get('steps'):
        p.append('<ol class="steps">' + ''.join('<li>%s</li>' % E(s) for s in it['steps']) + '</ol>')
    p.append('</div>')

p.append('<h2>Calendar — next 4 weeks</h2><div class="card cal">')
for c in m['calendar']:
    p.append('<div class="d">' + E(c).replace(E(c.split(':')[0] + ':'), '<b>' + E(c.split(':')[0]) + ':</b>', 1) + '</div>')
p.append('</div>')

p.append('<h2>The long game</h2><div class="card"><ul class="lg">')
for l in m['longgame']:
    p.append('<li>%s</li>' % E(l))
p.append('</ul></div>')

p.append('<div class="foot"><b>Engine status:</b> ' + E(m['engine_status']) +
         ('<br><b>Must-fix (applied 2026-06-09):</b> ' + E('; '.join(m['must_fix'])) if m.get('must_fix') else '') +
         '</div></div>')

out = os.path.join(ROOT, 'master_plan.html')
open(out, 'w', encoding='utf-8').write('\n'.join(p))
print('wrote', out, '(%d plan items, %d calendar entries)' % (len(m['plan']), len(m['calendar'])))
