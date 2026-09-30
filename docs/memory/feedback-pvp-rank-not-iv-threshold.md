---
name: feedback-pvp-rank-not-iv-threshold
description: "Keep PvP mons by LEAGUE RANK, never IV magnitude -- a bulk-IV gate overrode rank and permanently released a GL#1 Mareep."
metadata:
  node_type: memory
  type: feedback
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-25T19:38:20.917Z
---

# Keep PvP mons by LEAGUE RANK, never by IV magnitude — and pre-flight the Transfer pile (2026-06-05)

**The failure:** a **0/13/11 Mareep — Great League RANK 1** (i.e. the #1 GL stat-product spread for its evolved form **Ampharos**) was placed in the **Transfer** pile by keep_policy. The user bulk-released the pile trusting it, so the Mareep was **permanently transferred**. PoGo transfers are irreversible — it could not be recovered. The user was (rightly) furious: *"i thought iv thresholds were removed. you are to check every single iv rank for their league."*

**Root cause:** `pvp_iv_rule.qualifies()` (the SHARED rule behind the GL IV / UL IV tags AND the gl_iv/ul_iv keep-reasons) had a `BUILD_BULK` gate: a PRE-EVO build-target was only kept if `iv_def >= 14 AND iv_sta >= 14`. That IV-magnitude threshold sat ON TOP of the league rank and **rejected rank-#1 low-bulk spreads** (0/13/11 = def 13, sta 11). This DRIFTED IN after the registry's own 2026-05-29 changelog said the rule was "rank<=5 only" — so the code contradicted the documented (and user-understood) intent. A 0-attack GL build has a LOW iv_total (24/45), so by IV it looks like junk while by RANK it's elite — the exact case the threshold mishandled.

**`gl_rank`/`ul_rank` semantics (rank_cache.py / compute_all_ranks.py):** computed for EVERY in_bag mon, both leagues (+LL cap 500), as **the best rank among the stages this specimen can REACH, viable stages first** (a stage whose 15/15/15 reaches the cap beats one that cannot); `gl_stage`/`ul_stage` = that stage. So `gl_rank=1` on a pre-evo means **rank 1 for its evolved league form** — a real build-target, not a current-form artifact. The ranker re-evaluates EVERY mon every run (no skip) — power-up CP tiebreaks + game updates.

**The fix (2026-06-05):**
1. **Removed `BUILD_BULK` from `qualifies()`** — pre-evos are kept on `rank <= READY_RANK (5)` + CP-viability ALONE (no def/sta/total IV floor). CP-viability (`maxcp(stage) > cap + viability_margin`, currently 0 in keep_config.json; never raise it, see [[reference-pvp-rank-no-headroom-research]]) is KEPT — that's CP-reachability, not an IV gate; it drops the under-cap-hundo degeneracy.
2. **Added keep_policy rule 15b `pvp_rank`** — a SAFETY NET that keeps ANY mon top-5 for a CP-viable GL/UL form (superset of gl_iv/ul_iv; also catches rank-perfect spreads currently OVER the league cap). GL+UL only — Little League (cap 500) would protect ~every tiny common and gut the cull.
3. **Added a HARD TRIPWIRE** in keep_policy: it `raise SystemExit` ABORTS if any `rank<=READY_RANK` CP-viable spread is ever in the Transfer set, so a keeper can never silently reach the release pile again.
   Verified: Gligar 2/13/14 (GL#5) + Blitzle 0/15/13 (UL#4) — low-bulk rank-keepers the old gate killed — now KEPT.

**Standing lessons:**
- **NEVER gate PvP value on IV magnitude** (total / percentage / def-sta "bulk"). The league **RANK** is the sole strength discriminator (% is ~99.7% even for mediocre; bulk wrongly cuts rank-#1). Check **every** mon's GL+UL rank.
- **The Transfer pile is the ONE irreversible output** (the human bulk-releases it). It MUST be provably keeper-free BEFORE it is synced/acted on — a post-release "safety check" (which is what I had) is too late and only reports the loss. The tripwire is now the pre-flight gate.
- **Watch for code-vs-changelog drift:** the registry said rank-only; the code had a hidden IV gate. When the user says "I thought X was removed," check whether the CODE actually matches the documented rule before defending it.
- **A keep rule lives in `keep_policy.py` (the decision); its LABEL lives in `build_tagsets.py` and/or `granular_tags.py` (granular reason tags, rank tags). Grep both when a rule changes.** Change one without the other and the TAG silently drifts from the KEEP. 2026-06-05: the legacy keep-all change updated keep_policy rule 6 but NOT build_tagsets, so all 352 legacy were KEPT (0 in Transfer ✓) yet only 193 were LABELED "Legacy Moves" (build_tagsets still capped top-3/form). No mon was at risk, but the in-game filter undercounted. The check that catches it = the **TRIPLE-CHECK**: per tag, verify server (reconcile) == DB auth_tag_names == tagset .txt file (build_tagsets output) == an INDEPENDENT recompute from raw fields. Run it when the user says "triple check all the tags."

**No PvP spares (2026-09-24):** he said "I want whichever is best. Spares are not ok." That was about a GL #21 Raticate sitting behind a kept #20.
- Keep the single best usable copy per identity and league, plus any top-5 spread.
- Never offer or suggest keeping a second-best copy, including "favorite it as a spare".
- The cull report's "close call" line only confirms which copy stays.

**Cut-off by PLACE, not the overlay's % (2026-09-25):** he asked "5% their metric or top 15% ours?" after reading Pokemod's `GL1314(95.74%) UL302(93.98%)` on a Squawkabilly. The % (stat product / #1's) means a different depth per species and league: 95% = top ~1,899 in GL and ~2,817 in UL for cap-reaching species, but top 79-195 where the cap is out of reach (and ML). He chose **#500** for Best GL/UL/ML and shadows (pvp.best_rank_floor / shadow_rank_floor), then **#250** an hour later to make space (#250 both freed 51; #100 both would free 110; a 2-copy ladder 352), then **#150** at 15:37 (freed 25 more, 16 of them shadows incl. Garchomp/Tyranitar/Dragonite -- he chose it after seeing that). He reminded: "we comb up" -- a better-ranked arrival takes over the Best, the old one goes. Measure a floor change before touching the config: run keep_policy.main() in-process with keep_config.CFG['pvp'] overridden and builtins.open / os.replace / os.remove patched to redirect every write to a scratch dir (keep_policy never writes the DB) -- the unchanged run must reproduce the live 6_Transfer.txt first; it predicted the #500 pile exactly.

**2026-09-29:** best_rank_floor AND shadow_rank_floor = **100** ("Fine 100." -- a 1/3/10 Fletchling wore Best GL + Evo Best GL as a #146 Talonflame). Measured: 33 GL + 35 UL Bests lost, pile 20 -> 58 on the first pass.

**2026-09-29 02:3x:** best_rank_floor AND shadow_rank_floor = **55** on MAIN too ("Make mine #55 as well." -- florandez already ran 55). Measured: pile 11 -> 37 (16 shadows with best rank #57-98, 10 Best GL/UL copies #59-97).
