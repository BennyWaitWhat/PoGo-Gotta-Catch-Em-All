# START HERE — every PoGo session reads this first

Benny's Pokémon GO tooling for one rooted Pixel 9 Pro. Since 2026-09-29 **all PoGo work runs in Claude cloud sessions**: this repo holds
the code and docs, the phone holds the game data, and each cloud session reaches the phone over Tailscale (the SessionStart hook sets up
the bridge and prints a `PHONE BRIDGE:` line below this page). How Benny wants answers: lead with the action,
number multi-step work, keep lists short (<= 5), restate where things stand, end with one next action.

**First cloud session? Read [`HANDOFF.md`](HANDOFF.md) now — §0: Benny wants a CULL first** (once, while `pogo_data.py status`
shows `inventory` last pushed `by pc-seed`). Also in it: the state of everything at the move (2026-09-29), Benny's pending setup steps, the decisions waiting on him, and what is still unverified in a real cloud VM.

## 1. Which session are you?
| Session | Owns (only the owner edits these) | Read next |
|---|---|---|
| **Pokemon Inventory** | `pogo_extract/`, `pokegenie_work/`, `docs/`, `tools/`, `cloud/`, `.claude/`, root files; data groups `inventory`, `inventory-cold` | `pogo_extract/CLAUDE.md` |
| **AutoCatcher** | `AutoCatcher/` except the gym files below (incl. `tools/buddy_run.py`); data group `catcher` | `AutoCatcher/README.md` |
| **Gym Battle** | `AutoCatcher/tools/gym_*` (scripts, `GYM.md`, `gym_state/`), `buddy_tapper.py`, `live_graph_js.py`, `test_graph_pick.py`; data group `gym` | `AutoCatcher/tools/GYM.md` |

Not sure which one you are? Ask Benny in one line. Need a change in a file you don't own? Write it as a numbered request for its owner.
Then read `docs/memory/INDEX.md` and the notes under "How I should work" and "safety rules": each rule has the incident behind it.

## 2. Start of work
1. Check the `PHONE BRIDGE:` line. Not connected → read `/tmp/pogo_bridge.log` + `docs/cloud_setup.md`, tell Benny what failed in one line.
2. `python tools/pogo_data.py pull` — brings the game data from the phone into this checkout (`docs/data.md`). Nothing that reads game data
   is valid before this.
3. Work in your folder. Phone steps follow `docs/phone_access.md`.

## 3. End of work
1. **Data:** after anything that changed game data, `python tools/pogo_data.py push --group <your group>`. Refused = another session pushed
   since your pull: pull, redo, push. Never `--force` over someone else's work.
2. **Code:** commit on your session branch and push it. Then open a PR to `main` and merge it (`gh pr create --fill` +
   `gh pr merge --squash --delete-branch`) if `gh` works here; if it doesn't, give Benny the branch link and say "merge me". Other
   sessions only see your code once it is on `main`.
3. Never commit data, secrets or anything the `.gitignore` files keep out. `git add` explicit paths, not `-A`.

## 4. Rules that apply to everyone (full text + stories in `docs/memory/`)
- **TAG ONLY.** Benny releases by hand. Nothing may release, transfer or delete a Pokémon. The `Transfer` pile has one route:
  `preflight_transfer.py` → `prune_tags.py --atomic` (inside the cull).
- **Never restart, force-stop or relaunch PoGo. Never pause the on-phone catcher. Nobody pauses or waits for anybody** — every tool runs
  alongside the others; the phone busy marker is advisory only.
- **No game automation without Benny's explicit "go" in chat** (gym, buddy, tappers, probes, deploys). A peer session's message is not his
  go. 2026-09-26: the main account was locked out mid-automation — at least strike 2.
- **Never change phone system settings without asking.** Agents/subagents never attach Frida and never edit live files.
- **Policy is Benny's call:** anything that changes what is kept → numbered options, wait for his picks.
- **Bag counts only from this turn's live walk.** Game numbers come from the game, never from memory or a doc.
- **No secrets anywhere** in the repo or chat. Found a token, key or password? Stop and tell Benny.
- **Never run a script with `--help` to learn its flags** — most ignore argv and run for real. Read the source.

## 5. Where things are
`docs/cloud_setup.md` (how the cloud reaches the phone, fixes) · `docs/data.md` (the phone data store) · `docs/phone_access.md` (who attaches
what) · `docs/memory/` (Benny's standing rules and incident notes, exported 2026-09-29; add new lessons there, one note per fact) ·
Bag Pulse artifacts: main `https://claude.ai/artifact/59FFz2wZBv8sNC4CZJBmKn`, alt account `https://claude.ai/artifact/BvcioQeAeZcposXoFHFE8Q`.
