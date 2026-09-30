---
name: feedback-never-repropose-plain-shiny-cap
description: "4 plain shinies per form is HIS number -- never list \"plain shiny cap 4 -> 3/2\" as a cull lever again; the shiny lever he accepts is an IV FLOOR on plain shinies (\"only the absolute shitty ones\")"
metadata:
  node_type: memory
  type: feedback
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-24T05:37:03.207Z
---

Never re-propose lowering the plain-shiny cap (4 per species+form). He set it on 2026-09-23 ("i want 4 shinies like
i said") and when I listed "plain 4 -> 3" as a cull lever again on 2026-09-24 he answered "Why do you keep suggesting
that?".

**Why:** a cap decision he has stated twice is settled; re-listing it reads as not listening.

**How to apply:** when he asks how to free slots, list the OTHER levers (cost table) and, for shinies, only the IV
floor: `keep_config.shiny_floor_iv` (18/45 since 2026-09-24 = "the absolute shitty ones"; the best shiny of every
form always stays). Also settled that day: NO to plain ladder 3->2, NO to shadow ML-only, NO to legendary 6->5,
NO to costume 3->2. YES to XXL cut 1050. See [[feedback-number-findings-then-ask]],
[[feedback-pogo-collection-vision-2026-09-13]].

**Shadow rank floor (2026-09-24, later that night):** he took a RANK FLOOR on the shadow rule instead of ML-only: a shadow is kept as best ML/GL/UL only while that rank is in the top quarter (`pvp.shadow_rank_floor` 1024; his words "top 50%" -> "Then top 75%" = cut the bottom 75%). A species whose best shadow is bottom-quarter keeps no shadow. Mirrors: keep_policy rule 7, audit_cull (+ orphan layer exemption), _lawcheck. Yield: 27 (top half would have been 6 -- the ML best usually sits in the top half).

**2026-09-24 ~03:00 -- collection floor 25% across the board** ("1. thats the floor now" / "Do it right"): `keep_config.collection_floor_iv` 12/45; ONE helper `keep_config.floor_top` (index 0 stays, later copies need iv>=12) inside keep_policy.topn and its mirrors (audit_cull._topn + cards, _lawcheck plain/costume verdicts, preflight cards/cosmetic/legacy, _evocheck.improves). Legendary roster exempt from the best-rank floor (their best GL/UL/ML at any rank). Yield: 8. Legendaries: do NOT propose a legendary floor without the exemption in place.

**2026-09-25 -- YES to middle-stage costumes -> 1** ("the middle stages of costume pokemon don't need to be part of the
ladder, that can be reduced to 1"): keep_config caps.cosmetic_middle = 1 via `evolvable_forms.costume_cap` (engine +
audit_cull, preflight, _lawcheck, _spotdata). "pikachu is not a middle stage": a BABY pre-evo added below a line
(evolvable_forms.BABY_PIDS: Pichu, Cleffa, Igglybuff, Azurill, Budew, Happiny, Elekid, Magby ...) does not make its
evolution a middle stage -- I had called Pikachu middle and he was annoyed. Togetic stays middle (Togepi is the
original base). Freed 0 on day one. The PLAIN ladder's middle test (keep_policy._is_middle_sid, pvpoke graph) still
counts babies -- Clefairy/Jigglypuff/Roselia hold 2 plain slots, not 3 -- asked him 2026-09-25.

**2026-09-26 -- the Mewtwo cut was a ONE-OFF, NOT a rule** ("the mewtwo thing was a oneoff, not a new rule btw").
That day he culled Mewtwo by hand-spec (top 9 ML/UL/GL per form, specials + >90% kept, legacy not special) -> 14 to the pile.
Afterwards keep_config went BACK to rarity_keep_all_pids [150] with rarity_ladders {} (the machinery in
keep_config.rarity_ladder_keep stays dormant). Never re-propose a standing Mewtwo ladder; a future Mewtwo trim = ask, one-off again.

**2026-09-26 -- legacy cap 9 -> 6** ("legacy moves can be bumped down to 6") and **no GL shadows** ("remove the gl shadows,
we only collect ul and ml and best iv now"): keep_config shadow_best_leagues ["ul"] (keep_policy, audit_cull, _lawcheck
read keep_config.shadow_leagues()); the best-ML shadow IS the top-IV one. First pass freed 6 (4 legacy, 2 GL-only shadows).

**2026-09-26 -- HIS call on the new 1,000-slot account:** "Make the first thing in the ladder 2." + "and middle stage keep
at 1." -> keep_config caps.plain_line 2, plain_line_preevo 1 (gender stays 2). The "NO to plain 3->2" above was about ME
proposing it on the main account; he chose it himself for the small bag. Measured on that bag: plain 1 would add +85,
Pikachu costumes 4->1 +22, all costumes 3->1 +29, gender 2->1 +7; cards/legacy/XXL/Gmax/Best-floor ~0 (427 keepers are the
last copy of their form).
**Also 2026-09-26, HIS call for the 1,000-slot account:** shiny "4(2plain)" -> caps.shiny 4, shiny_plain 2 (Gyarados 18
unchanged); Pikachu costumes 2. He sets these himself -- still never PROPOSE lowering shiny caps.
**And:** legendary / rarity "3 perviant (mewtwo keeps all)" -> caps.rarity 3 (was 6), rarity_keep_all_pids [150] kept.
