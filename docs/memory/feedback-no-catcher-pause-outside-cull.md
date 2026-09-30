---
name: feedback-no-catcher-pause-outside-cull
description: Never pause the on-phone catcher; the walks already coexist with it (CATCHER_PAUSE_ENABLED=False) -- and he WANTS phone reads for research
metadata:
  type: feedback
---
Never pause the catcher -- and never CLAIM a pass pauses it without reading full_audit.py first. 2026-09-29 ~02:45 I announced "the catcher pauses briefly" before a read-only walk; he: "Why on earth are you pausing the catcher. Don't". The claim was FALSE: full_audit.py has `CATCHER_PAUSE_ENABLED = False` since 2026-09-24 ~23:10 (cull + catcher run at the same time; the freeze was fixed by the C liveness walk), so the walk never touched the catcher. I then over-corrected to "no more phone contact"; he: "I want you to have contact with the phone, i told you to read from the phone."

**Why:** a stale belief from an old summary, stated as fact -- the "don't say shit without checking" failure.
**How to apply:** read-only walks (`full_audit.py --no-sync`) are fine and wanted when he asks to read from the game; they do not pause the catcher. Keep CATCHER_PAUSE_ENABLED False. Never let parallel agents attach Frida -- one client from me, serialized. Related: [[feedback-one-phone-pass-not-three]], [[pogo-on-phone-catcher]], [[feedback-verify-before-irreversible]].
