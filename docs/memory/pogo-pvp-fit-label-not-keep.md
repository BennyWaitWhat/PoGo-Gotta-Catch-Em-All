---
name: pogo-pvp-fit-label-not-keep
description: "\"Can this copy ENTER the league\" gates labels, the Best GL/UL pick (2026-09-23) AND, since 2026-09-30, the rank<=5 keep itself (rules 15/15b): a GL/UL keep only counts on a copy that can play."
metadata:
  node_type: memory
  type: project
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-25T19:38:18.654Z
---

`pvp_iv_rule.fits(r, stage, cap, BS)` is the ONE test for "can this specimen still get under that league's cap"
(own stage -> its real cp; a later stage -> `cp_at` at today's level, since evolving does not change the level;
unknown data => FITS). Added 2026-09-19; `granular_tags` and the audits call it.

**2026-09-30 -- THE LAW CHANGED: a GL/UL keep only counts on a copy that can PLAY** (Benny: "Why would I keep any GL
and UL pokemon that cant participate? powering up is fine, but if its impossible in its best form for pvp, then
wtf"). `pvp_iv_rule.plays(r, league, cap, BS)` = a top-`ready_rank` chain stage that reaches the cap AND `fits()`;
rules 15 (`gl_iv`/`ul_iv`, `qualifies(..., row=r)`) and 15b (`pvp_rank`), preflight's rank alarm, audit_cull layer 7
and the cull report's safety check all ask it. On the 12:19 walk it changed 0 keeps: 4 over-cap top-5 copies
(Magmar, Huntail, Raboot, Croconaw) were all kept for a league they CAN play.
History, so nobody "re-fixes" it back: until then 15b was CP-blind "on purpose" -- gating it on `fits` was tried
2026-09-19 and the fixtures sent 9 spreads to the pile, but those fixtures were BUILT unplayable (the pre-evo at its
own cap's level: an L50 Eevee is an over-cap Umbreon). `regress_pvp_keepers.fixture_cp` now builds each at the level
where its RANKED STAGE sits under the cap (19/19 kept), and an **over-cap twin** (Eevee 0/15/14 at L50) must get NO
rank axis -- both directions are asserted. Never drop the fixtures or the twin.

**Rule 15d Best GL/UL IS now fit-gated (user decision 2026-09-23, "Usable only" + "evolve cps need to [be] figured
out completely").** Found when a verifier noticed the Best GL Centiskorch was a CP3301 hundo and the Best GL
Houndstone a CP1777 91% -- neither can ever play Great League -- while the best copies that CAN (Centiskorch 80%
CP216, Houndstone 78% CP1183) sat in the Transfer pile. New rule: a copy's GL/UL rank counts only at stages it can
actually reach (form/costume/gender locks) AND enter at its TRUE level (the level column is wrong on best buddies;
derive the level that reproduces stored cp). Best = best usable rank; ML unchanged. Applies to shadow rule 2's best
GL/UL too. The own-stage evolve block follows the USABLE winning stage.

Labels: a keeper over the cap gets NO Rank chip (that chip claims it can play). Under 15d-usable an over-cap rank<=5
spread is no longer guaranteed to be a Best GL/UL, so build_tagsets' coverage check may flag it -- ask him which chip.
See [[feedback-labels-true-for-the-mon-on-screen]], [[pogo-tag-vocabulary-2026-09-09]].

**Why (original):** the user read "GL Rank 2-5" on a cp1914 Magmar as the data being wrong. It was not -- all 16,638
chain-stage ranks re-derive exactly. The bug was the label's claim, not the number ([[pogo-rank-tags-per-stage-2026-09]]).

**How to apply:** when a PvP rule looks wrong, re-derive the rank FIRST (`audit_rank_tags.py` sweeps the whole bag).
If the rank is right, the defect is in what a rule DOES with it.

**2026-09-24 late -- EVOLUTION COUNTS EVERYWHERE ("evolution should be considered everywhere and evrything. what the fuck"):** the usable rank is now the best rank at ANY reachable stage, CP-blind per stage; the copy only has to be able to ENTER the league at some reachable stage. A Galarian Corsola 27% at L27 (Cursola would be 2,124 CP) still counts as Cursola GL #375. I had culled it under the stricter per-stage fit and he was furious. Canonical: pvp_iv_rule.usable_best + 5 mirrors (audit_cull, _lawcheck, preflight, audit_tags_membership, _spotdata) -- plus audit_labels.usable_stage, a 6th independent re-derivation that kept the 09-23 per-stage fit and failed the gate on 2026-09-25 (a 9/13/15 Zorua, Best GL as Zoroark #79 but 1,760 CP there); now CP-blind once it can enter at SOME stage. Rank floors: Best GL/UL/ML and shadows at rank <= 150 since 2026-09-25 15:37 ("Let's make it 150 rank." -- to make space; 250 from 04:15 "we comb up", 500 from 03:00, 614 = top 15% on 09-24). Losing a Best can also drop a plain copy's ladder slot: with only variant_floor left it dominance-collapses into a richer higher-IV kept sibling (a 58% Drapion into a 98% shadow Drapion). See [[feedback-pvp-rank-not-iv-threshold]].

**2026-09-29:** best_rank_floor AND shadow_rank_floor = **100** ("Fine 100." -- a 1/3/10 Fletchling wore Best GL + Evo Best GL as a #146 Talonflame). Measured: 33 GL + 35 UL Bests lost, pile 20 -> 58 on the first pass.

**2026-09-29 02:3x:** best_rank_floor AND shadow_rank_floor = **55** on MAIN too ("Make mine #55 as well." -- florandez already ran 55). Measured: pile 11 -> 37 (16 shadows with best rank #57-98, 10 Best GL/UL copies #59-97).
