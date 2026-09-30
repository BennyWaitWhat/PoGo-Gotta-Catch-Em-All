"""Independent adversarial re-derivation of '1 GL Least Bad'.
RULE: For each GL-meta species (top-30 by PVPoke score) the user owns where NO
specimen has gl_rank<=5, the single best (min gl_rank) specimen.
Shadow forms are their own ranking entry (<stage>_shadow).
"""
import sqlite3, json, os
from collections import defaultdict

ROOT = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = os.path.join(ROOT, 'pokemon.db')
FILE = os.path.join(ROOT, 'system/analysis/tagsets/1_GL_Least_Bad.txt')

META_TOPN = 30
STRICT_RANK = 5

GL = {e['speciesId']: (e.get('score') or 0) for e in json.load(open(os.path.join(ROOT, '_gl1500.json'), encoding='utf-8'))}
meta_gl = set(sorted(GL, key=lambda s: -GL[s])[:META_TOPN])
print("META top-30:", sorted(meta_gl, key=lambda s:-GL[s]))
print("score@30 boundary tie check:", [(s,GL[s]) for s in sorted(GL,key=lambda s:-GL[s])[28:33]])

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("""SELECT uid_hex,pokemon_id,form,fresh_alignment,species_name,
    iv_atk,iv_def,iv_sta,gl_rank,gl_stage,gl_chain_ranks FROM pokemon WHERE in_bag=1""").fetchall()

def metaform(stage, shadow):
    if not stage: return None
    sid = f'{stage}_shadow'
    if shadow and sid in GL: return sid
    return stage

# ---- main re-derivation (mirrors rule, NOT trusting builder output) ----
by_species = defaultdict(list)
for r in rows:
    if r['gl_rank'] is None: continue
    shadow = (r['fresh_alignment'] == 1)
    mf = metaform(r['gl_stage'], shadow)
    if mf in meta_gl:
        by_species[mf].append(r)

rederived = {}   # uid -> label
meta_strict = {}
for sid, lst in by_species.items():
    lst.sort(key=lambda r: r['gl_rank'])
    best = lst[0]
    if best['gl_rank'] <= STRICT_RANK:
        meta_strict[sid] = best
    else:
        rederived[best['uid_hex']] = (sid, best['gl_rank'], best['species_name'], best['fresh_alignment'])

file_uids = [l.strip() for l in open(FILE) if l.strip()]
file_set = set(file_uids)
red_set = set(rederived)

print("\nfile_count:", len(file_uids), "rederived_count:", len(red_set))
print("\n=== meta species the user owns with a rank<=5 (go to GL Meta, NOT least bad) ===")
for sid,b in sorted(meta_strict.items()):
    print(f"  {sid}: best r{b['gl_rank']} {b['species_name']} {b['uid_hex'][:10]}")

print("\n=== rederived LEAST-BAD members ===")
for uid,(sid,rk,nm,al) in sorted(rederived.items(), key=lambda x:x[1][0]):
    mark = '' if uid in file_set else '  <-- MISSING FROM FILE'
    print(f"  {uid[:12]} {sid} r{rk} {'Shadow ' if al==1 else ''}{nm}{mark}")

print("\n=== FALSE POSITIVES (in file, not in rederived) ===")
for uid in file_set - red_set:
    r = next((x for x in rows if x['uid_hex']==uid), None)
    if r is None:
        print(f"  {uid} : NOT FOUND in bag (in_bag=1)")
        continue
    shadow=(r['fresh_alignment']==1); mf=metaform(r['gl_stage'],shadow)
    reason = []
    if mf not in meta_gl: reason.append(f"species '{mf}' not in top-30 meta")
    # is it the best of its species?
    grp = by_species.get(mf, [])
    if grp:
        best=min(grp,key=lambda x:x['gl_rank'])
        if best['uid_hex']!=uid: reason.append(f"not best of {mf} (best is r{best['gl_rank']} {best['uid_hex'][:10]}, this r{r['gl_rank']})")
        if best['gl_rank']<=STRICT_RANK: reason.append(f"{mf} best r{best['gl_rank']}<=5 => belongs in GL Meta not Least Bad")
    print(f"  {uid[:12]} {r['species_name']} gl_stage={r['gl_stage']} r{r['gl_rank']} align={r['fresh_alignment']} :: {'; '.join(reason) or 'unknown'}")

print("\n=== FALSE NEGATIVES (in rederived, not in file) ===")
for uid in red_set - file_set:
    sid,rk,nm,al = rederived[uid]
    print(f"  {uid[:12]} {sid} r{rk} {'Shadow ' if al==1 else ''}{nm}")

c.close()
