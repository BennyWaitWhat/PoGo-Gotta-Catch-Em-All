"""Independent re-derivation of the '3 Legacy Moves' tag. Does NOT import
build_tagsets or keep_policy. Reimplements the rule from scratch."""
import sqlite3, json, os
from collections import defaultdict

ROOT = r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract"
DB = os.path.join(ROOT, "pokemon.db")
LEG_JSON = os.path.join(ROOT, "legacy_accurate.json")
TAGDIR = os.path.join(ROOT, "system", "analysis", "tagsets")
TAGFILE = os.path.join(TAGDIR, "3_Legacy_Moves.txt")
TRANSFILE = os.path.join(TAGDIR, "6_Transfer.txt")

# --- 1. legacy uid set from json ---
leg_raw = json.load(open(LEG_JSON, encoding="utf-8"))
leg = {e["uid_hex"] for e in leg_raw}
print(f"legacy_accurate.json entries={len(leg_raw)} unique_uid={len(leg)}")

# --- 2. TRANSFER set from 6_Transfer.txt ---
TRANSFER = set(open(TRANSFILE).read().split()) if os.path.exists(TRANSFILE) else set()
print(f"6_Transfer.txt members={len(TRANSFER)}")

# --- 3. pull in_bag rows (mirror build_tagsets columns we need) ---
c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("""SELECT uid_hex,pokemon_id,form,species_name,iv_total,cp,in_bag
                    FROM pokemon WHERE in_bag=1""").fetchall()
print(f"in_bag=1 rows={len(rows)}")

# --- 4. group legacy+in_bag rows by (pid, form or 0); top-4 by (iv_total desc, cp desc) ---
grp = defaultdict(list)
for r in rows:
    if r["uid_hex"] in leg:
        grp[(r["pokemon_id"], r["form"] or 0)].append(r)

derived = set()
for members in grp.values():
    for r in sorted(members, key=lambda x: (-(x["iv_total"] or 0), -(x["cp"] or 0)))[:4]:
        derived.add(r["uid_hex"])

print(f"derived_before_transfer={len(derived)}  groups={len(grp)}")

# --- 5. MINUS 6_Transfer ---
derived_final = derived - TRANSFER
print(f"derived_after_minus_transfer={len(derived_final)}")

# --- 6. load actual file set ---
file_set = set(open(TAGFILE).read().split())
print(f"file_count={len(file_set)}")

# --- 7. compare ---
only_in_file = sorted(file_set - derived_final)   # extras
only_in_rule = sorted(derived_final - file_set)   # missing
exact = (file_set == derived_final)
print(f"exact_match={exact}")
print(f"only_in_file (extras)={only_in_file}")
print(f"only_in_rule (missing)={only_in_rule}")

# --- 8. ghost check: file members with in_bag != 1 ---
inbag_map = {row[0]: row[1] for row in c.execute("SELECT uid_hex,in_bag FROM pokemon")}
ghosts = [u for u in file_set if inbag_map.get(u, None) != 1]
print(f"ghost_count={len(ghosts)}  ghosts={ghosts}")
# also flag any file member not present in DB at all
not_in_db = [u for u in file_set if u not in inbag_map]
print(f"file_members_not_in_db={not_in_db}")

# --- 9. how many derived would-be members got removed purely by the transfer subtraction ---
removed_by_transfer = sorted(derived & TRANSFER)
print(f"removed_by_transfer_subtraction={len(removed_by_transfer)} -> {removed_by_transfer}")

# --- 10. spot-check 3 real members: trace why they belong ---
print("\n--- SPOT CHECKS ---")
spot = list(file_set)[:3]
for u in spot:
    row = c.execute("""SELECT uid_hex,pokemon_id,form,species_name,iv_total,cp,in_bag
                       FROM pokemon WHERE uid_hex=?""", (u,)).fetchone()
    if not row:
        print(f"{u}: NOT IN DB"); continue
    key = (row["pokemon_id"], row["form"] or 0)
    g = sorted(grp[key], key=lambda x: (-(x["iv_total"] or 0), -(x["cp"] or 0)))
    rank = [m["uid_hex"] for m in g].index(u) + 1
    in_leg = u in leg
    in_tr = u in TRANSFER
    print(f"{u} {row['species_name']} pid={row['pokemon_id']} form={row['form']} "
          f"iv={row['iv_total']} cp={row['cp']} in_bag={row['in_bag']} | "
          f"in_legacy={in_leg} group_size={len(g)} rank_in_group={rank}/4cut in_transfer={in_tr}")
c.close()
