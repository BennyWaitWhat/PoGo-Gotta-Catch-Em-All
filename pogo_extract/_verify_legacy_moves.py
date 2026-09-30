import json, sqlite3, os

DB = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
LEGACY_JSON = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/legacy_accurate.json"
TAG_FILE = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets/3_Legacy_Moves.txt"
TRANSFER_FILE = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets/6_Transfer.txt"

# --- load legacy_accurate membership set ---
with open(LEGACY_JSON, "r", encoding="utf-8") as f:
    legacy_data = json.load(f)
legacy_set = set(d["uid_hex"] for d in legacy_data)
assert len(legacy_set) == len(legacy_data), "dup uids in legacy json"

# --- pull candidate rows from DB ---
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("""
    SELECT uid_hex, pokemon_id, form, iv_total, cp, species_name, iv_pct, is_shiny, in_bag
    FROM pokemon
    WHERE in_bag = 1
""")
rows = [dict(r) for r in cur.fetchall()]
con.close()

# filter to legacy membership (string compare directly)
cand = [r for r in rows if r["uid_hex"] in legacy_set]

# group by (pokemon_id, form OR 0)
from collections import defaultdict
groups = defaultdict(list)
for r in cand:
    form = r["form"] if r["form"] is not None else 0
    key = (r["pokemon_id"], form if form else 0)
    # "form OR 0": if form is falsy (0/None) -> 0 else form
    fkey = form if form else 0
    groups[(r["pokemon_id"], fkey)].append(r)

derived = set()
derived_rows = {}
for key, members in groups.items():
    # top-4 by (iv_total DESC, cp DESC). Tie-break beyond that: deterministic by uid for stability
    members_sorted = sorted(
        members,
        key=lambda r: (-(r["iv_total"] if r["iv_total"] is not None else -1),
                       -(r["cp"] if r["cp"] is not None else -1),
                       r["uid_hex"])
    )
    for r in members_sorted[:4]:
        derived.add(r["uid_hex"])
        derived_rows[r["uid_hex"]] = r

# --- subtract 6_Transfer ---
def load_uidfile(p):
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                out.append(s)
    return out

transfer_list = load_uidfile(TRANSFER_FILE)
transfer_set = set(transfer_list)

derived_after_subtract = derived - transfer_set

# --- load the file-under-test ---
file_list = load_uidfile(TAG_FILE)
file_set = set(file_list)

# --- compare ---
extra = file_set - derived_after_subtract      # in file but not derived
missing = derived_after_subtract - file_set    # derived but not in file
match = (len(extra) == 0 and len(missing) == 0)

print("=== COUNTS ===")
print("legacy_set size:", len(legacy_set))
print("in_bag rows total:", len(rows))
print("candidates (in_bag & legacy):", len(cand))
print("groups:", len(groups))
print("derived (pre-subtract):", len(derived))
print("transfer file size:", len(transfer_list), "distinct:", len(transfer_set))
print("derived (post-subtract):", len(derived_after_subtract))
print("file size:", len(file_list), "distinct:", len(file_set))
print("file has dup lines:", len(file_list) != len(file_set))
print("EXTRA (file - derived):", len(extra))
print("MISSING (derived - file):", len(missing))
print("MATCH:", match)

# overlap of derived with transfer (how many removed by subtraction)
removed_by_transfer = derived & transfer_set
print("derived intersect transfer (removed):", len(removed_by_transfer))

# shiny sanity: any derived-after-subtract that is shiny but appears in transfer? (shouldn't be transferred)
# Also: any candidate shiny that got dropped into transfer
def ctx(uid):
    r = derived_rows.get(uid)
    if r is None:
        # fetch from db-less cand map
        for rr in cand:
            if rr["uid_hex"] == uid:
                r = rr
                break
    if r is None:
        return f"{uid} (not in candidate set)"
    form = r["form"] if r["form"] is not None else 0
    return (f"{uid} | {r['species_name']} (pid={r['pokemon_id']}, form={form}) "
            f"IV={r['iv_total']}/45 ({r['iv_pct']}) CP={r['cp']} shiny={r['is_shiny']}")

print()
print("=== UP TO 8 DISCREPANCIES ===")
disc = []
for u in sorted(extra):
    disc.append(("EXTRA", u))
for u in sorted(missing):
    disc.append(("MISSING", u))
for tag, u in disc[:8]:
    # rank context within its group
    info = ctx(u)
    print(f"[{tag}] {info}")

# dump full discrepancy lists to a side json for completeness
with open("_verify_legacy_moves_out.json", "w", encoding="utf-8") as f:
    json.dump({
        "match": match,
        "file_count": len(file_set),
        "derived_count": len(derived_after_subtract),
        "extra": sorted(extra),
        "missing": sorted(missing),
        "removed_by_transfer": sorted(removed_by_transfer),
    }, f, indent=2)
