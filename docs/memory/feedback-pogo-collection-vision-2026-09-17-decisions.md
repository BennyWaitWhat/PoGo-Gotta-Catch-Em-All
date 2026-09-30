---
name: feedback-pogo-collection-vision-2026-09-17-decisions
description: User decisions 2026-09-17 after the process review -- favorites are a keep axis (read live), mega level does not matter, old generated nicknames cleared, candy read every walk; candy/items decide only whether to ADVISE an evolution (an earned-but-unaffordable copy is held, never piled)
metadata:
  type: feedback
---

> **CAP NUMBERS HERE ARE HISTORY, NOT CONFIGURATION.** Caps live in `keep_config.json`, except the middle-stage cap
> (`plain_line_preevo` = 2, MIDDLE stages only), a hard-coded `keep_config.py` DEFAULT.
> The figures in this file were true when written and several have since moved (checked 2026-09-20). Read the
> config before quoting any of them; see [[project-keep-config-dashboard]].

> These sit on top of the vision in [[feedback-pogo-collection-vision-2026-09-13]]; that file is the base statement.

Answers to the 5-point process review (2026-09-17):
1. Ledian 40% leftover: user released it ("my bad").
2. **Mega level: "doesnt matter"** -- never propose it as a keep axis again.
3. **Favorites: "keep em"** -- keep_policy reason `favorite`, pre-flight axis, native-covered (the star is the label),
   declared in audit_invariants AXES/MARK_MODEL. `favorite_`@0xb0 is now parsed LIVE every walk (the old column was a
   retired one-off: said 88, live is 17). nickname_@0xb8 is parsed live too.
4. **Old nicknames: "clear"** -- `clear_nicknames.py clear --auto-only` cleared 378 "<species>VF#/100" names (incl.
   35 on evolved mons carrying the pre-evo name). The other 248 generated-looking names ("Species N", "SnorlaVF1XXL",
   "Lugia GL UL", "Kangaskhan1O") -> user: "full reset is cool" -> `clear_nicknames.py clear` removed ALL of them
   (02:13, re-walk found 0 custom nicknames; 626 clears in ~10 min, under the ~1000 burst). If names reappear after a
   server re-sync the throttle rolled some back: rerun the same command.
5. **Candy: "read candy always so you can get better recommending stuff and improving my collection when sorting
   thru my catches."** `pogo_pipeline.step_read_candy` (InventoryCache dict walk, same session) -> candy.json each
   walk; `evolvable_forms.step_cost/path_cost/family/candy_now` from the client game master. keep_policy spends candy
   best-first (Evolve Shiny first via refresh_evolve_shiny.compute_target(why, spent), then the pooled advisory, then
   the comb-up), and _evocheck mirrors that spending; candy/items decide only whether to ADVISE an evolution -- an
   earned-but-unaffordable copy is held as variant_floor stock, never piled (2026-09-20). _evocheck was NOT updated
   for the hold or the open-slot rescue (its pile gate still requires afford, and improves() has no `_rescue`), so it
   cannot flag a piled earned-but-unpaid or rescue-eligible copy. candy_short.json -> ladder report "held back for
   candy". History: on its first run the 2026-09-17 version piled 5 beyond-cap copies only for being candy-short
   (Wailmer 82% needs 400 / has 74, Roggenrola 80/77 need 50 / has 41, Carkol 46/44); all five have left the bag
   (pokemon.db, 2026-09-21). The 2026-09-20 hold ended that behavior.
Why: labels must be actionable and true for the mon on screen. How to apply: any new advisory must use the candy
budget; never re-ask about mega level.

