# KEEP-Policy Dry-Run (READ-ONLY, no device)

_Generated 2026-05-29. Source of truth: per-rule protected sets in
`system/analysis/policy_sets/*.txt` (universe = `_in_bag.txt`), joined against
`pokemon.db` (`cull_decision_v9`, `species_name`). Nothing was written to the DB
or the device._

## Method

- **Universe** = `_in_bag.txt` = 4766 uid_hex (verified identical to the DB
  `in_bag=1` set — symmetric difference 0, every id resolves in the DB).
- **KEEP** = union of all 15 rule files (every rule member is inside the
  universe — 0 orphans).
- **TRANSFER** = universe − KEEP.
- `KEEP ∪ TRANSFER == in_bag` and `KEEP ∩ TRANSFER == ∅` both hold.

## Totals

| Metric | Count |
|---|--:|
| **in_bag** (universe) | **4766** |
| **KEEP** (union of rules) | **4331** |
| **TRANSFER** (in_bag − KEEP) | **435** |

Of the 4331 kept, 4276 were already `cull_v9=KEEP` and **55 are newly rescued**.
Of the 435 transferred, 195 were already `cull_v9=TRANSFER` and **240 are newly
trimmed**. (The file-universe contains no NULL/TRASH cull rows — every in-bag mon
is either KEEP or TRANSFER under v9: 4516 KEEP / 250 TRANSFER.)

## Per-rule protection

`<rule>: <protects> (<protects ALONE — drop this rule and the mon is unprotected>)`

| Rule | Protects | Unique-only |
|---|--:|--:|
| variant_floor | 2883 | **1668** |
| shiny | 1031 | **886** |
| hundo | 579 | 3 |
| rarity | 392 | 61 |
| dex_completeness | 387 | 0 |
| legacy | 199 | 15 |
| shadow | 181 | 155 |
| adventure_effect | 127 | 21 |
| xxl | 130 | 37 |
| location_card | 107 | 28 |
| nundo | 27 | 18 |
| origin | 23 | 3 |
| best_buddy | 17 | 0 |
| gl_ul_meta | 9 | 3 |
| mighty | 1 | 0 |

Read-out:
- **variant_floor** (trade-stock floor, top-3 per pid/form/costume, +1 for gmax)
  and **shiny** are the policy's backbone — together they account for 2554 of the
  4331 keeps via uniqueness alone.
- **dex_completeness (0 unique)**, **best_buddy (0)**, **mighty (0)** add nothing
  that another rule wasn't already protecting — they are pure safety-nets here.
  (mighty.txt has a single member, fully covered elsewhere.)
- **shadow (155 unique)** and **variant_floor (1668 unique)** are where most of
  the standalone protection lives — if you ever drop a rule, those two move the
  needle most.

## What actually changes vs. cull_v9

### newly_trimmed = 240 (was `cull_v9=KEEP`, now TRANSFER) — the real "what changes"

This is the meaningful column: 240 mons the *current* engine protects would be
released under the new union-of-rules policy. **118 of the 240 carry a "notable"
flag**, which is the headline risk:

| Flag on a newly-trimmed mon | Count |
|---|--:|
| BEST BUDDY | 59 |
| LEGENDARY | 38 |
| SHINY | 34 |
| XXL | 1 |

Old `cull_reason_v9` of the newly-trimmed (top reasons): `bread_2` 26, `bread_1`
25, `shiny_protected_chain` 18, `legendary` 12, `shadow;legendary` 11,
`best_buddy` 9, `best_buddy;purified` 8, `current_mega_evolved;has_mega_level` 8,
`ul_top2_pvp` 7, `legacy_move` 6, `final_top3_rank3` 6, `costume_*` 12,
`full_protect_species` 5.

So the categories the new policy stops blanket-protecting (relative to v9) are:
**Dynamax/GMax (`bread_1/2`, ~51), surplus shinies (~34 beyond the per-group cap),
surplus legendaries (~38 beyond top-6), best-buddy (the BB safety-net only keeps
17 of 607), megas, costumes, and PvP-rank picks** that don't independently clear
a rarity/variant/shiny floor.

#### newly_trimmed — top 15 species

| Species | Count |
|---|--:|
| Gyarados | 25 |
| Eevee | 17 |
| Unown | 14 |
| Gengar | 7 |
| Charizard | 7 |
| Blastoise | 6 |
| Cottonee | 6 |
| Mimikyu | 5 |
| Machamp | 5 |
| Venusaur | 5 |
| Articuno | 4 |
| Lapras | 4 |
| Rillaboom | 4 |
| Pikachu | 3 |
| Ampharos | 3 |

