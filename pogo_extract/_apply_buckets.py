"""Apply the 6 NEW bucket tags that aren't already covered by existing tags:
  Costume, XXS, Mega, Reserve (top-3/form), UL (ul_rank=1), Trade (fodder+free-evolves).
Existing 23 tags already serve the other buckets. Snapshot + single Frida session
+ DB mirror. Recomputes the keep-set to define Reserve/Trade correctly.
"""
import sqlite3, sys, time, shutil, os
from collections import defaultdict
import pogo_il2cpp as pg
sys.stdout.reconfigure(encoding='utf-8')

TRADE_EVO = {64,67,75,93,525,533,588,616,708,710}
HERE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(HERE,'pokemon.db')

c = sqlite3.connect(DB)
cur = c.execute("""SELECT uid_hex,pokemon_id,form,cp,iv_total,is_zero,fresh_shiny,is_lucky,
 is_legendary,is_mythical,is_ultra_beast,is_paradox,was_best_buddy_badge,fresh_has_location_card,
 fresh_alignment,fresh_bread_mode,fresh_costume,pokemon_size_category,can_mega_evolve,gl_rank,ul_rank,
 adventure_effects_left,(';'||COALESCE(auth_tag_names,'')||';') tags FROM pokemon WHERE in_bag=1""")
rows=cur.fetchall(); C={n:i for i,n in enumerate([d[0] for d in cur.description])}
def g(r,k): return r[C[k]]

# keep-set (same rules as _buckets.py) to define Reserve/Trade
by_form=defaultdict(list); by_sp_shadow=defaultdict(list); by_sp_mega=defaultdict(list)
for r in rows:
    by_form[(g(r,'pokemon_id'),g(r,'form') or 0)].append(r)
    if g(r,'fresh_alignment')==1: by_sp_shadow[g(r,'pokemon_id')].append(r)
    if g(r,'can_mega_evolve')==1: by_sp_mega[g(r,'pokemon_id')].append(r)
def topids(lst,n): return set(id(r) for r in sorted(lst,key=lambda r:g(r,'cp'),reverse=True)[:n])
top3shadow={k:topids(v,3) for k,v in by_sp_shadow.items()}
megabest={k:topids(v,1) for k,v in by_sp_mega.items()}

keep=set()
def iskeep_collection(r):
    pid=g(r,'pokemon_id'); rid=id(r)
    if g(r,'fresh_shiny')==1 or g(r,'iv_total')==45: return True
    if g(r,'is_zero')==1 and pid!=0: return True
    if any(g(r,k)==1 for k in ('is_legendary','is_mythical','is_ultra_beast','is_paradox')): return True
    if g(r,'is_lucky')==1 or g(r,'was_best_buddy_badge')==1: return True
    if g(r,'fresh_has_location_card')==1 or (g(r,'fresh_costume') or 0)!=0: return True
    if g(r,'fresh_alignment')==2 or g(r,'fresh_bread_mode') in (1,2): return True
    if (g(r,'adventure_effects_left') or 0)>0: return True
    if g(r,'pokemon_size_category') in (1,5): return True
    if g(r,'gl_rank')==1 or g(r,'ul_rank')==1: return True
    if ';GL Top 10;' in g(r,'tags') or ';UL Top 10;' in g(r,'tags'): return True
    if g(r,'fresh_alignment')==1 and rid in top3shadow.get(pid,()): return True
    if rid in megabest.get(pid,()): return True
    return False
for r in rows:
    if iskeep_collection(r): keep.add(g(r,'uid_hex'))
# Reserve: top-3/form among not-yet-kept
reserve=set()
for key,lst in by_form.items():
    rem=[r for r in lst if g(r,'uid_hex') not in keep]
    for r in sorted(rem,key=lambda r:g(r,'cp'),reverse=True)[:3]:
        reserve.add(g(r,'uid_hex')); keep.add(g(r,'uid_hex'))
