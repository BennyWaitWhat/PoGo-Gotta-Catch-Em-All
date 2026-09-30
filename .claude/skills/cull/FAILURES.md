# Cull: when something stopped

Loaded on demand from `SKILL.md` (2026-09-30: kept out of the per-cull reload). The one rule still holds: never release anything.

## If the audit gate fails

`AUDIT GATE FAILED` means the sync did **not** run — that is the gate working, not a crash. Do not retry it, do
not work around it, and do not sync by hand. Read the failing lines it prints, find the real cause, fix it, and
re-run. A failing audit has caught genuine bugs many times; treating it as noise is how a keeper gets released.

Common shapes:
- `promises ... culled after evolving` — the engine reserved a slot at a stage the sandbox then culls it from.
  Usually a stage-keying bug making a stage read as EMPTY; see `pogo-one-speciesid-many-plain-forms` in memory.
- `8-layer cull ... pvp rank` — a rank<=5 spread reached the pile. Stop; that is the Mareep failure mode.
- `structural inv. ... BLOCK` — an invariant about the MODEL, not the membership. Read its `DO:` line.

## If the game-master refresh stops the pass

`GAME MASTER REFRESH STOPPED THE PASS (rc 5)` means a game master moved keep decisions, so nothing was recrawled or
synced — the stop is the feature, not a crash. Two causes: pvpoke's ranks crossed the rank<=5 line, or PokeMiners
published a NEW client game master (`gamemaster_pokeminers.json`, asked on every run) that flips a keep verdict of a
mon in the bag: a held move that is a plain TM now (its Legacy protection), a form that can or cannot evolve, an XXL
copy's size numbers or types, tradability, rarity. The lines above name the mons and what flipped (the same rows are in
`pogo_extract/system/analysis/gamemaster_review_pending.json`). **Show Benny those rows and wait** — keep policy is his
call. Run `python system/scripts/refresh_gamemaster.py --ack` only when he says so, never yourself, then cull again.
A new client game master that flips a verdict is HELD (`gamemaster_pokeminers.pending.json`), not installed: `--ack` installs it
(the previous file stays as `.bak-<date>`), `--reject` keeps the installed one and declines that batch -- ask him which.
The previous file stays as `gamemaster_pokeminers.json.bak-<date>`. A batch the engine cannot load, or a bag that cannot
be read, is never installed: the `WARN pokeminers:` / `STOP` line says which file and how to restore it.

## If the attach fails

The pipeline waits out PoGo's 45-second init storm on its own, so a relaunched game just costs a few silent
seconds. Two failures it cannot absorb:

- `[frozen] PID ... is in the frozen cpuset` — PoGo is backgrounded and writes will not land. Check what is on
  screen before acting; if he is using the phone, say so rather than yanking PoGo to the foreground. The
  persistent fix (`device_config put activity_manager use_freezer false`) is a **system setting** and needs his
  explicit approval first.
- `session is gone` / a new PID — PoGo restarted or crashed. Read the log before re-attaching:
  `adb -s "$ADB_TARGET" shell "logcat -d -b crash | grep -i pokemongo | tail"`. Report a genuine crash
  rather than quietly retrying, and never run back-to-back passes to "make sure" — that froze the game twice.

Reach the phone at `$ADB_TARGET` (the cloud hook sets it; default the Tailscale IP `100.98.158.56:5555`). Always
pass `-s`: bare `adb` fails with "more than one device" when two transports exist.
