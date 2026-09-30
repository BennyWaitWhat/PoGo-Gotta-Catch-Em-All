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
| `test_gym_stab.py` | Offline check (2026-09-30): `node --check` of the whole tapper script text plus a top-level duplicate-name scan; the real STAB block (the `>>> STAB` / `<<< STAB` markers in `gym_tapper.py`) under node against mock il2cpp objects; `stab_config()`; the runner's STAB report lines. Needs node, not Frida. CI runs it. |
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

## Same-type bonus (STAB): changed 2026-09-30, CODE ONLY
Benny: "fix it". It ships at the next supervised run; every run or deploy still needs his explicit go. Nothing was run, attached or deployed.

The charged-move pick is power x the game's effectiveness label x STAB (x1.2 when the move's type is one of the attacker's two types). STAB never applied: in the 87 gym logs, 327 `charged moves:` readings, damage / power was always 1.0, 1.6 or 0.625, never x1.2 (Palkia: Aqua Tail 50, Draco Meteor 150; with STAB 60 and 180. Mewtwo: Psystrike 95 against Shadow Ball 100; with STAB 114, so the pick changes).
- **Proven cause (from the repo's own live dumps):** `PokemonSettingsProto` names its two types `type1_` @24 and `type2_` @28 (class recon `pogo_extract/_recon_evolve_out.json`, May). The 0.429.1 client dump `AutoCatcher/system/analysis/map_full.json` (2026-09-25) shows the same names (`"uniqueId_": 19, "type1_": 1`). The matcher wanted `type` / `type_` for the first, so `setT1` stayed -1 and `setOffs()` returned null with no log line. The class did match, so the one info line ("attacker settings class") never fired either, which is why none is in any log.
- **Inferred, not provable offline:**
  - `ChargeAttackDisplay` has an `IPokemonSettings` field at all (it was never `need()`-checked);
  - that field holds the ATTACKER's settings and not the defender's (the effectiveness label needs the defender's).
  - The repo history is one import commit, so it is not proven the STAB code was live in those runs. The `moves` line exists from `gym_v2_32` (2026-09-25 23:44).
- **What the tapper does now** (`gym_tapper.py`, the STAB block):
  - the type fields are found by declared type (`HoloPokemonType`, in declaration order), names only break ties;
  - **live** read: the button's settings object counts only when its species is one of our fighting six AND that Pokemon carries the button's move(s), so a defender's settings can never boost the wrong moves;
  - **table** fallback, independent of any live field: the attacker is our fighting six matched by the charge moves on the buttons, its types come from the client game master table the runner hands over (`gym_tapper.stab_config()` reads `pogo_extract/gamemaster_pokeminers.json` and `form_enum.json`; key `dex` or `dex:form`; the game master file is data, not in git, so `python tools/pogo_data.py pull --group inventory` brings it, and without it the runner says so and the live read decides alone). A mega-evolved attacker, a species the table lacks, or candidates that disagree get no boost (the old pick);
  - the multiplier is the live `GymBattleSettingsProto.SameTypeAttackBonusMultiplier` when it resolves, else the game master's 1.2.
  - Any failure in the STAB read leaves exactly the old pick. Pacing, targeting, feeding, deploying and timings are untouched.
- **First supervised run: read these lines to see which path fired:**
  - `same-type bonus (STAB): charge-button settings field(s) @... ; PokemonSettingsProto types @24/@28, species @16; multiplier x1.2 (live | game master | default)`, plus a `!! STAB:` line for anything unresolved;
  - `STAB table from the game master: N typings (... species + ... form overrides)`;
  - every `charged moves:` line now ends `stab xF` per move and `[attacker #dex Name; types: live | table | none (reason); same-type xM]`;
  - `STAB: the charge button settings object is species #N, not the attacker` means that field is the defender's (it is then ignored);
  - `STAB: a charge button has a settings object of another class` names the wrapper class.
  - The `related` fields in the first line list every button field that mentions a Pokemon, with its name: a field called `defenderSettings` answers the attacker/defender question at once.

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
python test_gym_stab.py
python -m py_compile gym_run.py gym_tapper.py buddy_tapper.py live_graph_js.py
bash -n gym_restart.sh && bash -n gym_send.sh
```