**"cull again and make sure you dont make me evolve pokemon for no reason" (2026-09-17 02:20).** Measured with a new
sandbox proof (`audit_promises.py`: evolves EVERY labelled mon at once, once per branch, reruns the real engine) --
all 87 promises held, but 80 of 85 only filled a spare plain slot, many under a hundo. Rule added in
`keep_policy._earns_slot` (mirrored in _evocheck.improves, enforced by audit_promises): an evolution must add the
first plain copy of that stage, a new best, or push a weaker copy out of a FULL top-N; a stage holding a plain hundo is
complete. Since 2026-09-20 ([[feedback-evolve-into-open-slot-beats-release]]) a copy with no keep reason besides
evolve_* may be evolved into an OPEN slot even beneath better copies (`_earns_slot` `_rescue`). A target stage that
already holds a plain hundo is still complete, and a full stage still needs a strictly higher IV, so e.g. the Rhydon
95/91 under a hundo Rhyperior still goes to the pile. Evolve_Twice can now be legitimately
EMPTY (audit_cull/audit_tags_membership accept an empty Evolve file only when no mon carries that reason). prune's
locked-mon deferral capped at 3 per tag (a big push produced dozens of cache-lag "deferred" members).

**Rollback observed (02:27):** after the 626-name reset, the next walk found 21 names back ("Venusaur VF1",
"Gyarados 9") -- server throttle rollback. Re-cleared at `--delay 1.5` (re-walk: 0 left). Every cull reads nicknames
live now, so check the count after each pass for a day and re-clear any that return.

**02:36 "shiny ladder like plains" -> "1 yes".** refresh_evolve_shiny.compute_target: a spare shiny is tagged when it
earns a shiny spot at the next stage (open spot under species_cap('shiny') or beats the weakest of the full top-N),
every qualifying spare (no one-per-stage), split lines need every branch, candy best-first; keep_policy marks targets
`shiny_ladder` (NOT 'evolve_*' -- many consumers treat startswith('evolve_') as Evolve Next/Twice; the first name broke
the label audit), native-covered, declared in audit_invariants, pre-flight axis. Evolve Shiny 2 -> 127 on the phone.
Also fixed: refresh_evolve_shiny imported pogo_il2cpp/tag_ops at module level, whose stdout.reconfigure crashed any
sandboxed engine run (regress_pvp_keepers would have failed the next cull) -- device imports moved into main().
**Trim menu measured with the real engine in a sandbox (bag 5611):** plain 3->2 base+final 260 (199 are 3-star+),
middle 2->1 63 (48 3-star+), XXL 2->1 39, legacy top-5/species 22 (Lickitung 19, none 3-star), costume 3->2 18,
shiny 10->6 17 (none 3-star, best 80%), Lickitung legacy 10 14, background 6->3 11, Dynamax 3->2 11, Gmax 8->4 7,
legendary 8->5 6, shiny 10->8 5, background 6->4 3, shadow 2->1 0. Script: scratchpad measure_trims.py pattern
(keep_config.CFG override + regress_pvp_keepers.build_sandbox/run_engine).

**02:49 trim decisions** (answering the measured menu row by row): legacy-move copies "Best 10" -> keep_config
legacy_default_cap 10 (Absol's 10 unchanged); shinies "bump down to 8" -> caps.shiny 8 (per-species overrides
Gyarados 20, Houndour 10, Combee 10 untouched); XXL, middle 2, base/final 3, costumes, backgrounds, Dynamax, Gmax,
legendaries, shadows: KEEP as is. Pile 19: 14 Lickitung 20-57%, shiny Dhelmise 17/31, shiny Gible 71/75, shiny
Pikipek 28. Fix needed on the way: the Legacy Moves TAG was built from the (now capped) keep reason, so 33 kept legacy
movers lost the label -> granular_tags.build now tags every kept uid in legacy_accurate.json (a fact, not a reason).

**PvP must always be checked, and visibly (02:55, "it should always be checked....thats happening right?").** Every cull:
ranks recomputed in the walk (pogo_pipeline compute_ranks_legacy -> rank_cache, all 4096 spreads per stage/league);
keep_policy 15b keeps any mon ranked 1-5 at a stage that reaches the GL/UL cap (15c: unknown rank = kept); the
pre-flight re-checks every pile mon's headline AND every chain stage; regress_pvp_keepers guards 19 fixtures. Added a
ladder_report line so it shows in every cull: "PvP check on the pile: N checked, none in any top 5 (closest: ...)".
Always quote that line when reporting a pile.

