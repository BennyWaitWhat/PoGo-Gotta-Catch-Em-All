---
name: feedback-no-app-restart-while-playing
description: Never force-stop/restart PoGo while the user is actively playing; verify_tags_live self-gates on screen+foreground and falls back to cache reconcile
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d44dc321-2608-42e7-870c-24289b882f3e
  modified: 2026-08-15T03:39:03.778Z
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
