"""AUTHORITATIVE league audit — corrected form IDs verified against
form_category.json AND the live bag. Supersedes _ml_top25*.py / _ul_top25*.py
which had swapped/wrong forms (Zacian, Zamazenta, Kyurem, Necrozma, Moltres).

ML  = open Master League (no CP cap) → best specimen = highest IV, then level.
UL  = Ultra League (2500 cap) → DB ul_rank/ul_pct give the optimal-IV ranking.

Form encoding (verified):
  Zacian   2576=CrownedSword 2577=Hero
  Zamazenta 2578=CrownedShield 2579=Hero
  Kyurem   146=Normal 147=Black 148=White
  Necrozma 2717=Normal 2718=DuskMane 2719=DawnWings
  Palkia   1859=Normal 2830=Origin    Dialga 1856=Normal 2829=Origin
  Meloetta 151=Aria   Moltres 2799=Galarian  Ninetales 58=Alola
  Zygarde  2592=50% 2593=Complete
  (single-form species: form=None → match any incl legacy form 0)
"""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

MOVES = {int(k): v for k, v in json.load(open('move_id_to_name.json')).items()}
def pm(m):
    if not m: return ''
    return MOVES.get(m, '').replace('_FAST', '').replace('_', ' ').title().replace('Of', 'of').replace('The', 'the')

XL = {50.0:0, 49.5:20, 49.0:40, 48.5:57, 48.0:74, 47.5:91, 47.0:108, 46.5:123, 46.0:138,
      45.5:153, 45.0:168, 44.5:181, 44.0:194, 43.5:207, 43.0:220, 42.5:232, 42.0:244,
      41.5:256, 41.0:268, 40.5:279, 40.0:290}
def xl_to(cur, tgt=50.0):
    if cur >= tgt or tgt <= 40.0: return 0
    return max(0, XL.get(max(cur,40.0),290) - XL.get(tgt,0))
def dust_to(cur, tgt, purified=False):
    if cur >= tgt: return 0
    halves=(tgt-cur)*2
    avg = 25000 if tgt>45 else 19000 if tgt>40 else 13000 if tgt>35 else 10000
    d=int(halves*avg)
    return int(d*0.9) if purified else d

def fbuild(form):
    if form is None: return '1'           # match all
    if isinstance(form, (list,tuple)): return 'form IN (' + ','.join(str(x) for x in form) + ')'
    return f'form={form}'

c = sqlite3.connect('pokemon.db')

# ---------------- MASTER LEAGUE ----------------
# (rank, label, score, species, form, align('np'|'shadow'), ideal_moves)
ML = [
 (1,'Zacian Crowned Sword',99.1,'Zacian',2576,'np',('Metal Claw','Close Combat','Behemoth Blade')),
 (2,'Palkia Origin',98.8,'Palkia',2830,'np',('Dragon Breath','Aqua Tail','Spacial Rend')),
 (3,'Metagross',96.6,'Metagross',None,'np',('Shadow Claw','Meteor Mash','Earthquake')),
 (4,'Xerneas',95.2,'Xerneas',None,'np',('Geomancy','Close Combat','Moonblast')),
 (5,'Zamazenta Crowned Shield',94.8,'Zamazenta',2578,'np',('Ice Fang','Close Combat','Behemoth Bash')),
 (6,'Kyurem White',94.7,'Kyurem',148,'np',('Dragon Breath','Fusion Flare','Ice Burn')),
 (7,'Dialga Origin',94.4,'Dialga',2829,'np',('Dragon Breath','Roar of Time','Iron Head')),
 (8,'Lunala',94.2,'Lunala',None,'np',('Shadow Claw','Shadow Ball','Moonblast')),
 (9,'Reshiram',94.1,'Reshiram',None,'np',('Dragon Breath','Fusion Flare','Draco Meteor')),
 (10,'Kyurem Black',92.9,'Kyurem',147,'np',('Dragon Tail','Freeze Shock','Fusion Bolt')),
 (11,'Zekrom',92.6,'Zekrom',None,'np',('Dragon Breath','Outrage','Fusion Bolt')),
 (12,'Marshadow',92.0,'Marshadow',None,'np',('Shadow Claw','Close Combat','Ice Punch')),
 (13,'Kyogre',91.8,'Kyogre',None,'np',('Waterfall','Avalanche','Origin Pulse')),
 (14,'Palkia Shadow',90.9,'Palkia',1859,'shadow',('Dragon Breath','Aqua Tail','Draco Meteor')),
 (15,'Lugia',90.7,'Lugia',None,'np',('Dragon Tail','Aeroblast','Fly')),
 (16,'Eternatus',90.5,'Eternatus',None,'np',('Dragon Tail','Dynamax Cannon','Flamethrower')),
 (17,'Lugia Shadow',89.9,'Lugia',None,'shadow',('Dragon Tail','Aeroblast','Fly')),
 (18,'Metagross Shadow',89.7,'Metagross',None,'shadow',('Shadow Claw','Meteor Mash','Earthquake')),
 (19,'Necrozma Dawn Wings',89.3,'Necrozma',2719,'np',('Shadow Claw','Dark Pulse','Moongeist Beam')),
 (20,'Yveltal',89.0,'Yveltal',None,'np',('Sucker Punch','Dark Pulse','Oblivion Wing')),
 (21,'Ho-Oh',88.5,'Ho-Oh',None,'np',('Incinerate','Brave Bird','Sacred Fire')),
 (22,'Necrozma Dusk Mane',88.2,'Necrozma',2718,'np',('Shadow Claw','Dark Pulse','Sunsteel Strike')),
 (23,'Garchomp',87.9,'Garchomp',None,'np',('Dragon Tail','Twister','Earth Power')),
 (24,'Groudon',87.8,'Groudon',None,'np',('Dragon Tail','Fire Punch','Precipice Blades')),
 (25,'Meloetta Aria',87.7,'Meloetta',151,'np',('Confusion','Psyshock','Dazzling Gleam')),
]

