---
name: pogo-game-authoritative-over-pvpoke
description: pvpoke's gamemaster MISSES evolution edges the client's own has; reconcile_gamemaster.py copies them in, additively.
metadata:
  type: project
---

`pvpoke_gamemaster.json` is a community PvP file; `gamemaster_pokeminers.json` is the CLIENT'S OWN game master.
Where they disagree the game wins. `reconcile_gamemaster.py` (2026-09-20) copies the game's truth into pvpoke's
copy and is wired into `refresh_gamemaster.py` (a fresh pvpoke download silently undoes it) and gated by
`audit_gamemaster.py` (BLOCKs on drift; proven to fire).

**Measured:** base stats agree on all 1,191 lines. EVOLUTION EDGES do not -- pvpoke was missing 8:
`corsola_galarian->cursola` (no family at all), `zygarde->zygarde_complete`, `poltchageist->sinistcha` (filed
BACKWARDS on sinistcha), `rockruff->lycanroc_dusk` (pvpoke's id is misspelled `lycranroc_dusk`, so the stage was
unrankable), plus finizen/espurr/lechonk/tandemaus gendered targets.

**Why it matters:** `rank_cache._reachable()` only ever REMOVES stages, so pvpoke claiming too much is already
handled -- but an edge pvpoke LACKS is invisible and that mon is ranked as if it were a final stage. One Galarian
Corsola went GL #3704 -> #375 once Cursola was scored. Under-protection = the release direction.

**Three traps, all hit while building this:**
1. A VARIANT template must never fill the BASE species key -- `CORSOLA_GALARIAN`'s branch answering for `CORSOLA`
   gave a Kantonian Corsola a Cursola stage, and `FARFETCHD_GALARIAN` gave a Kantonian Farfetch'd Sirfetch'd.
2. `<SPECIES>_NORMAL` OUTRANKS the formless template. The game ships `V0051_POKEMON_DUGTRIO` (def **134**) AND
   `V0051_POKEMON_DUGTRIO_NORMAL` (def **136**); bag Dugtrios are form 61 = DugtrioNormal and only reconstruct
   at 136. Taking the first template "corrected" pvpoke to a stale number -- `audit_invariants` BLOCKed it.
3. Adding the real edge on top of pvpoke's reversed one made a 2-cycle that recursed `get_evolutions` to death.
   It now carries a `_seen` cycle guard; bad upstream data must degrade, not crash.

**How to apply:** edges are ADDITIVE-ONLY (never delete -- `_reachable` is the remover and reads the game
directly). Mega/primal stats live in `tempEvoOverrides`, not their own template. See
[[pogo-viability-blind-best-stage-bug]], [[pogo-forensic-cull-audit-2026-09]], [[project-gamemaster-monthly-refresh]].

**2026-09-23, legacy moves too:** pvpoke still called Body Slam elite for Audino and Seed Flare for Shaymin while the
client game master rolls both from a plain TM -> 6 "Legacy Moves" members were untrue. detect_legacy.py now drops a
pvpoke elite flag when `_game_master_rollable()` (client quickMoves+cinematicMoves minus eliteQuick/CinematicMove, by
dex) contains the move. The client can ADD (event-only moves) and now also REMOVE a legacy verdict.
