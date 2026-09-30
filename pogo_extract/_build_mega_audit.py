import sqlite3, json, os
from collections import defaultdict

DB = os.path.join(os.path.dirname(__file__), "pokemon.db")
OUT = os.path.join(os.path.dirname(__file__), "agent_outputs", "mega_audit.json")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# Mega meta — PoGo thresholds (confirmed by data):
# mega_Level: 1 = 8h cooldown, 100% energy cost (1+ evolutions done)
# mega_Level: 2 = 4h cooldown, ~50% energy cost (7+ evolutions)
# mega_Level: 3 = no cooldown, ~25% energy cost (30+ evolutions)
TIER_THRESHOLDS = {1: 1, 2: 7, 3: 30}

# ---------- 1) MEGA LEVEL HOLDERS BY SPECIES ----------
holders = cur.execute("""
  SELECT species_name, form,
         COUNT(*) AS n_with_mega_level,
         MAX(mega_Level) AS max_mega_level,
         MAX(mega_Points) AS max_mega_points,
         MAX(iv_pct) AS best_iv_pct,
         MAX(cp) AS best_cp,
         AVG(iv_pct) AS avg_iv_pct,
         SUM(CASE WHEN fresh_current_temp_evolution != 0 THEN 1 ELSE 0 END) AS currently_evolved
    FROM pokemon
   WHERE in_bag=1 AND fresh_has_mega_level=1
   GROUP BY species_name, form
   ORDER BY max_mega_level DESC, max_mega_points DESC, species_name
""").fetchall()

mega_level_holders = [dict(r) for r in holders]

# ---------- 2) CURRENTLY MEGA-EVOLVED ----------
evolved = cur.execute("""
  SELECT uid_hex, species_name, form, fresh_current_temp_evolution AS evo_variant,
         level, cp, mega_cp, mega_cpm, mega_extra_cpm,
         iv_pct, iv_atk, iv_def, iv_sta, is_shiny,
         mega_Level, mega_Points
    FROM pokemon
   WHERE in_bag=1 AND fresh_current_temp_evolution != 0
   ORDER BY cp DESC
""").fetchall()
currently_evolved = [dict(r) for r in evolved]

# ---------- 3) MEGA ENERGY EFFICIENCY ----------
# mega_evo_state is misnamed in the schema — for non-mega rows the values 1/2 mark
# evolutionary stage (Pancham, Chimchar etc.) and have nothing to do with mega energy.
# Real mega energy/discount tier lives in mega_Level (1/2/3).
# Document the misnomer + report mega_Level efficiency tiers.
tier_rows = cur.execute("""
  SELECT mega_Level,
         COUNT(*) AS pokemon_with_tier,
         MIN(mega_Points) AS min_lifetime_evos,
         MAX(mega_Points) AS max_lifetime_evos,
         AVG(mega_Points) AS avg_lifetime_evos
    FROM pokemon
   WHERE in_bag=1 AND mega_Level IS NOT NULL
   GROUP BY mega_Level
   ORDER BY mega_Level
""").fetchall()

tier_meaning = {
    1: {"cooldown_hours": 8, "energy_discount_pct": 0,
        "evolutions_done_range": "1-6 (need >=7 to reach Tier 2)"},
    2: {"cooldown_hours": 4, "energy_discount_pct": 50,
        "evolutions_done_range": "7-29 (need >=30 to reach Tier 3)"},
    3: {"cooldown_hours": 0, "energy_discount_pct": 75,
        "evolutions_done_range": "30+"}
}

efficiency_tiers = []
for r in tier_rows:
    lvl = r["mega_Level"]
    efficiency_tiers.append({
        "mega_Level": lvl,
        "pokemon_count": r["pokemon_with_tier"],
        "min_lifetime_evos": r["min_lifetime_evos"],
        "max_lifetime_evos": r["max_lifetime_evos"],
        "avg_lifetime_evos": round(r["avg_lifetime_evos"] or 0, 2),
        "tier_effect": tier_meaning.get(lvl, {})
    })

