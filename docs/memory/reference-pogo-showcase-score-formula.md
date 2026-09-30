---
name: reference-pogo-showcase-score-formula
description: "The in-game / Pokemod showcase POINTS formula (800/150/50 + 178 XXL bonus, height normalised by the XXL upper bound) -- reproduces the on-screen \"1004-1008 PTS\" exactly."
metadata:
  node_type: memory
  type: reference
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-25T07:10:36.830Z
---

Extracted 2026-09-23 from Pokemod's agent (`showcaseScoreMath` / `U0` in
`pogo_extract/system/analysis/pokemod/fresh_20260908/agent_game_20260908.js`), verified against his screen
(Alolan Ninetales XXL 1.893 m / 34.65 kg / 32 IV -> "SHOWCASE: 1004-1008 PTS"):

    n = XxlUpperBound / pokedexHeightM        (PER SPECIES/FORM from the client's EXTENDED_V####_POKEMON_<FORM>
                                              pokemonExtendedSettings.sizeSettings: 1.75x most, 1.55x many, 2.0x some -- NOT a constant)
    c = (height / pokedexHeightM) / n
    u = (weight / pokedexWeightKg) / (0.5 + n)
    d = IV_total / 45
    points = trunc(800*c + 150*u + 50*d + (178 if size badge is XXL else 0))

The min-max on screen is the +/-0.005 display rounding of height and weight, clamped to the size band. The
template is the FORM's own (a Gourgeist Super uses GOURGEIST_SUPER's 1.7 m and its XxlUpperBound 1.7 -> n=1).
Proto fields: ContestScoreCoefficientProto/Types/PokemonSize {HeightCoefficient, WeightCoefficient, IvCoefficient,
XxlAdjustmentFactor}. Verified on TWO screens: Alolan Ninetales (n=2.0) 1004-1008 and Arboliva (n=1.75) 1039-1042.
Every XXL he owns scores 886-1144 (median 1069).

**Rule 7 since 2026-09-23 21:03 (his words, in order):** "XXL tags to go to the 2 highest showcase scores" -> "just per
species regardless of costume and other cosmetics" -> "they should only be tagged if they're actually XXL" -> "i only
want to track actual winners ... keep pokemon that score over 1000". So: XXL badge, per PvP identity (cosmetics fold),
points >= keep_config showcase_weights.min_points (955 since 21:1x; 1000 then 945 earlier), top caps.xxl (2). Tag `XXL` (278 members; the any-size
"Showcase" tag lived one pass and is deleted). full_audit prints "XXL showcase top-2 CHANGED +n/-m" every cull.
Counts on the same bag: old per-form XXL rule 289 | per-species XXL 286 | any-size top-2 1,988 | >=945: 278 | >=1000: 252 | >=1050: 187.

**Cut raised to 999 on 2026-09-24** ("Make the cut for XXL 999"): XXL tag 280 -> 259. **Then 1050 the same night** (cull-more round: "6. ok").

**Re-read from the GAME every pass since 2026-09-24** ("5 should be done everytime"): the coefficients live in the
client game master `CONTEST_SETTINGS.contestSettings.contestScoreCoefficient[].pokemonSize` (heightCoefficient 800,
weightCoefficient 150, ivCoefficient 50, xxlAdjustmentFactor 1.0 -- the +178 is Pokemod's, NOT in the GM) and the
bounds in each form's `EXTENDED_` `pokemonExtendedSettings.sizeSettings`. `pogo_pipeline.step_read_showcase_gm`
reads ContestSettingsProto out of GameMasterData's `Dictionary<System.Type, IMessage>` (GetByKey / MaybeGetByKey are
GENERIC on 0.429.1, so runtime_invoke can't call them -- the live read silently failed every pass 09-24 -> 09-25 03:10
until this; the AutoCatcher's tools/dump_game_limits.py found the dictionary), invokes `Get_PokemonExtendedSettings(pid, form).SizeSettings` and
`Get_PokemonSettings(pid, form)` (methods resolved by name + parameter types, fields at live offsets) for every
(species, form) in the bag -> `system/analysis/showcase_gm_live.json`; `size_line` scores by the live numbers (they
beat gamemaster_pokeminers.json); `full_audit.showcase_formula_step` prints one line per pass and STOPS the pass
(rc 7) on a coefficient / xxl-adjustment / CONTEST_SETTINGS-shape change; `game_news_step` announces a Pokemod
version change (re-match the formula on a screen then). Client protos already carry `ContestScoreFormulas`,
`IsNormalizedScoreToSpecies`, `IsPokemonScalarEnabled` -- the shape diff is what will catch Niantic switching them on.

**XXL KEEP = BEST REACHABLE STAGE (2026-09-24, "evolution should be considered everywhere"):** rule 7 and every mirror
rank/gate by `size_line.best_points(r)` = max(own points, projected points at every `later_stages(r)` -- keep_policy
pvp_later_stages over the ONE graph, minus branches `evolvable_forms.can_reach` denies, e.g. Scyther->Kleavor). Found
because an XXL Rhydon at 1005 (1104 as Rhyperior) was kept only by its IV slot; first replay added Rhydon, Electrike,
Yanma to XXL, pile unchanged. build_tagsets now reads `SELECT *` (its narrowed rows had no `gender` -> crash).
`Evolve for Size` (sync_evolve_size.picks) now needs score_after >= min_points AND not in the pile -- it had tagged a
1030 Exeggcute + 1008 Cubone that were also in Transfer, and a 1113 Dusclops -> 1014 Dusknoir.

**"Showcase scores trump all" (user 2026-09-24):** XXL keepers are ranked by total points only -- never add an IV
floor/tiebreak on the XXL axis; he combs their IV up by catching bigger AND better copies (XXL keepers average 61% IV
vs 81% bag-wide, because IV is 50 of ~1000 points).

**How to apply:** `size_line.showcase_points(r)` is the one own-stage implementation (`best_points` wraps it); keep_policy rule 7, build_tagsets,
preflight_transfer, studio_data and showcase_plan all rank/report with it. Constants live in
keep_config showcase_weights (+ xxl_bonus, xxl_upper_factor) as the FALLBACK; the live file wins when present. See [[pogo-special-backgrounds-capped]],
[[reference-pokemod-overlay-rank-mechanics]].
