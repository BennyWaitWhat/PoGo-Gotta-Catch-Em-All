"""Costume audit for in-bag pokemon with fresh_costume != 0."""
import json
import sqlite3
import sys
from collections import defaultdict

# Ensure stdout can handle unicode
sys.stdout.reconfigure(encoding="utf-8")

DB = "pokemon.db"
OUT = "agent_outputs/costume_audit.json"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute(
    """
    SELECT
        uid_hex, pokemon_id, species_name,
        fresh_costume, costume,
        cp, iv_total, iv_atk, iv_def, iv_sta, iv_pct, is_hundo,
        is_shiny, is_lucky, is_best_buddy, level, nickname,
        is_legendary, is_mythical, gender_name,
        creation_date, cull_decision_v9, cull_reason_v9,
        auth_tag_names
    FROM pokemon
    WHERE in_bag = 1
      AND fresh_costume IS NOT NULL
      AND fresh_costume != 0
    ORDER BY species_name, fresh_costume, iv_pct DESC, cp DESC
    """
).fetchall()

tree = defaultdict(lambda: defaultdict(list))
species_costume_stats = defaultdict(lambda: defaultdict(lambda: {"count": 0, "best_iv_pct": -1.0, "best_iv_total": -1, "hundo_count": 0, "shiny_count": 0, "lucky_count": 0}))
costume_totals = defaultdict(int)
species_totals = defaultdict(int)

total = 0
hundo_costumes = []

for r in rows:
    total += 1
    sp = r["species_name"] or f"#{r['pokemon_id']}"
    cos = int(r["fresh_costume"])
    iv_pct = r["iv_pct"] or 0.0
    iv_total = r["iv_total"] or 0

    instance = {
        "uid_hex": r["uid_hex"],
        "pokemon_id": r["pokemon_id"],
        "cp": r["cp"],
        "level": r["level"],
        "iv_pct": round(iv_pct, 1),
        "iv_total": iv_total,
        "iv_breakdown": f"{r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}",
        "is_hundo": bool(r["is_hundo"]),
        "is_shiny": bool(r["is_shiny"]),
        "is_lucky": bool(r["is_lucky"]),
        "is_best_buddy": bool(r["is_best_buddy"]),
        "gender": r["gender_name"],
        "nickname": r["nickname"],
        "creation_date": r["creation_date"],
        "cull_decision": r["cull_decision_v9"],
        "cull_reason": r["cull_reason_v9"],
        "auth_tags": r["auth_tag_names"],
        "is_legendary": bool(r["is_legendary"]),
        "is_mythical": bool(r["is_mythical"]),
    }
    tree[sp][str(cos)].append(instance)

    s = species_costume_stats[sp][cos]
    s["count"] += 1
    if iv_pct > s["best_iv_pct"]:
        s["best_iv_pct"] = round(iv_pct, 1)
        s["best_iv_total"] = iv_total
    if r["is_hundo"]:
        s["hundo_count"] += 1
        hundo_costumes.append({
            "species": sp,
            "pokemon_id": r["pokemon_id"],
            "costume_id": cos,
            "uid_hex": r["uid_hex"],
            "cp": r["cp"],
            "level": r["level"],
            "is_shiny": bool(r["is_shiny"]),
            "is_lucky": bool(r["is_lucky"]),
            "nickname": r["nickname"],
        })
    if r["is_shiny"]:
        s["shiny_count"] += 1
    if r["is_lucky"]:
        s["lucky_count"] += 1

    costume_totals[cos] += 1
    species_totals[sp] += 1

# Duplicates: (species, costume) bucket with > 1 instance
duplicates = []
for sp, costs in species_costume_stats.items():
    for cos, st in costs.items():
        if st["count"] > 1:
            # sort instances by IV desc, then CP desc, mark "keeper" = first, others = candidates
            insts = sorted(tree[sp][str(cos)], key=lambda x: (-(x["iv_pct"] or 0), -(x["cp"] or 0), -(x["iv_total"] or 0)))
            keeper = insts[0]
            extras = insts[1:]
            duplicates.append({
                "species": sp,
                "costume_id": cos,
                "count": st["count"],
                "keeper": {"uid_hex": keeper["uid_hex"], "iv_pct": keeper["iv_pct"], "cp": keeper["cp"], "is_hundo": keeper["is_hundo"], "is_shiny": keeper["is_shiny"]},
                "transfer_candidates": [
                    {
                        "uid_hex": x["uid_hex"],
                        "iv_pct": x["iv_pct"],
                        "cp": x["cp"],
                        "is_hundo": x["is_hundo"],
                        "is_shiny": x["is_shiny"],
                        "is_lucky": x["is_lucky"],
                        "level": x["level"],
                    } for x in extras
                ],
            })

# Sort duplicates by extra count desc
duplicates.sort(key=lambda d: (-len(d["transfer_candidates"]), d["species"]))

# Top costumes (most common)
top_costumes = sorted(costume_totals.items(), key=lambda x: -x[1])

# species_costume_stats convert defaultdict to dict for JSON
summary_by_species = {
    sp: {str(cos): st for cos, st in costs.items()}
    for sp, costs in species_costume_stats.items()
}

# Output tree (sorted keys for readability)
out_tree = {
    sp: {cos: insts for cos, insts in sorted(costs.items(), key=lambda x: int(x[0]))}
    for sp, costs in sorted(tree.items())
}

output = {
    "metadata": {
        "total_costumed_in_bag": total,
        "distinct_species_with_costume": len(species_totals),
        "distinct_costume_ids": len(costume_totals),
        "note": "fresh_costume != 0 means a non-default costume; the integer is the COSTUME enum id from PoGo. No human-readable name map was found in the project; IDs left numeric.",
    },
    "top_costumes_by_count": [
        {"costume_id": c, "count": n} for c, n in top_costumes
    ],
    "summary_by_species": summary_by_species,
    "hundo_costumes": hundo_costumes,
    "duplicates": duplicates,
    "tree": out_tree,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

# Print stdout summary
print(f"total costumed in_bag: {total}")
print(f"distinct species: {len(species_totals)}")
print(f"distinct costume IDs: {len(costume_totals)}")
print(f"hundos: {len(hundo_costumes)}")
print(f"duplicate (species,costume) buckets: {len(duplicates)}")
print(f"total transferable dupes (extras beyond best of each bucket): {sum(len(d['transfer_candidates']) for d in duplicates)}")
print("Top 10 costume IDs:", top_costumes[:10])
print(f"wrote {OUT}")
