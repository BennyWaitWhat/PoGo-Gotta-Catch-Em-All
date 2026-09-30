import sqlite3, os

DB = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
TAGDIR = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets"
HUNDO_FILE = os.path.join(TAGDIR, "4_Hundo.txt")
TRANSFER_FILE = os.path.join(TAGDIR, "6_Transfer.txt")

def load_uids(path):
    s = set()
    dups = 0
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            u = line.strip()
            if not u:
                continue
            if u in s:
                dups += 1
            s.add(u)  # keep verbatim string, no int()/reformat
    return s, dups

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Rule: in_bag=1 AND iv_total=45  (string uid_hex verbatim)
cur.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND iv_total=45")
rule_rows = [r[0] for r in cur.fetchall()]
rule_set = set(rule_rows)
print("rule rows:", len(rule_rows), "distinct uid_hex:", len(rule_set))

# Sanity: confirm any uid_hex not 16 chars, or non-hex
bad = [u for u in rule_set if len(u) != 16]
print("rule uids with len!=16:", bad)

# Transfer set
transfer_set, t_dups = load_uids(TRANSFER_FILE)
print("transfer file uids:", len(transfer_set), "dups-in-file:", t_dups)

# Derived = rule - transfer (no keep tag may contain a transfer mon)
derived = rule_set - transfer_set
overlap = rule_set & transfer_set
print("rule ∩ transfer (removed):", len(overlap))
print("DERIVED count:", len(derived))

# File set
file_set, h_dups = load_uids(HUNDO_FILE)
print("hundo file uids:", len(file_set), "dups-in-file:", h_dups)

# Compare (direct string compare)
extra = file_set - derived      # in file, not derived
missing = derived - file_set    # derived, not in file
match = (len(extra) == 0 and len(missing) == 0)
print("EXTRA (file - derived):", len(extra))
print("MISSING (derived - file):", len(missing))
print("MATCH:", match)

# Does the file itself contain any transfer mon? (the rule the tagset must obey)
file_transfer_overlap = file_set & transfer_set
print("file ∩ transfer (violation):", len(file_transfer_overlap), sorted(file_transfer_overlap)[:8])

# context for discrepancies
def ctx(uids):
    out = []
    for u in sorted(uids)[:8]:
        cur.execute("SELECT uid_hex, species_name, iv_atk, iv_def, iv_sta, iv_total, in_bag, gl_rank, cull_decision_v9 FROM pokemon WHERE uid_hex=?", (u,))
        row = cur.fetchone()
        if row is None:
            out.append((u, "NOT-IN-DB"))
        else:
            out.append(row)
    return out

print("\n--- EXTRA context (in file, not derived) ---")
for r in ctx(extra):
    print(r)
print("\n--- MISSING context (derived, not in file) ---")
for r in ctx(missing):
    print(r)

conn.close()
