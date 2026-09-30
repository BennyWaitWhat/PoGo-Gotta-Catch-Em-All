---
name: feedback-tell-me-what-to-expect
description: "User (2026-09-08): say up front WHICH steps touch the phone and WHEN, so he can use it in between; explain knobs in plain words with a concrete example (he called a CP-cap example 'bad', asked twice); a 1-agent workflow is worse than doing it myself; 'hurry up' = drop agent wrappers for mechanical checks, not drop the checks."
metadata:
  type: feedback
---

**What happened.** During a long rebuild he restarted the game several times because I never said which
phases needed the phone. His words: "you just dont tell me what to expect and i use my phone sometimes
while waiting for you." Then "1 Agent? Really?" when a serial phone step was wrapped in a workflow, and
"Why are you using an agent for verify?" for mechanical checks I could run in 4 minutes myself.

**How to apply.**
- Before any multi-phase run, state: which phase attaches to the phone, roughly when, what he must do
  (PoGo open + foreground, plugged in, don't restart), and that everything else is phone-free. Ask for an
  explicit `go` before the phone window; re-announce when it is done.
- Frida is single-client, so phone steps are inherently serial -> run them MYSELF (one `full_audit.py`
  call), never as a one-agent workflow. Agents earn their cost on parallel/independent work only.
- Mechanical verification (gate run, tripwires, set-compares, sandbox guard tests) -> do it directly and
  fast; keep the checks, drop the wrapper.
- Explain a knob with the plainest possible picture, one number, one consequence ("Abra tops out at
  1,517; Great League's door is 1,500; margin is how much room past the door we demand"). If he says he
  doesn't understand, change the example, don't restate it.
- Mid-run status answers must be grounded (read the journal/transcript), give elapsed + phase + honest ETA.

Related: [[feedback-pogo-session-conduct]], [[feedback-verify-before-irreversible]].