**03:08 usefulness audit + "one nundo. keep the most exotic places not in the US ones if you had to pick".** Audit of
all 5592 kept found little truly useless: 73 duplicate plain hundos (same species/form/look, no other reason; user did
NOT take `one hundo per look` -- hundos stay keep-all), 3 duplicate nundos (taken). New `trophy_pick.py`: look =
species, form, shiny, alignment, costume, costume form, Max, card, art bg, XXL, lucky; keeper = caught outside the US
first (farther from NYC in 100 km steps = more exotic), then unknown place, then US; ties by level/CP; keep_config
caps.nundo = 1. Engine rule 8 + tripwire, pre-flight, audit_cull, audit_tags_membership (Nundo tag minus pile),
audit_invariants (nundo axis now capped, cap_key nundo) all use it. Pile 3: Magnemite L11 San Francisco (kept the
Mumbai one), Yanma L7 NYC (kept the unknown-location one), Rookidee L4 Osaka (kept the L24 from the same city).

**03:18 "read everything".** pogo_pipeline.step_read_candy now reads the whole inventory every walk into
system/analysis/inventory.json (+ candy.json): stardust + coins (IapService.get_Stardusts/get_Coins, runtime invoke),
every item by live enum name (ItemProto field is `Item` -- PascalCase on 0.427.0, the old `item_` guess returned
nothing), candy + XL per family, player stats (PlayerStatsProto scalars: Level 78, XP, km, raids ...). Validated JS
lives in read_inventory.INVENTORY_EXTRA_JS. MEGA ENERGY NOT FOUND: PokemonFamilyProto.MegaEvolutionResources
(RepeatedField @0x18, element TemporaryEvolutionId@0x10/EnergyCount@0x14) is EMPTY for every family on this build
-- energy lives elsewhere; not pursued (user: mega level "doesnt matter"). Ladder shows "inventory: stardust | coins |
Rare Candy | Rare XL Candy | player level". First read: stardust 5,956,762, Rare Candy 42, Rare XL Candy 3.
Max-out recs use it: power-up costs from client GM POKEMON_UPGRADE_SETTINGS (per level x2, candy L1-39, XL L40-49,
shadow x1.2, purified x0.9, lucky dust x0.5, per-species overrides e.g. Eternatus).

An equal-IV evolution is NOT an upgrade (2026-09-17, "you made me evolve those though"): keep_policy._earns_slot let
an arrival whose IV EQUALS the copy it displaces earn the slot on the CP tie-break, so a 95% Linoone was labelled
Evolve beside a 95%/cp595 Obstagoon -- he spent candy, gained a 95%/cp1131, and the old 95% went to the pile. The
ladder did not move. Fixed: on a FULL stage the arrival must beat the copy it pushes out on IV strictly (_evocheck's
`i > bar` had always been strict; the engine was the outlier). LAW.md says "weaker means a LOWER IV". CP stays the
tie-break for WHICH copy to keep -- it is never a reason to evolve. See [[pogo-capped-vs-keepall-bug-class]].

Evolution ITEMS gate the advice too (2026-09-17, "it can evolve, i just dont have the stone to do it"): the branch's
`evolutionItemRequirement` is in the client game master, so `evolvable_forms.step_item/path_items/items_now` read it
and keep_policy._afford now needs the STONE in stock as well as the candy; _spend consumes it (one stone, one
promise) and the ladder report prints "waiting on a <Sun Stone/Unova Stone/...> (you have 0)". His Unova Stones are
0, which is why the costume Minccino cannot evolve -- the Evo UL Rank tag on it is CORRECT (he confirmed the form
can evolve; costume-by-field mons are now judged by evolvable_forms.costume_can_evolve -- a non-Noevolve
costume such as this Minccino evolves).

