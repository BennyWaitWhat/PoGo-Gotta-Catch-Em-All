---
name: pogo-accounts-and-line-pools-2026-09-26
description: Two trainers, separate data sets (oyebenny main, florandez active); account_guard stops a wrong-account walk; florandez runs "2 plain per evolution line" (keep_config line_pool_all) with pooled comb-up.
metadata:
  type: project
---

**Accounts** (user 2026-09-26: "make sure to keep oyebenny and florandez settings different"):
- Live set = the paths as always; `active_account.txt` names it (florandez now). Parked sets in `pogo_extract/accounts/<name>/`
  (pokemon.db, keep_config.json, ladder_history, last_report, stop_tags, .db_snapshots). `python switch_account.py <name>`.
- `account_guard.check` runs in pogo_pipeline right after attach: reads ClientPlayerProto.Name (PlayerService's PlayerInfo
  field, found by TYPE -- the service is obfuscated, the proto is not) and SystemExits before any DB write on a mismatch.
- Separate Bag Pulse per account: oyebenny 59FFz2wZBv8sNC4CZJBmKn (frozen), florandez BvcioQeAeZcposXoFHFE8Q
  (bag_pulse_alt.html = collection_stats.html with the title swapped). gen_bag_pulse reads live max_pokemon_storage now.

**florandez caps:** plain 2 / middle 1 / gender 2, costume Pikachu 2, shiny 4 (2 plain), rarity 3, card 2, Dmax 2 / Gmax 5,
XXL top 1, PvP best+shadow floor #55, line_pool_all true. oyebenny = its 03:11 config (plain 3/2/3, shiny 6/4, ...).

**Line pools** ("2 plain per evolution line" -> "this on", then "Just remember we have to comb up"): pattern_pools.pool_key
general branch -- key (('pool','line:'+line_root), form-suffix look, gender if ANY stage is dimorphic). Branches split
(each eeveelution / Vileplume / Alolan Raichu its own line). Ranked by IV at any stage; specials (costume/shiny) still take
plain slots (costume Charmanders pushed both plain Charizards out -- told him). dex_only is per POOL. Pooled comb-up in
keep_policy (late pass): a kept pre-evo is advised to its single same-pool final only when it beats the best kept copy
there (bar raised per promise), never own-stage PvP / collectible / dex_only. Mirrors: preflight _POOL_COUNTS, audit_cull
pool-wiped. First cull: pile 140; 7 promises he had just followed under the old per-stage rule broke.

**2026-09-27 21:3x -- back on MAIN.** Phone was logged in as trainer 'BennyValentinC'; guard stopped (set florandez). He
picked main -> `switch_account.py oyebenny` (florandez parked). account_guard.TRAINERS maps set name -> trainer name
where they differ ({'oyebenny': 'BennyValentinC'}); before this the guard suggested a non-existent set. First main cull
after the lockout: rc 0, 11/11 pass, pile 21, bag 5802/5850. Main Bag Pulse 59FFz2wZBv8sNC4CZJBmKn is live again (v95).