Gyarados (25) and Eevee (17) dominate because they are deep dupe stacks — once
the variant_floor keeps the best 3 and shiny keeps the per-group shiny picks, the
overflow (including shiny/BB overflow) falls through. Unown (14) is the inverse:
those are *rescued* by variant_floor, see below — but the surplus Unown forms
beyond cap also appear on the trimmed side.

### newly_kept = 55 (was `cull_v9=TRANSFER`, now KEEP)

All 55 are rescued by **variant_floor** (the trade-stock floor keeps top-3 per
variant even when v9 had marked the mon transfer). Top species: Unown 13,
Joltik 2, then 40 singletons (Drilbur, Rattata, Venusaur, Gulpin, Larvitar,
Sinistea, Spearow, Cubchoo, Mankey, Venonat, Mareep, Skwovet, Meowth, …). These
are low-stakes — mostly first/second copies of a variant the floor now guarantees.

## Concerns flagged by the rule agents (and this dry-run)

1. **Shiny rule is NOT "keep every shiny."** There are 1068 in-bag shinies but
   `shiny.txt` protects 1031; the rule is top-N-per-group, so **37 shinies fall
   outside it**, and **34 of those become newly_trimmed** (mostly surplus shiny
   Gyarados/Eevee/Magikarp). v9's blanket `shiny_protected_chain` kept them. If
   the intent is "never release a shiny," the shiny rule under-protects by ~34 and
   needs widening to all-shinies. This is the single largest behavioral
   divergence from v9 — **confirm before any cull.**

2. **Surplus legendaries get cut.** 466 in-bag legendaries; the **rarity** rule
   caps at top-6 per (pokemon_id, form), leaving **38 legendaries covered by no
   rule** — all 38 are newly_trimmed (Solgaleo, Rayquaza, Kyogre, Latios, Latias,
   Raikou, Suicune, Tornadus, the Regis/Regigigas/Regieleki, etc., many of them
   shadow or best-buddy copies). v9 blanket-kept all legendaries. Per the
   "treat missing protection input as PROTECTED" memory rule, releasing a
   legendary on a top-6 cap is a judgment call the user should sign off on.

3. **Best-buddy is effectively unprotected.** 607 in-bag best-buddies; the
   **best_buddy** rule keeps only **17** (it is a no-other-reason safety net, 0
   unique). **59 best-buddies are newly_trimmed.** If BB status alone should keep
   a mon, this rule is far too narrow.

4. **rarity NULL-flag handling (agent note).** 305 in-bag rows had all four
   rarity flags NULL (an unprocessed ingest batch). The rarity agent
   species-cross-references rather than treating NULL as 0, which rescues exactly
   one true false-negative (uid `f9af7a9aaeafbf75`, pid 150 Mewtwo); the other
   304 genuinely resolve common. Good call, but it means rarity membership leans
   on a species map, not raw flags — worth knowing if flags get repopulated.

5. **xxl grouping choice (agent note).** xxl groups by (pokemon_id, form) per the
   policy doc, NOT (pid, form, costume) like the older tagset script. One XXL mon
   (a Pumpkaboo, `xxl_top3_heaviest` under v9) is newly_trimmed as a result. No
   boundary ties needed arbitration.

6. **shadow CP-floor rejections (agent note).** The shadow rule keeps the
   strongest per (pid, form) plus top-10 GL/UL shadows *only if* the ranked shadow
   form clears the league CP floor (GL≥1400 / UL≥2400). Several top-10 shadow
   candidates were rejected by that floor; if a high-rank shadow PvP'er you value
   is in the trimmed set, that floor is why.

7. **Dynamax/GMax & Mega have no dedicated rule.** 51 `bread_1/2` (Dynamax) and 8
   `current_mega_evolved;has_mega_level` mons that v9 kept are newly_trimmed —
   they survive only if they independently clear variant_floor/shiny/rarity. The
   variant_floor gmax exception (cap 4) helps GMax dupes but not Max/Dynamax
   workhorses or mega investments per se. If the Max/Mega rosters matter, they are
   not covered.

**Sanity checks that passed:** 0 hundos in newly_trimmed (hundo rule holds); every
universe id resolves in the DB; KEEP+TRANSFER reconciles to in_bag exactly;
all rule members lie within the universe.

## Bottom line

The new union-of-rules policy keeps **4331 / 4766** and would release **435**, of
which **240 are mons the current v9 engine protects** — concentrated in surplus
shinies, surplus legendaries, best-buddies, and Dynamax/Mega/costume picks that
don't independently clear a floor. **Do not cull on this without explicitly
confirming the shiny (concern 1), legendary cap (concern 2), and best-buddy
(concern 3) behavior** — each is a deliberate narrowing relative to v9, and under
the project's "incomplete/lost-protection ⇒ treat as PROTECTED" rule they warrant
a human OK first.
