"""Compute the N=3 commons trim set (keep strongest 3 per species/form/costume + all
specials/PvP/legacy), save it, and write tag_drift.json so reconcile_from_drift.py
tags them as CLAUDE_TX for review. No transfers."""
import json, sqlite3
from collections import defaultdict
oc = {int(k): v for k, v in json.load(open('official_class.json')).items()}
gm = json.load(open('pvpoke_gamemaster.json')); name = {}
for x in gm['pokemon']:
    if x.get('dex'): name.setdefault(x['dex'], x['speciesName'].split(' (')[0])
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1').fetchall()]
def htag(p, t):
    a = p.get('auth_tag_names') or ''; return t in [x for x in a.split(';') if x]
KEEP_TAGS = ['Hundos','Nundos','JUMBO','GL','UL','LL','Legacy','Background','Adventure Eff','From Ethan','From Florandez','0-15-15','Evolve Me']
def tagprot(p): return any(htag(p, t) for t in KEEP_TAGS)
def special(p):
    return (p['is_shiny'] or p['iv_total'] in (0, 45) or p['alignment'] in (1, 2) or p['is_lucky']
            or (p['fresh_costume'] or 0) != 0 or p['pokemon_size_category'] in (1, 5) or tagprot(p)
            or (p['gl_rank'] is not None and p['gl_rank'] <= 10) or (p['ul_rank'] is not None and p['ul_rank'] <= 10))
N = 3
com = [p for p in rows if oc.get(p['pokemon_id']) not in (1, 2, 3)]
bucket = defaultdict(list)
for p in com:
    if not special(p): bucket[(p['pokemon_id'], p['form'], p['fresh_costume'] or 0)].append(p)
trim = []
for k, ps in bucket.items():
    ps.sort(key=lambda p: -(p['cp'] or 0))
    trim += ps[N:]
rec = [{'uid_hex': p['uid_hex'], 'species': name.get(p['pokemon_id'], str(p['pokemon_id'])),
        'form': p['form'], 'cp': p['cp'], 'iv': p['iv_total']} for p in trim]
json.dump(rec, open('commons_trim_n3.json', 'w'), indent=1)
json.dump({'CLAUDE_TX': {'add': [p['uid_hex'] for p in trim], 'remove': []}}, open('tag_drift.json', 'w'))
bysp = defaultdict(int)
for p in trim: bysp[name.get(p['pokemon_id'], str(p['pokemon_id']))] += 1
print(f'commons trim set (N={N}): {len(trim)} pokemon across {len(bysp)} species')
print('  ', ', '.join(f'{n} {co}' for n, co in sorted(bysp.items(), key=lambda x: -x[1])))
print('wrote commons_trim_n3.json + tag_drift.json (CLAUDE_TX adds)')