def align_sql(a):
    return 'fresh_alignment=1' if a=='shadow' else 'fresh_alignment IN (0,2)'

print('='*135)
print('MASTER LEAGUE (no CP cap) — best owned specimen per PVPoke top 25, correct forms')
print('='*135)
print(f'{"#":<3}{"Sc":>5}  {"Pokemon":<24}{"Status":<13}{"Lv":>5} {"IVs":<9}{"CP":>6}  XL/Dust→50        Moveset gap')
print('-'*135)
ml_ready=[]; ml_cheap=[]; ml_invest=[]; ml_missing=[]
for rank,label,score,sp,form,al,ideal in ML:
    where=f"species_name='{sp}' AND {fbuild(form)} AND {align_sql(al)}"
    r=c.execute(f'''SELECT iv_total,iv_atk,iv_def,iv_sta,level,cp,move1,move2,move3,fresh_alignment
                    FROM pokemon WHERE in_bag=1 AND ({where})
                    ORDER BY iv_total DESC, level DESC, cp DESC LIMIT 1''').fetchone()
    if not r:
        ml_missing.append((rank,label,score)); continue
    ivt,a,d,s,lvl,cp,m1,m2,m3,fa=r
    pur = fa==2
    flag='★' if ivt==45 else '+' if ivt>=42 else ' '
    altag=' P' if fa==2 else (' S' if fa==1 else '')
    cur={pm(x) for x in (m1,m2,m3) if x}
    miss=[m for m in ideal if m not in cur]
    xl=xl_to(lvl); dust=dust_to(lvl,50.0,pur)
    if lvl>=50.0:
        status='MAXED' if not miss else 'MAXED*'
        cost=''
        (ml_ready if not miss else ml_cheap).append(label)
    else:
        status=f'+{50.0-lvl:.1f}L'
        cost=f'{xl}XL/{dust//1000}k'
        (ml_cheap if xl<=140 else ml_invest).append(label)
    mg=('moves OK' if not miss else 'need: '+', '.join(miss))
    print(f'{rank:<3}{score:>5}  {flag}{label+altag:<23}{status:<13}{lvl:>5} {a}/{d}/{s}({ivt})'.ljust(54)+f'{cp:>6}  {cost:<16}  {mg}')
for rank,label,score in ml_missing:
    print(f'{rank:<3}{score:>5}    {label:<24}{"NOT OWNED":<13}')
    ml_missing  # noqa