The gated-evolution list is now DERIVED, not hand-written (2026-09-17 "Fix everything"). evolvable_forms.gated_targets()
reads _GATE_KEYS (evolutionItemRequirement, lureItemRequirement, questDisplay, kmBuddyDistanceRequirement, mustBeBuddy,
onlyDaytime/Nighttime, onlyUpsideDown -- NOT noCandyCostViaTrade, which is a discount) and keep_policy UNIONs it into
ITEM_GATED_TARGETS. Key BOTH `evolution` and its branch `form` minus a trailing _normal, or STEELIX_NORMAL never
matches pvpoke's 'steelix' (that bug silently dropped 38 item evolutions). Three hand-list names were REMOVED after
checking the game master branch by branch: floette, accelgor, escavalier are plain candy evolutions. huntail/gorebyss
stay -- Clamperl is a RANDOM tap and a label cannot name the branch. refresh_evolve_shiny no longer skips gated targets
blindly: it TAGS one whose only obstacle is an item in the bag (and spends it, sharing the ledger with keep_policy via
items_spent), and RECORDS the rest to system/analysis/shiny_gated.json so the ladder report says what each needs.
Evolve Shiny went 5 -> 21 real suggestions. ladder_report now reconfigures stdout to utf-8: a Flabebe in a report line
was silently killing the whole block on a cp1252 pipe, and its except now PRINTS instead of passing.

