import sqlite3
c = sqlite3.connect('pokemon.db').cursor()
print('in_bag=1:', c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1').fetchone()[0])
print('in_bag=0 (ghost):', c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=0').fetchone()[0])
print('KEEP:', c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='KEEP'").fetchone()[0])
print('TRANSFER:', c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='TRANSFER'").fetchone()[0])
print('auth_tag_names set:', c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND auth_tag_names IS NOT NULL').fetchone()[0])
print('size_category breakdown:')
for r in c.execute('SELECT pokemon_size_category, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY pokemon_size_category ORDER BY 1'):
    print(f'  {r[0]}: {r[1]}')
print('shadow:', c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_alignment=1').fetchone()[0])
print('shiny:', c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_shiny=1').fetchone()[0])
print('hundo:', c.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND is_hundo=1').fetchone()[0])
print('top transfer species:')
for r in c.execute("SELECT species_name, COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='TRANSFER' GROUP BY species_name ORDER BY 2 DESC LIMIT 10"):
    print(f'  {r[0]:20s} {r[1]}')
