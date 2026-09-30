# Scripts Index

**Verified against the tree on 2026-09-07.** Every script named below was confirmed to exist except
those explicitly marked DELETED or RETIRED.

Every `*.py` and key `*.js` in the repo, classified as:

- **CANONICAL** -- the scripts that matter. Use these.
- **DATA/UTIL** -- data builders, references, safety modules. Not run directly most of the time.
- **SUPERSEDED** -- historical one-offs. Replaced by a canonical tool. Do not use.
- **DELETED** -- gone from the tree. Named here only so an old doc or transcript referencing it
  resolves to what actually replaced it.
- **RETIRED** -- still present as a tombstone that refuses to run. Do not re-arm.

See [`../RUNBOOK.md`](../RUNBOOK.md) for the operating procedure. This file is the catalog.

## Canonical: the keep/tag cycle

The one-command cycle is `python full_audit.py`. These are the pieces it composes.

| Script | Location | Role |
|--------|----------|------|
| `full_audit.py` | root | **The one command.** Recrawl -> 6 audits in parallel -> hard gate -> sync -> verify. Flags: `--no-sync`, `--skip-crawl`, `--audits-only`. |
| `dashboard.py` | root | Control panel on `127.0.0.1:8765`. Owns `/api/recrawl`, `/api/sync`, `/api/preflight`, `/api/tagdiff`, `/studio`. The single code path the cycle and the buttons share. |
| `keep_policy.py` | system/scripts/ | **Step 1.** Decides KEEP vs pile. Writes `policy_reasons.json` + `6_Transfer.txt`. Has its own two `SystemExit` tripwires (PvP-spread leak, protected leak). |
| `build_tagsets.py` | system/scripts/ | **Step 2.** Turns decisions into `system/analysis/tagsets/*.txt`, including `Transfer.txt`. |
| `preflight_transfer.py` | system/scripts/ | **Step 3, the hard gate.** Independently re-derives every keep axis from the DB, reads gym deployment live off the proto. `rc != 0` aborts before any phone write. Writes the **preflight stamp** so its verdict survives the process; mutates nothing else. |
| `prune_tags.py` | system/scripts/ | **Step 4, the only sanctioned pusher.** Bidirectional push (add AND remove) then re-enumerate and verify set equality. `--atomic`, `--dry-run`, `--force`. Exit 0 only on an exact match for every tag. **Never run it standalone** -- with no tag arguments it targets the WHOLE plan, `Transfer` included; it must be preceded by a passing `preflight_transfer.py` on the same pile. |
| `set_db_tags_from_files.py` | system/scripts/ | **Step 5, runs LAST.** Mirrors the tagset files into `auth_tag_names`. DB-only. Running it before the push makes every sync report "already in sync" -- order corrected 2026-09-02. |
| `refresh_evolve_shiny.py` | system/scripts/ | Produces `Evolve_Shiny.txt`. **Not** in `prune_tags.PLAN` -- nothing else refreshes it. Runs between the push and the mirror. |
| `granular_tags.py` | root | **The tag registry.** `registry()` (46 tags = `LEGACY_TAGS` 11 + the label vocabulary), `EXEMPT_TAGSETS` / `EXEMPT_TAGS`, `build()`, `filename()`, `audit_registry()`. `prune_tags.PLAN` *is* `registry()`, so `build_tagsets` and `prune` can never disagree about a filename. `python granular_tags.py --audit` prints it offline -- no DB, no device. |
| `keep_config.py` | root | Cap/roster accessors over `keep_config.json`. **Always `cap(name)` / `species_cap(axis, pid, default)`, never `DEFAULTS[name]`** -- 5 of 11 caps currently differ. |
| `cpm_table.py` | root | **Single source of truth** for the CPM ladder, `MAX_LEVEL_IDX` and the league CP caps (`GL_CAP`/`UL_CAP`/`LL_CAP`). Import it; never re-hardcode a value from it. Created 2026-09-07 (defect D4: the L50 multiplier existed as two different values across seven copies, two of them regex scrapes of another file's source). |
| `autocull_watch.py` | root | Timer daemon: watches free bag space and runs the gated cull (`full_audit.py`) when it is low. Rewrites `pokemon.db` and the tagsets on its own schedule -- read `system/analysis/autocull_watch.log` before blaming a script for a changed file. |
| `ready_gate.py` | system/scripts/ | The pre-flight every tag-WRITE path must pass: screen on, PoGo foregrounded, not in the `/background` freezer cpuset. A frozen process accepts writes that never land. |

## Canonical: the six gate audits

All read-only, seconds each, no device contact. `full_audit.py` gates on `rc == 0` **and** the
verdict substring -- changing a verdict line without updating `full_audit.AUDITS` disarms the gate.

| Script | Location | Proves | Verdict substring |
|--------|----------|--------|-------------------|
| `audit_cull.py` | root | Pile is keeper-free across 8 layers | `ALL LAYERS PASS` |
| `audit_tags_membership.py` | root | Every tag matches its rule, both directions | `ALL TAG MEMBERSHIPS CORRECT` |
| `_evocheck.py` | root | No piled mon would improve a stage by evolving | `none of the tagged mons would improve` |
| `_lawcheck.py` | root | Every piled mon re-derives to a reason from scratch | `UNEXPLAINED: 0` |
| `audit_invariants.py` | root | The structural model is coherent, I1-I7 -- the only one that catches a wrong *question*. I7 (2026-09-07) = STAT-LINE FIDELITY: every `(species,form)` reproduces its own stored CP under the speciesId the live ranker maps it to | `ALL STRUCTURAL INVARIANTS HOLD` |
| `regress_pvp_keepers.py` | system/scripts/ | The 18 historically-lost PvP keepers all come back KEEP **by a PvP-class axis**, re-inserted into a SANDBOX copy of the bag and run through the REAL `keep_policy`. The only audit that can speak for a mon no longer in the bag. Currently 18/18 | `ALL PVP KEEPER FIXTURES KEPT` |

Not part of the gate, but read-only and cheap:

| Script | Location | Role |
|--------|----------|------|
| `_spotdata.py` | root | ~2s read-only JSON fact-pack |
| `check_constant_drift.py` | system/scripts/ | Asserts every game constant has exactly ONE definition -- runtime (each consumer's constant IS `cpm_table`'s) plus an AST scan for a re-hardcoded CPM ladder / L50 multiplier / league cap. Prints `ALL GAME CONSTANTS SINGLE-SOURCED`. Run it after touching a ranker. |
| `push_armored_tags.py` | root | **One-shot, by hand.** Pushes the static `Armored UL` / `Armored ML` snapshots. Its PLAN is hardcoded to those two tags with no CLI override, so it cannot name the pile. Nothing recomputes its tagsets -- that is why they are in `granular_tags.EXEMPT_TAGSETS`. |

## Canonical: crawl, query and tag utilities

| Script | Location | Role |
|--------|----------|------|
| `pogo_pipeline.py` | root | Single-attach re-crawl: bag walk -> reconcile -> tags -> ranks -> cull. Writes the `fresh_*` columns. Invoked by `/api/recrawl`. |
| `pogo_il2cpp.py` | root | Shared Frida/IL2CPP session library (`get_session`, `pick_singleton`, `walk_bag_protos`, `find_protos_for_uids`, `wait_ready_to_attach`). |
| `read_player_state.py` | root | Live player state -> `player_state.json`. **Never hardcode storage capacity** (a hardcoded 11150 was wrong by ~2x). |
| `verify_tags_live.py` | root | Post-sync server-truth verification. Self-gates on screen + foreground; falls back to a cache reconcile and says so. `--force` only on explicit request. |
| `bulk_tag.js` | root | Frida JS: `add_tag_on_instance`, `find_tag_id_by_name`, `bulk_tag_many`, `bulk_untag_one`. |
| `compute_all_ranks.py` | root | GL/UL/LL IV-spread rank calculator (chain-aware, level cap 50). Updates DB rank columns. |
| `detect_legacy.py` | root | Legacy/elite-move detector. Writes `legacy_accurate.json`. |
| `refresh.py` | system/scripts/ | Turnkey wrapper: precheck -> pipeline -> deep_profile -> reconcile -> auto-restore -> verify. |
| `query.py` | system/scripts/ | Instant-answer CLI over `deep_profiles.json`. Subcommands: `stats`, `mon`, `best`, `powerup`, `evolve`, `lucky`. |
| `doctor.py` | system/scripts/ | Read-only health check: DB age, freshness, tag drift, data-quality flags. Exit 0/1/2 = PASS/WARN/FAIL. |
| `deep_profile.py` | system/scripts/ | Per-specimen profiler: PvP viability, opportunities, flags. Writes `deep_profiles.json`. |
| `tag_ops.py` | system/scripts/ | Hardened tag create/apply with warm-up, exponential backoff, batch retry, and the 8s creation throttle. Colour is `PokemonTagColor` **0-8**; the argparse help saying "0-9" is wrong, the validator is right. Has **no delete primitive** and deliberately keeps none. Its `apply` CLI **refuses a pile tag** (`Transfer` / `6 Transfer`) unless `--yes-push-the-release-pile` is typed, the DB member set matches the tagset file, AND `preflight_transfer.py` runs right there and exits 0. |
| `safe_nuke_tags.py` | system/scripts/ | **The only sanctioned deletion path.** One tag at a time: fresh re-enumerate, delete, 3s settle, then re-enumerate ALL tags and verify every non-target still exists with the same member count. A `DeleteTag` loop reorgs the service cache and deletes off stale pointers -- that is how `Mega` was destroyed. Deletion is also separately rate limited (~1-3 per session). Replaced `_nuke_tags.py`. |
| `reconcile_tags.py` | system/scripts/ | Server-vs-DB tag drift reporter. Modes: `--report`, `--fix-db`, `--fix-server`. |
| `prune_server_tag.py` | system/scripts/ | Removes server members the DB no longer tags, for one named tag. Narrower than `prune_tags.py`; exists because `tag_ops apply` is add-only. |
| `check_freshness.py` | system/scripts/ | Fast live-bag-vs-DB staleness **report**. Exit 0=fresh, 1=stale. **Read-only -- writes nothing**, so it can tell you a recrawl is needed but cannot perform one. |
| `verify_tags.py` | system/scripts/ | Post-apply tag membership verifier, driven by `system/tags/registry.json` (the 11 historical tags). Compares SERVER vs DB vs RULE. |
| `clear_nicknames.py` | system/scripts/ | Bulk-clear custom nicknames via `PokemonBagImpl.NicknamePokemon(proto, "")` (empty string -> reverts to species name; server-authoritative). Modes: `scan`/`test`/`clear` (loop-until-dry, `--delay`/`--limit`). Replaces `run_rename*.py` / `run_nickname_*.py`. Writeup: [`nickname_clearing.md`](../nickname_clearing.md). |

## Data / utility modules

| Script | Role |
|--------|------|
| `references.py` | Untouchable-category constants (legendary/mythical/UB/paradox IDs, mega species, legacy moves) for cull engine. |
| `form_overrides_complete.py` | (species, form) -> PvPoke speciesId mapping table. Used by `compute_all_ranks.py`. |
| `build_form_category.py` | Generates `form_category.json` (default/regional/event/cosmetic/mega/dynamax/gmax classification). |
| `build_move_id_to_name.py` | Extracts HoloPokemonMove enum -> name map from IL2CPP metadata. Writes `move_id_to_name.json`. |
| `build_legacy_accurate.py` | Alternate legacy detector (reads pvpoke gamemaster). Writes `legacy_accurate.json`. |
| `form_category.py` | Legacy version of form category builder. |
| `db_safety.py` | DB snapshot + schema-version tracking module. `snapshot()`, `snapshot_before()`. |
| `frida_session_guard.py` | Preflight validation (version check, drift check) before DB writes. |
| `cull_v9.py` | Cull engine v9: single PROTECTION_RULES registry. Still imported in-process by `pogo_pipeline.py`, which writes the `cull_decision_v9` column. **That column is NOT the keep law** -- it is a dead legacy signal that disagrees with the live engine. The pile comes from `keep_policy.py` alone. |
| `keep_engine.py` | system/scripts/ -- shared keep-law helpers used by `keep_policy.py`. |
| `audit_invariants.py` | Structural invariant harness. Listed with the gate audits above; also the reference for what "capped axis vs keep-all axis" means. |
| `account_report.py` | Assembles `ACCOUNT_REPORT.md` from probe JSON + DB. Pure Python, no Frida. |
| `account_snapshot.py` | Captures live account state (stardust, coins, XP, etc.) via Frida. |
| `_pvp_top10.py` | Computes GL/UL top-10 meta pick tags from chain ranks. Writes tag plan JSON. |
| `_apply_buckets.py` | Applies the 6 bucket-derived tags (Reserve, Trade, Mega, etc.) to server. |
| `_restore_tags.py` | Restore deleted tags from DB mirror. Quick script; prefer `tag_ops.py apply`. |

## Deleted and retired scripts

These no longer run. Any doc, transcript or habit that still invokes one is wrong -- use the
replacement column.

| Script | State | What actually replaces it |
|--------|-------|---------------------------|
| `tag_cull_transfers.py` | **DELETED** | The sanctioned pile path: `keep_policy.py` -> `build_tagsets.py` -> `preflight_transfer.py` -> `prune_tags.py --atomic` -> `set_db_tags_from_files.py`, or just `python full_audit.py`. **Not** `pogo_pipeline.py --tag-transfers` -- that flag still exists but pushes the dead `CLAUDE_TX` tag, which is not the pile and is not gated. |
| `delete_tags.py` | **DELETED** | `system/scripts/safe_nuke_tags.py` (one-at-a-time, collateral detection). Deleting tags is outside the normal cycle. |
| `run_fresh_poll.py` | **DELETED** | `pogo_pipeline.py` -- it is what writes the `fresh_*` columns. **`check_freshness.py` is not a replacement**: it is read-only, writes nothing, and only reports whether a recrawl is needed. |
| `parse_fresh.py` | **DELETED** | `pogo_pipeline.py` (proto parsing is in-process now). |
| `ingest_new_pokemon.py` | **DELETED** | `pogo_pipeline.py` (upserts new catches during the reconcile step). |
| `auto_tag.py` | **RETIRED 2026-09-02** -- still present, exits 2 with an explanation | The sanctioned pile path above. It was a **second, ungated pile producer**: measured on the live DB it would have tagged 44 keepers (26 shiny, 13 variant_floor, 5 protected Pichu) for release and untagged 31 real pile members. Its own preflight returned zero hits on that pile. **Do not re-arm it**; the original body survives only as `auto_tag.py.prelockdown.bak` for forensics. |

## Superseded scripts (historical -- do not use)

### Tag operations (replaced by `system/scripts/tag_ops.py` + `safe_nuke_tags.py`)

| Script | Replaced by |
|--------|-------------|
| `_nuke_tags.py` | `safe_nuke_tags.py` -- **DANGEROUS: caused Mega/Costume deletion via stale pointers** |
| `_nuke_all_tags.py` | `safe_nuke_tags.py` |
| `run_bulk_tag.py` | `tag_ops.py` |
| `add_real_tag.py` | `tag_ops.py` |
| `find_tag_id.py` | `tag_ops.py` (uses `find_tag_id_by_name` internally) |
| `list_tags.py` | `reconcile_tags.py` (enumerates as part of reconciliation) |
| `enum_all_tags.py` | `reconcile_tags.py` |
| `audit_all_tags.py` | `reconcile_tags.py` |
| `audit_tags.py` | `reconcile_tags.py` |
| `fix_all_tags.py` | `reconcile_tags.py --fix-server` |
| `repoll_tags.py` | `reconcile_tags.py` |
| `verify_tags.py` (root) | A CLAUDE_TX one-off verifier. The canonical one is `system/scripts/verify_tags.py` -- do not confuse them. |
| `verify_all.py` | `reconcile_tags.py` |
| `verify_tags_authoritative.py` | `reconcile_tags.py` |
| `apply_tx_tag.py` | `tag_ops.py apply` |
| `capture_setpokemontags.py` | `tag_ops.py` |
| `scan_tag_bindings.py` | `reconcile_tags.py` |
| `find_tags.py` / `find_tags_v2.py` / `find_tags_v3.py` | `reconcile_tags.py` |
| `extract_tag_ids.py` | `reconcile_tags.py` |
| `get_authoritative_tagged.py` | `reconcile_tags.py` |
| `refresh_tag_bindings.py` / `refresh_tag_bindings_v2.py` | `pogo_pipeline.py` (mirrors tags during re-crawl) |
| `robust_tag.py` | `tag_ops.py` |
| `generate_tag_assignments.py` | `tag_ops.py` |
| `_tag_rebuild.py` | `tag_ops.py apply` |
| `_tag_clean_reset.py` | `safe_nuke_tags.py` + `tag_ops.py` |
| `_tag_drift_fix.py` | `reconcile_tags.py --fix-server` |
| `_tag_cull_set.py` | `_apply_buckets.py` |
| `_tag_new_qualifiers.py` | `tag_ops.py` |
| `_tag_pvp_top10.py` | `_pvp_top10.py` + `tag_ops.py` |
| `_tag_dex_review.py` | `deep_profile.py` |
| `_sync_tags_post_evo.py` | `reconcile_tags.py` |
| `_dump_tags_from_svc.py` | `reconcile_tags.py` |
| `_dump_claudetx_binding.py` | `reconcile_tags.py` |
| `_fix_claude_tx.py` | `reconcile_tags.py --fix-server` |
| `_commons_trim_tag.py` / `_commons_trim_more.py` | `_apply_buckets.py` |
| `final_2_tags.py` | `tag_ops.py` |
| `tag_45_shadows.py` | `tag_ops.py` |
| `tag_v3.py` / `tag_v3_cached.py` / `tag_v3_xfer.py` | `pogo_pipeline.py` |
| `tag_v8_transfers.py` / `tag_v8_transfers_v2.py` | The sanctioned pile path (see Deleted and retired above) |
| `tag_evolve_me.py` / `tag_review_candidates.py` | `deep_profile.py` |
| `tag_gl_ul.py` | `tag_ops.py apply "GL" 1` / `tag_ops.py apply "UL" 2` |
| `tag_dmax_strict.py` | Nuked tag; no longer needed. |

### Inventory / extraction (replaced by `pogo_pipeline.py`)

| Script | Replaced by |
|--------|-------------|
| `run_full_inventory.py` | `pogo_pipeline.py` |
| `full_pipeline.py` | `pogo_pipeline.py` |
| `full_inv_v2.py` | `pogo_pipeline.py` |
| `reconcile_inventory.py` / `reconcile_inventory_v3.py` | `pogo_pipeline.py` (internal reconcile step) |
| `rescan_inventory.py` / `rescan_inventory_v2.py` | `pogo_pipeline.py` |
| `refresh_size_category.py` | `pogo_pipeline.py` (internal step) |
| `read_pokedex_liveness.py` / `read_pokedex.py` / `read_pokedex_v2.py` / `read_pokedex_hundos.py` / `read_pokedex_live.py` | `pogo_pipeline.py` |
| `count_fresh.py` | `check_freshness.py` |
| `quick_inbag_check.py` | `check_freshness.py` |
| `enrich_displays.py` / `fix_displays.py` | `pogo_pipeline.py` (internal display enrichment) |
| `add_v2_fields.py` / `add_v3_fields.py` / `add_v4_display_fields.py` / `add_v5_remaining_fields.py` | `pogo_pipeline.py` |
| `add_extra_fields.py` / `add_names.py` / `add_species_flags.py` | `pogo_pipeline.py` |
| `extract_owners_bagwalk.py` / `extract_owner_names.py` | `pogo_pipeline.py` |

### Cull engine iterations (replaced by `cull_v9.py` via `pogo_pipeline.py`)

| Script | Note |
|--------|------|
| `cull_engine.py` / `cull_engine_v2.py` / `cull_engine_v3.py` | Early cull iterations |
| `cull_v4_pvp.py` / `cull_v5_shiny.py` / `cull_v6.py` / `cull_v7.py` / `cull_v8.py` / `cull_v8_indexed.py` | Intermediate cull iterations |
| `cull_v9_shadow_dryrun.py` | V9 variant; one-off |
| `cull_whatif.py` | Simulation tool |
| `kanto_cull.py` / `kanto_cull_v2.py` / `kanto_cull_v3.py` / `kanto_cull_v4.py` | Region-specific cull one-offs |
| `shiny_cull.py` / `dmax_cull.py` / `dmax_cull_v2.py` | Subset cull one-offs |
| `bulk_release.py` | Automated transfer via Frida (dangerous, rarely used) |
| `unfavorite_all.py` | Unfavorite helper for pre-cull |

### Offset / field discovery (early reverse-engineering, no longer needed)

All `analyze_offsets.py`, `find_more_offsets.py`, `find_all_fields.py`, `find_remaining.py`,
`full_offset_scan.py`, `find_pointers.py`, `find_more_pointers.py`, `correlate.py`,
`deep_offsets.py`, `specific_offsets.py`, `dig_more.py`, `refine_200.py`, `scan_offsets.py`,
`correlate_finds.py`, `dig_specific.py`, `verify_finds.py`, `dig_buddy.py`, `final_dig.py`,
`final2.py`, `v2_scan.py`, `v2_correlate.py`, `v2_aligned.py`, `v2_deep.py`, `v2_lists.py`,
`v2_more.py`, `v2_final.py`, `v2_remaining.py`, `v2_validate.py`, `new_field_hunt.py`,
`offset_scan.py`, `offset_validate.py`, `offset_validator.py`, `dump_bytes.py`,
`uid_neighborhood_scan.py`, `refined_scan.py`, `examine_v3.py`, `examine_klass.py`,
`examine_klass_2.py`, `scan_real_klass.py`, `find_all_binding_klasses.py`, `walk_arrays.py`,
`scan_marker.py`, `scan_uid_streaming.py`, `mem_scan.py` / `mem_scan_fast.py` /
`mem_scan_full.py` / `mem_scan_parallel.py` / `mem_scan_pc.py` / `mem_scan_v3.py`,
`examine_hits.py`, `examine_v2.py`, `find_real_bindings.py`, `dig_dict.py`,
`examine_backref.py`, `examine_dict.py`, `read_klass_names.py`,
`_dump_proto_layout.py`, `_enrich_proto_fields.py`.

### Capture / hook / network (experimental, not part of normal workflow)

`pogo_capture.py`, `run_capture.py`, `reattach_capture.py`, `diag_hook.py`,
`analyze_captures.py`, `spawn_inject.py`, `decode_xor.py`, `il2cpp_dump.py`,
`gadget_hook.py`, `hook_aggressive.py`, `hook_ble_data.py`, `hook_ble_native.py`,
`hook_ble_read.py`, `hook_cq_response.py`, `hook_cq_v2.py`, `hook_native_waina.py`,
`hook_ui_text.py`, `ble_logger.py`, `get_pgp_mac.py`, `floyd_client.py`,
`probe_endpoints.py`, `niantic_replay.py`, `paranoid_decrypt.py`, `paranoid2.py`.

### Waina / quests / sleep (experimental features)

`waina_capture.py`, `waina_inject.py`, `waina_inject_v2.py`, `waina_loop.py`,
`waina_orchestrator.py`, `waina_walk_and_claim.py`, `waina_walk_one.py`,
`walk_waina_progress.py`, `walk_waina_subquests.py`, `check_waina_state.py`,
`extract_quests.py` / `extract_quests_v2.py` / `extract_quests_v3.py`,
`unstuck_quests.py`, `inject_sleep_records.py`, `trigger_sleep_sync.py`,
`trace_sleep_pipeline.py`, `stardust_watch.py`, `dex_watcher.py`.

### Friends / social (one-offs)

`extract_friends.py` / `extract_friends_v2.py` / `extract_friends_v3.py`,
`extract_friend_activities.py`, `dump_friend_class_layout.py`, `find_friend_classes.py`,
`find_friend_protos.py` / `find_friend_protos2.py`.

### Audits / analyses (one-off queries, replaced by `deep_profile.py` or direct SQL)

`_activity_audit.py`, `_agent_1_absolute_rarity.py`, `_audit_legendary.py`,
`_buddy_audit.py`, `_build_mega_audit.py`, `_costume_audit.py`, `_dex_analysis.py`,
`_dex_deep_read.py`, `_hundo_audit.py`, `_jumbo_reconcile_check.py`,
`_jumbo_server_members.py`, `_league_audit.py`, `_lucky_audit.py`,
`_move_analysis.py`, `_pvp_audit.py`, `_regional_audit.py`, `_size_audit.py`,
`forms_diversity_audit.py`, `build_dmax_gmax_audit.py`, `analyze_evolution_candidates.py`,
`analyze_missing_forms.py`, `aggregate_review_candidates.py`, `evo_dex_gap.py`,
`missing_hundos.py` / `missing_hundos_v2.py`, `inspect_pokemon.py` / `inspect2.py`.

### Verification one-offs (replaced by `reconcile_tags.py`)

`_verify_claudetx_uids.py` / `_verify_claudetx_uids_v2.py`,
`_verify_null_transfers.py` / `_verify_null_transfers_bulk.py`,
`_verify_pipeline_state.py`, `_verify_v8_transfers.py`,
`verify_ranks.py`, `verify_locationcard.py`, `validate.py`, `validate_instance.py`,
`_triple_check.py`, `full_check.py`.

### Bucket-specific one-offs (replaced by `_apply_buckets.py` or `tag_ops.py`)

`_buckets.py`, `_bucket_251_300.py`, `_bucket_601_650.py`, `_bucket_851_900.py`,
`_chunk_specimens.py`, `_classify_specimens.py`, `_classmap.py`,
`_analyze_151_200.py`, `_analyze_901_950.py` / `_analyze_901_950_strict.py`,
`_strict_701_750.py`, `strict_check_251_300.py`, `_legendary_trim_dryrun.py`,
`_retry_legendary.py`, `_finish_stragglers.py`, `_new_qualifiers.py`,
`_apply_agent_tags.py`, `_agent_pipeline.py`.

### Miscellaneous one-offs

`_bag_currency_check.py`, `_best_buddy_only.py`, `_claim_waina_subs.py`,
`_confirm_coin_stardust.py`, `_decode_items_stardust.py`, `_decode_oneof.py`,
`_dex_max_out.py`, `_diag_clientitem.py`, `_diag_dict.py`, `_diag_key.py`,
`_diag_model.py`, `_extract_currency_items.py`, `_extract_evo_reqs.py`,
`_find_byte_dispatch.py`, `_find_i18n.py` / `_find_i18n_impl.py`,
`_find_pgp_classes.py` / `_find_pgp_native.py`, `_find_pokedex_now.py`,
`_find_quest_classes.py` / `_find_quest_impl.py` / `_find_quest_rpc.py` /
`_find_quest_status.py` / `_find_quest_svc.py`, `_find_real_svc.py`,
`_find_record_handler.py`, `_find_rpc_dispatch.py`, `_find_submit_sleep.py`,
`_find_svc_now.py`, `_find_uid_offset.py`, `_find_waina.py`,
`_fix_levels_live.py`, `_ml_top25.py`, `_prune_jumbo.py`,
`_probe_cq_sig.py`, `_probe_multipart.py`, `_probe_rpcrequest.py`,
`_probe_sendrpc.py`, `_probe_svc.py`, `_probe.py`, `_read_exc.py`,
`_recon_classes.py`, `_recon_evolve.py`, `_recon_gm2.py`,
`_recon_inv_currency.py`, `_recon_inv2.py`, `_recon_services.py`,
`_scan_pgp_syms.py`, `_stardust_probe.py`, `_try_complete.py`,
`_ul_final.py`, `_ul_top25.py` / `_ul_top25_v2.py` / `_ul_top25_v3.py`,
`_walk_inventory.py`, `_dump_cqo_status.py`, `_dump_cqstatus.py`,
`_dump_pgid.py`, `_dump_pgpapi.py`, `_dump_pgpcb.py`, `_dump_pgpstate.py`,
`_dump_quest_enums.py` / `_dump_quest_enums2.py` / `_dump_quest_enums3.py`,
`_dump_rpcrequest_fields.py`, `_dump_sleepservice_methods.py`, `_dump_snorlax.py`,
`_dump_waina_pipeline.py`, `apply_legacy_and_clean.py`, `audit_backgrounds.py`,
`build_db.py`, `build_final.py`, `debug_pokedex_entry.py`, `decode_s2.py`,
`dump_form_enum.py`, `dump_hit3.py`, `dump_mapfield.py`, `dump_pokemon_form.py`,
`egg_status.py`, `eggs_walker.py`, `extract_all_stats.py`, `extract_base_stats.py`,
`extract_settings_v2.py`, `extract_submessages.py`, `find_dmax_gmax_in_cull.py`,
`find_form_class.py`, `find_fp.py`, `find_pokedex.py`, `find_pokemod_data.py`,
`find_pokemod_range.py`, `lean_legacy.py`, `migrate_eggs_table.py`,
`orchestrate.py`, `pgp_probe.py`, `pogo_daemon.py`,
`pogo_il2cpp_cache.py`, `pokedex_incremental_hook.py`, `prime_cache.py`,
`probe_activities_inst.py`, `probe_cax.py`, `probe_pokemod.py`, `probe.py`,
`pvp_rank_test.py`, `pvp_rank_v2.py`, `quick_test.py`, `reanalyze_evolve_me.py`,
`rebuild_full.py`, `rebuild_hundos_florandez.py`, `reconcile_from_drift.py`,
`reconcile_gl.py`, `reconcile_jumbo.py`, `reconcile_league.py`,
`reconcile_ul_cp.py`, `research_pokedex_hooks.py` through `research_pokedex_hooks5.py`,
`restore_db.py`, `run_nickname_search.py`, `run_nickname_extra.py`,
`run_rename.py`, `run_rename_attach.py`, `run_script.py`,
`scan_heap_for_uids.py`, `self_update.py`, `sync_jumbo_tag.py`,
`test_attach.py`, `test_java.py`, `to_sqlite.py`, `untag_*.py` variants,
`update_evolve_me.py`, `version_detector.py`,
`dig_pokemod.py` / `dig_pokemod_v2.py`,
`fix_evolve_me_remainder.py`, `fix_hundos_only.py`,
`investigate_perrserker.py` / `investigate_perrserker_v2.py`.
