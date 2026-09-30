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
| Phone | Toggles | flag files `/data/local/tmp/pogo_{catch,spin,tap,perfect,apples}.on` (content `1`/`0`), the Auto-Catcher app, or `catcher_ctl.sh <feature>-on/off` |
| Phone | Reward catcher, on demand | `catcher_ctl.sh rewards [--dry]` → `reward_phone.py` → `reward_catcher.py` |
| **Desktop** (Windows, via adb over Tailscale) | Reward catcher, research probes, map recorders, analysis | `reward_catcher.py`, `tools/*.py` (attach through `pogo_il2cpp.get_session`) |
| **Cloud clone** | Code and analysis ONLY | no phone, no adb, no Frida: never deploy, attach or toggle from the cloud |

The desktop `pogo_il2cpp.py` is AutoCatcher's own copy. The phone has its own `pogo_il2cpp.py`, and `catch_phone.py`
points `get_session` at the local gadget (`127.0.0.1:27047`, `dev.attach("Gadget")`).

## For cloud sessions

A cloud session cannot reach the phone: it has no Tailscale, adb or Frida. It edits code, runs the offline sims and
analyses the data. Every step below needs the **phone bridge**, i.e. the PC that has adb over Tailscale:

- **Deploying to the phone:** `deploy.sh`, and anything that pushes to `~/pogo` or `/data/local/tmp`.
- **Toggling or restarting the catcher:** `catcher_ctl.sh`, and the flag files.
- **Every desktop tool that attaches to the game:** `reward_catcher.py`, `tools/*` probes, recorders and collectors (they
  go through `pogo_il2cpp.get_session`).
- **Reading the phone's logs:** `catch_loop.log`, `pogo_state.txt`, `flags.log`.

Before trusting any number from the phone, re-read the game's own records through the bridge.

## Deploying to the phone

```bash
./deploy.sh system/scripts/game_write/catch_loop_fast.py catcher_ctl.sh      # md5-verified push, owner kept as Termux
./deploy.sh --restart system/scripts/game_write/catch_loop_fast.py           # ... then restart the catcher (~1 s)
```

`deploy.sh` needs Git Bash (it uses `cygpath`), adb, and root on the phone. After a deploy, delete
`~/pogo/system/scripts/game_write/__pycache__/catch_loop_fast*.pyc`.

Verify on the phone:
- the `attached ...` line in `~/pogo/system/analysis/pokemod/catch_loop.log`;
- `catcher_ctl.sh status`.

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
