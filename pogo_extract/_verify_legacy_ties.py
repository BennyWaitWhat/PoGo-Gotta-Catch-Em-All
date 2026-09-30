import os, json, sqlite3
from collections import defaultdict

ROOT = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"
TAGS = os.path.join(ROOT, "system", "analysis", "tagsets")
DB = os.path.join(ROOT, "pokemon.db")

legacy = json.load(open(os.path.join(ROOT, "legacy_accurate.json")))
legacy_uids = set(r["uid_hex"] for r in legacy)

con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
rows = con.execute("SELECT uid_hex, pokemon_id, form, iv_total, cp, species_name FROM pokemon WHERE in_bag=1").fetchall()
con.close()
cand = [r for r in rows if r["uid_hex"] in legacy_uids]

groups = defaultdict(list)
for r in cand:
    form = r["form"] if r["form"] is not None else 0
    groups[(r["pokemon_id"], form)].append(r)

# Group size distribution
sizes = defaultdict(int)
for k, lst in groups.items():
    sizes[len(lst)] += 1
print("group count:", len(groups))
print("group-size distribution (size:count):", dict(sorted(sizes.items())))
oversized = {k: v for k, v in groups.items() if len(v) > 4}
print("groups with >4 members (these are the only ones where top-4 truncation matters):")
for k in sorted(oversized.keys()):
    print("  group", k, "size", len(oversized[k]))

# For each oversized group, check for a tie straddling the rank-4/rank-5 boundary
# i.e. members 4 and 5 (1-indexed) share identical (iv_total, cp).
print()
print("=== boundary-tie check (rank4 vs rank5 identical iv & cp) ===")
ambiguous = 0
for k, lst in oversized.items():
    # sort WITHOUT uid tiebreak to inspect the natural ordering ties
    s = sorted(lst, key=lambda r: (-(r["iv_total"] or 0), -(r["cp"] or 0)))
    r4 = s[3]; r5 = s[4]
    tie = (r4["iv_total"] == r5["iv_total"]) and (r4["cp"] == r5["cp"])
    species = lst[0]["species_name"]
    print(f"  {species} {k} size={len(lst)}: "
          f"rank4=(iv {r4['iv_total']},cp {r4['cp']},{r4['uid_hex']}) "
          f"rank5=(iv {r5['iv_total']},cp {r5['cp']},{r5['uid_hex']}) boundary_tie={tie}")
    if tie:
        ambiguous += 1
        # list everyone sharing that iv/cp to see how many compete for the cutoff
        same = [x for x in lst if x["iv_total"]==r4["iv_total"] and x["cp"]==r4["cp"]]
        print("     ", len(same), "members tie at iv", r4["iv_total"], "cp", r4["cp"], ":",
              [x["uid_hex"] for x in same])

print()
print("AMBIGUOUS boundary groups:", ambiguous)
print("If 0 -> the top-4 selection is unambiguous regardless of tie-break; the match is robust.")
