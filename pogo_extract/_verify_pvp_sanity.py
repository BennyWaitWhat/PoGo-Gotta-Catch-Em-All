import json, sqlite3, os
DB = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
TAGDIR = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets"
GM = "C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pvpoke_gamemaster.json"
d = json.load(open(GM)); BS = {p['speciesId']: p['baseStats'] for p in d['pokemon']}
def maxcp(sid):
    b = BS.get(sid)
    if not b: return None
    return int(((b['atk']+15)*(b['def']+15)**0.5*(b['hp']+15)**0.5*0.84029999**2)/10)
def load(name):
    with open(os.path.join(TAGDIR,name)) as f:
        return set(l.strip() for l in f if l.strip())
transfer=load("6_Transfer.txt"); ul_iv=load("1_UL_IV.txt"); gl_iv=load("1_GL_IV.txt"); hundo=load("4_Hundo.txt"); nundo=load("4_Nundo.txt")

con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; cur=con.cursor()
rows=cur.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()

# Sanity 1: confirm string format of uid_hex in DB matches file (length, sample membership)
uids_db=set(r['uid_hex'] for r in rows)
print("DB uid_hex sample len:", len(rows[0]['uid_hex']), "| all 16-char:", all(len(r['uid_hex'])==16 for r in rows))
print("transfer ⊆ DB-uids (any-bag)?:")
all_uids=set(r[0] for r in cur.execute("SELECT uid_hex FROM pokemon").fetchall())
print("  transfer entries not present anywhere in DB:", len(transfer-all_uids))
print("  ul_iv entries not present anywhere in DB:", len(ul_iv-all_uids))

# Sanity 2: split qualified by each criterion, and report how many are KEPT somewhere vs uncategorized
def quals(r):
    out=set()
    if r['gl_rank'] is not None and r['gl_rank']<=5 and r['gl_stage'] and (maxcp(r['gl_stage']) or 0)>=1400: out.add('GL')
    if r['ul_rank'] is not None and r['ul_rank']<=5 and r['ul_stage'] and (maxcp(r['ul_stage']) or 0)>=2400: out.add('UL')
    if r['iv_atk']==0 and r['iv_def']==15 and r['iv_sta']==15: out.add('NUNDO')
    return out
q=[(r,quals(r)) for r in rows]; q=[x for x in q if x[1]]
from collections import Counter
c=Counter()
for r,s in q:
    for t in s: c[t]+=1
print("qualified count:",len(q),"by criterion:",dict(c))

# overlap of qualified with kept tagsets vs transfer
in_transfer=sum(1 for r,s in q if r['uid_hex'] in transfer)
kept_any=sum(1 for r,s in q if r['uid_hex'] in (ul_iv|gl_iv|hundo|nundo))
print("qualified in transfer:", in_transfer)
print("qualified appearing in UL_IV/GL_IV/Hundo/Nundo (sanity that pipeline kept them):", kept_any, "of", len(q))

# Sanity 3: is the criterion non-trivial? show the GL and NUNDO qualifiers explicitly (UL r<=5 may be few)
print("\n-- UL rank<=5 qualifiers --")
for r,s in q:
    if 'UL' in s: print(f"  {r['uid_hex']} {r['species_name']} ul_r{r['ul_rank']} {r['ul_stage']} mc={maxcp(r['ul_stage'])} IV={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']} inTransfer={r['uid_hex'] in transfer} inUL_IV={r['uid_hex'] in ul_iv}")
print("-- GL rank<=5 qualifiers (first 15) --")
gqs=[(r,s) for r,s in q if 'GL' in s]
for r,s in gqs[:15]:
    print(f"  {r['uid_hex']} {r['species_name']} gl_r{r['gl_rank']} {r['gl_stage']} mc={maxcp(r['gl_stage'])} inTransfer={r['uid_hex'] in transfer} inGL_IV={r['uid_hex'] in gl_iv}")
print("  total GL qualifiers:", len(gqs))
print("-- NUNDO (0/15/15) qualifiers --")
for r,s in q:
    if 'NUNDO' in s: print(f"  {r['uid_hex']} {r['species_name']} IV={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']} shiny={r['is_shiny']} inTransfer={r['uid_hex'] in transfer} inNundo={r['uid_hex'] in nundo}")
con.close()
