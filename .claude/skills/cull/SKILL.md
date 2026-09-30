---
name: cull
description: Run the Pokemon GO cull cycle for this project - pull the game data from the phone, fresh bag recrawl, the 11-audit gate, tag sync to the phone, pages, push the data back, publish Bag Pulse - and report what to release. Use this whenever Benny says "cull", "cull again", "recull", "cull now", "run the cull", or asks to re-scan / re-audit / re-check his Pokemon, refresh the Transfer tag, or find out what is safe to release. Use it even when he phrases it as a question ("anything to cull?") or bundles it with other work ("fix X then recull"). This is the only sanctioned path to the irreversible Transfer pile, so prefer it over running any of the underlying scripts by hand.
---

# Cull

Four steps, all from the repo root (a cloud session; the phone bridge must say `connected` — `docs/cloud_setup.md` if not):

```bash
python tools/pogo_data.py pull
```
(the game data lives on the phone — `docs/data.md`; skip only if this session already pulled and nothing pushed since)

```bash
cd pogo_extract && python full_audit.py
```
That is: dashboard up -> game master freshness -> **fresh bag recrawl** -> walk tripwires -> Adventure-Effect roster ->
**11 audits in parallel** -> tag sync to the phone -> retire stale tag shells -> verify -> Remote Trade tag ->
Evolve-for-Size tag -> the report -> pages (gen_artifacts, gen_bag_pulse) -> dashboard down. Never add a guessed flag
(unknown flags stop it, rc 2) and never pipe it into `head`/`tail` — a broken pipe kills it mid-cycle.

```bash
python tools/pogo_data.py push --group inventory
```
ALWAYS after a phone pass, even when the gate failed (the walk still changed the data). Refused = another session
pushed since your pull: tell Benny, don't `--force`.

Then publish Bag Pulse: `pogo_extract/system/analysis/collection_stats.html` to
`https://claude.ai/artifact/59FFz2wZBv8sNC4CZJBmKn` (Artifact tool, `url` = that link; the alt account's is
`https://claude.ai/artifact/BvcioQeAeZcposXoFHFE8Q`). No Artifact tool in this session? Say so in one line.

## The one rule that matters

**Never release anything.** The cycle *tags* a Transfer pile; Benny releases by hand in game. Nothing in this
skill deletes a Pokemon, and no step should be added that does. The pile is irreversible, which is why eleven
independent audits stand in front of it.

## If the audit gate fails

`AUDIT GATE FAILED` means the sync did **not** run — that is the gate working, not a crash. Do not retry it, do
not work around it, and do not sync by hand. Read the failing lines it prints, find the real cause, fix it, and
re-run. A failing audit has caught genuine bugs many times; treating it as noise is how a keeper gets released.

Common shapes:
- `promises ... culled after evolving` — the engine reserved a slot at a stage the sandbox then culls it from.
  Usually a stage-keying bug making a stage read as EMPTY; see `pogo-one-speciesid-many-plain-forms` in memory.
- `8-layer cull ... pvp rank` — a rank<=5 spread reached the pile. Stop; that is the Mareep failure mode.
- `structural inv. ... BLOCK` — an invariant about the MODEL, not the membership. Read its `DO:` line.

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
```

He expects all three sections EVERY cull (user 2026-09-24: "Where's my little thing about what got improved and
why each thing got culled"; "theres some that you dont tell me which to evolve it to"). **The cull writes it:**
full_audit ends with `=== REPORT ===` (cull_report.py) — relay that block, adding only the bag/audit line and
anything unusual from the log. Do not rebuild it by hand ("Why does it take you so long to make the report? it
shouldnt..."). Send the report BEFORE any follow-up work (the data push and Bag Pulse come right after; the
pages and the dashboard stop are already done by full_audit).

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
