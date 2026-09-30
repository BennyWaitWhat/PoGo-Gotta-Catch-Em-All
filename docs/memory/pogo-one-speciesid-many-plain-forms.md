---
name: pogo-one-speciesid-many-plain-forms
description: "A stage is a (speciesId, FORM). pvpoke collapses Gastrodon seas and Florges colours into one id; ask the game which form a pre-evo becomes."
metadata: 
  node_type: memory
  type: project
  originSessionId: 8fde11a7-6340-4cdf-8f4e-02a95910c52b
  modified: 2026-09-22T08:47:38.356Z
---

One pvpoke speciesId can cover several PLAIN forms: `gastrodon` = West + East, `florges` = 5 colours,
also Basculin stripes, Deerling/Sawsbuck seasons, Flabebe/Floette. The evolved copy keeps its OWN lineage's
form, and the game says which: `evolvable_forms.target_form(form_id, target_sid)` reads `evolutionBranch`
(`SHELLOS_WEST_SEA -> GASTRODON_WEST_SEA`). Added 2026-09-20 (cache v7) with `form_name(form_id)`.

**Two real defects this caused, found the same day:**
* `keep_policy._key_of_sid` holds ONE stage key per (speciesId, gender terminal), chosen by pool size. A WEST
  Shellos was judged against the EAST Gastrodon pool `(423, 99, 0)` and "earned" a slot by displacing an East
  copy it can never become -- while the West pool it really joins already held a hundo. `_tkey` now asks the
  game **only when that sid maps to more than one bag key**, so single-form species are untouched.
* `audit_promises` pooled stages by `pvid()` alone, so a **FloetteRed** was called pointless against the
  Yellow/Blue Florges hundos -- it would be the first RED Florges in the bag. Buckets are now filled under both
  the bare speciesId and the form, and a promise is judged on the form the game names. Falls back to the
  speciesId pool when any held copy of that stage has no readable form name (form-0 species behave as before).

**Why:** the engine and the auditor disagreed and blocked the sync. Neither was "the" bug -- they were BOTH
form-blind in different directions, one too permissive and one too strict.

**The full class (live census, not examples):** 21 speciesIds cover >1 plain form in the bag -- unown (28
letters), scatterbug/spewpa/vivillon (patterns), spinda, squawkabilly, flabebe/floette/florges, sawsbuck/deerling,
gastrodon/shellos, basculin, oricorio, furfrou, frillish/jellicent, pyroar, dudunsparce, gimmighoul, rockruff.
NINE are evolution targets. `Unset` and `<SPECIES>_NORMAL` are the SAME form (cf collapses them) -- fold them out
or the census reads 396.

**The attach guard WAITS, it does not fail** (user 2026-09-20: "fuck waiting for the guard"): `pogo_pipeline`
calls `pg.wait_ready_to_attach()` before `get_session()`, so a relaunched game costs silent seconds instead of
"RECRAWL FAILED rc=1". The 45s init-storm protection itself stays -- attaching mid-storm is what froze PoGo.

**Both sides of a pool must run through `canon_form(sid, name)`** or they silently miss each other: filling under
'' while reading 'TINKATONNORMAL' made every stage read EMPTY and 35 piled mons look like upgrades.

**Two ways the form key silently reads a stage as EMPTY** -- and an empty stage means every mon "earns" a slot:
1. the GENDER TERMINAL: a female Ralts looked up GARDEVOIRNORMAL at gterm 2, missed the pool filed at gterm 0
   and a 68% earned a slot a 100% already held. Keep the `_g` -> `0` fallback the speciesId path always had.
2. a branch with NO `form` field: the game's Pikachu->Raichu branch names only 'RAICHU', which matches no bag
   key. `canon_form` reduces it to '' = "the base form", and the speciesId path resolves that correctly.
Both were caught by `audit_promises` ("culled after evolving"), never by a human.

**Same family, the CAP (2026-09-22):** `keep_policy._stage_cap` asks ONE representative row "can this stage
evolve?", and `_stage_rep` kept whichever row came first. A locked costume-82 Floragato shares the ordinary
copies' stage key, so Floragato read as a FINAL (cap 3) and a 91% Sprigatito was promised a slot that
`audit_promises` (middle cap 2) called `NO REASON ... only out-CPs an equally good 91% copy`. It blocked every
cull for a day. Fix: prefer an evolvable rep. Pile identical before/after; only that promise moved.

**Consumers fixed:** `keep_policy._tkey`, `audit_promises.stage_key`, `_evocheck` (spec/doms/best/held),
`game_opportunities.hundo_at`, `ladder_report.prev_best`. `audit_gamemaster` now WARNs when the game names no
target form for a multi-form stage (only Dunsparce -> DudunsparceTwo/Three, which is genuinely random).

**It came back in new code (2026-09-30):** the H08 shiny-spot check `audit_promises._shiny_earns` (2026-09-29) keyed
the shiny ladder by `pvid()` alone, so all five Florges colours shared 4 plain spots. The first cloud cull after
105 reward catches blocked on `NO REASON: Floette 57% -> florges` -- 3 White + 2 Yellow Floettes promised, while the
bag's only shiny Florges is Blue. The law and `keep_policy` key shinies by (pokemon_id, form). Fix: the spots are
filed bare + form and a promise is judged on `stage_key()`'s form (commit "audit_promises: shiny spots per
species+form"). The producer `refresh_evolve_shiny` (`sh_ivs` by pvid) was fixed the same way the same night:
it was only ever STRICTER than the law, and it did hide one upgrade -- a 55% shiny FlabebeRed got no evolve label
because White/Yellow shiny Florges filled the pooled spots. Offline before/after: pile identical, that one
`Evolve Once -> floette` added, 11/11 audits. Any NEW pooled-by-pvid code is the same bug: grep for it when you add
a ladder.

**How to apply:** never treat a pvpoke speciesId as a stage identity. Read the target FORM from the client
branch, and read it from the FORM template, never the formless one -- `V0422_POKEMON_SHELLOS` claims EAST for
every Shellos, the same stale-base-template trap as Dugtrio's baseDefense in
[[pogo-game-authoritative-over-pvpoke]]. See also [[pogo-capped-vs-keepall-bug-class]],
[[pogo-combup-bar-ignored-displacement-2026-09-13]].
