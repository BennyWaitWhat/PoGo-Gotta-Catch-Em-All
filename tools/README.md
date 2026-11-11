# tools

## `triple_check.py` — run before you say "done"

```bash
python tools/triple_check.py            # git state, compile/parse, self-tests, guards, secrets (ALL history), doc links, data store
python tools/triple_check.py --gate     # + the 11-audit gate (pull first)
python tools/triple_check.py --fresh    # everything on a fresh clone of origin/main + a data pull
```
Read-only (no Frida; the phone is only read). Ends with `ALL CLEAR` (exit 0) or `NOT DONE` (exit 1). CI runs it on every push.

## `cull_now.sh` — ONE cull pass per go

```bash
bash tools/cull_now.sh              # start a pass (or attach to the one the hook started), wait, print its output
bash tools/cull_now.sh --selfcheck  # the go matcher + the lock / detach / attach paths, no phone (CI runs it)
```
On the PC a `UserPromptSubmit` hook (`bash tools/cull_now.sh --hook`, in the untracked `.claude/settings.local.json`) starts
the pass the moment Benny sends a bare `cull` (2026-11-10, "A2"). One pass per go: a second start attaches to the first.
It never retries, never restarts the game, and only tags (it runs `full_audit.py`). State: `pogo_extract/system/analysis/cull_now.*`.

## `pogo_data.py` — the phone data store

The game data never goes in git. It lives on the phone in `/data/local/tmp/pogo_data/`, one versioned tarball per group
(groups and their files: [`data_manifest.txt`](data_manifest.txt)). Full story: [`../docs/data.md`](../docs/data.md).

```bash
python tools/pogo_data.py status                   # phone version vs this checkout, per group
python tools/pogo_data.py pull                     # every non-cold group (only what changed)
python tools/pogo_data.py push --group inventory   # owner only; refused if the phone moved since your pull
python tools/pogo_data.py selftest                 # offline check (CI runs it)
```

Device: `$ADB_TARGET` (the cloud hook sets it; default `100.98.158.56:5555`). Standard library only.
