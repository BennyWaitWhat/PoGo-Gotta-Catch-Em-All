import sqlite3, os

DB = os.path.join(os.getcwd(), "pokemon.db")
TAGDIR = os.path.join(os.getcwd(), "system", "analysis", "tagsets")
BB_FILE = os.path.join(TAGDIR, "3_Best_Buddy.txt")
TR_FILE = os.path.join(TAGDIR, "6_Transfer.txt")

def load_tagfile(path):
    s = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            parts = line.split("\t")
            uid = parts[-1].strip()  # last column is uid_hex; first is index
            s.append(uid)
    return s

bb_file_list = load_tagfile(BB_FILE)
tr_file_list = load_tagfile(TR_FILE)
bb_file = set(bb_file_list)
tr_file = set(tr_file_list)
assert len(bb_file_list) == len(bb_file), f"dup in BB file {len(bb_file_list)} vs {len(bb_file)}"
assert len(tr_file_list) == len(tr_file), f"dup in TR file {len(tr_file_list)} vs {len(tr_file)}"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# Independently re-derive: in_bag=1 AND was_best_buddy_badge=1
# Pull all rows, apply rule in python (do NOT trust a precomputed tag col).
rows = cur.execute("""
    SELECT uid_hex, in_bag, was_best_buddy_badge, is_best_buddy, is_shiny,
           species_name, iv_atk, iv_def, iv_sta, iv_total, iv_pct,
           cp, level, gl_rank, ul_rank, ll_rank
    FROM pokemon
""").fetchall()

ctx = {}
derived = set()
null_inbag = 0
null_badge = 0
for r in rows:
    u = r["uid_hex"]
    # uid_hex should already be zero-padded 16-char per project; verify
    ctx[u] = r
    ib = r["in_bag"]
    wb = r["was_best_buddy_badge"]
    if ib is None: null_inbag += 1
    if wb is None: null_badge += 1
    # Rule: in_bag=1 AND was_best_buddy_badge=1
    if ib == 1 and wb == 1:
        derived.add(u)

# uid_hex length check
badlen = [u for u in ctx if len(u) != 16]

# Compare derived tag vs file (3_Best_Buddy.txt)
bb_extra   = bb_file - derived   # in file, not in my derivation
bb_missing = derived - bb_file   # in my derivation, not in file
print("=== STEP 1: re-derive 3 Best Buddy (in_bag=1 AND was_best_buddy_badge=1) ===")
print("total rows                :", len(rows))
print("NULL in_bag count         :", null_inbag)
print("NULL was_best_buddy_badge :", null_badge)
print("uid_hex not 16 chars      :", len(badlen), badlen[:5])
print("derived count             :", len(derived))
print("file count (3_Best_Buddy) :", len(bb_file))
print("BB extra (file - derived) :", len(bb_extra), sorted(bb_extra))
print("BB missing (derived-file) :", len(bb_missing), sorted(bb_missing))
print("BB exact match            :", len(bb_extra)==0 and len(bb_missing)==0)

# Cross-check: any shiny in the derived set? (all shinies kept; BB tag is keep-side, fine either way)
sh = [u for u in derived if ctx[u]["is_shiny"]==1]
print("shinies within derived BB :", len(sh))

# Also compare derived against is_best_buddy (current best buddy) to note semantic
ibb = sum(1 for r in rows if r["is_best_buddy"]==1)
print("rows is_best_buddy=1      :", ibb, "(distinct from was_best_buddy_badge)")

print()
print("=== STEP 2: SUBTRACT 6_Transfer.txt ===")
# "Then SUBTRACT 6_Transfer.txt" — final keep-set = derived tag minus transfer set.
final_derived = derived - tr_file
# The file we compare against is still 3_Best_Buddy.txt (the produced tagset).
# Per spec: extra = file-derived ; missing = derived-file ; using FINAL (post-subtract) derived.
final_extra   = bb_file - final_derived   # in file, not in final derived
final_missing = final_derived - bb_file   # in final derived, not in file
print("transfer file count       :", len(tr_file))
overlap = derived & tr_file
print("BB-derived ∩ transfer     :", len(overlap), sorted(overlap))
print("final derived count       :", len(final_derived))
print("file count                :", len(bb_file))
print("FINAL extra (file-derived):", len(final_extra), sorted(final_extra))
print("FINAL missing(derived-file):", len(final_missing), sorted(final_missing))
print("FINAL match               :", len(final_extra)==0 and len(final_missing)==0)

# Build discrepancy context (up to 8), union of extra+missing from the FINAL comparison
disc = []
for u in sorted(final_extra):
    disc.append(("extra", u))
for u in sorted(final_missing):
    disc.append(("missing", u))
print()
print("=== DISCREPANCY CONTEXT (up to 8) ===")
for kind, u in disc[:8]:
    if u in ctx:
        r = ctx[u]
        rank = r["gl_rank"]
        print(f"{kind:7} {u} sp={r['species_name']} iv={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']} "
              f"({r['iv_pct']}) cp={r['cp']} L{r['level']} glrank={r['gl_rank']} ulrank={r['ul_rank']} "
              f"inbag={r['in_bag']} badge={r['was_best_buddy_badge']} shiny={r['is_shiny']}")
    else:
        print(f"{kind:7} {u} (NOT FOUND IN DB)")
print("total discrepancies       :", len(disc))

con.close()
