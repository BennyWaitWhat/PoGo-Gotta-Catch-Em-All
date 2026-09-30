import sqlite3, json
from collections import defaultdict
c=sqlite3.connect('pokemon.db'); c.row_factory=sqlite3.Row
jd=json.load(open('legacy_accurate.json')); jset=set(x['uid_hex'] for x in jd)
ph=','.join('?'*len(jset)); jlist=list(jset)
rows=c.execute(f"SELECT uid_hex,pokemon_id,form,iv_total,cp,is_shiny FROM pokemon WHERE in_bag=1 AND uid_hex IN ({ph})", jlist).fetchall()
groups=defaultdict(list)
for r in rows:
    groups[(r['pokemon_id'], r['form'] or 0)].append(r)

# 1) Tie sensitivity at the top-4 cut: is the keep/drop boundary ever a (iv,cp) tie?
ambiguous=0
ambig_groups=[]
for key,lst in groups.items():
    s=sorted(lst, key=lambda r:(-r['iv_total'],-r['cp'],r['uid_hex']))
    if len(s)>4:
        last_keep=(s[3]['iv_total'], s[3]['cp'])
        first_drop=(s[4]['iv_total'], s[4]['cp'])
        if last_keep==first_drop:
            ambiguous+=1
            ambig_groups.append((key,[(x['uid_hex'],x['iv_total'],x['cp']) for x in s]))
print('groups with >4 members:', sum(1 for l in groups.values() if len(l)>4))
print('groups where slot4 vs slot5 is an (iv,cp) TIE (tiebreak-sensitive):', ambiguous)
for g in ambig_groups[:10]:
    print('  ', g)

# 2) Was subtract meaningful? intersection of derived-before-subtract with transfer
with open('system/analysis/tagsets/6_Transfer.txt') as f:
    transfer=set(l.strip() for l in f if l.strip())
derived=set()
for key,lst in groups.items():
    for r in sorted(lst, key=lambda r:(-r['iv_total'],-r['cp'],r['uid_hex']))[:4]:
        derived.add(r['uid_hex'])
print('derived-before-subtract INTERSECT transfer:', len(derived & transfer))

# 3) NEW RULE sanity: are any shinies in the transfer file? (should be 0 per "all shinies kept")
ph2=','.join('?'*len(transfer)); tlist=list(transfer)
shiny_in_transfer=c.execute(f"SELECT COUNT(*) FROM pokemon WHERE is_shiny=1 AND uid_hex IN ({ph2})", tlist).fetchone()[0]
print('shinies present in 6_Transfer.txt:', shiny_in_transfer)

# 4) confirm none of the final 200 are shiny-excluded incorrectly: how many derived_final are shiny
final=derived-transfer
ph3=','.join('?'*len(final)); flist=list(final)
shiny_final=c.execute(f"SELECT COUNT(*) FROM pokemon WHERE is_shiny=1 AND uid_hex IN ({ph3})", flist).fetchone()[0]
print('shinies kept in final 200:', shiny_final)
