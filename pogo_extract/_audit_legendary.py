"""Audit legendary/mythical/ultra-beast/paradox pokemon."""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).parent / "pokemon.db"
OUT = Path(__file__).parent / "agent_outputs" / "legendary_mythical_audit.json"

ULTRA_BEASTS = {
    "Nihilego", "Buzzwole", "Pheromosa", "Xurkitree", "Celesteela",
    "Kartana", "Guzzlord", "Naganadel", "Stakataka", "Blacephalon",
    "Poipole",
}

# Paradox pokemon (Scarlet/Violet) - not yet released in PoGo, but included for completeness
PARADOX = {
    "Great Tusk", "Scream Tail", "Brute Bonnet", "Flutter Mane", "Slither Wing",
    "Sandy Shocks", "Roaring Moon", "Walking Wake", "Gouging Fire", "Raging Bolt",
    "Iron Treads", "Iron Bundle", "Iron Hands", "Iron Jugulis", "Iron Moth",
    "Iron Thorns", "Iron Valiant", "Iron Leaves", "Iron Boulder", "Iron Crown",
}

# Full mythical roster for "missing" check (canonical list through Gen 9)
ALL_MYTHICAL = {
    "Mew", "Celebi", "Jirachi", "Deoxys", "Phione", "Manaphy", "Darkrai",
    "Shaymin", "Arceus", "Victini", "Keldeo", "Meloetta", "Genesect",
    "Diancie", "Hoopa", "Volcanion", "Magearna", "Marshadow", "Zeraora",
    "Meltan", "Melmetal", "Zarude",
}

