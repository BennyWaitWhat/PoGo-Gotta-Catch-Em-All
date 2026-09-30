#!/usr/bin/env python3
"""Compute the protected uid_hex set for keep-rule "xxl".

RULE (per task spec, finalized PoGo keep policy KEEP_POLICY.md sec 4):
  Among rows with pokemon_size_category = 5 (and in_bag = 1):
    per group (pokemon_id, form), keep the UNION of:
       - top 2 by weight_kg
       - top 2 by height_m

Notes / decisions:
  * Grouping is (pokemon_id, form) EXACTLY as the task states -- costume is NOT
    a group key here (the policy doc sec 4 says "per (species, form)"; the older
    tagset script grouped by (pid,form,fresh_costume), so we diff that below).
  * Pool is in_bag=1 only (a keep set only protects bag mons).
  * Size column is pokemon_size_category (not size_enum) per the task spec.
  * "top 2" = the 2 rows with the largest metric value. Sort desc by metric;
    deterministic uid_hex secondary sort. Rows with NULL metric are ineligible
    for that metric (there are none in this dataset). Boundary ties (value of the
    2nd-place row == value of the 3rd-place row) are reported; on a tie we keep
    only 2 rows (the deterministic ones) and flag it -- there are none here.
"""
import sqlite3
import os
from collections import defaultdict

DB = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
OUTDIR = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/policy_sets"
OUTFILE = os.path.join(OUTDIR, "xxl.txt")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute(
    """
    SELECT uid_hex, pokemon_id, form, fresh_costume, species_name,
           weight_kg, height_m, pokemon_size_category
    FROM pokemon
    WHERE in_bag = 1 AND pokemon_size_category = 5
    """
)
rows = [dict(r) for r in cur.fetchall()]
con.close()

print(f"size5 in_bag rows: {len(rows)}")


def topn(grouped, metric, n=2):
    """uid_hex set of top-n by metric per group; plus boundary-tie report."""
    sel = set()
    ties = []
    for k, members in grouped.items():
        elig = [m for m in members if m[metric] is not None]
        elig.sort(key=lambda m: (-m[metric], m["uid_hex"]))
        for m in elig[:n]:
            sel.add(m["uid_hex"])
        if len(elig) > n and elig[n - 1][metric] == elig[n][metric]:
            v = elig[n - 1][metric]
            ties.append((k, metric, v, [m["uid_hex"] for m in elig if m[metric] == v]))
    return sel, ties


def derive(rows, keyfn):
    g = defaultdict(list)
    for r in rows:
        g[keyfn(r)].append(r)
    w_sel, w_ties = topn(g, "weight_kg")
    h_sel, h_ties = topn(g, "height_m")
    return (w_sel | h_sel), w_sel, h_sel, w_ties, h_ties, g


# === PRIMARY: group by (pokemon_id, form) -- the task spec ===
key_pf = lambda r: (r["pokemon_id"], r["form"])
sel_pf, w_pf, h_pf, wt_pf, ht_pf, g_pf = derive(rows, key_pf)

# === Alternate: group by (pokemon_id, form, fresh_costume) -- old tagset ===
key_pfc = lambda r: (r["pokemon_id"], r["form"], r["fresh_costume"])
sel_pfc, _, _, _, _, _ = derive(rows, key_pfc)

print(f"groups (pid,form): {len(g_pf)}")
print(f"PRIMARY protected count (pid,form): {len(sel_pf)}")
print(f"  selected by weight: {len(w_pf)}  by height: {len(h_pf)}")
print(f"ALT protected count (pid,form,costume): {len(sel_pfc)}")
print(f"  diff: in PRIMARY not ALT = {sorted(sel_pf - sel_pfc)}")
print(f"  diff: in ALT not PRIMARY = {sorted(sel_pfc - sel_pf)}")

print("=== boundary ties (weight) ===")
for t in wt_pf:
    print("  ", t)
print("=== boundary ties (height) ===")
for t in ht_pf:
    print("  ", t)

by_uid = {r["uid_hex"]: r for r in rows}

# Show every group that has >2 members (these are the only groups where the rule
# actually drops anything) and which uids it keeps + the deciding stat.
print("=== groups with >2 members (rule can drop here) ===")
for k, members in sorted(g_pf.items()):
    if len(members) <= 2:
        continue
    sp = members[0]["species_name"]
    print(f"  (pid={k[0]},form={k[1]}) {sp}  n={len(members)}")
    wsorted = sorted(members, key=lambda m: (-m["weight_kg"], m["uid_hex"]))
    hsorted = sorted(members, key=lambda m: (-m["height_m"], m["uid_hex"]))
    print(f"     weight top2: {[(m['uid_hex'], m['weight_kg']) for m in wsorted[:2]]}")
    print(f"     height top2: {[(m['uid_hex'], m['height_m']) for m in hsorted[:2]]}")
    kept = sel_pf & set(m["uid_hex"] for m in members)
    dropped = set(m["uid_hex"] for m in members) - sel_pf
    print(f"     KEPT {len(kept)} DROPPED {len(dropped)}: dropped={sorted(dropped)}")

# Build a 6-item sample: species + deciding stat (why each was kept)
sample = []
for u in sorted(sel_pf):
    r = by_uid[u]
    reasons = []
    if u in w_pf:
        reasons.append(f"weight {r['weight_kg']:.2f}kg")
    if u in h_pf:
        reasons.append(f"height {r['height_m']:.2f}m")
    sample.append(f"{r['species_name']} ({u}): " + " & ".join(reasons))

# write the set
os.makedirs(OUTDIR, exist_ok=True)
with open(OUTFILE, "w", encoding="utf-8") as f:
    for u in sorted(sel_pf):
        f.write(u + "\n")
print(f"WROTE {len(sel_pf)} uids -> {OUTFILE}")

# emit a few interesting sample lines (from the >2 groups so the deciding stat matters)
print("=== SAMPLE (first 6 of full set) ===")
for s in sample[:6]:
    print("  ", s)
