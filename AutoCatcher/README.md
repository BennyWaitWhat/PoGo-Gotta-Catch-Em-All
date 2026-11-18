# AutoCatcher

On-phone automation for Pokémon GO on a rooted Pixel 9 Pro. It catches wild, lure and incense Pokémon, taps event map
tappables (apples), spins stops, clears Field Research reward encounters, and reports when the server is refusing
actions. The code attaches to the game's Frida gadget and calls the game's own methods. Nothing forges server requests.

Owner: the **AutoCatcher** Claude session. `tools/gym_*.py`, `tools/buddy_tapper.py`, `tools/live_graph_js.py` and
`tools/test_graph_pick.py` belong to the **Gym Battle** session. `../pogo_extract/` (the bag database, culls and tags)
belongs to the **Pokemon Inventory** session. No session edits another's files.

## What runs where

| Where | What | Entry point |
|---|---|---|
| **Phone** (Termux, always on) | The catcher: wild/lure/incense catching, apples, auto-spin, limit detection | `system/scripts/game_write/catch_loop_fast.py`, run by `catch_phone.py` → `run_catch.sh` → `catcher_ctl.sh` |
| Phone | Toggles | flag files `/data/local/tmp/pogo_{catch,spin,tap,perfect,apples}.on` (content `1`/`0`), `pogo_berries.on` (`1` = Pinap and Razz, `pinap`, `razz`, anything else = none) and `pogo_dust.on` (Catch only: a whole number; `0`, no file or anything else = catch everything, `N` = only species whose base catch stardust is N or more, plus every shiny); the Auto-Catcher app (its switch tiles, its Catch only bar and its Berries bar); or `catcher_ctl.sh <feature>-on/off`, `catcher_ctl.sh berries-off / berries-pinap / berries-razz / berries-on` and `catcher_ctl.sh dust-off / dust-500 / dust-700 / dust-1000` (any `dust-<whole number>`). The berries and dust verbs write the flag and nothing else |
| Phone | Reward catcher, on demand | `catcher_ctl.sh rewards [--dry]` → `reward_phone.py` → `reward_catcher.py` |
| Phone → PC | CULL NOW button (app 1.2, 2026-11-05) | the app writes `/data/local/tmp/pogo_cull.req` as root; the PC's `pogo_extract/cull_button.py` (Pokemon Inventory) runs one cull per tap and writes `/data/local/tmp/pogo_cull_status.txt`, which the app shows |
| Phone | Gym Battle switch (app 1.3, 2026-11-18) | `/data/local/tmp/pogo_gym.on` (`1` = on, anything else off). The gym runner runs on the phone under its own supervisor, `~/pogo/run_gym.sh` (Gym Battle's file, see `tools/GYM.md`). The app's switch or `catcher_ctl.sh gym-on` writes the flag and starts the supervisor when it is not alive (no `run_gym.sh` on the phone: nothing is started). `gym-off` writes the flag and NOTHING else: the supervisor watches the flag and stops its runner by itself, and nothing here ever kills a gym process. `catcher_ctl.sh reconcile` (the boot hook) starts the supervisor again when the flag was left on. The catcher is blind to all of it: `running()` / `stop_proc` / `run_catch.sh` count neither the flag nor the gym processes. The runner writes ONE status line (`HH:MM:SS ...`, `STOPPED: ...` when it gave up) to `/data/local/tmp/pogo_gym_status.txt`, which the app shows under the switch. Switch on and that file older than 60 s, or missing: the app says the gym runner is not answering. Switch off: an old line is not shown |
| **Cloud session** (Linux VM, the phone via the bridge) — the default place for AutoCatcher work | Everything the desktop does: deploys, toggles, reward catcher, probes, analysis | same files; `ADB_TARGET` is exported by the session hook |
| **Desktop** (Windows, adb over Tailscale) — fallback | Same as the cloud | `reward_catcher.py`, `tools/*.py` (attach through `pogo_il2cpp.get_session`) |

The desktop `pogo_il2cpp.py` is AutoCatcher's own copy. The phone runs its own, older `pogo_il2cpp.py`. Git keeps it
as `ondevice_toggle/phone_pogo_il2cpp.py`. `catch_phone.py` points `get_session` at the local gadget
(`127.0.0.1:27047`, `dev.attach("Gadget")`).

`ondevice_toggle/` holds the phone-side setup:
- the phone's own library, `phone_pogo_il2cpp.py`;
- the Auto-Catcher app (`apk/`; `apk/build.ps1` builds it, run it in PowerShell 7). `adb shell am instrument -w 'com.benny.autocatcher/.MainActivity$RenderProbe'`
  draws its screen off screen into two PNG files in the app's own files folder, without opening the app (add `-e demo 1`,
  `2` or `3` for a made-up state, `-e help 1` for the fold-out);
