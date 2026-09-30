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

# FREQUENCY VOTING: for each integer, count candidate moveIds across all carrier rows (union, weighted).
fast_vote = defaultdict(Counter); charge_vote = defaultdict(Counter)
fast_n = Counter(); charge_n = Counter()
for r in rows:
    cs = candset(r); f, c = cs['f'], cs['c']
    if r['move1']:
        for m in f: fast_vote[r['move1']][m] += 1
        fast_n[r['move1']] += 1
    if r['move2']:
        for m in c: charge_vote[r['move2']][m] += 1
        charge_n[r['move2']] += 1
    if r['move3']:
        for m in c: charge_vote[r['move3']][m] += 1
        charge_n[r['move3']] += 1

# A correct moveId should appear in EVERY carrier row's candidate set (support == n) IF gamemaster
# is complete. Legacy moves break this. So: best candidate = highest support fraction.
def best(vote, n):
    out = {}
    for i, cnt in vote.items():
        tot = n[i]
        ranked = cnt.most_common()
        topmove, topc = ranked[0]
        # support fraction
        out[i] = (topmove, topc / tot, tot, [(mv_name[m], c, round(c / tot, 3)) for m, c in ranked[:4]])
    return out

fb = best(fast_vote, fast_n); cb = best(charge_vote, charge_n)

# Distinctness sanity: for charge, if best(m2)==best(m3) for the SAME row's pair, that's a violation.
# Count violations of current frequency assignment.
viol = 0
for r in rows:
    if r['move2'] and r['move3'] and r['move2'] != r['move3']:
        if cb.get(r['move2'], (None,))[0] == cb.get(r['move3'], (None,))[0]:
            viol += 1
print('charge distinctness violations under frequency assignment:', viol)

# Report low-confidence (support fraction < 0.99) ones - these need manual/registry confirmation.
print('=== FAST low-confidence (frac<0.999) ===')
for i in sorted(fb):
    m, frac, tot, top = fb[i]
    if frac < 0.999:
        print(' ', i, '->', mv_name[m], 'frac=%.3f n=%d' % (frac, tot), top)
print('=== CHARGE low-confidence (frac<0.999) ===')
for i in sorted(cb):
    m, frac, tot, top = cb[i]
    if frac < 0.999:
        print(' ', i, '->', mv_name[m], 'frac=%.3f n=%d' % (frac, tot), top)

pickle.dump({'fb': fb, 'cb': cb}, open(BASE + r'\pokegenie_work\moveres3.pkl', 'wb'))
print('TOTAL fast ints:', len(fb), ' charge ints:', len(cb))
