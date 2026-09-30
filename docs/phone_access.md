# Phone access — who attaches what

One game on one phone, several sessions and tools. **Benny's rule (2026-09-29): "everything should be working while each tool is in
there. no one should be pausing anything for anyone."** Tools overlap by design; nobody waits, refuses or pauses for another.

## The plumbing
- **Cloud:** the SessionStart hook runs `tailscaled` (userspace), pipes `socat` → `tailscale nc 100.98.158.56 5555` and runs
  `adb connect`. The bridge listens on the phone's own address (`100.98.158.56:5555`, added to the VM's loopback) when the VM allows it,
  else on `127.0.0.1:5555`. `ADB_TARGET` is exported either way; every current tool reads it (default `100.98.158.56:5555`).
  Always `adb -s "$ADB_TARGET"`.
- **Frida:** the game runs a Frida gadget injected at zygote fork (ZygiskFrida). Desktop tools `adb forward tcp:27047` and attach to
  `127.0.0.1:27047` through `pogo_il2cpp.get_session()` (connect + forward + readiness gate + attach). Each copy of `pogo_il2cpp.py`
  (`pogo_extract/`, `AutoCatcher/`) belongs to its folder's owner.
- **On-phone catcher:** runs inside the phone (Termux), attaches to the same gadget locally, and needs no bridge. It never stops for us.

## Who attaches what
| Actor | Owner | When |
|---|---|---|
| The cull (`pogo_extract/full_audit.py`: walk, tag sync, post tags) | Pokemon Inventory | When Benny says "cull" (or asks for a read-only walk). One pass per ask |
| Other `pogo_extract` tools that attach | Pokemon Inventory | On Benny's go |
| AutoCatcher desktop tools, `deploy.sh`, `catcher_ctl.sh` | AutoCatcher | On Benny's go; anything that acts in the game needs an explicit go |
| Gym and buddy runners, tappers | Gym Battle | Explicit go every time (2026-09-26 lockout) |
| The on-phone catcher | AutoCatcher | Always running; toggled by its flag files |

## The busy marker — ADVISORY
`/data/local/tmp/pogo_desktop_busy` = `<name> <epoch-seconds deadline>` (phone clock). Every desktop attacher writes its own name with a
deadline ≤ 300 s ahead, refreshes it while attached, and clears it on exit only if it still names itself. A foreign live marker is
**logged and reported, never waited on, never a reason to refuse**. It exists so a crash or oddity can be traced to who was attached.
Implementations: `pogo_extract/pogo_il2cpp.phone_busy_acquire`, `AutoCatcher/pogo_il2cpp.py`. The on-phone catcher is exempt.

## Rules of the road
- Tell Benny what a phone step will do before it starts (which step attaches, roughly how long, PoGo must stay open), unless he just
  asked for exactly that ("cull" is the go for one cull).
- One pass per go. Never re-run a failed pass while the game is restarting; never attach-probe in a retry loop.
- Attach only when PoGo is attach-safe (`pogo_il2cpp.wait_ready_to_attach()`: libil2cpp mapped, process older than 45 s).
- Never restart, force-stop or relaunch PoGo; never stop GPS Joystick or Pokemod while PoGo is open; never change system settings.
- Contract the cull relies on (tell Pokemon Inventory before changing it): the `^HH:MM:SS CATCH ` lines of
  `~/pogo/system/analysis/pokemod/catch_loop.log` and `caught=` in `/data/local/tmp/pogo_state.txt` (read by `walk_tripwires.py`).
- The pause file `/data/local/tmp/pogo_pause` (the catcher detaches while its deadline is in the future): the cull never sets it
  (`full_audit.CATCHER_PAUSE_ENABLED = False`). AutoCatcher's reward catcher used it; under the no-pausing rule, reward catching is
  being folded into the catcher itself (AutoCatcher owns that).
