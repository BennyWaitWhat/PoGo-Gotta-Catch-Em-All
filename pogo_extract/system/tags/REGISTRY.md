# Tag Registry

**Live registry (2026-09-09): `python granular_tags.py --audit` -- 30 managed tags (6 legacy + 24 vocabulary-only), 5 exempt (Evolve Shiny, Armored ML/UL/Trade/Release), 22 retired (see `granular_tags.RETIRED_TAGS`; 7 of them were redundant with the in-game filter chips, whose counts match the DB exactly). `registry.json` is regenerated from it. Everything below this line is the 2026-05-28 scheme, kept as history.**

---

# Tag Registry (16 tags) — renamed 2026-05-28

Source of truth: registry.json. Scheme: number-prefix groups: 1=PvP 2=Raid 3=Keep 4=Collection 5=Origin 6=Sort. Name limit 15 chars. Rename via EditTag (in-place, members preserved).

| Tag | was | Color | Rule | Count |
|-----|-----|:---:|------|:---:|
| **1 0-15-15** | 0-15-15 | 3 | iv_atk=0 AND iv_def=15 AND iv_sta=15 | 16 |
| **1 GL IV** | GL | 1 | gl_rank=1 | 143 |
| **1 GL Meta** | GL Top 10 | 1 | Best owned specimen (lowest meta-species rank from gl_chain_ | 10 |
| **1 UL IV** | UL | 2 | ul_rank=1 | 307 |
| **1 UL Meta** | UL Top 10 | 2 | Best owned specimen for each PVPoke UL overall top-10 specie | 9 |
| **2 Mega** | Mega | 6 | best (highest CP) specimen per species where can_mega_evolve | 84 |
| **3 Best Buddy** | Best Buddy | 1 | was_best_buddy_badge=1 | 17 |
| **3 Legacy Moves** | Legacy | 3 | legacy_accurate.json (legacy movesets) INTERSECT in_bag=1 | 253 |
| **4 Costume** | Costume | 4 | fresh_costume!=0 | 181 |
| **4 Hundo** | Hundos | 1 | iv_total=45 | 575 |
| **4 Nundo** | Nundos | 2 | is_zero=1 AND pokemon_id!=0 | 27 |
| **4 XXL** | JUMBO | 5 | top-2 XXL (pokemon_size_category=5) per (pokemon_id,form) by | 124 |
| **5 Ethan** | From Ethan | 7 | (is_traded=1 OR is_traded_flag_v2=1 OR is_lucky=1) AND lower | 19 |
| **5 Florandez** | From Florandez | 8 | (is_traded=1 OR is_traded_flag_v2=1 OR is_lucky=1) AND lower | 4 |
| **6 Reserve** | Reserve | 3 | top-3 by CP per (pokemon_id,form) among specimens NOT in any | 1526 |
| **6 Trade** | Trade | 1 | (not in any keep-bucket = fodder) UNION (free-trade-evolutio | 68 |

## Nuked 2026-05-28
Native-duplicates: Shiny, Shadow, Purified, Lucky, Legendary, Mythical, Hatched, Traded, Dynamax, Gigantamax, Adventure Eff, Background, XXS.

Restored after collateral mass-delete: Mega, Costume, 3 Legacy Moves.