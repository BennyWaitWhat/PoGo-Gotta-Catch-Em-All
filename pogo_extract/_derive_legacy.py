import sqlite3, json
from collections import defaultdict

DB='pokemon.db'
JSON='legacy_accurate.json'
LEGACY_TXT='system/analysis/tagsets/3_Legacy_Moves.txt'
TRANSFER_TXT='system/analysis/tagsets/6_Transfer.txt'

c=sqlite3.connect(DB); c.row_factory=sqlite3.Row

# JSON uid set (string compare verbatim)
jd=json.load(open(JSON))
jset=set(x['uid_hex'] for x in jd)

# pull candidate rows: in_bag=1 AND uid_hex in json set
ph=','.join('?'*len(jset))
jlist=list(jset)
rows=c.execute(
  f"SELECT uid_hex, pokemon_id, form, iv_total, cp, is_shiny, species_name "
  f"FROM pokemon WHERE in_bag=1 AND uid_hex IN ({ph})", jlist
).fetchall()
print('candidate rows (in_bag=1 AND in json):', len(rows))

# group by (pokemon_id, form OR 0)
groups=defaultdict(list)
for r in rows:
    key=(r['pokemon_id'], r['form'] if r['form'] is not None else 0)
    groups[key].append(r)

# per group top-4 by (iv_total DESC, cp DESC). tie-break uid_hex for determinism.
derived=set()
for key, lst in groups.items():
    lst_sorted=sorted(lst, key=lambda r:(-r['iv_total'], -r['cp'], r['uid_hex']))
    for r in lst_sorted[:4]:
        derived.add(r['uid_hex'])

print('groups:', len(groups))
print('derived (before subtract):', len(derived))

# load transfer set
with open(TRANSFER_TXT) as f:
    transfer=set(l.strip() for l in f if l.strip())
print('transfer set:', len(transfer))

# subtract transfer
derived_final = derived - transfer
print('derived_final (after subtract transfer):', len(derived_final))

# load the file under test
with open(LEGACY_TXT) as f:
    filed=[l.strip() for l in f if l.strip()]
fileset=set(filed)
print('file lines:', len(filed), 'unique:', len(fileset))

extra = fileset - derived_final     # in file, not derived
missing = derived_final - fileset   # derived, not in file
print('EXTRA (file - derived):', len(extra))
print('MISSING (derived - file):', len(missing))
print('MATCH:', len(extra)==0 and len(missing)==0)

# dump context for discrepancies
def ctx(uid):
    r=c.execute("SELECT uid_hex,pokemon_id,form,species_name,iv_total,cp,is_shiny,in_bag FROM pokemon WHERE uid_hex=?", (uid,)).fetchone()
    if not r: return f"{uid} NOT-IN-DB"
    injson = uid in jset
    intrans = uid in transfer
    return (f"{uid} id={r['pokemon_id']} form={r['form']} {r['species_name']} "
            f"iv={r['iv_total']} cp={r['cp']} shiny={r['is_shiny']} in_bag={r['in_bag']} "
            f"in_json={injson} in_transfer={intrans}")

print('\n--- EXTRA (in file, not in my derived set) ---')
for u in list(extra)[:8]: print(' ', ctx(u))
print('\n--- MISSING (in my derived set, not in file) ---')
for u in list(missing)[:8]: print(' ', ctx(u))

# extra diagnostics: for any discrepancy, show the full group to explain ranking
import itertools
def show_group_for(uid):
    r=c.execute("SELECT pokemon_id,form FROM pokemon WHERE uid_hex=?", (uid,)).fetchone()
    if not r: return
    pid, frm = r['pokemon_id'], (r['form'] if r['form'] is not None else 0)
    key=(pid,frm)
    lst=groups.get(key,[])
    lst_sorted=sorted(lst, key=lambda x:(-x['iv_total'], -x['cp'], x['uid_hex']))
    print(f"  GROUP pid={pid} form={frm} size={len(lst)} (top-4 kept):")
    for i,x in enumerate(lst_sorted):
        mark='KEEP' if i<4 else 'drop'
        intr = x['uid_hex'] in transfer
        print(f"    [{i}] {mark} {x['uid_hex']} iv={x['iv_total']} cp={x['cp']} shiny={x['is_shiny']} in_transfer={intr}")

alldisc=list(extra)+list(missing)
seen=set()
print('\n--- GROUP DETAIL for discrepancy uids ---')
for u in alldisc[:8]:
    r=c.execute("SELECT pokemon_id,form FROM pokemon WHERE uid_hex=?", (u,)).fetchone()
    if not r: continue
    k=(r['pokemon_id'], r['form'] if r['form'] is not None else 0)
    if k in seen: continue
    seen.add(k)
    show_group_for(u)
