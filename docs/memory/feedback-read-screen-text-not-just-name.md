---
name: feedback-read-screen-text-not-just-name
description: "Any warning/lockout/modal screen the game raises must have its TEXT captured and surfaced, not just its controller name -- the ban screen's reason was lost this way"
metadata:
  node_type: memory
  type: feedback
  originSessionId: d6a9a7ab-f13f-48eb-b075-69e3e4547939
  modified: 2026-09-26T08:59:35.863Z
---

On 2026-09-26 the gym runner logged `top screen: BannedPlayerLockoutGuiController` and, on five earlier occasions, `WarningModalDialog`. It logged only the controller names. Its "GAME SAYS" text reader covered only GlobalError, toast and quest controllers.

When he asked what Niantic said had triggered the action, there was no record: nothing in the logs, logcat or the game prefs.

Earlier that night he had said *"you might be not catching notes msgs or errors or something."* This was exactly that.

**Why:** a screen whose text was never read cannot be explained later. For a ban or strike notice, that text is the one thing he needs.

**How to apply:**
- Any tool that watches the game reads the text of EVERY modal, dialog, lockout, warning or error screen. It logs the text with "!!" so the monitor surfaces it, and saves a phone screencap next to the log.
- It never taps these screens away.
- When a runner has an unknown message kind or screen, it logs it loudly and never drops it silently (on_msg got a catch-all `else` that day).

Related: [[pogo-ban-lockout-2026-09-26]], [[feedback-report-twice-watch-improve]].
