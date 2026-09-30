#!/usr/bin/env python3
"""
Compute the protected uid_hex set for keep-rule "rarity" of the finalized PoGo keep policy.

RULE (KEEP_POLICY.md sec.4): Among mons that are Legendary OR Mythical OR Ultra Beast OR Paradox,
keep the top 6 by iv_total (tiebreak cp) per (pokemon_id, form).

Scope: pokemon table, in_bag=1.

Classification judgment call (see notes returned by the agent):
  305 in_bag rows have NULL for all four rarity flags (an unprocessed ingest batch).
  Treating NULL as 0 would silently DROP a real legendary (uid f9af7a9aaeafbf75 = pid 150 Mewtwo,
  the only Mewtwo whose flag was never populated). Per the project's "treat missing protection
  input as PROTECTED" rule and policy intent, we classify rarity by SPECIES cross-reference:
  a row counts as rare if EITHER its own flag is 1 OR any populated row of the same pokemon_id
  asserts that rarity. This fixes the one demonstrable false negative without inventing data
  (only pid 150 among the 305 NULL rows resolves to rare; the other 304 are genuinely common).

  PRIMARY output = species-cross-referenced set (written to rarity.txt).
  We also compute the LITERAL set (flag=1 only) and report the membership delta.
"""
import sqlite3, os
from collections import defaultdict

DB = os.path.join(os.path.dirname(__file__), '..', '..', 'pokemon.db')
DB = os.path.abspath(DB)
OUT = os.path.join(os.path.dirname(__file__), 'policy_sets', 'rarity.txt')
os.makedirs(os.path.dirname(OUT), exist_ok=True)

con = sqlite3.connect(DB)
cur = con.cursor()

# --- Build authoritative species->rarity map from populated rows (any in-bag/out-of-bag row) ---
cur.execute("""SELECT pokemon_id, is_legendary, is_mythical, is_ultra_beast, is_paradox
               FROM pokemon WHERE is_legendary IS NOT NULL""")
species_rare = defaultdict(lambda: [0, 0, 0, 0])
for pid, leg, myth, ub, par in cur.fetchall():
    r = species_rare[pid]
    r[0] |= int(leg or 0); r[1] |= int(myth or 0)
    r[2] |= int(ub or 0);  r[3] |= int(par or 0)

def is_rare_species(pid):
    return any(species_rare.get(pid, (0, 0, 0, 0)))

# --- Pull all in_bag rows with the fields we need ---
cur.execute("""SELECT uid_hex, pokemon_id, form, iv_total, cp, species_name,
                      is_legendary, is_mythical, is_ultra_beast, is_paradox
               FROM pokemon WHERE in_bag=1""")
rows = cur.fetchall()

def own_flag_rare(leg, myth, ub, par):
    return (leg == 1) or (myth == 1) or (ub == 1) or (par == 1)

def topN_per_group(pool, n=6):
    """pool: list of dicts. Return set of uid_hex kept = top-n by iv_total desc, cp desc per (pid,form)."""
    groups = defaultdict(list)
    for r in pool:
        groups[(r['pid'], r['form'])].append(r)
    kept = set()
    for key, lst in groups.items():
        lst.sort(key=lambda r: (r['iv_total'], r['cp']), reverse=True)
        for r in lst[:n]:
            kept.add(r['uid'])
    return kept, groups

# Build the two candidate pools
literal_pool, species_pool = [], []
for uid, pid, form, ivt, cp, name, leg, myth, ub, par in rows:
    rec = dict(uid=uid, pid=pid, form=form, iv_total=ivt, cp=cp, name=name)
    if own_flag_rare(leg, myth, ub, par):
        literal_pool.append(rec)
    if own_flag_rare(leg, myth, ub, par) or (
        (leg is None and myth is None and ub is None and par is None) and is_rare_species(pid)):
        species_pool.append(rec)

literal_set, _ = topN_per_group(literal_pool)
species_set, species_groups = topN_per_group(species_pool)

# --- Write PRIMARY (species-cross-referenced) set, sorted for stable output ---
with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
    for uid in sorted(species_set):
        f.write(uid + '\n')

# --- Report ---
print('DB                  :', DB)
print('OUT                 :', OUT)
print('literal pool rows   :', len(literal_pool))
print('species pool rows   :', len(species_pool), '(literal +', len(species_pool) - len(literal_pool), 'NULL-flag rare-species rows)')
print('LITERAL protected   :', len(literal_set))
print('SPECIES protected   :', len(species_set), '<-- written to rarity.txt')
print('delta (species-literal):', sorted(species_set - literal_set))
print('delta (literal-species):', sorted(literal_set - species_set))

# 6-item sample: pick the top-1 (by deciding stat) of six distinct species groups, show deciding stat
sample = []
seen_species = set()
# iterate groups by size desc for variety
for (pid, form), lst in sorted(species_groups.items(), key=lambda kv: -len(kv[1])):
    if pid in seen_species:
        continue
    lst_sorted = sorted(lst, key=lambda r: (r['iv_total'], r['cp']), reverse=True)
    top = lst_sorted[0]
    sample.append((top['uid'], top['name'], pid, form, top['iv_total'], top['cp']))
    seen_species.add(pid)
    if len(sample) >= 6:
        break
print('\nSAMPLE (species | deciding stat):')
for uid, name, pid, form, ivt, cp in sample:
    print(f'  {uid}  {name} (pid {pid}, form {form})  iv_total={ivt}, cp={cp}')

con.close()