Game-master sweep (2026-09-17 "Learn more about what the game has for info and be comprehensive"). The client game
master (gamemaster_pokeminers.json) now drives: costume NOEVOLVE rule + allowNoevolveEvolution exceptions
(evolvable_forms.costume_can_evolve; the shiny path had its own copy that ignored the exceptions -- removed),
gendered evolution FORMS (female Lechonk -> oinkologne_female; pvpoke's family lists 'oinkologne' twice),
evolutionItemRequirementCost (999 Gimmighoul coins), onlyFullMoon/onlyDuskPeriod/evolutionMoveRequirement gates,
evolutionQuestTemplate goals rendered as text (gate_text), legacy = union of pvpoke AND "no form of the species can roll
it" per the real movepools (+31 mons; numeric move ids in the gm are named via move_id_to_name.json), and move names
590/592/593/594/595 (Glaive Rush, Snipe Shot, Dive, Gulp Missile x2) from the gm's V0xxx_MOVE_* templateIds -- which
removed the UNKNOWN_MOVE safety net from 2 surplus Cramorants (they correctly went to the pile). New: audit_gamemaster.py
(one of the 10 audits in full_audit.AUDITS, #7: rarity classes vs references.py, one-gender branches vs GENDER_TERMINALS, isTransferable vs the pile,
unnamed move ids) and game_opportunities.py (purify-to-hundo where the stage has none; PvP #1-5 with no second charged
move + the thirdMove price) printed by ladder_report. Verified clean: pokemonClass matches references (the 6 extra
game "legendaries" are the Paradox ones), 0 non-transferable mons in the bag, gender families complete.
Git-Bash heredocs mangle long patches with quotes/backslashes -- write patch scripts with the Write tool instead.

Shadows are valued AS shadows (2026-09-17, "you should check to see which hundos i already have" / "hundo shadows are
really nice. so check pvp ivs and stuff too. dont be stupid."). I suggested purifying a 97% Cacnea (his ONLY Cacnea), his
only Alolan Ninetales shadow and his only Wartortle because each would purify to 15/15/15 -- all three were the stage's
best shadow. Rule now in game_opportunities.purify_to_hundo: suggest only a SURPLUS shadow (none of _KEEP_AS_IS:
shadow_best, dex_only_copy, legacy, PvP axes, collectibles ...), not ranked 1-100 in a league its stage can enter, at a
stage with no hundo of ANY alignment (a shadow hundo counts as having that hundo). Today that list is empty (15 of the 18
would-be hundos sit at stages that already have one, 3 are best shadows). Before any "use up X to get Y" advice, check
what X is to him first -- its keep reasons, its PvP ranks, and whether he already owns Y.

ladder_report was blind to promises (fixed 2026-09-18): it matched evolutions against hist[-1] -- the entry the SAME
pass (or my manual re-run) had just written, i.e. labels taken AFTER he evolved -- so it printed "promises kept 0,
broken 0" forever. Entries now carry `walk` (the before_sync snapshot stamp they describe); the comparison uses the
entry of the PREVIOUS walk; re-reporting the same walk replaces its entry instead of stacking another. Same file: the
pile classifier keyed arrivals by (species_name, raw form), so an evolved Hattrem stored with form 0 did not match its
Normal-form (3191) sibling and the one it pushed out read as "moved by a rule change" -- now keyed by pvid (stage).
Also: before calling a cap "doubled", print bread mode -- two "extra" plain Hatennas were Dynamax (their own bucket).

Currency read (2026-09-19): IapService had no multi-instance probe, so after a game restart pick_singleton took a stale
instance and the walk wrote stardust 0 / coins 0 as the balance (he held ~5.4M). Now: _pick_singleton_live probes
IapService (largest get_Stardusts wins), pick_singleton(fresh=True) bypasses the per-pid cache, pogo_pipeline re-picks
once on a 0-and-0 read and otherwise records None + `currency_last_good`; ladder_report prints "unknown this walk (last
read X at T)"; game_opportunities falls back to the last good read. Verified on the 2026-09-20 22:03 walk, after a
21:41 game restart: stardust 5,515,371 / coins 262 (currency_last_good current). General rule: an unreadable
value is None, never 0.

"The whole point of culling after catches is to comb up and improve our collection" (2026-09-19). So the report must
SHOW the improvement: ladder_report now prints `combed up at N stage(s): Species old%->new%` for every copy the pass
pushed out, naming the better arrival that replaced it. Same pass fixed the third form-keying bug in that file: the
"stage best beaten" list keyed prev_best by (species_name, raw form), so a form-0 arrival compared against a record
that did not exist and it claimed records at Fidough/Luvdisc/Rockruff where nothing improved (1 real: Nuzleaf 82->88).
Rule: in ladder_report, ALWAYS key a stage by pvid(species, form), never by the raw form id.
Location cards/backgrounds are current (checked 2026-09-19): 420 names in location_card_enum.json, 66 distinct ids on
306 mons, ZERO unnamed ids held -- including LcSpecialbackground202610ThAnniversary001, LcSpecialbackgroundS24Sep2026
and LcSpecialbackgroundGg2026. The in-walk name refresh is working; check "unnamed ids held" to answer that question.

CAPS ARE MULTIPLES OF 3 OR 6 (user 2026-09-19: "I want them to be multiples of 3 or 6" -> "round down except for the
shadow and xxl" -> "except pikachu, keep at 6"). Applied and synced: shiny 8->6, rarity/legendary 8->6, gigantamax
8->6, legacy_default_cap 10->9 (and legacy_species_caps 359 -> 9), per_species shiny Gyarados 20->18, Houndour 10->9,
Combee 10->9; shadow 2->3 and XXL 2->3 (rounded UP -- his exception); Pikachu cosmetic stays 6. Unchanged and still
off-grid ON PURPOSE: plain_line_preevo 2 (his "middles capped at 2") and nundo 1 ("one nundo") -- he dismissed the
question, so leave them. caps.xxs is inert: rules.xxs is FALSE, nothing is kept for being small ("We're not doing XXS
only XXL"); 0 mons carry an xxs reason. Cost measured before applying: +26 tagged (17 shinies, 4 shadow legendaries,
Rayquaza/Reshiram/Giratina, a Gmax Machamp 86%, a 60% Lickitung). Legendary keeps two guards on top of the 6: anything
>= rarity_floor_iv (37/45) stays, and the best GL and best UL copy per species+form stays.