# ---------------- ULTRA LEAGUE ----------------
UL = [
 (1,'Jellicent',95.5,'Jellicent',None,'np',47.5,('Hex','Surf','Shadow Ball')),
 (2,'Corviknight',95.4,'Corviknight',None,'np',47.0,('Sand Attack','Air Cutter','Payback')),
 (3,'Lapras',95.4,'Lapras',None,'np',40.5,('Psywave','Sparkling Aria','Ice Beam')),
 (4,'Lapras Shadow',95.0,'Lapras',None,'shadow',40.5,('Psywave','Sparkling Aria','Ice Beam')),
 (5,'Tinkaton',94.9,'Tinkaton',None,'np',50.0,('Fairy Wind','Gigaton Hammer','Bulldoze')),
 (6,'Empoleon',94.4,'Empoleon',None,'np',33.0,('Metal Sound','Hydro Cannon','Drill Peck')),
 (7,'Moltres Galarian',94.3,'Moltres',2799,'np',29.5,('Sucker Punch','Fly','Brave Bird')),
 (8,'Empoleon Shadow',94.2,'Empoleon',None,'shadow',33.0,('Metal Sound','Hydro Cannon','Drill Peck')),
 (9,'Feraligatr Shadow',93.9,'Feraligatr',None,'shadow',35.0,('Shadow Claw','Hydro Cannon','Ice Beam')),
 (10,'Malamar Shadow',93.3,'Malamar',None,'shadow',50.0,('Psywave','Foul Play','Super Power')),
 (11,'Florges',93.2,'Florges',None,'np',28.5,('Fairy Wind','Chilling Water','Disarming Voice')),
 (12,'Feraligatr',93.1,'Feraligatr',None,'np',35.0,('Shadow Claw','Hydro Cannon','Ice Beam')),
 (13,'Dondozo',93.0,'Dondozo',None,'np',32.0,('Waterfall','Surf','Outrage')),
 (14,'Virizion',92.7,'Virizion',None,'np',31.0,('Double Kick','Leaf Blade','Sacred Sword')),
 (15,'Regidrago',92.5,'Regidrago',None,'np',32.5,('Dragon Breath','Dragon Energy','Vice Grip')),
 (16,'Lickilicky',92.3,'Lickilicky',None,'np',47.0,('Rollout','Body Slam','Shadow Ball')),
 (17,'Ludicolo',92.3,'Ludicolo',None,'np',47.5,('Astonish','Weather Ball','Leaf Storm')),
 (18,'Clefable',92.1,'Clefable',None,'np',47.5,('Fairy Wind','Meteor Mash','Moonblast')),
 (19,'Blastoise',91.7,'Blastoise',None,'np',45.5,('Rollout','Hydro Cannon','Skull Bash')),
 (20,'Oranguru',91.7,'Oranguru',None,'np',47.0,('Confusion','Brutal Swing','Trailblaze')),
 (21,'Zygarde Complete',91.5,'Zygarde',2593,'np',24.0,('Dragon Tail','Crunch','Earthquake')),
 (22,'Malamar',91.4,'Malamar',None,'np',50.0,('Psywave','Foul Play','Super Power')),
 (23,'Dusknoir Shadow',91.3,'Dusknoir',None,'shadow',48.5,('Astonish','Dynamic Punch','Shadow Punch')),
 (24,'Ninetales Alolan',91.3,'Ninetales',58,'np',47.5,('Powder Snow','Weather Ball','Chilling Water')),
 (25,'Walrein',91.3,'Walrein',None,'np',38.5,('Powder Snow','Icicle Spear','Earthquake')),
]

print('\n'+'='*135)
print('ULTRA LEAGUE (2500 cap) — best owned rank-1/near-rank-1 IV per PVPoke top 25, correct forms')
print('='*135)
print(f'{"#":<3}{"Sc":>5}  {"Pokemon":<22}{"Status":<20}{"Lv→Tgt":>11} {"IVs":<9}{"CP":>6} {"rk/pct":<12} Cost / move gap')
print('-'*135)
ul_missing=[]
for rank,label,score,sp,form,al,tgt,ideal in UL:
    where=f"species_name='{sp}' AND {fbuild(form)} AND {align_sql(al)}"
    # rank-1 first; else best ul_rank
    r=c.execute(f'''SELECT iv_atk,iv_def,iv_sta,iv_total,level,cp,ul_rank,ul_pct,ul_fits_at_current_level,
                          move1,move2,move3,fresh_alignment
                    FROM pokemon WHERE in_bag=1 AND ({where}) AND ul_rank IS NOT NULL
                    ORDER BY ul_rank ASC, ul_pct DESC, level DESC LIMIT 1''').fetchone()
    if not r:
        # any specimen even without ul_rank (e.g. brand new form)
        r=c.execute(f'''SELECT iv_atk,iv_def,iv_sta,iv_total,level,cp,NULL,NULL,NULL,move1,move2,move3,fresh_alignment
                        FROM pokemon WHERE in_bag=1 AND ({where})
                        ORDER BY iv_total DESC, level DESC LIMIT 1''').fetchone()
    if not r:
        ul_missing.append((rank,label,score)); continue
    a,d,s,ivt,lvl,cp,urank,upct,ufits,m1,m2,m3,fa=r
    flag='★' if ivt==45 else '+' if ivt>=42 else ' '
    altag=' P' if fa==2 else (' S' if fa==1 else '')
    cur={pm(x) for x in (m1,m2,m3) if x}
    miss=[m for m in ideal if m not in cur]
    rk = f'rk{urank}/{upct:.0f}%' if urank else 'rk-/-'
    if ufits==0:
        status='OVERSHOT >2500'
        cost=''
    elif ufits==1 and lvl>=tgt-0.25:
        status='MET (at target)'
        cost=''
    elif ufits==1:
        status=f'powerup'
        xl=xl_to(lvl,tgt); dust=dust_to(lvl,tgt,fa==2)
        cost=(f'{xl}XL/' if xl else '')+f'{dust//1000}k'
    else:
        status='check'
        cost=''
    mg=('moves OK' if not miss else 'need: '+', '.join(miss))
    print(f'{rank:<3}{score:>5}  {flag}{label+altag:<21}{status:<20}{f"{lvl}→{tgt}":>11} {a}/{d}/{s}({ivt})'.ljust(70)+f'{cp:>6} {rk:<12} {cost} | {mg}')
for rank,label,score in ul_missing:
    print(f'{rank:<3}{score:>5}    {label:<22}{"NOT OWNED":<20}')

c.close()
