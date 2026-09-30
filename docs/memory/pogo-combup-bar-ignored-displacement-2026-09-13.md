---
name: pogo-combup-bar-ignored-displacement-2026-09-13
description: "The Evolve Next/Twice comb-up bar counted PLAIN copies only while the keep rule lets shinies/costumes/Gmax take plain slots by IV, so it promised slots that did not exist; the user evolved an 89% Ivysaur on that advice and the Venusaur was culled. keep_policy replaced the bar with ONE model: _earns_slot simulates the evolved copy using the cull's own _eff_cap/topn/dominance. The independent audit _evocheck still re-derives this with its own merged-bar + dominance replica, and its comments still cite the removed keep_policy._stage_bar/_stage_hold."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-13T21:10:03.805Z
---

**Incident (2026-09-13).** User: "the venusaur i evolved because you told me to... you culled... so whats the point of
the evo next tag." Ivysaur 15/13/12 (89%) carried Evolve Next; evolved, the Venusaur had NO keep reason and went to
Transfer. Venusaur's three plain slots were held by Gmax 98%, costume 93% and Gmax 93% under rule 1b's displacement
("any variant any shiny can take up a plain pokemon's spot", 2026-06-08), so `_eff_cap` for plain Venusaur was 0 --
but the comb-up bar (`_improves_stage`/`_cap_of_stage` over `_stage_hold`, plain IVs only) saw 2 plain copies
under a cap of 3 and called it a free slot. Two models of the same slot, the advisory one wrong -- the same
capped-vs-keep-all family as [[pogo-capped-vs-keepall-bug-class]].

**Fix.** `keep_policy._stage_bar(sid)`: merged ranking of the stage's displacing specials (non-hundo shiny +
cosmetic/Dmax/Gmax, keyed per (pid, cf) via `_special_iv_grp`, gender-split and pattern-pooled species excluded)
plus the held plains, specials winning ties; a candidate must strictly beat the cap-th entry. Used by
`_improves_stage` AND the seed-bar oracle export. `_evocheck.sweep` mirrors it (spec[] per sid). Measured on the
live bag: Evolve labels 724 -> 639; of the 85 false ones 54 pre-evos fell to Transfer (they were beyond their own
stage cap and kept ONLY for the promised evolution), 31 stay for other reasons.

**How to apply:** an advisory label is a promise about the keep rule; it must be computed with the keep rule's
own occupancy model, never a simplified copy. When a label tells the user to spend candy/stardust, the outcome
must be provable from the same function that will judge the result. The evolved Venusaur itself stays fodder
under the user's rules unless he says keep.
Related: [[reference-pogo-tag-inheritance]], [[pogo-pattern-pooled-lines-2026-09]], [[feedback-labels-true-for-the-mon-on-screen]].

