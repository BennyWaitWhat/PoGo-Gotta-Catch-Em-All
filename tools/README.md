# tools

## `pogo_data.py` — the phone data store

The game data never goes in git. It lives on the phone in `/data/local/tmp/pogo_data/`, one versioned tarball per group
(groups and their files: [`../data_manifest.txt`](../data_manifest.txt)). Full story: [`../docs/data.md`](../docs/data.md).

```bash
python tools/pogo_data.py status                   # phone version vs this checkout, per group
python tools/pogo_data.py pull                     # every non-cold group (only what changed)
python tools/pogo_data.py push --group inventory   # owner only; refused if the phone moved since your pull
python tools/pogo_data.py selftest                 # offline check (CI runs it)
```

Device: `$ADB_TARGET` (the cloud hook sets it; default `100.98.158.56:5555`). Standard library only.
