# Gym runner (AutoCatcher/tools, owned by the Gym Battle session)

**Status: OFF since the 2026-09-26 04:55 ban lockout.** Nothing here runs until Benny explicitly says go. A peer session's message is not his go.

## Files
| File | What it is |
|---|---|
| `gym_run.py` | The runner: on the PC (adb), or on the phone itself (Termux, `on_phone.py`). Attaches Frida to PoGo, injects `gym_tapper.JS`, and moves the avatar through the GPS Joystick intents (`cutoff_hunt.py`). Battles, places, feeds; logs everything. `--on-open` = the app's Gym Battle switch (below). |
| `on_phone.py` | The runner ON the phone (2026-11-18). Which side this is: the Termux folder is there, or `POGO_ON_PHONE=1` / `0` says so. There: ONE root shell in place of `adb shell` (`su`, commands on its input), the attach gate read from `/proc`, the session through the game's own gadget (127.0.0.1:27047) by pid. On the PC nothing of it runs. |
| `gym_status.py` | The app's status line from the runner's own log: `python gym_status.py LOG`, `--why LOG` (why an ended runner ended), `--selftest`. |
| `../run_gym.sh` | The Gym Battle switch's supervisor on the phone (below). `run_gym.sh --preflight` = the read-only check after a deploy. |
| `test_gym_awareness.py` | Offline check of the runner's pure decisions (the picker, joins and retakes, cooldowns, `open_plan` for `--on-open`). CI runs it. |
| `test_gym_phone.py` | Offline check of the phone path: `on_phone.py`, the unchanged PC path, the attach gate, `--on-open` stops, `--switch`, `--preflight`, and `run_gym.sh` run under bash against a fake runner. No phone, no game, no Frida. CI runs it. |
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

## The app's Gym Battle switch: `--on-open`, on the phone (2026-11-18, CODE ONLY)
Benny: "any gym i visit and enter it will automatically go drill and finish and place shiny gyrados", then "why cant gym mode work without the PC? i want it working on my phone." Built offline. Nothing of it has run on the phone or against the game: the first run is `run_gym.sh --preflight`, then his first flip.

**What the mode does (`gym_run.py --on-open`).** The runner picks no gym, scans none, walks nowhere and sends the joystick nothing while it waits. A gym HE opens is read (`open_plan`, a pure function):
- an enemy gym: counters, drill until it is empty, a shiny Gyarados in (his highest-CP shinies when no Gyarados is at full HP; at the 20-gym cap it is emptied only);
- an EMPTY gym: the Gyarados goes in at once;
- his team's gym with a free slot and none of his in it: joined, no battle;
- hands off, with one log line that says why: a raid, full, his already in, out of reach, a gym on `--skip`, a deploy lockout, a battle he started himself.

While it works on a gym it holds him there: the 25 m circle, the same joystick WALK as every run. **A route he had running in the GPS Joystick is replaced by that WALK and is not started again**; after the gym the joystick gets nothing more. Berries are off (`--no-feed --no-feed-mate --no-topup`), direct deploy is off, and no revive batch is used while it only waits (the batch at 30 fainted comes with a gym he opens).

