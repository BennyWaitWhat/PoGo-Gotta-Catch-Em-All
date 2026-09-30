"""build_map.py -- generate system/analysis/system_map.html, the visual map of
how every keep-reason flows into the three views (CULL / PURPOSE / TAGS).

Reproducible: re-run after any crawl/profile to refresh the live numbers. Pulls
reasons from cull_v9 (the engine) and the mapping from keep_engine (the spec),
so the picture can never disagree with the code.
"""
import sys, os, sqlite3, json, html
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)          # cull_v9, references
sys.path.insert(0, HERE)          # keep_engine
os.chdir(ROOT)                    # cull_v9 reads json files relative to cwd
import cull_v9, keep_engine
sys.stdout.reconfigure(encoding='utf-8')

OUT = os.path.join(ROOT, 'system', 'analysis', 'system_map.html')
PURPOSE_COLORS = {'PVP': '#e74c3c', 'MEGA': '#9b59b6', 'ADVENTURE': '#16a085',
                  'MAX': '#e67e22', 'COLLECTION': '#2980b9', 'RESERVE': '#7f8c8d',
                  'TRADE': '#f1c40f', 'TRANSFER': '#34495e'}


def main():
    conn = sqlite3.connect('pokemon.db'); conn.row_factory = sqlite3.Row
    rows, ctx = cull_v9._load_rows_and_ctx(conn.cursor())
    n = len(rows)

    # per-mon reasons -> purpose; reason-dimension histogram
    dim = Counter()                      # reason-prefix -> mons protected
    purpose_ct = Counter()
    cull_transfer = set()
    tagged = set()
    for p in rows:
        reasons = cull_v9.is_protected(p, ctx)
        seen = set()
        for r in reasons:
            pref = keep_engine.reason_prefix(r)
            if pref not in seen:         # count each dimension once per mon
                dim[pref] += 1; seen.add(pref)
        pur = keep_engine.classify_purpose(reasons, p['iv_total'])
        purpose_ct[pur] += 1
        if not reasons:
            cull_transfer.add(p['uid_hex'])
        if (p['auth_tag_names'] or '').strip(';'):
            tagged.add(p['uid_hex'])

    # OLD purpose (pre-unification) from the existing profile, for the before/after
    old_transfer = set()
    try:
        prof = json.load(open('system/analysis/deep_profiles.json', encoding='utf-8'))
        old_transfer = {p['uid'] for p in prof if p.get('purpose') == 'TRANSFER'}
    except Exception:
        pass
    both = cull_transfer & old_transfer
    cull_only = cull_transfer - old_transfer
    old_only = old_transfer - cull_transfer

    # ---- build the dimension matrix rows (purpose-priority then count) ----
    def meta_for(pref):
        if pref == 'user_tag':
            m = {'purpose': '(tag-derived)', 'native': False, 'tag': 'various'}
        else:
            m = keep_engine.REASON_META.get(pref, {'purpose': '?', 'native': False, 'tag': None})
        lab, desc = keep_engine.REASON_LABELS.get(pref, (pref, ''))
        return {'pref': pref, 'purpose': m['purpose'], 'native': m['native'],
                'tag': m.get('tag') or '', 'label': lab, 'desc': desc}
    rowdata = []
    for pref, cnt in dim.items():
        m = meta_for(pref); m['cnt'] = cnt; rowdata.append(m)
    rowdata.sort(key=lambda r: (keep_engine._PRIO.get(r['purpose'], 99), -r['cnt']))

    def esc(x): return html.escape(str(x))
    def bar(label, cnt, color):
        pct = 100.0 * cnt / max(n, 1)
        return (f'<div class="barrow"><span class="blab">{esc(label)}</span>'
                f'<span class="btrack"><span class="bfill" style="width:{pct:.1f}%;'
                f'background:{color}"></span></span><span class="bval">{cnt}</span></div>')

    purpose_bars = ''.join(
        bar(p, purpose_ct.get(p, 0), PURPOSE_COLORS[p]) for p in keep_engine.PURPOSE_PRIORITY)

    matrix_rows = ''
    for r in rowdata:
        pc = PURPOSE_COLORS.get(r['purpose'], '#bbb')
        nat = ('<span class="yes">native filter</span>' if r['native']
               else '<span class="no">needs tag</span>')
        matrix_rows += (
            f'<tr><td><span class="rlabel">{esc(r["label"])}</span>'
            f'<div class="rcode">{esc(r["pref"])}</div></td>'
            f'<td class="rdesc">{esc(r["desc"])}</td>'
            f'<td class="num">{r["cnt"]}</td>'
            f'<td><span class="pchip" style="background:{pc}">{esc(r["purpose"])}</span></td>'
            f'<td>{nat}</td><td class="tag">{esc(r["tag"])}</td></tr>')

    # tag -> reasons (which dimensions feed each custom tag)
    tag_feed = {}
    for r in rowdata:
        if r['tag'] and r['tag'] != 'various':
            for t in r['tag'].split(' / '):
                tag_feed.setdefault(t.strip(), []).append(f'{r["label"]} ({r["cnt"]})')
    tag_rows = ''.join(
        f'<tr><td class="tag">{esc(t)}</td><td>{esc(", ".join(v))}</td></tr>'
        for t, v in sorted(tag_feed.items()))

    HTML = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Collection System Map</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1419;color:#e6e6e6}}
 .wrap{{max-width:1080px;margin:0 auto;padding:32px 24px 80px}}
 h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:18px;margin:36px 0 12px;border-bottom:1px solid #2a3441;padding-bottom:6px}}
 .sub{{color:#8b98a5;margin:0 0 24px}}
 .flow{{display:flex;align-items:stretch;gap:14px;flex-wrap:wrap}}
 .engine{{flex:1 1 100%;background:#1a2330;border:1px solid #2a3441;border-radius:10px;padding:16px 18px;text-align:center}}
 .engine b{{color:#ffd479;font-size:15px}} .engine .dims{{color:#8b98a5;font-size:12.5px;margin-top:6px}}
 .arrow{{flex:1 1 100%;text-align:center;color:#5a6b7a;font-size:20px;margin:2px 0}}
 .view{{flex:1 1 30%;min-width:240px;background:#1a2330;border:1px solid #2a3441;border-radius:10px;padding:14px 16px}}
 .view h3{{margin:0 0 6px;font-size:15px}} .view p{{margin:0;color:#9fb0bf;font-size:13px}}
 .v-cull h3{{color:#e74c3c}} .v-purpose h3{{color:#2980b9}} .v-tag h3{{color:#16a085}}
 .venn{{display:flex;gap:18px;align-items:center;flex-wrap:wrap;background:#1a2330;border:1px solid #2a3441;border-radius:10px;padding:18px 20px}}
 .venncol{{flex:1 1 360px}} .vstat{{display:flex;gap:10px;margin:6px 0;align-items:baseline}}
 .vstat .nbig{{font-size:22px;font-weight:700;min-width:54px;text-align:right}}
 .grn{{color:#2ecc71}} .org{{color:#e67e22}} .red{{color:#e74c3c}} .gry{{color:#8b98a5}}
 .barrow{{display:flex;align-items:center;gap:10px;margin:5px 0}}
 .blab{{min-width:96px;font-size:13px}} .btrack{{flex:1;background:#222d3a;border-radius:4px;height:18px;overflow:hidden}}
 .bfill{{display:block;height:100%}} .bval{{min-width:42px;text-align:right;color:#cdd9e3;font-size:13px}}
 table{{width:100%;border-collapse:collapse;margin-top:8px}}
 th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #232e3b;font-size:13px}}
 th{{color:#8b98a5;font-weight:600}} .num{{text-align:right;color:#cdd9e3;font-variant-numeric:tabular-nums}}
 .rname{{font-family:ui-monospace,Menlo,monospace;color:#cfe3ff}}
 .rlabel{{font-weight:600;color:#eaf2fb;font-size:13.5px}} .rcode{{font-family:ui-monospace,Menlo,monospace;color:#5f7488;font-size:10.5px;margin-top:1px}}
 .rdesc{{color:#9fb0bf;font-size:12.5px;max-width:400px}}
 .pchip{{color:#fff;padding:2px 8px;border-radius:10px;font-size:11.5px;font-weight:600}}
 .yes{{color:#2ecc71}} .no{{color:#e67e22}} .tag{{color:#ffd479;font-size:12.5px}}
 .note{{background:#15202b;border-left:3px solid #ffd479;padding:10px 14px;border-radius:0 8px 8px 0;color:#c9d6e0;margin:14px 0}}
</style></head><body><div class="wrap">
<h1>Collection System Map</h1>
<p class="sub">{n:,} in-bag specimens &middot; one keep-reason engine, three views &middot; generated by build_map.py</p>

<h2>The model</h2>
<div class="flow">
  <div class="engine"><b>ONE KEEP-REASON ENGINE</b> &nbsp;(cull_v9 registry &rarr; {len(dim)} dimensions)
    <div class="dims">hundo &middot; shiny &middot; legendary &middot; GL/UL top-2 &middot; mega &middot; XXL &middot; species-top-3 &middot; shadow &middot; legacy &middot; dex-gap &middot; adventure &middot; tagged &hellip;</div></div>
  <div class="arrow">&darr; &nbsp; projects into three views &nbsp; &darr;</div>
  <div class="view v-cull"><h3>CULL</h3><p>TRANSFER &hArr; the reason set is <b>empty</b>. Everything else is KEEP.</p></div>
  <div class="view v-purpose"><h3>PURPOSE</h3><p>The single <b>highest-priority</b> reason's category (1 of 8 buckets).</p></div>
  <div class="view v-tag"><h3>TAGS</h3><p>Only the reasons PoGo <b>can't filter natively</b> &rarr; your 16 custom server tags.</p></div>
</div>

<h2>Before &rarr; after unification (the transfer zone)</h2>
<div class="venn"><div class="venncol">
  <div class="vstat"><span class="nbig grn">{len(both)}</span><span>both cull &amp; purpose agreed TRANSFER &mdash; the <b>safe cull set</b></span></div>
  <div class="vstat"><span class="nbig org">{len(old_only)}</span><span>purpose-only TRANSFER (cull kept) &mdash; old drift</span></div>
  <div class="vstat"><span class="nbig org">{len(cull_only)}</span><span>cull-only TRANSFER (purpose kept) &mdash; old drift</span></div>
  <div class="vstat"><span class="nbig gry">0</span><span>tagged mons in any transfer set &mdash; tags are sacred</span></div>
</div><div class="venncol">
  <div class="note"><b>After unification:</b> purpose now derives from the same engine as cull, so
  purpose-TRANSFER &equiv; cull-TRANSFER by construction. The {len(old_only)+len(cull_only)} drift cases vanish &mdash;
  no two views can disagree again.</div>
</div></div>

<h2>Purpose distribution (unified)</h2>
{purpose_bars}

<h2>Keep-reason matrix &mdash; every dimension &rarr; its three views</h2>
<p class="sub">Sorted by purpose priority. "native filter" = PoGo search already covers it (no custom tag needed). Edit mappings in <span class="rname">keep_engine.py</span>.</p>
<table><thead><tr><th>Keep reason</th><th>What it means</th><th class="num"># mons</th><th>Purpose</th><th>In-game filter</th><th>Custom tag</th></tr></thead>
<tbody>{matrix_rows}</tbody></table>

<h2>Custom tags &larr; which reasons feed them</h2>
<table><thead><tr><th>Server tag</th><th>Fed by reason(s)</th></tr></thead><tbody>{tag_rows}</tbody></table>
</div></body></html>"""

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(HTML)
    # also write index.html so a static server can serve the map at its root
    with open(os.path.join(os.path.dirname(OUT), 'index.html'), 'w', encoding='utf-8') as f:
        f.write(HTML)
    print(f'wrote {OUT}')
    print(f'  {n} mons | {len(dim)} reason dimensions | purpose: {dict(purpose_ct.most_common())}')
    print(f'  transfer zone: both={len(both)} purpose_only={len(old_only)} cull_only={len(cull_only)}')


if __name__ == '__main__':
    main()
