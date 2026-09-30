# PoGo catch + flee reference (verified 2026) — for the auto-catcher loss analysis

## Two-roll model (per ball that fails to catch)
1. **Catch roll** — single Bernoulli: `rand[0,1) < p_throw`. `p_throw` folds in ball, berry, throw bonus, curveball, type medal, weather (via CPM), encounter mod, BCR/CPM. GO does NOT use the 4-shake check — one roll per throw; the 3 wobbles are cosmetic.
2. **Flee roll** — ONLY if the catch failed: separate trial vs species `base_flee_rate` (f). **f is multiplied by NOTHING** (berries/ball/throw/curve do not affect it).

## Result codes (our LOSS log: r=)
- **2 = escape**: catch failed, flee roll stayed → a *genuine break-out*.
- **3 = flee**: ran. Genuine ONLY if a prior escape happened for that pid. **A flee on att#1 with no prior escape, indifferent to prob (esp. high prob/p=1.0), is a SERVER-REJECT, not the flee mechanic.**
- **4 = miss**: throw missed the ring → no catch roll, no flee roll. Mechanical waste.

## Genuine break-out-flee (Razz HELPS) vs server-reject (Razz USELESS)
- **Genuine**: preceded by ≥1 escape; frequency tracks species f; responds to prob.
- **Server-reject**: att#1, no escape, prob-indifferent (fled even at p=1.0); 3 sub-causes by scope:
  - Global outage (all pids/everyone, brief).
  - **Per-account soft-ban** (spoof-relevant): only this account; co-occurs with "Try Again Later" at stops / no loot (== this account's OUT_OF_RANGE spin block). Clears by spinning a stop ~30-40x.
  - Stale/desynced encounter: sporadic, right after a location jump (route/teleport).
- **esc:flee ratio test** — if `flee/(flee+escape)` >> the species' f, the losses are server-rejects, not flees. (Our run: 37 flee / 3 esc = 92% → impossible for the species seen → server-reject dominated.)

## Catch-prob transform (logged X excludes throw+curve; catcher always Excellent+curve)
`p_real = 1 − (1 − X)^(E×1.7)`, E∈[1.7,2.0] → exponent 2.89–3.40. Quick: 0.10→~0.28, 0.20→~0.50, 0.40→~0.80, 0.60→~0.95, 0.80→~0.99.

## Catch multipliers (catch rate ONLY — none affect flee)
Ball: Poke 1.0 / Great 1.498 / Ultra 1.995. Berry: Razz 1.5 / Silver Pinap 1.8 / Golden Razz 2.5. Throw: continuous `2−r`, Nice 1.0–1.3 / Great 1.3–1.7 / Excellent 1.7–2.0. Curveball 1.7. Medal (per type, avg of dual): Bronze 1.1 / Silver 1.2 / Gold 1.3 / Platinum 1.4. Weather: via CPM (no flat term). Encounter: wild 1 / research 2.
Formula: `P = 1 − (1 − BCR/(2·CPM))^(Ball·Berry·Throw·Curve·Medal·Encounter)`.

## Species base_flee_rate (historical GameMaster; Niantic set the live field to -1 since ~2018, so these are pre-obfuscation & unverifiable live)
- Abra **0.99**; Galarian Articuno/Zapdos/Moltres **0.90**.
- Common "fleey" (Pidgey/Rattata/Caterpie/Weedle/Wurmple/Zubat/Spinarak/Sentret/Zigzagoon) **0.20**.
- Magikarp 0.15; Bulbasaur/Charmander/Squirtle/Gastly/Magnemite/Murkrow **0.10**; Ralts/Onix 0.09.
- Evolved generally **0.05–0.07** (Kadabra 0.07 → Alakazam 0.05; note Abra's family crashes from 0.99).
- Default ~0.15 unevolved / ~0.07 evolved. **Combee/Drowzee/Drifloon: no citable f (likely ~0.20 by analogy, UNVERIFIED).**

## Highest-leverage REGULAR-RAZZ-ONLY lever (only for GENUINE flees)
Front-load Razz on the FIRST ball of genuine high-flee species (f≥0.20 — Abra/Galarian birds/the 0.20 common tier), since on high-flee mons you often get only one throw. Useless on server-rejects (the bulk here) and on low-flee mons. NEVER Golden Razz (706) / Silver Pinap (708; 707 is Golden Nanab) — hard user constraint.

Sources: Bulbapedia Catch rate (GO) & catch-rate list; GamePress GUCT; PoGo Hub catch-mechanics + "first-throw flee glitch" + soft-ban guides; Dexerto; pogoapi.net. Full reports: tasks/wc9ynt2nm.output.
