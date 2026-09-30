import sqlite3, json, pickle
from collections import defaultdict, Counter
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
con = sqlite3.connect(BASE + r'\pogo_extract\pokemon.db')
con.row_factory = sqlite3.Row; cur = con.cursor()
gm = json.load(open(BASE + r'\pogo_extract\pvpoke_gamemaster.json'))
mv_name_raw = {m['moveId']: m['name'] for m in gm['moves']}
mv_type = {m['moveId']: m['type'] for m in gm['moves']}

# ---- PokeGenie display-name normalization (derived from ground truth) ----
def pg_name(gm_name):
    n = gm_name.replace('(', '').replace(')', '')
    while '  ' in n: n = n.replace('  ', ' ')
    n = n.strip()
    n = n.replace('Future Sight', 'Futuresight')
    n = n.replace('Superpower', 'Super Power')
    n = n.replace('Techno Blast Douse', 'Techno Blast Water')  # Douse drive = Water in PokeGenie
    return n

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

rows = cur.execute("SELECT pokemon_id,species_name,form,form_region,move1,move2,move3,fresh_alignment FROM pokemon WHERE in_bag=1").fetchall()

# Frequency voting (union) for fast + charge.
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

FAST = {}; CHARGE = {}
for i, cnt in fast_vote.items():
    FAST[i] = cnt.most_common(1)[0][0]
for i, cnt in charge_vote.items():
    CHARGE[i] = cnt.most_common(1)[0][0]

# Special / synthetic charged moves not in gamemaster movepools:
SPECIAL_CHARGE = {322: 'Frustration', 323: 'Return'}  # confirmed via shadow/purified alignment
# Special fast: 281 = Hidden Power (display 'Hidden Power'; element via hiddenPowerType)

# Build final int->PokeGenie-string maps.
def fast_pg(i):
    if i == 0: return ''
    if i == 281: return 'Hidden Power'  # element handled separately
    return pg_name(mv_name_raw[FAST[i]])

def charge_pg(i):
    if i == 0: return ''
    if i in SPECIAL_CHARGE: return SPECIAL_CHARGE[i]
    return pg_name(mv_name_raw[CHARGE[i]])

# Hidden Power element from the Pokemon's IVs is the official rule, BUT PoGo stores the HP type
# in the move id (281 is generic in gamemaster). Determine HP type from gamemaster? Not available.
# In PoGo the Hidden Power TYPE is computed from IVs. Derive element from IVs.
def hp_type_from_ivs(atk, dfn, sta):
    # Official Hidden Power type formula (PoGo): floor((sum of bit0 of each IV pattern)...).
    # PoGo formula: type = floor( ((a&1)+2*(d&1)+4*(s&1)+ ... ) )? Use the canonical 16-type table.
    # Standard: hp = (15 * ( (atk&1) + 2*(def&1) + 4*(sta&1) ... )) -- but PoGo uses a different one.
    pass

# Validate name coverage vs ground truth.
data = json.load(open(BASE + r'\pokegenie_work\extracted\scan_data.json'))
gt_fast = Counter(); gt_charge = Counter()
for e in data:
    if e.get('quickMove'): gt_fast[e['quickMove']] += 1
    if e.get('chargeMove'): gt_charge[e['chargeMove']] += 1
    if e.get('chargeMove2'): gt_charge[e['chargeMove2']] += 1

derived_fast_names = set(fast_pg(i) for i in FAST) | {'Hidden Power'}
derived_charge_names = set(charge_pg(i) for i in CHARGE) | set(SPECIAL_CHARGE.values())

# Which ground-truth move names can our maps NOT produce?
gt_fast_names = set(gt_fast) - {'Struggle'}
gt_charge_names = set(gt_charge) - {'Struggle'}
missing_fast = gt_fast_names - derived_fast_names
missing_charge = gt_charge_names - derived_charge_names
print('GT FAST names our table cannot produce:', sorted(missing_fast))
print('GT CHARGE names our table cannot produce:', sorted(missing_charge))
print()

# Reverse check: which derived names are NOT seen in ground truth (could indicate a wrong mapping
# OR simply a move present in bag but not in the old scans -> expected, since bag != old scans).
extra_fast = derived_fast_names - gt_fast_names - {''}
extra_charge = derived_charge_names - gt_charge_names - {''}
print('Derived FAST names NOT in ground truth (info only):', sorted(extra_fast))
print('Derived CHARGE names NOT in ground truth (info only):', sorted(extra_charge))
print()

# Confidence per fast/charge integer (frequency fraction).
def frac(vote, n, mp):
    return {i: vote[i][mp[i]] / n[i] for i in mp}
ff = frac(fast_vote, fast_n, FAST); cf = frac(charge_vote, charge_n, CHARGE)
print('FAST ints with confidence < 0.95:', {i: round(ff[i], 3) for i in ff if ff[i] < 0.95})
print('CHARGE ints with confidence < 0.95 (excl 322/323):',
      {i: round(cf[i], 3) for i in cf if cf[i] < 0.95 and i not in SPECIAL_CHARGE})

# Save the final maps as JSON for downstream use.
FAST_OUT = {str(i): fast_pg(i) for i in FAST}
FAST_OUT['281'] = 'Hidden Power'
CHARGE_OUT = {str(i): charge_pg(i) for i in CHARGE}
for i, nm in SPECIAL_CHARGE.items():
    CHARGE_OUT[str(i)] = nm
json.dump({'fast': FAST_OUT, 'charge': CHARGE_OUT}, open(BASE + r'\pokegenie_work\move_id_to_pgname.json', 'w'), indent=1)
print('\nWrote move_id_to_pgname.json  (fast %d, charge %d)' % (len(FAST_OUT), len(CHARGE_OUT)))
pickle.dump({'FAST': FAST, 'CHARGE': CHARGE, 'ff': ff, 'cf': cf, 'mv_name_raw': mv_name_raw,
             'fast_vote': dict(fast_vote), 'charge_vote': dict(charge_vote)},
            open(BASE + r'\pokegenie_work\moveres_final.pkl', 'wb'))
