---
name: autocull-disabled-2026-09-22
description: "The autocull daemon is OFF (user 2026-09-22: 'kill all the background stuff. i am only culling with you for now'). Culls happen only when he asks me; no heartbeat, no background passes."
metadata:
  node_type: memory
  type: project
  originSessionId: 8fde11a7-6340-4cdf-8f4e-02a95910c52b
  modified: 2026-09-22T18:22:38.501Z
---

Stopped `autocull_watch.py` and `dashboard.py`, and removed the login launcher
`%APPDATA%\...\Startup\start_autocull.vbs` (Recycle Bin; a byte-identical source copy lives at
`pogo_extract\start_autocull.vbs`). No Windows or Claude scheduled tasks ever ran culls. Phone side: only the
Pokemod app runs; the on-phone catcher was not running. Tailscale untouched.

**Consequences:** `autocull_watch.log` stops growing -- it is no longer a heartbeat, and there is no daemon pass
to collide with before a phone attach. `full_audit.py` starts the dashboard itself (`ensure_dashboard`) and that
dashboard then keeps running until killed -- so STOP it after every cull (after gen_artifacts.py, which is offline):
he wants nothing of ours running in the background. The phone-button page (/m) only works while it runs.

**How to apply:** do not restart the daemon or re-add the launcher unless he asks. To re-enable: copy
`pogo_extract\start_autocull.vbs` back into the Startup folder (or run it once). Related:
[[feedback-one-phone-pass-not-three]], [[project-keep-config-dashboard]].