**Same day, stage caps (user: "middle evos can be capped at 2. Only 3 of the first and final evos can remain at 3.
And remember to comb up").** `plain_line_preevo` (2) now applies to MIDDLE stages only = can still evolve AND some
sid evolves into it (`_is_middle_sid`, parents derived from `allreach_sp`); base and final stages get `plain_line`
(3); a 2-stage line has no middle. The comb-up bar (`_cap_of_stage`), `_lawcheck` and `_evocheck` use the same
test. Measured: pile 55 -> 50 (five base-stage #3 spares rescued), Evolve labels unchanged.

**Second incident, same day (dominance).** After the merged bar shipped the user evolved 47 "Evolve Next" pre-evos;
39 earned a slot, 8 landed in the pile (Growlithe under a 97% Dmax Arcanine, two Krabby under a 95% Dmax Kingler,
two Grimer + a Wooper under costumes, a 93% Jigglypuff under a 96% costume Wigglytuff). Cause: the dominance pass
("collapse up") drops a plain kept only by variant_floor when a kept non-trophy richer sibling has STRICTLY higher
IV, and the bar never modelled it -- the evolved copy earned the slot and was collapsed on arrival. Fix:
`_dom_floor[sid]` = best non-trophy dominator IV (shiny/costume/Dmax/Gmax/shadow/card; form-encoded costumes
excluded, they are their own stage key), `_stage_bar` returns max(cap-th merged entry, dom-1); `_domattr` moved
above the bar; `_specials_by_sid` also skips form-encoded costume keys; `_evocheck.sweep` mirrors (`dom{}`).
Measured offline: Evolve labels 594 -> 546, pile 11 -> 32 (21 pre-evos held only for a false promise).
Rule of thumb: the bar must reproduce EVERY pass that can remove the evolved copy (cap, displacement, dominance).

**Third incident, same evening (label wording + vacated slots).** The user evolved 50 base mons that all read
"Evolve Twice", evolved them ONCE and culled in between: 9 fresh middle-stage copies + 8 older ones hit the pile.
Two causes. (A) The label printed `dist_sp` = evolutions REMAINING to the final, not the steps to the stage the
engine had actually reserved -- a Gible committed to a GABITE slot still read "Evolve Twice". Fixed: `_steps(sid, t)`
from allreach_sp at every mark site; 77 labels re-worded Twice -> Next. (B) A copy earmarked to evolve still held
its stage slot in the top-N ranking, so the next-best plain was "beyond the cap" and, if it improved no later stage,
went to the pile -- yet it is the rightful holder the moment the earmarked copy evolves. Fixed with a RESCUE-ONLY
backfill after the comb-up loop (re-rank each stage over copies with no evolve_ reason, same _eff_cap/topn, mark
variant_floor; the dominance pass still applies). Measured: pile 17 -> 9, labels Next 254 -> 331, Twice 230 -> 153.
Rule: the promised outcome must hold in EVERY intermediate state the user can create by following the label.

**Fourth pass, same evening (18:27 cull, 245 evolutions).** Two more wasted evolutions, both fixed: (1) Poliwhirl 82%
+ 66% were promised POLITOED slots under "Evolve Next" (the comb-up tried finals alphabetically and never knew
Politoed needs a King's Rock); the user evolved by candy into Poliwrath -> fodder. Fix: `ITEM_GATED_TARGETS` (the
shiny label's SPECIAL list, now ONE list in keep_policy) + `_promisable(ts, src)`: an item-gated target is skipped
only when a CANDY sibling branch leaves the same parent stage (Politoed/Poliwrath, Gallade/Gardevoir,
Bellossom/Vileplume, Slowking/Slowbro, Froslass/Glalie, Eevee lure/heart forms); linear chains ending in an item
step (Piloswine->Mamoswine, Roselia->Roserade, Ursaring->Ursaluna) stay promisable. (2) Fennekin 91% was promised a
Braixen slot beside a 93% location-card Fennekin heading to the same stage; on arrival the card copy dominated it.
Fix: `_commit_stage(sid, iv, r)` raises `_dom_floor[sid]` when the promoted candidate carries a dominator attribute
(cards are plain-pool candidates). `_evocheck` mirrors both. Lazier alternative named and rejected: a separate
"Evolve Item" tag (10-file vocabulary change).

**ONE MODEL (2026-09-13 late, user: "you seem to be not able to grasp a sure fire way to organize this").** The
hand-written comb-up bar (`_stage_hold`/`_stage_bar`/`_dom_floor`/`_specials_by_sid`) is GONE. An Evolve label is now
a SIMULATION: `_earns_slot(t, r)` drops a virtual evolved copy of r (same IV/CP/attributes, uid+'~evo') into the
target stage's real plain pool plus the copies already promised there (`_committed`), ranks with the cull's own
`_eff_cap` + `topn`, then applies the cull's own dominance test (kept, non-trophy, strict-superset attributes,
higher IV) against every row of that stage. The comb-up loop + mid-stage promotion + seed-bar oracle moved to just
before the dominance pass so every keep axis is already marked. Oracle bars come from a max-CP plain probe by
binary search (lower bound, as its contract requires). `_evocheck` mirrors the dominance test with `_attrs`/`doms`
(kept per policy_reasons). Measured: pile unchanged (81), labels 272 -> 290 (18 real slots the old bar missed),
engine 1.8 s. Rule: never write a second model of "would this be kept" -- simulate with the first.

**19:38 cull, 135 evolutions, 134 promises held.** Two rules added: (A) the best copy of a MIDDLE stage competes in IV
order like every other candidate (it used to be tried last and then blocked by an "another copy stays" guard, so
Eelektrik 68% got "Evolve Next" while the 91% stayed); the first promotion out of a middle stage PINS the best
remaining copy as resident (`_pinned`, never promoted that pass) -- never emptied, and the worse copy is the one that
stays. (B) Split lines (any source with >1 promisable final) are promised only when every final earns a slot and
is affordable: `keep_policy._promise_targets` / `_evocheck` `_rand` (2026-09-17), because "Evolve Next" cannot name
the branch: the game picks it on a random tap (Wurmple's Silcoon/Cascoon, Toxel, Eevee's candy trio), or it takes an
evolution task or item the label cannot name (Charcadet, Galarian Slowpoke); a 68% Wurmple promised Dustox's
free slot became a Beautifly and went to the pile. `_evocheck` mirrors both. Measured: pile unchanged, 18 labels
moved from worse to better copies.

**2026-09-16: one-model stage key for costume-form species.** `_key_of_sid` was "last key wins" per speciesId; Pikachu
has 46 form keys (45 costume forms, one plain pool at form 598), so two Pichus were judged against a costume-form key
with no dominators, evolved, and were collapsed by 95% costume Pikachus. Fix: prefer the non-costume-form key with the
largest plain pool (`_key_rank`). Removed 3 false promises (Pichu 91%, Charmeleon 91%/64%). Rule: a virtual evolved
copy lands in the PLAIN form of its target; judge it there.
