"""Generate the three live-data artifacts: Hundo Dex tracker, Collection Snapshot, Keep Lattice.
Self-contained HTML (no external deps), cross-linked, dark theme matching the dashboard.
Rerun after a recrawl to refresh. Served by the dashboard at /dex /snapshot /lattice."""
import json, sqlite3, os, sys, html, datetime, math
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
g = lambda q: con.execute(q).fetchone()[0]
TODAY = datetime.date.today().isoformat()
E = html.escape

# ---------- gather ----------
bag = g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1")
pile = len([x for x in open('system/analysis/tagsets/Transfer.txt').read().split() if x])
keep = bag - pile
census = {
    'Shiny': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_shiny=1"),
    'Hundo 100%': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND iv_total=45"),
    'Nundo 0%': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND iv_total=0"),
    'Gigantamax': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_bread_mode=2"),
    'Dynamax': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_bread_mode=1"),
    'Shadow': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_alignment=1"),
    'Purified': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_alignment=2"),
    'Lucky': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND is_lucky=1"),
    'XXL': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5"),
    'XXS': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND pokemon_size_category=1"),
    'Costume': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND COALESCE(fresh_costume,0)!=0"),
    'Location card': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_has_location_card=1"),
    'Mighty': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_is_strong=1"),
    'Shiny hundo': g("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_shiny=1 AND iv_total=45"),
}
# Storage capacity is a GAME-OWNED number -- read LIVE from PlayerService.get_MaxPokemon by
# read_player_state.py (runs each recrawl) and cached in player_state.json. It was hardcoded 11150
# here from a stale note and was flat WRONG (real value 5700) -- never hardcode it again.
try:
    _ps = json.load(open('player_state.json'))
    STORAGE = int(_ps['max_pokemon_storage'])
    STORAGE_SRC = 'live'
except Exception:
    STORAGE = None            # unknown -> show nothing rather than invent a number
    STORAGE_SRC = 'unknown'
tags = {}
for f in sorted(os.listdir('system/analysis/tagsets')):
    if f.endswith('.txt') and not f.startswith('6_'):
        tags[f[:-4].replace('_', ' ')] = len([x for x in open('system/analysis/tagsets/' + f).read().split() if x])
# ----- dex tiers + keep-reasons computed INLINE (self-sufficient: rerun after any recrawl) -----
import subprocess, collections
gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
NAME = {}
for _p in gm['pokemon']:
    _d = _p.get('dex')
    if _d and '_shadow' not in _p['speciesId'] and _d not in NAME:
        NAME[_d] = _p['speciesName']
try:
    from references import LEGENDARY_IDS, MYTHICAL_IDS
except Exception:
    LEGENDARY_IDS, MYTHICAL_IDS = set(), set()
try:
    from references import ULTRA_BEAST_IDS, PARADOX_IDS
except Exception:
    ULTRA_BEAST_IDS, PARADOX_IDS = set(), set()
_rare = set(LEGENDARY_IDS) | set(MYTHICAL_IDS) | set(ULTRA_BEAST_IDS) | set(PARADOX_IDS)
_dx = json.load(open('pokedex_hundos_live.json'))['entries']
_caught = {e['pid'] for e in _dx if (e.get('times') or 0) > 0}
_hund = {e['pid'] for e in _dx if e.get('hundo')}
caught_n, hundo_n = len(_caught), len(_hund)
# which missing-hundo targets are reachable by evolving a bag hundo (CLEAN bucket of evo_hundo_gap)
_clean = set()
try:
    _out = subprocess.run([sys.executable, 'evo_hundo_gap.py'], capture_output=True, text=True, timeout=120).stdout
    _grab = False
    for _ln in _out.splitlines():
        if 'CLEAN' in _ln:
            _grab = True; continue
        if 'CAUTION' in _ln or 'BLOCKED' in _ln:
            _grab = False
        if _grab and '->' in _ln:
            _clean.add(_ln.split('->')[1].strip().split(',')[0].strip())
except Exception:
    pass
