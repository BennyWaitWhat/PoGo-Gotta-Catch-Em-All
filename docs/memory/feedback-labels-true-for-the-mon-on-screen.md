---
name: feedback-labels-true-for-the-mon-on-screen
description: "Every in-game tag must be literally true for the mon it sits on (its own stage, its own form); a chain/line fact needs its own tag name -- \"these are the kinda small things I need resolved\""
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-09T02:58:00.387Z
---

A tag the user reads in-game must be true of THAT mon as it is right now. "GL Rank 1" on a Raboot that
is #7 as a Raboot (and #1 only as a Cinderace) is wrong to him even though the data behind it was correct.
He called it out immediately ("Why is Raboot tagged as GL rank 1 if... it isnt?") and added "These are the
kinda small things I need resolved."

**Why:** he verifies tags against the Pokemod overlay on the mon's own screen; a label that needs a
footnote ("...after evolving") reads as a bug and erodes trust in the whole tag set, which feeds an
irreversible release.

**How to apply:** when a label summarises a LINE or a FUTURE state, give it a distinct name (`Evo GL Rank 1`,
`Evolve Twice`) rather than reusing the present-tense one; when a user asks "why is X tagged Y", answer
from the row's own data first, then fix the label semantics if the tag is not literally true. Treat these
"small things" as first-class work, not polish.
Related: [[pogo-rank-tags-per-stage-2026-09]], [[feedback-tell-me-what-to-expect]].
