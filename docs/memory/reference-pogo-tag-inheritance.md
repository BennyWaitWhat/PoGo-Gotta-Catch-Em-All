---
name: reference-pogo-tag-inheritance
description: "Evolving a tagged mon carries ALL its server tags to the evolved form, so any non-PLAN tag drifts; evolution = depart+insert with a new uid."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 13477788-96d8-4172-8c7d-deee9a225a6b
  modified: 2026-09-21T03:29:32.602Z
---

# PoGo tags INHERIT through evolution → non-PLAN tags drift (2026-06-05)

**Evolving a tagged Pokémon carries ALL its server tags to the evolved form.** Verified 2026-06-05: the user evolved 10 shinies that carried the custom **"Evolve Shiny"** tag → all 10 evolved forms (Baxcalibur, Chesnaught, Quilladin, Golem, Jellicent, Ribombee, Ferrothorn, Lokix, Xatu, Pignite) inherited "Evolve Shiny". reconcile then showed `Evolve Shiny 98 server / 88 db / srv_only 10 DRIFT`.

**Consequence:** `prune_tags.PLAN` = `granular_tags.registry()` (31 tags as of 2026-09-20, including Evolve Shiny since 2026-09-12); prune exact-syncs them. Outside PLAN, the static Armored UL/ML/Trade/Release snapshots are never re-synced, so they (and any tag the user makes himself) drift through evolution. Remote Trade and Evolve for Size are re-synced every cull by their own scripts.

**Evolution in the crawl looks like a departure+insert, NOT an in-place update:** the evolved form gets a **new uid**, so the pre-evo uid shows as `departed` and the evolved uid as `inserted`. Evolution **preserves IV and creation_date** (the evolved form keeps the original catch date). So to tell an evolution from a release: a departed shiny whose evolved-species shiny appears in the inserted set with the **same IV** + an **old (preserved) creation_date** = evolved, not released. (This is why a recrawl right after an evolve session shows high churn with protected/shiny mons "departing" — they evolved.)

## ROOKIDEE INCIDENT (2026-06-10)
The tag listed ALL the user's shiny Rookidee (each individually "beat the evolved best"); he evolved
the stack -> Rookidee 0 shinies / Corvisquire 5 / Corviknight 1. A stage stripped bare, another
drowning in dupes. User: "WHAT THE FUCK DO YOU THINK WERE DOING HERE" + "even your assumption is
incomplete." Live rule in refresh_evolve_shiny.compute_target: per stage (pid + form-0-normalized
form) the BEST shiny is never tagged; collectible/shadow/protected/Noevolve shinies never climb; every
other spare, best IV first, is tagged when, on EVERY takeable next-stage branch, that stage holds fewer
shinies than its shiny cap (keep_config, per-species overrides) or the spare beats the weakest of its
top-cap shinies; each tag raises that stage's bar; live candy/items must cover it. Chains still move
one step per sync, but up to the cap can move at once. ALSO WARN THE USER: server tags INHERIT through evolution, so
right after evolving, the evolved form still SHOWS "Evolve Shiny" in-game until the next sync — never
chain-evolve off an inherited tag (that's how one went all the way to Corviknight).
PRINCIPLE for any advisory: count what the action COSTS (source side), not just what it produces; and
when the user repeatedly pushes back on a rule, the rule's GOAL is wrong, not its tuning.

## "Evolve Shiny" tag
- Rule: the compute_target ladder above. Gated targets = `keep_policy.ITEM_GATED_TARGETS` (imported as `SPECIAL`): a hand floor list UNION `evolvable_forms.gated_targets()` from the game master. A gated branch is tagged only when its sole gate is an evolution item in the bag (the item is then spent); other gated branches are recorded in `shiny_gated.json`.
- A managed PLAN tag since 2026-09-12: `build_tagsets` writes `Evolve_Shiny.txt` via `refresh_evolve_shiny.compute_target` and `prune_tags` pushes it. Sync = prune -> set_db (mirror) -> reconcile. Do NOT run `refresh_evolve_shiny.py` standalone: its `main()` still attaches and writes tags.

## Before recommending OR tagging an evolution, check THREE things the evo graph alone misses (2026-06-09, user: "did you even check the requirements... why do you keep making these mistakes. every pokemon needs to be thoroughly checked")
The naive evolution-graph reach over-recommends. Three reliable gates, all verified this session:
1. **TARGET actually released in PoGo.** pvpoke gamemaster's `released` flag is UNRELIABLE for this — it marks ~84 dex#s unreleased incl. in-game species (Ditto, Drednaw, Type:Null, Eiscue). So NEVER auto-filter on it. Maintain a small WEB-VERIFIED `UNRELEASED_IN_POGO` set instead. Confirmed: **Farigiraf #981 is NOT in PoGo** (Girafarig "will" evolve once it launches) — so Girafarig→Farigiraf is impossible. Strongest positive proof a target IS available: the user has already CAUGHT it (dex times>0) — the evo path is demonstrably live in their game.
2. **SOURCE can actually evolve — costumed mons usually CAN'T.** A costume's evolve button is greyed out unless Niantic enabled that exact costume (rare, event-gated, inconsistent). Evolvability = `evolvable_forms.row_can_evolve`: the form's game-master `evolutionBranch` decides first (a locked FORM such as Psyduck Swim 2025 stays locked); then the costume: a `*Noevolve` costume is locked unless the species' `allowNoevolveEvolution` names it (the Jan/Spring 2020 Bulbasaur and Charmander lines can evolve), and any other costume evolves. Verified bugs: a `Fashion2021Noevolve` shiny Sneasel was recommended →Weavile; **2 `Horizons2025Noevolve` Floragato were live-tagged "Evolve Shiny"** (refresh_evolve_shiny's `can_evolve_estimated` is SPECIES-level, blind to the costume variant). `refresh_evolve_shiny._noevolve_costume` delegates to `row_can_evolve` (2026-09-17); `evo_hundo_gap.source_can_evolve` has NOT been migrated and still blocks EVERY costume.
3. **Don't recommend sacrificing a SHINY** (or only-copy). Evolving consumes the pre-evo; a shiny hundo is a keeper, not fodder — flag it CAUTION, don't list it CLEAN.
Plus the gender/form gates already in [[pogo-collector-keep-rules-2026]]: female-only (Salazzle/Froslass/Vespiquen/Wormadam), male-only (Mothim/Gallade), and region routing (Hisuian Sneasel→Sneasler not Weavile).
**Tool: `evo_hundo_gap.py`** (default = bag hundos→missing-hundo slots; `--caught` = any bag mon→uncaught slot; `--pile` = flag sources in Transfer). Buckets results CLEAN / CAUTION(shiny) / BLOCKED(costume·unreleased·no GO evolution method). Scyther→Kleavor, Stantler→Wyrdeer and Basculin→Basculegion have NO evolution method in GO: no evolutionBranch in the client game master targets them (Scyther's only branch is Scizor). BLOCKED via `EVOLUTION_METHOD_MISSING` (Kleavor, Wyrdeer) and `UNRELEASED_IN_POGO` (Basculegion); Bisharp/Pawniard→Kingambit and Spritzee→Aromatisse need an evolution quest.
