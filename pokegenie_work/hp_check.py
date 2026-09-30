import sqlite3, json
from collections import Counter
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
con = sqlite3.connect(BASE + r'\pogo_extract\pokemon.db')
con.row_factory = sqlite3.Row; cur = con.cursor()

# Dump ALL columns; look for anything text-ish that could encode HP type for 281 carriers.
cur.execute("PRAGMA table_info(pokemon)")
cols = [c[1] for c in cur.fetchall()]
print('total columns:', len(cols))
# Pull a full row for a 281 (Hidden Power) carrier and print non-null fields.
r = cur.execute("SELECT * FROM pokemon WHERE in_bag=1 AND move1=281 LIMIT 1").fetchone()
print('\nFull 281-carrier row (non-empty fields):')
for k in r.keys():
    v = r[k]
    if v not in (None, '', 0):
        print('   %-30s = %r' % (k, v))

# Is move1=281 ALWAYS generic, or are there distinct fast ids 282..297 for typed HP? In old PoGo,
# Hidden Power had ONE move id and type was separate. Confirm only 281 exists for HP in bag.
hp_like = cur.execute("SELECT DISTINCT move1 FROM pokemon WHERE in_bag=1 AND move1 BETWEEN 281 AND 281").fetchall()
print('\nHP fast id present:', [x[0] for x in hp_like])

# Count 281 carriers in bag
n = cur.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND move1=281").fetchone()[0]
print('bag mons with Hidden Power (281):', n)

# Confirm in ground truth: of all quickMove=='Hidden Power', how many have empty hpType?
data = json.load(open(BASE + r'\pokegenie_work\extracted\scan_data.json'))
hp = [e for e in data if e.get('quickMove') == 'Hidden Power']
empty = sum(1 for e in hp if not e.get('hiddenPowerType'))
print('GT Hidden Power entries:', len(hp), 'of which empty hpType:', empty)
