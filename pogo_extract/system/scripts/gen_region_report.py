#!/usr/bin/env python
"""Self-contained HTML bag-optimization report for a dex range (one region).
Usage: python gen_region_report.py [lo] [hi] [RegionName]   (default 1 151 'Kanto (Gen 1)')

Trim math is PLAIN-ONLY and bundle-correct: a copy is trimmable only if it is _truly_plain
(no costume / event-bg / art / decoration / Dynamax / Gmax / form-encoded-costume) AND kept
solely by the top-3 cap (`variant_floor` is its only reason). Collectibles are never counted.
"""
import sqlite3, json, os, sys, html
from collections import defaultdict, Counter
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from costume_forms import is_costume_form, FORM_ENUM
import evolvable_forms   # BREAD_MODES / max_axis: the game's own Max-mode names

LO = int(sys.argv[1]) if len(sys.argv) > 1 else 1
HI = int(sys.argv[2]) if len(sys.argv) > 2 else 151
REGION = sys.argv[3] if len(sys.argv) > 3 else 'Kanto (Gen 1)'
c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db')); c.row_factory = sqlite3.Row
pr = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))
RM = pr['reasons'] if (isinstance(pr, dict) and isinstance(pr.get('reasons'), dict)) else pr


def reasons(u):
    v = RM.get(u); return v if isinstance(v, list) else []


def tp(r):
    return (not (r['fresh_costume'] or 0) and not (r['special_bg_id'] or 0) and not (r['natural_art_background'] or 0)
            and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
            and not evolvable_forms.max_axis(r['fresh_bread_mode']) and not is_costume_form(r['fresh_form']))


allbag = c.execute("SELECT COUNT(*) n FROM pokemon WHERE in_bag=1").fetchone()['n']
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN ? AND ?", (LO, HI)).fetchall()
kept = [r for r in rows if reasons(r['uid_hex'])]


def bucket(r):
    rs = reasons(r['uid_hex'])
    if 'shiny' in rs: return 'Shiny'
    if 'hundo' in rs: return 'Hundo'
    if 'rarity' in rs: return 'Legendary'
    if 'shadow_best' in rs: return 'Shadow'
    if 'xxl' in rs: return 'XXL'
    if 'legacy' in rs: return 'Legacy'
    if any(x in rs for x in ('gl_iv', 'ul_iv', 'pvp_spread', 'pvp_rank', 'pvp_best_gl', 'pvp_best_ul')): return 'PvP'
    if any(x in rs for x in ('nundo', 'best_buddy', 'origin', 'adventure_effect', 'mighty')): return 'Other'
    if not tp(r): return 'Event/Variant'
    if 'dex_only_copy' in rs: return 'Dex-only'
    return 'Plain'


plain = [r for r in kept if tp(r)]
bnd = defaultdict(list)
for r in plain:
    bnd[(r['pokemon_id'], r['form'] or 0)].append(r)
trim2 = defaultdict(list); trim1 = defaultdict(list)
for k, lst in bnd.items():
    lst.sort(key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))
    for i, r in enumerate(lst):
        if reasons(r['uid_hex']) == ['variant_floor']:
            if i >= 2: trim2[r['species_name']].append(r)
            if i >= 1: trim1[r['species_name']].append(r)
fodder = sum(1 for r in plain if reasons(r['uid_hex']) == ['variant_floor'] and (r['iv_total'] or 0) < 36)
n2 = sum(len(v) for v in trim2.values()); n1 = sum(len(v) for v in trim1.values())

BUCKETS = ['Shiny', 'Hundo', 'Legendary', 'Shadow', 'XXL', 'Legacy', 'Event/Variant', 'PvP', 'Other', 'Dex-only', 'Plain']
COL = {'Shiny': '#f4c542', 'Hundo': '#e0556a', 'Legendary': '#9b6dff', 'Shadow': '#6b5b95', 'XXL': '#4a90d9',
       'Legacy': '#2bb3a3', 'Event/Variant': '#e066b0', 'PvP': '#5cb85c', 'Other': '#7d8590', 'Dex-only': '#56606b', 'Plain': '#ef8c3b'}
