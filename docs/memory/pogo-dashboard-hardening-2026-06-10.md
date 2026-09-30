---
name: pogo-dashboard-hardening-2026-06-10
description: "The 5-agent dashboard audit — 37 fixes applied; the dry-run-not-dry + stale-process + Event.txt-vacuous gotchas, and how to preview/restart the dashboard."
metadata: 
  node_type: memory
  type: project
  originSessionId: d44dc321-2608-42e7-870c-24289b882f3e
---

# Dashboard deep-audit + 37 fixes (2026-06-10, 5 audit agents → synthesis → applied & verified)

All 37 in `dashboard.py` (+ studio_data.py, keep_config.py, keep_policy.py); snapshots `*.uxbak`. Verified end-to-end via Flask **test client** (every route, XSS-free
render, JSON shapes) AND a **live browser** (preview_start 'pogo-map' → preview_eval `location.href='http://127.0.0.1:8765'` → DOM queries; screenshots work once the nav settles). 0 console errors.

## Durable gotchas this surfaced (the non-obvious ones):
- **Dashboard "dry-run" Sync was NOT dry.** `--dry-run` reached only prune; `refresh_evolve_shiny` still
  did live Frida tag writes and `set_db_tags_from_files` overwrote `auth_tag_names` (the server-truth
  mirror `/api/tagdiff` reads) → next preview falsely said "already in sync." FIX: dry = prune `--dry-run` +
  **no set_db** (`*([] if dry else [(...set_db...)])`); refresh_evolve_shiny left the push steps 2026-09-12
  (prune pushes Evolve_Shiny.txt). Verified by capturing the step list (monkeypatch start_job) without executing.
- **The dashboard is a long-lived process — on-disk code edits DON'T apply until restart.** The audit
  itself caught the live PID serving pre-fix code (config saves 500'ing on the caps.xxs KeyError). Added
  `/api/health` returning `src_stale` (mtime of dashboard.py/keep_config.py vs `_BOOT` capture) → the UI
  paints a persistent "⚠ code changed — restart" badge. **To restart: confirm `/api/job` idle, then
  `Get-NetTCPConnection -LocalPort 8765 -State Listen | Stop-Process -Force` (kill the listener PID), then
  relaunch `python dashboard.py`.** A fresh process shows src_stale all-False.
- **The preflight gate may NEVER trust a tagset FILE for leak detection** — `build_tagsets` strips Transfer
  uids from every tag file before the gate reads them, so `tagset ∩ Transfer = ∅` BY CONSTRUCTION (the
  Event.txt "route" to catch a leaked location_card mon was vacuous). Gate clauses must read DB columns
  directly. Added an unconditional `fresh_has_location_card` clause (was the one uncovered keeper class).
- **Adding ANY cap to keep_config DEFAULTS requires `_CAP_BOUNDS[name]` (+ `_psc_cats`)** or `validate()`
  KeyErrors on every dashboard save. Hardened validate() to `_CAP_BOUNDS.get(k); if None: continue` so a
  future skew can never kill saves again. (Same lesson as [[pogo-ultracode-audit-2026-06-09]] round 2.)
- **Studio/dashboard keep-status MUST come from `policy_reasons.json` (uid absent = Transfer), never a
  client re-rank.** The Studio render now uses engine truth when untouched (`m.in_transfer`) and only
  estimates in a what-if "touched" cap-drag. Matches [[reference-pogo-tag-inheritance]]/the F3 fix.

## Other applied (all ADDITIVE, single-page preserved, no XXS in UI per [[feedback-tag-only-never-release-no-xxs]]):
atomic writes of policy_reasons.json/6_Transfer.txt (tmp+os.replace); job Cancel (taskkill /T) + stdin=DEVNULL;
`_child_env()` (PYTHONUTF8, drop COSMETIC_CAP) + errors='replace' on every child; BUSY flag so preview/tagdiff
don't wipe the job log; `@before_request` cross-origin POST guard (curl/no-Origin still allowed); `@errorhandler(500)`
JSON; DB-age KPI (amber>1h/red>24h) + age warning in the Sync confirm; pile_stale badge (6_Transfer vs Transfer);
What-changed: growing transfer pile = amber; rules explainer rewritten for the collapses/gender-split + dynamic
rarity roster + rule 16; header links /report+/plan; search shows form/variant; tagdiff intersects the bag + lists
untracked personal tags; XXL studio sort by showcase score (231=231 vs engine); sprite fallback → inline pokeball;
all "release"→"tag for transfer" language. `gen_master_plan.py`→`/plan`, `gen_line_report.py`→`/report` routes.
Studio per-species overrides now LOAD saved values + clear via explicit nulls.
Workflow scripts: `.wf_dashboard_audit.js`.
