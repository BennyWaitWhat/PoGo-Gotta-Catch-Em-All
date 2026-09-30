---
name: feedback-do-it-yourself-workflows-too-slow
description: "He cancelled a 40-min workflow (\"Do it yourself\") -- for PoGo work do it inline; a workflow only for a truly parallel read-only sweep, and never when he's waiting on storage."
metadata:
  node_type: memory
  type: feedback
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-24T00:15:53.746Z
---

2026-09-23: "I think these workflows are taking too long...." then, after a 5-agent sandbox+review workflow ran
40 minutes, "That other workflow i canclled because it took 40min. Do it yourself." Doing it inline took ~10 min:
merge the cancelled builder's sandbox diff (git merge-file current base sandbox), fix what the audits flag, replay
keep_policy + build_tagsets + `full_audit.py --audits-only` offline, then one cull pass.

**Why:** his storage is usually full and he is playing while he waits; review agents re-derive the whole project
from scratch each time. The project's own 10 audits + the lost-keeper fixtures ARE the adversarial review for keep
changes -- run them instead of spawning reviewers.

**How to apply:** default to doing the change myself, verifying with the offline audits, then the cull. Even when
ultracode reminders say "use workflows", his explicit instruction wins. A background read-only research sweep is
OK only if it never blocks what he is waiting for. If a workflow is cancelled, harvest its sandbox before redoing
work. Related: [[feedback-pogo-session-conduct]], [[feedback-tell-me-what-to-expect]].
