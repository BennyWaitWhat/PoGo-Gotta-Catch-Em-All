import sqlite3, json, pickle
from collections import defaultdict, Counter
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
con = sqlite3.connect(BASE + r'\pogo_extract\pokemon.db')
con.row_factory = sqlite3.Row; cur = con.cursor()

# Check rows carrying charge id 322 and 323: are they shadow / purified?
for mid in (322, 323):
    rows = cur.execute(
        "SELECT fresh_alignment, is_lucky, COUNT(*) c FROM pokemon WHERE in_bag=1 AND (move2=? OR move3=?) GROUP BY fresh_alignment",
        (mid, mid)).fetchall()
    print('charge', mid, ':')
    for r in rows:
        print('   fresh_alignment=', r['fresh_alignment'], 'count=', r['c'])

# Also: what fraction of rows have move2 in {322,323}? and check column for shadow flag name
cur.execute("PRAGMA table_info(pokemon)")
cols = [c[1] for c in cur.fetchall()]
align_cols = [c for c in cols if 'align' in c.lower() or 'shadow' in c.lower() or 'purif' in c.lower()]
print('alignment-ish columns:', align_cols)

# Distribution of fresh_alignment overall
print('fresh_alignment distribution in bag:')
for r in cur.execute("SELECT fresh_alignment, COUNT(*) c FROM pokemon WHERE in_bag=1 GROUP BY fresh_alignment"):
    print('  ', dict(r))

# How many bag mons are shadow vs purified, and how many carry 322/323?
n322 = cur.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (move2=322 OR move3=322)").fetchone()[0]
n323 = cur.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (move2=323 OR move3=323)").fetchone()[0]
print('bag carrying 322:', n322, ' carrying 323:', n323)
