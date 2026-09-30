---
name: cull
description: Run the Pokemon GO cull cycle for this project - pull the game data from the phone, fresh bag recrawl, the 11-audit gate, tag sync to the phone, pages, push the data back, publish Bag Pulse - and report what to release. Use this whenever Benny says "cull", "cull again", "recull", "cull now", "run the cull", or asks to re-scan / re-audit / re-check his Pokemon, refresh the Transfer tag, or find out what is safe to release. Use it even when he phrases it as a question ("anything to cull?") or bundles it with other work ("fix X then recull"). This is the only sanctioned path to the irreversible Transfer pile, so prefer it over running any of the underlying scripts by hand.
---

# Cull

Four tool rounds per cull, from the repo root (a cloud session; the phone bridge must say `connected` —
`docs/cloud_setup.md` if not). Every round re-reads the whole session, so keep it to these four:

1. In the same message as loading this skill: `python tools/pogo_data.py status | grep '^inventory '; adb -s "$ADB_TARGET" shell pidof com.nianticlabs.pokemongo`.
   Phone version != here -> `python tools/pogo_data.py pull` first (`docs/data.md`). A new PID since the last pass -> `FAILURES.md`.
2. The cull, its report and the page's text in ONE command (log to a file: never pipe `full_audit.py` itself into
   `head`/`tail`, a broken pipe kills it mid-cycle; never add a guessed flag, unknown flags stop it, rc 2):
   ```bash
   cd pogo_extract && python full_audit.py > system/analysis/last_cull.log 2>&1; echo "rc=$?"; grep -E "bag [0-9]|AUDIT GATE|DONE --|STOPPED|frozen|session is gone" system/analysis/last_cull.log; sed -n '/=== REPORT ===/,$p' system/analysis/last_cull.log | grep -v '^\['; python bag_art.py --text
   ```
   full_audit = dashboard up -> game master freshness -> **fresh bag recrawl** -> walk tripwires -> Adventure-Effect roster ->
   **11 audits in parallel** -> tag sync -> ONE post-push session (reconcile, retire, Remote Trade, tag order) -> verify ->
   the report -> pages (gen_artifacts, gen_bag_pulse) -> dashboard down.
3. ONE message: the report (below), then two tool calls side by side:
   - Bash (repo root): `python tools/pogo_data.py push --group inventory && python tools/triple_check.py --gate | tail -3`
   - Artifact publish of the page `bag_art.py --text` just printed (in `pogo_extract/system/analysis/`):
     `collection_stats.html` (`oyebenny`) -> `https://claude.ai/artifact/59FFz2wZBv8sNC4CZJBmKn`; `bag_pulse_alt.html` (any other
     account) -> `https://claude.ai/artifact/BvcioQeAeZcposXoFHFE8Q`. No Artifact tool in this session? Say so in one line.

   ALWAYS push after a phone pass, even when the gate failed (the walk still changed the data). Refused = another session
   pushed since your pull: tell Benny, don't `--force`.
4. One closing line. The final check must say ALL CLEAR before you call the pass done.

## The one rule that matters

**Never release anything.** The cycle *tags* a Transfer pile; Benny releases by hand in game. Nothing in this
skill deletes a Pokemon, and no step should be added that does. The pile is irreversible, which is why eleven
independent audits stand in front of it.

## Something stopped?

`AUDIT GATE FAILED`, `GAME MASTER REFRESH STOPPED THE PASS (rc 5)`, a `[frozen]` / `session is gone` attach failure or a new
PID: **read `FAILURES.md` in this folder before doing anything else.** Never retry, work around it or sync by hand.

## Reporting the result

Lead with the action — he wants to know what to do, not what you ran:

```
**Release the N in the Transfer tag.** All 11 audits pass[, 0 BLOCK / 0 WARN].

Bag X/Y (Z free) · N tag changes pushed · Remote Trade N · <anything that changed>

**What improved** (since the last walk: evolved N, caught N) — new hundos, new #1s, new stage bests.

**Why each one is in the pile** — one numbered line per mon: what pushed it out, and whether that copy was
JUST CAUGHT or JUST EVOLVED (see memory feedback-just-caught-in-pile-explanations).

**Safety check:** N checked, none in any top 5 — closest <mon> at <league> #<n> as <stage>.

**Which way to evolve** — every `which way:` line full_audit printed (evolve_targets.py), in plain words.

**Power Up to 2500** — only when a Power Up tag holds mons: each one's exact price from the game master (dust / candy / XL candy)
against what you hold, "doable now" / "doable after exchanging N candy (if the game allows the exchange)" / "short X". Report only.
```

He expects all three sections EVERY cull (user 2026-09-24: "Where's my little thing about what got improved and
why each thing got culled"; "theres some that you dont tell me which to evolve it to"). **The cull writes it:**
full_audit ends with `=== REPORT ===` (cull_report.py) — relay that block, adding only the bag/audit line and
anything unusual from the log. Do not rebuild it by hand ("Why does it take you so long to make the report? it
shouldnt..."). Send the report BEFORE any follow-up work (the data push and Bag Pulse come right after; the
pages and the dashboard stop are already done by full_audit).

The Power Up block at the end of that report (2026-09-30) is advice only: it reads the tag files and this walk's balances and changes
nothing that is kept or tagged. Relay it as printed -- the exchange is the game's 100-candy-for-1-XL swap, which no tool here has ever
done, so its "if the game allows the exchange" stays in.

Then, briefly, only what is worth his attention: a count that moved, a new trophy, an audit that fired, an
upgrade now affordable. Skip anything that reads the same as last time — repeating a steady number every pass
trains him to stop reading.

**Bag and free-slot counts come only from this pass's walk** — the line `full_audit.py` prints, or a query
against the DB that same walk just wrote. Never quote a previous message or an older heartbeat; he has been
burned by a stale count before. If the bag line scrolled past, re-read it from `pokemon.db` plus
`player_state.json` (storage capacity is read live and never hardcoded).

Flag it clearly when free slots are low (under ~50) — that is when releasing actually matters.

## Notes

- The pile being **0** is a normal, good outcome. Say so plainly instead of hunting for something to release.
- `full_audit.py --audits-only` runs the gate with **no phone contact** — use it to check a code change before
  spending a phone pass.
- Timing is ~45s-2min. Most of it is the audits; the whole-bag rank sweep re-derives ~16.6k ranks each pass.
  The first cull in a fresh cloud VM is slower: it rebuilds the rank-table cache (not kept in the data store).