sp = {}
for r in kept:
    d = sp.setdefault(r['species_name'], {'pid': r['pokemon_id'], 'kept': 0, 'b': Counter()})
    d['kept'] += 1; d['b'][bucket(r)] += 1
for s in sp:
    sp[s]['t2'] = len(trim2.get(s, [])); sp[s]['t1'] = len(trim1.get(s, []))
maxk = max((d['kept'] for d in sp.values()), default=1)
rc = Counter(); solo = Counter()
for r in kept:
    rs = reasons(r['uid_hex'])
    for x in rs: rc[x] += 1
    if len(rs) == 1: solo[rs[0]] += 1

E = html.escape
def fname(r):
    return FORM_ENUM.get(r['fresh_form'] or 0) or 'base'

# ---- build HTML ----
rowsh = []
for s, d in sorted(sp.items(), key=lambda kv: -kv[1]['kept']):
    seg = ''
    for b in BUCKETS:
        n = d['b'].get(b, 0)
        if n:
            seg += f'<span class="seg" style="width:{n/maxk*340:.1f}px;background:{COL[b]}" title="{b}: {n}"></span>'
    cand = trim2.get(s, [])
    det = ''
    if cand:
        items = ''.join(f"<tr><td>{(r['iv_total'] or 0)*100//45}%</td><td>{r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}</td><td>{r['cp']}</td><td>{'shadow' if r['fresh_alignment']==1 else ('purified' if r['fresh_alignment']==2 else '')}</td><td>{E(fname(r))}</td></tr>" for r in sorted(cand, key=lambda r:-(r['iv_total'] or 0)))
        det = f'<tr class="detail" id="d{d["pid"]}"><td colspan="7"><b>{E(s)} — {len(cand)} trimmable at top-2 (3rd+ plain, no special trait):</b><table class="mini"><tr><th>IV%</th><th>spread</th><th>CP</th><th>state</th><th>form</th></tr>{items}</table></td></tr>'
    rowsh.append(f'<tr class="srow" data-k="{d["kept"]}" data-t2="{d["t2"]}" data-t1="{d["t1"]}" data-d="{d["pid"]}" onclick="tog({d["pid"]})"><td>{d["pid"]}</td><td>{E(s)}</td><td class="num">{d["kept"]}</td><td><div class="bar">{seg}</div></td><td class="num t2">{d["t2"] or ""}</td><td class="num t1">{d["t1"] or ""}</td><td class="exp">{"+" if cand else ""}</td></tr>')
    rowsh.append(det)

legend = ''.join(f'<span class="lg"><span class="dot" style="background:{COL[b]}"></span>{b}</span>' for b in BUCKETS)
levers = ''.join(f'<tr><td>{E(x)}</td><td class="num">{rc[x]}</td><td class="num">{solo.get(x,0)}</td></tr>' for x, _ in rc.most_common())

