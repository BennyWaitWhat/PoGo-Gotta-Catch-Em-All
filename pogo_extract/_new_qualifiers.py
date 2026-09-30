"""Find in-bag specimens that QUALIFY for a tag (by rule) but are NOT currently
tagged (auth_tag_names). These are new qualifiers from recent catches/evolutions/
hatches. Read-only — just reports."""
import sqlite3, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

RULES = {
    'Hundos':   "iv_total=45",
    '0-15-15':  "iv_atk=0 AND iv_def=15 AND iv_sta=15",
    'Hatched':  "hatched_from_egg=1",
    'GL':       "gl_rank=1",
    'Lucky':    "is_lucky=1",
    'Shiny':    "fresh_shiny=1",
    'Shadow':   "fresh_alignment=1",
    'Purified': "fresh_alignment=2",
    'Legendary':"is_legendary=1",
    'Mythical': "is_mythical=1",
    'Traded':   "(is_traded=1 OR is_traded_flag_v2=1)",
    'Nundos':   "is_zero=1 AND pokemon_id!=0",
    'Dynamax':  "fresh_bread_mode=1",
    'Gigantamax':"fresh_bread_mode=2",
    'Background':"fresh_has_location_card=1",
    'Adventure Eff':"adventure_effects_left>0",
}

def tagged_set(c, name):
    return {r[0] for r in c.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND (';'||COALESCE(auth_tag_names,'')||';') LIKE ?",
        (f'%;{name};%',))}

def jumbo_keep(c):
    rows = c.execute("""SELECT uid_hex,pokemon_id,form,weight_kg,height_m FROM pokemon
                        WHERE in_bag=1 AND pokemon_size_category=5""").fetchall()
    by=defaultdict(list)
    for r in rows: by[(r[1],r[2] or 0)].append(r)
    keep=set()
    for k,rs in by.items():
        for r in sorted(rs,key=lambda x:x[3],reverse=True)[:2]: keep.add(r[0])
        for r in sorted(rs,key=lambda x:x[4],reverse=True)[:2]: keep.add(r[0])
    return keep

c=sqlite3.connect('pokemon.db')
total_new=0
for name, rule in RULES.items():
    qual={r[0] for r in c.execute(f"SELECT uid_hex FROM pokemon WHERE in_bag=1 AND ({rule})")}
    tag=tagged_set(c,name)
    new=qual-tag
    if new:
        total_new+=len(new)
        print(f'\n{name}: {len(new)} new qualifier(s)')
        for u in new:
            r=c.execute("SELECT species_name,cp,iv_total,iv_atk,iv_def,iv_sta,level,fresh_shiny FROM pokemon WHERE uid_hex=?",(u,)).fetchone()
            sh='★' if r[7] else ' '
            print(f'   {u} {sh} {r[0]:<15} cp={r[1]:>4} {r[3]}/{r[4]}/{r[5]} ({r[2]}) L{r[6]}')

# JUMBO special
jk=jumbo_keep(c); jt=tagged_set(c,'JUMBO')
jnew=jk-jt; jrem=jt-jk
if jnew or jrem:
    print(f'\nJUMBO: +{len(jnew)} new top-2, -{len(jrem)} no-longer-top-2')
    for u in jnew:
        r=c.execute("SELECT species_name,cp,weight_kg,height_m FROM pokemon WHERE uid_hex=?",(u,)).fetchone()
        print(f'   ADD  {u} {r[0]:<14} cp={r[1]} w={r[2]:.1f} h={r[3]:.1f}')
    for u in jrem:
        r=c.execute("SELECT species_name,cp,weight_kg,height_m FROM pokemon WHERE uid_hex=?",(u,)).fetchone()
        print(f'   DROP {u} {r[0]:<14} cp={r[1]} w={r[2]:.1f} h={r[3]:.1f}')
    total_new+=len(jnew)

print(f'\nTotal new tag applications needed: {total_new} (+ JUMBO drops {len(jrem)})')
c.close()
