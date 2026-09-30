# The game data lives on the phone

Git holds code and docs. Everything the tools READ AND WRITE as they run — `pokemon.db`, the DB snapshots, walk outputs (candy, items,
Pokédex, player state), tag sets, `keep_config.json` (per account), the game-master copies, catcher studies, gym state — lives in one
place: `/data/local/tmp/pogo_data/` on the Pixel. Why there: cloud VMs are wiped between sessions, cloud sessions can only push their own
git branch, git LFS does not work in the cloud, and the data changes every run (committing it would bloat the repo by GBs a month).
Every session that does phone work reaches the phone anyway.

## Commands (repo root)
```
python tools/pogo_data.py status                   # every group: phone version vs the version this checkout holds
python tools/pogo_data.py pull                     # all non-cold groups -> into this checkout (only what changed)
python tools/pogo_data.py pull --group inventory   # one group
python tools/pogo_data.py push --group inventory   # after a cull (owner only); refused if the phone moved since your pull
python tools/pogo_data.py selftest                 # offline check of the tool itself
```

## Groups (`tools/data_manifest.txt` says exactly which files)
| Group | Owner (only the owner pushes it) | What | Pulled by default |
|---|---|---|---|
| `inventory` | Pokemon Inventory | `pokemon.db`, walk outputs, tag sets, analysis state, per-account sets, newest 6 snapshots | yes |
| `inventory-cold` | Pokemon Inventory | every DB snapshot + the pre-switch archive (`archive_main_account_20260926/`, keep forever). **Not seeded yet** — 1.6 GB, ~25 min at the link's ~1 MB/s; the PC holds it. Seed from the PC when Benny is not playing: `push --group inventory-cold` | no |
| `catcher` | AutoCatcher | map data, studies (`*.jsonl`), caches its tools read | yes |
| `gym` | Gym Battle | `AutoCatcher/tools/gym_state/` except the runner inbox | yes |

## Guarantees
- **Per-group versions.** Sessions never block each other; a push is refused only when THAT group moved since your pull (`--force` exists
  for recovery; never use it over another session's work).
- **Nothing lost silently.** A pull refuses to overwrite a local file that is newer than the phone's copy (a PC that still holds unpushed
  work); `--force` takes the phone's copy anyway.
- **Code never rolls back.** Files git tracks are never packed, so a pull cannot overwrite code.
- **SQLite-safe.** `*.db` files are packed through SQLite's backup API; stale `-wal`/`-shm` files are removed on pull.
- **Atomic.** Uploads land under a temp name, are sha256-checked on the phone, then renamed; a reader never sees half a file.

## Not in the data store
Secrets (Pokemod/Niantic prefs, `nia_secret_*`, keystores, `game_limits.json`, `pogo_extract/system/analysis/pokemod/`), RE dumps,
binaries, logs, backups, and `system/scripts/rank_tables.pkl` (333 MB, rebuilds itself when missing — the first cull in a fresh VM is
slower for it). To add a file: put its pattern in `tools/data_manifest.txt` under the owning group (owner edits), then push that group.

## The PC
The Windows PC is no longer where PoGo work happens. It seeded the store on 2026-09-29 and still holds the original copies. If a PC
session ever works again: `pull` first, `push` after — the version checks keep the PC and the cloud from overwriting each other.
