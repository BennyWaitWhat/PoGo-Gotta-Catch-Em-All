"""ADVERSARIAL pre-evo check for '1 GL Least Bad'.
For each top-30 meta species, find the user's TRUE best rank AS that species by
parsing gl_chain_ranks (which lists rank for EVERY stage in the chain), regardless
of which stage gl_stage resolved to. Then compare with what the file/rederivation used.
A false-negative arises if a pre-evo specimen has a BETTER rank as the meta form than
the tagged least-bad specimen, but was excluded (its gl_stage pointed elsewhere).
"""
import sqlite3, json, os, re
from collections import defaultdict

ROOT = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = os.path.join(ROOT, 'pokemon.db')
FILE = os.path.join(ROOT, 'system/analysis/tagsets/1_GL_Least_Bad.txt')
META_TOPN=30; STRICT=5

GL = {e['speciesId']:(e.get('score') or 0) for e in json.load(open(os.path.join(ROOT,'_gl1500.json'),encoding='utf-8'))}
meta_gl = set(sorted(GL,key=lambda s:-GL[s])[:META_TOPN])
# base (non-shadow) name of each meta entry, for chain matching
def base(sid): return sid[:-7] if sid.endswith('_shadow') else sid

c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
rows=c.execute("""SELECT uid_hex,pokemon_id,form,fresh_alignment,species_name,iv_atk,iv_def,iv_sta,
    gl_rank,gl_stage,gl_chain_ranks FROM pokemon WHERE in_bag=1 AND gl_chain_ranks IS NOT NULL""").fetchall()
file_set=set(l.strip() for l in open(FILE) if l.strip())

def parse_chain(s):
    # 'spheal:23(97.14%);sealeo:3117(92.81%)' -> {'spheal':23,'sealeo':3117}
    out={}
    for part in s.split(';'):
        m=re.match(r'([a-z0-9_]+):(\d+)\(', part.strip())
        if m: out[m.group(1)]=int(m.group(2))
    return out

# For each meta species (by base name + shadow-awareness), gather every owned specimen
# whose CHAIN includes that base stage, with the rank it'd have AS that stage.
# Respect shadow: a shadow specimen ranks as <base>_shadow universe entry; we match the
# stage name in chain to base(meta entry) and require alignment consistency.
species_candidates=defaultdict(list)  # meta_sid -> list of (rank_as_that_stage, row)
for r in rows:
    shadow=(r['fresh_alignment']==1)
    chain=parse_chain(r['gl_chain_ranks'])
    for meta_sid in meta_gl:
        b=base(meta_sid)
        want_shadow = meta_sid.endswith('_shadow')
        if want_shadow != shadow:   # shadow entry only for shadow mons; non-shadow entry only for non-shadow
            continue
        if b in chain:
            species_candidates[meta_sid].append((chain[b], r))

print("=== TRUE best-as-meta-form per species (chain-aware), vs tagged ===")
discrepancies=[]
for meta_sid in sorted(meta_gl, key=lambda s:-GL[s]):
    cands=species_candidates.get(meta_sid,[])
    if not cands: continue
    cands.sort(key=lambda x:x[0])
    best_rank,best_row=cands[0]
    # what gl_stage-based logic would have tagged: the min gl_rank among rows whose gl_stage==base & align ok
    # find which candidate is currently in the file for this species
    in_file=[(rk,rw) for rk,rw in cands if rw['uid_hex'] in file_set]
    tag_status = (f"FILE has r{in_file[0][0]} {in_file[0][1]['uid_hex'][:10]}" if in_file else "not in file")
    # determine if best chain-form specimen got excluded
    note=""
    if best_rank<=STRICT:
        note=f"-> best is r{best_rank}<=5 (would be GL Meta, not least-bad)"
    elif not in_file:
        note="-> NO specimen of this species in file"
    elif in_file[0][0] > best_rank:
        note=f"*** DISCREPANCY: file tags r{in_file[0][0]} but better r{best_rank} exists ({best_row['species_name']} {best_row['uid_hex'][:10]}, gl_stage={best_row['gl_stage']})"
        discrepancies.append((meta_sid,best_rank,best_row,in_file[0]))
    print(f"  {meta_sid:22s} best-as-form r{best_rank} ({best_row['species_name']} gl_stage={best_row['gl_stage']}) | {tag_status} {note}")

print("\n=== DISCREPANCIES (potential false negatives via pre-evo) ===")
if not discrepancies:
    print("  NONE")
for meta_sid,br,brow,(frk,frow) in discrepancies:
    print(f"  {meta_sid}: better specimen {brow['uid_hex']} ({brow['species_name']} r{br}, IV {brow['iv_atk']}/{brow['iv_def']}/{brow['iv_sta']}, gl_stage={brow['gl_stage']}) vs tagged r{frk} {frow['uid_hex']}")
    print(f"      chain: {brow['gl_chain_ranks']}")

c.close()
