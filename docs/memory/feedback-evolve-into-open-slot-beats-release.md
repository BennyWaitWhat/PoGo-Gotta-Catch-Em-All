---
name: feedback-evolve-into-open-slot-beats-release
description: Filling an OPEN slot at a later stage is worth it when the alternative is releasing the copy (a stage with a plain hundo, or a full stage without a strictly higher IV, still refuses); candy-short never means release.
metadata:
  type: feedback
---

Two rules now, not one:

* **Kept for another reason** -> still refuse to evolve it into an open slot beneath better copies. That is the
  2026-09-17 rule ("make sure you dont make me evolve pokemon for no reason") and it stands.
* **Kept ONLY for the evolution** -> EVOLVE IT. Its two outcomes are "occupy a slot the law says you may hold"
  and "gone forever". `keep_policy._earns_slot` computes `_rescue = no keep reason besides evolve_*` and skips
  the worth-it refusal; `audit_promises` mirrors it via the LIVE `policy_reasons.json` (its own `reasons` is the
  SANDBOX post-evolution state and cannot answer "would this be released").

**The rescue has limits.** `_rescue` skips ONLY the open-slot-beneath-better-copies refusal. `_earns_slot` still
refuses a target stage that already holds a plain hundo (checked before the rescue: that stage is complete) and,
on a FULL stage, an arrival that does not beat the copy it pushes out on IV strictly (checked after it). Either
refusal still sends the copy to the pile, e.g. a Rhydon under a hundo Rhyperior.

**Candy/item short is a HOLD, never a release.** Affordability decides whether to ADVISE an evolution (2026-09-17
"i just dont have the stone"), never whether the mon lives. An earned-but-unpaid promise marks `variant_floor`
(kept as at-stage stock, no Evolve tag, commits no bar) -- the same shape the phantom-gender-rescue already used.

**Why:** a 13/14/10 Maschiff was tagged Transfer with ONE Mabosstiff held against a cap of 3 -- two empty slots --
because it was 11 candy short of the second evolution. User: "im surprised you ask to transfer maschiff instead of
evolve it" -> "exactly, and that means this is happening to every pokemon."

**Effect measured:** evolve_1 7 -> 16, Transfer pile 1 -> 0. See [[feedback-pogo-collection-vision-2026-09-13]],
[[pogo-data-completeness-before-destructive-actions]].

**2026-09-23 -- the same rule was missing on the COLLAPSE path.** The only plain Minccino (87%) was #1 of its
ladder, then the dominance collapse (a 98% costume copy) removed it; the collapse's own comb-up check asked
`_earns_slot`, whose "worth it" test saw the `variant_floor` reason the collapse was about to delete, read the mon as
"kept anyway", refused the open Cinccino slot -> pile. `_evocheck` (the evo comb-up audit) caught it and blocked the
sync. Fix: keep_policy `_collapsing` set -- a copy under collapse is judged as a rescue (`_rescue=True`); it is now
held with "needs a Unova Stone (have 0)". Lesson: whenever a keep path can DELETE a reason, any decision it makes
must be evaluated as if the reason were already gone.