missing = []
for _pid in sorted(_caught - _hund):
    _nm = NAME.get(_pid, '#%d' % _pid)
    _t = 'raid' if _pid in _rare else ('evolve' if _nm in _clean else 'grind')
    missing.append({'pid': _pid, 'name': _nm, 'tier': _t})
tier_counts = {'evolve': 0, 'raid': 0, 'grind': 0}
for m in missing:
    tier_counts[m['tier']] += 1
_pol = json.load(open('system/analysis/policy_reasons.json'))
_baguids = {r['uid_hex'] for r in con.execute('SELECT uid_hex FROM pokemon WHERE in_bag=1')}
reasons = dict(collections.Counter(r for u, rs in _pol.items() if u in _baguids for r in rs))

CSS = '''
:root{--bg:#0c0f16;--card:#151a25;--card2:#1b2231;--line:#242c3c;--ink:#e7ecf6;--mut:#8a95ab;
--gold:#ffd23f;--grn:#34d27b;--red:#ff6b6b;--blu:#5b9dff;--pur:#b07cf0;--org:#ff9f43;--cyan:#3fe0c4}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#16203a 0%,var(--bg) 55%);
color:var(--ink);font:14.5px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;padding:0 0 60px}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px}
nav{display:flex;gap:8px;align-items:center;padding:16px 22px;position:sticky;top:0;
background:rgba(12,15,22,.82);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);z-index:9;flex-wrap:wrap}
nav .brand{font-weight:800;letter-spacing:.3px;margin-right:8px}nav .brand span{color:var(--gold)}
nav a{text-decoration:none;color:var(--mut);font-weight:650;font-size:13px;border:1px solid var(--line);
border-radius:9px;padding:7px 12px}
nav a.on{color:var(--ink);border-color:#3a465a;background:var(--card2)}nav .date{margin-left:auto;color:var(--mut);font-size:12px}
h1{font-size:25px;margin:26px 0 2px}.sub{color:var(--mut);margin-bottom:20px}
h2{font-size:16px;margin:30px 0 12px;color:var(--gold);letter-spacing:.2px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px}
.kpi .v{font-size:27px;font-weight:800;line-height:1}.kpi .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.6px;margin-top:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.cell{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;justify-content:space-between;align-items:baseline}
.cell .n{font-size:21px;font-weight:750}.cell .t{color:var(--mut);font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin-bottom:14px}
.bar{height:9px;border-radius:6px;background:#0a0d14;overflow:hidden}.bar i{display:block;height:100%}
.tagrow{display:flex;align-items:center;gap:12px;padding:7px 0;border-bottom:1px solid var(--line)}
.tagrow:last-child{border:0}.tagrow .nm{width:130px;font-size:13px}.tagrow .ct{width:46px;text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
.tagrow .bar{flex:1}
.chip{display:inline-block;font-size:11px;padding:3px 9px;border-radius:20px;border:1px solid;font-weight:650;margin:2px}
.mut{color:var(--mut)}.big{font-size:13px}
.tierhead{display:flex;align-items:center;gap:10px;margin:4px 0 10px}.tierhead .n{font-size:22px;font-weight:800}
.names{display:flex;flex-wrap:wrap;gap:6px}.names span{font-size:12px;color:#cdd6e8;background:var(--card2);border:1px solid var(--line);border-radius:7px;padding:3px 8px}
.ring{display:block;margin:0 auto}
svg text{fill:var(--ink)}
.lat-node{fill:var(--card2);stroke:var(--line)}.lat-lbl{font-size:13px;font-weight:650}
.foot{margin-top:30px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:14px}
a.inl{color:var(--blu)}
table.t{width:100%;border-collapse:collapse;margin:0 0 26px}
table.t td{padding:7px 10px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}
table.t tr:last-child td{border-bottom:0}
table.t td:first-child{width:38%}
table.t tr:hover td{background:var(--card2)}
'''

