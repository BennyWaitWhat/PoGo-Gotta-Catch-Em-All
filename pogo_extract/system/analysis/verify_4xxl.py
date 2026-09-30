import sqlite3, os

DB = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
SETFILE = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets/4_XXL.txt"
TAG = "4 XXL"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ---- (2) actual DB membership ----
cur.execute("""
    SELECT uid_hex, pokemon_id, form, fresh_costume, weight_kg, height_m,
           pokemon_size_category, in_bag, auth_tag_names, species_name
    FROM pokemon
""")
rows = [dict(r) for r in cur.fetchall()]

def is_tagged(r):
    s = ";" + (r["auth_tag_names"] or "") + ";"
    return r["in_bag"] == 1 and (";" + TAG + ";") in s

db_members = set(r["uid_hex"] for r in rows if is_tagged(r))

# ---- (1) re-derive CORRECT membership from the RULE ----
# Rule: among rows with pokemon_size_category=5, per group (pokemon_id, form, fresh_costume):
#       union of top-2 by weight_kg and top-2 by height_m.
# Two interpretations of the candidate pool:
#   A) ALL rows with size=5 (rule text literally)
#   B) only in_bag=1 rows with size=5 (since a tag only applies to bag rows)
def derive(pool_rows, metric, exclude_null=True):
    """Return set of uid_hex that are top-2 by `metric` within each group.
    Ties: we take strictly the rows whose metric value is among the 2 largest
    DISTINCT? No -- 'top-2' means 2 rows. Implement as sort desc, take first 2.
    But ties at the boundary are ambiguous; handle by value-rank to be safe and
    report ambiguity separately."""
    pass

from collections import defaultdict

def group_key(r):
    return (r["pokemon_id"], r["form"], r["fresh_costume"])

def topn_by(grouped, metric, n=2):
    """For each group, return uid_hex of the top-n rows by metric (desc).
    Rows with NULL metric are not eligible to be 'top'. Stable: ties broken by
    uid_hex to be deterministic, but we ALSO compute a tie-sensitive variant."""
    sel = set()
    boundary_ties = []  # (group, metric, value, uids_tied_at_cutoff)
    for k, members in grouped.items():
        elig = [m for m in members if m[metric] is not None]
        # sort by metric desc, then uid_hex asc for determinism
        elig.sort(key=lambda m: (-m[metric], m["uid_hex"]))
        chosen = elig[:n]
        sel.update(m["uid_hex"] for m in chosen)
        # detect ties spanning the cutoff (value of nth == value of (n+1)th)
        if len(elig) > n:
            vcut = elig[n-1][metric]
            vnext = elig[n][metric]
            if vcut == vnext:
                tied = [m["uid_hex"] for m in elig if m[metric] == vcut]
                boundary_ties.append((k, metric, vcut, tied))
    return sel, boundary_ties

def derive_membership(pool):
    grouped = defaultdict(list)
    for r in pool:
        grouped[group_key(r)].append(r)
    w_sel, w_ties = topn_by(grouped, "weight_kg")
    h_sel, h_ties = topn_by(grouped, "height_m")
    return (w_sel | h_sel), w_ties, h_ties, grouped

size5_all = [r for r in rows if r["pokemon_size_category"] == 5]
size5_bag = [r for r in size5_all if r["in_bag"] == 1]

ruleA, wtA, htA, gA = derive_membership(size5_all)   # all size=5
ruleB, wtB, htB, gB = derive_membership(size5_bag)   # in_bag size=5

# A tag can only legitimately be on in_bag rows. Restrict each rule set to in_bag
# (so we compare apples to apples with DB membership which requires in_bag=1).
inbag_uids = set(r["uid_hex"] for r in rows if r["in_bag"] == 1)
ruleA_bagrestricted = ruleA & inbag_uids

print("=== COUNTS ===")
print("DB members (in_bag=1 & tagged):", len(db_members))
print("Rule A (pool=ALL size5), raw:", len(ruleA), " restricted to in_bag:", len(ruleA_bagrestricted))
print("Rule B (pool=in_bag size5):", len(ruleB))
print()

# choose primary interpretation = B (in_bag pool) but report both
for name, ruleset in [("A_raw", ruleA), ("A_bagrestricted", ruleA_bagrestricted), ("B", ruleB)]:
    fp = db_members - ruleset
    fn = ruleset - db_members
    print(f"--- vs Rule {name}: FP(tagged not in rule)={len(fp)} FN(in rule not tagged)={len(fn)}")

print()
print("=== boundary ties (pool=in_bag size5) ===")
for k,m,v,tied in (wtB+htB):
    print(" ", m, "group", k, "value", v, "tied uids", tied)
print("=== boundary ties (pool=ALL size5) ===")
for k,m,v,tied in (wtA+htA):
    print(" ", m, "group", k, "value", v, "tied uids", tied)

# ---- detailed FP/FN for primary interpretation B and for A_bagrestricted ----
by_uid = {r["uid_hex"]: r for r in rows}

def explain(uid):
    r = by_uid.get(uid)
    if not r: return f"{uid} (NOT IN DB?)"
    return (f"{uid} pid={r['pokemon_id']} form={r['form']} cost={r['fresh_costume']} "
            f"sz={r['pokemon_size_category']} w={r['weight_kg']} h={r['height_m']} "
            f"in_bag={r['in_bag']} sp={r['species_name']} tags={r['auth_tag_names']}")

print()
print("=== DETAIL: FP/FN under Rule B (in_bag pool) ===")
fpB = sorted(db_members - ruleB); fnB = sorted(ruleB - db_members)
print("FP (tagged but fails rule B):", len(fpB))
for u in fpB: print("  FP", explain(u))
print("FN (satisfies rule B but not tagged):", len(fnB))
for u in fnB: print("  FN", explain(u))

print()
print("=== DETAIL: FP/FN under Rule A (all size5, restricted to in_bag) ===")
fpA = sorted(db_members - ruleA_bagrestricted); fnA = sorted(ruleA_bagrestricted - db_members)
print("FP:", len(fpA))
for u in fpA: print("  FP", explain(u))
print("FN:", len(fnA))
for u in fnA: print("  FN", explain(u))

# ---- (also) confirm computed set file == DB membership ----
with open(SETFILE) as f:
    fileset = set(l.strip() for l in f if l.strip())
print()
print("=== computed file vs DB ===")
print("file count:", len(fileset), "db count:", len(db_members))
print("in file not in db:", sorted(fileset - db_members))
print("in db not in file:", sorted(db_members - fileset))

# ---- and computed file vs each rule ----
print()
print("=== computed file vs Rule B ===")
print("file-not-ruleB:", len(fileset - ruleB), "ruleB-not-file:", len(ruleB - fileset))
print("=== computed file vs Rule A_bagrestricted ===")
print("file-not-A:", len(fileset - ruleA_bagrestricted), "A-not-file:", len(ruleA_bagrestricted - fileset))

con.close()
