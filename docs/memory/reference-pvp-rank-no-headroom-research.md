---
name: reference-pvp-rank-no-headroom-research
description: "Deep research 2026-09-08 (11 claims verified against PvPoke's own code/rankings): IV rank = stat product Atk*Def*floor(HP) at the highest half-level under the cap, 1-based index of 4096; there is NO 'headroom above the cap' concept anywhere (the only +150 margin is the Candy-XL cost icon); under-cap species are still ranked and can be META (Tinkatuff GL #8 at max 1495; Cramorant UL #18; Medicham needs XL to reach 1500). Viability margin stays 0."
metadata:
  type: reference
---

**What the tools compute (pvpoke.com/js/pokemon/Pokemon.js, verified 3-0):** for each of 4096 IV spreads walk the
level up in 0.5 steps until CP would exceed the league cap, step back, score `Atk*Def*floor(HP)` with each stat
`CPM*(base+IV)`; `getIVRank()` = 1-based index in the descending list. Level 51 (Best Buddy) enters only by raising
`levelCap`; XL candy is not a rule, just levels 41-50. Poke Genie's PvP IV rating is the same idea.

**No headroom concept exists.** PvPoke's rankings text never mentions max CP or a margin; the single CP-margin
constant, `needsXLCandy()` (L41 hundo CP >= cap+150), only drives a "Requires Candy XL" icon. The rank-1 GL
Medicham is 5/15/15 at L50 = CP 1499 -- the optimizer hugs the cap from below; it never seeks room above it.

**Under-cap species are ranked and can be meta.** 142 of 1,146 GL entries cannot reach 1500 even at L51 (their IV
rank degenerates to "max level + hundo"); Tinkatuff is GL **#8** (score 92.4) with a hard ceiling of 1495; Cramorant
is UL **#18** while falling short of 2500; Pachirisu GL #102 at max 1372. Barely reaching the cap does not degrade a
species -- Medicham (#54 GL, needs XL) is the classic.

**Implication for this project's engine:** the "viability" gate (`maxcp(stage) > cap + margin`) is a stricter idea
than the community uses -- but it is only deciding whether a *rank* earns a PvP tag. For an under-cap species the
rank is meaningless (hundo = #1) and its best copies are exactly the highest-IV ones, which `variant_floor` (top 3
by IV) already keeps. So nothing changes except: **viability_margin stays 0** ("reaches the cap at all"), and the
knob should never be raised -- there is no game concept it would model. The user's framing was right: rank is the
copy's quality FOR THE FORM THE IVS POINT AT; level/CP/moveset are adjustable and irrelevant to the decision.

Related: [[feedback-pvp-rank-not-iv-threshold]], [[pogo-viability-blind-best-stage-bug]], [[pogo-forensic-cull-audit-2026-09]].


**SUPERSEDED 2026-09-28:** viability_margin is now **-101** (a stage counts as reaching the league when its L50 hundo is >= 2,400 UL / 1,400 GL). User: "ok fine 2400 is a good cut off" after his UL #1 Talonflame (max 2,493) and hundo Umbreon (max 2,416) got no UL Rank tag. keep_config _PVP_BOUNDS allows -500..1000. After changing it, run rank_cache.py before keep_policy (the stored *_stage columns pick the 'viable stage first'). Effect on 09-28: pile unchanged (31); UL Rank 1-5 94, Power Up to 1500/2500 9/27, Unlock 2nd Move 34.
