"""Final UL audit with CP-cap-aware, specimen-specific powerup costs.

For each owned best-IV specimen, compute the max level it can reach while
staying <= 2500 CP (using the real CPM table + cp scaling), then cost the
powerup from its current level to THAT level — not a generic target.
This fixes hundos showing bogus 'powerup to L47.5' when they cap out ~L42.
"""
import sqlite3, json, math, sys
sys.stdout.reconfigure(encoding='utf-8')

MOVES = {int(k): v for k, v in json.load(open('move_id_to_name.json')).items()}
def pm(m):
    if not m: return ''
    return MOVES.get(m, '').replace('_FAST', '').replace('_', ' ').title().replace('Of','of').replace('The','the')

CPM = [
    0.094,0.135137432,0.16639787,0.192650919,0.21573247,0.236572661,0.25572005,0.273530381,
    0.29024988,0.306057377,0.3210876,0.335445036,0.34921268,0.362457751,0.37523559,0.387592406,
    0.39956728,0.411193551,0.42250001,0.432926419,0.44310755,0.4530599578,0.46279839,0.472336083,
    0.48168495,0.4908558,0.49985844,0.508701765,0.51739395,0.525942511,0.53435433,0.542635767,
    0.55079269,0.558830576,0.56675452,0.574569153,0.58227891,0.589887907,0.59740001,0.604818814,
    0.61215729,0.619399365,0.62656713,0.633644533,0.64065295,0.647576426,0.65443563,0.661214806,
    0.667934,0.674577537,0.68116492,0.687680648,0.69414365,0.700538673,0.7068842,0.713164996,
    0.71939909,0.725571552,0.7317,0.734741009,0.73776948,0.740785574,0.74378943,0.746781211,
    0.74976104,0.752729087,0.7556855,0.758630378,0.76156384,0.764486065,0.76739717,0.770297266,
    0.7731865,0.776064962,0.77893275,0.781790055,0.78463697,0.787473578,0.79030001,0.792803968,
    0.79530001,0.797800015,0.8003,0.802799995,0.8053,0.807800014,0.81029999,0.812799985,
    0.81529999,0.81779999,0.82029998,0.82279998,0.82529997,0.82779996,0.83029996,0.83279996,
    0.83529995,0.83779995,0.84029995,0.84279995,0.84529994
]
def lvl_to_idx(L): return int(round((L-1)*2))
def idx_to_lvl(i): return 1 + i*0.5

# XL candy cumulative from level → 50 (we only need deltas)
XL = {50.0:0,49.5:20,49.0:40,48.5:57,48.0:74,47.5:91,47.0:108,46.5:123,46.0:138,45.5:153,
      45.0:168,44.5:181,44.0:194,43.5:207,43.0:220,42.5:232,42.0:244,41.5:256,41.0:268,40.5:279,40.0:290}
def xl_between(cur,tgt):
    if cur>=tgt or tgt<=40.0: return 0
    return max(0, XL.get(max(cur,40.0),290)-XL.get(tgt,0))
def dust_between(cur,tgt,pur=False):
    if cur>=tgt: return 0
    tot=0.0
    # per-half-level dust brackets (approx official)
    i=lvl_to_idx(cur)
    while idx_to_lvl(i) < tgt:
        L=idx_to_lvl(i)
        d = 10000 if L<30 else 13000 if L<35 else 19000 if L<40 else 25000 if L<45 else 35000
        tot+=d; i+=1
    return int(tot*(0.9 if pur else 1.0))

def max_level_under_cap(cp_now, level_now, cap=2500):
    """Highest level whose projected CP stays <= cap. Derives the current
    CPM from the stored level (robust to NULL/boost-mismatched cp_multiplier).
    CP scales with CPM^2, base+IV constant."""
    cpm_now = CPM[lvl_to_idx(level_now)]
    best=1.0
    for i in range(len(CPM)):
        cp_i = cp_now * (CPM[i]/cpm_now)**2
        if cp_i <= cap:
            best=idx_to_lvl(i)
    return best

