---
name: feedback-read-in-game-records
description: "User rule (2026-09-25) — ALWAYS report the game's own in-game records (the fields the game itself keeps/shows), never a number I derived; label anything else as my measurement."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-25T04:58:40.542Z
---

"You should ALWAYS read the in game records, you need to re do the whole this." I reported "buddy +3.31 km since set",
which was my own arithmetic (player KmWalked minus BuddyPokemonProto.StartKmWalked). The user's buddy page said 0.00.
That 0.00 turned out to be the DAILY "Walk together 0.00 / 2.00 km" heart. Its driver isn't found yet
(maybe BuddyObservedData.TodayStatsShownHearts, a MapField I haven't decoded).
The candy "Walking progress 11/20 km" on screen = PlayerStats.KmWalked − BuddyPokemonProto.LastKmAwarded
(13856.449 − 13845.377, checked against a screenshot). That one moves with every credited batch.
`BuddyObservedData.TotalStats.KmWalked` (467.62) is a lifetime stat that does NOT update live. I first called the
buddy "not credited" from it, which was wrong.
Server credit at a real 10.33 km/h: batches of about 330 m every ~2 min, essentially 100% of the distance moved
(2 eggs hatched on 2026-09-25 00:48 and 00:54). At a real ~12 km/h, only about 2 of ~14 km counted.

**Why:** a derived number can contradict what the game shows, and then I'm confidently wrong.

**How to apply:**
- Every progress number comes straight from the game's record, named by its field:
  PlayerStatsProto.KmWalked, EggIncubatorProto Start/TargetKmWalked, BuddyObservedData.TotalStats.KmWalked,
  BuddyPokemonProto.LastKmAwarded.
- If the screen shows a value I can't map to a record, screenshot the screen (read-only) and match it before claiming anything.
- My own measurements (GPS movement) are fine, but label them "moved (GPS)" and never mix them into "progress".
- Tools: `AutoCatcher/tools/track_walk.py`, `tools/buddy_read.py`.
Related: [[feedback-verify-before-irreversible]], [[reference-gps-joystick-control]].
