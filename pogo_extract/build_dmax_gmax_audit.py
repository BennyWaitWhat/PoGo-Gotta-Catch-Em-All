import sqlite3, json, os
from collections import defaultdict

DB = os.path.join(os.path.dirname(__file__), "pokemon.db")
OUT = os.path.join(os.path.dirname(__file__), "agent_outputs", "dmax_gmax_audit.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

MODE_NAME = {1: "Dmax", 2: "Gmax", 4: "MaxForm"}

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("""
SELECT uid_hex, species_name, form, cp, iv_atk, iv_def, iv_sta, iv_total, iv_pct,
       level, is_hundo, is_shiny, nickname, fresh_bread_mode,
       is_dynamax_capable, is_gigantamax_capable, fresh_bread_count
FROM pokemon
WHERE in_bag = 1 AND fresh_bread_mode != 0
""")
rows = [dict(r) for r in cur.fetchall()]

totals = defaultdict(int)
for r in rows:
    totals[r["fresh_bread_mode"]] += 1

per_species = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
species_form_gmax_eligible = defaultdict(lambda: defaultdict(lambda: False))
for r in rows:
    sp, fm, md = r["species_name"], r["form"], r["fresh_bread_mode"]
    per_species[sp][fm][md] += 1
    if r["is_gigantamax_capable"]:
        species_form_gmax_eligible[sp][fm] = True

per_species_out = []
for sp in sorted(per_species.keys()):
    for fm in sorted(per_species[sp].keys()):
        entry = {
            "species": sp,
            "form": fm,
            "dmax": per_species[sp][fm].get(1, 0),
            "gmax": per_species[sp][fm].get(2, 0),
            "max_form": per_species[sp][fm].get(4, 0),
            "gmax_eligible": bool(species_form_gmax_eligible[sp][fm]),
        }
        per_species_out.append(entry)

best_keys = defaultdict(lambda: None)
for r in rows:
    k = (r["species_name"], r["form"], r["fresh_bread_mode"])
    cur_best = best_keys[k]
    if cur_best is None or (r["cp"], r["iv_total"]) > (cur_best["cp"], cur_best["iv_total"]):
        best_keys[k] = r

best_per_species = []
for (sp, fm, md), r in sorted(best_keys.items(), key=lambda x: (-x[0][2], x[0][0], x[0][1])):
    best_per_species.append({
        "species": sp,
        "form": fm,
        "bread_mode": md,
        "bread_mode_name": MODE_NAME.get(md, f"mode_{md}"),
        "uid_hex": r["uid_hex"],
        "cp": r["cp"],
        "iv_total": r["iv_total"],
        "iv_pct": r["iv_pct"],
        "level": r["level"],
        "is_hundo": bool(r["is_hundo"]),
        "is_shiny": bool(r["is_shiny"]),
        "nickname": r["nickname"],
    })

hundos = []
for r in rows:
    if r["is_hundo"]:
        hundos.append({
            "uid_hex": r["uid_hex"],
            "species": r["species_name"],
            "form": r["form"],
            "bread_mode": r["fresh_bread_mode"],
            "bread_mode_name": MODE_NAME.get(r["fresh_bread_mode"], f"mode_{r['fresh_bread_mode']}"),
            "cp": r["cp"],
            "level": r["level"],
            "is_shiny": bool(r["is_shiny"]),
            "nickname": r["nickname"],
        })
hundos.sort(key=lambda x: (-x["bread_mode"], -x["cp"]))

gmax_eligible_species = set()
for r in rows:
    if r["is_gigantamax_capable"]:
        gmax_eligible_species.add((r["species_name"], r["form"]))

gmax_eligible_dmax = []
for sp, fm in sorted(gmax_eligible_species):
    dmax_cnt = per_species[sp][fm].get(1, 0)
    gmax_cnt = per_species[sp][fm].get(2, 0)
    if dmax_cnt > 0 or gmax_cnt > 0:
        gmax_eligible_dmax.append({
            "species": sp,
            "form": fm,
            "dmax_count": dmax_cnt,
            "gmax_count": gmax_cnt,
            "can_evolve_to_gmax": dmax_cnt > 0 and gmax_cnt == 0,
        })

unique_dmax_species = len({(r["species_name"], r["form"]) for r in rows if r["fresh_bread_mode"] == 1})
unique_gmax_species = len({(r["species_name"], r["form"]) for r in rows if r["fresh_bread_mode"] == 2})

output = {
    "generated_at": "2026-05-20",
    "source": "in_bag=1 AND fresh_bread_mode != 0",
    "bread_mode_legend": {
        "0": "Normal (not Max)",
        "1": "Dmax (Dynamax)",
        "2": "Gmax (Gigantamax)",
        "4": "MaxForm (Hero/Crowned/Eternamax)",
    },
    "totals": {
        "all_bread": sum(totals.values()),
        "dmax": totals.get(1, 0),
        "gmax": totals.get(2, 0),
        "max_form": totals.get(4, 0),
        "unique_dmax_species_forms": unique_dmax_species,
        "unique_gmax_species_forms": unique_gmax_species,
    },
    "hundos": hundos,
    "per_species_form": per_species_out,
    "best_per_species_form_mode": best_per_species,
    "gmax_eligible_species": gmax_eligible_dmax,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Wrote {OUT}")
print(f"Totals: Dmax={totals.get(1,0)} Gmax={totals.get(2,0)} MaxForm={totals.get(4,0)}")
print(f"Hundos: {len(hundos)}")
print(f"Gmax-eligible species/forms: {len(gmax_eligible_dmax)}")
