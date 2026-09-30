import sqlite3, json, pickle
from collections import defaultdict, Counter
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
con = sqlite3.connect(BASE + r'\pogo_extract\pokemon.db')
con.row_factory = sqlite3.Row; cur = con.cursor()
gm = json.load(open(BASE + r'\pogo_extract\pvpoke_gamemaster.json'))
mv_name = {m['moveId']: m['name'] for m in gm['moves']}
P = pickle.load(open(BASE + r'\pokegenie_work\moveres_final.pkl', 'rb'))
FAST, CHARGE, fast_vote, charge_vote = P['FAST'], P['CHARGE'], P['fast_vote'], P['charge_vote']

# FAST cannot-produce: Present, Water Shuriken. Are 291 / 373 in bag and what's their winner?
for mid in (291, 373):
    inbag = cur.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND move1=?", (mid,)).fetchone()[0]
    print('fast id', mid, 'winner=', mv_name[FAST[mid]] if mid in FAST else 'NOT IN BAG',
          'inbag=', inbag, 'vote=', [(mv_name[m], c) for m, c in fast_vote.get(mid, Counter()).most_common(5)])
    if inbag:
        rows = cur.execute("SELECT species_name, form_region FROM pokemon WHERE in_bag=1 AND move1=? LIMIT 8", (mid,)).fetchall()
        print('   carriers:', dict(Counter((r['species_name'], r['form_region']) for r in rows)))

# 291: Present vs Quick Attack. Present is Delibird/event-only. Which species carry 291 in bag?
# 373: Bubble/Feint Attack/Water Shuriken (Greninja). Check carriers.

# ---- Hidden Power: how does ground truth populate quickMove + hiddenPowerType together? ----
data = json.load(open(BASE + r'\pokegenie_work\extracted\scan_data.json'))
print('\n=== Ground-truth Hidden Power entries (quickMove + hiddenPowerType + IVs) ===')
n = 0
for e in data:
    if e.get('quickMove') == 'Hidden Power':
        a, d, s = e.get('avgAttackIV'), e.get('avgDefenseIV'), e.get('avgStaminaIV')
        print('  name=%-12s hpType=%-8s IV(a/d/s)=%s/%s/%s' % (
            e.get('pokemonName'), repr(e.get('hiddenPowerType')), a, d, s))
        n += 1
        if n >= 18: break

# Does DB store HP type anywhere, or must we compute from IVs? Check move id 281 carriers' columns.
print('\n=== DB columns that might hold HP type ===')
cur.execute("PRAGMA table_info(pokemon)")
allcols = [c[1] for c in cur.fetchall()]
hpcols = [c for c in allcols if 'hidden' in c.lower() or 'hp_type' in c.lower() or 'power_type' in c.lower()]
print('candidate HP-type columns:', hpcols)
# Sample a few 281 carriers with their IVs
rows = cur.execute("SELECT species_name, iv_atk, iv_def, iv_sta, move1 FROM pokemon WHERE in_bag=1 AND move1=281 LIMIT 8").fetchall()
print('281 carriers sample:', [(r['species_name'], r['iv_atk'], r['iv_def'], r['iv_sta']) for r in rows])
