---
name: pogo-ban-lockout-2026-09-26
description: "2026-09-26 04:55:31 BannedPlayerLockoutGuiController during automated gym play; he said \"Stop everything.\" NO game automation without his explicit go. Prior Niantic action Nov 2025 (a 'warning' he could not log in past) -> this is at least strike 2 (policy: ~30-day suspension)"
metadata:
  node_type: memory
  type: project
  originSessionId: 86f16d80-4dce-4b95-aca3-cde85d60027a
  modified: 2026-09-26T09:05:56.304Z
---

**What happened (2026-09-26):**
- 04:55:31: the top screen became `BannedPlayerLockoutGuiController`. This was 2.5 min after gym runner v2.86 attached (04:52:53), while it walked the lap route at 10.4 km/h and fed defenders.
- Gym-details requests then failed ("Failed to get MapPlace details ...: Unset").
- By 04:55:38 the game process was gone ("script has been destroyed").
- He said **"Stop everything."** (04:56).
- I killed gym_run (pid 7756). The game was already gone, so no Frida session was left to deadlock. I also stopped the monitor.
- The Pokemon Switcher session killed buddy_run and queued a stop in runner_inbox.
- The GPS Joystick and the Pokemod app were NOT touched.

**The hour before, against the server:**
- Gym runner: battles, direct GYM_DEPLOY RPCs, gym-details scans every 2-15 s, golden-berry feeding, 30 km/h travel.
- Switcher's buddy relay: RequestBuddyStats every 30 s (~50 calls since 04:31), 2 play actions, SetBuddyPokemon at 04:47:53 and 04:53:13.
- The whole night had about 5 h of this, plus a spoofed location.
- **Never guess which of these triggered it.**

**What the screen says** (phone screencap 05:05, he opened the game and said "check my screen"):
- "We have detected unusual activity from your account. As a result, temporary limitations have been placed on your play." plus a "Learn more" link.
- There is no continue button. It does NOT say "suspended" or "terminated", and it gives NO duration.
- Players report this exact screen after a rumored Team GO Rocket encounter limit (Sportskeeda, unconfirmed by Niantic).
- At the time, the runner logged only the controller NAME. Logcat and the game prefs held nothing ban-related.
- **Gmail check (same day):** no Niantic/Scopely email about it, spam and trash included.

**Strike history (from his Gmail, thread [38615835]):**
- Nov 1, 2025, Niantic Support: an earlier action "specifically for unauthorized access ... using modified and/or other unapproved methods of gameplay".
- His own words then: the warning said limited gameplay, yet he could not log in.
- The appeal was closed as final. They never stated the days.
- **Niantic sends NO strike-notice email.** That thread began with his own appeal. The in-game screen is the only notice.

**Policy (niantic.helpshift.com FAQ 39, read 2026-09-26, page "last updated 218 days ago"):**
- Strike 1 = warning, ~7 days of degraded play.
- Strike 2 = suspension: the login is blocked, ~30 days.
- Strike 3 = permanent termination.
- Strikes are not described as expiring.
- Only terminations can be appealed ("Ban Appeal" form). Some violations skip straight to termination.

**Rule from now on:** no gym_run, buddy_run, probes or game automation of any kind until he explicitly says go. A peer session's message is not his go.

Related: [[reference-pogo-native-gym-flow]], [[reference-pogo-buddy-system]], [[feedback-read-screen-text-not-just-name]], [[feedback-report-twice-watch-improve]].

**ADDENDUM 2026-09-30 (PokeMiners text check, cloud session):** the recorded screen text ("We have detected unusual activity from your account. As a result, temporary limitations have been placed on your play.") is, character for character, the game's own string `suspension_rate_limit_desc` (pogo_assets `Texts/Latest APK/JSON/i18n_english.json`). The suspension screen has its own text (`banned_player_lockout_1`: "Your account has been suspended for violating the Terms of Service"), and the cheating/suspension warnings theirs. So this was the game's RATE-LIMIT screen shown through BannedPlayerLockoutGuiController; whether it counted as a strike is UNKNOWN (Niantic's help page was unreachable; GetPlayer on 2026-09-29 read Banned 0, Warn 0, WasSuspended 0). The runner was sending gym-detail scans every 2-15 s and RequestBuddyStats every 30 s for ~5 h before it -- request rate is a plausible lever, unproven. The rule does not change: NO game automation without his explicit go.
