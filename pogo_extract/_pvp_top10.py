"""PVPoke GL top 10 + UL top 10. For each meta pick, scan the user's whole
evolution family and pick the specimen with the best rank AT THE META SPECIES
(parsed from gl_chain_ranks/ul_chain_ranks — IVs are preserved on evolution, so
this correctly answers 'which to build/evolve'). Flags evolution requirements.
Writes a tag plan JSON. Read-only against the DB."""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')
FC = json.load(open('form_category.json'))
def gal(pid):
    for k,v in FC.items():
        if k.startswith(f'{pid}_') and 'Galarian' in v.get('form_name',''): return int(k.split('_')[1])
    return None
CORSOLA_G, MOLTRES_G = gal(222), gal(146)

# (league,label,meta_pvpokeid,final_pid,final_form,align, family[(pid,name)], how_to_final)
GL=[
 ('GL','Lickilicky','lickilicky',463,None,'np',[(463,'Lickilicky'),(108,'Lickitung')],'evolve Lickitung +Lick(legacy) 50 candy'),
 ('GL','Quagsire','quagsire',195,None,'np',[(195,'Quagsire'),(194,'Wooper')],'evolve Wooper 50 candy'),
 ('GL','Quagsire Shadow','quagsire',195,None,'shadow',[(195,'Quagsire'),(194,'Wooper')],'evolve Shadow Wooper 50 candy'),
 ('GL','Feraligatr','feraligatr',160,None,'np',[(160,'Feraligatr'),(159,'Croconaw'),(158,'Totodile')],'evolve to Feraligatr'),
 ('GL','Jellicent','jellicent',593,None,'np',[(593,'Jellicent'),(592,'Frillish')],'evolve Frillish 50 candy'),
 ('GL','Tinkaton','tinkaton',959,None,'np',[(959,'Tinkaton'),(958,'Tinkatuff'),(957,'Tinkatink')],'evolve to Tinkaton'),
 ('GL','Corsola Galarian','corsola',222,CORSOLA_G,'np',[(222,'Corsola-Galar')],'(use as-is; rank approx*)'),
 ('GL','Forretress','forretress',205,None,'np',[(205,'Forretress'),(204,'Pineco')],'evolve Pineco 50 candy'),
 ('GL','Feraligatr Shadow','feraligatr',160,None,'shadow',[(160,'Feraligatr'),(159,'Croconaw'),(158,'Totodile')],'evolve to Feraligatr'),
 ('GL','Altaria','altaria',334,None,'np',[(334,'Altaria'),(333,'Swablu')],'evolve Swablu 400 candy'),
]
UL=[
 ('UL','Jellicent','jellicent',593,None,'np',[(593,'Jellicent'),(592,'Frillish')],'evolve Frillish 50 candy'),
 ('UL','Corviknight','corviknight',823,None,'np',[(823,'Corviknight'),(822,'Corvisquire'),(821,'Rookidee')],'evolve to Corviknight'),
 ('UL','Lapras','lapras',131,None,'np',[(131,'Lapras')],'use as-is'),
 ('UL','Lapras Shadow','lapras',131,None,'shadow',[(131,'Lapras')],'use as-is'),
 ('UL','Tinkaton','tinkaton',959,None,'np',[(959,'Tinkaton'),(958,'Tinkatuff'),(957,'Tinkatink')],'evolve to Tinkaton'),
 ('UL','Empoleon','empoleon',395,None,'np',[(395,'Empoleon'),(394,'Prinplup'),(393,'Piplup')],'evolve to Empoleon'),
 ('UL','Moltres Galarian','moltres_galarian',146,MOLTRES_G,'np',[(146,'Moltres-Galar')],'use as-is'),
 ('UL','Empoleon Shadow','empoleon',395,None,'shadow',[(395,'Empoleon'),(394,'Prinplup'),(393,'Piplup')],'evolve to Empoleon'),
 ('UL','Feraligatr Shadow','feraligatr',160,None,'shadow',[(160,'Feraligatr'),(159,'Croconaw'),(158,'Totodile')],'evolve to Feraligatr'),
 ('UL','Malamar Shadow','malamar',687,None,'shadow',[(687,'Malamar'),(686,'Inkay')],'evolve Inkay 50 candy + flip phone'),
]

def asql(a): return 'fresh_alignment=1' if a=='shadow' else 'fresh_alignment IN (0,2)'
def meta_rank(chain, mid):
    if not chain: return None
    for seg in chain.split(';'):
        sid, _, rest = seg.partition(':')
        if sid == mid:
            try: return int(rest.split('(')[0])
            except: return None
    return None

c=sqlite3.connect('pokemon.db')
plan={'GL':[],'UL':[]}
for targets in (GL,UL):
    league=targets[0][0]; cr='gl_chain_ranks' if league=='GL' else 'ul_chain_ranks'
    print(f'\n===================== {league} TOP 10 =====================')
    for (_l,label,mid,fpid,fform,align,fam,how) in targets:
        pids=[p for p,_ in fam]
        ph=','.join('?'*len(pids))
        rows=c.execute(
            f"""SELECT uid_hex,pokemon_id,species_name,form,iv_atk,iv_def,iv_sta,iv_total,level,cp,{cr},fresh_alignment
                FROM pokemon WHERE in_bag=1 AND pokemon_id IN ({ph}) AND {asql(align)}""",pids).fetchall()
        # for galarian targets, restrict to the right form
        if fform is not None:
            rows=[r for r in rows if r[3]==fform]
        cands=[]
        for r in rows:
            mr=meta_rank(r[10], mid)
            if mr is not None: cands.append((mr,r))
        if not cands:
            print(f'  {label:<18} ❌ NOT OWNED (no family member)')
            plan[league].append({'label':label,'uid':None,'status':'missing'}); continue
        cands.sort(key=lambda x:x[0])
        mr,r=cands[0]
        uid,pid,nm,form,a,d,s,ivt,lvl,cp,_chain,fa=r
        altag='(S)' if fa==1 else '(P)' if fa==2 else ''
        need_evo = (pid != fpid)
        flag='✅' if mr<=10 else ('▫' if mr<=100 else '•')
        if need_evo:
            print(f'  {label:<18} ⬆ EVOLVE {nm:<11} {altag:<3} {a}/{d}/{s}({ivt}) L{lvl} cp={cp}  → as {label} rank={mr}  [{how}]')
        else:
            print(f'  {label:<18} {flag} HAVE   {nm:<11} {altag:<3} {a}/{d}/{s}({ivt}) L{lvl} cp={cp}  rank={mr}')
        plan[league].append({'label':label,'uid':uid,'species':nm,'rank':mr,
                             'status':'evolve' if need_evo else 'have',
                             'how':how if need_evo else None,'iv':f'{a}/{d}/{s}'})
c.close()
import os; os.makedirs('rescan_report',exist_ok=True)
json.dump(plan,open('rescan_report/pvp_top10_plan.json','w'),indent=2)
print('\n* Galarian Corsola rank computed vs regular-Corsola stats (FORM_OVERRIDES gap) — treat as approximate.')
print('wrote rescan_report/pvp_top10_plan.json')
