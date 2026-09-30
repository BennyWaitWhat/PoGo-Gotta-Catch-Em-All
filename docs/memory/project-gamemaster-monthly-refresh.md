---
name: project-gamemaster-monthly-refresh
description: "pvpoke_gamemaster.json (base stats behind EVERY PvP rank) must be refreshed at least monthly (user 2026-09-08). system/scripts/refresh_gamemaster.py downloads PvPoke's current file, diffs, recomputes ranks, exits 2 if any keep decision crossed rank<=5; full_audit.py runs it automatically when >30 days old and stops before sync on exit 2; audit_invariants WARNs past 30 days. Since 2026-09-30 it also asks PokeMiners on every run and guards the CLIENT game master (gamemaster_pokeminers.json): a new batch is diffed against the bag before install, exit 2 on an in-bag keep-verdict flip, stamped in a .meta, audit_invariants I2.7 WARNs. It also judges each held form's costume flag, refuses a batch under 90% of the installed one on 14 content counts (--accept-smaller only on Benny's word) and names ids a batch prints as numbers."
metadata:
  type: project
---

**Rule (user, 2026-09-08): "This should be checked often, at least once a month."** The game master had
gone 85 days with no producer. First refresh 2026-09-08: 1,724 -> 1,742 species (23 added = shadow/mega
variants, 5 removed = squawkabilly colour ids + cradily_b, none referenced by form_overrides), 2 base-stat
edits (Mega Mewtwo X/Y, unreachable by the ranker), 68 movepool changes (ranks are stat-product, unaffected).
**0 rank changes, 0 rows crossed the rank<=5 line.**

**Mechanism:** `python system/scripts/refresh_gamemaster.py` (self-skips under 30 days; `--force`;
`--check-only` exits 3 when stale). It refuses to install a file that would orphan an override
(`form_overrides_complete.py` still naming a removed speciesId => NULL ranks, the Mudbray class), backs up
to `pvpoke_gamemaster.json.bak-<date>`, recomputes via `rank_cache.py`, and **exits 2 when any in-bag row
crosses rank<=5 or goes NULL** -- `full_audit.py` then returns 5 BEFORE recrawl/sync. `autocull_watch.py`
runs full_audit.py (and so this check) only while free slots are below 150 (its default --free), at most once per
1800 s; otherwise the refresh runs only when full_audit.py itself runs (the /cull skill). The dashboard FULL AUDIT
button runs `full_audit.py --audits-only`, which does NOT refresh: there the only guard is `audit_invariants`' >30-day
WARN.

Same day: the four fossil flag columns (is_legendary/is_mythical/is_ultra_beast/is_paradox) were retired
from keep_policy (roster RARE_PIDS only) -- measured 0 rows would lose protection, 197 roster mons had
NULL flags anyway. audit_cull.py still reads them as an over-protective superset check (harmless).
Viability margin left at 0 by the user's choice (Abra, whose own L50 hundo tops out at 1,517 vs GL 1,500, counts as viable).

Related: [[pogo-forensic-cull-audit-2026-09]], [[pogo-pile-gate-2026-09]], [[feedback-pvp-rank-not-iv-threshold]].

