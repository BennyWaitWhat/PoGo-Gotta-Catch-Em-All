---
name: pogo-data-completeness-before-destructive-actions
description: Never cull/transfer/tag-for-transfer on incomplete data — treat any NULL/missing protection input as PROTECTED.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

A cull/transfer is IRREVERSIBLE (a released Pokémon is gone). Every cull mistake this project ever hit traces to one root cause: running a destructive decision on incomplete or uncomputed data. The user's repeated frustration ("Why the fuck are you culling without scanning them?", "be context aware of each pokemon", "are you fucking kidding me") is all about this single failure.

Concrete traps observed:
- **NULL PVP ranks.** Fresh captures have NULL `gl_rank`/`ul_rank`/`ll_rank`. The cull's `gl_rank<=15` protection SILENTLY fails on NULL (NULL is not `<=15` in SQL), so a top-tier meta Pokémon (e.g. a GL/UL Blastoise, form 187) landed in the transfer set. Fix: the pipeline runs `system/scripts/rank_cache.py` before the cull (`compute_all_ranks.py` = manual fallback); a rank/legacy failure aborts it with SystemExit(2).
- **Unmaterialized protos / stale dex / unchecked regional-variant counts / unchecked evolution-dex-gaps** — same class of bug: a protection dimension whose input wasn't COMPLETE and FRESH for the candidates.

The rule: **a NULL or missing value in ANY protection input must be treated as PROTECTED, never as transferable.** Before emitting any transfer set, every dimension must be complete and fresh for the candidates: gl/ul/ll ranks computed (not NULL), live dex read this run (not bag-inferred — see [[pogo-pokedex-lifetime-not-bag]]), size_category fresh, evolution-dex-gap checked, regional-form counts checked, sibling-coverage checked (verify a better sibling is already KEPT before flagging anything as a loss).

**Why:** Releases cannot be undone, and the protection logic uses SQL/Python comparisons where NULL/absent quietly evaluates to "not protected" — the exact opposite of safe.

**How to apply:** the pre-cull completeness gate lives in `keep_policy.py`: section 0 keeps any row with a NULL protection column as `data_incomplete` (a missing column = abort); rule 15c keeps NULL-rank rows and refuses the pile if >20% lack ranks. `auth_tag_names` is not a protection input (keep_policy never reads it; NULL = no managed tag). Assert the live dex was read this run; only then run the cull. If the gate fails, fix the data first — never emit transfers. Surface the gate result to the user every run. The pipeline order is load-bearing: walk_bag → reconcile_db → normalize_forms → refresh_tag_bindings → read_dex → read_ae_registry/loc-card enum/player_state/candy → compute_ranks_legacy (fill NULLs) → cull_v9 → sanity → keep_tagsets → preflight. Relates to [[feedback-verify-before-irreversible]], [[pogo-source-of-truth-db-rules]], [[project-pogo-extract]].