def nav(active):
    items = [('dex','Hundo Dex','art_dex.html'),('snapshot','Collection','art_collection.html'),
             ('lattice','Keep Lattice','art_lattice.html'),('upgrades','Upgrades','art_upgrades.html')]
    s = '<nav><div class="brand">PoGo&nbsp;<span>&#9670;</span></div>'
    for key,lab,href in items:
        s += '<a class="%s" href="%s">%s</a>' % ('on' if key==active else '', href, lab)
    s += '<div class="date">live data &middot; %s</div></nav>' % TODAY
    return s

def page(active, title, sub, body):
    return ('<!doctype html><meta charset="utf-8"><title>%s</title><style>%s</style>%s<div class="wrap">'
            '<h1>%s</h1><div class="sub">%s</div>%s'
            '<div class="foot">Generated from your live bag (pokemon.db) + lifetime dex on %s. '
            'Rerun <code>gen_artifacts.py</code> after a recrawl to refresh.</div></div>'
            % (E(title), CSS, nav(active), E(title), sub, body, TODAY))

# ---------- 1. HUNDO DEX ----------
pct = hundo_n / caught_n * 100
R, C = 78, 2*math.pi*78
off = C * (1 - hundo_n/caught_n)
ring = ('<svg class="ring" width="200" height="200" viewBox="0 0 200 200">'
        '<circle cx="100" cy="100" r="78" fill="none" stroke="#0a0d14" stroke-width="16"/>'
        '<circle cx="100" cy="100" r="78" fill="none" stroke="url(#gg)" stroke-width="16" stroke-linecap="round"'
        ' stroke-dasharray="%.1f" stroke-dashoffset="%.1f" transform="rotate(-90 100 100)"/>'
        '<defs><linearGradient id="gg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffd23f"/>'
        '<stop offset="1" stop-color="#ff6ad5"/></linearGradient></defs>'
        '<text x="100" y="96" text-anchor="middle" font-size="40" font-weight="800">%d</text>'
        '<text x="100" y="120" text-anchor="middle" font-size="13" fill="#8a95ab">of %d caught</text>'
        '<text x="100" y="150" text-anchor="middle" font-size="15" font-weight="700" fill="#ffd23f">%.1f%%</text>'
        '</svg>') % (C, off, hundo_n, caught_n, pct)

tiers = [
    ('evolve','&#9889; Evolve now','#34d27b','You already own the hundo pre-evo &mdash; just evolve it. Zero RNG.'),
    ('raid','&#9876; Raid / special wall','#ff6b6b','Legendary / mythical / UB &mdash; needs raid luck or a special research line.'),
    ('grind','&#127806; Wild grind','#5b9dff','Common spawns. Best odds from FLOORED encounters (research / egg / raid, 1/216) not wild.'),
]
body = '<div class="card" style="display:flex;gap:26px;align-items:center;flex-wrap:wrap">'
body += ring
body += ('<div style="flex:1;min-width:220px"><div style="font-size:15px;margin-bottom:10px">'
         '<b>%d</b> hundo species locked in &middot; <b style="color:var(--gold)">%d</b> still to catch a perfect.</div>'
         '<div class="grid">') % (hundo_n, len(missing))
for key,lab,col,_ in tiers:
    body += ('<div class="cell"><span class="t" style="color:%s">%s</span><span class="n">%d</span></div>'
             % (col, lab, tier_counts[key]))
body += '</div></div></div>'

by_tier = {'evolve':[], 'raid':[], 'grind':[]}
for m in missing: by_tier[m['tier']].append(m['name'])
for key,lab,col,desc in tiers:
    names = sorted(by_tier[key])
    body += '<div class="card"><div class="tierhead"><span class="n" style="color:%s">%d</span><div><b>%s</b><div class="mut big">%s</div></div></div>' % (col, len(names), lab, desc)
    if key=='evolve':
        body += '<div class="mut big" style="margin-bottom:8px">Bisharp <b>or</b> Pawniard &rarr; <b>Kingambit</b> &middot; Spritzee &rarr; <b>Aromatisse</b> &mdash; verified in your bag, both candy-only.</div>'
    body += '<div class="names">' + ''.join('<span>%s</span>' % E(n) for n in names) + '</div></div>'

