---
name: feedback-number-findings-then-ask
description: "Before acting on anything I investigated (removals, cleanups, code fixes), present NUMBERED findings + proposed actions and WAIT for his picks -- even after he said 'nuke it' or 'fix it'."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8fde11a7-6340-4cdf-8f4e-02a95910c52b
  modified: 2026-09-23T23:20:54.928Z
---

User 2026-09-22, mid-Syncthing-removal: *"didnt i say number ur findings and then run them by me?"*
He had said "You can nuke anything related to Syncthing ... trace it all through. Just tailscale." I traced
it across PC + phone and executed everything in one go (service delete, config/markers to the Recycle Bin,
phone package/config removal, Magisk boot-script rename). The same session I also patched keep_policy.py and
synced tags without showing him the finding first.

**Why:** "nuke X" / "fix it" authorizes the GOAL, not skipping his review of the list. Some steps were
irreversible (phone Syncthing config deleted), and a script bug in the unreviewed run broke part of it
(Android toybox `sed 's/\r$//'` treats `\r` as a literal `r` -- it chopped `/usr` to `/us`, so the package
uninstall silently failed). A numbered review pass is exactly where that gets caught.

**How to apply:** investigate read-only -> numbered list (what it is, what I propose, reversible or not,
anything that could break) -> wait for his picks -> do only those -> report back by the same numbers.
**UPDATED 2026-09-23** -- he narrowed this: *"you need to fix everything you find along the way. Workflow."*
Tooling DEFECTS I find while working (wrong baselines, hidden error reasons, stale fallbacks, audit gaps) are now
fixed without waiting: diagnose + adversarially review the patch (a workflow), apply, verify offline, then report
by number. Still ask first for: anything irreversible or on the phone, system settings, deleting data, and any
collection-POLICY choice (what gets kept -- caps, thresholds like the pinned XXL showcase cut). A fix that would
change which mons are kept is a policy change: show it before it reaches the pile.
Related: [[feedback-tell-me-what-to-expect]], [[feedback-verify-before-irreversible]],
[[feedback-dont-change-system-settings-without-asking]].
