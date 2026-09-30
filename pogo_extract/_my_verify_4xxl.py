import sqlite3, collections, os

DB = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/pokemon.db"
TAGDIR = r"C:/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract/system/analysis/tagsets"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

rows = cur.execute("""
    SELECT uid_hex, pokemon_id, species_name, form, fresh_costume,
           weight_kg, height_m, is_shiny,
           iv_atk, iv_def, iv_sta, iv_total, iv_pct
    FROM pokemon
    WHERE in_bag=1 AND pokemon_size_category=5
""").fetchall()

print("candidate rows (in_bag=1 AND size=5):", len(rows))

# group by (pokemon_id, form OR 0, fresh_costume OR 0)
groups = collections.defaultdict(list)
for r in rows:
    key = (r["pokemon_id"], r["form"] or 0, r["fresh_costume"] or 0)
    groups[key].append(r)

print("number of groups:", len(groups))

derived = set()
# Per group: top-2 by weight_kg UNION top-2 by height_m
# Deterministic: sort by metric desc, tiebreak uid_hex asc, take first 2.
for key, members in groups.items():
    by_w = sorted(members, key=lambda r: (-r["weight_kg"], r["uid_hex"]))[:2]
    by_h = sorted(members, key=lambda r: (-r["height_m"], r["uid_hex"]))[:2]
    for r in by_w:
        derived.add(r["uid_hex"])
    for r in by_h:
        derived.add(r["uid_hex"])

print("derived (pre-subtract) count:", len(derived))

# uid -> row map for context
umap = {r["uid_hex"]: r for r in rows}

def load(fname):
    p = os.path.join(TAGDIR, fname)
    s = set()
    with open(p) as f:
        for line in f:
            t = line.strip()
            if t:
                s.add(t)
    return s

file_xxl = load("4_XXL.txt")
transfer = load("6_Transfer.txt")

print("file 4_XXL count:", len(file_xxl))
print("file 6_Transfer count:", len(transfer))

# ALL shinies are kept (never transferred). Sanity: confirm transfer excludes shinies.
shiny_uids = {r["uid_hex"] for r in rows if r["is_shiny"] == 1}
print("shinies in candidate set:", len(shiny_uids))
print("shinies that appear in 6_Transfer file:", len(shiny_uids & transfer))

# SUBTRACT transfer from derived
derived_final = derived - transfer
print("derived_final (after subtract transfer) count:", len(derived_final))

extra = file_xxl - derived_final      # in file but not derived
missing = derived_final - file_xxl    # derived but not in file
match = (len(extra) == 0 and len(missing) == 0)

print("EXTRA (file - derived):", len(extra))
print("MISSING (derived - file):", len(missing))
print("MATCH:", match)

def ctx(uid):
    r = umap.get(uid)
    if not r:
        # might be in transfer/file but not in candidate set
        rr = cur.execute("SELECT uid_hex,species_name,pokemon_id,iv_atk,iv_def,iv_sta,iv_pct,is_shiny,weight_kg,height_m,in_bag,pokemon_size_category FROM pokemon WHERE uid_hex=?", (uid,)).fetchone()
        if not rr:
            return f"{uid} (NOT IN DB)"
        return f"{uid} sp={rr['species_name']} pid={rr['pokemon_id']} iv={rr['iv_atk']}/{rr['iv_def']}/{rr['iv_sta']}({rr['iv_pct']:.1f}%) shiny={rr['is_shiny']} wt={rr['weight_kg']} ht={rr['height_m']} in_bag={rr['in_bag']} size={rr['pokemon_size_category']}"
    return f"{uid} sp={r['species_name']} pid={r['pokemon_id']} iv={r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}({r['iv_pct']:.1f}%) shiny={r['is_shiny']} wt={r['weight_kg']} ht={r['height_m']}"

print("\n--- EXTRA samples (up to 8) ---")
for u in list(sorted(extra))[:8]:
    print(ctx(u))
print("\n--- MISSING samples (up to 8) ---")
for u in list(sorted(missing))[:8]:
    print(ctx(u))

# Also report how many derived items were removed by the subtract
print("\nderived items that were in transfer (subtracted):", len(derived & transfer))
con.close()
