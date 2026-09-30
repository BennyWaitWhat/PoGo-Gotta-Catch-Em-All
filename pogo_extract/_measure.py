import json, sqlite3
from collections import Counter
before = set(json.load(open('_before_tf.json')))
after = set(open('system/analysis/tagsets/6_Transfer.txt').read().split())
reasons = json.load(open('system/analysis/policy_reasons.json'))
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row
def det(uids):
    o = [c.execute('SELECT species_name,form,iv_total,is_shiny,is_lucky,was_best_buddy_badge,gender,pokemon_id FROM pokemon WHERE uid_hex=?', (u,)).fetchone() for u in uids]
    return [r for r in o if r]
newly = after - before; rescued = before - after
nd = det(newly)
print(f'TRANSFER {len(before)} -> {len(after)}   (+{len(newly)} newly culled, -{len(rescued)} rescued)')
print(f'  newly: shiny={sum(r["is_shiny"] or 0 for r in nd)} lucky={sum(r["is_lucky"] or 0 for r in nd)} '
      f'hundo={sum(1 for r in nd if r["iv_total"]==45)} bestbuddy={sum(1 for r in nd if r["was_best_buddy_badge"]==1)} '
      f'maxIV={max((r["iv_total"] or 0 for r in nd), default=0)}')
print('  newly top species:', dict(Counter(r['species_name'] for r in nd).most_common(20)))
luck = [(r['species_name'], r['iv_total']) for r in nd if r['is_lucky']]
print(f'  LUCKY among newly-culled ({len(luck)}):', luck[:40])

ge = [u for u, rs in reasons.items() if 'gender_evo' in rs]
print(f'\ngender_evo protects {len(ge)}:')
for u in ge:
    r = c.execute('SELECT species_name,gender,iv_total,is_shiny FROM pokemon WHERE uid_hex=?', (u,)).fetchone()
    g = 'M' if r['gender'] == 1 else 'F' if r['gender'] == 2 else '?'
    print(f'    {r["species_name"]:<10} {g} iv{r["iv_total"]}{" SHINY" if r["is_shiny"] else ""}')

bulb = c.execute("SELECT uid_hex,form,iv_total,is_lucky FROM pokemon WHERE in_bag=1 AND pokemon_id=1 AND fresh_shiny=0 AND COALESCE(fresh_alignment,0)!=1 AND COALESCE(fresh_costume,0)=0 AND COALESCE(special_bg_id,0)=0 AND COALESCE(natural_art_background,0)=0 AND COALESCE(fresh_bread_mode,0)=0").fetchall()
print(f'\nBulbasaur PLAIN pool ({len(bulb)}) after form-merge:')
for r in sorted(bulb, key=lambda x: -(x['iv_total'] or 0)):
    st = 'KEEP' if r['uid_hex'] in reasons else 'XFER'
    print(f'    form{r["form"]} iv{r["iv_total"]} {"lucky" if r["is_lucky"] else ""} -> {st} {reasons.get(r["uid_hex"], [])}')
