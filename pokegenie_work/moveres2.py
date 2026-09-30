import sqlite3, json, pickle
from collections import defaultdict, Counter
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
con = sqlite3.connect(BASE + r'\pogo_extract\pokemon.db')
con.row_factory = sqlite3.Row; cur = con.cursor()
gm = json.load(open(BASE + r'\pogo_extract\pvpoke_gamemaster.json'))
mv_name = {m['moveId']: m['name'] for m in gm['moves']}

def norm_tok(s):
    if s is None: s = ''
    return str(s).lower().replace(' ', '').replace('-', '').replace('_', '')

forms = defaultdict(lambda: {'f': set(), 'c': set()})
bydex = defaultdict(lambda: {'f': set(), 'c': set()})
byname = defaultdict(lambda: {'f': set(), 'c': set()})
for p in gm['pokemon']:
    sid = norm_tok(p['speciesId'])
    forms[sid]['f'] |= set(p['fastMoves']); forms[sid]['c'] |= set(p['chargedMoves'])
    bydex[p['dex']]['f'] |= set(p['fastMoves']); bydex[p['dex']]['c'] |= set(p['chargedMoves'])
    byname[norm_tok(p['speciesName'])]['f'] |= set(p['fastMoves'])
    byname[norm_tok(p['speciesName'])]['c'] |= set(p['chargedMoves'])

def candset(r):
    sp = norm_tok(r['species_name']); reg = norm_tok(r['form_region']); frm = norm_tok(r['form'])
    for key in [sp + reg, sp + frm, sp]:
        if key in forms: return forms[key]
    if sp in byname: return byname[sp]
    return bydex.get(r['pokemon_id'])

rows = cur.execute("SELECT pokemon_id,species_name,form,form_region,move1,move2,move3 FROM pokemon WHERE in_bag=1").fetchall()

# Per-ROW observations: a row gives (move1 in fastset), (move2 in chargeset), (move3 in chargeset),
# AND move2 != move3 as moveIds. Build candidate sets per integer (separate fast vs charge namespaces;
# but integers are globally unique in PoGo, so fast ints and charge ints never collide -> keep separate maps).
fast_cand = {}   # int -> set of possible moveIds (running intersection)
charge_cand = {}
# Also track, per row, the pair (m2,m3) for distinctness constraint
charge_pairs = []
for r in rows:
    cs = candset(r)
    f, c = set(cs['f']), set(cs['c'])
    if r['move1']:
        fast_cand[r['move1']] = fast_cand.get(r['move1'], set(f)) & f if r['move1'] in fast_cand else set(f)
    if r['move2']:
        charge_cand[r['move2']] = charge_cand.get(r['move2'], set(c)) & c if r['move2'] in charge_cand else set(c)
    if r['move3']:
        charge_cand[r['move3']] = charge_cand.get(r['move3'], set(c)) & c if r['move3'] in charge_cand else set(c)
    if r['move2'] and r['move3'] and r['move2'] != r['move3']:
        charge_pairs.append((r['move2'], r['move3'], frozenset(c)))

# Constraint propagation on charge_cand using distinctness within same form's charge set.
# Rebuild full per-row charge candidate lists for AC-3 style narrowing.
charge_rows = []  # list of (intA,intB, allowed_set) for distinct pairs
for a, b, allowed in charge_pairs:
    charge_rows.append((a, b, allowed))

def propagate(cand, pair_constraints):
    changed = True
    rounds = 0
    while changed and rounds < 50:
        changed = False; rounds += 1
        # singletons
        fixed = {i: next(iter(v)) for i, v in cand.items() if len(v) == 1}
        # distinctness: for a pair (a,b), if a is fixed, b cannot be that value
        for a, b, allowed in pair_constraints:
            if a in fixed and fixed[a] in cand.get(b, set()):
                cand[b].discard(fixed[a]); changed = True
            if b in fixed and fixed[b] in cand.get(a, set()):
                cand[a].discard(fixed[b]); changed = True
        # also: within allowed set, a and b together; if allowed has exactly 2 and both share, etc (skip)
    return cand

charge_cand = propagate(charge_cand, charge_rows)

def report(cand, label):
    solid = {i: next(iter(v)) for i, v in cand.items() if len(v) == 1}
    amb = {i: sorted(v) for i, v in cand.items() if len(v) != 1}
    print('%s: solid %d / %d ; ambiguous %d' % (label, len(solid), len(cand), len(amb)))
    return solid, amb

fsolid, famb = report(fast_cand, 'FAST')
csolid, camb = report(charge_cand, 'CHARGE')
print('--- ambiguous FAST ---')
for i, v in sorted(famb.items()):
    print(' ', i, [mv_name[x] for x in v])
print('--- ambiguous CHARGE (first 40) ---')
for i, v in sorted(camb.items())[:40]:
    print(' ', i, [mv_name[x] for x in v])

pickle.dump({'fast_cand': {k: set(v) for k, v in fast_cand.items()},
             'charge_cand': {k: set(v) for k, v in charge_cand.items()},
             'fsolid': fsolid, 'csolid': csolid, 'famb': famb, 'camb': camb,
             'charge_pairs': charge_pairs},
            open(BASE + r'\pokegenie_work\moveres2.pkl', 'wb'))
