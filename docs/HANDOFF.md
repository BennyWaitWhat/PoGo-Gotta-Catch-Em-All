# HANDOFF — state of everything at the move to the cloud (2026-09-29, ~23:00 ET)

Written by the PC's Pokemon Inventory session as its last act. The PC sessions are winding down; from here on **all PoGo
work happens in Claude cloud sessions**. Read this once in your first session, after `docs/START_HERE.md`. Every fact
below was verified on 2026-09-29 unless it says otherwise.

---

## 0. FIRST THING: CULL
Benny, 2026-09-29 ~23:05 ET, verbatim: **"The first thing I want it to do is do a cull."** That is his explicit go for
ONE cull by the first cloud session. The test for "first": `python tools/pogo_data.py status` shows the `inventory` group
last pushed `by pc-seed` (no cloud session has culled yet). If so, and the `PHONE BRIDGE:` line says connected, do this
before anything else: `python tools/pogo_data.py pull` → `cd pogo_extract && python full_audit.py` → from the repo root
`python tools/pogo_data.py push --group inventory` → publish Bag Pulse → report per `.claude/skills/cull/SKILL.md`.
Bridge not connected → say which log line failed instead (§1, `cloud_setup.md`). Once `inventory` shows `by cloud`, this
section is done; later culls run only when Benny says "cull".

