---
name: pogo-mechanics-reference
description: "Durable Pokémon GO mechanics — CP/IV/CPM, multipliers, sizes, mega levels, lucky/shadow/purified, proto-field meanings."
metadata: 
  node_type: memory
  type: reference
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

Durable rules I should not have to re-research each session. Last verified 2026-05-27. Full sourced details: [pogo_extract/research_2026-05-27/01_core_mechanics.md](../../pogo_extract/research_2026-05-27/01_core_mechanics.md).

## CP & level
- `CP = floor(Atk × √Def × √HP × CPM² / 10)`, minimum 10.
- Pokémon level cap **50**; CPM anchors (client GM PLAYER_LEVEL_SETTINGS.cpMultiplier): L1 0.094, L40 0.7903, L50 0.8403, **L51 (Best Buddy active) 0.8453** (L55+ plateau 0.8653).
- Best Buddy bonus is **+1 effective level CPM only while the Pokémon is the active buddy** — switching buddies drops the boost; the badge persists.
- Trainer cap **80** (since 2025-10-15); see [[pogo-game-state-2026]].

## IV floors by source
0/0/0 = wild + TGR (Team Rocket Grunt) catches. 4/4/4 = weather-boosted wild + TGR-boosted. 6/6/6 = Shadow Raid, Giovanni shadow legendaries. 10/10/10 = normal raids, research rewards, eggs, Party Play, Postcard catches, GBL win reward (normal season). **0/0/0** = GO Battle Day/Week/Weekend rewards (deliberately lower). 12/12/12 = Lucky / Lucky-Friend trade. 5/5/5 = best-friend trade. 13/13/13 = Mighty Pokémon (Wild Area, L40+ catch).

## Multipliers
- STAB: **1.2×** (PvE and PvP).
- Weather boost: **1.2×** in PvE only; also +5 catch levels and +25% Stardust on catch.
- Shadow: attack **1.2×**, defence **0.833×** (PvE and PvP) — **combat-only; does NOT affect CP.** Shadow CP == non-shadow CP for identical IVs/level (the boost lives in the stat-product/combat, never the CP formula). Applying the shadow multiplier inside `compute_cp` caps shadows at the wrong level and wildly mis-ranks high-attack shadow IV spreads (real bug: a shadow cp996 read GL 3378 instead of 1048; fixed 2026-05-29 in `compute_all_ranks.py` + `rank_cache.py` — multiplier on `stat_product` ONLY; matches PvPoke).
- PvE type effectiveness: SE **1.6×**, NVE **0.625×**, immunity ~**0.39×** (not zero in PoGo).