# Untapped: can_mega_evolve=1 but no mega_Level yet
untapped = cur.execute("""
  SELECT species_name, form,
         COUNT(*) AS n_eligible,
         MAX(iv_pct) AS best_iv,
         MAX(cp) AS best_cp,
         SUM(CASE WHEN iv_pct=100 THEN 1 ELSE 0 END) AS n_hundo,
         SUM(CASE WHEN is_shiny=1 THEN 1 ELSE 0 END) AS n_shiny
    FROM pokemon
   WHERE in_bag=1 AND can_mega_evolve=1
     AND (fresh_has_mega_level=0 OR fresh_has_mega_level IS NULL)
   GROUP BY species_name, form
   ORDER BY n_eligible DESC
""").fetchall()
untapped_species = [dict(r) for r in untapped]

# 'mega_evo_state' misnomer cross-tab — keep visible so reader understands why
# we did NOT use this column for efficiency.
misnomer_rows = cur.execute("""
  SELECT mega_evo_state, fresh_has_mega_level,
         COUNT(*) AS n,
         GROUP_CONCAT(DISTINCT species_name) AS sample_species
    FROM pokemon
   WHERE in_bag=1 AND mega_evo_state IS NOT NULL AND mega_evo_state != 0
   GROUP BY mega_evo_state, fresh_has_mega_level
   ORDER BY mega_evo_state, fresh_has_mega_level
""").fetchall()
mega_evo_state_misnomer = [dict(r) for r in misnomer_rows]

# ---------- 4) BEST MEGA CANDIDATE PER SPECIES ----------
# "Best" = highest iv_pct, tiebreaker cp desc, tiebreaker level desc.
best_rows = cur.execute("""
  WITH ranked AS (
    SELECT p.*,
           ROW_NUMBER() OVER (
             PARTITION BY species_name, form
             ORDER BY iv_pct DESC, cp DESC, level DESC
           ) AS rn
      FROM pokemon p
     WHERE in_bag=1 AND fresh_has_mega_level=1
  )
  SELECT uid_hex, species_name, form, mega_Level, mega_Points,
         iv_pct, iv_atk, iv_def, iv_sta, is_hundo, is_shiny,
         cp, mega_cp, level, fresh_current_temp_evolution,
         nickname
    FROM ranked
   WHERE rn = 1
   ORDER BY iv_pct DESC, cp DESC
""").fetchall()
best_candidates = [dict(r) for r in best_rows]

# ---------- RECOMMENDATIONS ----------
# Prioritize species that:
#  (a) are currently at Tier 1 (low) with a high-IV best candidate -> walk + evolve for cheap tier-up
#  (b) are at Tier 2 close to Tier 3 (mega_Points 20-29) -> a few more evos unlocks free cooldown
#  (c) currently 0 mega_Level on strong species (Mewtwo, Rayquaza, etc.) with elite IV -> start now
priority_climb_to_t2 = []
priority_climb_to_t3 = []
priority_start = []

# Group best_candidates by tier to drive recommendations
for c in best_candidates:
    lvl = c["mega_Level"]
    pts = c["mega_Points"]
    if lvl == 1 and (c["iv_pct"] or 0) >= 90:
        # 6 - pts evolutions away from T2
        remaining = max(0, TIER_THRESHOLDS[2] - (pts or 0))
        priority_climb_to_t2.append({
            "species": c["species_name"], "form": c["form"],
            "uid_hex": c["uid_hex"], "iv_pct": c["iv_pct"], "cp": c["cp"],
            "mega_Points": pts, "evos_to_T2": remaining
        })
    if lvl == 2 and (pts or 0) >= 20:
        remaining = max(0, TIER_THRESHOLDS[3] - (pts or 0))
        priority_climb_to_t3.append({
            "species": c["species_name"], "form": c["form"],
            "uid_hex": c["uid_hex"], "iv_pct": c["iv_pct"], "cp": c["cp"],
            "mega_Points": pts, "evos_to_T3": remaining
        })

# strong untapped — large pools of high-IV pokemon that have never mega-evolved
strong_untapped = [
    u for u in untapped_species
    if (u["best_iv"] or 0) >= 95 and u["n_eligible"] >= 3
]