**2026-09-30 -- the CLIENT game master (gamemaster_pokeminers.json) is guarded too.** It used to be downloaded over the
installed file on the 30-day clock with one check (>= 1500 pokemonSettings): no diff, no stamp, no review (0.407 -> 0.427 moved
80 in-bag rows: 22 held a move that went from "no normal roll" to "plain TM", 58 changed evolvability). Now
`refresh_gamemaster.py` asks PokeMiners' 13-byte `latest/timestamp.txt` on EVERY run; a new batch is downloaded, diffed and judged
against the bags BEFORE install (the active account's and every resting account's parked one: the file is shared) by `gm_guard.assess` (detect_legacy's two pool functions, evolvable_forms -- the form's
evolvability, the whole evolution chain's requirements and the middle-stage flag that caps costume copies -- size_line: the size
numbers, XXL bounds and types an XXL keep is scored by, for the copy's own stage AND every later stage it can become (review
2026-09-30: an XXL Ponyta is kept by its projected Rapidash points) -- isTradable, isTransferable, rarity class: the engine's own
code, run on the candidate). A flip installs it with a dated backup, writes the
SAME review record and exits 2 (`--ack` clears it); a candidate the engine cannot load is never installed. Every batch is stamped
in `gamemaster_pokeminers.json.meta` (batch time, APK, sha256, last check; in data_manifest.txt); `audit_invariants` I2.7 WARNs
when it is unstamped, behind the phone's APK, unchecked for 14 days or older than 150 days (PokeMiners' longest 2026 gap was 133).
`refresh_gamemaster.py --selftest` proves all of it offline.

**2026-09-30 (later) -- three more checks, the follow-up to PR #27 (0 tag, 0 keep-reason, 0 pile changes on the 2026-09-30 bag):**
1. **Costume status is judged per in-bag mon.** costume_forms calls a form a costume when its NAME says so OR the game master flags
   `isCostume` (add only), so a batch that flags or unflags a held form moves those copies between the costume and plain ladders.
   `gm_guard` runs costume_forms' own parser and rule on the candidate. 0.407 -> 0.427 flags 14 more forms, 10 of them held, all
   already costumes by name: 0 flips.
2. **Content canary.** `load_gm` counted pokemonSettings by KEY, so renamed templateIds, renamed base stats or an emptied evolution
   table passed. `gm_guard.content_counts` = 14 counts (pokemon templates, base stats, evolution edges, isTransferable / isTradable
   true, quick / charged move lists, extended templates, size bands, forms, evolution quests, legendary / mythical / ultra beast
   species); a candidate under 90% of the INSTALLED file on any of them is refused like a truncated one (WARN, `rejected` in the
   .meta, I2.7 WARNs every cull). Backtest over the 239 consecutive steps of PokeMiners' 240 batches (2021-06 .. 2026-08): 2 trip
   (2021-11-03, the bogus apk9999 folder; 2022-08-03, extended templates 1630 -> 0), 0 of the 154 since 2023 (the closest: 99.7%).
   BUT measured against the last INSTALLED batch, one genuine format change (2021-11: formSettings 949 -> 763 forms) would have
   refused every batch for four years -- so `refresh_gamemaster.py --accept-smaller`, ONLY on Benny's word, lets a refused batch
   through to every other check (the loaders, the keep-verdict flips, the review stop).
3. **Ids printed as numbers.** 0.381.2 / 0.395.1 printed 57 / 536 ids as enum NUMBERS (38 of the 240 batches hold at least one):
   `evolvable_forms._load` crashed on them, and a crash left half a table that every later call returned. Now
   `evolvable_forms.normalize_ids` names them (a form from its own template's templateId, else the enum name in the batch's or the
   installed file's spelling; a pokemon / family id from the dex) on every download (`gm_guard.normalize_file`: the stamped sha256
   is of the NAMED bytes, `ids_named` in the .meta) and inside `_load` itself; `costume_forms._parse_gm` names numeric forms
   through form_enum.json; a failed `_load` leaves no table. Proof: 0.427 with all 15,706 of its ids as numbers names back to
   identical content and is judged CLEAR; all 1,255 numbers in 0.395.1 are named.

**2026-09-29:** `refresh_rankings()` in refresh_gamemaster.py fetches pvpoke's META rankings (rankings-1500/2500/10000.json from raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/) on the SAME 30-day clock, into system/analysis/pvpoke_rankings/, and prints what moved in/out of the top-200 (the Power Up / Unlock 2nd Move meta gate, keep_config pvp.power_up_meta_top / unlock_meta_top = 200). Fewer than 300 entries or no 'score' = keep the old file.
