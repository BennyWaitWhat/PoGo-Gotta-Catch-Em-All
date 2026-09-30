---
name: feedback-pogo-collection-vision-2026-09-13
description: "The user's stated collection vision (2026-09-13): every axis climbs the same IV ladder (shinies too), the ideal line is a hundo at every stage, a 3-star legendary is never fodder by count, CP tie-breaks are fine, and Dynamax CAN be traded (my claim that it cannot was wrong)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-21T03:31:17.904Z
---

> Later decisions refine this: read [[feedback-pogo-collection-vision-2026-09-17-decisions]] second.

On 2026-09-13 the user said "I don't think you understand my vision totally" and had me guess the gaps. His answers:

1. **CP as an IV tie-break is fine** ("nope" to my guess that CP must never decide). Keep `topn` as is.
2. **"shinies should be combed up by IV......wtf."** Shinies climb the same ladder as plains (2026-09-17 "shiny
   ladder like plains"): every qualifying spare (never a stage's best/only shiny) is flagged Evolve Shiny when the
   next stage has an open spot under the shiny cap or the spare beats the weakest of a full top-N, candy
   best-first, bar raised on each tag (the Corvisquire-stacking guard). Implemented in
   `refresh_evolve_shiny.compute_target`.
3. **A 3-star legendary is never fodder just because he has more** ("ok"). `keep_config.rarity_floor_iv` = 37
   (in-game 3-star line); keep_policy rule 5 + audit_cull + _spotdata mirror it. Measured: +8 protected.
4. **Dynamax and Gigantamax CAN be traded.** I claimed they cannot and he doubted it; Niantic's help centre
   confirms they trade normally (not a special trade, Max Move levels reset). Never repeat the claim.
5. **The ideal line is a hundo at EVERY stage** ("if i have 3 hundos, one for each stage"), so a stage is a
   collection slot, not just a stepping stone. To "should the best copy of a middle stage move up" he said
   "yes kinda": implemented as promote-last, finals only, and only when another copy of that stage stays
   un-promoted (a stage is never emptied). Base stages keep their best.

**Why:** the whole method is one upward ladder by IV on every axis, with the labels as the instructions for
spending candy; every intermediate state the user can create by following a label must still hold.
**How to apply:** when a rule is added or a cap changes, ask which axis it climbs and whether the promised
outcome survives after the user acts on it. Related: [[pogo-combup-bar-ignored-displacement-2026-09-13]],
[[feedback-labels-true-for-the-mon-on-screen]], [[pogo-capped-vs-keepall-bug-class]].

**"Are you truly listening to me when I say Comb up?" (same evening, after 104 catches and only 64 culled).** COMB UP
means: a stage holds the best N you own, promised-to-evolve or not; a copy ENTERS only by beating one of them or by
improving a later stage; the worse one leaves when the better arrives. Two things violated it: (1) my 18:07
"backfill" (re-rank residents over non-promised copies) let weak fresh catches into stages that already held better
copies (Fletchling 84%/82% beside three 97%s promised to Talonflame) -- REMOVED; (2) my "no weak fillers" / 3-star
floor for ordinary plains was a quality gate, not comb-up -- withdrawn. Do not propose IV gates for ordinary
plains; propose only comb-up-shaped rules (better replaces worse) or explicit caps.

**Per-cull improvement report (user 2026-09-13: "see how my collection improved after each cull to see if the right
mindset is still growing").** `ladder_report.py` runs at the end of every full_audit pass and appends to
system/analysis/ladder_history.json: stages with a hundo, resident mean IV, best-copy-per-stage mean IV, shiny mean
IV and 3-star shiny stages, open Evolve promises, and since the previous walk (newest-but-one .db_snapshots
before_sync gzip): evolved / promises kept vs broken / released / caught, pile = pushed-out + fresh + leftover.
Quote its block after each pass. PvP validation he asked for ("trace everything and validate", incl. pre-evos that
reach a rank by evolving): chain ranks -> viable stages -> keep + Evo/own-stage rank tags, checked independently of
granular_tags; 90 mons with a viable stage <=5, zero mismatches.

**2026-09-16 "I also thought pichus were protected....so you fucked up twice."** A PROTECTED keep-all species
(keep_config.protected_keep_all_pids, accessor `protected_pids()`) means keep EVERY copy as it is -- it must never
carry an Evolve / Evolve Shiny label (evolving consumes the protected copy). Two protected Pichus were told to
evolve; both Pikachus were culled (second cause: the costume-form stage-key bug). Fixed in `_evo_ok`,
`refresh_evolve_shiny` and `_evocheck.can_evo`. Rule: every keep-all axis (protected, rarity keep-all, AE form,
dex-only copy) must be checked against every ADVISORY label that asks the user to consume the copy.

**2026-09-16 "why are you evolving special background pokemon? ... is that because I already have 3 to spare?"** Four
of six card-19 Charmanders (all within the card cap 6, all kept) carried Evolve labels because card copies sit in the
plain pool. A copy kept as a COLLECTIBLE is never advised to evolve: location_card, xxl, legacy (moves reroll on
evolution), dex_only_copy, mighty, protected, and an OWN-stage PvP asset (gl/ul_stage == own sid, rank <= READY_RANK,
viable). Only SURPLUS copies climb; a surplus card copy is judged against the target's card slots first
(`_earns_slot`, rule-13 cap). Measured: 8 labels withdrawn (4 legacy, 2 xxl, 1 card, 1 own-stage PvP), pile unchanged.

**2026-09-16 "/ponytail Fix everything. I don't think you see the full picture."** The picture, now written once as
`pogo_extract/LAW.md`: every copy belongs to ONE bucket (trophies; PvP assets; legendaries; shiny; special
background; costume/Max; shadow; XXL; plain), each bucket has its own cap and its own ladder, and a label may only
ever sit on a copy its bucket is willing to give up (a surplus). `audit_labels.py` runs in every pass and BLOCKS the
sync if any Evolve / Evolve Shiny label breaks that (trophy, protected, legendary, collectible, shadow, legacy,
last copy, own-stage PvP asset, shiny with a plain-ladder label). Update LAW.md first whenever he corrects a rule.

**2026-09-16 "find a better comprehensive way to see if pokemon are evolvable ... some costume ones can evolve, find
the distinctions."** A shiny PsyduckSwim2025 (form 3019) carried Evolve Shiny; the form cannot evolve. Source of
truth = the real game master (gamemaster_pokeminers.json): `pokemonSettings.evolutionBranch` with an `evolution`
target (a temporaryEvolution-only branch is a Mega); `evolutionIds` lies. `evolvable_forms.py` maps the live Form
enum name -> bool (1447 forms, 912 locked; 8 of 97 costume forms evolve). Used by keep_policy._can_evo,
refresh_evolve_shiny, _evocheck.can_evo and audit_labels. The costume Noevolve lock comes from the game master (allowNoevolveEvolution exceptions); no name-only heuristic remains.

**2026-09-17 split lines.** The client game master's `evolutionBranch` says HOW each branch is reached: no fields =
plain candy tap (several such = random: Wurmple, Toxel, Eevee's Vaporeon/Jolteon/Flareon); `questDisplay` = an
evolution TASK the player picks (Charcadet -> Armarouge/Ceruledge, Galarian Slowpoke -> Slowbro/Slowking);
`evolutionItemRequirement`, `lureItemRequirement`, `mustBeBuddy`+`kmBuddyDistanceRequirement`, `onlyDaytime`/
`onlyNighttime`, `genderRequirement`. "Evolve Next" cannot name a branch, so `keep_policy._promise_targets` (one
helper for both promise sites) promises a line with more than one promisable final only when EVERY final has room
and commits to all; _evocheck and refresh_evolve_shiny mirror it; espeon/umbreon joined ITEM_GATED_TARGETS.
Replaced the Wurmple-only constant, which also fell through to single-target promises. Measured: 5 labels withdrawn
(Charcadet 84/82, Scyther 82, Galarian Slowpoke 51, Toxel 88), 3 beyond-cap extras to the pile.

**2026-09-17 process review ("Something seems off").** Fixed: Evolve Shiny now excludes shinies kept as collectibles /
trophies / shadows (73 were eligible; audit_labels enforces it); ladder_report names broken promises, reports
"moved by a rule change" instead of "pushed out by better" when no new copy arrived, and lists pile mons not released
for a day+ (Ledian 40% since 09-13). RESOLVED 2026-09-17: favorites are a keep axis, candy is read every walk,
nicknames cleared, shiny ladder fills top-N and beyond-cap shinies are held (`shiny_ladder`); mega level stays a
non-axis. See [[feedback-pogo-collection-vision-2026-09-17-decisions]]. DB lock columns are unreliable: is_best_buddy=1 on 549, has_pokemon_contest_info=1 on 1153.

**UPDATE 2026-09-23 (user):** the "every 3-star legendary is kept" floor is GONE ("Remove the 3 star thing") -- keep_config rarity_floor_iv=46 (off); legendaries are top-6 per variant + Best GL/UL/ML only. Pikachu costume cap 6 -> 4; location cards 6 -> 5 per card. Caps stay in keep_config.json.

**2026-09-24 late:** shiny floor added -- a PLAIN shiny under 18/45 (40%) takes no plain-shiny slot unless it is its form's best shiny or best plain shiny ("only the absolute shitty ones"; "do not cull my only shinies" -> 0 of 742 shiny forms lose their last shiny, verified). XXL cut 1050. Location cards 3. See [[feedback-never-repropose-plain-shiny-cap]].
