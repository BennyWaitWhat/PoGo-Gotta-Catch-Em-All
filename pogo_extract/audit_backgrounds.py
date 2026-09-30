"""Audit Background/Location Card pokemon and emit agent_outputs/background_audit.json."""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).parent / "pokemon.db"
OUT = Path(__file__).parent / "agent_outputs" / "background_audit.json"
OUT.parent.mkdir(exist_ok=True)

con = sqlite3.connect(str(DB))
con.row_factory = sqlite3.Row
cur = con.cursor()

# 1. Totals across candidate columns
totals = {}
for label, sql in [
    ("fresh_has_location_card_1_in_bag", "SELECT COUNT(*) FROM pokemon WHERE fresh_has_location_card=1 AND in_bag=1"),
    ("fresh_has_location_card_1_all", "SELECT COUNT(*) FROM pokemon WHERE fresh_has_location_card=1"),
    ("loc_LocationCard_notnull_in_bag", "SELECT COUNT(*) FROM pokemon WHERE loc_LocationCard IS NOT NULL AND in_bag=1"),
    ("loc_LocationCard_notnull_all", "SELECT COUNT(*) FROM pokemon WHERE loc_LocationCard IS NOT NULL"),
    ("location_bg_id_nonzero_in_bag", "SELECT COUNT(*) FROM pokemon WHERE location_bg_id IS NOT NULL AND location_bg_id!=0 AND in_bag=1"),
    ("location_bg_id_nonzero_all", "SELECT COUNT(*) FROM pokemon WHERE location_bg_id IS NOT NULL AND location_bg_id!=0"),
    ("fresh_loc_card_enum_gt0_in_bag", "SELECT COUNT(*) FROM pokemon WHERE fresh_loc_card_enum > 0 AND in_bag=1"),
]:
    totals[label] = cur.execute(sql).fetchone()[0]

# 2. Per-background-id counts (in_bag)
cur.execute("""
    SELECT loc_LocationCard AS card_id, COUNT(*) AS cnt
    FROM pokemon
    WHERE in_bag=1 AND loc_LocationCard IS NOT NULL
    GROUP BY loc_LocationCard
    ORDER BY cnt DESC, card_id
""")
per_card = [{"card_id": r["card_id"], "count": r["cnt"]} for r in cur.fetchall()]

# 3. Distinct backgrounds collected
distinct_cards = len(per_card)
distinct_card_ids = sorted({c["card_id"] for c in per_card})

# 4. Multi-of-same-background pokemon
multi = [c for c in per_card if c["count"] > 1]
single = [c for c in per_card if c["count"] == 1]

# Per-card sample species
cur.execute("""
    SELECT loc_LocationCard, species_name, nickname, captured_cell_hex, creation_date, lat, lon
    FROM pokemon
    WHERE in_bag=1 AND loc_LocationCard IS NOT NULL
    ORDER BY loc_LocationCard, creation_date
""")
samples = defaultdict(list)
for r in cur.fetchall():
    samples[r["loc_LocationCard"]].append({
        "species": r["species_name"],
        "nickname": r["nickname"] or "",
        "cell": r["captured_cell_hex"],
        "date": (r["creation_date"] or "")[:10],
        "lat": r["lat"],
        "lon": r["lon"],
    })

# Pokemon flagged has_card=1 but loc_LocationCard NULL (likely stripped/glitch)
cur.execute("""
    SELECT uid_hex, species_name, nickname, in_bag, location_bg_id
    FROM pokemon
    WHERE fresh_has_location_card=1 AND loc_LocationCard IS NULL
""")
flag_no_id = [dict(r) for r in cur.fetchall()]

# Non-bag pokemon with card
cur.execute("""
    SELECT uid_hex, species_name, nickname, loc_LocationCard, in_bag
    FROM pokemon
    WHERE loc_LocationCard IS NOT NULL AND (in_bag=0 OR in_bag IS NULL)
""")
non_bag = [dict(r) for r in cur.fetchall()]

# Per-card representative entries (first 3 per card)
per_card_detail = []
for c in per_card:
    cid = c["card_id"]
    s = samples[cid]
    species_counts = defaultdict(int)
    for p in s:
        species_counts[p["species"]] += 1
    date_min = min(p["date"] for p in s if p["date"])
    date_max = max(p["date"] for p in s if p["date"])
    per_card_detail.append({
        "card_id": cid,
        "count": c["count"],
        "species_breakdown": dict(sorted(species_counts.items(), key=lambda kv: -kv[1])),
        "date_first": date_min,
        "date_last": date_max,
        "examples": s[:5],
    })

result = {
    "scope": "in_bag=1 unless noted",
    "totals": totals,
    "summary": {
        "pokemon_with_card_in_bag": totals["loc_LocationCard_notnull_in_bag"],
        "pokemon_with_card_all": totals["loc_LocationCard_notnull_all"],
        "distinct_card_ids_collected": distinct_cards,
        "distinct_card_ids": distinct_card_ids,
        "cards_with_multiple_pokemon": len(multi),
        "cards_with_one_pokemon": len(single),
        "flagged_no_id_count": len(flag_no_id),
        "non_bag_with_card_count": len(non_bag),
    },
    "per_card_counts": per_card,
    "per_card_detail": per_card_detail,
    "multi_pokemon_cards": multi,
    "single_pokemon_cards": single,
    "flagged_has_card_but_null_id": flag_no_id,
    "non_bag_with_card": non_bag,
}

OUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
print(f"Wrote {OUT}")
print(f"in_bag with card (loc_LocationCard): {totals['loc_LocationCard_notnull_in_bag']}")
print(f"in_bag fresh_has_location_card=1   : {totals['fresh_has_location_card_1_in_bag']}")
print(f"distinct cards collected           : {distinct_cards}")
print(f"cards with multiple pokemon        : {len(multi)}")
print(f"cards with one pokemon             : {len(single)}")
con.close()
