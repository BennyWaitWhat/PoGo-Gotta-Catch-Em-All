---
name: pogo-field-research-reward-catcher
description: "How to auto-clear stacked Field Research (\"Today\") reward encounters UI-free, and the non-obvious gotchas that make or break it."
metadata: 
  node_type: memory
  type: project
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-26T10:54:03.253Z
---

Tool: `system/scripts/game_write/reward_catcher.py` clears stacked Field-Research dangling reward encounters one-by-one on the main-thread pump (`CameraFollowingGround.LateUpdate`). Built + proven this session (cleared ~94 of ~96).

**v3, 2026-09-26 (florandez).** The live copy is `Phone Maintenance/AutoCatcher/`; deploy with `./deploy.sh`. The pogo_extract copy is stale.
- **The run.** The Today view shows **"POKÉMON LIMBO (N)"** = rewards waiting. Cleared 95: box 903→998, +30,068 dust, 216 s. Two more came in 4 min later (the wild catcher completes research).
- **Where the time went** (100 throws for 95 catches):
  - 5 LOST throws cost 48 s (23%), 9–10 s each. v2 waited 3 STUCK cycles before re-throwing at the same encounter id.
  - 8 slow opens cost 40 s (19%).
  - 87 normal catches: median 1.4 s (OPEN_LAG 52 + SETTLE 18 frames).
- **The fix.**
  - Same id comes back AND the box did not rise → re-throw after LOSTWAIT=150 frames.
  - Box rose → the catch is in, the server just hasn't cleared the reward → wait, never throw twice (`slowconf`).
  - **Per-reward cap MAXTHROWS=6**, then skip that type and end as `stuck` with no reconnect.
  - v2 threw FOREVER at a reward that never registers: each throw reset SAMESTALL, so its 6/9 escalation was unreachable.
- **Offline test:** `python tools/reward_sim.py` (node). Lost throw: 364 vs 738 frames; 738 matches the real ~9.5 s. Re-run it after any tick() change.
- **Heap (liveness) lookups** for IapService/PokemonBagImpl now run BEFORE install() hooks LateUpdate (catcher rule 7b).
- **The phone's "Catch Rewards" button silently never ran from 07-26 to 09-26.** reward_catch.log / reward_rounds.jsonl / reward_stdout.log were root-owned, context `app_data_file:s0`. The `>>` redirect failed, and the status sat at "queued". The phone copy was also the old no-`propagate` build.
  - Fixed: `chown 10762:10762` + `chcon u:object_r:app_data_file:s0:c250,c258,c512,c768`.
  - Verified: `catcher_ctl.sh rewards --dry` → "READY".
  - Never create files in the Termux tree as root without this.
- **Box read 1001 after the last reward** (above the recorded 1,000 cap). The game still accepted it. Cap vs. reward rules are unverified.

**Catch path (IL2CPP, holo-game.dll):** `QuestService.GetDanglingEncounterOfType(EncounterType, "")` → `QuestPokemonEncounterProto`; `QuestStateManager.OpenQuestEncounter(proto)` opens it; the actual catch is **`MapPokemon.TryCapture(PokeballThrow, null)` on the `QuestMapPokemon`** — the *same* throw path as wild spawns. (`ResearchEncounter.AttemptCapture` is NOT the path the game uses.) Discovered by tracing the user's manual catches (hook the methods, watch the call order).