**The chain.** App tile -> `catcher_ctl.sh gym-on` / `gym-off` (AutoCatcher's file) -> `/data/local/tmp/pogo_gym.on` (`1` = on) -> `~/pogo/run_gym.sh` -> the runner -> `/data/local/tmp/pogo_gym_status.txt`.
- `gym-on` writes `1` and starts `run_gym.sh` (Termux RunCommandService) when none is alive. `gym-off` writes `0` and nothing else. The boot hook (`reconcile`) starts it when the switch was left on.
- `run_gym.sh` lives only while the switch holds 1. The game is up and no gym runner is alive: it starts ONE, from `~/pogo`:
  `python -u tools/gym_run.py --on-open --no-feed --no-feed-mate --no-topup --switch /data/local/tmp/pogo_gym.on --cmd tools/gym_state/runner_cmd.json --minutes 100000`
  plus one line of options from `gym_state/switch_args.txt`, if that file is there (for example `--one-by-one`).
- A runner that ends is started again. Three runs in a row that each end inside 60 s = `STOPPED: ...` until the switch is set again.
- It starts nothing while the game is closed, while another gym runner is alive on the phone, or while Catch Rewards (`reward_phone.py`) is running (`waiting: Catch Rewards is running`).
- **Off means off, three ways.** The supervisor writes `{"stop": true}` into the runner's inbox (the file `gym_send.sh` writes) and waits for the runner's own exit. The runner reads the switch file itself (`--switch`, once a second), so OFF stops it even when no supervisor is left. `--on-open` waits for a closed game in 10 s slices, so a stop never waits five minutes. Nothing is ever killed, the game is never started or restarted, and none of it writes the switch file.
- **The status line** is `HH:MM:SS text`, at most 90 characters, rewritten at least every 15 s (the app calls it dead after 60 s). The supervisor writes it. While a runner is alive the text is built from the runner's log by `gym_status.py`: `watching for a gym you open | 14/20 in gyms`, `battling NAME: 2 of 4 left`, `Gyarados 3643 placed at NAME (15/20 in gyms)`, `hands off NAME: a raid is on it`, `stopping: ...`. Its last line is `off`.

**On the phone the same `gym_run.py` runs** (`on_phone.py`). Every device command the PC sends through `adb shell` (the joystick's fix and WALK, the Back key, the advisory marker) goes, same text, into ONE root shell. The attach goes through the game's own gadget by pid, behind the same `/proc` gate as on the PC plus "the gadget listens". The PC path is unchanged. The catcher keeps running next to it; nobody pauses for anybody.

**Files on the phone** (all under `~/pogo` = `/data/data/com.termux/files/home/pogo`, owner 10762):
| What | Where | Without it |
|---|---|---|
| code | `run_gym.sh`, `pogo_il2cpp.py` (there already), `tools/gym_run.py`, `tools/gym_tapper.py`, `tools/live_graph_js.py`, `tools/dump_game_limits.py`, `tools/cutoff_hunt.py`, `tools/on_phone.py`, `tools/gym_status.py` | `STOPPED: tools/gym_run.py is not on the phone -- ask Claude` |
| game master | `pogo_extract/gamemaster_pokeminers.json` (20 MB, not in git), `pogo_extract/form_enum.json` | no counter team (the attack rank order fights), no legendary list for the placement fallback, no same-type table |
| attack rank | `tools/gym_state/attack_rank.json` (2.2 MB) | the attack team is the highest CP |
| place handler | `tools/gym_state/pick_handler.json` (45 bytes) | auto-place only if the tapper finds the handler by its shape; else an emptied gym waits for his hand |
| written there | `tools/gym_state/logs/onopen_MMDD_HHMMSS.log` (the 20 newest are kept), `run_gym.log`, `preflight.log`, `runner_inbox/`, `run_gym.lock/`, `cooldown_obs.jsonl`, `gym_reports.jsonl` | |

**Deploy** (from `AutoCatcher/`, with Benny's go; `deploy.sh` copies only into folders that exist):
1. The folders, as root, owned by Termux: `adb -s <phone> shell "su -c 'cd /data/data/com.termux/files/home/pogo && mkdir -p tools/gym_state/logs tools/gym_state/runner_inbox pogo_extract && chown -R 10762:10762 tools pogo_extract'"`
2. `./deploy.sh run_gym.sh tools/gym_run.py tools/gym_tapper.py tools/live_graph_js.py tools/dump_game_limits.py tools/cutoff_hunt.py tools/on_phone.py tools/gym_status.py` (md5-checked, owner 10762).
3. The data files the same way (push, `chown 10762:10762`, compare md5): the two game master files into `~/pogo/pogo_extract/`, `attack_rank.json` and `pick_handler.json` into `~/pogo/tools/gym_state/`. The game master on the phone goes stale after the monthly refresh on the PC: push it again then.
4. `run_gym.sh --preflight` (next paragraph).

**Preflight** (`run_gym.sh --preflight`; read-only, the switch stays as it is). One `PASS` / `FAIL` line per check: python, the nine files, the state folder, the switch file, the status file, root, the game, and that no gym runner, supervisor or reward run is alive. Then `gym_run.py --on-open --preflight`: the attach, the tapper's live reads, auto-place, his Pokemon in gyms, his shiny Gyarados, his six, the gyms on the map, a clean unload (`WARN` = it runs, with less; `SKIP` = not looked at). It presses nothing, places nothing, feeds nothing and sends the joystick nothing. The same lines are kept in `gym_state/preflight.log`; the last line is `PREFLIGHT PASS` or `PREFLIGHT FAIL (n)`. While it runs, a flip of the switch starts no supervisor (`catcher_ctl.sh` takes the check for one): its `NOTE` line says so.

**Rules of the switch.**
- The switch is Benny's: only the app writes `pogo_gym.on`. No session flips it for him.
- One gym runner at a time. A runner on the PC is invisible from the phone: **flip the switch off and wait for `off` before a PC run.**
- To stop it: the switch. `gym_send.sh '{"stop": true}'` stops the runner too, and the supervisor then starts a fresh one while the switch is on. Never a kill.

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

## Attack reports: 3 s by default (2026-09-30)
The runner rewrites `GymBattleSettingsProto.AttackServerInterval` (the game's own value: 5 s) at every attach. It was 1.5 s through the run that ended in the 2026-09-26 lockout (`gym_v2_79`..`86`: "was [5]", then "was [1.5]"). Benny picked the middle ground: `--attack-report` now defaults to **3.0** (20 reports a minute instead of 40; the game sends 12). `--attack-report 0` leaves the game's 5 s alone. No causal link to the lockout is claimed: its screen text is the game's rate-limit string (`suspension_rate_limit_desc`), and nobody knows the trigger. The 3 s knockout windows are unmeasured (5 s gave 4-7 s, 1.5 s gave 2-4 s).
Owner: since 2026-09-30 the cloud session carries the Gym Battle duties (the PC sessions are retiring). Nothing runs without Benny's go.

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
python test_gym_awareness.py
python gym_status.py --selftest
python test_gym_phone.py
python -m py_compile gym_run.py gym_tapper.py buddy_tapper.py live_graph_js.py on_phone.py gym_status.py
bash -n gym_restart.sh && bash -n gym_send.sh && bash -n ../run_gym.sh
```