- the Termux:Boot starter `20-pogo-catcher.sh`;
- the gadget's listen config `config.listen.so` (the same bytes as the phone's live `/data/local/tmp/re.zyg.fri/libgadget.config.so`);
- the phone guide `AUTO_CATCHER_PHONE.html`;
- the Termux build and repair scripts.

The June config-swap toggles and installers are retired and not in git. They force-stopped PoGo, switched the gadget out of
listen mode, wiped `~/pogo` or wrote Magisk root grants. Their phone copies are in `/data/local/tmp/retired_2026-09-29/`.

## For cloud sessions

Cloud sessions reach the phone through the **bridge** that `.claude/hooks/cloud_session_start.sh` sets up. It runs
Tailscale in userspace mode and forwards the phone's adb port onto the VM's loopback: the phone's own address
`100.98.158.56:5555` when it can bind it, otherwise `127.0.0.1:5555`. It exports `ADB_TARGET` (and
`TZ=America/New_York`). Every tool here reads `ADB_TARGET`, so deploys, toggles, the reward catcher, probes and
recorders all work from the cloud, with the same rules as on the PC:

- **Crash rules** (below) and the **phone-access rules** apply unchanged. Nobody pauses anything for anyone; the busy
  marker is advisory.
- **Data:**
  - The catcher's logs, map data and recordings are not in git. They live on the phone in
    `/data/local/tmp/pogo_data/catcher.tar.gz`. Get them with `python tools/pogo_data.py pull --group catcher`.
  - After a run that changes them, save them back with `python tools/pogo_data.py push --group catcher`.
  - `system/analysis/game_limits.json` (the game's Google Maps key) is never shipped.
- **Before trusting any number,** re-read the game's own records from the phone (bag counts, the catcher's status line).
- If the bridge is down (`adb -s "$ADB_TARGET" get-state` is not `device`), do code and analysis only. Never guess at the phone's state.

## Deploying to the phone

```bash
./deploy.sh system/scripts/game_write/catch_loop_fast.py catcher_ctl.sh      # md5-verified push, owner kept as Termux
./deploy.sh --restart system/scripts/game_write/catch_loop_fast.py           # ... then restart the catcher (~1 s)
```

`deploy.sh` runs on Linux (the cloud VM) and on Git Bash (it uses `cygpath` only when it exists). It needs `adb`,
`md5sum` and root on the phone, and it honours `ADB_TARGET`. It also deletes the phone's stale
`__pycache__/*.pyc` for every `.py` it deploys.

`deploy.sh` puts `ondevice_toggle/phone_pogo_il2cpp.py` at `~/pogo/pogo_il2cpp.py`. It refuses the desktop
`pogo_il2cpp.py`, which has never run on the phone.

Verify on the phone:
- the `attached ...` line in `~/pogo/system/analysis/pokemod/catch_loop.log`;
- `catcher_ctl.sh status` (read only; it prints `proc=up catch=1 spin=1 perfect=0 tap=0 apples=1 gym=0 berries=pinap dust=0`).

## Crash rules (each one is a PoGo crash we had)

