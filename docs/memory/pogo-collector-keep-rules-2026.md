---
name: pogo-collector-keep-rules-2026
description: "2026-specific per-Pokémon attributes that mark a specimen as keep-worthy — Adventure-Effect roster, Gigantamax, Max-move unlocks, Mighty (fresh_is_strong)."
metadata: 
  node_type: memory
  type: project
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

What makes a Pokémon irreplaceable in 2026, beyond the classic IV/PvP/Legacy-move criteria. Full details: [pogo_extract/research_2026-05-27/03_tag_cosmetic_systems.md](../../pogo_extract/research_2026-05-27/03_tag_cosmetic_systems.md) and [04_recent_framework.md](../../pogo_extract/research_2026-05-27/04_recent_framework.md).

## Adventure Effect roster

May 2026 snapshot; the source of truth is `ae_registry_live.json` + `derive_ae_roster.py`:

| Dex | Species | Form / signature move |
|----:|---|---|
| 483 | Dialga | Origin / Roar of Time |
| 484 | Palkia | Origin / Spacial Rend |
| 646 | Kyurem | Black or White (each form has its own) |
| 800 | Necrozma | Dusk Mane (Sunsteel Strike) or Dawn Wings (Moongeist Beam) |
| 888 | Zacian | Crowned Sword |
| 889 | Zamazenta | Crowned Shield |
| 890 | Eternatus | Dynamax Cannon — only AE that stacks rather than replacing |

The live registry holds 11 effects. The 2 beyond the table, moves 495 Dynamic Punch+ and 496 Future Sight+, are Mega Mewtwo X/Y (dex 150). They were read by temp-evo enum name on 2026-09-08 (see [[pogo-adventure-effect-live-registry]]) and are covered by `rarity_keep_all_pids` [150]. Since 2026-09-20 the live read returns them only as bare MOVE_495/MOVE_496 (the temp-evo enum name is gone). `derive_ae_roster` maps them to 150 through the desc_key HINTs `dynamic_punch_+` / `future_sight_+` (added 2026-09-20; `ae_roster_derived.json` lists 150), and for any future live effect that maps to no species it WARNs (exit 2 if an in-bag mon carries that move).

`references.py` `ADVENTURE_EFFECT_IDS` and keep_config `adventure_effect_pids` = {483,484,646,800,888,889,890}; the keep rule itself is form-level via `derive_ae_roster` species_ids (base Necrozma, base Kyurem, base Zacian/Zamazenta do not have the effect).

## Gigantamax (irreplaceable per individual)

An individual IS Gigantamax when `fresh_bread_mode==2`, the same field as Dynamax; `is_gigantamax_capable` is a species-level column. The live Gmax roster grows (Garbodor is already live), so protection must never key on a hand-written species list. The roster (informational only) is the species whose client-GM `pokemonExtendedSettings.breadOverrides` carries `breadMode: BREAD_DOUGH_MODE`: 18 on 2026-09-20, listed in [[pogo-ultracode-audit-2026-06-09]]. Do NOT count `BREAD_SHARED_SETTINGS.breadSettings.allowedSourdoughPokemon` (31, incl. Eevee, Melmetal, Corviknight) or raw BREAD_DOUGH_MODE hits; a GM entry proves the client knows the form, not that it is released.

## Max-move investment (per-individual, sunk cost)

Max Attack levels up by default but **Max Guard** and **Max Spirit** must be *unlocked* per individual at significant resource cost. A Pokémon with either unlocked is meaningfully harder to replace than one without. Captured once, not tracked: `extract_bread_moves.py` (manual Frida pass, last run ~2026-05-28, not part of the recrawl) wrote `bread_moves` ([MoveType, MoveLevel] pairs) / `bread_max_level`. Mons caught since then have no data (34 in-bag Dmax/Gmax on 2026-09-20) and existing levels can be stale. Used only by `deep_profile.py`/`query.py`; not a keep axis or a tag.

## `fresh_bread_mode` = the Dynamax/Gigantamax enum