**Critical gotchas (each one cost a debug cycle):**
- There are **two `QuestMapPokemon` instances**; only one is active. `find_singleton` picks the wrong one (encounterId=0) → opens but never catches. Capture the live one by hooking `QuestMapPokemon.SendEncounterRequest` (`onEnter: ACTIVE_QMP = args[0]`) — `OpenQuestEncounter` triggers it — then `TryCapture` on `ACTIVE_QMP`.
- **`QuestStateManager` is lazily instantiated only while the user has Field Research / Today open.** After any PoGo restart it's gone → `find_singleton` returns 0 → the script aborts "MISSING a required singleton". Have the user open Field Research first, then launch.
- There are also **two `QuestService` instances** (one empty); probe `GetDanglingEncounterOfType` and pick the one returning non-null.
- **EncounterType values carrying dangling rewards (observed): 4, 5, 6, 10, 13, 23.** Empty questId returns the next dangling of that type; loop types until all null = done.
- **Verify via box** (`PokemonBagImpl.get_PokemonOnlyCount`) — auto-transfer spares reward Pokémon, so box rises by exactly # caught (unlike wild, which auto-transfer masks).
- `OPEN_LAG` = 52 frames (user's choice, 2026-09-20). Timing too tight races → `TryCapture` on a stale QMP → "access violation accessing 0x0" → crashes/restarts PoGo. ~2.5-3s/catch was the v1 floor; **v2 (2026-06-08) hits a median ~1.3s/catch.** The residual tail (periodic 6–15s waits — ~11 of them ate ~47% of a 73-catch round) is **server-side encounter-materialization over Tailscale** (batch refill: one big wait, then a burst of fast catches as the local batch drains), NOT client timing — the STUCK re-probe is already near-optimal there. DON'T trade the fast ~88% away chasing it.
- **Single instance only** — two reward catchers both opening encounters collide and crash each other.
- **Blocked-throw stall — `STUCK=480` frames (~8s) recovery is FAR too slow (user complaint 2026-06-05).** When a throw doesn't register (ACTIVE_QMP not yet captured, or the prior catch's encounterId not yet consumed: `curId===lastId`), the state machine sits in ST1 the whole `STUCK` window before resetting to IDLE → visible multi-second freezes (log gaps of 9–11s between catches). **FIXED 2026-06-08 (v2):** `STUCK` 480→150 frames + a single mid-wait `NUDGE` re-open. Stalled catches now re-probe every ~2.5s instead of freezing ~8s; the fast ~88% are untouched. Caveat for comparing runs: shorter STUCK ⇒ more `STALLS++` per server-wait, so judge by **wall-time / avg-s-per-catch, NOT raw stall count.**
- **No auto-reconnect (unlike `catch_loop_fast.py`/`feed_loop.py`).** Attaches once; a PoGo restart / lossy-Tailscale drop kills it mid-run with `frida.InvalidOperationError: script has been destroyed` (hit at caught=37 on 2026-06-05, pid drifted 26848→5239). Catches bank server-side, so a plain relaunch continues from the remaining danglings. **DONE 2026-06-08 (v2):** outer reconnect loop (budget 8, 3s backoff) — it rode through a full PoGo crash+restart mid-run (round 1 dropped at caught=73, app restarted pid 13629→8094, `no_qsm` until Today reopened, round 6 finished the last 26 → dry) with zero manual touch.

Each reward catch also grants stardust server-side. **Validated 2026-06-05:** full sweep of 94 cleared in two passes (drop at 37, relaunch finished 53), box 4,979→5,073. Stardust **+21,699 (~231/catch)** with a Star Piece active — average sits right at the 1.5× line (un-bonused reward catches avg ~150/catch), confirming **reward catches DO receive the Star Piece bonus**. Read dust via `IapService.get_Stardusts` (pick the **max-value** instance), box via `PokemonBagImpl.get_PokemonOnlyCount`; A/B before/after with `system/scripts/game_read/read_dust.py` (single shot) — run it only when the catcher is detached (Frida collision). Frida RPC name mapping: JS export `setQs` ↔ Python `set_qs` (Frida maps snake_case to camelCase; a JS `setQS` would need `set_q_s`); see [[pogo-adventure-effect-live-registry]]. Related: [[project-pogo-extract]], [[pogo-frida-stability]], [[pogo-server-authority]].

**v2 run 2026-06-08:** 98 reward mons cleared to dry, box 5,087→5,185; stardust **+20,726 (~209/catch; round 6 alone +6,662/26 = 256/catch)** — above the ~150 un-bonused reward baseline, so a Star Piece multiplier was active. Per-round structured logs now land in `system/analysis/pokemod/reward_rounds.jsonl` — one `session` object per attach (reason, caught, elapsed, stalls, min/max/avg + full latency array, dust/box delta) plus an `operation` summary — for afterward self-reflection. Usage is now `reward_catcher.py [MAX] [--dry]`; `--dry` = readiness check (attach + install hooks + read dust/box baseline + probe a dangling, then detach WITHOUT catching). Dust before/after is read in-session now (no separate `read_dust.py` needed).
