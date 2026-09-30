---
name: feedback-keep-the-only-look
description: "Never advise evolving the best shiny of a LOOK (species + form + costume + gender where drawn differently). 2026-09-30: a crowned shiny Cottonee was tagged to evolve because a plain one was the stage's best; he evolved it and lost the look."
metadata:
  type: feedback
---

User 2026-09-30: "i noticed you dont keep my only anything when evolving shinies. for example the costumed whimsicott i
evolved, not theres no costumed cottonee." -> "i already evolved it num nuts".

**What happened:** `refresh_evolve_shiny` keeps each stage's best shiny as its trophy (never tagged to evolve), keyed by
(species, form). The flower-crown costume (fresh_costume 75) is not a form, so with a 78% plain shiny Cottonee as the
stage's best, the 51% crowned shiny Cottonee read as a spare and got Evolve Gated (a Sun Stone). He evolved it; the
crowned look left the Cottonee stage. Same gap for gender looks: that day 5 advised shinies were their look's only/best
shiny -- crowned Cottonee, Sneasel M, Hisuian Sneasel F, Murkrow F, Rhydon F.

**Rule now (LAW shiny ladder, 2026-09-30):** a stage's best shiny never moves PER LOOK -- species + form + costume + the
gender where the game draws the two differently (`evolvable_forms.gender_key`). `audit_labels` BLOCKs any evolve tag on
the best shiny of its look, whatever the producer (a planted crowned Cottonee was caught). Keeps did not move: all 5 are
kept as `shiny`; they lost only `shiny_ladder` and the tag.

**How to apply:** "a look" is every visible difference he collects: form, costume, gender-look, background/card
(collectible), shadow. Before any advice that CONSUMES a copy, ask "is this his only one of this look at this stage?"
-- and tag changes reach the phone only on a cull, so warn him off the stale tags in the meantime.
Related: [[feedback-labels-true-for-the-mon-on-screen]], [[pogo-gender-is-a-look-2026-09-23]], [[reference-pogo-tag-inheritance]].
