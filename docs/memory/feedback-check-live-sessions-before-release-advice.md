---
name: feedback-check-live-sessions-before-release-advice
description: Before saying "release the N", check no other Claude session on this project is mid-way through a keep-rule change.
metadata:
  type: feedback
---

On 2026-09-23 I resumed after a 3-day gap, ran a cull and reported "Release the 13 in the Transfer tag".
Another session (a live sibling, not a finished one) was at that moment implementing a keep-rule change he had
asked for that morning -- best GL + best UL per species -- which made 4 of those 13 keepers. He released
from my report first. Drifloon 84%, Rattata 78%, Snover 53% and Lopunny 47% are gone; the rule now protects
each species' NEXT-best copy (Lopunny's best GL fell from #86 to #230).

**Why:** a cull is only as current as the rules on disk. Two sessions can share one project, one phone and one
pile, and neither sees the other's plans -- the other session saw my 16:50 cull and did not know who ran it.

**How to apply:** at the start of any session, and always before telling him to release, list recent
transcripts in `~/.claude/projects/<project>/*.jsonl`; if another one was written in the last ~30 minutes,
read its tail (it may be mid-change or waiting on his answer) and say so before any phone pass or release
advice. Two live sessions must never both attach to PoGo. See [[feedback-one-phone-pass-not-three]],
[[feedback-tag-only-never-release-no-xxs]].
