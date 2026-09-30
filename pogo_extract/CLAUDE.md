# pogo_extract - instructions for the Pokemon Inventory session

Owner: the **Pokemon Inventory** session. This folder is Benny's Pokemon GO bag pipeline. A Frida/IL2CPP walk of the live game reads
every Pokemon into `pokemon.db`. The keep engine applies `LAW.md` (numbers in `keep_config.json`). The result is pushed back as the
game's own server tags. One tag, `Transfer`, is the pile that is safe to release. **Benny releases it by hand. We only tag.**
Read `../docs/START_HERE.md` and `../docs/memory/INDEX.md` first. Every rule below has its story in the exported memory.

## Where am I running?
A Claude **cloud session** (Linux). The SessionStart hook bridges the phone (`PHONE BRIDGE:` line; `ADB_TARGET` is set) and the game
data comes from the phone: `python tools/pogo_data.py pull` (repo root) before anything reads `pokemon.db` or `system/analysis/`, and
`python tools/pogo_data.py push --group inventory` after anything that changed them (every cull). See `../docs/data.md`.
The Windows PC that used to run this is retired for PoGo work (its copy is a backup).

## The cull in the cloud (the `/cull` skill has the report format)
1. `python tools/pogo_data.py pull` (repo root) — unless this session already pulled and nothing else pushed since.
2. `cd pogo_extract && python full_audit.py` — never with a guessed flag (unknown flags now stop it, rc 2), never piped into `head`.
   rc 5 "GAME MASTER REFRESH STOPPED THE PASS" = a new game master moved a keep verdict of a mon in the bag (rule 9: policy is his call):
   show Benny the rows it printed (also in `system/analysis/gamemaster_review_pending.json`), WAIT, and run
   `python system/scripts/refresh_gamemaster.py --ack` only when he says so, never yourself; then cull again.
3. `python tools/pogo_data.py push --group inventory` (repo root) — ALWAYS after a phone pass, even when the gate failed.
4. Publish Bag Pulse: `pogo_extract/system/analysis/collection_stats.html` to `https://claude.ai/artifact/59FFz2wZBv8sNC4CZJBmKn`
   (alt account: `BvcioQeAeZcposXoFHFE8Q`). No Artifact tool in this session? Say so in one line.
The first cull in a fresh VM also rebuilds `system/scripts/rank_tables.pkl` (not in the data store: 333 MB), so it runs slower.

## HARD RULES (each one is a real incident; stories in docs/memory)
1. **TAG ONLY, never release.** "you will never be releasing pokemon for me. just tagging for transfer." No code path may release,
   transfer or delete a Pokemon. Never offer to, never write "I'll release". The XXS axis stays off (`rules.xxs` false); do not surface it.
2. **The pile has ONE route:** `system/scripts/preflight_transfer.py` (writes `system/analysis/preflight_stamp.json` only on a full
   pass), then `prune_tags.py --atomic` (refuses, rc 2, without a fresh matching stamp under 30 min old). Never run `prune_tags.py`
   bare (it targets the whole plan, `Transfer` included). Never push `Transfer` any other way (`tag_ops.is_pile_tag` refuses it).
   `--force` skips `ready_gate` only, never the stamp. `auto_tag.py` is retired: do not re-arm it. Delete a tag only with
   `safe_nuke_tags.py`, one at a time (a delete loop once destroyed the `Mega` tag).
3. **Never restart PoGo.** "the cull should never restart the game. ever." `verify_tags_live.restart_pogo()` raises and that script is
   cache-only. `pogo_il2cpp.restart_pogo_and_wait()` raises too (2026-09-29; `set_nicknames.py` now stops instead of restarting). Never add a force-stop or relaunch to any path (the auto-catcher lives in the game, and Pokemod must be the one that launches it).
