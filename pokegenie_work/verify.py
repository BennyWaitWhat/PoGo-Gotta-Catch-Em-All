import sqlite3, json, pickle
from collections import defaultdict, Counter
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
con = sqlite3.connect(BASE + r'\pogo_extract\pokemon.db')
con.row_factory = sqlite3.Row; cur = con.cursor()
gm = json.load(open(BASE + r'\pogo_extract\pvpoke_gamemaster.json'))
mv_name = {m['moveId']: m['name'] for m in gm['moves']}
P = pickle.load(open(BASE + r'\pokegenie_work\moveres_final.pkl', 'rb'))
FAST, CHARGE = P['FAST'], P['CHARGE']
fast_vote, charge_vote = P['fast_vote'], P['charge_vote']

def norm_tok(s):
    if s is None: s = ''
    return str(s).lower().replace(' ', '').replace('-', '').replace('_', '')

# Examine the actual SPECIES carrying each low-confidence integer to confirm winner by reasoning.
def show_carriers(intcol, mid, slot_label, limit=12):
    rows = cur.execute(
        "SELECT species_name, form, form_region, move1, move2, move3 FROM pokemon WHERE in_bag=1 AND %s=? LIMIT ?" % intcol,
        (mid, limit)).fetchall()
    sps = Counter()
    for r in rows:
        sps[(r['species_name'], r['form_region'])] += 1
    print('  [%s id=%d] carriers:' % (slot_label, mid), dict(sps))

# Low-confidence FAST: 224, 243
print('=== FAST 224 (winner=%s) ===' % mv_name[FAST[224]])
show_carriers('move1', 224, 'fast')
print('  full vote:', [(mv_name[m], c) for m, c in fast_vote[224].most_common(6)])
print('=== FAST 243 (winner=%s) ===' % mv_name[FAST[243]])
show_carriers('move1', 243, 'fast')
print('  full vote:', [(mv_name[m], c) for m, c in fast_vote[243].most_common(6)])

# Low-confidence CHARGE: 33,125,292,293,91,391
for mid in (33, 125, 292, 293, 91, 391):
    print('=== CHARGE %d (winner=%s) ===' % (mid, mv_name[CHARGE[mid]]))
    rows = cur.execute("SELECT species_name, form_region FROM pokemon WHERE in_bag=1 AND (move2=? OR move3=?) LIMIT 10", (mid, mid)).fetchall()
    print('  carriers:', dict(Counter((r['species_name'], r['form_region']) for r in rows)))
    print('  vote:', [(mv_name[m], c) for m, c in charge_vote[mid].most_common(6)])

# Now: are the "GT cannot produce" charge moves actually present in the bag under a different winner?
# Map each such GT name to its gamemaster moveId, then check if that moveId is the winner of SOME int,
# OR if some int's vote includes it strongly.
gt_missing = ['Acrobatics','Bleakwind Storm','Fell Stinger','Fusion Flare','High Horsepower',
 'High Jump Kick','Ice Burn','Octazooka','Sacred Fire','Sandsear Storm','Sparkling Aria',
 'Synchronoise','Volt Tackle','Weather Ball Water']
name2id = {v: k for k, v in mv_name.items()}
# normalize gm names to compare
def pg(n):
    n=n.replace('(','').replace(')','')
    while '  ' in n: n=n.replace('  ',' ')
    n=n.strip().replace('Future Sight','Futuresight').replace('Superpower','Super Power').replace('Techno Blast Douse','Techno Blast Water')
    return n
pg2id = {}
for mid_str, nm in mv_name.items():
    pg2id[pg(nm)] = mid_str
print('\n=== Are GT-missing charge moves present in any bag mon? ===')
for nm in gt_missing:
    mvid = pg2id.get(nm)
    if not mvid:
        print('  %-20s -> NO gamemaster moveId (synthetic/typed)' % nm); continue
    # is this moveId the winner of any int? is it in any int's vote?
    won = [i for i, w in CHARGE.items() if w == mvid]
    voted = [(i, charge_vote[i][mvid]) for i in charge_vote if mvid in charge_vote[i]]
    # does any BAG mon's form actually list this move? count bag mons whose form has it
    print('  %-20s moveId=%-22s winnerOfInts=%s votedInInts=%s' % (nm, mvid, won, voted[:5]))