1. Every managed call into the game runs on **UnityMain**, inside the `CameraFollowingGround.LateUpdate` pump. A C
   (CModule) gate enters JS every 6th frame. RPC exports may only set flags or read caches.
2. Every `NativeFunction` uses `{exceptions: 'propagate'}`. Frida's default steals ART's own faults, and the next GC then crashes.
3. The object lookup (Unity liveness walk) runs **in C with the world stopped**. There must be no JS inside the stopped world:
   Frida has one JS lock for every script in the gadget.
4. No game pointer outlives the tick that read it. Track things by id, and re-validate klass and fields before acting.
5. CModule static variables are read-only in this gadget. Keep state in JS-allocated buffers.
6. Never restart or force-stop PoGo from a tool. Never attach to a cold-starting PoGo.
7. **The live service graph:** the game can rebuild its services in-process, and the old copies answer with frozen
   data. Pick the copy whose `InventoryCache.latestTimestamp` is newest (`pickLive` in the catcher, `live_graph` in
   `pogo_il2cpp.py`).

## Phone access between sessions

- **The busy marker (advisory).** `/data/local/tmp/pogo_desktop_busy` holds `"<name> <epoch-seconds>"`. Every desktop Frida attacher writes it
  before attaching and holds it while attached (`pogo_il2cpp.get_session` does this). A foreign live marker is only
  logged: nobody waits on it or refuses ("no one should be pausing anything for anyone"). The on-phone catcher is exempt.
- **The pause handshake.** `/data/local/tmp/pogo_pause` holds an epoch deadline. The on-phone catcher detaches until it
  passes. Only the reward catcher uses it; culls run alongside the catcher.
- **Contract with the cull.** Keep the `^HH:MM:SS CATCH ` log line format, the log path
  `~/pogo/system/analysis/pokemod/catch_loop.log`, and `caught=` in `/data/local/tmp/pogo_state.txt`. Tell the Pokemon
  Inventory session before changing any of them.

## The legendary skip list (`CFG["legendary"]` in `catch_loop_fast.py`)

The catcher skips every species in this hand list (`walk()` runs `finish(enc, 'legendary')` before `priority` and before any
catch); a species that is not listed is auto-thrown at, up to 12 balls. The list mirrors the client game master's
`pokemonClass` LEGENDARY / MYTHIC / ULTRA_BEAST (111 dex today).

- **2026-09-30 (Benny: "fix it"):** added the six Paradox legendaries the list had missed: 1009 Walking Wake, 1010 Iron Leaves,
  1020 Gouging Fire, 1021 Raging Bolt, 1022 Iron Boulder, 1023 Iron Crown. **Code only: it ships at the next deploy, which needs
  Benny's go.** Nothing was deployed or run.
- **144 / 145 / 146 stay out on purpose.** The Galarian birds are in `CFG["priority"]` (opened first, best ball), and the skip runs
  before it, so listing them would skip them.
- **Drift guard:** `pogo_extract/audit_gamemaster.py` (check 1b, one of the 11 audits in the cull gate) parses the list from the
  catcher's source text with `ast` (the catcher is never run) and BLOCKS when the game master classes a LEGENDARY / MYTHIC /
  ULTRA_BEAST dex that is missing, except 144 / 145 / 146. It only WARNs about a listed dex the game master does not class so.
  When a game master refresh brings a new legendary, add its dex to the list; the audit passes from the source text alone, no deploy needed.

## Offline tests (run after changing the logic)

```bash
python tools/catcher_apple_sim.py    # apple tapping decisions (9 scenarios)
python tools/reward_sim.py           # reward catcher state machine (4 scenarios)
python tools/apple_sim.py            # desktop apple collector
```

They need `node`. Desktop Python needs `frida` (17.x) and `s2sphere`.

## Hard limits (the user's standing rules)

- Never release or transfer a Pokémon. The user releases in game.
- Never use Golden Razz (706) or Silver Pinap (708) when catching.
- Never change phone system settings without asking.
- No game automation without the user's explicit go, after the 2026-09-26 lockout.
