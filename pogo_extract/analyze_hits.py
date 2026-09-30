"""Analyze the hit distribution to better understand what's a real binding."""
import json
from collections import Counter

with open('tag_bindings_full_raw.json') as f:
    d = json.load(f)

print(f'Total hits: {len(d["all_hits"])}')
print(f'Valid: {len(d["valid"])}')

# Show marker distribution
marker_counts = Counter(h['marker'] for h in d['all_hits'])
print('\nTop 20 markers (field +0x1c) over all hits:')
for m, c in marker_counts.most_common(20):
    print(f'  {m}: {c}')

# Show marker distribution for valid hits
valid_marker_counts = Counter(h['marker'] for h in d['valid'])
print('\nTop 20 markers among VALID hits:')
for m, c in valid_marker_counts.most_common(20):
    print(f'  {m}: {c}')

# tag_id distribution for valid
tid_counts = Counter(h['tag_id'] for h in d['valid'])
print(f'\ntag_id distribution (valid): {dict(tid_counts)}')

# Show some invalid hits with valid uid in db but tag_id outside 0-15
print('\nSample of valid UID + invalid tag_id hits:')
import sqlite3
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
c.execute('SELECT uid FROM pokemon')
known = set(r[0] for r in c.fetchall())
for h in d['all_hits']:
    if h['uid'] in known and not (0 <= h['tag_id'] <= 15):
        print(f'  uid={h["uid_hex"]} tag_id={h["tag_id"]} marker={h["marker"]} addr={h["addr"]}')
        # Only show first few
        break

# Show some hits with UID NOT in db (sub-object overlap)
unknown_uid = [h for h in d['all_hits'] if h['uid'] not in known][:5]
print('\nSample unknown-UID hits:')
for h in unknown_uid:
    print(f'  addr={h["addr"]} uid={h["uid_hex"]} tag_id={h["tag_id"]} marker={h["marker"]}')
