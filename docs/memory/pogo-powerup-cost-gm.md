---
name: pogo-powerup-cost-gm
description: Exact Power Up costs from the client game master (2026-09-30): game_opportunities.power_up_cost / power_up_plan, the cull report's report-only Power Up block, how the tables are indexed (slot floor(level)-1), the shadow / purified / lucky / Eternatus rules, and what is NOT verified (rounding, the candy-to-XL swap)
metadata:
  type: project
---

Why: the deep dive into the PokeMiners game master found that nothing priced the `Power Up to 1500 / 2500` tag: `granular_tags.power_ups`
returns (level now, best level) but no code asked whether the dust, candy and XL candy are there. Benny said "yes" (2026-09-30) to a
report-only line. REPORT ONLY: nothing here is a keep reason, a tag or a pile decision (all 8 tagged mons are kept for their own reasons).

## The tables (`POKEMON_UPGRADE_SETTINGS`, identical in APK 0.395.1, 0.407.0 and 0.427.0)
- `upgradesPerLevel` 2: one table slot per WHOLE level, paid twice. A step from level L reads slot `floor(L) - 1`
  (L1 -> L1.5 -> L2 -> L2.5 -> L3 all cost 200 dust; L39.5 -> L40 is slot 38; L49.5 -> L50 slot 48). XL candy reads `xlCandyCost[floor(L) - 40]`.
- `stardustCost` 49 slots (200 .. 15,000), `candyCost` 50 slots (1 x10, 2 x10, 3 x5, 4 x5, 6 6 8 8 10 10 12 12 15, then 0 from L40),
  `xlCandyCost` [10 10 12 12 15 15 17 17 20 20] from `xlCandyMinPokemonLevel` 40, `maxNormalUpgradeLevel` 50,
  `allowedLevelsAbovePlayer` 10 (trainer level 78 here: never binds; a low-level second account's could).
- Totals (hand-checked, they are the selftest goldens): L1 -> L50 = 520,000 dust + 304 candy + 296 XL; L1 -> L40 = 270,000 + 304;
  L40 -> L50 = 250,000 dust + 296 XL; L20 -> L50 = 475,000 + 248 candy + 296 XL; L49.5 -> L50 = 15,000 dust + 20 XL.
- shadow x1.2 and purified x0.9 (`shadowStardustMultiplier`, `shadowCandyMultiplier`, `purified...`) on dust AND candy AND XL candy;
  lucky = `LUCKY_POKEMON_SETTINGS.powerUpStardustDiscountPercent` 0.5 on dust only.
- A per-species override: template `POKEMON_UPGRADE_OVERRIDE_SETTINGS_<the pokemonSettings templateId>`. Only
  `..._V0890_POKEMON_ETERNATUS` exists (candy 30 .. 890 a slot, XL 100 .. 890 a whole level, same dust): L40 -> L50 is 8,900 XL candy, and
  the bag's L45 Eternatus -> L50 is 138,000 dust + 6,900 XL. No `pokemonSettings` field points at an override: the game finds it by name.
- `candyPerXlCandy` 100 on all 541 `V####_FAMILY_*` templates: the game's swap is 100 plain candy for 1 XL candy.
- The second charged move: `SHARED_MOVE_SETTINGS` x1.2 (shadow) / x0.8 (purified) on the `thirdMove` dust and candy. `second_moves()` used to quote
  the plain price for every mon; on the 2026-09-30 bag 1 of its 41 candidates changed (a purified Stantler 50,000 + 50 -> 40,000 + 40), none is tagged.

## What ships
- `game_opportunities.power_up_cost(level_from, level_to, shadow, purified, lucky, dex, form)` -> `{dust, candy, xl, steps}` or None (= unknown:
  no game master, a table shape it does not price, a level the game does not have). Tables are read at call time, never hard-coded.
  `power_up_plan(items, rows)` -> per mon `now` / `exchange` / `short` / `level` / `unread` / `unknown` against this walk's stardust, the
  family's candy and XL candy (`candy.json` / `inventory.json`, only when THIS walk wrote them: the same gates as `candy_now`).
- `cull_report.py`: the last block of the report, for the members of the two Power Up tag FILES, one line each (12 full lines, any more are still
  named in one short line: Benny's "always print it all out"), then a total. `deep_profile.py` prices `power-up->L50` with the same function
  (it said L40 -> L50 = 340,000 dust / 290 XL and L20 -> L50 = 840,000). `_ul_final.py` and `_league_audit.py` keep hand tables of their own:
  dead one-offs, nothing calls them, left as they are.
- Bag Pulse is unchanged: it shows only a size chip for each managed tag, no per-mon Power Up view to add numbers to.
- `evolvable_forms.py` is NOT touched on purpose: it is hashed into the pile's engine stamp (`keep_policy._engine_sha`), so the XL read lives in
  `game_opportunities`. With the same inputs (PYTHONHASHSEED=0) the pile, `policy_reasons.json` and all 33 tag files are byte-identical to
  the code before, and `pile_provenance.json` carries the same `engine_sha256`.

## The 2026-09-30 01:43 bag (the tag holds 8 mons)
- Mandibuzz L16 -> L50: 492,600 dust + 264 candy + 296 XL, the family holds 601 XL: doable now.
- Dusknoir, Slurpuff, Stunfisk (L49.5 -> L50): 15,000 dust + 20 XL each, holding 18 / 11 / 7 XL: doable after exchanging 200 / 900 / 1,300 candy.
- Lickilicky (172 XL, holds 14), Mimikyu (296 vs 4), Seaking (97 vs 19), Turtonator (296 vs 111): short, the swap needs far more candy than is held.
- Total 1,476,600 dust, 512 candy, 1,217 XL against 2,462,829 dust. (4 Rare Candy XL are not counted.)

## Not verified (say so, never claim)
- ROUNDING: the game master gives multipliers, not the rounding. Each step is rounded UP (shadow L40 -> L50 = 300,000 dust + 360 XL, not 355.2).
  The in-game screen wins where it differs.
- The candy-to-XL swap: `candyPerXlCandy` is in the game master, but nothing here has ever done one; a daily limit is unknown. The report says
  "if the game allows the exchange".
- A purified LUCKY mon pays 0.9 x 0.5 on dust here; nobody has checked that in game.
- No live read of the upgrade costs exists (the walk does not read the game's own price screen).
