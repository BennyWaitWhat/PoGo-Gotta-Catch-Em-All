import sqlite3, os

DB = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
TAGDIR = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets"

def load_file(name):
    p = os.path.join(TAGDIR, name)
    s = set()
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if t:
                s.add(t)
    return s

con = sqlite3.connect(DB)
cur = con.cursor()

# Sanity: distinct in_bag values, iv_total range, NULL checks
print("=== in_bag distinct ===")
for r in cur.execute("SELECT in_bag, COUNT(*) FROM pokemon GROUP BY in_bag ORDER BY in_bag"):
    print(r)
print("=== iv_total distinct (top by value) ===")
for r in cur.execute("SELECT iv_total, COUNT(*) FROM pokemon WHERE iv_total IS NOT NULL GROUP BY iv_total ORDER BY iv_total DESC LIMIT 5"):
    print(r)
print("=== iv_total NULL count ===")
print(cur.execute("SELECT COUNT(*) FROM pokemon WHERE iv_total IS NULL").fetchone())

# uid_hex format sanity
print("=== uid_hex length distribution ===")
for r in cur.execute("SELECT LENGTH(uid_hex), COUNT(*) FROM pokemon GROUP BY LENGTH(uid_hex)"):
    print(r)

# Derive raw hundo set: in_bag=1 AND iv_total=45
derived_raw = set()
for (uh,) in cur.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND iv_total=45"):
    derived_raw.add(uh)
print("=== derived_raw (in_bag=1 AND iv_total=45) count ===", len(derived_raw))

# Also compute via is_hundo flag for cross-check
hundo_flag = set()
for (uh,) in cur.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND is_hundo=1"):
    hundo_flag.add(uh)
print("=== cross-check in_bag=1 AND is_hundo=1 count ===", len(hundo_flag))
print("    diff (iv45 not flag):", len(derived_raw - hundo_flag), " (flag not iv45):", len(hundo_flag - derived_raw))

transfer = load_file("6_Transfer.txt")
print("=== 6_Transfer.txt count ===", len(transfer))
hundo_file = load_file("4_Hundo.txt")
print("=== 4_Hundo.txt count ===", len(hundo_file))

# Validate file uids exist in DB and are 16-char
all_db = set()
for (uh,) in cur.execute("SELECT uid_hex FROM pokemon"):
    all_db.add(uh)
print("=== hundo_file uids not in DB ===", len(hundo_file - all_db))
print("=== transfer uids not in DB ===", len(transfer - all_db))
badlen_h = [u for u in hundo_file if len(u)!=16]
badlen_t = [u for u in transfer if len(u)!=16]
print("    hundo_file non-16-char:", badlen_h[:5], "count", len(badlen_h))
print("    transfer non-16-char:", badlen_t[:5], "count", len(badlen_t))

# Apply subtraction
derived_final = derived_raw - transfer
print("=== derived_final (derived_raw - transfer) count ===", len(derived_final))

# Overlap between derived_raw and transfer
overlap = derived_raw & transfer
print("=== hundos that ARE in transfer (subtracted out) ===", len(overlap))

# NEW RULE check: any shiny in transfer set?
transfer_list = "','".join(transfer)
shiny_in_transfer = []
for (uh, isshiny, sp, ivt, inbag) in cur.execute(
    f"SELECT uid_hex, is_shiny, species_name, iv_total, in_bag FROM pokemon WHERE uid_hex IN ('{transfer_list}')"):
    if isshiny == 1:
        shiny_in_transfer.append((uh, sp, ivt, inbag))
print("=== SHINIES present in 6_Transfer.txt (violates NEW RULE) ===", len(shiny_in_transfer))
for r in shiny_in_transfer[:10]:
    print("   ", r)

# Compare
extra = hundo_file - derived_final
missing = derived_final - hundo_file
print("=== EXTRA (file - derived) ===", len(extra))
print("=== MISSING (derived - file) ===", len(missing))
print("=== MATCH ===", (len(extra)==0 and len(missing)==0))

# Context for discrepancies (up to 8)
def ctx(uids, label):
    out=[]
    for uh in list(uids)[:8]:
        row = cur.execute("SELECT uid_hex, species_name, iv_total, iv_atk, iv_def, iv_sta, is_shiny, in_bag, is_hundo FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
        out.append((label, row))
    return out

print("=== EXTRA context ===")
for x in ctx(extra, "EXTRA"):
    print("   ", x)
print("=== MISSING context ===")
for x in ctx(missing, "MISSING"):
    print("   ", x)

con.close()
