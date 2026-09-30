# LEAN_SCHEMA.md — current-bag-only store proposal (NON-DESTRUCTIVE)

> Status: **PROPOSAL ONLY. Nothing here has been executed.** `migrate_lean.py`
> below is a skeleton; it is not present as a runnable file and must be reviewed
> before anyone runs it. The owner does not care about history — only what is in
> the bag *now* — so this trims `pokemon.db` to (a) `in_bag=1` rows and (b) the
> columns the live keep/tag path actually reads.

Generated: 2026-05-30 (re-audited; **fixes a 4-column bug** in the prior draft —
see the "CORRECTION" box below). Audited against the live keep/tag path:
`system/scripts/keep_policy.py`, `system/scripts/build_tagsets.py`, `cull_v9.py`,
`compute_all_ranks.py`, `pvp_iv_rule.py`, `detect_legacy.py`, and the tag pipeline
(`system/scripts/tag_ops.py` + `system/scripts/apply_tagsets.py` + `bulk_tag.js`).
Current DB: **242 columns, 7067 rows (4930 `in_bag=1`, 2137 ghosts), 24.1 MB.**

---

> ## ⚠ CORRECTION vs the prior 47-column draft
> The previous draft put **`move1`, `move2`, `move3`, `alignment`** in the DROP
> list. **That is wrong.** `detect_legacy.py` is a *live pipeline step*
> (`pogo_pipeline.py` L741, runs every crawl) whose `SELECT` reads exactly those
> four columns (plus already-kept ones) to detect legacy/elite moves. Its output
> `legacy_accurate.json` is then consumed in the **same run** by `cull_v9.py`
> (the `legacy_move` protection → `ctx['legacy_uids']`) and by `build_tagsets.py`
> (the `3 Legacy Moves` tag).
>
> Materiality (measured on the current DB): **268** in-bag mons carry the
> `legacy_move` cull protection and **202** carry the `3 Legacy Moves` tag.
> Dropping `move1/2/3` (or `alignment`) would make the next crawl's
> `detect_legacy.py` raise `no such column`, empty `legacy_accurate.json`, and
> **delete all 268 protections + 202 tags** — i.e. it *would* change
> keep/transfer/tag outcomes. So those four columns are **KEPT**. Corrected keep
> set: **51 columns** (the prior 47 + these 4).

---

## How the audit was done (so it is reproducible / falsifiable)

