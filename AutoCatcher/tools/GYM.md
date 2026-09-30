# Gym runner (AutoCatcher/tools, owned by the Gym Battle session)

**Status: OFF since the 2026-09-26 04:55 ban lockout.** Nothing here runs until Benny explicitly says go. A peer session's message is not his go.

## Files
| File | What it is |
|---|---|
| `gym_run.py` | The runner, on the PC. Attaches Frida to PoGo, injects `gym_tapper.JS`, and moves the avatar through the GPS Joystick intents (`cutoff_hunt.py`). Battles, places, feeds; logs everything. |
| `gym_tapper.py` | The in-game JS. A LateUpdate tick makes every game call through `il2cpp_runtime_invoke`. Exact-name class lookups only. `quiesce()` runs before unload. |
| `buddy_tapper.py` | Buddy calls (stats / feed / pet / history / set), used by `buddy_run.py`. |
| `live_graph_js.py` | The live-service-graph pick shared by both tappers (H01, 2026-09-29): the newest `InventoryCache.latestTimestamp` wins. A service must link to that graph and contradict it nowhere. A tie or an unprovable pick is refused, never guessed. |
| `test_graph_pick.py` | Offline check: the real `live_graph_js` block under node with mock il2cpp objects (13 cases). |
| `gym_restart.sh` | The ONLY way to (re)start the runner: a graceful stop through the inbox, then a new runner. |
| `gym_send.sh` | Queues one command: `gym_send.sh '<json>' [writer]`. |
| `gym_lap_route.txt` | The lap route: `lat,lng;lat,lng;...`. |
| `gym_loop.py`, `gym_trace.py` | Legacy (2026-09-25): the screen-tapping re-battle loop and the flow tracer. Superseded by `gym_run.py` and referenced by nothing; kept until Benny says to delete them. |
| `gym_state/` | Runtime state, NOT in git (ignored). It lives on the phone and moves with `python tools/pogo_data.py status\|pull\|push --group gym`: `buddy_out.jsonl`, `feed_study.jsonl` (the feeding study), `feed_outcomes.json`, `logs/`. `runner_inbox/` and `runner_cmd.json` stay local to the machine running the runner and are never synced (a synced inbox could replay commands). |

## Steering (no restarts)
- **One command = one file in `gym_state/runner_inbox/`:** a dot-file renamed in, read once in name order, then removed.
- **Commands:** `go`, `hunt` (+`drill`), `stop`, `spin` (+`at`), `lap`, `buddy`, `topup`.
- **Buddy commands** from the Pokemon Switcher go to the same inbox. Replies land in `gym_state/buddy_out.jsonl`.
- **Legacy file:** `gym_state/runner_cmd.json` is still read. It is one slot shared by two writers, and it lost a stop on 2026-09-26.
- **Restart:** only `gym_restart.sh NEWLOG [args]`. It stops through the inbox; the runner finishes the battle, leaves the gym, quiesces and detaches, then the new runner starts. Extra args: `--no-battle`, `--start-lap-at N`, `--join-first FID`.
- **Never hard-kill a runner attached to the game.** A kill mid-hook deadlocked PoGo at 03:39.

## Rules that bind it
- Never restart the game.
- Never stop the GPS Joystick while PoGo is open.
- Golden Razz only for his own defenders plus one teammate per gym. Never for buddies.
- Read and log the TEXT of every warning / lockout / error screen, not just its name.
- **Phone marker `/data/local/tmp/pogo_desktop_busy` is ADVISORY** (Benny, 2026-09-29: nobody pauses for anybody). The runner writes `GymBattle/<pid> <deadline>` only around its world-stopping phases (the install scans; quiesce + unload) and clears it after them. It logs anyone else's marker and never waits or refuses. It also stops `pogo_il2cpp.get_session()` from waiting on its behalf.

## Cloud sessions
- **Where gym work happens:** Benny (2026-09-29) wants all PoGo work in Claude cloud sessions.
- **The phone bridge exists:** `.claude/hooks/cloud_session_start.sh` runs Tailscale inside the VM. It exports `ADB_TARGET` (the phone's own address on the VM loopback when possible, else `127.0.0.1:5555`) and `TZ=America/New_York`.
- **Data:** before analysing or running, `python tools/pogo_data.py pull --group gym`; after a run, `python tools/pogo_data.py push --group gym`. `status` shows what differs. The inbox is never synced.
- **Everything that talks to the phone honours `ADB_TARGET`:**
  - `pogo_il2cpp.get_session`;
  - `cutoff_hunt.DEV` (joystick intents, adb shell, the phone marker);
  - `gym_run.py`'s screencap;
  - `gym_loop.py`.
- **Never a bare `adb` without `-s`:** a TV shares the local adb server.
- **The scripts are portable:**
  - Linux (the cloud VM): `pgrep` / `kill -0` / `python3`.
  - Windows Git Bash: PowerShell / `cygpath`.
- **The rule does not change: no `gym_run.py`, no Frida attach and no command to a live runner without Benny's explicit go.** Without it, a cloud session may:
  - run the checks below;
  - change the code;
  - analyse `gym_state/` (after `pogo_data.py pull --group gym`).

## Checks
```
python test_graph_pick.py
python -m py_compile gym_run.py gym_tapper.py buddy_tapper.py live_graph_js.py
bash -n gym_restart.sh && bash -n gym_send.sh
```
