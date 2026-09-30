---
name: pogo-game-state-2026
description: "Pokémon GO structural state (base May 2026): ownership, trainer cap, friend tiers, storage (read live), Daily Discovery cadence. Seasons are deliberately not tracked."
metadata: 
  node_type: memory
  type: project
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

Pokémon GO's structural state changed materially in 2024–2026; what was true in older training data is partly stale. Anchors as of 2026-05-27:

- **Ownership:** Scopely closed the $3.85B acquisition of Niantic's gaming division on 2025-05-29. PoGo is now a Scopely product. Niantic Spatial Inc. kept the AR-mapping tech (Ingress/Peridot). Same client, same dev team, but cadence shifted: paid event tickets largely replaced by the GO Pass (Free/Deluxe $7.99 / Premium $14.99) seasonal progression model, and weekend events are standardised Sat–Sun.
- **Trainer level cap is 80** (raised from 50 on 2025-10-15). L71–80 require XP plus per-level research tasks. **Pokémon level cap is still 50** (Best Buddy +1 active CPM puts the active buddy at L51 effective).
- **Storage:** game maximums (game master `INVENTORY_SETTINGS`, read 2026-09-20) are Pokémon 12,650 / items 12,000; the user's own caps are far lower (`max_pokemon_storage` 5800, `max_item_storage` 3650 on 2026-09-20). Read them live every pass -- they are upgradeable, and hardcoding one under-reported free slots by 50 once.
- **Forever Friends** (2025-12-08) added a 6th friendship tier above Best Friend. Earned via Friendship Points (1/day per friend + up to 7/week via Weekly Challenges; ~90 FP after BF). Once FF, remote trading is unlocked — 1 remote trade/pair/day at the normal Special-Trade Stardust cost, with a **30-day catch-date lockout** for remote trades. Friend cap 450→650.
- **Guaranteed-Lucky cap:** 25→35 on 2025-02-18 (window: caught 2019 or earlier), 35→45 on 2025-12-31 (window: caught 2020 or earlier; permanent).
- **Daily Discovery weekly cadence** (since Memories in Motion, Mar 2026): each weekday has a theme — Mon Max Battles, **Tue Showcases** (replaces the old weekly Spotlight Hour), Wed Raids, Thu GBL, Fri Friendship. Pauses during GO Fest / Wild Area / Tour.
- **Spotlight Hour is no longer a weekly thing** as a result — Showcase Tuesday takes its slot.
- **GO Tour 2026 was Kalos** (in-person Feb 20–22, global Feb 28–Mar 1).
- **GO Fest 2026 = 10th anniversary**: Tokyo May 29–Jun 1 (Zeraora debut for ticketholders), Chicago Jun 5–7, Copenhagen Jun 12–14, **Global Jul 11–12 — free for the first time**. Mega Mewtwo X + Y debut window.
- **Seasons: NOT TRACKED HERE (decided 2026-09-20).** Season names/windows go stale every ~3 months and drive no
  decision this project makes. Checked the phone three ways -- shared_prefs, the app's files dir, and the client
  game master -- and the live season is none of them: it is server state, readable only by attaching to the running
  game. Not worth a phone pass for something two taps away in the UI. If a season ever matters, read it there.

**Why:** When ranking, culling, or tagging the user's bag, the keep-worthy criteria and the meta shift around these structural changes. A 2023-era mental model is materially wrong for 2026 — friendship math, trade rules, trainer XP, and even what counts as a weekly event are different.

**How to apply:**
- Don't assume Spotlight Hour is on Tuesdays — Showcase is.
- Treat anything caught in the last 30 days as remote-trade-locked (matters when the user asks "can I trade X to my friend").
- When the user mentions Niantic, remember Scopely owns the game; news may be filed under either name.
- The full live-meta snapshot (raid bosses, GBL season, recent debuts) lives in [pogo_extract/research_2026-05-27/02_live_meta.md](../../pogo_extract/research_2026-05-27/02_live_meta.md); refresh from web before quoting current event/raid state — it goes stale fast.

See also [[pogo-mechanics-reference]], [[pogo-collector-keep-rules-2026]], [[project-pogo-extract]].
