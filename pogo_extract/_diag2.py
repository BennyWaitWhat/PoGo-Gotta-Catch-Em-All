import sqlite3
from collections import Counter
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row

print('=== A. COMBEE individuals + Vespiquen ownership ===')
for r in c.execute("SELECT gender,gender_name,form,fresh_costume,iv_total,is_shiny FROM pokemon WHERE in_bag=1 AND pokemon_id=415 ORDER BY gender"):
    print(f"  g={r['gender']}({r['gender_name']}) form={r['form']} costume={r['fresh_costume']} iv={r['iv_total']} {'SHINY' if r['is_shiny'] else ''}")
print('  Vespiquen(416) owned in_bag:', c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND pokemon_id=416").fetchone()[0])

print('\n=== B. SALANDIT individuals + Salazzle ownership ===')
for r in c.execute("SELECT gender,gender_name,form,iv_total,is_shiny FROM pokemon WHERE in_bag=1 AND pokemon_id=757"):
    print(f"  g={r['gender']}({r['gender_name']}) form={r['form']} iv={r['iv_total']} {'SHINY' if r['is_shiny'] else ''}")
print('  Salazzle(758) owned in_bag:', c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND pokemon_id=758").fetchone()[0])

print('\n=== C. other gender-locked evos: do they own the result? ===')
for src, dst, dn in ((361,478,'Froslass'),(281,475,'Gallade'),(412,413,'Wormadam'),(412,414,'Mothim'),(757,758,'Salazzle'),(415,416,'Vespiquen')):
    print(f"  own {dn}({dst}):", c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND pokemon_id=?", (dst,)).fetchone()[0])

print('\n=== D. FORM-0 quirk (species with NO regional forms) ===')
for pid, name in ((1,'Bulbasaur'),(4,'Charmander'),(7,'Squirtle'),(133,'Eevee'),(16,'Pidgey'),(10,'Caterpie'),(63,'Abra')):
    fc = Counter(r['form'] for r in c.execute("SELECT form FROM pokemon WHERE in_bag=1 AND pokemon_id=?", (pid,)))
    print(f"  {name} (pid {pid}): {dict(fc)}")

print('\n=== E. genuine regional / multi-form (should stay distinct) ===')
for pid, name in ((37,'Vulpix'),(52,'Meowth'),(19,'Rattata'),(745,'Lycanroc'),(479,'Rotom')):
    rows = c.execute("SELECT form,form_region,COUNT(*) n FROM pokemon WHERE in_bag=1 AND pokemon_id=? GROUP BY form", (pid,)).fetchall()
    print(f"  {name} (pid {pid}): " + ', '.join(f"f{r['form']}/{r['form_region']}={r['n']}" for r in rows))

print('\n=== F. form-0 prevalence + quirk-split species ===')
z = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (form=0 OR form IS NULL)").fetchone()[0]
nz = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND form!=0 AND form IS NOT NULL").fetchone()[0]
print(f"  in_bag form0/null={z}  form!=0={nz}")
both = c.execute("""SELECT species_name,
  SUM(CASE WHEN form=0 OR form IS NULL THEN 1 ELSE 0 END) z,
  SUM(CASE WHEN form!=0 AND form IS NOT NULL THEN 1 ELSE 0 END) nz
  FROM pokemon WHERE in_bag=1 GROUP BY pokemon_id HAVING z>0 AND nz>0 ORDER BY z+nz DESC""").fetchall()
print(f"  species split across BOTH form-0 and non-zero: {len(both)}")
for r in both[:15]: print(f"      {r['species_name']}: form0={r['z']} nonzero={r['nz']}")

print('\n=== G. gender=NULL species (capture gaps on gendered mons) ===')
for r in c.execute("SELECT species_name,pokemon_id,COUNT(*) n FROM pokemon WHERE in_bag=1 AND gender IS NULL GROUP BY pokemon_id ORDER BY n DESC LIMIT 15"):
    print(f"  {r['species_name']} (pid {r['pokemon_id']}): {r['n']}")
