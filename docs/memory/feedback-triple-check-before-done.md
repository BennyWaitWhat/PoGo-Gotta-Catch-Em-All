---
name: feedback-triple-check-before-done
description: "Before telling Benny anything is \"done\" -- run tools/triple_check.py (ALL CLEAR required) and get every owning session's confirmation; \"Same for future posterity\""
metadata:
  node_type: memory
  type: feedback
  originSessionId: a147e4df-96f5-4d9a-96fd-bbb3fff35fe1
  modified: 2026-09-30T02:59:16.028Z
---

Benny, 2026-09-29 (end of the cloud migration): "IS everyone done yet? if not, hurry it up and be helpful. Once done, triple check everything. Same for future posterity."

**Why:** several Claude sessions share one repo, one phone and one data store; a claim of "done" from one of them has been wrong before (stale counts, an unannounced cull from `--help`, files left uncommitted by a peer). He wants proof, not assurances -- and he wants the habit to outlive this session.

**How to apply:**
- Before saying "done": `python tools/triple_check.py --gate` (after `python tools/pogo_data.py pull`) must end with `ALL CLEAR` (0 FAIL). It checks: git clean + in sync with origin/main + no open PRs/stale branches; every .py compiles, every .sh parses, the self-tests, the full_audit unknown-flag guard; a key/token/email scan of ALL git history; every relative doc link; the phone data store (sha256 vs meta, unpushed local changes, half-uploads); the 11-audit gate.
- For a release or a handoff: `python tools/triple_check.py --fresh` (fresh clone of origin/main + data pull + everything above) = what GitHub really holds.
- Ask each owning session (Pokemon Inventory, AutoCatcher, Gym Battle) for its own status -- committed + pushed, data group pushed, its tests -- and relay their answers; name anything still waiting on Benny.
- Report WARNs honestly; never round a WARN or an unverified step up to "done".
- CI runs the same checker on every push, so the tool itself can't rot.

Related: [[feedback-verify-before-irreversible]], [[feedback-total-diligence-no-spotcheck]], [[pogo-repo-and-session-ownership-2026-09-29]], [[feedback-never-probe-scripts-with-help]].
