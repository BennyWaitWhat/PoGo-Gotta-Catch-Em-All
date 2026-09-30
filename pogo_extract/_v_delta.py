"""Post-rescan delta (read-only): NEW catches since _before_rescan.json + current Transfer pile + safety."""
import sqlite3, json, os
from collections import Counter

c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
before = json.load(open('_before_rescan.json'))
before_uids = set(before['uids']); before_count = before['count']
cur = c.execute("SELECT uid_hex,species_name,iv_total,cp,is_shiny FROM pokemon WHERE in_bag=1").fetchall()
new = [r for r in cur if r['uid_hex'] not in before_uids]
print(f"NEW_CATCHES {len(new)}   bag {before_count} -> {len(cur)}")
for r in sorted(new, key=lambda x: -(x['iv_total'] or 0)):
    fl = []
    if r['is_shiny']: fl.append('SHINY')
    if (r['iv_total'] or 0) == 45: fl.append('HUNDO')
    print(f"  {r['species_name']:<16} {str(r['iv_total'] if r['iv_total'] is not None else '?'):>3}/45  CP{r['cp'] or 0}  {' '.join(fl)}")

uids = open(os.path.join('system', 'analysis', 'tagsets', '6_Transfer.txt')).read().split()
det = [c.execute('SELECT species_name,is_shiny,is_legendary,is_mythical,iv_total,was_best_buddy_badge FROM pokemon WHERE uid_hex=?', (u,)).fetchone() for u in uids]
det = [r for r in det if r]
sens = [r['species_name'] for r in det if r['is_shiny'] or (r['iv_total'] or 0) == 45 or r['is_legendary'] or r['is_mythical'] or r['was_best_buddy_badge'] == 1]
print(f"\nTRANSFER {len(det)}   maxIV {max((r['iv_total'] or 0 for r in det), default=0)}   SENSITIVE {sens}")
print("COMP " + ' '.join(f'{s}:{n}' for s, n in Counter(r['species_name'] for r in det).most_common(20)))
