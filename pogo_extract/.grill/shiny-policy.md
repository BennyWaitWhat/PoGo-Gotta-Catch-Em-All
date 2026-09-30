# Grill — Shiny policy (2026-06-08)

## Intent
Pressure-test whether the engine's shiny handling matches what the user actually wants — both the **keep cap** and the **Evolve Shiny** advisory tag — before changing any logic.

## Constraints / principles
- Shinies are rare and releasing one is **one-way** → bias toward keeping; never silently over-cull shinies.
- **Shiny progression is its own goal**, not contingent on competitive value. ("shinies are allowed to be progressed in their own rite.")
- Competitive (GL/UL) value of a shiny is **incidental** — nice if it happens, never a gate.
- Any tunable must live in `keep_config` single-source (no drift).

## Key decisions
1. **Shiny cap stays 20 (best-IV per species,form) — for now.** Acknowledged it barely bites (last pile had `SHINY_EXCESS=1`; ~1,290 shinies kept) and the "1 shiny per gym × 20 gyms" rationale doesn't really hold (gyms take variety, not 20 of one species) — but the user is fine with 20 for now. No change.
2. **Evolve Shiny logic: NO change.** Current `compute_target()` is correct: flag a candy-ready shiny pre-evo when evolving it would give the best/first **shiny** of the terminal (or best raw IV of it), candy-only (item/trade/special evos in `SPECIAL` excluded). This already "progresses shinies in their own right"; the best-IV clause lets GL/UL-relevant shinies ride along for free.
3. **REJECTED: adding a PvP-rank gate to Evolve Shiny.** Considered flagging shinies whose evolution would be a GL/UL keeper (rank ≤ ready_rank, CP-viable). User rejected — PvP is incidental, not a trigger. Do not build this.
4. **One shiny per evolved form is enough** — don't flag a *second* candy-ready shiny pre-evo once you own a shiny of the terminal (avoids nagging to evolve every spare shiny Magikarp). Keep current behavior.

## Surfaced assumptions
- The 20-cap was rationalized as gym-defense but is really just a round "I have enough" number kept by preference. That's fine, but it's preference, not tactics.
- Shinies are ~26% of the bag (~1,290), but the cull-driven storage problem is overwhelmingly **plains** — shinies are not the space issue, so capping them buys ~nothing.

## Open questions / future scope
- **Standalone shiny tool (the real want).** User wants shiny management to be a **separate, dedicated thing** — "a different standalone thing for me to filter thru and turn knobs too" — distinct from the main cull engine. Envisioned: browse/filter the whole shiny collection by attributes (species, IV, form, costume, lucky, evolve-readiness, dupes…) and shiny-specific knobs (e.g. per-species shiny caps, keep-all-for-X, event-spam handling like Community-Day stacks). **Deferred** ("for now, 20 of the best IV are good"). Needs its own grill + design pass before building.

## Out of scope (ruled out)
- PvP-rank gating of Evolve Shiny.
- Changing the shiny cap now (stays 20).
- Master / Little League consideration in the evolve logic (Master = highest IV, already covered; Little excluded everywhere by design).
