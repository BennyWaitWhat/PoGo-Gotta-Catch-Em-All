import json
import sqlite3
from collections import OrderedDict

DB = "pokemon.db"
OUT = "agent_outputs/buddy_audit.json"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

BB_WHERE = "is_best_buddy=1 AND COALESCE(in_bag,1)=1"

cur.execute(f"SELECT COUNT(*) FROM pokemon WHERE is_best_buddy=1")
total_all = cur.fetchone()[0]
cur.execute(f"SELECT COUNT(*) FROM pokemon WHERE {BB_WHERE}")
total_in_bag = cur.fetchone()[0]

cur.execute(f"""
    SELECT species_name, form, COUNT(*) AS n
    FROM pokemon
    WHERE {BB_WHERE}
    GROUP BY species_name, form
    ORDER BY n DESC, species_name
""")
group_rows = []
for r in cur.fetchall():
    group_rows.append({
        "species_name": r["species_name"],
        "form": r["form"],
        "count": r["n"],
    })

cur.execute(f"""
    SELECT uid_hex, pokemon_id, species_name, form, nickname, cp, level,
           alignment_name, is_shiny, is_lucky, is_legendary, is_mythical,
           buddy_km_walked, num_upgrades_or_battles
    FROM pokemon
    WHERE {BB_WHERE} AND is_hundo=1
    ORDER BY cp DESC
""")
hundos = [dict(r) for r in cur.fetchall()]

cur.execute(f"""
    SELECT uid_hex, pokemon_id, species_name, form, nickname, cp, level,
           alignment_name, is_shiny, is_lucky, is_hundo, is_legendary, is_mythical,
           buddy_km_walked, num_upgrades_or_battles
    FROM pokemon
    WHERE {BB_WHERE} AND alignment_name='SHADOW'
    ORDER BY cp DESC
""")
shadows = [dict(r) for r in cur.fetchall()]

cur.execute(f"""
    SELECT uid_hex, pokemon_id, species_name, form, nickname, cp, level,
           alignment_name, is_shiny, is_lucky, is_hundo, is_legendary, is_mythical,
           buddy_km_walked, num_upgrades_or_battles
    FROM pokemon
    WHERE {BB_WHERE} AND alignment_name='PURIFIED'
    ORDER BY cp DESC
""")
purified = [dict(r) for r in cur.fetchall()]

cur.execute(f"""
    SELECT uid_hex, pokemon_id, species_name, form, nickname, cp, level,
           alignment_name, is_shiny, is_lucky, is_hundo, is_mythical,
           buddy_km_walked, num_upgrades_or_battles
    FROM pokemon
    WHERE {BB_WHERE} AND (is_legendary=1 OR is_mythical=1)
    ORDER BY cp DESC
""")
legendaries = [dict(r) for r in cur.fetchall()]

cur.execute(f"""
    SELECT uid_hex, pokemon_id, species_name, form, nickname, cp, level,
           alignment_name, is_shiny, is_lucky, is_hundo, is_legendary, is_mythical,
           buddy_km_walked, num_upgrades_or_battles
    FROM pokemon
    WHERE {BB_WHERE}
    ORDER BY buddy_km_walked DESC NULLS LAST
    LIMIT 25
""")
most_walked = [dict(r) for r in cur.fetchall()]

cur.execute(f"""
    SELECT uid_hex, pokemon_id, species_name, form, nickname, cp, level,
           alignment_name, is_shiny, is_lucky, is_hundo, is_legendary, is_mythical,
           buddy_km_walked, num_upgrades_or_battles
    FROM pokemon
    WHERE {BB_WHERE}
    ORDER BY num_upgrades_or_battles DESC NULLS LAST
    LIMIT 25
""")
most_powered = [dict(r) for r in cur.fetchall()]

# Core team heuristic: rank BBs by composite signal
# - buddy_km_walked (effort to keep them as buddy/swap)
# - num_upgrades_or_battles (XL investment)
# - cp (relative scaling)
# - is_hundo, is_shiny, is_lucky, is_legendary bonuses
cur.execute(f"""
    SELECT uid_hex, pokemon_id, species_name, form, nickname, cp, level,
           alignment_name, is_shiny, is_lucky, is_hundo, is_legendary, is_mythical,
           buddy_km_walked, num_upgrades_or_battles, iv_pct
    FROM pokemon
    WHERE {BB_WHERE}
""")
all_bb = [dict(r) for r in cur.fetchall()]

max_km = max((p["buddy_km_walked"] or 0) for p in all_bb) or 1
max_pow = max((p["num_upgrades_or_battles"] or 0) for p in all_bb) or 1
max_cp = max((p["cp"] or 0) for p in all_bb) or 1

scored = []
for p in all_bb:
    km = p["buddy_km_walked"] or 0
    pw = p["num_upgrades_or_battles"] or 0
    cp = p["cp"] or 0
    score = (
        0.40 * (km / max_km)
        + 0.35 * (pw / max_pow)
        + 0.15 * (cp / max_cp)
        + (0.05 if p["is_hundo"] else 0)
        + (0.03 if p["is_shiny"] else 0)
        + (0.02 if p["is_lucky"] else 0)
        + (0.02 if p["is_legendary"] or p["is_mythical"] else 0)
    )
    scored.append((score, p))
scored.sort(key=lambda x: x[0], reverse=True)

core_team = []
for score, p in scored[:12]:
    entry = dict(p)
    entry["core_score"] = round(score, 4)
    core_team.append(entry)

result = OrderedDict()
result["meta"] = {
    "db": DB,
    "filter": "is_best_buddy=1 AND in_bag=1 (NULL treated as in_bag)",
    "total_bb_all": total_all,
    "total_bb_in_bag": total_in_bag,
}
result["totals"] = {
    "total_bb_all_records": total_all,
    "total_bb_in_bag": total_in_bag,
}
result["group_by_species_form"] = group_rows
result["hundos"] = {"count": len(hundos), "items": hundos}
result["shadows"] = {"count": len(shadows), "items": shadows}
result["purified"] = {"count": len(purified), "items": purified}
result["legendaries_mythicals"] = {"count": len(legendaries), "items": legendaries}
result["most_walked_top25"] = most_walked
result["most_powered_top25"] = most_powered
result["core_team_top12"] = {
    "scoring": "0.40*km_norm + 0.35*pow_norm + 0.15*cp_norm + hundo/shiny/lucky/legendary bonuses",
    "items": core_team,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"Wrote {OUT}")
print(f"Total BBs (all): {total_all}")
print(f"Total BBs (in_bag): {total_in_bag}")
print(f"Unique species+form: {len(group_rows)}")
print(f"Hundo BBs: {len(hundos)}")
print(f"Shadow BBs: {len(shadows)}")
print(f"Purified BBs: {len(purified)}")
print(f"Legendary/mythical BBs: {len(legendaries)}")
print()
print("Top 5 core team:")
for entry in core_team[:5]:
    print(f"  {entry['species_name']} (CP {entry['cp']}, {entry['buddy_km_walked']}km, {entry['num_upgrades_or_battles']} powerups) score={entry['core_score']}")

conn.close()
