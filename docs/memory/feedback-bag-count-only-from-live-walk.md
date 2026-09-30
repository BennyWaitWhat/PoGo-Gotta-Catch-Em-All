---
name: feedback-bag-count-only-from-live-walk
description: "Never state a bag count, free-slot count, or 'nothing changed since X' unless it came from a live bag walk in THIS turn. The DB, player_state.json, daemon log lines and my own earlier messages are all the PREVIOUS walk's numbers. Got this wrong 3x in one session."
metadata:
  type: feedback
---

User 2026-09-07: *"You need to improve. For example, always rescan pokemon bag before saying things like
3free when you're wrong."*

**What happened (three times in one session):**
1. Quoted the DB's 5,720 as the current bag right after saying the DB was 4 hours stale. Live walk: 5,748.
2. Told the user "bag still 5,747 (3 free), so nothing was released since the last cycle" — read off the
   autocull daemon's log line. The live walk 60 seconds later found 5,724 (26 free): he had released 23.
3. Earlier: found a "skipped 9 parse-failure entries" log line and nearly reported it as tonight's cause;
   it was from June.

**Why every one of those sources is stale by construction:**
- `pokemon.db` only changes on a walk. Between walks it is frozen at the last walk.
- `autocull_watch.box_state()` reads `SELECT COUNT(*) FROM pokemon WHERE in_bag=1` from that DB, so the
  daemon's "bag N/cap | free M" heartbeat is the previous walk's number wearing a fresh timestamp.
- `player_state.json` is the CAPACITY (live-read), not the count.
- My own earlier message in the same session is the oldest source of all.
- The user is actively playing: catching, hatching, evolving and RELEASING between every one of my turns.
  The bag moves by dozens in minutes (5,587 → 5,747 in one 5-minute daemon interval on 2026-09-06).

**The rule:** a bag count, free-slot count, or any "unchanged since" claim is only sayable if a live walk
produced it IN THIS TURN. Otherwise say "last walk: N at HH:MM" and label it as such — or just run the
walk. `full_audit.py` walks first, so the correct move on "recull" is to run it and quote ITS
`bag X/Y (free Z)` line, never the pre-run state. The cost of the walk is ~16 seconds; the cost of the
stale number is the user's trust.

**Generalisation** (same failure as [[feedback-verify-before-irreversible]] and
[[feedback-always-recheck-upstream]]): a timestamp on a log line is when it was WRITTEN, not when the
value was MEASURED. Before quoting any number, ask what measured it and when.
See also [[pogo-source-of-truth-db-rules]] — the DB is the source of truth for RULE inventory, not for
right-now counts.

**What the game's storage number counts (read live 2026-09-24):** "Pokémon 5743/5850" is `PokemonBagImpl.get_Count`. That's **Pokémon + eggs in incubators** (5734 + 7 = 5741). Eggs outside incubators don't count. The walk parses Pokémon only; eggs show up as pid0 entries and are skipped. So the cull used to understate the bag by the number of incubating eggs.
- Every walk now records `get_Count`, `get_PokemonOnlyCount`, `get_EggCount` and `get_IncubatedEggCount` to `system/analysis/bag_count.json`.
- full_audit's bag line and the cull report show game_count and free = cap − (Pokémon + incubated eggs).
- He caught this with "The bag is 5743/5850. Check for yourself...". I first guessed "all eggs count", which was wrong. Read the counters instead of guessing.
