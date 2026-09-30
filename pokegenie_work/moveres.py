import sqlite3, json, pickle
from collections import defaultdict, Counter
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
con = sqlite3.connect(BASE + r'\pogo_extract\pokemon.db')
con.row_factory = sqlite3.Row; cur = con.cursor()
gm = json.load(open(BASE + r'\pogo_extract\pvpoke_gamemaster.json'))
mv_name = {m['moveId']: m['name'] for m in gm['moves']}

def norm_tok(s):
    if s is None:
        s = ''
    s = str(s)
    return s.lower().replace(' ', '').replace('-', '').replace('_', '')

forms = defaultdict(lambda: {'f': set(), 'c': set(), 'sid': []})
bydex = defaultdict(lambda: {'f': set(), 'c': set()})
byname = defaultdict(lambda: {'f': set(), 'c': set()})
for p in gm['pokemon']:
    sid = norm_tok(p['speciesId'])
    forms[sid]['f'] |= set(p['fastMoves']); forms[sid]['c'] |= set(p['chargedMoves'])
    forms[sid]['sid'].append(p['speciesId'])
    bydex[p['dex']]['f'] |= set(p['fastMoves']); bydex[p['dex']]['c'] |= set(p['chargedMoves'])
    byname[norm_tok(p['speciesName'])]['f'] |= set(p['fastMoves'])
    byname[norm_tok(p['speciesName'])]['c'] |= set(p['chargedMoves'])

def candset(r):
    sp = norm_tok(r['species_name']); reg = norm_tok(r['form_region']); frm = norm_tok(r['form'])
    for key in [sp + reg, sp + frm, sp]:
        if key in forms:
            return forms[key]
    if sp in byname:
        return byname[sp]
    return bydex.get(r['pokemon_id'])

rows = cur.execute("SELECT pokemon_id,species_name,form,form_region,move1,move2,move3 FROM pokemon WHERE in_bag=1").fetchall()
fast_int = defaultdict(list); charge_int = defaultdict(list)
nocand = 0
for r in rows:
    cs = candset(r)
    if not cs:
        nocand += 1; continue
    if r['move1']: fast_int[r['move1']].append(frozenset(cs['f']))
    if r['move2']: charge_int[r['move2']].append(frozenset(cs['c']))
    if r['move3']: charge_int[r['move3']].append(frozenset(cs['c']))
print('rows with no candidate form:', nocand)

def resolve(intmap):
    res = {}
    for mid, sets in intmap.items():
        inter = set.intersection(*[set(s) for s in sets])
        if len(inter) == 1:
            res[mid] = (list(inter)[0], 'inter1', len(sets))
        elif len(inter) == 0:
            res[mid] = (None, 'empty', len(sets))
        else:
            res[mid] = (sorted(inter), 'multi', len(sets))
    return res

fres = resolve(fast_int); cres = resolve(charge_int)
solidF = sum(1 for v in fres.values() if v[1] == 'inter1')
solidC = sum(1 for v in cres.values() if v[1] == 'inter1')
print('FORM-AWARE: fast solid %d/%d, charge solid %d/%d' % (solidF, len(fres), solidC, len(cres)))
pickle.dump({'fres': fres, 'cres': cres,
             'fast_int': {k: [set(x) for x in v] for k, v in fast_int.items()},
             'charge_int': {k: [set(x) for x in v] for k, v in charge_int.items()}},
            open(BASE + r'\pokegenie_work\moveres.pkl', 'wb'))
print('still ambiguous fast:', sorted([k for k, v in fres.items() if v[1] != 'inter1']))
print('still ambiguous charge count:', sum(1 for v in cres.values() if v[1] != 'inter1'))
