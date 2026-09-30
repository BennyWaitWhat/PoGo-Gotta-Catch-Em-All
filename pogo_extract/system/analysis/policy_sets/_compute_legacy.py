"""
Compute the protected UID set for keep-rule "legacy" (KEEP_POLICY.md §4:
"Legacy / event-only moves: top 4" per (species, form)).

Universe: mons whose uid_hex appears in legacy_accurate.json.
Selection: top 4 by iv_total, tiebreak cp (both desc), grouped by (pokemon_id, form).
Source of truth for the deciding stats = the DB (in_bag=1), per memory note
"Source of truth = DB rules". The JSON only defines membership.
READ-ONLY: no writes to the DB, no device/Frida.
"""
import json
import os
import sqlite3
from collections import defaultdict

ROOT = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
JSON_PATH = os.path.join(ROOT, "legacy_accurate.json")
DB_PATH = os.path.join(ROOT, "pokemon.db")
OUT_DIR = os.path.join(ROOT, "system", "analysis", "policy_sets")
OUT_PATH = os.path.join(OUT_DIR, "legacy.txt")

CAP = 4

with open(JSON_PATH, "r", encoding="utf-8") as f:
    legacy = json.load(f)
universe = {x["uid_hex"] for x in legacy}

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

placeholders = ",".join("?" * len(universe))
cur.execute(
    f"""SELECT uid_hex, pokemon_id, form, species_name, iv_total, cp, fresh_form, form_region
        FROM pokemon
        WHERE in_bag=1 AND uid_hex IN ({placeholders})""",
    tuple(universe),
)
rows = cur.fetchall()
con.close()

# Group by (pokemon_id, form).
groups = defaultdict(list)
for r in rows:
    groups[(r["pokemon_id"], r["form"])].append(r)

protected = []  # (uid_hex, species_name, iv_total, cp, pokemon_id, form, rank_in_group, group_size)
for key, members in groups.items():
    # Sort: iv_total desc, then cp desc. Deterministic final tiebreak on uid_hex
    # so the cut is stable if iv_total AND cp are both tied at the boundary.
    members.sort(key=lambda r: (-r["iv_total"], -r["cp"], r["uid_hex"]))
    gsize = len(members)
    for i, r in enumerate(members[:CAP]):
        protected.append(
            (r["uid_hex"], r["species_name"], r["iv_total"], r["cp"],
             r["pokemon_id"], r["form"], i + 1, gsize)
        )

# Write the UID set, sorted for stable diffing.
protected_uids = sorted({p[0] for p in protected})
os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
    for u in protected_uids:
        f.write(u + "\n")

# --- Diagnostics to stdout ---
print("universe (json uids):", len(universe))
print("matched in-bag rows:", len(rows))
print("groups (pokemon_id,form):", len(groups))
print("protected uids written:", len(protected_uids))
assert len(protected_uids) == len(protected), "duplicate uid across groups?!"

# How many got trimmed (universe minus protected).
trimmed = len(universe) - len(protected_uids)
print("trimmed (universe - protected):", trimmed)

# Detect tie-at-the-boundary judgment calls: groups where the 4th-kept and the
# 5th (first-cut) share the same (iv_total, cp) -> the uid_hex tiebreak decided it.
print("\n-- boundary ties (cap actually arbitrated a tie) --")
boundary_ties = 0
for key, members in groups.items():
    if len(members) <= CAP:
        continue
    s = sorted(members, key=lambda r: (-r["iv_total"], -r["cp"], r["uid_hex"]))
    kept4 = s[CAP - 1]
    cut1 = s[CAP]
    if (kept4["iv_total"], kept4["cp"]) == (cut1["iv_total"], cut1["cp"]):
        boundary_ties += 1
        print(f"  TIE pid={key[0]} form={key[1]} {kept4['species_name']}: "
              f"kept uid={kept4['uid_hex']} vs cut uid={cut1['uid_hex']} "
              f"(both iv={kept4['iv_total']} cp={kept4['cp']})")
if not boundary_ties:
    print("  none")

# 6-item sample across distinct species, showing the deciding stat (iv_total, cp tiebreak).
print("\n-- sample (6) --")
seen = set()
sample = []
for p in sorted(protected, key=lambda x: (-x[2], -x[3])):
    if p[1] in seen:
        continue
    seen.add(p[1])
    sample.append(p)
    if len(sample) == 6:
        break
for p in sample:
    print(f"  {p[1]} (pid={p[4]} form={p[5]}): iv_total={p[2]}, cp={p[3]} "
          f"[rank {p[6]}/{p[7]} in group] uid={p[0]}")
