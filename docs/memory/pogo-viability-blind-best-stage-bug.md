---
name: pogo-viability-blind-best-stage-bug
description: "rank_cache stored the chain's best rank VIABILITY-BLIND: a stage that never reaches the league cap ranks its spreads by raw IV (hundo = #1), so it MASKED the real viable stage's rank (Dottler 15/15/15: stage dottler #1 / max CP 1,164 hid Orbeetle UL #3 / max CP 2,513) and every consumer saw no PvP protection. Fixed 2026-09-08: prefer viable stages; 2,232 of 5,738 rows changed; regress fixture added."
metadata:
  type: project
---

**The bug.** `rank_cache.py` (and `compute_all_ranks.py`, `regress_pvp_keepers._best_rank`) chose `gl_stage/gl_rank`
as the LOWEST rank across all evolution stages. For a stage whose 15/15/15 never reaches the cap, every spread
"ranks" by raw IV, so a hundo is #1 there and always wins the chain -- then `pvp_iv_rule.qualifies()` saw a
non-viable stored stage and returned False, and rules 15/15b/1095 and preflight all agreed: no PvP protection.
Live measurement 2026-09-08: 1 mon masked in UL (Dottler 15/15/15, protected only because it is a hundo), 0 in
GL -- but **2,232 of 5,738 rows** carried a non-viable best stage (Pikachu x203, Eevee, Bulbasaur, Squirtle...),
so the GL/UL Rank ordinal tags and Best GL/UL were built on the wrong stage for all of them.

**The fix (source, not consumers):** `rank_cache._stage_viable(cache, sid, cap, shadow)` = the stage's 15/15/15
breaches `cap + viability_margin` before max level (`find_max_idx(...) < MAX_LEVEL_IDX`; base stats are the dict
`{'atk','def','hp'}`). Selection: a viable stage always beats a non-viable one; among equals lowest rank; fall
back to the overall lowest so rule 15c's NULL guard keeps its meaning. `regress_pvp_keepers._best_rank` mirrors
it, a **Dottler fixture** pins stage=orbeetle + a PvP axis, and four old anchors that had frozen the bug (Abra
"UL #3 via abra", Meowth-Galarian "GL #548 via meowth_galarian") were re-anchored to the viable stage. Pile
unchanged (25); 6 audits + 19/19 fixtures pass.

**Why it matters for the viability-margin debate:** the "degenerate under-cap band" the margin was meant to
suppress was partly this bug -- with a viable-first selection, an under-cap stage only wins when NO stage in the
chain reaches the cap, which is the one case the rank truly is meaningless.

Related: [[feedback-pvp-rank-not-iv-threshold]], [[pogo-forensic-cull-audit-2026-09]], [[pogo-capped-vs-keepall-bug-class]].
