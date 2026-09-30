# Refresh (re-crawl + profile)

**Verified 2026-09-07.**

## Purpose

Bring `pokemon.db` into full sync with the live bag. `pogo_pipeline.py` is the re-crawl — it is what
writes the `fresh_*` columns, upserts new catches, and marks transferred mons `in_bag=0`.

In normal operation you do **not** run it directly: `python full_audit.py` runs it as the first step
of the cycle (via the dashboard's `/api/recrawl`, alongside `read_player_state.py`), then six audits,
then the hard gate, then the sync. Run it standalone only when you want the crawl without the audits
and sync.

Note that `autocull_watch.py` also runs the gated cull on a timer when free bag space is low, so the
DB and the tagsets can change under you. Check `system/analysis/autocull_watch.log` and
`dashboard_run.log` before concluding that something you ran caused a change.

## Preconditions

- Pokemon GO **open and foregrounded** on the phone. A backgrounded app gets parked in the
  `cpuset:/background` freezer, where reads still work but **writes silently never land**.
- ADB reachable at Tailscale IP `100.98.158.56:5555`.
- frida-server running on device (port-forwarded to `127.0.0.1:27047`).
- Cold attach after an app restart takes ~10s for IL2CPP class init. `get_session()` refuses to
  attach unless `libil2cpp.so` is mapped and the process is >45s old.

Wait for a safe window rather than retry-looping — **every attach probe is a crash roll**:

```
python -c "import sys;sys.path.insert(0,'.');import pogo_il2cpp as pg;print(pg.wait_ready_to_attach(timeout_s=300))"
```

## Quick check: is a refresh even needed?

```
python system/scripts/check_freshness.py
```

Exit 0 = FRESH (no drift). Exit 1 = RE-CRAWL NEEDED (prints new/gone counts).

**This is a report, not a fix.** It is read-only and writes nothing — it cannot refresh anything. Use
it to decide whether to run the crawl. (It is *not* a replacement for the deleted `run_fresh_poll.py`;
`pogo_pipeline.py` is.)

## Command

```
python full_audit.py            # normal: crawl + six audits + gate + sync + verify
python full_audit.py --no-sync  # crawl + audits only, never touches the phone's tags
python pogo_pipeline.py         # the crawl alone
```

### What the crawl does (in order, single Frida attach)

1. Walk the full `PokemonBagImpl` LinkedHashMap — extract proto bytes for every mon.
2. Reconcile the DB: upsert new catches, mark transferred mons `in_bag=0`.
3. Refresh size categories from the proto display sub-message.
4. Mirror server tags into `auth_tag_names`.
5. Read pokedex hundo flags.
6. Run the `cull_v9` classification pass.
7. Print a sanity-check summary.

Step 6 writes the `cull_decision_v9` column. **That column is a dead legacy signal, not the keep
law** — it disagrees with the live engine. The pile comes from `keep_policy.py` alone.

### Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Skip tag operations (no server-state writes) |
| `--tag-transfers` | **Legacy, do not use.** Tags the v9 TRANSFER set as `CLAUDE_TX` — a dead tag that is not the pile and is not gated by pre-flight. The sanctioned pile path is `keep_policy` → `build_tagsets` → `preflight_transfer` → `prune_tags --atomic` → `set_db_tags_from_files`. |

## Post-pipeline: deep profile

```
python system/scripts/deep_profile.py
```

Generates `system/analysis/deep_profiles.json` with per-specimen PvP viability, power-up costs,
evolve-to-meta opportunities, and transfer-safety flags. `system/scripts/query.py` reads it.

## Expected output

- `pokemon.db` updated with fresh proto data for all in-bag mons.
- Console summary: bag size, new catches, gone (transferred), tag drift.
- Typical timing: the full `full_audit.py` cycle runs ~70s.

## Troubleshooting

- **Frida attach fails**: only ONE session may be attached at a time. Kill any stale Python holding
  the session, re-verify with `adb shell pidof com.nianticlabs.pokemongo`, then wait with
  `wait_ready_to_attach()`.
- **DB locked**: another process has the DB open (often `dashboard.py` or `autocull_watch.py`).
  Close it and retry.
- **"The DB changed but nothing did anything"**: `pokemon.db` is a **WAL** database. A checkpoint
  rewrites the main file and bumps its mtime while the content is byte-for-byte identical, and merely
  *opening* it as a reader updates `pokemon.db-shm`. Compare **content hashes**, never mtime.
- **Everything reads fine but writes don't stick**: check the freezer —
  `adb shell cat /proc/<pid>/cgroup | grep cpuset`. `/background` means writes will not land.
  Foreground the app. `ready_gate.py` checks this automatically on write paths.
- **IL2CPP NPE on first call**: normal cold start. Wait 5-10s and retry.
