import json, sqlite3, os, glob

BASE = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
DB = os.path.join(BASE, "pokemon.db")
TAGDIR = os.path.join(BASE, "system", "analysis", "tagsets")
POLICY = os.path.join(BASE, "system", "analysis", "policy_reasons.json")
TRANSFER_FILE = os.path.join(TAGDIR, "6_Transfer.txt")

def read_tagfile(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()  # strips \r \n spaces
            if s:
                out.append(s)
    return out

with open(POLICY, "r", encoding="utf-8") as f:
    policy = json.load(f)
KEEP = set(policy.keys())

transfer_list = read_tagfile(TRANSFER_FILE)
TRANSFER = set(transfer_list)

con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1")
inbag_list = [r[0] for r in cur.fetchall()]
INBAG = set(inbag_list)
cur.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND is_shiny=1")
INBAG_SHINY = set(r[0] for r in cur.fetchall())
cur.execute("SELECT uid_hex FROM pokemon WHERE is_shiny=1")
ALL_SHINY = set(r[0] for r in cur.fetchall())
cur.execute("SELECT uid_hex, in_bag FROM pokemon")
DBMAP = dict(cur.fetchall())
con.close()

print("=== SET SIZES ===")
print("KEEP (policy keys)      :", len(KEEP))
print("TRANSFER 6_Transfer     : lines=%d unique=%d dups=%d" % (len(transfer_list), len(TRANSFER), len(transfer_list)-len(TRANSFER)))
print("INBAG (in_bag=1)        :", len(INBAG))
print("INBAG_SHINY             :", len(INBAG_SHINY))
print("ALL_SHINY               :", len(ALL_SHINY))

violations = 0
details = []

overlap = KEEP & TRANSFER
print("\n=== CHECK 1: KEEP disjoint TRANSFER ===")
print("overlap count:", len(overlap))
if overlap:
    violations += len(overlap)
    for u in sorted(overlap):
        details.append("[C1 overlap] %s in BOTH KEEP and TRANSFER" % u)
check1 = (len(overlap) == 0)

union = KEEP | TRANSFER
uncovered = INBAG - union
extra = union - INBAG
print("\n=== CHECK 2: KEEP u TRANSFER == INBAG ===")
print("union size:", len(union))
print("uncovered (INBAG not in union):", len(uncovered))
print("extra (union not in INBAG):", len(extra))
if uncovered:
    violations += len(uncovered)
    for u in sorted(uncovered):
        details.append("[C2 uncovered] %s in_bag=1 but neither KEEP nor TRANSFER" % u)
if extra:
    violations += len(extra)
    for u in sorted(extra):
        src=[]
        if u in KEEP: src.append("KEEP")
        if u in TRANSFER: src.append("TRANSFER")
        in_db = "yes" if u in DBMAP else "NOT_IN_DB"
        ib = DBMAP.get(u, "NA")
        details.append("[C2 extra] %s in %s but in_bag!=1 (in_db=%s in_bag=%s)" % (u, "+".join(src), in_db, ib))
check2 = (len(uncovered) == 0 and len(extra) == 0)
if extra:
    not_in_db = [u for u in extra if u not in DBMAP]
    in_db_not_bag = [u for u in extra if u in DBMAP and DBMAP[u] != 1]
    print("  extra breakdown: not_in_db=%d in_db_but_in_bag!=1=%d" % (len(not_in_db), len(in_db_not_bag)))

print("\n=== CHECK 3: KEEP tag files subset of KEEP and disjoint TRANSFER ===")
keep_tag_files = sorted(glob.glob(os.path.join(TAGDIR, "*.txt")))
c3_not_keep = 0
c3_in_transfer = 0
per_file = []
for path in keep_tag_files:
    fname = os.path.basename(path)
    if fname == "6_Transfer.txt":
        continue
    uids = read_tagfile(path)
    nk = 0; nt = 0
    for u in uids:
        if u not in KEEP:
            nk += 1; violations += 1; c3_not_keep += 1
            details.append("[C3 not-in-KEEP] %s: %s tagged but NOT in KEEP" % (fname, u))
        if u in TRANSFER:
            nt += 1; violations += 1; c3_in_transfer += 1
            details.append("[C3 in-TRANSFER] %s: %s tagged (KEEP file) but IS in TRANSFER" % (fname, u))
    per_file.append((fname, len(uids), nk, nt))

print("%-20s %6s %8s %11s" % ("file","lines","notKEEP","inTRANSFER"))
for fname, n, nk, nt in per_file:
    print("%-20s %6d %8d %11d" % (fname, n, nk, nt))
print("\nC3 totals: tagged-not-in-KEEP=%d tagged-in-TRANSFER=%d" % (c3_not_keep, c3_in_transfer))
check3 = (c3_not_keep == 0 and c3_in_transfer == 0)

print("\n=== SUMMARY ===")
print("CHECK 1:", "PASS" if check1 else "FAIL")
print("CHECK 2:", "PASS" if check2 else "FAIL")
print("CHECK 3:", "PASS" if check3 else "FAIL")
print("TOTAL VIOLATIONS:", violations)
overall = check1 and check2 and check3
print("OVERALL PASSED:", overall)

shiny_in_transfer = ALL_SHINY & TRANSFER
inbag_shiny_not_keep = INBAG_SHINY - KEEP
print("\n=== SHINY RULE CONTEXT (all shinies kept, never transferred) ===")
print("shinies (any) in TRANSFER:", len(shiny_in_transfer))
print("in-bag shinies NOT in KEEP:", len(inbag_shiny_not_keep))

print("\n###RESULT###")
print(json.dumps({
 "violations": violations, "check1": check1, "check2": check2, "check3": check3, "overall": overall,
 "c1_overlap": len(overlap), "c2_uncovered": len(uncovered), "c2_extra": len(extra),
 "c3_not_keep": c3_not_keep, "c3_in_transfer": c3_in_transfer, "transfer_dups": len(transfer_list)-len(TRANSFER),
 "shiny_in_transfer": len(shiny_in_transfer), "inbag_shiny_not_keep": len(inbag_shiny_not_keep)}))
print("\n###DETAILS(first 80)###")
for d in details[:80]:
    print(d)
