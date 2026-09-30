---
name: pogo-adventure-effect-live-registry
description: "The Adventure-Effect roster is now READ FROM THE GAME every recrawl (user 2026-09-08: 'should be scanned every time'). AdventureEffectService.adventureEffects (List<AdventureEffect>: PokemonMove@0x18, BonusType@0x1c, MoveDescriptionKey@0x38) held 11 effects vs the hand list's 9 -- Mega Mewtwo X/Y were new. The public game master has NO adventure-effect field at all."
metadata:
  type: project
---

**Finding (2026-09-08, live read pid 19459):** 11 Adventure Effects: Roar of Time (Dialga 483), Spacial Rend
(Palkia 484), Sunsteel Strike / Moongeist Beam (Necrozma 800, fusion items 408/409), Ice Burn / Freeze Shock
(Kyurem 646), Behemoth Blade / Bash (Zacian 888 / Zamazenta 889), Dynamax Cannon (Eternatus 890, move id 482),
and **Mega Mewtwo X (Dynamic Punch+) / Mega Mewtwo Y (Future Sight+)** -- temp-evo moves 495/496, dex 150,
absent from the hand list `keep_config.adventure_effect_pids` (Mewtwo was protected only by rarity keep-all).

**Why the game is the only source:** PokeMiners' GAME_MASTER has zero `adventureEffect` fields, lists Roar of
Time / Spacial Rend under NO Pokemon template, and has no move named Dynamax Cannon (it appears only as the
numeric `eliteCinematicMove: [482]`). Behemoth/Kyurem/Necrozma moves live under
`formChange.moveReassignment.replacementMoves`, not the move pools.

**Mechanism (all read-only, no extra attach):** `pogo_pipeline.step_read_ae_registry(sess)` runs after
`read_dex` on the walk's existing Frida session -> `system/analysis/ae_registry_live.json` (fail-SOFT: a
failed read keeps the previous file; proven with a simulated failure). `system/scripts/derive_ae_roster.py`
maps moves -> species via desc_key hints + temp-evo enum names (`VmMoveTempEvolutionMegaXV0150PokemonMewtwo`)
+ the game master (`gamemaster_pokeminers.json`) -> `ae_roster_derived.json`; exits 2 if a species has no
protection. `full_audit.py` runs it right after every recrawl and returns 6 (stop before sync) on exit 2.
`keep_policy._ae_ids_live()` and `preflight_transfer._ae_roster_union()` UNION the derived species with the
config list (adds protection only, <14 days old). `audit_invariants` BLOCKs on `unprotected`, WARNs if
missing/stale, else ok. Proven end-to-end live: in-walk read rewrote the json, deriver OK, 6 audits pass.

**Two Frida gotchas that each cost a run:** Python `exports_sync.ae_list` calls the JS export **`aeList`**
(snake_case -> camelCase); and never append a `//` comment to a JS line that still has code after it.
Frida 17: `ptr(a).readByteArray(n)`, not `Memory.readByteArray`.

Related: [[pogo-collector-keep-rules-2026]], [[pogo-il2cpp-internals]], [[project-gamemaster-monthly-refresh]].

**UPDATE 2026-09-23 -- PER MON, not per form.** User: "most of those pokemon dont have the adventure effect at all. You
need to stop generalizing and look at each pokemon that actually has it." The 2026-09-09 form rule (every Origin
Dialga) tagged 38, only 19 knew the move. Now `ae_moves.known(r, ae_moves.move_ids())` -- the specimen KNOWS one of the
registry's effect moves (move1/move2/move3, re-read every walk) -- decides in keep_policy rule 8, preflight_transfer,
audit_cull and _spotdata; the form/species roster is only the fallback when the registry cannot be read.
`audit_tag_truth.py` (in full_audit's AUDITS) now tests every tag's CLAIM on every member's own data each cull.
