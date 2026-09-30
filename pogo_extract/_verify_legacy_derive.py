import os, json, sqlite3

ROOT = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
TAGS = os.path.join(ROOT, "system", "analysis", "tagsets")
DB = os.path.join(ROOT, "pokemon.db")

def read_tagfile(path):
    raw = open(path, "rb").read().decode("utf-8")
    # split on any newline style, strip CR/whitespace, drop empties
    out = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = line.strip()
        if s:
            out.append(s)
    return out

# ---- inputs ----
legacy = json.load(open(os.path.join(ROOT, "legacy_accurate.json")))
legacy_uids = set(r["uid_hex"] for r in legacy)   # direct hex strings
print("legacy_accurate uids:", len(legacy_uids), "(records:", len(legacy), ")")

transfer_list = read_tagfile(os.path.join(TAGS, "6_Transfer.txt"))
transfer_set = set(transfer_list)
print("6_Transfer uids:", len(transfer_list), "unique:", len(transfer_set))

file_list = read_tagfile(os.path.join(TAGS, "3_Legacy_Moves.txt"))
file_set = set(file_list)
print("3_Legacy_Moves file uids:", len(file_list), "unique:", len(file_set))

# ---- DB pull ----
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()
# Pull all in_bag=1 rows with fields we need. Compare uid_hex as STRING.
rows = cur.execute("""
    SELECT uid_hex, pokemon_id, form, iv_total, cp, species_name
    FROM pokemon
    WHERE in_bag = 1
""").fetchall()
con.close()
print("in_bag=1 rows total:", len(rows))

# Filter: uid_hex in legacy_accurate (direct string membership)
cand = [r for r in rows if r["uid_hex"] in legacy_uids]
print("in_bag=1 AND in legacy_accurate:", len(cand))

# How many legacy uids are NOT in bag (or not in DB)?
cand_uids = set(r["uid_hex"] for r in cand)
legacy_not_in_bag = legacy_uids - cand_uids
print("legacy uids not matched by in_bag=1 rows:", len(legacy_not_in_bag))

# group by (pokemon_id, form OR 0); per group top-4 by (iv_total DESC, cp DESC)
from collections import defaultdict
groups = defaultdict(list)
for r in cand:
    form = r["form"] if r["form"] is not None else 0
    key = (r["pokemon_id"], form)
    groups[key].append(r)

derived = set()
rank_ctx = {}  # uid -> (rank, group, iv, cp, species)
for key, lst in groups.items():
    # sort: iv_total DESC, cp DESC. Tie-break must be deterministic -> add uid_hex for stable order.
    lst_sorted = sorted(lst, key=lambda r: (-(r["iv_total"] or 0), -(r["cp"] or 0), r["uid_hex"]))
    for i, r in enumerate(lst_sorted):
        if i < 4:
            derived.add(r["uid_hex"])
            rank_ctx[r["uid_hex"]] = (i + 1, key, r["iv_total"], r["cp"], r["species_name"])

print("derived top-4 (pre-transfer-subtract):", len(derived))

# SUBTRACT transfer set
overlap_with_transfer = derived & transfer_set
print("derived & transfer (removed):", len(overlap_with_transfer))
derived_final = derived - transfer_set
print("derived FINAL (after subtract):", len(derived_final))

# ---- compare to file ----
extra = file_set - derived_final      # in file, not derived
missing = derived_final - file_set    # derived, not in file
match = (len(extra) == 0 and len(missing) == 0)
print()
print("=== COMPARISON ===")
print("file uids:", len(file_set))
print("derived_final uids:", len(derived_final))
print("extra (file - derived):", len(extra))
print("missing (derived - file):", len(missing))
print("MATCH:", match)

# Sanity: does the file contain any transfer mon? (rule says no keep tag may)
file_has_transfer = file_set & transfer_set
print("file & transfer:", len(file_has_transfer))

# ---- discrepancy context (up to 8 each) ----
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()
def ctx(uid):
    r = cur.execute("SELECT uid_hex, species_name, pokemon_id, form, iv_total, cp, in_bag FROM pokemon WHERE uid_hex=?", (uid,)).fetchone()
    if r is None:
        return f"{uid} NOT IN DB"
    inleg = uid in legacy_uids
    intr = uid in transfer_set
    rk = rank_ctx.get(uid)
    rankinfo = f"rank{rk[0]} in grp{rk[1]}" if rk else "not-in-derived-top4"
    return (f"{uid} {r['species_name']}(id={r['pokemon_id']},form={r['form']}) "
            f"iv={r['iv_total']} cp={r['cp']} in_bag={r['in_bag']} "
            f"legacy={inleg} transfer={intr} | {rankinfo}")

print()
print("=== EXTRA (in file, not in derived) up to 8 ===")
for u in list(extra)[:8]:
    print(" ", ctx(u))
print()
print("=== MISSING (derived, not in file) up to 8 ===")
for u in list(missing)[:8]:
    print(" ", ctx(u))
con.close()

# dump for examples
out = {
    "file_count": len(file_set),
    "derived_count": len(derived_final),
    "extra_count": len(extra),
    "missing_count": len(missing),
    "match": match,
    "extra_sample": list(extra)[:8],
    "missing_sample": list(missing)[:8],
    "file_has_transfer": len(file_has_transfer),
    "legacy_not_in_bag": len(legacy_not_in_bag),
    "groups": len(groups),
    "overlap_with_transfer_removed": len(overlap_with_transfer),
}
json.dump(out, open(os.path.join(ROOT, "_verify_legacy_out.json"), "w"), indent=2)
print()
print("WROTE _verify_legacy_out.json")
