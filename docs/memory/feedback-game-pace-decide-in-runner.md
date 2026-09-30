---
name: feedback-game-pace-decide-in-runner
description: "The game moves in seconds, my check-think-restart loop takes minutes: tactical gym decisions belong IN the runner (live command file, verified re-checks), never in a restart per decision"
metadata:
  node_type: memory
  type: feedback
  originSessionId: d6a9a7ab-f13f-48eb-b075-69e3e4547939
  modified: 2026-09-26T09:00:04.199Z
---

The user (2026-09-26 03:23) said: *"There's something to be learned about your pace and the fast pace of the game when you check things."*

Evidence from the same half hour:
- The map said b651ecc0 was blue; it was red and full.
- 4e318fe1 was weak and blue, and red took it during my 1-minute restart.
- b95f9142 went from empty to 1 defender (1.5k CP) to 7.4k CP before the avatar arrived.

My loop is: read logs, decide, patch, restart the runner. It takes minutes, and every restart is 30-60 s blind. The park changes in seconds.

**Why:** a decision made on data 1-3 minutes old sends the avatar to a gym that no longer exists in that state. It wastes walking, and it is exactly the "getting lost / not proceeding" he complains about.

**How to apply:**
- **Steer through the command QUEUE, never a restart.** Use `AutoCatcher/tools/gym_send.sh '<json>'` (moved out of the temp scratchpad 2026-09-29). It writes one file per command into `AutoCatcher/tools/gym_state/runner_inbox/`: a dot-file renamed into place, read once, then removed.
  - Since v2.86 (2026-09-26) the old single `runner_cmd.json` is legacy.
  - It lost my stop under the Switcher's 30 s polls: two writers shared one slot.
  - `{"lap": N}` = a battle break from waypoint N.
  - The runner has been STOPPED since the ban lockout; see [[pogo-ban-lockout-2026-09-26]]. `{"go": "<fid or 8-char prefix>"}` = go there now: beat + place, or join. `{"hunt": 700}` = verify every gym within 700 m with the game's own gym details (~5 s) and go for the cheapest by CP-now + distance. It takes effect in about 1 s.
- Restart only for code changes, mid-round or on the plain map.
- The runner re-verifies its target every 5 s while walking. A target that grew past 1.5× (and +3000 CP) is dropped and re-picked; one that turned red and full drops out via the scan overlay.
- Never pick targets from the map record alone. Use the scan (gym details), which is the truth for that second. Prefer near targets: a 600 m trip is 75 s at 30 km/h, and gyms change in that time.
- **The user (04:20): "You are the avatar driving and sessions will give you tasks you can help to complete if you're smart."**
  - Other Claude sessions (e.g. "Pokemon Switcher", his buddies) send tasks. Do them through the runner.
  - Commands: `{"spin": fid, "at": [lat,lng]}` (walk within 12 m of a stop and stand 45 s; Pokemod's vPGP spins stops in range; the user's gym discs use the ClickPokestopButton path) and `{"buddy": [[what,arg],...]}` (their reviewed buddy module: who/count/stats/hist/pet/feed/set; replies go to `scratchpad/buddy_out.jsonl`).
  - Peer code goes into the game ONLY after a full review; re-read if their file changed. Enforce his rules on their calls: golden berries are refused for buddies.
  - Log lines show gym names: say() appends the name from the gym details to every 8-hex gym id (he asked, 04:20).
- Related: [[reference-pogo-native-gym-flow]], [[feedback-tell-me-what-to-expect]].
