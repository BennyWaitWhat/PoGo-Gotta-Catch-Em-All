---
name: pogo-xxl-trim-one-off
description: XXL trim = a ONE-OFF cull only when he says (best 1 XXL per species + best 5 per type, showcase points 1,050+) via `full_audit.py --xxl-trim`; everyday rule stays top 2 per species
metadata:
  type: project
---
XXL TRIM (built 2026-09-29). He picked "2, but 1,000", then: "This is a one time thing, that will be done sometimes when i say, not every time."

- Run it ONLY when he asks: `python full_audit.py --xxl-trim`. It sets caps.xxl=1 + caps.xxl_per_type=5 + showcase_weights.min_points=1050 ("Actually make the cut off 1050", same day; everyday min stays 1000) for that run and restores keep_config.json at the end. A killed trim run is undone at the start of the next pass (backup `keep_config.json.pre_xxl_trim`).
- Everyday rule unchanged: top caps.xxl (2) per species+battle form at showcase points >= min_points (1000). Pumpkaboo/Gourgeist override stays 4 (also during a trim).
- Code: `size_line.xxl_keepers` is the ONE selection (engine rule 7, build_tagsets, preflight_transfer, audit_tags_membership, audit_tag_truth, _spotdata). audit_cull re-derives the per-type part independently (pvpoke types vs the game-master types size_line uses). audit_invariants: axis `xxl_per_type` + CAPPING_HELPERS.
- Why per type, read from the game 2026-09-29: ContestSettingsProto PlayerContestMaxEntries 5, DefaultContestMaxEntries 200 (daily 150). Focus kinds: Pokemon / Type / Buddy / Family / Generation / Class / Alignment / Shiny / Hatched / Mega. Metric PokemonSize, biggest wins (Min exists, unused). Web: 2026 Showcase Tuesdays rotate ~4-5 of 18 types + Good/Great Buddy; 5 entries since 2026-06-02 (was 3); species showcases only with events.
- First trim, 2026-09-29 03:40 at 1,000: 49 XXLs piled; redone at 1,050 right after (+~20), all XXL-only keepers (none shiny/hundo/lucky/fav/PvP 1-5); XXL tag 283 -> 225.
- Buddy data: only 20 mons carry the live BEST_BUDDY badge (fresh_pokemon_badge=1); DB is_best_buddy (530) is stale. Good/Great levels are not on PokemonProto.

Related: [[reference-pogo-showcase-score-formula]], [[feedback-number-findings-then-ask]], [[pogo-capped-vs-keepall-bug-class]].
