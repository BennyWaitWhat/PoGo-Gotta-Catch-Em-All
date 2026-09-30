# -*- coding: utf-8 -*-
import json, sqlite3, itertools

CPM = {
 1:0.094,1.5:0.1351374318,2:0.16639787,2.5:0.1926509131,3:0.21573247,3.5:0.2365726576,
 4:0.25572005,4.5:0.2735303812,5:0.29024988,5.5:0.3060573775,6:0.3210876,6.5:0.3354450362,
 7:0.34921268,7.5:0.3624577511,8:0.3752356,8.5:0.3875924077,9:0.39956728,9.5:0.4111935495,
 10:0.4225,10.5:0.4335426182,11:0.44310755,11.5:0.4530599535,12:0.46279839,12.5:0.4723360853,
 13:0.48168495,13.5:0.4908558072,14:0.5,14.5:0.5087017489,15:0.51739395,15.5:0.5259425113,
 16:0.5343543,16.5:0.5426357538,17:0.5507927,17.5:0.5588305845,18:0.5667545,18.5:0.5745691333,
 19:0.5822789,19.5:0.5898879072,20:0.5974,20.5:0.6048236651,21:0.6121573,21.5:0.6194041106,
 22:0.6265671,22.5:0.6336491815,23:0.64065295,23.5:0.6475763555,24:0.65443563,24.5:0.6612212834,
 25:0.667934,25.5:0.6745775332,26:0.6811649,26.5:0.6876849038,27:0.69414365,27.5:0.7005386546,
 28:0.7068842,28.5:0.7131649884,29:0.7193991,29.5:0.7255780101,30:0.7317,30.5:0.7347410093,
 31:0.7377695,31.5:0.7407855938,32:0.74378943,32.5:0.7467812109,33:0.74976104,33.5:0.7527290997,
 34:0.7556855,34.5:0.7586303702,35:0.76156384,35.5:0.7644963557,36:0.76739717,36.5:0.7702972656,
 37:0.7731865,37.5:0.7760649616,38:0.77893275,38.5:0.7817791916,39:0.78463697,39.5:0.7874736085,
 40:0.7903,40.5:0.792803968,41:0.7953,41.5:0.797803921,42:0.8003,42.5:0.802803892,
 43:0.8053,43.5:0.805803863,44:0.8103,44.5:0.812803859,45:0.8153,45.5:0.817803838,
 46:0.8203,46.5:0.822803810,47:0.8253,47.5:0.827803790,48:0.8303,48.5:0.832803753,
 49:0.8353,49.5:0.837803731,50:0.84029999,50.5:0.842301082,51:0.84499997,
}
LEVELS = sorted(CPM)

def calc_cp(b,a,d,s,L):
    m=CPM[L]
    return max(int(((b['atk']+a)*(b['def']+d)**0.5*(b['hp']+s)**0.5*m*m)/10),10)
def stat_prod(b,a,d,s,L):
    m=CPM[L]
    return (b['atk']+a)*m*(b['def']+d)*m*int((b['hp']+s)*m)
def best_for(b,a,d,s,cap=1500,maxlvl=51):
    bs,bl,bc=0,None,0
    for L in LEVELS:
        if L>maxlvl: break
        c=calc_cp(b,a,d,s,L)
        if c<=cap:
            sp=stat_prod(b,a,d,s,L)
            if sp>bs: bs,bl,bc=sp,L,c
    return bl,bc,bs
def species_best(b,cap=1500,maxlvl=51):
    best=0
    for a,d,s in itertools.product(range(16),repeat=3):
        _,_,sp=best_for(b,a,d,s,cap,maxlvl)
        if sp>best: best=sp
    return best

with open(r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\pvpoke_gamemaster.json','r',encoding='utf-8') as f:
    gm=json.load(f)
base_by_dex={}
for p in gm['pokemon']:
    if p.get('dex') and p.get('baseStats',{}).get('atk'):
        sid=str(p.get('speciesId',''))
        # prefer the plain base form: skip shadow/zen/mega/alola/galar/hisui/paldea/form variants
        if any(t in sid for t in ('_shadow','_zen','_mega','_alolan','_galarian','_hisuian','_paldean','_xs','_xl')):
            continue
        base_by_dex.setdefault(p['dex'],p['baseStats'])

with open(r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pokegenie_work\extracted\scan_data.json','r',encoding='utf-8') as f:
    data=json.load(f)

# cache species_best per dex
ref_cache={}
def get_ref(dex,b):
    if dex not in ref_cache: ref_cache[dex]=species_best(b)
    return ref_cache[dex]

# Test maxCP / prod / level / rank(current-species) on single-comb status1 entries
ok_cp=ok_lvl=ok_prod=tested=0
mism=[]
for d in data:
    pr=d.get('pvpGreatResult')
    if not pr or pr['status']!=1 or not d.get('singleIVComb'): continue
    sc=d.get('scannedIvComb') or {}
    if not sc: continue
    dex=pr['pokeNum']
    if dex not in base_by_dex: continue
    b=base_by_dex[dex]
    a,dd,s=sc['attackIV'],sc['defenseIV'],sc['staminaIV']
    bl,bc,bsp=best_for(b,a,dd,s)
    if bl is None: continue
    ref=get_ref(dex,b)
    prodidx=round(10000*bsp/ref)
    enc_lvl=round(2*bl-2)
    tested+=1
    if bc==pr['maxCP']: ok_cp+=1
    if enc_lvl==pr['levelLower']: ok_lvl+=1
    if abs(prodidx-pr['prodLower'])<=1: ok_prod+=1
    elif len(mism)<8: mism.append((d['pokemonName'],a,dd,s,'cp',bc,pr['maxCP'],'lvl',enc_lvl,pr['levelLower'],'prod',prodidx,pr['prodLower']))
    if tested>=400: break

print('tested',tested)
print('maxCP match: %d/%d'%(ok_cp,tested))
print('levelLower match: %d/%d'%(ok_lvl,tested))
print('prodLower match(+-1): %d/%d'%(ok_prod,tested))
print('--- sample mismatches ---')
for m in mism: print(m)