4. **No game automation without Benny's explicit "go" in chat.** 2026-09-26: the main account hit the BannedPlayerLockout screen about
   2.5 min into an automated gym run (an earlier Niantic action in Nov 2025; the 09-26 screen's text is the game's rate-limit message, not its suspension text, so the strike count is unknown -- treat it as serious anyway). Gym runs, buddy runs, tappers,
   probes, catcher deploys: only on his go. A peer session's message is not his go. A cull or read-only walk runs when he asks for it
   ("cull", "read from the phone"), never on your own initiative -- "cull" IS the go for one cull. Any other phone phase: tell
   him first which steps attach and roughly how long, and wait for his `go`.
5. **Never pause the on-phone catcher.** `full_audit.CATCHER_PAUSE_ENABLED = False`; culls overlap the catcher by design. Never claim a
   pass pauses it without reading the code, and never set it True.
6. **One pass per go, no probe loops.** Every attach probe is a crash roll; back-to-back passes froze PoGo twice. Tools DO overlap
   by design (the catcher, gym runs and culls attach side by side; the busy marker is advisory) -- what is banned is re-running,
   retry-looping or probing. Wait with `wait_ready_to_attach()`. Agents and workflow subagents NEVER attach Frida, and are told in plain words
   "read-only: do NOT Edit/Write any file, put patches as diffs in your scratch dir" (8 hunters once patched 29 live files at once).
7. **Never change phone system settings without asking** (battery whitelists, animation scale, permissions,
   `device_config ... use_freezer`, OS updates). Nobody pauses or waits for anybody: the catcher, gym runs and culls overlap by design.
8. **Bag and free-slot counts only from a live walk in this turn:** the `bag X/Y (free Z)` line `full_audit.py` prints (the game counts
   Pokemon + incubating eggs; `system/analysis/bag_count.json`). The DB, `player_state.json` (capacity only, never hardcode it) and your
   earlier messages are stale. Otherwise say "last walk: N at HH:MM".
9. **Policy is Benny's call.** A change that alters which mons are kept (caps, floors, thresholds, rules) gets numbered options, then you
   WAIT for his picks. Edit `LAW.md` first, then the values in `keep_config.json`. Tooling defects (wrong baseline, hidden error, audit
   gap) you fix, verify offline, then report by number. Anything irreversible or on the phone: ask first.