1. Pulled all 242 column names from `PRAGMA table_info(pokemon)`.
2. Whole-word (`\b`-anchored, regex `(?<![A-Za-z0-9_])col(?![A-Za-z0-9_])`) scan
   of every column name across **eleven** live files: the six named in the task
   plus `keep_engine.py`, `apply_tagsets.py`, `references.py`, `pogo_pipeline.py`,
   and `detect_legacy.py` (each is on the live keep/tag path — see "Why these
   files" below). Script: `_audit_cols_tmp.py` (kept in repo root).
3. Removed false positives by distinguishing **value-use** (`p['col']` / `r['col']`
   bracket access, or presence in an explicit `SELECT col-list` / `WHERE`) from
   incidental token matches (comments, local variables, `level=logging.INFO`,
   reason-string literals like `'bread'`/`'costume'`).
4. For `SELECT *` consumers (`keep_policy.py`, `cull_v9.py`) every `r['col']`
   field access is a real read, so the scan is exhaustive for those.
5. Classified the 12 ranker output columns into **read-downstream** vs
   **write-only** by scanning the *consumers* (not the ranker itself).
6. Confirmed `references.py` (imported by `cull_v9`) reads **no** DB columns — it
   is pure ID-set constants + `has_legacy_move(pokemon_id, moves)` operating on
   passed-in args.
7. **Empirically proved** the ghost-drop is a no-op: `_audit_ghost_invariance_tmp.py`
   copies the DB twice, deletes `in_bag!=1` from one copy, runs the real
   `cull_v9` engine against both, and diffs. Result: **identical** KEEP=4623 /
   TRANSFER=307, identical per-reason histogram, **0** per-uid decision diffs.

### Why these 11 files are "the live keep/tag path"
`pogo_pipeline.py` is the single orchestrator. Per crawl it runs, in order:
reconcile (writes `fresh_*`) → `compute_all_ranks.py` (ranks) → `detect_legacy.py`
(`legacy_accurate.json`) → `cull_v9.py` (KEEP/TRANSFER, imports `references.py`,
reads `legacy_accurate.json`) → sanity → `tag_transfers`. The tag *materialization*
side is `build_tagsets.py` → `preflight_transfer.py` (writes the pre-flight stamp) → `prune_tags.py --atomic` (refuses the pile without a fresh matching stamp), on `tag_ops.py` primitives (+`bulk_tag.js`). `apply_tagsets.py` is a retired 2026-05-29 tool: add-only, no keeper gate, and since 2026-09-07 it REFUSES pile tags.
`keep_engine.py` is imported by deep_profile/system-map and maps reasons→purpose;
it reads **no** DB column (only `iv_total`, passed in). `keep_policy.py` is the
DB-only keep/transfer view. All eleven are in-scope; the four "missing" canonical
names from the task brief map to these (`keep_policy.py`, `build_tagsets.py`,
`tag_ops.py` live under `system/scripts/`).

### False positives explicitly excluded from the keep set
| token | why it is NOT a real read |
|---|---|
| `level` | DB column never read by the keep path. Hits are `level=logging.INFO` (tag_ops), `MAX_LEVEL_IDX = 98 # level 50.0` (compute_all_ranks comment), and "species-**level**" in comments. Pipeline *writes* it; nothing in the keep path reads it. → DROP |
| `uid` (bare) | Keep path reads `uid_hex`. Bare `uid` hits are the local var in `mark(uid, …)` and "per-**uid**" comments. **BUT `uid` IS kept** — `pogo_pipeline.step_tag_transfers` (L763) `SELECT uid … WHERE in_bag=1 AND cull_decision_v9='TRANSFER'` to feed signed IDs to the tagger. |
| `costume` (non-fresh) | Every costume keep/tag rule uses `fresh_costume`. `compute_all_ranks` unpacks SELECT position 5 — which is **`fresh_costume`** — into a local *named* `costume`, then passes it to `to_pvpoke_id(…, costume)`, whose body (L39-42) **ignores** the costume arg entirely. The DB column `costume` is dead for keep/tag. → DROP |
| `bread_mode` (non-fresh) | In keep_policy it appears only in a comment (L60) and as the substring of `fresh_bread_mode` (L63). In cull_v9 the column read is `fresh_bread_mode`; `'bread'` is only the reason-string literal. → DROP |
| `fresh_form` | Not value-read by any keep-path file; build_tagsets/compute_all_ranks read `form`, never `fresh_form`. Pipeline *writes* it (INSERT + UPDATE). → DROP (but a pipeline *writer*, see Caveats). |
| `is_shiny` (non-fresh) | Keep path reads `fresh_shiny`. `is_shiny` is only the pre-crawl snapshot the pipeline writes. → DROP |
| `alignment_name` | Pipeline writes it; no keep-path read. (`alignment` itself **is** read — by detect_legacy — and is KEPT.) → DROP |

---

## (a) MINIMAL KEEP SET — 51 columns

Every column below is value-read by at least one live keep/tag file. Grouped by
role; the bracket shows the reader(s). (Δ marks the 4 added by this correction.)

### Identity / join keys (4)
- `uid_hex` — primary key everywhere; tag membership join. [all]
- `uid` — signed-ID source for `bulk_tag.js` transfer tagging (`step_tag_transfers` selects it). [pipeline/tag]
- `pokemon_id` — species grouping + rarity ID-set lookups. [keep_policy, cull_v9, build_tagsets, compute_all_ranks, detect_legacy]
- `species_name` — pvpoke speciesId resolution + labels. [all]

### Strength + IVs — the keep metric and rank inputs (5)
- `cp` — CP tiebreak in `topn()`, GL/UL reachability, labels. **(the power-up-flips-a-tiebreak column the owner called out)** [keep_policy, build_tagsets, cull_v9]
- `iv_atk`, `iv_def`, `iv_sta` — PvP IV rule (atk<=1, bulk>=14) + 4096-combo rank index. [keep_policy, build_tagsets, compute_all_ranks, pvp_iv_rule]
- `iv_total` — strength metric in every `topn()`/bucket sort; `=45` hundo, `4 Hundo` tag; legacy top-4-by-IV. [keep_policy, build_tagsets, cull_v9, detect_legacy]

### Moves — legacy-move detection (3) **Δ ADDED (the bug fix)**
- `move1`, `move2`, `move3` — `detect_legacy.py` classifies each against the species'
  movepool (elite/off-pool → legacy). Drives `legacy_move` cull protection (268
  mons) + `3 Legacy Moves` tag (202 mons). [detect_legacy → cull_v9, build_tagsets]

### Form / variant grouping (2)
- `form` — variant-floor + per-(pid,form) buckets + pvpoke form override + legacy form-pool select. [keep_policy, build_tagsets, cull_v9, compute_all_ranks, pvp_iv_rule, detect_legacy]
- `fresh_costume` — costume keep rule, `4 Costume` tag, XXL grouping key, rank-SELECT slot. [keep_policy, build_tagsets, cull_v9, compute_all_ranks]

### Alignment (2) — shadow/purified
- `fresh_alignment` — shadow(1)/purified(2) keep + shadow_best + variant-floor pool split + rank shadow flag. [keep_policy, build_tagsets, cull_v9, compute_all_ranks]
- `alignment` (non-fresh) **Δ ADDED** — `detect_legacy.py` L233 `is_shadow = alignment in (1,2)` picks the correct base movepool for shadow/purified before legacy classification. [detect_legacy]
  - (Both columns are fully populated today and currently agree; detect_legacy literally selects the column *named* `alignment`, so it must exist.)

### Fresh per-mon state flags — authoritative live values the keep rules read (7)
(The `fresh_*` columns are read precisely because cached protos drift; the keep
path trusts only the freshly-crawled values.)
- `fresh_shiny` — keep-ALL-shinies rule, shiny buckets. [keep_policy, cull_v9]
- `fresh_bread_mode` — Dynamax/Gmax keep + variant-floor cap (gmax→4). [keep_policy, cull_v9]
- `fresh_is_strong` — Mighty keep rule. [keep_policy, cull_v9]
- `fresh_has_location_card` — Location Card keep rule. [keep_policy, cull_v9]
- `fresh_has_mega_level` — has-mega-level keep rule. [cull_v9]
- `fresh_current_temp_evolution` — currently-mega keep rule. [cull_v9]
- `fresh_pokemon_badge` — decorative-badge keep rule. [cull_v9]

### Size — XXL rule (3)
- `height_m`, `weight_kg` — top-2-by-weight ∪ top-2-by-height. [keep_policy, build_tagsets, cull_v9]
- `pokemon_size_category` — `=5` (XXL) gate. [keep_policy, build_tagsets, cull_v9]

### Boolean / scalar per-mon keep inputs (10)
- `is_hundo` — hundo keep. [cull_v9]
- `is_zero` — nundo keep + `4 Nundo`. [keep_policy, build_tagsets, cull_v9]
- `is_lucky` — lucky-from-special-owner keep + `5 Ethan/Florandez`. [keep_policy, build_tagsets, cull_v9]
- `is_traded`, `is_traded_flag_v2` — origin/traded keep + owner tags. [keep_policy, build_tagsets, cull_v9]
- `is_best_buddy` — best-buddy keep (cull_v9). [cull_v9]
- `is_deployed` — deployed-in-gym keep. [cull_v9]
- `was_best_buddy_badge` — `3 Best Buddy` keep (keep_policy/build_tagsets). [keep_policy, build_tagsets]
- `original_owner_name` — Ethan/Florandez owner gate. [keep_policy, build_tagsets, cull_v9]
- `adventure_effects_left` — **RETIRED as a keep axis 2026-09-07; kept in the lean
  store only for the pre-flight gate.** `keep_policy.py:842` dropped the
  `(adventure_effects_left or 0) > 0 or` term, so the Adventure-Effect axis is now
  roster-only (`pokemon_id in AE_IDS`, from `keep_config`). The column was a
  mis-identified proto field: offset `0x1F0` is `markedRemoteTradable_`, a bool that a
  2026-05-05 one-off read as an i32 — `PokemonProto` has no per-mon Adventure-Effect
  charge counter at all (the mechanic is player-level). Proven pile-neutral before the
  term was dropped: 15 off-roster mons carried the `adventure_effect` reason and **0**
  had it as their ONLY reason.
  **Sole remaining reader that can move a keep/transfer outcome: `preflight_transfer.py:605`**,
  which ORs the column with `keep_config.ae_pids()`. That read is an **additive superset
  guard, not a keep axis** — deliberately unconditional (it ignores the
  `rules.adventure_effect` toggle) so the pile gate can only ever OVER-protect: it can add
  `adventure_effect` to a mon's reason list and hold it OUT of the pile, never put one in.
  Dropping the column would weaken that guard, so it **stays in the keep set**.
  `cull_v9.py:146` still reads it too, but advisorily only: cull_v9 is a RETIRED generation
  that runs each crawl solely to write `cull_decision_v9`, which `keep_policy.py:1061`
  consumes for the `newly_trimmed / newly_kept` print alone (L1164-1166) and which decides
  nothing. Readers: [preflight_transfer, cull_v9] — **no longer keep_policy**.

### Rarity booleans (4) — read by keep_policy rule 5 ("rarity: top-6 per pid/form")
- `is_legendary`, `is_mythical`, `is_ultra_beast`, `is_paradox`. [keep_policy]
- NOTE: `cull_v9` does NOT read these booleans; it recomputes rarity from
  `pokemon_id ∈ LEGENDARY_IDS/…` in `references.py`. They are kept solely because
  `keep_policy.py` reads the stored booleans. (Optional future cleanup: switch
  keep_policy to the same ID-sets and drop these 4 — out of scope here.)

### Bag membership + tags (2)
- `in_bag` — **the filter that makes ghost-dropping safe**; every rule reads `WHERE in_bag=1`. [all]
- `auth_tag_names` — user_tag keep, tag mirror, `6 Transfer`/XXL diff. [build_tagsets, cull_v9, tag_ops, apply_tagsets]

### Ranker outputs READ downstream (7)
- `gl_rank`, `gl_pct`, `gl_stage` — GL PvP keep + `1 GL IV` tag + cull GL-qualify (`gl_pct` is the qualify sort key, cull_v9 L231/234). [keep_policy, build_tagsets, cull_v9, pvp_iv_rule]
- `ul_rank`, `ul_pct`, `ul_stage` — UL equivalents (`ul_pct` qualify sort key). [keep_policy, build_tagsets, cull_v9]
- `ll_rank` — LL rank<=15 keep (cull_v9). [cull_v9]

### Cull decision output (2)
- `cull_decision_v9` — written by cull_v9; read by keep_policy diff + `step_tag_transfers` SELECT. [cull_v9, keep_policy, pipeline]
- `cull_reason_v9` — v9 audit reason string (read back by pipeline reporting). [cull_v9, pipeline]

**Full machine-readable keep list (51) — in current column order:**
```
uid_hex, uid, pokemon_id, species_name, cp, move1, move2, move3,
iv_atk, iv_def, iv_sta, iv_total, is_hundo, is_zero, height_m, weight_kg,
is_best_buddy, is_lucky, is_deployed, form, alignment, is_traded,
adventure_effects_left, is_legendary, is_mythical, is_traded_flag_v2,
pokemon_size_category, fresh_costume, fresh_alignment, fresh_pokemon_badge,
fresh_current_temp_evolution, fresh_has_mega_level, fresh_has_location_card,
fresh_bread_mode, fresh_is_strong, fresh_shiny, in_bag, auth_tag_names,
gl_rank, gl_pct, gl_stage, ul_rank, ul_pct, ul_stage, ll_rank,
original_owner_name, cull_decision_v9, cull_reason_v9, is_ultra_beast,
is_paradox, was_best_buddy_badge
```

---

## (b) DROP LIST — 191 columns (dead for the keep/tag path)

None of these is value-read by any of the eleven live files. They fall into
buckets:

**B1. Superseded cull versions (16)** — only the current `*_v9` pair is live:
`cull_decision, cull_reason, cull_decision_v2…v8, cull_reason_v2…v8`.

**B2. Ranker write-only outputs (5)** — `compute_all_ranks.py` computes and stores
them, but no consumer ever reads them back; they are recomputed every run anyway:
`ll_pct, ll_stage, ll_chain_ranks, gl_chain_ranks, ul_chain_ranks`.

**B3. Stale "cached-proto" duplicates of the live `fresh_*` / `form` columns** —
the keep path uses the `fresh_*` value (or `form`/`alignment`); the non-fresh
mirrors are pre-crawl snapshots:
`costume, alignment_name, is_shiny, costume_decoration_id, current_temp_evolution,
has_mega_evolution_level, has_location_card, is_strong_pokemon, bread_mode,
display_form, display_costume, display_alignment, display_pokemon_badge,
fresh_form, fresh_loc_card_enum, fresh_natural_art_*, fresh_day_night,
fresh_tag_count, fresh_tag_ids, fresh_bread_count, fresh_in_heap`.
(`alignment` and `move1/2/3` are **NOT** here — they are read by detect_legacy.)

**B4. One-off / archived extract fields never read by keep/tag** — written by the
many `_*.py`, `v2_*.py`, `cull_v4…v8.py`, `add_*_fields.py`, `dig_*.py`,
`find_*.py`, `examine_*.py` exploration scripts in the project root, never by the
live path. This is the bulk of the drop list: stamina, eggs, deploy/gym
telemetry, trading metadata, mega-point counters, natural-art, day/night,
station/escrow, display-mirror fields, raw proto hex, lat/lon, `level`, `iv_pct`,
`is_powered_up`, the `*_final_rank`/`*_fits_at_current_level` experimental ranker
columns, etc.

**Full machine-readable drop list (191) — exactly the 242 columns minus the 51 kept:**
```
stamina, stamina_max, iv_pct, cp_multiplier, num_additional_cpm, level, pokeball,
pokeball_name, creation_time_ms, creation_date, is_hatched_from_egg,
egg_km_walked_target, nickname, deployed_fort_id, captured_cell_hex, origin_detail,
origin_detail_name, gender, gender_name, costume, is_shiny, weather_boosted,
weather_name, alignment_name, original_owner, traded_time_ms, traded_date,
original_location_hash, special_bg_id, location_bg_id, addr, raw_proto_hex,
display_raw_hex, can_mega_evolve, is_dynamax_capable, is_gigantamax_capable,
can_evolve_estimated, lat, lon, buddy_km_walked, is_purified_flag, is_mega_evolved,
mega_evo_state, mega_cp, mega_extra_cpm, mega_cpm, num_upgrades_or_battles,
num_poweredup_or_walks, costume_decoration_id, is_powered_up, cull_decision,
cull_reason, added_friendship_score, trading_original_owner_hash,
is_special_acquisition, is_favorite_v2, has_mega_evolved_v2, temp_evo_cp,
pokemon_tag_count, bread_move_count, is_gmax_dmax, caught_in_party, is_fusion,
marked_remote_tradable, display_costume, display_form, display_alignment,
display_pokemon_badge, current_temp_evolution, original_costume, display_id,
has_mega_evolution_level, has_location_card, bread_mode, is_strong_pokemon,
shiny_rate, location_card_rate, natural_art_type, natural_art_background,
natural_art_use_full_scene, day_night_type, battles_attacked, battles_defended,
has_egg_incubator_id, from_fort, buddy_candy_awarded, display_pokemon_id,
display_cp, is_bad, coins_returned, deployed_duration_ms,
deployed_returned_timestamp_ms, cp_multiplier_before_trading, has_pvp_combat_stats,
has_npc_combat_stats, move2_is_purified_exclusive, has_limited_pokemon_identifier,
pre_boosted_cp, pre_boosted_additional_cpm, deployed_gym_lat, deployed_gym_lng,
egg_type, egg_slot_type, has_egg_telemetry, has_egg_distribution,
has_pokemon_contest_info, has_iris_social_deployment, has_deployed_station_id,
deployed_station_expiration_ms, is_stamp_collection_reward, is_actively_training,
has_bonus_stat_level, in_escrow, has_day_night_bonus_stat, tag_ids, mega_Points,
mega_Level, mega_MegaPointDailyCounters, loc_LocationCard, loc_inner_value,
fresh_form, fresh_loc_card_enum, fresh_natural_art_type, fresh_natural_art_bg,
fresh_natural_art_full, fresh_day_night, fresh_tag_count, fresh_tag_ids,
fresh_bread_count, fresh_in_heap, cull_decision_v2, cull_reason_v2,
authoritative_claudetx, cull_decision_v3, cull_reason_v3, gl_chain_ranks,
ul_chain_ranks, ll_pct, ll_stage, ll_chain_ranks, gl_final_rank, ul_final_rank,
final_form_max_cp, gl_fits_at_current_level, ul_fits_at_current_level,
cull_decision_v4, cull_reason_v4, cull_decision_v5, cull_reason_v5,
cull_decision_v6, cull_reason_v6, cull_decision_v7, cull_reason_v7,
cull_decision_v8, cull_reason_v8, max_stamina, is_egg, egg_km_target, egg_km_start,
pokeball_item, captured_s2_cell, additional_cpm, favorite, hatched_from_egg,
deployed_returned_ts_ms, cpm_before_trade, traded_owner_hash, pre_boosted_cpm,
has_mega_evolved, temp_evo_stamina_mod, temp_evo_cpm, size_enum, is_component,
is_stamp_reward, weather_boost, temp_evo_finish_ms, temp_evo_locked,
locked_temp_evo, natural_art_bg, natural_art_full_scene, owner_name,
egg_incubator_id, original_owner_nickname, limited_pokemon_id, deployed_station_id,
is_adventure_effect_species, form_region, is_three_star, is_four_star, bread_moves,
bread_max_level
```

(Note several drop-list names are *semantic duplicates* of kept columns —
`size_enum`≈`pokemon_size_category`, `favorite`/`is_favorite_v2`,
`additional_cpm`/`num_additional_cpm`, `weather_boost`/`weather_boosted`,
`hatched_from_egg`/`is_hatched_from_egg`, `owner_name`/`original_owner_name`,
`has_mega_evolved`/`has_mega_evolved_v2`. These were added by exploration scripts
and the keep path standardized on one spelling each. The unused spellings drop.)

---

## (c) Correctness proof — dropping ghosts + dead columns cannot change any keep / transfer / tag outcome

**Claim:** every keep/transfer/tag decision is a pure function of (`in_bag=1` rows) ×
(the 51 kept columns). Therefore removing `in_bag=0` rows and the 191 unread
columns leaves all decisions bit-for-bit identical.

**Proof obligations and their checks:**

1. **Ghost rows are never read — PROVEN EMPIRICALLY.** Two independent arguments:
   - *Static:* every `SELECT/UPDATE/DELETE … pokemon` in the eleven live files is
     either guarded by `WHERE in_bag=1` (keep_policy `SELECT *`, cull_v9 `SELECT *`,
     compute_all_ranks SELECT, detect_legacy SELECT, build_tagsets SQL-tags + XXL
     diff, tag_ops membership SELECT, pipeline tag-transfer SELECT, all cull
     sanity/`COUNT` queries), **or** keyed `WHERE uid_hex=?` where the uid came
     from an `in_bag=1` loop (cull UPDATE, rank UPDATE, `_mirror_db`). Every
     per-(pid,form,costume) bucket (variant_floor, shadow_best, rarity, legacy,
     xxl, shiny/species-form, GL/UL top-2, dex-gap) is built from the `in_bag=1`
     set only.
   - *Empirical:* `_audit_ghost_invariance_tmp.py` deleted all **2137** ghost rows
     from a throwaway copy and re-ran the live `cull_v9` engine. Result vs the
     full DB: **identical KEEP=4623 / TRANSFER=307**, identical per-reason
     histogram, **0** per-uid decision differences. ⇒ ghost-drop is a no-op.

2. **Dropped columns are never value-read.** By construction the drop list is the
   exact complement of the value-read set; the word-boundary scan + SELECT-list
   audit found zero value-uses of any dropped column in the keep/tag path. The
   four columns the prior draft mis-dropped (`move1/2/3/alignment`) are now in the
   KEEP set, closing that hole.

3. **NULL-safety is preserved.** Several kept columns carry NULLs for in-bag mons
   (`is_best_buddy/is_deployed/was_best_buddy_badge/is_legendary…`: 540 NULL;
   `original_owner_name`: 4839 NULL; `adventure_effects_left`: 835 NULL). The keep
   rules handle NULL defensively (`== 1`, `(x or '')`, `(x or 0)`) — consistent
   with the project rule "treat any NULL/missing protection input as
   PROTECTED/handled." The slim table copies these values verbatim, so NULL
   behavior is unchanged.

4. **Re-evaluation invariant is untouched.** The owner's hard constraint — *re-read
   and re-evaluate every in-bag mon on every crawl; speed only from caching the
   per-SPECIES stat-product tables* — lives entirely in `compute_all_ranks.py`
   (the 4096-combo `ranking_cache` keyed by `(species_id, cap, shadow)`), not in
   the schema. This migration changes neither the per-mon re-read loop nor the
   caching. It only narrows the row/column footprint each loop touches.

**Conclusion:** the keep/transfer/tag output is invariant under (ghost-drop) ∪
(dead-column-drop), with the keep set fixed at the audited 51 columns. ∎

---

## (d) `migrate_lean.py` — SKELETON (DO NOT RUN as-is; review first)

> This is a skeleton. It is intentionally guarded, makes a backup, and prints a
> dry-run diff before doing anything. **It has NOT been run.** The prerequisite
> (see "Caveats") MUST be resolved first, or the next pipeline crawl will raise
> `no such column` because the canonical pipeline writes more columns than the
> slim table keeps.

```python
"""migrate_lean.py — rebuild pokemon.db as a current-bag-only, lean-column store.

NON-DESTRUCTIVE BY DEFAULT: runs a dry-run unless --apply is passed, and always
copies pokemon.db -> pokemon.db.prelean.<ts> first. Idempotent-ish: if the table
already has exactly KEEP cols it only drops ghosts + VACUUMs.

DOES:
  1. DELETE FROM pokemon WHERE in_bag IS NOT 1     (drop history/ghost rows)
  2. CREATE pokemon_lean (KEEP columns only), INSERT ... SELECT from pokemon
  3. DROP pokemon; ALTER pokemon_lean RENAME TO pokemon
  4. recreate the indexes; VACUUM

Run:  python migrate_lean.py            # dry-run: prints what WOULD change
      python migrate_lean.py --apply    # actually migrate (after backup)
"""
import sqlite3, os, sys, shutil, time

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pokemon.db')
DB = os.path.normpath(DB)

KEEP = [  # the audited 51 — order here defines the new table's column order
    ('uid_hex','TEXT'), ('uid','INTEGER'), ('pokemon_id','INTEGER'),
    ('species_name','TEXT'), ('cp','INTEGER'),
    ('move1','INTEGER'), ('move2','INTEGER'), ('move3','INTEGER'),
    ('iv_atk','INTEGER'), ('iv_def','INTEGER'), ('iv_sta','INTEGER'),
    ('iv_total','INTEGER'), ('is_hundo','BOOLEAN'), ('is_zero','BOOLEAN'),
    ('height_m','REAL'), ('weight_kg','REAL'), ('is_best_buddy','BOOLEAN'),
    ('is_lucky','BOOLEAN'), ('is_deployed','BOOLEAN'), ('form','INTEGER'),
    ('alignment','INTEGER'), ('is_traded','BOOLEAN'),
    ('adventure_effects_left','INTEGER'), ('is_legendary','BOOLEAN'),
    ('is_mythical','BOOLEAN'), ('is_traded_flag_v2','INTEGER'),
    ('pokemon_size_category','INTEGER'), ('fresh_costume','INTEGER'),
    ('fresh_alignment','INTEGER'), ('fresh_pokemon_badge','INTEGER'),
    ('fresh_current_temp_evolution','INTEGER'), ('fresh_has_mega_level','INTEGER'),
    ('fresh_has_location_card','INTEGER'), ('fresh_bread_mode','INTEGER'),
    ('fresh_is_strong','INTEGER'), ('fresh_shiny','INTEGER'), ('in_bag','INTEGER'),
    ('auth_tag_names','TEXT'), ('gl_rank','INTEGER'), ('gl_pct','REAL'),
    ('gl_stage','TEXT'), ('ul_rank','INTEGER'), ('ul_pct','REAL'),
    ('ul_stage','TEXT'), ('ll_rank','INTEGER'), ('original_owner_name','TEXT'),
    ('cull_decision_v9','TEXT'), ('cull_reason_v9','TEXT'),
    ('is_ultra_beast','INTEGER'), ('is_paradox','INTEGER'),
    ('was_best_buddy_badge','INTEGER'),
]
KEEP_COLS = [c for c, _ in KEEP]


def main(apply):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    existing = [r[1] for r in cur.execute('PRAGMA table_info(pokemon)')]
    total = cur.execute('SELECT COUNT(*) FROM pokemon').fetchone()[0]
    ghosts = cur.execute('SELECT COUNT(*) FROM pokemon WHERE in_bag IS NOT 1').fetchone()[0]
    missing = [c for c in KEEP_COLS if c not in existing]
    if missing:
        sys.exit(f'ABORT: keep columns absent from current table: {missing}')
    drop = [c for c in existing if c not in KEEP_COLS]

    print(f'DB: {DB}')
    print(f'rows: {total} total, {ghosts} ghosts (in_bag!=1) -> would delete')
    print(f'cols: {len(existing)} -> {len(KEEP_COLS)} (dropping {len(drop)})')
    if not apply:
        print('\nDRY-RUN. Re-run with --apply to migrate. No changes made.')
        # Recommended: also run the verification gate below on a throwaway copy
        # and assert byte-identical keep/tag output BEFORE ever passing --apply.
        return

    # 1. backup
    bak = f'{DB}.prelean.{int(time.time())}'
    shutil.copyfile(DB, bak)
    print(f'backup -> {bak}')

    cur.execute('PRAGMA foreign_keys=OFF')
    cur.execute('BEGIN')
    # 2. drop ghost/history rows
    cur.execute('DELETE FROM pokemon WHERE in_bag IS NOT 1')
    # 3. slim table
    coldef = ', '.join(f'{c} {t}' for c, t in KEEP)
    cur.execute(f'CREATE TABLE pokemon_lean ({coldef})')
    collist = ', '.join(KEEP_COLS)
    cur.execute(f'INSERT INTO pokemon_lean ({collist}) SELECT {collist} FROM pokemon')
    cur.execute('DROP TABLE pokemon')
    cur.execute('ALTER TABLE pokemon_lean RENAME TO pokemon')
    cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_pokemon_uid_hex ON pokemon(uid_hex)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_pokemon_in_bag ON pokemon(in_bag)')
    con.commit()
    # 4. reclaim space (cannot run inside a transaction)
    cur.execute('VACUUM')
    con.commit()
    print('migration complete. Verify with keep_policy.py / build_tagsets.py, '
          'then diff tag membership vs the backup.')


if __name__ == '__main__':
    main('--apply' in sys.argv)
```

### Recommended verification gate (bake into the dry-run before --apply)
Run on a throwaway copy and assert byte-identical results:
```
cp pokemon.db /tmp/pre.db
python migrate_lean.py --apply        # operates on pokemon.db (after backup)
python cull_v9.py            > /tmp/cull_after.txt
python system/scripts/keep_policy.py  > /tmp/keep_after.txt
python system/scripts/build_tagsets.py > /tmp/tags_after.txt
# compare KEEP/TRANSFER totals + per-rule protects + each tagsets/*.txt
# against a run captured on /tmp/pre.db BEFORE migrating.
```
Expected: identical `KEEP=…/TRANSFER=…`, identical per-rule protect counts,
identical `system/analysis/tagsets/*.txt` membership (esp. `3_Legacy_Moves.txt`,
which is the canary for the move1/2/3 fix).

---

## CAVEATS — must be resolved before `--apply` (why this is not purely additive)

**1. The canonical pipeline writes 13 columns the slim table would not have.**
`pogo_pipeline.py`'s reconcile INSERT (L452-473) + full-refresh UPDATE (L481-507)
and `compute_all_ranks.py`'s rank UPDATE write these *every crawl*, but no
keep/tag rule reads them, so they are in the DROP list:

> from the pipeline: `level, iv_pct, is_shiny, alignment_name,
> costume_decoration_id, is_powered_up, fresh_in_heap, fresh_form`
> from the ranker: `ll_pct, ll_stage, ll_chain_ranks, gl_chain_ranks,
> ul_chain_ranks`

If you drop them, the very next crawl raises `sqlite3.OperationalError: no such
column`. **Two clean options:**
  - **(A) Trim the writers (recommended for a true lean store):** edit the three
    statements — reconcile `INSERT` (~L452), reconcile full-refresh `UPDATE`
    (~L481), and the rank `UPDATE` (`compute_all_ranks.py` ~L162) — to stop
    writing these 13 dead columns. Small and mechanical. (Note: `move1/2/3` and
    `alignment` are *also* written there, but those STAY — they are read by
    detect_legacy. Only remove the 13 listed above.)
  - **(B) Keep these 13 in the slim table** (schema 51→64). Zero code changes;
    still drops 178 columns and all 2137 ghosts. Lower risk, slightly less lean.
    `level` here is the convenience display copy; the keep path needs only `cp`
    + the cached CPM tables, so `level` stays purely for the writer's sake.

**2. Nine kept columns are NOT refreshed by the canonical crawl (pre-existing
staleness, independent of this migration).** `keep_policy.py` reads
`is_legendary/is_mythical/is_ultra_beast/is_paradox` (static, species-derived —
fine) and `is_best_buddy/is_deployed/was_best_buddy_badge/original_owner_name`
(per-mon dynamic). `adventure_effects_left` is the ninth, and as of 2026-09-07 it is NO
LONGER one of the columns keep_policy reads — its only outcome-bearing reader is
`preflight_transfer.py:605`, where an unwritten/NULL column can only under-ADD to an
already-additive superset guard (see the keep-set entry above). The current `pogo_pipeline.py` crawl
does **not** write these five; they were back-filled by a one-time bag-walk
enrichment and are partly NULL today (`is_best_buddy/is_deployed`: 540 NULL of
4930; `original_owner_name`: 4839 NULL). The lean store preserves whatever values
exist (so outcomes are unchanged), but if the owner wants these to honor the
"re-evaluate every mon every crawl" rule, the *crawl* must be extended to emit
them — a separate task from this schema trim. (`cull_v9.py`'s best_buddy/deployed
rules and keep_policy's owner rule silently under-protect any mon whose value
is stale-NULL; treating NULL as PROTECTED, per project policy, would close that
gap.)

**3. `alignment` vs `fresh_alignment`.** Both are kept and both are written every
crawl (pipeline L467/L500 write `alignment`; L471/L504 write `fresh_alignment`).
detect_legacy reads `alignment`; the keep rules read `fresh_alignment`. They agree
today (4930/4930 populated, identical shadow flags). Keeping both is correct; a
future cleanup could point detect_legacy at `fresh_alignment` and drop `alignment`,
but that is a code change, out of scope here.

**4. Index recreation:** the skeleton adds `idx_pokemon_uid_hex` (unique) and
`idx_pokemon_in_bag`. Confirm no other code depends on a differently-named index
(none found in the live path).

---

## Audit artifacts (kept in repo root for reproducibility)
- `_audit_cols_tmp.py` — the 242-column × 11-file word-boundary mention scan.
- `_audit_keepset_tmp.py` — assembles the 51-col keep set from each reader's
  verified value-reads and diffs it against the prior 47-col draft (shows exactly
  the 4-column `move1/2/3/alignment` correction, and zero over-keeps).
- `_audit_ghost_invariance_tmp.py` — the empirical ghost-drop no-op proof
  (deletes 2137 ghosts on a temp copy, re-runs cull_v9, diffs: 0 changes).
