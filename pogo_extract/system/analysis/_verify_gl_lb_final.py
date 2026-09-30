"""FINAL correct re-derivation of '1 GL Least Bad' using chain-aware best-rank.
For each top-30 meta species the user owns:
  best_specimen = the owned specimen with MIN rank-as-that-meta-form (from gl_chain_ranks),
                  shadow forms matched only by shadow specimens.
  if best rank <= 5 -> belongs to GL Meta (exclude)
  else              -> that specimen is the Least Bad member.
Compare to file.
"""
import sqlite3, json, re, os
from collections import defaultdict
ROOT=r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
GL={e['speciesId']:(e.get('score') or 0) for e in json.load(open(os.path.join(ROOT,'_gl1500.json'),encoding='utf-8'))}
meta=set(sorted(GL,key=lambda s:-GL[s])[:30])
def base(s): return s[:-7] if s.endswith('_shadow') else s
c=sqlite3.connect(os.path.join(ROOT,'pokemon.db')); c.row_factory=sqlite3.Row
rows=c.execute("SELECT uid_hex,species_name,fresh_alignment,gl_chain_ranks FROM pokemon WHERE in_bag=1 AND gl_chain_ranks IS NOT NULL").fetchall()
def parse(s):
    o={}
    for p in s.split(';'):
        m=re.match(r'([a-z0-9_]+):(\d+)\(',p.strip())
        if m: o[m.group(1)]=int(m.group(2))
    return o
best=defaultdict(lambda:(10**9,None))
for r in rows:
    sh=(r['fresh_alignment']==1); ch=parse(r['gl_chain_ranks'])
    for ms in meta:
        if ms.endswith('_shadow')!=sh: continue
        b=base(ms)
        if b in ch and ch[b]<best[ms][0]:
            best[ms]=(ch[b],r)
correct={}  # uid -> (species, rank)
for ms,(rk,r) in best.items():
    if r is None: continue
    if rk>5:
        correct[r['uid_hex']]=(ms,rk,r['species_name'])
fileset=[l.strip() for l in open(os.path.join(ROOT,'system/analysis/tagsets/1_GL_Least_Bad.txt')) if l.strip()]
fs=set(fileset); cs=set(correct)
print("CORRECT (chain-aware) count:",len(cs)," FILE count:",len(fileset))
print("\nFALSE NEGATIVES (correct, missing from file):")
for u in cs-fs:
    s,rk,nm=correct[u]; print(f"  {u} {s} r{rk} {nm}")
print("\nFALSE POSITIVES (in file, not in correct set):")
for u in fs-cs:
    r=next((x for x in rows if x['uid_hex']==u),None)
    print(f"  {u} {r['species_name'] if r else '??'}")
c.close()