# Top 10 IV mega-level holders never currently evolved (good targets for next evolution)
ready_high_iv = cur.execute("""
  SELECT uid_hex, species_name, form, iv_pct, cp, mega_Level, mega_Points,
         (CASE WHEN mega_Level=1 THEN 7 - COALESCE(mega_Points,0)
               WHEN mega_Level=2 THEN 30 - COALESCE(mega_Points,0)
               ELSE 0 END) AS evos_to_next_tier
    FROM pokemon
   WHERE in_bag=1 AND fresh_has_mega_level=1
     AND (fresh_current_temp_evolution = 0 OR fresh_current_temp_evolution IS NULL)
     AND iv_pct >= 95
   ORDER BY iv_pct DESC, cp DESC LIMIT 20
""").fetchall()
ready_high_iv = [dict(r) for r in ready_high_iv]

# Edge case: fresh_has_mega_level=1 but mega_Level NULL (3 rows seen)
edge_cases = cur.execute("""
  SELECT uid_hex, species_name, form, iv_pct, cp,
         mega_Level, mega_Points, fresh_current_temp_evolution
    FROM pokemon
   WHERE in_bag=1 AND fresh_has_mega_level=1 AND mega_Level IS NULL
""").fetchall()
edge_cases = [dict(r) for r in edge_cases]

# ---------- ASSEMBLE ----------
totals = cur.execute("""
  SELECT
    SUM(CASE WHEN fresh_has_mega_level=1 THEN 1 ELSE 0 END) AS with_mega_level,
    SUM(CASE WHEN can_mega_evolve=1 THEN 1 ELSE 0 END) AS can_mega_evolve,
    SUM(CASE WHEN fresh_current_temp_evolution != 0 THEN 1 ELSE 0 END) AS currently_evolved,
    SUM(CASE WHEN has_mega_evolution_level=1 THEN 1 ELSE 0 END) AS has_mega_evolution_level_flag,
    SUM(CASE WHEN mega_Level=3 THEN 1 ELSE 0 END) AS at_T3,
    SUM(CASE WHEN mega_Level=2 THEN 1 ELSE 0 END) AS at_T2,
    SUM(CASE WHEN mega_Level=1 THEN 1 ELSE 0 END) AS at_T1
    FROM pokemon WHERE in_bag=1
""").fetchone()

recommendations = {
    "priority_climb_to_T2": sorted(priority_climb_to_t2, key=lambda x: (x["evos_to_T2"], -x["iv_pct"]))[:20],
    "priority_climb_to_T3": sorted(priority_climb_to_t3, key=lambda x: (x["evos_to_T3"], -x["iv_pct"]))[:20],
    "strong_untapped_species": strong_untapped[:20],
    "ready_high_iv_holders_not_currently_evolved": ready_high_iv,
    "notes": [
        "PoGo Mega Level thresholds (confirmed by mega_Points distribution): T1>=1, T2>=7, T3>=30 mega evolutions performed.",
        "T2 cuts cooldown from 8h to 4h and energy cost ~50%. T3 removes cooldown entirely.",
        "Use mega_Points (lifetime mega-evo count) as the energy-efficiency proxy, NOT mega_evo_state.",
        "mega_evo_state column is misnamed: nonzero values 1/2 on rows like Pancham/Chimchar reflect base-evolution stage, not mega progress.",
        "fresh_current_temp_evolution variants: 1=standard mega, 2=Mega X (Charizard X), 3=Mega Y (Charizard Y), 4=Primal (Kyogre/Groudon).",
        "3 pokemon (Charizard 178, Glalie 0, Glalie 929) have fresh_has_mega_level=1 but null mega_Level — most likely first-time mega in progress.",
    ]
}

out = {
    "summary": dict(totals),
    "tier_efficiency": efficiency_tiers,
    "mega_level_holders_by_species": mega_level_holders,
    "currently_evolved": currently_evolved,
    "best_candidate_per_species": best_candidates,
    "untapped_species_no_mega_level_yet": untapped_species,
    "edge_cases_mega_level_null": edge_cases,
    "mega_evo_state_misnomer_evidence": mega_evo_state_misnomer,
    "recommendations": recommendations,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, default=str)

print(f"Wrote {OUT}")
print(f"Holders: {len(mega_level_holders)} species/form rows")
print(f"Currently evolved: {len(currently_evolved)}")
print(f"Best candidates: {len(best_candidates)}")
print(f"Untapped species: {len(untapped_species)}")
print(f"Edge cases (null mega_Level): {len(edge_cases)}")
