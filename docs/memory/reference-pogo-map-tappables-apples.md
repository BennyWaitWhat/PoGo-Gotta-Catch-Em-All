---
name: reference-pogo-map-tappables-apples
description: "Map tappables (event apples 2026-09-29) — what they are, the game's own tap path (gesture handler by signature), the ProcessTappable reply layout, item ids 1151/1152/1155, and the collector tool"
metadata:
  node_type: memory
  type: reference
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-30T00:17:29.106Z
---

**The apples (event, 2026-09-29).**
- Map tappables with TypeKey/AssetKey `TAPPABLE_TYPE_MAPLE`. They appear around PokéStops with a **Mossy Lure Module** (research: "Mossy Lure Modules will only attract apples"; a lure lasts 1 h). `TappableLocation` holds the fort id.
- A tap gives EITHER an apple item OR reveals a Pokémon (`Encounter`). Revealed so far: Cottonee costume 75 CP 97, Smoliv CP 740.
- Items (live Item enum): Sweet Apple = `ITEM_OTHER_EVOLUTION_STONE_MAPLE_A` = 1151 → Appletun; Tart Apple = `MAPLE_B` = 1152 → Flapple; Syrupy Apple = `MAPLE_C` = 1155 → Dipplin. Each is 20 apples + 200 candy.
- Apples ignore bag space and are hidden in the item bag.
- Game master: `TAPPABLE_TYPE_MAPLE` visibleRadiusMeters 150, removeWhenTapped. Other types: POKEBALL, HAT, BREAKFAST, ROUTE_PIN.

**Client objects (0.429.1).**
- `DynamicTappableController` (global namespace). Fields by name: `<Id>`, `<EncounterId>` (uint64), `<TypeKey>`/`<AssetKey>` (string), `<Location>` (`Niantic.LatLng`, 2 doubles), `<TappableLocation>` (fort id string at +0x10), `<DespawnTimeMs>`, `<IsEncounter>`, `tapGesture`.
- `Niantic.Holoholo.Services.DynamicTappables`: DynamicTappablesService, DynamicTappablesSession, DynamicTappableBehaviorService.
  - `BEH.bfnf` = the RPC (returns `IPromise<ProcessTappableOutProto>`).
  - `bfng` handles the reply; `bfnh(LootItemProto)` shows the loot; `bfni(…, TappableEncounterProto)` reveals the Pokémon.
- **The game keeps expired controllers pooled.** Always check DespawnTimeMs against the phone clock.
- **The session re-adds tappables on every map refresh** (AddTappables churn), so DespawnTimeMs of a live one shows only ~1–1.5 min.
- **First seen at ~55–60 m.**
- **Timestamps are epoch ms. Convert with the device clock, not by eye:** I misread despawns as 17:37 when they were 16:57.

**THE TAP PATH (proven 2026-09-29):**
- Call the controller's gesture handler, found by SIGNATURE `void ?(System.Object, System.EventArgs)` (it is named `uxy` in 0.429.1). Pass `(controller.tapGesture, EventArgs.Empty)`, on UnityMain (CameraFollowingGround.LateUpdate pump, `Niantic.Holoholo` namespace).
- Taps at 24–58 m → Status 1.
- `Tapped()` is only a bool query: 5 calls produced 0 requests.
- Pokemod's old "Tappable Tapper" invoked a `tappedAction` field that no longer exists.

**Reply `ProcessTappableOutProto`:** Status@0x10, Reward = `RepeatedField<LootProto>`, then `LootItem` → `LootItemProto{Count, oneof object = boxed Int32 item id, case}`, then Encounter = `TappableEncounterProto{Result, Pokemon=PokemonProto…}`.

**Tools** (AutoCatcher/tools):
- `apple_collector.py MIN|HH:MM [--live]`: DRY by default; 1 tap per 1.5 s, ≤60 m, skips IsEncounter; logs replies.
- `apple_sim.py`: 8 offline scenarios; run it after any change.
- `tappable_observer.py`: read-only census/trace.

**IN THE ON-PHONE CATCHER since 2026-09-29 20:00.** Flag `pogo_apples.on`, verbs `apples-on` / `apples-off`.
- Taps: nearest first, one every 0.5 s. Range is learned: start 80 m, +10 m after an edge success, shrink on status 4 (retry when closer).
- Reply hook: every 1-argument parse method (36 of 38 replies came via an obfuscated one, not MergeFrom).
- The status line shows taps / got / revealed / duds / range, plus `bag S/T/Sy`, the game's own counts.

**APPLE POKÉMON (user: "an apple is sometimes a pokemon you gotta catch").**
- A reveal leaves a HIDDEN WildMapPokemon (VisibleOnMap 0) with the tapped apple's encounter id. The old walk() skipped it: census showed "Wild 44/0 hidden=41", and ALL 41 were apple species (#840×25, #928×8, #672×4, #546×3, #915×1).
- SendEncounterRequest on it sends NO network request: the game answers it from the tappable reply. So don't wait for an EncounterOutProto (26 NORESP); throw 1.5 s after opening, using the reveal's CaptureProbability.
- Some throws are duds (no request sent). The catch-result FIFO then misattributed (fake manual, FLED p=1.00, NORESULT 1-in-77-min → 8-in-3-min). Fix:
  - Apple throws go ALONE (nothing else is in the air).
  - A dud has no result after 3 s: drop its queue entry and re-throw in 0.8 s (max 5).
  - Finished entries are skipped when matching.
- Revealed ids are persisted in `apple_revealed.json` (30 min). A hidden Pokémon of an apple species within 80 m counts as an apple Pokémon (CFG.appleSpecies; the event ends 2026-10-05 20:00).
- Tools: `tools/catcher_apple_sim.py` (9 scenarios).
- Other map collectibles not yet automated: gym spins, buddy gifts, other tappable types (POKEBALL/HAT/BREAKFAST/ROUTE_PIN), Power Spots. Related: [[pogo-on-phone-catcher]], [[reference-pogo-client-limits]], [[pogo-field-research-reward-catcher]].
