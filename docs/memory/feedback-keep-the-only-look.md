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

**Keep side (LAW bucket 4, user 2026-09-30: "1. yes but comb up, and it comb up once there's at least 2. but keep cap 6.
does that make sense?"):** the shiny cap stays 6 per species + form (4 plain), but the best shiny of each look takes a slot
FIRST -- a plain one a plain slot, floor or not; with 2+ of a look only its best does (comb up). Engine + mirrors
(audit_cull, _lawcheck, preflight_transfer). `Shiny - Only One` is per look too (483 -> 539) -- it also keeps those out of
Remote Trade (remote_trade_picks NEVER_TAGS). The look's costume is `fresh_costume` ONLY: the legacy `costume` column holds
junk (a Gengar read -958922464). 0 keeps changed that day; a synthetic test (8 shiny Donphans: the only female at 12/45
and the only costumed one kept, the 3 weakest extra males piled) passed the engine, preflight and 10 of the 11 audits.
The 11th, rank tags, flagged 16 stored-vs-fresh rank mismatches: all 8 synthetic rows x 2 leagues (they copied a real
Donphan's stored ranks with new IVs) -- a test artifact, confirmed by a re-run of that audit alone.

**How to apply:** "a look" is every visible difference he collects: form, costume, gender-look, background/card
(collectible), shadow. Before any advice that CONSUMES a copy, ask "is this his only one of this look at this stage?"
-- and tag changes reach the phone only on a cull, so warn him off the stale tags in the meantime.
Related: [[feedback-labels-true-for-the-mon-on-screen]], [[pogo-gender-is-a-look-2026-09-23]], [[reference-pogo-tag-inheritance]].
