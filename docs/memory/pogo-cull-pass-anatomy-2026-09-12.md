---
name: pogo-cull-pass-anatomy-2026-09-12
description: "Where a full_audit cull pass spends its time (measured 2026-09-12) and the five cuts that took it from ~75 s to 43 s without touching an audit or gate -- cached singletons in the recrawl (18 s), stamp reuse in the sync gate, check-before-sleep in prune's verify, no duplicate cache reconcile while playing, no retire attach when nothing was retired"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-12T08:36:38.431Z
---

**Measured (2026-09-12, bag 5762).** Recrawl job = pogo_pipeline (attach 0.6 s, singletons, walk 2.6 s, reconcile 0.5 s,
ranks 3 s, cull 1 s, keep_policy+build_tagsets 2.6 s, pre-flight live read ~1 s, tag audit ~1 s) + read_player_state
(own attach ~3 s). Sync job = keep_policy+build_tagsets again (~4 s), pre-flight gate, prune (attach, walk, apply,
verify walks), refresh_evolve_shiny (own attach ~5 s), set_db, reconcile (own attach ~5 s). Then full_audit: retire,
verify_tags_live. Before: 7 attaches, ~75 s. After: 5 attaches, 43 s.

**The cuts (user: "speed and precision" -- precision means no audit, gate or hash check changed):**
1. `pogo_pipeline.step_singletons` now goes through `pg.pick_singleton` (per-pid cache, re-validated by the same
   plausibility probes: bag > 100, 0 < tags < 200, dex 500..4000). Three liveness scans = 18 s AND three GC
   world stops per recrawl; now 0.5 s on a hit, scan only on a miss (new game pid).
2. `preflight_transfer` reuses its own stamp when it is < 120 s old and pile bytes, config fingerprint and DB
   content sha all match -- the recrawl pipeline and the sync job run the gate back-to-back on identical inputs.
   The stamp invalidation moved from import time into main(); prune still checks all three hashes + age.
3. `prune_tags` verify checks immediately and sleeps only on a miss (was a fixed 4 s before the first check).
   Released-while-syncing uids are excluded from "short" (and from reconcile's db_only): the user releases the
   pile while the pass runs, and that was failing every pass as phantom drift.
4. `full_audit` polls the dashboard job every 1 s (was 4), skips retire_tags unless the sync log shows a
   RETIRED strip, and skips verify_tags_live when the sync's reconcile was clean AND the user is playing (it
   would only repeat the same cache read; the restart-based server proof still runs when the phone is idle).

**Folded (user "fold", 2026-09-12):** the live storage cap is read INSIDE the recrawl session
(`pogo_pipeline.step_read_player_state`: PlayerService instance + klass pointer cached per pid, plain invoke,
scan only on a miss; read_player_state.py stays as the standalone tool) and Evolve Shiny is computed by
build_tagsets (`refresh_evolve_shiny.compute_target`, fail-LOUD) and pushed by prune like every tag (in the
vocabulary, no longer exempt; may legitimately be empty). Attaches per pass 5 -> 3, writers 2 -> 1. The dashboard
is a long-lived process: its job step lists only change after a restart.

**Probe cost lesson:** the freeze probe cost 6 s per call -- a 160-thread `cat` loop over adb, and it had to move
under `su` because /proc is mounted hidepid (an unprivileged shell reads every wchan as "0", so the probe was
blind). Now one pipeline over the ~8 UnityMain threads, 0.3 s, substring match on sigsuspend, 3 samples 1 s apart.
Result: full pass 43-45 s (recrawl 17 s, audits 3 s, sync ~24 s).

**Not cut, on purpose:** the audits, the rollback gzip (3 MB, < 1 s), the live gym read on a fresh pile. Next
candidate if more speed is wanted: skip the sync's duplicate keep_policy/build_tagsets when provenance is < 2 min
old (~4 s).
Related: [[pogo-gc-world-freeze-2026-09-09]], [[feedback-one-phone-pass-not-three]], [[pogo-pile-gate-2026-09]].

TWO FINISH PATHS in full_audit (2026-09-19): when the user is playing, the sync's reconcile is accepted and main()
RETURNS EARLY at the "VERIFY OK (... user playing ...)" branch -- it has its own DONE + ladder_report and never reaches
the tail. A step added only after the tail DONE silently never runs on a normal cull (that is how the Remote Trade
refresh appeared to work and did not). Both paths now call the same `remote_trade_step()` + `ladder_step()` helpers,
and ladder_step prints the last 8 report lines, not 4 (the new showcase / comb-up lines were being cut off).
Also: after a tag write the PokemonProto pointers are REALLOCATED, so any verify must re-walk the bag -- reusing the
pre-write proto map makes the tag read unchanged and look like cache lag.