# Trade: fodder (not kept) + all free-trade-evo specimens
fodder={g(r,'uid_hex') for r in rows if g(r,'uid_hex') not in keep}
tradeevo={g(r,'uid_hex') for r in rows if g(r,'pokemon_id') in TRADE_EVO}
trade=fodder|tradeevo

# 6 new bucket memberships
plan={
 'Costume':[g(r,'uid_hex') for r in rows if (g(r,'fresh_costume') or 0)!=0],
 'XXS':    [g(r,'uid_hex') for r in rows if g(r,'pokemon_size_category')==1],
 'Mega':   [g(r,'uid_hex') for r in rows if id(r) in megabest.get(g(r,'pokemon_id'),())],
 'UL':     [g(r,'uid_hex') for r in rows if g(r,'ul_rank')==1],
 'Reserve':sorted(reserve),
 'Trade':  sorted(trade),
}
c.close()
COLORS={'Costume':4,'XXS':5,'Mega':6,'UL':2,'Reserve':3,'Trade':1}
for k,v in plan.items(): print(f'  {k:<9} {len(v):>5}')
allu=sorted({u for v in plan.values() for u in v})
print(f'  distinct uids: {len(allu)}')

stamp=time.strftime('%Y-%m-%d_%H%M%S')
snap=os.path.join(HERE,'.db_snapshots',f'pokemon.db.{stamp}.pre_buckets.bak')
os.makedirs(os.path.dirname(snap),exist_ok=True); shutil.copy2(DB,snap)
print('snapshot:',snap)

sess,pid=pg.get_session(); print('pid',pid)
try:
    bag=pg.pick_singleton(sess,'Niantic.Holoholo.Internal','PokemonBagImpl')
    svc=pg.pick_singleton(sess,'Niantic.Holoholo.Tagging','TaggingRpcService')
    pm=pg.find_protos_for_uids(sess,bag,sorted({str(int(u,16)) for u in allu}))
    print(f'bag-walk {len(pm)}/{len(allu)}')
    bt=sess.create_script(open('bulk_tag.js',encoding='utf-8').read()); bt.on('message',lambda m,d:None); bt.load(); bt.exports_sync.init_status()
    conn=sqlite3.connect(DB)
    for name,uids in plan.items():
        ft=bt.exports_sync.find_tag_id_by_name(svc,name)
        if not ft.get('ok'):
            for attempt in range(3):
                bt.exports_sync.add_tag_on_instance(svc,name,COLORS[name])
                time.sleep(3.0 if attempt==0 else 5.0)
                ft=bt.exports_sync.find_tag_id_by_name(svc,name)
                if ft.get('ok'): break
        if not ft.get('ok'): print(f'  ! create {name} failed'); continue
        tp=ft['tagProtoAddr']
        protos=[]; vu=[]
        for u in uids:
            p=pm.get(str(int(u,16)))
            if p: protos.append(p); vu.append(u)
        done=0; B=100; i=0
        while i<len(protos):
            cu=vu[i:i+B]; cp=protos[i:i+B]
            r=None
            for _ in range(3):
                r=bt.exports_sync.bulk_tag_many(svc,tp,cp)
                if r.get('ok') and r.get('built',0)==len(cp): break
                time.sleep(0.6)
            if r.get('ok'):
                done+=len(cu)
                curd=conn.cursor()
                for u in cu:
                    row=curd.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?",(u,)).fetchone()
                    tg=[t for t in ((row[0] if row else None) or '').split(';') if t]
                    if name not in tg: tg.append(name)
                    curd.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",(';'.join(tg),u))
                conn.commit()
            else: print(f'    ! {name} batch {i}: {r}')
            i+=B
            if i<len(protos): time.sleep(0.4)
        print(f'  {name}: applied {done}/{len(uids)}')
    conn.close(); bt.unload()
finally:
    sess.detach()
print('done')
