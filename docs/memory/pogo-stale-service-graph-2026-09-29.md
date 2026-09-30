---
name: pogo-stale-service-graph-2026-09-29
description: PoGo can rebuild its whole service graph without a restart; cached singletons then read a FROZEN bag/tags -- pick_singleton follows InventoryCache.latestTimestamp for EVERY class, and walk tripwires (rc 8) stop a frozen read
metadata:
  type: project
---
2026-09-29 ~05:00 the game (same pid 5429) rebuilt PokemonBagImpl, TaggingRpcService, PokedexImpl, InventoryCache, PlayerService, RpcHandler. The old objects stayed allocated with their last contents. pogo_il2cpp's per-pid singleton cache (and the "biggest bag wins" live pick) kept reading the OLD graph: 4 culls said "caught 0, released 0", 41 "tagged", stardust 3.9M -- while the in-game Transfer tag showed 0 (he had released them). He: "Its wrong" / "Look at my screen, you're wrong".

**Fix 1 (pogo_il2cpp.live_graph / pick_singleton):** one liveness scan of PokemonBagImpl per session; the live graph = the bag whose InventoryCache.latestTimestamp (ms) is newest. EVERY class now goes through the live graph (matched by its PlayerService / InventoryCache / PokemonBag pointer); no fallback to cache / first hit / biggest value -- an ambiguous pick raises GraphRefusal. `_pick_singleton_live` and the pipeline's `_pick_real_*` pickers are retired. prune_tags re-derives the graph after its verify (`revalidate_graph`; a rebuild mid-pass = "VERIFY VOID").

**Fix 2 (walk_tripwires.py, installed 2026-09-29 17:1x):** every recrawl appends a fingerprint to system/analysis/walk_fingerprints.jsonl and judges it. STOP (pipeline exits 8, full_audit returns 8, nothing written or synced) on corroborated evidence only: CATCH_AFTER_GRAPH (the catcher's own catch_loop.log has a catch > 2 min after the graph's last update and before the read -- would have stopped all 3 frozen passes of the morning), CATCHER_UNSEEN, FROZEN_REPEAT with catches in between, BAG_AHEAD_OF_INV, GRAPH_TS_BACKWARDS, COUNTER_BACKWARDS, INV_BEHIND_BAG, MIXED_GRAPH, GRAPH_UNPROVEN. Age alone (GRAPH_STALE) only WARNs up to 10 min while PoGo is on screen: the catch log shows 19 live gaps > 5 min in 9,006 catches. A WARN walk skips the 2-crawl purge. Preflight stamps carry walk_fp (schema 2); prune refuses a pile whose walk verdict was STOP, or a graph older than / rebuilt since the walk. RETRO_FROZEN names past frozen walks from the .db_snapshots (retro_frozen_seen.json).

**Why:** a plausible-looking stale object passes every sanity probe; only a signal written by another process (the catcher log) or the game's own clock can tell frozen from quiet.
**How to apply:** rc 8 / "FROZEN OR IMPOSSIBLE READ" = re-run after the game has been on screen a minute; if it repeats, PoGo holds an abandoned graph (he relaunches it -- never restart it from a cull). When a cull reports "nothing changed" while he is playing, or his screen disagrees with the report, believe the screen and take a screencap. Related: [[feedback-read-screen-text-not-just-name]], [[reference-fresh-catch-tag-write-lag]], [[pogo-frida-stability]], [[feedback-workflow-hunters-never-edit-live]].

**Gym tools (2026-09-29 20:48, H01-8 from the Inventory session):**
- AutoCatcher/tools/gym_tapper.py: `pickGraph()` = the ItemBagImpl with the newest InventoryCache.latestTimestamp; with 2+ graphs, a tie or an unreadable timestamp is refused.
- `graphPick()` ties BuddyRpcService / BuddyPokemonService / MapPlaceDetailsService to that graph by their PlayerService / InventoryCache / PokemonBag reference; a lone unreferenced instance is taken, anything else is refused ("!!" at startup).
- gym_run bag_status reads only the tapper's bag; the biggest-bag fallback is deleted.
- Tripwire: a confirmed Golden Razz use that never reaches latestTimestamp, with no inventory update for 10 min, turns feeding off and stops the runner cleanly.
- Offline check: `python test_graph_pick.py` (11 cases, the real JS under node).
- NOT yet verified on the phone: whether those services carry a graph reference. The first live run shows it.
