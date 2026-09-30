---
name: pogo-capped-vs-keepall-bug-class
description: "The #1 recurring defect in the PoGo keep system: code that treats a CAPPED keep axis as if it were KEEP-ALL (or reads the global cap instead of the per-species cap). Recurred 10x in one session. Check every consumer whenever an axis gains a cap."
metadata:
  type: project
---

**THE BUG CLASS.** Every keep axis is either KEEP-ALL (every holder is safe) or CAPPED (only the top-N
per group are safe). Every time an axis is converted from keep-all to capped — or gains a *per-species*
override on top of a global cap — every downstream consumer that still assumes the old shape becomes
wrong. This single mistake recurred **ten times** in the 2026-09-02 session alone, in
`preflight_transfer.py`, `audit_cull.py`, `_lawcheck.py`, `_spotdata.py`, `_evocheck.py`,
`audit_tags_membership.py` and `audit_invariants.py`.

The failure is always ASYMMETRIC and always in the dangerous direction: a checker that thinks an axis is
keep-all sees a legitimately over-cap mon in the Transfer pile and screams BLOCK (noisy but safe), while
a checker that thinks an axis is capped when it is keep-all silently lets a keeper through (silent and
irreversible). Both erode trust in the gate that guards the one irreversible output.

**THE RULE: when you add or change a cap, grep for EVERY consumer of that axis before you finish.**
It is never a one-file change. The canonical checklist:
`keep_policy.py` (the engine) -> `preflight_transfer.py` (the gate) -> every audit in `full_audit.AUDITS` (10) ->
`granular_tags.py` (the tag ordinals) -> the docs.

**Per-species caps are the sharper version.** `keep_config.cap(axis)` returns the GLOBAL cap;
`keep_config.species_cap(axis, pid, base)` returns the per-species override. Code that calls `cap()`
where it should call `species_cap()` is correct until the first per-species override exists and then
instantly wrong. This is exactly what happened the moment `per_species_caps.cosmetic = {"25": 6}`
(the Pikachu costume cap) was added: `preflight_transfer.py` went from PASS to a live BLOCK.

Axes and their shape as of 2026-09-20 (values in `keep_config.json`) — CAPPED: variant_floor (`plain_line` for
base and final stages; `plain_line_preevo` for MIDDLE stages, a `keep_config.py` DEFAULT absent from the json),
cosmetic (per-species: Pikachu 25), shiny (per-species overrides: Gyarados 130, Houndour 228,
Combee 415), shadow, rarity, location_card (per species+form+CARD TYPE), xxl, dynamax, gigantamax, nundo
(per look), legacy moves (`legacy_default_cap` + `legacy_species_caps`, e.g. Absol 359, applied by
`keep_policy.py`; shiny/shadow/costume/hundo and the best GL/UL copy are never cut -- the
`audit_invariants.AXES['legacy']` "keep-all" text is stale), PvP (rank<=5 + a viability gate).
KEEP-ALL: hundo, E+F-origin lucky/traded, Adventure-Effect roster, mighty, dex_only last-copy, live gym
deployment, favorite, shiny_ladder, and the `protected_keep_all_pids` species.

2026-09-17 -- the same class in an AUDIT, not a keeper: `audit_promises.py` judged every target stage's
occupancy with `cap('plain_line')` (3, the FINAL-stage cap) although a MIDDLE stage holds
`plain_line_preevo` (2), ignored `_eff_cap` special displacement, and counted nundos as slot-holders.
It called a lawful Oshawott->Dewott promise "NO REASON: fills a spare slot under a 93% copy" and BLOCKED
the sync. The engine was right: the stage was full and the promise replaced the weakest copy. Lesson:
a hand-written mirror of the engine's occupancy model is the same bug class one file further out --
mirror `_stage_cap` + `_eff_cap` + `_slot_exempt` together, or don't mirror at all. Trace the real
engine (patched copy in a sandbox, printing the closure's own numbers) before believing a replica.

Related: [[feedback-transfer-preflight-every-axis]], [[pogo-collector-keep-rules-2026]],
[[project-keep-config-dashboard]], [[pogo-granular-tags-2026-09]].
