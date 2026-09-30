---
name: feedback-report-twice-watch-improve
description: "If you report something more than twice, it needs to be watched, reviewed, understood, and improved upon" -- recurring issues get a counter, a root cause and a fix, never another hand-wave
metadata:
  type: feedback
---

His words (2026-09-26, about repeated "feed not applied" reports):
- *"Stuff like this needs to be automated and improved upon, not hand waved."*
- *"if you report something more than twice, it needs to be watched, reviewed, understood, and improved upon."*

**Why:** I kept reporting the same symptom (wasted Golden Razz, a recurring error popup) as news each time instead of fixing it.

**How to apply:** on the third report of anything:
1. **Watched.** A counter or record the tool itself prints, e.g. the runner's "FEED RECORD (10 min)" line or a tally in STATS.
2. **Reviewed.** Pull every occurrence from the logs, not just the latest.
3. **Understood.** Find the common trigger from the data. Never state an unverified game mechanic as the cause.
4. **Improved.** Ship the fix, then check that the counter moves.

Examples from 2026-09-26:
- Wasted feeds: 18% in the knockout reading vs 4% later, so the feeder skips the knockout reading.
- A stop that was lost: two writers shared one command slot, so it became the runner_inbox queue.
- "The Gym battle has already been completed! (29)": 8 in 1,454 rounds, auto-recovered in 3-4 s.

Related: [[feedback-read-screen-text-not-just-name]], [[feedback-game-pace-decide-in-runner]].