HTML = f"""<!doctype html><html><head><meta charset="utf-8"><title>{E(REGION)} Bag Optimization</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#0d1117;color:#e6edf3;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:28px 0 10px;color:#58a6ff}}.sub{{color:#8b949e;margin-bottom:18px}}
.cards{{display:flex;gap:14px;flex-wrap:wrap}}.card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px 18px;min-width:120px}}
.card .big{{font-size:26px;font-weight:700}}.card .lbl{{color:#8b949e;font-size:12px}}
.dial{{display:flex;gap:14px;flex-wrap:wrap}}.dcard{{flex:1;min-width:200px;background:#161b22;border:1px solid #30363d;border-left-width:4px;border-radius:10px;padding:14px 18px}}
.dcard.c{{border-left-color:#3fb950}}.dcard.r{{border-left-color:#d29922}}.dcard.a{{border-left-color:#f85149}}
.dcard .n{{font-size:30px;font-weight:700}}.dcard .t{{font-weight:600;margin-bottom:4px}}.dcard .d{{color:#8b949e;font-size:12.5px}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:6px 9px;border-bottom:1px solid #21262d;text-align:left}}
th{{color:#8b949e;font-size:12px;cursor:pointer;user-select:none;position:sticky;top:0;background:#0d1117}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}.t2{{color:#d29922;font-weight:600}}.t1{{color:#f85149}}
.srow{{cursor:pointer}}.srow:hover{{background:#161b22}}.bar{{display:flex;height:13px;border-radius:3px;overflow:hidden;background:#21262d;width:344px}}.seg{{height:13px}}
.exp{{color:#8b949e;width:18px;text-align:center}}.detail{{display:none;background:#10151c}}.detail.show{{display:table-row}}
.mini{{margin:6px 0 2px;width:auto}}.mini th,.mini td{{padding:2px 10px 2px 0;border:0;font-size:12.5px}}
.lg{{display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:12px;color:#c9d1d9}}.dot{{width:10px;height:10px;border-radius:2px;display:inline-block}}
.legend{{margin:8px 0 14px;flex-wrap:wrap}}
</style></head><body>
<h1>{E(REGION)} — Bag Optimization</h1>
<div class="sub">As of last crawl. Bag total {allbag:,} · this region is {len(rows)} mons ({100*len(rows)//allbag}% of bag).</div>
<div class="cards">
 <div class="card"><div class="big">{len(rows)}</div><div class="lbl">in bag</div></div>
 <div class="card"><div class="big">{len(kept)}</div><div class="lbl">kept</div></div>
 <div class="card"><div class="big">{len(rows)-len(kept)}</div><div class="lbl">already transfer</div></div>
 <div class="card"><div class="big">{len(plain)}</div><div class="lbl">truly-plain kept</div></div>
 <div class="card"><div class="big">{len(kept)-len(plain)}</div><div class="lbl">collectibles (protected)</div></div>
</div>
<h2>Idea #1 — Trim the plain top-3 cap (PLAIN-ONLY, collectibles untouched)</h2>
<div class="dial">
 <div class="dcard c"><div class="t">Conservative</div><div class="n">{fodder}</div><div class="d">drop only &lt;80%-IV cap-fillers</div></div>
 <div class="dcard r"><div class="t">Recommended · top-3 → top-2</div><div class="n">{n2}</div><div class="d">keep your 2 best plain of each species</div></div>
 <div class="dcard a"><div class="t">Aggressive · top-3 → top-1</div><div class="n">{n1}</div><div class="d">keep single best plain of each</div></div>
</div>
<h2>Per-species — what's kept &amp; what's trimmable <span style="color:#8b949e;font-weight:400;font-size:12px">(click a row to see the exact trim candidates; click headers to sort)</span></h2>
<div class="legend">{legend}</div>
<table id="t"><thead><tr><th onclick="srt(0,1)">Dex</th><th onclick="srt(1,0)">Species</th><th onclick="srt(2,1)" class="num">Kept</th><th>Composition</th><th onclick="srt(4,1)" class="num">Trim@2</th><th onclick="srt(5,1)" class="num">Trim@1</th><th></th></tr></thead>
<tbody>{''.join(rowsh)}</tbody></table>
<h2>Keep-reason levers</h2>
<table><tr><th>reason</th><th class="num">kept w/ it</th><th class="num">solo (only reason)</th></tr>{levers}</table>
<script>
function tog(id){{var e=document.getElementById('d'+id);if(e)e.classList.toggle('show');}}
function srt(col,num){{var tb=document.querySelector('#t tbody');var rs=[...tb.querySelectorAll('tr.srow')];
 rs.sort((a,b)=>{{var x=a.children[col].innerText,y=b.children[col].innerText;return num?(+y||0)-(+x||0):x.localeCompare(y);}});
 tb.innerHTML='';rs.forEach(r=>{{tb.appendChild(r);var d=document.getElementById('d'+r.dataset.d);if(d)tb.appendChild(d);}});}}
</script></body></html>"""
out = os.path.join(ROOT, 'system', 'analysis', f"{REGION.split()[0].lower()}_optimization.html")
open(out, 'w', encoding='utf-8').write(HTML)
print(f"wrote {out}")
print(f"{REGION}: in_bag={len(rows)} kept={len(kept)} plain={len(plain)} collectibles={len(kept)-len(plain)}")
print(f"PLAIN-ONLY trim: fodder(<80%)={fodder}  top2={n2}  top1={n1}")
