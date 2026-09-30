---
name: project-pokemod-labels-and-sync-lag
description: "Pokemod-style ungated rank labels (user 2026-09-08 'pokemod labels') were REVERSED 2026-09-09: rank tags are per stage and cap-gated; Best GL/UL are retired. The cache-lag lesson still applies: a sync whose prune verify sees cache lag returns rc=1, SKIPS the set_db mirror step, and the next verify shows DRIFT against the STALE MIRROR -- a second pass converges; it is not a phone problem."
metadata:
  type: project
---

**Labels (granular_tags.py):** the 2026-09-08 ungated decision was REVERSED 2026-09-09 ("drop 13 + gate"). Rank
tags are per stage and cap-gated (maxcp > cap + margin, and not already over the cap), split into own-stage and Evo
tags; Best GL/UL are retired.

**Sync-order lesson (dashboard _push_steps: prune --atomic -> set_db mirror ONLY after a verified push -> reconcile;
Evolve Shiny is pushed by prune since 2026-09-12):** a big label push (323 adds) is ACCEPTED, but prune's immediate re-enumerate
sees the client cache lag ("short=N", never "extra") and returns rc=1 -> full_audit says "SYNC FAILED rc=1" ->
set_db is skipped -> the DB mirror keeps the OLD membership -> verify_tags_live / reconcile compare the phone
(new, correct) to the stale mirror and print DRIFT (e.g. "UL Rank 1 server=230 want=23"). Diagnose by
checking the mirror count vs the tagset FILE count; **the fix is simply a second pass** (prune finds ~0 to
add, verify equal, set_db runs, "VERIFIED after a genuine server refetch"). Do not "repair" the phone.

Also seen: `[WARN] 1 row stored is_egg!=0 but live isEgg_=0` -- the hatch flag clearing
([[reference-hatched-mon-isegg-artifact]]); the pipeline keeps the stored flag conservatively; harmless.

Related: [[reference-pokemod-overlay-rank-mechanics]], [[pogo-viability-blind-best-stage-bug]],
[[reference-fresh-catch-tag-write-lag]], [[pogo-dashboard-hardening-2026-06-10]], [[pogo-rank-tags-per-stage-2026-09]].
