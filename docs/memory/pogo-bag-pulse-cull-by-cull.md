---
name: pogo-bag-pulse-cull-by-cull
description: Bag Pulse shows the last 30 culls pass by pass (IV, PvP standing, cumulative wins) since 2026-09-29; ladder_history carries pvp_* standing per pass (ladder_report.pvp_metrics, backfilled from walk snapshots).
metadata:
  type: project
---

User 2026-09-29: "Can the bag pulse be more progressive about the changes over the last few culls? i cant really tell the
trend in iv improvement and pvp improvement." The day charts hid it (the ladder moves ~0.1/day) and PvP standing was
never recorded.

- `ladder_report.pvp_metrics(rows, kept_uids)` -> per pass `pvp_{gl,ul}_{ident,rank1,top5,top100}`: per PvP identity
  (pvid) the best OWN-stage rank among kept non-shadow copies at a stage that reaches the league (keep_config
  viability_margin, TODAY's rule for every pass), CP-blind like the rank tags. `python ladder_report.py --backfill-pvp`
  fills past entries from `.db_snapshots/*.before_sync.*.gz` (kept = walk bag minus that pass's `_pile`); entries with
  no snapshot (before 2026-09-23 16:51) stay without it. Re-run the backfill with `--force` after a viability change.
- gen_bag_pulse: first card "Cull by cull" = last 30 passes: window strip (from->to for ladder / best-per-stage /
  top-5 / #1 / top-100 forms; sums of stage bests beaten, new hundos, GL/UL #1 found, evolved/caught/released), a
  per-pass IV chart (tight dual axis), a per-pass PvP chart, a cumulative-wins step chart; KPI "PvP top-5 forms";
  a per-day "forms in the top 100" card; the pass table gained delta and top-5 columns.
- Verify a Bag Pulse change locally: wrap the fragment in a doctype, drop it in pogo_extract/system/analysis/ and open it
  through the `pogo-map` launch config (port 8731) -- the browser pane's claude.ai login is a different account, so the
  artifact URL 404s there.
