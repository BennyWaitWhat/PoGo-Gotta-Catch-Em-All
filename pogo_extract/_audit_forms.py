"""Deep audit: does the keep engine account for every FORM and GENDER? Read-only."""
import sqlite3, json, os
from collections import Counter, defaultdict
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
reasons = json.load(open('system/analysis/policy_reasons.json')) if os.path.exists('system/analysis/policy_reasons.json') else {}
transfer = set(open('system/analysis/tagsets/6_Transfer.txt').read().split()) if os.path.exists('system/analysis/tagsets/6_Transfer.txt') else set()
def kept(u): return u in reasons
def why(u): return ','.join(reasons.get(u, [])) if isinstance(reasons.get(u), list) else str(reasons.get(u, ''))

print('=== 1. GENDER population (in_bag) ===')
for r in c.execute("SELECT gender, gender_name, COUNT(*) n FROM pokemon WHERE in_bag=1 GROUP BY gender ORDER BY gender"):
    print(f'  gender={r["gender"]} ({r["gender_name"]}): {r["n"]}')

GLOCK = [
 (415, 'Combee',   'F -> Vespiquen; M is a DEAD-END'),
 (757, 'Salandit', 'F -> Salazzle; M dead-end'),
 (361, 'Snorunt',  'F -> Froslass; either -> Glalie'),
 (281, 'Kirlia',   'M -> Gallade; either -> Gardevoir'),
 (280, 'Ralts',    '(carries the Kirlia/Gallade gender need)'),
 (412, 'Burmy',    'F -> Wormadam; M -> Mothim'),
 (678, 'Meowstic', 'M/F are different forms (movepool)'),
 (876, 'Indeedee', 'M/F different forms'),
 (902, 'Basculegion','M/F different forms'),
 (668, 'Pyroar',   'F visual form'),
]
print('\n=== 2. GENDER-LOCKED / gender-as-form species (in_bag) ===')
for pid, name, note in GLOCK:
    rows = c.execute("SELECT uid_hex,gender_name,form,iv_total,is_shiny FROM pokemon WHERE in_bag=1 AND pokemon_id=?", (pid,)).fetchall()
    if not rows:
        print(f'  {name} (pid {pid}): NONE in bag   [{note}]'); continue
    byg = defaultdict(list)
    for r in rows: byg[r['gender_name'] or '?'].append(r)
    forms = sorted({r['form'] for r in rows})
    print(f'  {name} (pid {pid}): {len(rows)} in bag, forms={forms}   [{note}]')
    for g, lst in sorted(byg.items()):
        lst.sort(key=lambda r: -(r['iv_total'] or 0))
        nk = sum(1 for r in lst if kept(r['uid_hex']))
        nt = sum(1 for r in lst if r['uid_hex'] in transfer)
        sh = ' SHINY' if any(r['is_shiny'] for r in lst) else ''
        topwhy = why(lst[0]['uid_hex'])
        print(f'      {g:<11} n={len(lst):<3} topIV={lst[0]["iv_total"]:<3} kept={nk}/{len(lst)} transfer={nt}  top-reason=[{topwhy}]{sh}')

print('\n=== 3. ROCKRUFF / LYCANROC line (forms + ranks) ===')
for pid, name in ((744, 'Rockruff'), (745, 'Lycanroc')):
    rows = c.execute("SELECT form,form_region,gl_rank,ul_rank,iv_total,is_shiny,uid_hex FROM pokemon WHERE in_bag=1 AND pokemon_id=?", (pid,)).fetchall()
    if not rows:
        print(f'  {name} (pid {pid}): NONE'); continue
    byf = defaultdict(list)
    for r in rows: byf[(r['form'], r['form_region'])].append(r)
    print(f'  {name} (pid {pid}): {len(rows)} in bag, {len(byf)} distinct form(s)')
    for (f, reg), lst in byf.items():
        ranked = sum(1 for r in lst if r['gl_rank'] is not None)
        nk = sum(1 for r in lst if kept(r['uid_hex']))
        sh = ' has-shiny' if any(r['is_shiny'] for r in lst) else ''
        print(f'      form={f} region={reg}: n={len(lst)} maxIV={max(r["iv_total"] or 0 for r in lst)} ranked={ranked}/{len(lst)} kept={nk}/{len(lst)}{sh}')

print('\n=== 4. UNRANKED in_bag forms (ranker form-map gaps) ===')
un = c.execute("SELECT species_name,pokemon_id,form,form_region,COUNT(*) n FROM pokemon WHERE in_bag=1 AND (gl_rank IS NULL OR ul_rank IS NULL) GROUP BY pokemon_id,form ORDER BY species_name").fetchall()
print(f'  {len(un)} (pid,form) groups unranked:')
for r in un: print(f'      {r["species_name"]} (pid {r["pokemon_id"]} form {r["form"]} region {r["form_region"]}): {r["n"]}')

print('\n=== 5. species with >1 distinct form in bag ===')
mf = c.execute("SELECT species_name,pokemon_id,COUNT(DISTINCT form) nf FROM pokemon WHERE in_bag=1 GROUP BY pokemon_id HAVING nf>1 ORDER BY nf DESC, species_name").fetchall()
print(f'  {len(mf)} species have multiple forms in bag:')
for r in mf: print(f'      {r["species_name"]} (pid {r["pokemon_id"]}): {r["nf"]} forms')