## 1. Benny's next steps (he has NOT done these yet)
The cloud cannot reach the phone until he does steps 1–4 of [`cloud_setup.md`](cloud_setup.md) (~15 min):
1. claude.ai/code → pick this repo (authorize the Claude GitHub app for it if it isn't listed).
2. Tailscale admin → Settings → Keys → auth key: Reusable + Ephemeral (+ Pre-approved if shown).
3. On the PC (Git Bash): `adb keygen ~/.android/cloud_adbkey`, then `base64 -w0 ~/.android/cloud_adbkey | clip` (and the `.pub`).
4. New cloud environment "PoGo": Network **Full**; env vars `TAILSCALE_AUTHKEY`, `ADB_KEY_B64`, `ADB_PUB_B64`; setup script = `cloud/setup.sh`.
5. First session: the phone asks "Allow USB debugging?" → he ticks **Always allow** → Allow → says "retry the bridge" → you run
   `adb connect "$ADB_TARGET"` → then run the first cull (§0).

**If you are the first cloud session:** check the `PHONE BRIDGE:` line. Not connected → read `/tmp/pogo_bridge.log`, match the
line in `cloud_setup.md` → tell Benny the ONE thing to fix. Nothing about the bridge has run in a real cloud VM yet (see §7).

## 2. First-session checklist (Pokemon Inventory)
```bash
python tools/pogo_data.py status        # expect: inventory v2, catcher v1, gym v1 on the phone; inventory-cold not seeded
python tools/pogo_data.py pull          # ~65 MB over the tailnet; ~1 min at ~1 MB/s (slower if relayed)
cd pogo_extract && python full_audit.py --audits-only   # expect: ALL 11 AUDITS PASS (proven on a fresh clone 2026-09-29)
```
Then do §0 (the first cull). After that, whenever Benny says **`cull`**: follow `.claude/skills/cull/SKILL.md` exactly (pull → `full_audit.py` → push
`--group inventory` → publish Bag Pulse). The first cull in a fresh VM rebuilds `system/scripts/rank_tables.pkl` (333 MB, not in
the store) — expect it slower than the ~80 s the PC took.

## 3. Where things stand
| Thing | State (2026-09-29) |
|---|---|
| Repo | `main` = a8c89b3 at handoff (PRs #1–#9 merged), release **v1.0.0** (tag at 798d7ed), CI green, 1 branch, 0 open PRs |
| Phone data store | `inventory` v2 (334 files, 51.1 MB, 21:53) · `catcher` v1 (16 files, 13.4 MB) · `gym` v1 (90 files, 0.3 MB) — sha256 on the phone matches each meta; the PC changed nothing after seeding |
| `inventory-cold` | **Not seeded** (1.6 GB: all DB snapshots + `archive_main_account_20260926/`, keep forever). The PC holds it. Push from the PC when the phone is idle (~25 min) |
| Last cull | 21:28 ET: 11/11 PASS, **pile 27** tagged `Transfer`, the server answered Success for 1/1 tag batch, last walk: bag 5,706/5,850. Its post-DONE steps (Remote Trade + Evolve-for-Size tags) were cut off by a broken pipe — the next cull refreshes them |
| Benny's to-do in game | **Release the 27 in the Transfer tag** (he released the previous 28) |
| Bag Pulse | v118 published at 21:3x to `https://claude.ai/artifact/59FFz2wZBv8sNC4CZJBmKn` (alt: `BvcioQeAeZcposXoFHFE8Q`, built by hand from the same page with the title swapped) |
| Phone | Pixel 9 Pro, Tailscale 100.98.158.56, adb TCP 5555 restored at every boot by Magisk `service.d/adb_tcp_5555.sh`; busy marker empty; `pogo_pause` = 0; PoGo running |
| Active account | main **oyebenny** (trainer BennyValentinC); alt `florandez` rests in `accounts/florandez/` |
| Versions | game 0.429.1 · Pokemod 13.3.3 · frida 17.9.11 (phone gadget) · frida-tools 14.8.2 |

## 4. What changed today (so you don't redo it)
- **Stale service graph fix**: every singleton comes from the live graph (`pogo_il2cpp.live_graph` / `pick_singleton`);
  `walk_tripwires.py` stops a pass (rc 8) on catcher-log proof of a frozen read.
- **Server answers**: `tag_ops` records the game server's answer per tag batch (`system/analysis/last_tag_server_answer.json`);
  a refusal fails the write. Verified live at 21:28.
- **Shiny ladder / evolve labels**: per-specimen later stages + game-master gate reasons; `_evocheck` mirrors the engine's slot model.
- **Busy marker is advisory** everywhere (Benny: "no one should be pausing anything for anyone").
- **Migration**: this repo, the SessionStart bridge, `cloud/setup.sh`, the phone data store, docs, 113 memory notes.
- **Safety pass**: `full_audit.py` refuses unknown flags and missing data (rc 2); `restart_pogo_and_wait()` raises in both
  `pogo_il2cpp` copies; 28 hard-rule scripts (pogo_extract) + 42 retired AutoCatcher files are out of git (still on the PC,
  still in the history of commit 1abe382); `evolvable_forms` cache is atomic; `granular_tags --audit` says NOT RUN without data.
- **Polish**: README, community files, offline CI (compile, `bash -n`, self-tests, guards, secret scan), templates, labels, v1.0.0.

## 5. Decisions waiting on Benny (numbered — ask, don't assume)
1. **Keep-policy picks** still open from earlier: LAW caps (1a/1b), trade spares (2A–D), look-alikes (3a–c). Background:
   `docs/memory/pogo-keep-research-2026-09-29.md` (bag refills ~64/day; open: LAW caps 783, trade spares 469, merge 235).
2. **florandez line pools**: should costume copies count toward the 2 plain slots per line? (Charmander lost both plain Charizards.)
3. **Seed `inventory-cold`** from the PC (phone idle, ~25 min).
4. **Tailscale lock-down** to the phone's adb port (`cloud_setup.md` → "Lock it down"), and **branch protection** on `main`
   (GitHub suggests it; it's a security setting — his click).
5. **Scrub git history** of the untracked hard-rule scripts (private repo, 1abe382) — only if he wants.
6. **Memory notes with identifiers** (the ban-lockout note cites a Gmail thread number; artifact ids; account names) — keep or redact.
7. **Durability**: the phone is now the only live copy of the data. A periodic `pull` back to the PC as a backup?
8. **Gym Battle**: the gym runner is OFF (2026-09-26 lockout, ≥ strike 2); its first run needs his explicit go and is a
   verification run. Also: delete legacy `gym_loop.py` / `gym_trace.py`? delete old scratch originals (incl. a 416 MB game-binary dump)?
9. **AutoCatcher**: two phone-side scripts in `/data/local/tmp/re.zyg.fri/` (`pogo-catch.sh`, `restore.sh`) still force-stop
   PoGo — move them out? (AutoCatcher asked him.)

## 6. Known open items (not blocking)
- Level 71 tracker paused: Benny wants 15 Platinum (catch) medals; `read_medals.py` broke on the obfuscated build
  (PlayerService members scrambled); the PlayerStatsProto counters are not located yet.
- `account_guard` fails OPEN when the trainer-name read fails (WARN, walk continues); the push is still protected by
  `prune_tags`' trainer-equality check.
- `audit_invariants` WARN: Darumaka form 2063 has no stat line that reproduces its stored CP.
- The Alt Bag Pulse is a manual copy, not in `gen_bag_pulse.py`.
- The "Pokemon Switcher" session (offline) has not acknowledged the gym runner's new inbox path (`AutoCatcher/tools/gym_state/runner_inbox/`);
  harmless while the runner is off, must be confirmed before any buddy relay.
- AutoCatcher #9 (merged at handoff): the phone's own helper library is in git as `AutoCatcher/ondevice_toggle/phone_pogo_il2cpp.py`,
  and `deploy.sh` refuses to push the desktop copy to the phone.
- Old research notes in `pogo_extract/*.md` link to data files that are not in git (expected, 12 links).

## 7. Unverified until the first real cloud run
Tailscale through the cloud's HTTPS proxy · whether the VM allows `ip addr add` on loopback (else the bridge uses
127.0.0.1:5555 and only `ADB_TARGET`-aware tools reach the phone) · `cloud/setup.sh` end to end (frida wheels exist for
Linux; the Tailscale static fallback URL was checked) · whether `gh` can open/merge PRs from a cloud session (else hand
Benny the branch link) · whether cloud sessions have the Artifact tool for Bag Pulse (else say so) · data pull speed through
a DERP relay.

## 8. Gotchas that cost time today
- **Never run a script with `--help` to learn it** — `full_audit.py --help` ran a real cull (fixed: unknown flags → rc 2).
  Never pipe a phone script into `head`/`tail`: a broken pipe kills it mid-cycle.
- **Heredocs mangle backslashes and quotes** in the agent shell: write patch scripts to a file, then run them.
- **Keep each file's line endings** (`* -text`; many pogo_extract files are CRLF). Python rewrites with default newline
  handling silently convert CRLF → LF — read/write bytes, or use the Edit tool.
- **Other adb devices share the tailnet** (Bravia TV 100.113.169.96, Google TV 100.85.17.54): always `adb -s "$ADB_TARGET"`.
- **The app's PR monitor can't read this repo's CI** (its GitHub account lacks access): read `gh pr checks N` once; don't poll.
- **adb over the tailnet runs ~1 MB/s**: big transfers take minutes; `pogo_data.py` timeouts scale with size.
- **Cloud sessions can't message each other back.** Coordinate through the repo (PR descriptions, `docs/memory/`) and Benny.

## 9. Standing rules (full text: `START_HERE.md` §4, `pogo_extract/CLAUDE.md`, `docs/memory/`)
Tag only, never release · the pile's one route: `preflight_transfer.py` → `prune_tags.py --atomic` · never restart / force-stop
PoGo · never pause the catcher; nobody waits for anybody · no game automation without Benny's explicit "go" · no system
settings without asking · policy = numbered options, his picks, `LAW.md` first · bag counts only from this turn's walk ·
report game-owned numbers from the game · say what you verified and what you didn't.
