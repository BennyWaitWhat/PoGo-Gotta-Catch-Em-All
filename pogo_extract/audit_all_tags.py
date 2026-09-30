"""Read-only audit: for each rule-based tag, compute rule-set from DB and diff vs server
membership (auth_tag_names). Prints to-add / to-remove per tag. Run AFTER a pipeline
refresh so auth_tag_names + ranks + legacy are current."""
import json, sqlite3
from collections import defaultdict

c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row; cur = c.cursor()
rows = [dict(r) for r in cur.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
gm = json.load(open('pvpoke_gamemaster.json'))
by_sid = {p['speciesId']: p for p in gm['pokemon']}

def has_tag(p, name):
    a = p['auth_tag_names']
    return bool(a) and name in [t for t in a.split(';') if t]

def server_set(name):
    return {p['uid_hex'] for p in rows if has_tag(p, name)}

# --- rule sets ---
def rule_hundos():   return {p['uid_hex'] for p in rows if p['iv_total'] == 45}
def rule_nundos():   return {p['uid_hex'] for p in rows if p['iv_total'] == 0}
def rule_01515():    return {p['uid_hex'] for p in rows if p['iv_atk']==0 and p['iv_def']==15 and p['iv_sta']==15}
def rule_background(): return {p['uid_hex'] for p in rows if (p['fresh_has_location_card'] or 0)==1}
def rule_adveff():   return {p['uid_hex'] for p in rows if (p['fresh_pokemon_badge'] or 0)!=0}
def rule_owner(owner):
    return {p['uid_hex'] for p in rows
            if ((p['is_traded_flag_v2'] or 0)==1 or p['is_lucky']) and (p['original_owner_name'] or '').lower()==owner}
def rule_legacy():
    try: return {e['uid_hex'] for e in json.load(open('legacy_accurate.json'))}
    except FileNotFoundError: return None
def rule_jumbo():
    g=defaultdict(list)
    for p in rows:
        if (p['pokemon_size_category'] or 0)==5:
            g[(p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)].append(p)
    out=set()
    for l in g.values():
        for p in sorted(l, key=lambda x:-(x['weight_kg'] or 0))[:2]: out.add(p['uid_hex'])
        for p in sorted(l, key=lambda x:-(x['height_m'] or 0))[:2]: out.add(p['uid_hex'])
    return out
CPM=0.84029999
_cp={}
def maxcp(sid):
    if sid in _cp: return _cp[sid]
    p=by_sid.get(sid); v=None
    if p:
        bs=p.get('baseStats',{}); v=max(10,int(((bs.get('atk',0)+15)*(bs.get('def',0)+15)**0.5*(bs.get('hp',0)+15)**0.5*CPM**2)/10))
    _cp[sid]=v; return v
def rule_league(rank_col, stage_col, pct_col, cpmin, strict):
    g=defaultdict(list)
    for p in rows:
        r=p[rank_col]
        if r is None or r>10: continue
        st=p[stage_col]
        if not st: continue
        cp=maxcp(st)
        if cp is None: continue
        if (cp>cpmin) if strict else (cp>=cpmin): g[p['pokemon_id']].append(p)
    out=set()
    for l in g.values():
        for p in sorted(l, key=lambda x:(x[rank_col], -(x[pct_col] or 0)))[:2]: out.add(p['uid_hex'])
    return out

AUDIT = [
    ('Hundos', rule_hundos()),
    ('Nundos', rule_nundos()),
    ('0-15-15', rule_01515()),
    ('JUMBO', rule_jumbo()),
    ('GL', rule_league('gl_rank','gl_stage','gl_pct',1425,False)),
    ('UL', rule_league('ul_rank','ul_stage','ul_pct',2425,True)),
    ('Background', rule_background()),
    ('Adventure Eff', rule_adveff()),
    ('From Ethan', rule_owner('ethanmateovz')),
    ('From Florandez', rule_owner('florandez')),
    ('Legacy', rule_legacy()),
]
print(f"{'Tag':16s} {'server':>7} {'rule':>6} {'add':>5} {'remove':>7}  status")
print('-'*60)
drift = {}
for name, ruleset in AUDIT:
    if ruleset is None:
        print(f'{name:16s}   (rule data missing - skipped)'); continue
    srv = server_set(name)
    add = ruleset - srv; rem = srv - ruleset
    status = 'OK' if not add and not rem else 'DRIFT'
    print(f'{name:16s} {len(srv):>7} {len(ruleset):>6} {len(add):>5} {len(rem):>7}  {status}')
    if add or rem: drift[name] = (sorted(add), sorted(rem))
json.dump({k:{'add':v[0],'remove':v[1]} for k,v in drift.items()}, open('tag_drift.json','w'))
print(f"\nDrifted tags: {list(drift.keys())}  (details -> tag_drift.json)")