open('art_dex.html','w',encoding='utf-8').write(page('dex','Hundo Dex Tracker',
    'Every perfect you own, and exactly what is left &mdash; tiered by how you actually get it.', body))

# ---------- 2. COLLECTION SNAPSHOT ----------
b = '<div class="kpis">'
_kpis = [('In bag', bag, 'var(--ink)'), ('Kept', keep, 'var(--grn)'),
         ('Tagged to transfer', pile, 'var(--red)'), ('Dex hundos', hundo_n, 'var(--gold)')]
if STORAGE:
    _kpis.append(('Storage free', STORAGE - bag, 'var(--cyan)'))
for lab, v, col in _kpis:
    b += '<div class="kpi"><div class="v" style="color:%s">%s</div><div class="l">%s</div></div>' % (col, format(v, ','), lab)
b += '</div>'
if STORAGE:
    _free = STORAGE - bag
    _pctu = min(100.0, bag / STORAGE * 100)
    _col = '#34d27b' if _pctu < 75 else ('#ff9f43' if _pctu < 92 else '#ff6b6b')
    b += '<h2>Storage</h2><div class="card">'
    # the width WAS an unformatted '%.1f%%' literal -> broken CSS, bar never filled. Now interpolated.
    b += ('<div class="bar" style="height:14px"><i style="width:%.1f%%;background:linear-gradient(90deg,%s,#ffd23f)"></i></div>'
          % (_pctu, _col))
    b += ('<div class="mut" style="margin-top:8px"><b>%s</b> / %s used (%.0f%%) &middot; <b>%s</b> slots free'
          ' &middot; cap read live from the game</div></div>'
          % (format(bag, ','), format(STORAGE, ','), _pctu, format(_free, ',')))
else:
    b += ('<h2>Storage</h2><div class="card"><div class="mut">Storage cap unknown &mdash; run '
          '<code>python read_player_state.py</code> (with PoGo open) to read it live from the game.</div></div>')
b += '<h2>Trophy census &mdash; what is in the bag</h2><div class="grid">'
order=['Shiny','Hundo 100%','Shiny hundo','Nundo 0%','Gigantamax','Dynamax','Shadow','Purified','Lucky','XXL','XXS','Costume','Location card','Mighty']
for lab in order:
    b += '<div class="cell"><span class="t">%s</span><span class="n">%s</span></div>' % (lab, format(census[lab],','))
b += '</div>'
b += '<h2>Server tags &mdash; synced to your phone</h2><div class="card">'
mx=max(tags.values()) or 1
tcol={'Hundo':'#ff6ad5','Event':'#3fe0c4','Legacy Moves':'#34d27b','XXL':'#ff9f43','GL IV':'#5b9dff','UL IV':'#5b9dff',
      'Nundo':'#b07cf0','Traded by E+F':'#ffd23f','Evolve 1':'#16a085','Evolve 2':'#16a085','Evolve Shiny':'#ffd23f','Transfer':'#ff6b6b'}
for nm,ct in sorted(tags.items(), key=lambda x:-x[1]):
    col=tcol.get(nm,'#5b9dff')
    b += ('<div class="tagrow"><span class="nm">%s</span><span class="ct">%d</span>'
          '<span class="bar"><i style="width:%.1f%%;background:%s"></i></span></div>' % (E(nm), ct, ct/mx*100, col))
b += '</div>'
open('art_collection.html','w',encoding='utf-8').write(page('snapshot','Collection Snapshot',
    'One glance at the whole collection &mdash; bag, keepers, trophies, and the live phone tags.', b))

