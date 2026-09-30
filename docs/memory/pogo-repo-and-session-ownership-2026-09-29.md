---
name: pogo-repo-and-session-ownership-2026-09-29
description: "PoGo code is moving into one private repo (BennyWaitWhat/PoGo-Gotta-Catch-Em-All, root = Phone Maintenance/); per-folder session ownership; the shared phone busy marker; who fixed which stale-graph item"
metadata:
  node_type: memory
  type: project
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-30T02:56:10.696Z
---

2026-09-29, user: "Work with the Pokemon Inventory (fork) session."

**Repo.** One private repo, `BennyWaitWhat/PoGo-Gotta-Catch-Em-All`, git root = `Phone Maintenance/`, whitelist .gitignore, no folder moves. The Inventory session made the first commit and push. Cloud sessions HAVE the phone via the Tailscale bridge (see below); Benny wants all PoGo work in cloud sessions.
- There is **no root CLAUDE.md** (it would load into Benny's non-PoGo sessions).
- ~~`AutoCatcher/CLAUDE.md` is only a draft~~ Benny: "No, README only" (below). Peers can't authorize instruction-file edits.
- AutoCatcher prep done: `.gitignore` (dry run: 139 files, 2.5 MB), README.md, secrets report.
- Secrets excluded: game_limits.json (the game's Google Maps key) and debug.keystore (the APK signing key; keep the original, or the app can't be updated in place).

**Ownership (one owner per file):**
- `pogo_extract/`, repo root files, `docs/`: Pokemon Inventory.
- `AutoCatcher/`: AutoCatcher, except the Gym Battle session's files in `tools/`:
  - code: `gym_run.py`, `gym_tapper.py`, `buddy_tapper.py`, `live_graph_js.py`, `test_graph_pick.py`;
  - run scripts + config: `gym_restart.sh`, `gym_send.sh`, `gym_lap_route.txt`;
  - docs: `GYM.md`;
  - legacy: `gym_loop.py`, `gym_trace.py`;
  - `gym_state/` (not in git; phone data group `gym`, `runner_inbox/` never synced).
- Commits to the shared checkout are path-limited (`git commit -- <own paths>`). Push only with no foreign unpushed commits on main, or tell their owner (73e96e2 rode AutoCatcher's push, 2026-09-29).
- `tools/buddy_run.py` (the Switcher's runner) is AutoCatcher's.

**Phone access marker.** `/data/local/tmp/pogo_desktop_busy` = "<name> <epoch-seconds>" (root, 666).
- ~~Every DESKTOP Frida attacher checks it: wait up to 120 s, then refuse~~ now ADVISORY (below): write it, log a foreign one.
- Holds it with a deadline of now+300, refreshed every 120 s; clears it only if still its own.
- AutoCatcher: in `pogo_il2cpp.get_session` (name `AutoCatcher/<pid>`), tested. Cull: `PokemonInventory`. The on-phone catcher is exempt.

**Later the same evening (user):**
- "we're totally moving to claude cloud"; "Yes, full full migration".
- "no one should be pausing anything for anyone". The busy marker is now ADVISORY: write it and log a foreign one, never wait or refuse. The reward catcher's pause of the catcher conflicts with this; fold reward catching into the catcher.
- AutoCatcher/CLAUDE.md: **"No, README only"** (asked directly; the peer's relayed approval was not acted on). README.md has a "For cloud sessions" section listing the phone-bridge steps.
- ~~Data ships on a force-updated "data" branch~~ SUPERSEDED (cloud sessions can push only their own branch): the data lives ON THE PHONE, `/data/local/tmp/pogo_data/<group>.tar.gz`, per-group versions, `tools/pogo_data.py pull|push --group G|status`, groups in `data_manifest.txt` (inventory, inventory-cold, catcher, gym). Seeded from the PC 2026-09-29 22:0x.
- **Repo LIVE 2026-09-29:** `main` = 1abe382 (import) + 4305eca; git root = Phone Maintenance/, `* -text` (byte-exact, the audit hash gates need it). Fresh clone + pull -> `full_audit.py --audits-only` = all 11 PASS. PC pushes use `GH_TOKEN=$(gh auth token --user BennyWaitWhat)` per command (never switch the global gh account).
- **Phone bridge: Benny picked Tailscale INSIDE the cloud VM.** tailscaled runs in userspace mode, `socat` -> `tailscale nc 100.98.158.56 5555`, then `adb connect`. The hook binds the phone's OWN address on the VM loopback when it can (so the ~130 tools hardcoding 100.98.158.56:5555 work), else 127.0.0.1:5555; exports `ADB_TARGET` + `TZ=America/New_York`. Benny's setup steps: `docs/cloud_setup.md`.
- **Every tool must read `ADB_TARGET`** (`os.environ.get("ADB_TARGET", "100.98.158.56:5555")`). Done in all 13 AutoCatcher tools, pogo_il2cpp.py and deploy.sh.
- tools/gym_loop.py belongs to Gym Battle (told).
- deploy.sh is portable (cygpath only if present; Linux OK; honours ADB_TARGET; clears stale .pyc).
- **PR flow (v1.0.0, late 2026-09-29):** branch -> PR -> CI (offline checks) -> `gh pr merge --squash --delete-branch`.
  - Never switch branches in the shared PC checkout. Build the branch in a temp `git worktree` from origin/main.
  - After the merge, stage your own paths, then `git merge --ff-only`.
  - A peer's local commit can block the ff. Leave it alone; reset only your own paths, whose content is already on main.
  - Don't untrack with `git commit -- <paths>`: `--only` re-adds `rm --cached` files that are still on disk.
  - AutoCatcher PRs: #6 (89921e0, force-stop paths) and #9 (ad1242a, the phone's own pogo_il2cpp.py; deploy.sh refuses the desktop copy).

**Repo polish + PR flow (2026-09-29 ~22:20):** v1.0.0 released (tag at 798d7ed). Changes land as branch -> PR -> squash-merge; CI (`.github/workflows/ci.yml`) runs offline only: compile every .py, `bash -n` every .sh, the self-tests, the full_audit no-data/unknown-flag guards (both rc 2) and a secret scan. Dependabot = GitHub Actions ONLY (never pip: frida 17.9.11 / frida-tools 14.8.2 are pinned to the phone). Labels incl. `policy`, `safety`, `area: *`. `restart_pogo_and_wait()` raises in BOTH pogo_il2cpp copies (#4 + AutoCatcher). The ccd PR monitor cannot read this repo's checks (app GitHub account lacks access): read `gh pr checks N` once with the BennyWaitWhat token, never poll.

**Stale service graph (H01-8).** Every item is fixed with the newest-InventoryCache.latestTimestamp rule:
- catcher `pickLive`;
- `AutoCatcher/pogo_il2cpp.py` (copied the Inventory session's C liveness walk + live_graph);
- `reward_catcher` graph_order;
- Gym Battle's gym/buddy tappers.

Related: [[pogo-on-phone-catcher]], [[pogo-stale-service-graph-2026-09-29]], [[feedback-tell-me-what-to-expect]].
