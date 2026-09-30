---
name: feedback-always-recheck-upstream
description: Never report a version/compatibility conclusion from earlier in the session — re-query upstream every single time before stating it.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9e97229e-bbef-4f0b-940e-b84b513b701e
  modified: 2026-08-21T02:11:07.969Z
---

**Always re-check upstream live before asserting any version or compatibility claim. Never reuse a check from earlier in the same session, and never restate a conclusion from memory.**

**Why:** On 2026-08-20 I told the user "WaEnhancer is current, WhatsApp is just ahead of it — don't update WhatsApp." That was a conclusion from a check run earlier in the same session. In the interim **six** newer WaEnhancer builds had shipped, and `1.5.5-31bf87c4` (2026-08-05) had already added WA 2.26.28/29/30 support — exactly the version the user was blocked on. The fix had been sitting there for two weeks. The user caught it ("WhatsApp is still ahead?!") and then told me plainly: *"I shouldn't have to remind you to check. You need to always check."*

This is especially dangerous with **nightly/rolling-build projects** ([[user-phone-setup]] — Dev4Mod/WaEnhancer ships every few days, chsbuffer/NexAlloy autobuilds, JingMatrix/Vector canaries). A check that is hours old is already stale for these.

**How to apply:**
- Before any "X is up to date" / "no update available" / "X is incompatible with Y" statement → run the `gh api repos/<owner>/<repo>/releases` query *again*, right then. Cheap query, expensive mistake.
- Read the **release bodies**, not just tag names — WaEnhancer keeps the same `1.5.5` version string across many commit-tagged builds, so the tag alone does NOT reveal that WhatsApp support changed. The supported-WA-version list lives only in the changelog text.
- Same rule for "still broken" claims — re-verify from the live LSPosed log (`/data/adb/lspd/log/modules_*.log`), and check the log TIMESTAMPS: an `Unsupported version` line from before an update is not evidence of current breakage. Filter to entries after the change (`awk "/<timestamp>/,0"`).
- Session length is the trap: the longer a session runs, the more likely any earlier finding has gone stale. Treat prior tool output as a lead, never as current truth.