Niantic's internal codename for Dynamax is "Bread" (Bread Station = Dynamax Den, Bread Move = Max Move). `fresh_bread_mode` is ONE per-individual enum (display proto `BreadModeEnum` @0x60): 0 none, 1 Dynamax (`BREAD_MODE`), 2 Gigantamax (`BREAD_DOUGH_MODE`), 4 `BREAD_SPECIAL_MODE` (the game's special Max mode on Crowned Zacian/Zamazenta and Eternatus; a real value, 5 in-bag rows). keep_policy treats anything other than 1/2 as plain (its comment calls 4 garbage).

## Mighty Pokémon (`fresh_is_strong`)

`fresh_is_strong` = `PokemonDisplayProto.IsStrongPokemon` (+0x64) = the MIGHTY flag (the client pairs it with the mighty FTUE encounter). Keep rule 11 (mighty) applies, labelled Never Cull. There is no per-mon Showcase-winner bit (`PokemonProto.pokemonContestInfo_` = ContestId/ContestEndTimeMs/FreeUpTimeMs is entry state; wins are a separate `ContestWinDataProto` record).

Mighty IV floor: 13/13/13 (verified). Nothing in the engine uses it (the client GM has no IV-floor field); `fresh_is_strong` alone marks a Mighty. UNVERIFIED: that a Mighty is a Wild Area encounter caught at trainer level 40+.

## Evolution feasibility gotchas (apply BEFORE tagging "to-evolve" specimens)

When recommending evolves for dex completion, use the client game master (`gamemaster_pokeminers.json` evolutionBranch / evolutionQuestTemplate), never main-series evolution rules, and filter by:

**Gender-locked targets** (target_pid → required gender):
- 416 Vespiquen → female Combee only
- 758 Salazzle  → female Salandit only

**Region-locked evolution targets** (only reachable from the specific regional variant of the source line):
- Hisuian-only: 903 Sneasler (from Hisuian Sneasel, daytime + quest), 904 Overqwil (from Hisuian Qwilfish, quest)
- Galarian-only: 862 Obstagoon, 864 Cursola, 865 Sirfetch'd, 866 Mr. Rime, 867 Runerigus

A Kantonian shadow Sneasel reaches Weavile (461) only, NOT Sneasler. A Kantonian shadow Yamask reaches Cofagrigus only, NOT Runerigus. A Kantonian Qwilfish doesn't evolve at all (only the Hisuian variant evolves, to Overqwil).

**Trade-discount evolutions** (game master `noCandyCostViaTrade`: candy is waived when the mon was received in a trade, otherwise normal candy): Gigalith, Conkeldurr, Escavalier, Accelgor, Trevenant and Gourgeist at 200 candy; Alakazam, Machamp, Golem and Gengar at 100 candy. No PoGo evolution requires a trade, so a shadow copy still evolves with candy.

**Specific-action evolutions** (worth flagging but not excluding):
- 979 Annihilape = Primeape + 100 candy + defeat 30 Ghost- or Psychic-type Pokémon
- 983 Kingambit = Bisharp + 100 candy + win 15 raids against Dark- or Steel-type raid bosses (public guides: with Bisharp as buddy)
- 923 Pawmot = Pawmo + 100 candy + walk 25 km as buddy
- 901 Ursaluna = ANY Ursaring + 100 candy during an in-game full moon, no walking (no buddy-km requirement in the game master)
- 738 Vikavolt = Charjabug + 100 candy at a Magnetic Lure

**No GO evolution** (no evolutionBranch in the client game master targets them): 899 Wyrdeer, 900 Kleavor (the Scyther->Kleavor chain is display-only in the Pokedex), 902 Basculegion, 981 Farigiraf.