# ---------- 3. KEEP LATTICE ----------
lat = '''<svg width="100%" viewBox="0 0 720 300" font-family="inherit">
<defs><marker id="ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto">
<path d="M0,0 L6,3 L0,6 Z" fill="#34d27b"/></marker></defs>
<!-- arrows up -->
<g stroke="#34d27b" stroke-width="2" fill="none" marker-end="url(#ar)" opacity="0.7">
<line x1="360" y1="232" x2="220" y2="150"/><line x1="360" y1="232" x2="360" y2="150"/><line x1="360" y1="232" x2="500" y2="150"/>
<line x1="220" y1="118" x2="360" y2="70"/><line x1="360" y1="118" x2="360" y2="70"/><line x1="500" y1="118" x2="360" y2="70"/>
</g>
<g text-anchor="middle">
<rect class="lat-node" x="300" y="232" width="120" height="44" rx="10"/><text class="lat-lbl" x="360" y="259">plain</text>
<rect class="lat-node" x="160" y="118" width="120" height="44" rx="10"/><text class="lat-lbl" x="220" y="145">shiny</text>
<rect class="lat-node" x="300" y="118" width="120" height="44" rx="10"/><text class="lat-lbl" x="360" y="145">Dmax / Gmax</text>
<rect class="lat-node" x="440" y="118" width="120" height="44" rx="10"/><text class="lat-lbl" x="500" y="145">costume / bg</text>
<rect class="lat-node" x="300" y="26" width="120" height="44" rx="10" stroke="#ffd23f"/><text class="lat-lbl" x="360" y="53" fill="#ffd23f">shiny + Dmax + &hellip;</text>
<text x="585" y="44" fill="#34d27b" font-size="13" font-weight="700">richer</text>
<text x="585" y="262" fill="#8a95ab" font-size="13" font-weight="700">plainer</text>
</g>
</svg>'''
b = '<div class="card">' + lat + ('<div class="mut big" style="margin-top:6px">'
    '&#11014;&#65039; <b style="color:var(--grn)">Collapse only ever goes UP.</b> A plain with no special trait is absorbed by a strictly richer, '
    'higher-IV sibling of the same species+gender. <b style="color:var(--ink)">Specials are NEVER absorbed</b> &mdash; a shiny / Gmax / '
    'Dmax / costume / bg is limited by its own CAP, never deleted by a richer copy. Hundos and every hard axis are immune.</div></div>')

b += '<h2>The keep axes &mdash; how many mons each one protects right now</h2><div class="card">'
LBL={'variant_floor':'Variant floor (top-N per cosmetic)','shiny':'Shiny (cap per form)','hundo':'Hundo 100%','rarity':'Legendary / rare',
'legacy':'Legacy move','xxl':'XXL showcase','shadow_best':'Best shadow','dex_only_copy':'Only copy (dex)','location_card':'Location card',
'adventure_effect':'Adventure Effect','pvp_rank':'PvP rank &le;5','gl_iv':'Great League','ul_iv':'Ultra League','nundo':'Nundo 0%',
'origin':'Lucky/traded (E+F)','evolve_1':'Evolve (advisory)','pvp_spread':'PvP spread trophy','protected':'Protected keep-all',
'evolve_2':'Evolve 2 (advisory)','mighty':'Mighty',
'pvp_best_gl':'Best GL of species/form','pvp_best_ul':'Best UL of species/form'}
COL={'hundo':'#ff6ad5','shiny':'#ffd23f','variant_floor':'#5b9dff','rarity':'#ff6b6b','legacy':'#34d27b','xxl':'#ff9f43',
'pvp_rank':'#3fe0c4','gl_iv':'#3fe0c4','ul_iv':'#3fe0c4','nundo':'#b07cf0','location_card':'#ff9f43','shadow_best':'#9b59b6',
'pvp_best_gl':'#3fe0c4','pvp_best_ul':'#3fe0c4'}
mx=max(reasons.values()) or 1
for r,ct in sorted(reasons.items(), key=lambda x:-x[1]):
    if r in ('evolve_1','evolve_2'): continue
    b += ('<div class="tagrow"><span class="nm" style="width:230px">%s</span><span class="ct">%d</span>'
          '<span class="bar"><i style="width:%.1f%%;background:%s"></i></span></div>'
          % (LBL.get(r,r), ct, ct/mx*100, COL.get(r,'#5b9dff')))
