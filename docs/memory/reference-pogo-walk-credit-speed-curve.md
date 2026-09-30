---
name: reference-pogo-walk-credit-speed-curve
description: "MEASURED 2026-09-25 — server walking-distance credit (KmWalked: eggs + buddy candy) vs exact speed, plus the ~2-min credit cadence; full credit to ~10.5 km/h real, partial to ~11.1, zero from ~11.9."
metadata:
  node_type: memory
  type: reference
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-25T06:45:05.894Z
---

Measured 2026-09-25 01:46-02:44 with `AutoCatcher/tools/speed_grid.py`:
- GPS Joystick Pro API: a straight WALK line, SPEED set exactly with wobble 0, controls HIDDEN.
- The judge is the game's own PlayerStatsProto.KmWalked record, hooked at parse (0.429.1 parses it in the
  obfuscated 1-arg methods `mxx`/`mxy`, NOT MergeFrom).
- Each speed gets two windows that start and end at credit updates. Window 1 absorbs leftover credit and is not
  judged; window 2 is judged against GPS distance moved.

| set km/h | real | credited |
|---|---|---|
| 10.40 | 10.32 | 91% (full) |
| 10.60 | 10.48 | 91% (full) |
| 10.80 | 10.61 | 66% |
| 11.00 | 10.78 | 32% |
| 11.20 | 11.08 | 10% |
| 11.50 | 11.51 | 3% |
| 12.00 | 11.87 | 0% |
| 13.00 | 12.86 | 0% |
| 14.00 | 13.68 | 0% |

- **91% = full credit.** The server credits straight lines between the positions it samples, which is slightly
  shorter than my 0.25 s GPS path.
- Credit fades between ~10.5 and ~11.1 km/h real. The likely cause: per-sample speed estimates straddle a cutoff
  near 10.5. It is never 100%-or-0 in that band.
- The user believed "12 or 14 works". It doesn't: measured 0%.
- **Cadence:** KmWalked updates every 111-124 s (median ~123 s) while distance is being credited. Nothing arrives
  when nothing is credited. Each update is roughly 2 min of straight-line distance.
- Eggs and buddy CANDY both run off this counter (the candy display = KmWalked − BuddyPokemonProto.LastKmAwarded).
- The buddy "Walk together" heart (BuddyAffectionKmInProgress) did NOT move even at 5 km/h, so it's not speed-gated.
- **Fine sweep, one window each (02:49-03:00, so leftover from the previous speed can inflate a result):**
  10.65 = 123% (at least full), 10.70 = 77%, 10.75 = 81%. The edge sits between set 10.65 and 10.70
  (real ~10.5 km/h).
- **Best setting:** SPEED 10.6 (real ~10.48), clean two-window FULL credit, and set live 2026-09-25 03:0x. 10.65
  is probably full but was only measured once, in a contaminated window.

Related: [[reference-gps-joystick-control]], [[feedback-read-in-game-records]].
