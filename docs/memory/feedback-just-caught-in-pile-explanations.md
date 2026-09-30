---
name: feedback-just-caught-in-pile-explanations
description: "When explaining a cull pile, mark which better copies were JUST CAUGHT / just evolved (arrivals since the previous walk) so he sees new stock coming in and old stock going out"
metadata:
  node_type: memory
  type: feedback
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-24T04:26:23.508Z
---

When I explain why each pile mon was tagged, say explicitly which of the better copies are **just caught** (or just
evolved) since the previous walk, and which pile mons are OLD stock finally outdated by them. He said on 2026-09-24:
"I like it when you say 'Just caught', its easier to understand whats new an improving coming in and which old stuff
is finally getting outdated."

**Why:** the pile is only interesting to him as a story of improvement -- a 73% Stufful losing its XXL slot to a
just-caught 80% XXL Stufful is the point; "outside plain floor" alone is not.

**How to apply:** arrivals = uids in pokemon.db that are absent from the previous `.db_snapshots` before_sync gzip
(scratchpad `pile_arrivals.py` does this; `pile_why.py` marks them `*caught`). Per pile mon: "old X% — pushed out by
the just-caught Y%" or "old stock, ladder was already full (A%, B%, C%)". Also count the arrivals that were kept
(new keepers) vs arrivals that went straight to the pile. See [[feedback-number-findings-then-ask]] for the pile
format and [[feedback-evolve-into-open-slot-beats-release]] for the comb-up side.