# Canonical legendary roster (PoGo-released)
ALL_LEGENDARY = {
    "Articuno", "Zapdos", "Moltres", "Mewtwo",
    "Raikou", "Entei", "Suicune", "Lugia", "Ho-Oh",
    "Regirock", "Regice", "Registeel", "Latias", "Latios", "Kyogre", "Groudon", "Rayquaza",
    "Uxie", "Mesprit", "Azelf", "Dialga", "Palkia", "Heatran", "Regigigas", "Giratina", "Cresselia",
    "Cobalion", "Terrakion", "Virizion", "Tornadus", "Thundurus", "Reshiram", "Zekrom", "Landorus", "Kyurem",
    "Xerneas", "Yveltal", "Zygarde",
    "Tapu Koko", "Tapu Lele", "Tapu Bulu", "Tapu Fini", "Solgaleo", "Lunala", "Necrozma",
    "Zacian", "Zamazenta", "Eternatus", "Kubfu", "Urshifu", "Regieleki", "Regidrago", "Glastrier", "Spectrier", "Calyrex", "Enamorus",
}

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT species_name, is_legendary, is_mythical, is_hundo, is_shiny, is_lucky,
               alignment, alignment_name, iv_pct, cp, level, nickname
        FROM pokemon
        WHERE in_bag=1
    """)
    rows = cur.fetchall()

    # Classify
    by_category = {
        "legendary": defaultdict(list),
        "mythical": defaultdict(list),
        "ultra_beast": defaultdict(list),
        "paradox": defaultdict(list),
    }

    for r in rows:
        species = r["species_name"]
        if species in ULTRA_BEASTS:
            cat = "ultra_beast"
        elif species in PARADOX:
            cat = "paradox"
        elif r["is_mythical"]:
            cat = "mythical"
        elif r["is_legendary"]:
            cat = "legendary"
        else:
            continue
        by_category[cat][species].append(dict(r))

    # Build report
    report = {
        "summary": {},
        "by_category": {},
        "heavy_species": [],
        "missing_dex": {},
        "mass_transfer_candidates": [],
    }

    grand_total = 0
    for cat, species_dict in by_category.items():
        cat_total = sum(len(v) for v in species_dict.values())
        grand_total += cat_total
        report["summary"][cat] = {
            "total_pokemon": cat_total,
            "unique_species": len(species_dict),
        }
        species_breakdown = {}
        for sp, mons in sorted(species_dict.items()):
            hundo = sum(1 for m in mons if m["is_hundo"])
            shiny = sum(1 for m in mons if m["is_shiny"])
            shadow = sum(1 for m in mons if m["alignment"] == 1)
            purified = sum(1 for m in mons if m["alignment"] == 2)
            lucky = sum(1 for m in mons if m["is_lucky"])
            ivs = [m["iv_pct"] for m in mons if m["iv_pct"] is not None]
            avg_iv = round(sum(ivs)/len(ivs), 1) if ivs else None
            max_iv = round(max(ivs), 1) if ivs else None
            high_iv_count = sum(1 for v in ivs if v >= 93.3)  # 93.3% = 14/14/14 or better
            species_breakdown[sp] = {
                "count": len(mons),
                "hundo": hundo,
                "shiny": shiny,
                "shadow": shadow,
                "purified": purified,
                "lucky": lucky,
                "avg_iv_pct": avg_iv,
                "max_iv_pct": max_iv,
                "high_iv_count_93plus": high_iv_count,
            }
            if len(mons) >= 10:
                report["heavy_species"].append({
                    "category": cat,
                    "species": sp,
                    "count": len(mons),
                    "hundo": hundo,
                    "shiny": shiny,
                    "shadow": shadow,
                    "lucky": lucky,
                    "high_iv_93plus": high_iv_count,
                })
        report["by_category"][cat] = species_breakdown

    report["summary"]["grand_total"] = grand_total

    # Missing dex
    owned_legendary = set(report["by_category"]["legendary"].keys())
    owned_mythical = set(report["by_category"]["mythical"].keys())
    owned_ub = set(report["by_category"]["ultra_beast"].keys())
    report["missing_dex"]["legendary"] = sorted(ALL_LEGENDARY - owned_legendary)
    report["missing_dex"]["mythical"] = sorted(ALL_MYTHICAL - owned_mythical)
    report["missing_dex"]["ultra_beast"] = sorted(ULTRA_BEASTS - owned_ub)

    report["heavy_species"].sort(key=lambda x: -x["count"])

    # Mass transfer recommendations
    # Logic: keep best 5-7 per legendary depending on use:
    #   - 1 hundo each (if any), 1 shiny each form, 1 shundo, 1 shadow, 1 shadow shundo
    #   - keep all 93%+ IV (PVP/raid worthy)
    # Recommend transferring mediocre extras of heavy species
    for cat in ("legendary", "mythical", "ultra_beast"):
        for sp, info in report["by_category"][cat].items():
            count = info["count"]
            if count < 8:
                continue
            keepers_estimate = info["hundo"] + info["shiny"] + max(info["shadow"], 0)
            # Floor: protect at least the high-IV pool plus shinies/hundos/shadows
            protected = max(keepers_estimate, info["high_iv_count_93plus"])
            transferable = count - protected
            if transferable >= 5:
                report["mass_transfer_candidates"].append({
                    "category": cat,
                    "species": sp,
                    "total": count,
                    "hundo": info["hundo"],
                    "shiny": info["shiny"],
                    "shadow": info["shadow"],
                    "lucky": info["lucky"],
                    "high_iv_93plus": info["high_iv_count_93plus"],
                    "rough_transferable": transferable,
                    "note": "After protecting hundos, shinies, shadows, and 93%+ IV mons",
                })

    report["mass_transfer_candidates"].sort(key=lambda x: -x["rough_transferable"])

    OUT.write_text(json.dumps(report, indent=2))
    print(f"Wrote {OUT}")
    print(f"Grand total special-class in bag: {grand_total}")
    for cat, s in report["summary"].items():
        if cat == "grand_total":
            continue
        print(f"  {cat}: {s['total_pokemon']} across {s['unique_species']} species")
    print(f"Heavy species (10+): {len(report['heavy_species'])}")
    print(f"Mass-transfer candidates: {len(report['mass_transfer_candidates'])}")
    print(f"Missing legendary: {len(report['missing_dex']['legendary'])}")
    print(f"Missing mythical: {len(report['missing_dex']['mythical'])}")
    print(f"Missing ultra beast: {len(report['missing_dex']['ultra_beast'])}")

if __name__ == "__main__":
    main()
