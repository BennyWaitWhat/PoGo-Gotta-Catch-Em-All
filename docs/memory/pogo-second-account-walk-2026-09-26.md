---
name: pogo-second-account-walk-2026-09-26
description: Since 2026-09-26 05:20 the ACTIVE account is a second one (storage 1000, lvl 70); main archived in archive_main_account_20260926/; separate Bag Pulse; released_pids.json; still no account guard.
metadata:
  type: project
---

2026-09-26 05:10: `full_audit.py` walked a second account logged into the phone (bag 986/1000, 26 hundos) and wrote it
into pokemon.db: 984 foreign rows in_bag=1, the main account's 5,792 rows flipped to in_bag=0 (NOT deleted -- the
<70%-of-last-bag guard skipped the purge). player_state / candy / dex / tagsets / policy files all described that
account. The 11-audit gate FAILED (Traded by E+F empty, Zygarde stat line, game-master drift, 6 Stop tags) so NOTHING
was pushed to it.

**Self-heal:** the next walk on the main account sets in_bag=1 on its mons and rewrites every derived file; the 984
foreign rows go in_bag=0 and the 2-crawl purge deletes them on the walk after. Never restore pokemon.db from a
.db_snapshots copy for this -- the walk already fixes it.

**Open defect (not fixed, user said stop):** no account guard. Pipeline should refuse (before writing the DB) when the
walked account differs -- e.g. storage capacity / trainer name vs the last run. Until then: before a cull, if the bag
line shows a capacity other than ~5,850, STOP and ask which account is on the phone. See [[project-pogo-extract]].

**05:20 update -- he switched for good** ("You're in a whole new account now. Same system. Get them set up and cull. Delete
all previous tags"; main is under the 04:55 lockout). Done:
- Main account archived: `pogo_extract/archive_main_account_20260926/` (pokemon_MAIN_0424_before_sync.db.gz = last good main
  DB, old .db_snapshots, tagsets, ladder_history, last_report, policy_reasons). pokemon.db now holds the new account only
  (the first walk's 2-crawl purge dropped the main rows).
- All 12 old tags on the new account deleted (safe_nuke 4 + retire 3 + later 1; DeleteTag refuses after ~4 per session).
- SEPARATE Bag Pulse: https://claude.ai/artifact/BvcioQeAeZcposXoFHFE8Q ("Alt Bag Pulse", built from
  system/analysis/bag_pulse_alt.html = collection_stats.html with the title swapped). The main one (59FFz2wZBv8sNC4CZJBmKn)
  is frozen at v93 -- never republish it with this account's data.
- `released_pids.json` (949 species: both dexes + the main bag): keep_policy.build_evo_graph unions it into the dex gate,
  so a young dex no longer makes Herdier/Dusclops/Pawmo read as final stages. step_read_dex grows it every walk.
- Same keep_config for both accounts (he said "same system").
