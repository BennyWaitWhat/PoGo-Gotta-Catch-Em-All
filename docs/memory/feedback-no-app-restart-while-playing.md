---
name: feedback-no-app-restart-while-playing
description: Never force-stop/restart PoGo while the user is actively playing; verify_tags_live self-gates on screen+foreground and falls back to cache reconcile
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d44dc321-2608-42e7-870c-24289b882f3e
  modified: 2026-09-30T02:57:04.142Z
---

User (2026-08-14): "Stop crashing the app everytime you do an audit, its annoying." The audit cycle's
`verify_tags_live.py` force-stops PoGo for the genuine server-refetch proof, which killed the user's
session mid-play every audit.

**Why:** The restart is invisible when the phone is idle, but eats the user's game session when they
are in the app. Server-proof matters ([[pogo-tag-system-2026]]: cache reads false-PASS), but not at the
cost of killing an active session — defer it instead.

**How to apply:** `verify_tags_live.py` now self-gates: screen interactive (`dumpsys power` mWakefulness=Awake)
AND PoGo is topResumedActivity (`dumpsys activity activities`) → skip the restart, do a cache-only
reconcile, print honestly that it is NOT server proof; re-run later when idle (or `--force` if the user
explicitly wants hard proof now). Idle phone → full restart-verify as before. Same principle for any
other tooling: never `am force-stop` / kill PoGo while the user is foregrounded in it; recrawl/sync
attach without killing and are fine.

**2026-09-25, NEVER, EVER:** "the cull should never restart the game. ever."
- `verify_tags_live.py` is cache-only now: `cache_only = True` always, and `--force` no longer restarts.
- `restart_pogo()` raises.
- The dashboard's verify button relabelled to match.
- Reasons: the auto-catcher runs on the game, and Pokemod has to be the one that launches PoGo.
- The "server proof" restart is gone for good. Tag truth comes from prune's fresh-walk verify plus the sync's reconcile.
- Never re-add a force-stop or relaunch to any cull path.

**2026-09-29: no tool in git kills or launches PoGo.** Cloud sessions reach the phone now.
- `restart_pogo_and_wait` raises in all three copies: pogo_extract (PR #4), AutoCatcher desktop (#6), and the phone's
  own `ondevice_toggle/phone_pogo_il2cpp.py` (#9; deployed to the phone 2026-09-29 ~23:00, md5 3fa661a3).
- `tools/joystick_round.py` refuses while PoGo is open. The user closes and reopens the game.
- The June toggles and installers are untracked; their phone copies are in `/data/local/tmp/retired_2026-09-29/`.
- `docs/START_HERE.md` section 4: "Never restart, force-stop or relaunch PoGo." A new tool must not add any of these.
