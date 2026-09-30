# PoGo Self-Update - Design and Setup

## What it does

`self_update.py` is a daily (or on-demand) runner that keeps the toolkit current:

1. Runs `pogo_pipeline.py` (Frida bag walk, DB reconcile, cull). Retries up to 2 times if the phone is unreachable, then logs failure and continues.
2. Runs `account_snapshot.py` (writes `account_snapshot.json`).
3. Archives the new snapshot to `snapshots/snapshot_YYYYMMDD_HHMMSS.json`, then diffs it against the previous archived snapshot.
4. Writes `snapshots/changelog_YYYYMMDD_HHMMSS.txt` with pipeline status and every detected change.
5. Sends a Telegram summary to chat 8749793156 via `TELEGRAM_BOT_TOKEN` env var.

## What the diff detects

- Pokemon count in bag (net gain/loss)
- Pokedex seen/caught counts
- Stardust, coins
- Candy gains/losses per species (suppresses noise under 5)
- New pokemon (species, CP, IV, shiny/hundo flags) - up to 10 shown
- Pokemon no longer in bag (transferred count)
- New hundos (species names)
- New shinies (species names)
- Tag membership changes (added/removed per tag name)

## Snapshot contract

`account_snapshot.py` must write `account_snapshot.json` with these optional top-level keys. Any absent key is silently skipped in the diff:

```json
{
  "pokemon_count": 1200,
  "pokedex_seen": 720,
  "pokedex_caught": 680,
  "stardust": 450000,
  "coins": 150,
  "candy": { "Pikachu": 200, "Eevee": 800 },
  "hundos": ["aabbcc...", ...],
  "shinies": ["ddeeff...", ...],
  "tags": { "KEEPER": ["aabbcc", ...], "CLAUDE_TX": [...] },
  "bag": [
    { "uid_hex": "aabbcc...", "species_name": "Pikachu",
      "cp": 1200, "iv_total": 45, "is_shiny": 1, "is_hundo": 1 }
  ]
}
```

## Scheduling on Windows (schtasks)

Run this once in an admin PowerShell to register a daily 9 AM task:

```powershell
schtasks /Create /TN "PoGoSelfUpdate" /TR "python C:\Users\Blanco\Desktop\`"Claude Operations`"\`"Phone Maintenance`"\pogo_extract\self_update.py" /SC DAILY /ST 09:00 /RU kali /RL HIGHEST /F
```

To trigger it manually at any time:

```powershell
schtasks /Run /TN "PoGoSelfUpdate"
```

To remove it:

```powershell
schtasks /Delete /TN "PoGoSelfUpdate" /F
```

Notes:
- `/RL HIGHEST` runs it elevated so ADB and Frida work without UAC interruption.
- The task runs the current user's Python (assumes `python` is on PATH). Adjust to an absolute path like `C:\Python312\python.exe` if needed.
- `TELEGRAM_BOT_TOKEN` must be set as a **user environment variable** (System Properties > Environment Variables > User variables) so the task inherits it.

## Alternative: loop mode

For ad-hoc use or if you prefer a persistent process, run:

```powershell
while ($true) {
    python self_update.py
    Start-Sleep -Seconds 86400
}
```

Or with a tighter poll (e.g. every 6 hours):

```powershell
while ($true) {
    python self_update.py
    Start-Sleep -Seconds 21600
}
```

## Flags

| Flag | Effect |
|---|---|
| `--dry-run` | Passes `--dry-run` to the pipeline (no tag writes to server). Diff and notify still run. |
| `--skip-pipeline` | Skip step 1. Useful if the pipeline just ran and you only want a fresh snapshot + diff. |
| `--skip-snapshot` | Skip step 2. Reuses the existing `account_snapshot.json`. |

## Files produced

```
pogo_extract/
  snapshots/
    snapshot_20260521_090000.json   archived snapshots (one per run)
    snapshot_20260522_090000.json
    changelog_20260522_090000.txt   human-readable diff for each run
```

Old snapshots are never auto-deleted. Manual pruning is fine; the diff only ever looks at the two most recent files.