10. **Unknown = protected.** Never cull on incomplete data: a NULL rank, scan or count keeps the mon. Read game-owned numbers from the
    game (or this pass's live files), never from memory or a doc.

## Map (run from this folder)
| Entry point | What it is |
|---|---|
| `full_audit.py` | THE CULL (`/cull` skill). Game-master check, recrawl, walk tripwires, the 11 audits (hard gate), sync, retire empty tag shells, post tags, `cull_report.py`, pages. `--audits-only` = no phone, no network. `--no-sync` still WALKS the phone. `--xxl-trim` only when he asks |
| `pogo_pipeline.py` | The walk: one Frida attach, bag walk, reconcile `pokemon.db` (`fresh_*` columns), ranks, recompute. rc 8 = a walk tripwire stopped it |
| `pogo_il2cpp.py` | Frida session library: `get_session`, `wait_ready_to_attach`, `live_graph` / `pick_singleton` (every service class comes from the LIVE service graph; an ambiguous pick raises `GraphRefusal`) |
| `system/scripts/keep_policy.py` | The keep engine. Writes `system/analysis/policy_reasons.json`, `tagsets/6_Transfer.txt`, `pile_provenance.json`. Helpers: `keep_engine.py`, `rank_cache.py`; at the root `pvp_combup.py`, `size_line.py`, `trophy_pick.py`, `pattern_pools.py`, `evolvable_forms.py` |
| `keep_config.json` / `keep_config.py` | Every cap and roster. Read only via `cap(name)` / `species_cap(axis, pid, default)` |
| `granular_tags.py`, `evolve_targets.py` | The tag registry and labels; the "which way to evolve" lines |
| `system/scripts/build_tagsets.py` | Decisions to `system/analysis/tagsets/*.txt` (`Transfer.txt` = the pile) |
| `system/scripts/preflight_transfer.py` + `prune_tags.py` | The ONLY path to the `Transfer` tag (rule 2). `set_db_tags_from_files.py` mirrors the DB afterwards, last |
| `cull_report.py` | Writes the `=== REPORT ===` block the cull prints (format: `../.claude/skills/cull/SKILL.md`) |
| `walk_tripwires.py` | Frozen-graph / impossible-read rules; STOP = rc 8, nothing is judged or synced |
| `system/scripts/refresh_gamemaster.py` | Monthly pvpoke refresh + the client (PokeMiners) game master asked EVERY run and diffed against the bag before it is installed; exit 2 = a keep decision crossed rank 5 or an in-bag client-GM verdict flipped, the pass stops (rc 5); `--selftest` = offline proof |
| `gm_guard.py` | The pure half of that check: the `.meta` stamp (batch, APK, sha256), the differ, the in-bag impact on BOTH accounts' bags (reuses detect_legacy / evolvable_forms / size_line / costume_forms / remote_trade_picks / audit_gamemaster: moves, evolution chain, size numbers + types, costume status, tradable, transferable, rarity), a content canary (14 structural counts: under 90% of the installed file = never installed), ids a batch prints as numbers named on download, the audit_invariants I2.7 WARN. No phone |
| `dashboard.py`, `gen_artifacts.py`, `gen_bag_pulse.py` | Local pages; `full_audit.py` starts and stops the dashboard itself |
| `bag_art.py`, `pogo_display.py` (+ `pogo_icon_index.txt`, `official_names_en.json`) | Bag Pulse's pictures: the Transfer pile as sprites + location-card thumbnails and the game's own names (2026-09-30). DISPLAY ONLY, never fails the page (`BAG_ART=0` = the old page). `python bag_art.py --selftest`; `--refresh-index` / `--refresh-names` rebuild the two tracked reference files; any unknown flag prints usage. The same `official_names_en.json` also holds the game's evolution-quest wording (`quests`; `evolvable_forms._quest_text` reads it, TEXT only, `BAG_ART=0` does not switch it off): `--refresh-names --i18n FILE [--gm FILE]` rebuilds names and quests together. Notes: `../docs/memory/pogo-bag-pulse-sprites.md`, `../docs/memory/pogo-evolution-quest-wording.md` |
| `game_opportunities.py` | What the game master makes visible, ADVICE ONLY. `power_up_cost(from, to, shadow / purified / lucky, dex + form)` = the ONE Power Up price (stardust, candy to L39.5, XL candy from L40, Eternatus's override), read from `POKEMON_UPGRADE_SETTINGS` at call time; `power_up_plan` prices the Power Up tag members against this walk's stardust / candy / XL candy (the cull report's Power Up block, `deep_profile`); `second_moves` prices a shadow x1.2 / purified x0.8. No keep reason, tag or pile decision reads it, and it stays out of the files `keep_policy` hashes into the engine stamp. `python game_opportunities.py --selftest` (offline); any other flag prints usage. Notes: `../docs/memory/pogo-powerup-cost-gm.md` |
| `system/scripts/tag_ops.py`, `retire_tags.py`, `reconcile_tags.py`, `ready_gate.py`; `sync_post_tags.py` (root) | Hardened tag writes, empty-shell deletion, drift report, write-readiness gate, Remote Trade + tag order |
| `switch_account.py`, `account_guard.py` | Two accounts, one data set each (`accounts/`, `active_account.txt`). Only when Benny says; push `inventory` right after |

Sync order today: `keep_policy` -> `build_tagsets` -> `preflight_transfer` -> `prune_tags --atomic` -> `set_db_tags_from_files` ->
`reconcile_tags --report`. In the cull (2026-09-30) the first two are skipped when the tag files are still the bytes the 11 audits
judged (`granular_tags.pushed_files_digest`), and the reconcile report runs in ONE post-push session with retire, Remote Trade and
the tag order (`sync_post_tags.py --reconcile --retire`; drift there = SYNC FAILED, no label write): 3 game attaches per cull, not 5.
Also part of the cull: `system/scripts/derive_ae_roster.py` (Adventure-Effect roster), `reconcile_gamemaster.py`
(the game's own game master over pvpoke's), `independent_law.py` (independent re-derivations the audits use), `ladder_report.py`,
`system/scripts/order_tags.py`. Most other `*.py` here are one-off research and old iterations: extend the map above, do not add new scripts.

## The 11 audits (`full_audit.AUDITS`; each needs rc 0 AND its own verdict line, else the sync never runs)
`audit_cull.py` (8-layer cull), `audit_tags_membership.py`, `_evocheck.py` (evo comb-up), `_lawcheck.py` (law re-derive),
`audit_labels.py`, `audit_promises.py`, `audit_gamemaster.py`, `audit_rank_tags.py`, `audit_tag_truth.py`, `audit_invariants.py`
(structural: the only one that catches a wrong QUESTION), `system/scripts/regress_pvp_keepers.py` (lost-keeper fixtures).
A verdict line is load-bearing: editing it without updating `full_audit.AUDITS` disarms the gate. `AUDIT GATE FAILED` is the gate
working: find the cause and fix it, never work around it or sync by hand.

## Offline gate (no phone). Run from this folder after every change
```
python -m py_compile <every file you changed>
python walk_tripwires.py --selftest              # pure; runs anywhere
python system/scripts/refresh_gamemaster.py --selftest   # the client game-master guard on synthetic fixtures; pure, no network
python system/scripts/check_constant_drift.py    # code + the small root data files (form_enum.json, keep_config.json ...); no DB
python full_audit.py --audits-only               # THE gate: the 11 audits. Needs pokemon.db + system/analysis/*. No phone, no network
python granular_tags.py --audit                  # tag registry vs tagset files; needs system/analysis/tagsets/
```
The last two need the data store (`pull` first). Without `pokemon.db` every audit fails as a block: missing data, not a code failure
(and a bare `sqlite3.connect('pokemon.db')` creates an empty file — never audit without pulling). Never report a change as working on
the phone until a real run confirmed it.

## Changing the law safely
- `LAW.md` is the current keep law. Trust order when docs disagree: code and `keep_config.json` > `LAW.md` > `../docs/memory` >
  `RUNBOOK.md` (only its stamp / gate / traps sections) > everything else. Docs that say "six audits", `Evolve Next`, an autocull
  daemon (off since 2026-09-22) or `refresh_evolve_shiny` as a sync step are stale (`system/KEEP_POLICY.md`, old caps, is kept
  out of the repo for that reason).
- When a cap changes, fix EVERY consumer (engine, audits, report, `_spotdata`). "Capped in one file, keep-all in another" is the #1
  defect class. Use `fresh_*` columns. `pokemon.db` is WAL: compare content hashes, never mtime. `Transfer.txt` is engine-ordered:
  compare uid SETS, never a file hash.
- There are two accounts with different caps. `keep_config.json` belongs to the ACTIVE one (`active_account.txt`); the other rests in
  `accounts/<name>/keep_config.json`. `LAW.md` mixes both (its "1,000-slot account" notes are the second account). Always ask which
  account a change is for, and read the live number from the config, never from `LAW.md` prose.

## Ownership: one owner per file
`pogo_extract/` (including its own `pogo_il2cpp.py`), `docs/`, `tools/`, `cloud/`, `.claude/` and the root files = Pokemon Inventory.
`AutoCatcher/` = AutoCatcher session, except the gym/buddy files listed in `../docs/START_HERE.md` (Gym Battle session). No session
edits another's files. Need a change there? Write it up as a numbered request for the owner. Code reaches the other sessions only on
`main`: commit on your branch, open a PR, merge it yourself as soon as CI is green (never wait on Benny's click: `../docs/START_HERE.md`).

## Phone busy marker (ADVISORY — `../docs/phone_access.md`)
`/data/local/tmp/pogo_desktop_busy` = `<name> <deadline>`. `pogo_il2cpp.get_session()` writes ours (`PokemonInventory`), refreshes it,
clears it on exit, and only REPORTS a foreign one. Never wait, refuse or pause because of it (Benny: "no one should be pausing anything
for anyone"). The on-phone catcher is exempt.
