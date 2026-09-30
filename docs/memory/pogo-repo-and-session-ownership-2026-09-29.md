---
name: pogo-repo-and-session-ownership-2026-09-29
description: "PoGo code is moving into one private repo (BennyWaitWhat/PoGo-Gotta-Catch-Em-All, root = Phone Maintenance/); per-folder session ownership; the shared phone busy marker; who fixed which stale-graph item"
metadata:
  node_type: memory
  type: project
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-30T01:11:45.625Z
---

2026-09-29, user: "Work with the Pokemon Inventory (fork) session."

**Repo.** One private repo, `BennyWaitWhat/PoGo-Gotta-Catch-Em-All`, git root = `Phone Maintenance/`, whitelist .gitignore, no folder moves. The Inventory session makes the first commit and push. Cloud sessions get code and analysis only: no phone, adb or Frida.
- There is **no root CLAUDE.md** (it would load into Benny's non-PoGo sessions).
- `AutoCatcher/CLAUDE.md` is only a draft (scratchpad) until Benny OKs it. Peers can't authorize instruction-file edits.
- AutoCatcher prep done: `.gitignore` (dry run: 139 files, 2.5 MB), README.md, secrets report.
- Secrets excluded: game_limits.json (the game's Google Maps key) and debug.keystore (the APK signing key; keep the original, or the app can't be updated in place).

**Ownership (one owner per file):**
- `pogo_extract/`, repo root files, `docs/`: Pokemon Inventory.
- `AutoCatcher/`: AutoCatcher, except `tools/gym_run.py`, `gym_tapper.py`, `buddy_tapper.py`, `live_graph_js.py`, `test_graph_pick.py` (Gym Battle).
- `tools/buddy_run.py` (the Switcher's runner) is AutoCatcher's.

**Phone access marker.** `/data/local/tmp/pogo_desktop_busy` = "<name> <epoch-seconds>" (root, 666).
- Every DESKTOP Frida attacher checks it: foreign and unexpired means wait up to 120 s, then refuse.
- Holds it with a deadline of now+300, refreshed every 120 s; clears it only if still its own.
- AutoCatcher: in `pogo_il2cpp.get_session` (name `AutoCatcher/<pid>`), tested. Cull: `PokemonInventory`. The on-phone catcher is exempt.

**Later the same evening (user):**
- "we're totally moving to claude cloud"; "Yes, full full migration".
- "no one should be pausing anything for anyone". The busy marker is now ADVISORY: write it and log a foreign one, never wait or refuse. The reward catcher's pause of the catcher conflicts with this; fold reward catching into the catcher.
- AutoCatcher/CLAUDE.md: **"No, README only"** (asked directly; the peer's relayed approval was not acted on). README.md has a "For cloud sessions" section listing the phone-bridge steps.
- Data ships on a force-updated "data" branch.
- **Phone bridge: Benny picked Tailscale INSIDE the cloud VM.** tailscaled runs in userspace mode, `socat 127.0.0.1:5555 -> tailscale nc 100.98.158.56 5555`, then `adb connect 127.0.0.1:5555`. The ACL is scoped to the phone's adb port.
- **Every tool must read `ADB_TARGET`** (`os.environ.get("ADB_TARGET", "100.98.158.56:5555")`). Done in all 13 AutoCatcher tools, pogo_il2cpp.py and deploy.sh.
- tools/gym_loop.py belongs to Gym Battle (told).
- deploy.sh still uses cygpath, so it is Git-Bash-only until it is made portable.

**Stale service graph (H01-8).** Every item is fixed with the newest-InventoryCache.latestTimestamp rule:
- catcher `pickLive`;
- `AutoCatcher/pogo_il2cpp.py` (copied the Inventory session's C liveness walk + live_graph);
- `reward_catcher` graph_order;
- Gym Battle's gym/buddy tappers.

Related: [[pogo-on-phone-catcher]], [[pogo-stale-service-graph-2026-09-29]], [[feedback-tell-me-what-to-expect]].