b += '</div>'
b += ('<h2>Two rules people always ask about</h2><div class="card big">'
      '<p><b style="color:var(--gold)">PvP keeps by RANK, not IV size.</b> A 0/15/15 can be a league #1 while a 15/15/15 is mediocre &mdash; '
      'low attack lets a mon hit a higher level under the CP cap, so it ends up bulkier. We keep top-5 rank in GL or UL for any species that '
      'can actually reach the cap.</p>'
      '<p style="margin-bottom:0"><b style="color:var(--gold)">Shinies are never culled by a richer shiny.</b> A richer shiny only out-ranks at a '
      'contested cap slot &mdash; it can&rsquo;t reach down and delete the others. Collapse goes up, never sideways or down.</p></div>')
open('art_lattice.html','w',encoding='utf-8').write(page('lattice','Keep Lattice',
    'Why anything gets tagged &mdash; the dominance lattice and every keep axis, drawn from the live engine.', b))

# ---------- 4. UPGRADES ----------
# Everything the collection would gain from an action you can take, with what it costs and whether you can pay
# today (user 2026-09-20: "i want to keep upgrading and optimizing my pokemon as well"). Nothing is recomputed
# here: each block is the SAME function the cull already runs, so this page and the cull log cannot disagree.
def _load(p, d):
    try:
        return json.load(open(os.path.join('system', 'analysis', p), encoding='utf-8'))
    except Exception:
        return d

_inv = _load('inventory.json', {})
# THIS WALK'S BALANCE, OR SAY SO (2026-09-29, H04). The walk writes stardust/coins as None when it could not read them
# ("never a 0 that downstream code would believe", 2026-09-19) and keeps the OLD file when the whole read failed; this
# page turned the first into "0 stardust" and showed the second as today's balance.
try:                                                   # the ONE "written by this walk" rule (evolvable_forms._walk_fresh)
    import evolvable_forms as _efw
    _inv_old = bool(_inv) and not _efw._walk_fresh(os.path.join('system', 'analysis', 'inventory.json'), 7200,
                                                    con.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0])
except Exception:
    _inv_old = False
_money = lambda v: '{:,}'.format(v) if isinstance(v, int) else '?'
_dust, _coins = _inv.get('stardust'), _inv.get('coins')
_rare = (_inv.get('items') or {}).get('RareCandy')
_rare = _rare if isinstance(_rare, int) else '?'         # unread is '?', never a 0 he would believe (R-B review)
_promises = _load('promises.json', {})
_shgate = _load('shiny_gated.json', [])
_cshort = _load('candy_short.json', [])
_ishort = _load('item_short.json', [])

try:
    import game_opportunities as _go, showcase_plan as _sp
    _gr = _go._rows()
    import granular_tags as _gtx
    _sm_tag = _gtx.second_move_ones(_gr)                 # the tag's own set: rank 1-N, meta gate, evolve-labelled copies excluded (2026-09-29)
    _second = [x for x in _go.second_moves(_gr) if x['uid'] in _sm_tag]
    _purify = _go.purify_to_hundo(_gr)
    _show = [e for e in _sp.evolve_to_win(_sp._rows()) if e['size'] == 5]   # XXL badge carries through (measured)
except Exception as _e:                                    # a page that renders is better than a page that 500s
    _second, _purify, _show, _gr = [], [], [], []
    print('upgrades: live blocks unavailable:', _e)

_nm = {}
for _r in con.execute('SELECT uid_hex, species_name, iv_total FROM pokemon WHERE in_bag=1'):
    _nm[_r['uid_hex']] = (_r['species_name'], _r['iv_total'] or 0)


def _rowsblk(title, sub, rows_html, n):
    return ('<div class="tierhead"><span class="n">%d</span><b>%s</b></div><div class="sub">%s</div>'
            '<table class="t"><tbody>%s</tbody></table>' % (n, E(title), sub, rows_html or
            '<tr><td class="mut">nothing here right now</td></tr>'))


_b = ['<div class="card"><b>What you can spend</b><div class="names" style="margin-top:8px">'
      '<span>%s stardust</span><span>%s coins</span><span>%s Rare Candy</span>%s</div></div>'
      % (_money(_dust), _money(_coins), _rare,
         ('<span class="mut">read %s -- NOT by this walk; not today\'s balance</span>' % E(str(_inv.get('read_at'))))
         if _inv_old else '')]