UL = [
 (1,'Jellicent',95.5,'Jellicent',None,'np',('Hex','Surf','Shadow Ball')),
 (2,'Corviknight',95.4,'Corviknight',None,'np',('Sand Attack','Air Cutter','Payback')),
 (3,'Lapras',95.4,'Lapras',None,'np',('Psywave','Sparkling Aria','Ice Beam')),
 (4,'Lapras Shadow',95.0,'Lapras',None,'shadow',('Psywave','Sparkling Aria','Ice Beam')),
 (5,'Tinkaton',94.9,'Tinkaton',None,'np',('Fairy Wind','Gigaton Hammer','Bulldoze')),
 (6,'Empoleon',94.4,'Empoleon',None,'np',('Metal Sound','Hydro Cannon','Drill Peck')),
 (7,'Moltres Galarian',94.3,'Moltres',2799,'np',('Sucker Punch','Fly','Brave Bird')),
 (8,'Empoleon Shadow',94.2,'Empoleon',None,'shadow',('Metal Sound','Hydro Cannon','Drill Peck')),
 (9,'Feraligatr Shadow',93.9,'Feraligatr',None,'shadow',('Shadow Claw','Hydro Cannon','Ice Beam')),
 (10,'Malamar Shadow',93.3,'Malamar',None,'shadow',('Psywave','Foul Play','Super Power')),
 (11,'Florges',93.2,'Florges',None,'np',('Fairy Wind','Chilling Water','Disarming Voice')),
 (12,'Feraligatr',93.1,'Feraligatr',None,'np',('Shadow Claw','Hydro Cannon','Ice Beam')),
 (13,'Dondozo',93.0,'Dondozo',None,'np',('Waterfall','Surf','Outrage')),
 (14,'Virizion',92.7,'Virizion',None,'np',('Double Kick','Leaf Blade','Sacred Sword')),
 (15,'Regidrago',92.5,'Regidrago',None,'np',('Dragon Breath','Dragon Energy','Vice Grip')),
 (16,'Lickilicky',92.3,'Lickilicky',None,'np',('Rollout','Body Slam','Shadow Ball')),
 (17,'Ludicolo',92.3,'Ludicolo',None,'np',('Astonish','Weather Ball','Leaf Storm')),
 (18,'Clefable',92.1,'Clefable',None,'np',('Fairy Wind','Meteor Mash','Moonblast')),
 (19,'Blastoise',91.7,'Blastoise',None,'np',('Rollout','Hydro Cannon','Skull Bash')),
 (20,'Oranguru',91.7,'Oranguru',None,'np',('Confusion','Brutal Swing','Trailblaze')),
 (21,'Zygarde Complete',91.5,'Zygarde',2593,'np',('Dragon Tail','Crunch','Earthquake')),
 (22,'Malamar',91.4,'Malamar',None,'np',('Psywave','Foul Play','Super Power')),
 (23,'Dusknoir Shadow',91.3,'Dusknoir',None,'shadow',('Astonish','Dynamic Punch','Shadow Punch')),
 (24,'Ninetales Alolan',91.3,'Ninetales',58,'np',('Powder Snow','Weather Ball','Chilling Water')),
 (25,'Walrein',91.3,'Walrein',None,'np',('Powder Snow','Icicle Spear','Earthquake')),
]
def fbuild(form):
    if form is None: return '1'
    return f'form={form}'
def align_sql(a):
    return 'fresh_alignment=1' if a=='shadow' else 'fresh_alignment IN (0,2)'

c=sqlite3.connect('pokemon.db')
print('ULTRA LEAGUE — specimen-specific cap level + true powerup cost')
print(f'{"#":<3}{"Sc":>5} {"Pokemon":<22}{"IVs":<10}{"Lv→Cap":>11}{"CP@now":>7} {"rk/pct":<11} {"Status":<16} Cost / move gap')
print('-'*132)
ready=[]; cheap=[]; invest=[]; missing=[]
for rank,label,score,sp,form,al,ideal in UL:
    where=f"species_name='{sp}' AND {fbuild(form)} AND {align_sql(al)}"
    r=c.execute(f'''SELECT iv_atk,iv_def,iv_sta,iv_total,level,cp,cp_multiplier,ul_rank,ul_pct,
                          move1,move2,move3,fresh_alignment
                    FROM pokemon WHERE in_bag=1 AND ({where}) AND ul_rank IS NOT NULL
                    ORDER BY ul_rank ASC, ul_pct DESC, level DESC LIMIT 1''').fetchone()
    if not r:
        missing.append((rank,label,score)); continue
    a,d,s,ivt,lvl,cp,cpm,urank,upct,m1,m2,m3,fa=r
    flag='★' if ivt==45 else '+' if ivt>=42 else ' '
    altag=' P' if fa==2 else (' S' if fa==1 else '')
    cur={pm(x) for x in (m1,m2,m3) if x}
    miss=[m for m in ideal if m not in cur]
    capL = max_level_under_cap(cp, lvl, 2500)
    rk=f'rk{urank}/{upct:.0f}%'
    if cp > 2500:
        status='OVERSHOT >2500'
        cost='(too big for UL)'
        bucket = invest
    elif lvl >= capL - 0.01:
        status='AT CAP (max)'
        cost=''
        bucket = ready if not miss else cheap
    else:
        xl=xl_between(lvl,capL); dust=dust_between(lvl,capL,fa==2)
        status=f'pwr →L{capL}'
        cost=(f'{xl}XL + ' if xl else '')+f'{dust//1000}k dust'
        bucket = cheap if (xl<=110 and dust<=400000) else invest
    bucket.append(label)
    mg='moves OK' if not miss else 'need '+','.join(miss)
    print(f'{rank:<3}{score:>5} {flag}{label+altag:<21}{a}/{d}/{s}({ivt})'.ljust(42)
          +f'{f"{lvl}->{capL}":>11}{cp:>7} {rk:<11} {status:<16} {cost} | {mg}')
for rank,label,score in missing:
    print(f'{rank:<3}{score:>5}   {label:<22}{"NOT OWNED"}')
c.close()
print(f'\nAT-CAP & moves-ok (ready): {ready}')
print(f'Cheap finish (≤110XL,≤400k): {cheap}')
print(f'Big invest: {invest}')
