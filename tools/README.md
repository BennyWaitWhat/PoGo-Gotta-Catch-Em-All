# tools

## `triple_check.py` — run before you say "done"

```bash
python tools/triple_check.py            # git state, compile/parse, self-tests, guards, secrets (ALL history), doc links, data store
python tools/triple_check.py --gate     # + the 11-audit gate (pull first)
python tools/triple_check.py --fresh    # everything on a fresh clone of origin/main + a data pull
```
Read-only (no Frida; the phone is only read). Ends with `ALL CLEAR` (exit 0) or `NOT DONE` (exit 1). CI runs it on every push.

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
