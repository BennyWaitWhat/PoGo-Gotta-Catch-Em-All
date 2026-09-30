---
name: feedback-cull-report-sections
description: Every cull report needs What improved + Why each pile mon (just caught/evolved) + Which way to evolve; send it before any follow-up work
metadata:
  node_type: memory
  type: feedback
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-24T21:48:27.053Z
---

On 2026-09-24 he asked "Where's my little thing about what got improved and why each thing got culled and whatnot....". I had started building a feature before sending the cull report. Earlier the same day he said "theres some that you dont tell me which to evolve it to".

**Why:** the report is how he acts on a cull. It tells him what to release, what is new, and which button to press when an evolution can go more than one way (Gloom → Vileplume, not Bellossom; Eevee → which eeveelution; Charcadet → one of each).

**The report is automatic (2026-09-24 17:46):** full_audit ends with `=== REPORT ===`, which is `cull_report.py`'s output. Relay it; don't rebuild it by hand. He asked "Why does it take you so long to make the report? it shouldnt..." after 5–10 min of manual digging.
- "Since the last report" comes from `system/analysis/last_report.json` (walk stamp, pile, keep reasons, evolve targets). An interrupted pass doesn't move it.
- The story for each pile mon: a lost keep reason → the new holder of it (just caught/evolved); "you evolved it from the last pile"; "just evolved, meant to become X" (a wrong branch).
- The shiny cap pools genders; plain ladders are per gender (dimorphic species).

**Paste it in chat, in full, every cull** (user 2026-09-24: "I want you to print the report to me here."). Never just say it was printed in the cull output. `python cull_report.py` re-prints the same report for the same walk.

**How to apply:**
- Send the full report FIRST, then do any follow-up work.
- Sections: Release the N / bag line; **What improved** (evolved N, caught N, new hundos / #1s / stage bests); **Why each one is in the pile** (numbered, "just caught" / "just evolved", see [[feedback-just-caught-in-pile-explanations]]); safety check; **Which way to evolve**.
- The "which way" lines come from full_audit's `which way:` output (`evolve_targets.py`). Branches are from the game master, so quote their requirement text (e.g. Charcadet → Armarouge needs "defeat 30 Psychic-type", not an armor item).
- The template lives in `.claude/skills/cull/SKILL.md`.

**2026-09-26 ("Fix everything."):** "Which way to evolve" also prints `X -> Y, then STOP -- do not evolve it on to Z` for
every promise whose stage can evolve again (he evolved an Evolve-Next Tympole to Seismitoad twice). A pile mon that is
the best AS its stage but loses to its species' Best at another stage is a note ("one per species"), not a CHECK;
cut-off notes are one line per mon; an empty kept-list names the copies that stay. Remote Trade: a game-refused mon
already on the tag (gym defender) is FROZEN -- one refused write sank the whole request, adds included.

**Never truncate (2026-09-26):** "dont do this. always print it all out." -- after "...and 61 more new keepers". Every list in the report (What improved, the pile, PvP lines) is printed in FULL, in the tool (cull_report no longer caps at 15) AND in my chat message -- no "+N more", no "...and N others".