**Item-required evolutions** (need the item before evolving): Metal Coat (Steelix, Scizor); Sun Stone (Bellossom, Sunflora, Whimsicott, Lilligant, Heliolisk); Sinnoh Stone (Ambipom, Dusknoir, Electivire, Froslass, Gallade, Gliscor, Honchkrow, Lickilicky, Magmortar, Mamoswine, Mismagius, Porygon-Z, Rhyperior, Roserade, Tangrowth, Togekiss, Weavile, Yanmega); Unova Stone (Chandelure, Cinccino, Eelektross, Musharna, Simipour/Simisage/Simisear). Lure Modules: Magnetic (Magnezone, Probopass, Vikavolt), Mossy (Leafeon), Glacial (Glaceon, Crabominable), Rainy (Goodra).

## 30-day catch-date lockout for remote trades

Anything caught in the last 30 days **cannot be remote-traded** (only in-person traded). When advising on trade plans, factor this in.

## Why this matters

The project's cull and tag rules protect collector value. In 2026 the collector-value surface expanded materially (Gigantamax, Max-move unlocks, Mighty, Forever Friends remote trades). Using a stale 2023-era mental model under-protects irreplaceable Gigantamax/Mighty specimens.

## How to apply

- When discussing `fresh_bread_mode`, name the value (Dynamax / Gigantamax) — not "Bread Mode" — for the user's benefit, but keep the proto column name unchanged.