_r1 = ''.join('<tr><td><b>%s</b> %d%%</td><td class="mut">&rarr; %s</td></tr>'
              % (E(_nm.get(u, ('?', 0))[0]), _nm.get(u, ('?', 0))[1] * 100 // 45, E(', '.join(t)))
              for u, t in sorted(_promises.items(), key=lambda kv: -_nm.get(kv[0], ('', 0))[1]))
_b.append(_rowsblk('Evolve now', 'The engine reserved a slot at the later stage and you can pay for it today. '
                   'These carry the <b>Evolve to Mid</b> / <b>Evolve to Final</b> chip in game.', _r1, len(_promises)))

_free = [e for e in _show if not e['is_my_best_there']]
_r2 = ''.join('<tr><td><b>%s</b> %.2fm</td><td class="mut">&rarr; %s</td><td>z %.1f</td><td>%s</td></tr>'
              % (E(e['species']), e['height_m'], E(e['target']), e['z_after'],
                 '<span style="color:var(--gold)">free</span>' if not e['is_my_best_there']
                 else '<span class="mut">costs your best at its own stage</span>')
              for e in sorted(_show, key=lambda x: -x['z_after'])[:40])
_b.append(_rowsblk('Win showcases', 'XXL pre-evos whose evolved copy would out-score your best entry at the '
                   'target, under the game&rsquo;s own 800/150/50 formula. <b>%d</b> of them do not cost your best '
                   'entry at their own stage.' % len(_free), _r2, len(_show)))

_r3 = ''.join('<tr><td><b>%s</b></td><td class="mut">%s #%d</td><td>%s dust + %d candy</td><td>%s</td></tr>'
              % (E(x['species']), E(x['league']), x['rank'], '{:,}'.format(x['dust']), x['candy'],
                 '<span style="color:var(--gold)">affordable</span>' if x['affordable'] else
                 ('<span class="mut">balance not read this walk</span>' if x['affordable'] is None else '<span class="mut">short</span>'))
              for x in sorted(_second, key=lambda x: (x['rank'], x['dust'])))
_b.append(_rowsblk('Unlock a second charged move', 'Ranked 1&ndash;5 at their own stage in a league they can '
                   'actually enter, still on one charged move &mdash; the cheapest real PvP upgrade you own.',
                   _r3, len(_second)))

_r4 = ''.join('<tr><td><b>%s</b> %d%%</td><td class="mut">&rarr; %s</td><td>%s</td></tr>'
              % (E(x['species']), (x['iv'] or 0) * 100 // 45, E(x['target']), E(x['need'] or '?'))
              for x in _shgate)
_r4 += ''.join('<tr><td><b>%s</b> %d%%</td><td class="mut">&rarr; evolve</td><td>%s more candy</td></tr>'
               % (E(x['species']), (x['iv'] or 0) * 100 // 45, x.get('candy_left'))
               for x in _cshort)
_b.append(_rowsblk('Blocked on an item, a condition or candy',
                   'Held, not released &mdash; being short is temporary and a release is not. Each line names '
                   'exactly what it is waiting for.', _r4, len(_shgate) + len(_cshort) + len(_ishort)))

if _purify:
    _r5 = ''.join('<tr><td><b>%s</b></td><td class="mut">purify &rarr; hundo at a stage that has none</td></tr>'
                  % E(x['species'] if isinstance(x, dict) else str(x)) for x in _purify)
    _b.append(_rowsblk('Purify into a hundo', 'A shadow whose purified IVs land at 100% for a stage you have '
                       'no hundo of.', _r5, len(_purify)))

open('art_upgrades.html', 'w', encoding='utf-8').write(page(
    'upgrades', 'Upgrades',
    'Every improvement available to the collection right now, with what it costs and whether you can pay for it.',
    ''.join(_b)))

con.close()
for f in ('art_dex.html','art_collection.html','art_lattice.html','art_upgrades.html'):
    print('wrote', f, '%.0f KB' % (os.path.getsize(f)/1024))