## Sizes
Five categories, set at catch time from a roll of height + weight relative to the species. `pokemon_size_category` integer enum is **1=XXS, 2=XS, 3=Normal, 4=XL, 5=XXL** (the project's pipeline uses these values). Showcase score = `height·800 + weight·150 + IV·50`, with **+178 bonus for XXL**. There is **no XL Candy bonus from XXL** — XL Candy comes from evolution stage, not size.

## Mega Evolution (4-tier ladder)
First-ever mega = 200 energy + 14-day cooldown.
- **Base** (after 1 evolution): 41 energy / 7-day cooldown
- **High** (7 evolutions of this species): 21 energy / 5-day cooldown
- **Max** (30 evolutions): 11 energy / 3-day cooldown
- **Super Max** (added Tour Kalos Feb 2026; requires a one-time mega-energy power-up beyond Max): ~24-hour cooldown, boosted catch XP/candy/CP
Mega form lasts **8 hours active**. While active: +30% same-type / +10% other-type attack bonus for teammates of the mega-active Pokémon.

## Lucky, Shadow, Purified
- **Lucky**: 50% Stardust to power up; IV floor 12/12/12; permanent per individual. **Guaranteed Lucky** = a trade where either mon was caught in 2020 or earlier, until the trainer's lifetime 45 guaranteed luckies are spent (cap 25→35 on 2025-02-18 with the window to 2019; 35→45 on 2025-12-31 with the window to 2020, permanent).
- **Shadow**: no blanket IV floor — Team GO Rocket grunt/leader catches are 0/0/0 (4/4/4 weather-boosted); Shadow Raid and Giovanni shadow legendaries are 6/6/6 (Shadow Raids 7/7/7 during some boosted events). +20% attack, −16.7% defence; needs Frustration TM'd off (Elite Charged TM or special event) before it can learn its proper charged moves.
- **Purified**: removes Shadow, adds +2 to each IV (a 13/13/13 Shadow purifies to **hundo**), allows Return as charged move, **costs less Stardust** to power up than a normal of equivalent level.

## Adventure Effect mechanic
Charged "out-of-battle" usage of the signature attack of certain legendary forms. Per use: 6 or 10 minutes of effect, extendable in 2-hour increments up to 24 hours stored max. One effect active at a time *except* Dynamax Cannon (Eternatus) which stacks. Roster: see [[pogo-collector-keep-rules-2026]].

## Tag system (project-relevant)
- Per-Pokémon display limit in-game: **3 tag chips** (extras hidden under "…").
- Account-level limit: ~**100 distinct tags**.
- **14-tag-per-Pokémon cap is NOT confirmed by any web source** — `generate_tag_assignments.py` assumes it; verify by testing in-game or via proto inspection if it ever matters.

## Proto field meanings (project-specific decoder)
- `fresh_bread_mode` = ONE per-individual enum (display proto @0x60): 0 none, 1 **Dynamax**, 2 **Gigantamax**, 4 `BREAD_SPECIAL_MODE` (Crowned Zacian/Zamazenta and Eternatus; 5 in-bag rows on 2026-09-20). Gigantamax is value 2 of this same column, not a separate flag; keep_policy treats anything but 1/2 as plain. "Bread" is Niantic's internal codename for the Dynamax/Gigantamax system. `BreadMove` = Max move. See [[pogo-collector-keep-rules-2026]].
- `fresh_is_strong` = PokemonDisplayProto.IsStrongPokemon (@0x64) = the **MIGHTY** Pokémon flag (strong encounters). keep_policy rule 11 keeps it as reason `mighty`. It is not a Showcase mark.
- `pokemon_size_category` = 1..5 as above.
- `fresh_pokemon_badge` (display +0x28) = the single-int per-Pokémon badge enum (BestBuddy=1, plus Lucky / Lucky-Friend / hundo variants); full enum is not public — treat unknown values as "keep" and infer from data frequencies.
- `fresh_has_location_card` = boolean; encodes both Location Background (in-person event catches, mostly) and Special Background (Ultra Beast / global-event catches). Both behave as "Special Trade" for trade-cost purposes.
- `fresh_has_mega_level` = `True` ⇔ this individual has been mega-evolved at least once.

See also [[pogo-il2cpp-internals]] (offsets), [[project-pogo-extract]] (pipeline shape), [[pogo-collector-keep-rules-2026]] (what these fields mean for tagging).

## Showcases / size, verified 2026-09-19 (user: "i just want to win showcases")
Scoring is a THREE-PART blend, not a single metric: `ContestScoreComponentType` Height=1 / Weight=2 / Iv=3, each with
its own `CoefficientValue` in a `ContestScoreFormulaProto` the SERVER sends per contest. CONTEST_SETTINGS holds the
defaults -- height 800, weight 150, iv 50, xxlAdjustmentFactor 1.0 -- i.e. exactly the 0.80/0.15/0.05 this project
ranks XXL keepers with, so our ranking is faithful (a base-ratio normalisation vs our group-max one changed nothing on
his bag). A focus can be species, family, type, shiny, mega, region, class or alignment (the client's *FocusFilter
classes). `playerContestMaxEntries` = 5.
SIZE BADGE: PokemonProto stores heightM_@104, weightKg_@108 and size_@424 (the badge) -- there is NO stored scale, so
the evolved size is computed server-side. Measured over 5,632 in-bag mons the badge follows
z = (height - pokedexHeightM)/heightStdDev: XXS <= -4, XS -4..-2, normal -2..+2, XL +2..+4, XXL >= +4 (7 of 250 XXL
fall outside only because my form->template mapping misses those forms).
SIZE SURVIVES EVOLUTION -- MEASURED, not assumed (2026-09-19, "do a full study on the evos i did"): 297 evolutions
matched across the walk snapshots (a mon that left one walk and arrived in the next with the same IV spread and
creation date but a different pokemonId). The size badge carried through in 297 of 297 -- 132/132 XXL stayed XXL, plus
162 normal, 2 XL, 1 XS; nothing changed. The evolved HEIGHT matches base_target x (height/base_source) within 1% in 87%
of cases (90th pct 5.3%, worst 25%: Bellsprout->Weepinbell came out 25% taller, Ponyta->Rapidash 11% shorter), so the
projection is good for ranking but not exact. z is NOT preserved (base and stdDev differ per species) -- the badge is.
`size_line.stays_xxl` is therefore a badge test, and `project` only supplies the score.
READABLE LIVE if ever needed: ContestService.GetAllPokestopsWithContests, CheckIfValidContestIsInRange,
SelectBestEligiblePokemonInInventory, TryGetDisplayPokemonForContest; ContestRpcService.GetContestData/GetEnteredContests.