See also [[pogo-mechanics-reference]] (mechanics behind these), [[pogo-data-completeness-before-destructive-actions]] (don't transfer on incomplete protection inputs), [[project-pogo-extract]] (where the protections are enforced).

## OWNERSHIP + KEEP-LAW HANDOFF (2026-08-31) -- I now own culling + Transfer tagging
Benny moved culling and auto-tag-for-transfer to THIS session; phone-maintenance-38 developed the
rules and has stood down from writing `auth_tag_names` / pushing the tag. Full handoff doc lives at
**`pogo_extract/HANDOFF_KEEP_LAW.md`** -- read it before touching the pile.

**LIVE TRUTH is `system/analysis/policy_reasons.json` (kept uid -> reasons) +
`system/analysis/tagsets/Transfer.txt` (the pile). They partition EXACTLY (verified 5522+57=5579=
in_bag, zero overlap). `cull_decision_v9` is a DEAD legacy column** -- I read it, invented a
24-keeper "drift" and a Groudon scare, and was wrong twice. It disagrees with the live engine on 54
rows. NEVER read it.

**THE CAP TRAP: never read `keep_config.DEFAULTS` -- always `keep_config.cap(name)`.**
keep_config.json overrides and several DIFFER (reading DEFAULTS for rarity flipped the Groudon call).
Per-species overrides exist: `keep_config.species_cap('xxl', pid, keep_config.cap('xxl'))`.

**CAPPED vs KEEP-ALL -- the distinction that caught me on the Groudon:**
  KEEP-ALL (uncapped): hundo, Adventure-Effect FORMS, mighty (fresh_is_strong), dex-only copy, protected
  pids, E+F origin, favorites (since 2026-09-17), PvP rank<=READY_RANK on a CP-viable stage + pvp_spread,
  Safety Hold (rank_unknown/data_incomplete), and location-card holders with an UNKNOWN card id.
  CAPPED (top-N, the rest is LEGITIMATE fodder): plain_line / plain_line_preevo (MIDDLE stages), cosmetic,
  dynamax, gigantamax, shiny, **rarity (yes, legendaries)**, xxl, shadow, location_card (per species/form/card,
  since 2026-09-02), nundo (per look, since 2026-09-17), legacy moves (per species: `legacy_default_cap` +
  `legacy_species_caps`).
A legendary or an XXL sitting in the pile is NOT automatically a bug. The culled Groudon was #14 of
15, lowest CP of the four 82.2%, and the only copy carrying no independent axis -- correct.

**NULL == PROTECTED.** Preflight fail-safes when the gamemaster does not load. XXL is read from two
size columns (pokemon_size_category OR size_enum); the XXL tag is deliberately NOT a protection
input. Use `fresh_*` columns, and
specifically **`fresh_natural_art_bg`, NEVER `natural_art_background`** -- the non-fresh column
holds garbage that once fabricated a phantom background and collapsed a real shiny Gmax Lapras.

**Four more non-obvious laws:** collapse goes UP only (specials are never collapse victims, trophies
never dominators); trophies never consume a capped slot; shinies displace the plain floor and win IV
ties EXCEPT Unown (count-based carve-out); comb-up is keyed by **speciesId, not dex** (Galarian vs
Kantonian Rapidash share dex 78; a dex-keyed pool once released a Galarian Ponyta), and an evolution
only counts if the target has been seen in the dex.

**KEEP preflight_transfer.py, do not reinvent it** -- its value is that it re-derives keepers
INDEPENDENTLY of keep_policy. Exits 1 if any pile uid earns an unconditional keep axis and is not
gym-locked, or if a Transfer uid is missing from pokemon.db. It deliberately over-protects.
keep_policy has two more SystemExit tripwires: a CP-viable top-rank PvP spread in the pile, and a
protected mon in the pile. **Deployment must be read LIVE off the proto (gym coords @0x140/0x148)** --
the DB deploy columns lie.
**Deliberately NOT automated:** releasing (TAG ONLY, standing rule), XXS, blanket policy changes,
restarting PoGo mid-play, and attaching to a cold-starting app.
Read-only helpers: `audit_cull.py`, `audit_tags_membership.py`, `_evocheck.py`, `_lawcheck.py`, and
`_spotdata.py` (JSON fact-pack of every keep axis per pile mon, ~2s).

## SETTLED: Pokemod's Transfer-on-Catch CANNOT be used on this collection (2026-08-31)
The user asked repeatedly to "just copy how Pokemod does it". I did -- their exact trigger
(CatchPokemonOutProto.IMergeFrom onLeave -> CapturedPokemonId), their exact next-frame retry
(`if (!PokemonBag.GetPokemon(id)) return runNextFrame(s)`, cap 600), and their exact protection list
(hundo/nundo, shiny, shadow=INVASION origin, location card, special ball [PREMIER 5/BEAST 6/
WILD_BALL_PREMIER 8/MASTER 4], pokemonClass != NORMAL, !isTransferable_, origin not in {WILD 1,
INVASION 6}). Enums: POKEMON_ORIGIN {NONE0 WILD1 EGG2 RAID3 QUEST4 VSSEEKER5 INVASION6 PHOTOBOMB7
TUTORIAL8 POSTCARD9 STATION10 INCENSE11 DISK12 BREADBATTLE13}, POKEMON_CLASS {NORMAL0 LEGENDARY1
MYTHIC2 ULTRABEAST3}.
**MEASURED AGAINST THE LIVE BAG: it finds 171/171 of the pile (perfect recall) but tags 2,518
KEEPERS** -- Pikachu 123, Unown 69, Scatterbug 25, Lickitung 24, Eevee 22, Spinda 21, Mewtwo 20.
Their law is PER-MON; this collection's is COHORT/CAP based (variant_floor 1971, shiny 1475,
rarity 496, evolve_1 317, location_card 299...). No IV threshold rescues it -- a Mewtwo is kept by
the rarity cap at ANY IV, an Unown by dex coverage at ANY IV.
A seed-bar oracle (a provable lower bound) models ONLY the plain_line/preevo axis: measured
**688 false positives**, 37% recall.
Making it safe means reimplementing all ~20 keep axes in on-device JS, where every missed axis is a
lost keeper. DO NOT SHIP PER-CATCH TAGGING. Say no and cite these numbers.
**The batch is the answer and is not slow:** full_audit.py runs the 10 audits in `full_audit.AUDITS`
in parallel, and the 2026-09-20 autocull runs took about 85-153 s end to end. The "10 minute wait"
was waiting on a human to start it, not the tool.
Engine note: `system/scripts/keep_policy.py` also emits `system/analysis/fodder_oracle.json` (seed
bars); ladder_report.py reads it every cull, so do not remove the export.
