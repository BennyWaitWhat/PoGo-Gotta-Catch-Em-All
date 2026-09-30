import json, sqlite3, os
ROOT = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB=os.path.join(ROOT,"pokemon.db"); GM=os.path.join(ROOT,"pvpoke_gamemaster.json")
TAGDIR=os.path.join(ROOT,"system/analysis/tagsets")
gm=json.load(open(GM)); BS={p['speciesId']:p['baseStats'] for p in gm['pokemon']}
def maxcp(sid):
    b=BS.get(sid)
    if b is None: return None
    return int(((b['atk']+15)*(b['def']+15)**0.5*(b['hp']+15)**0.5*0.84029999**2)/10)
def rf(n):
    s=set()
    with open(os.path.join(TAGDIR,n),encoding='utf-8') as f:
        for l in f:
            t=l.strip()
            if t: s.add(t)
    return s
transfer=rf("6_Transfer.txt")

con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; cur=con.cursor()

# 1) Sanity: do all uid_hex in transfer exist in DB as strings? (catches format mismatch)
cur.execute("SELECT uid_hex FROM pokemon"); all_db=set(r[0] for r in cur.fetchall())
ghost=[u for u in transfer if u not in all_db]
print(f"transfer uids NOT found in DB (format-mismatch canary): {len(ghost)}")
for g in ghost[:10]: print("  ghost:", repr(g))

# 2) Are transfer mons all in_bag=1? (they should be live)
cur.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1"); inbag=set(r[0] for r in cur.fetchall())
not_inbag=[u for u in transfer if u in all_db and u not in inbag]
print(f"transfer uids that exist but in_bag!=1: {len(not_inbag)}")

# 3) Build the 128 valuable set again and break down by reason; verify NONE in transfer (independent recompute)
cur.execute("SELECT uid_hex,species_name,iv_atk,iv_def,iv_sta,gl_rank,gl_stage,ul_rank,ul_stage FROM pokemon WHERE in_bag=1")
a_only=b_only=c_only=0; total=0; in_t=0
cat_a=cat_b=cat_c=0
samples=[]
for r in cur.fetchall():
    A = r['gl_rank'] is not None and r['gl_rank']<=5 and r['gl_stage'] and (maxcp(r['gl_stage']) or 0)>=1400
    B = r['ul_rank'] is not None and r['ul_rank']<=5 and r['ul_stage'] and (maxcp(r['ul_stage']) or 0)>=2400
    C = (r['iv_atk']==0 and r['iv_def']==15 and r['iv_sta']==15)
    if A or B or C:
        total+=1
        if A: cat_a+=1
        if B: cat_b+=1
        if C: cat_c+=1
        if r['uid_hex'] in transfer: in_t+=1
        if len(samples)<8:
            samples.append((r['uid_hex'],r['species_name'],f"{r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}",
                            r['gl_rank'],r['gl_stage'],maxcp(r['gl_stage']) if r['gl_stage'] else None,
                            r['ul_rank'],r['ul_stage'],maxcp(r['ul_stage']) if r['ul_stage'] else None,
                            ('A' if A else '')+('B' if B else '')+('C' if C else '')))
print(f"\nRecomputed valuable total={total}  in_transfer={in_t}")
print(f"satisfy (a)GL: {cat_a}   (b)UL: {cat_b}   (c)IV0/15/15: {cat_c}  (categories overlap)")
print("\nSample valuable mons:")
for s in samples:
    print(f"  {s[0]} {s[1]:<22} IV={s[2]:<8} glR={s[3]} gl={s[4]}({s[5]}) ulR={s[6]} ul={s[7]}({s[8]}) [{s[9]}]")

# 4) maxcp spot-check against known values
print("\nmaxcp spot-checks:")
for sid in ['charizard','medicham','azumarill','registeel','swampert','cresselia']:
    print(f"  maxcp({sid}) = {maxcp(sid)}")
con.close()
