---
name: pogo-pile-gate-2026-09
description: "The ONLY sanctioned route to the irreversible Transfer tag: preflight_transfer.py writes preflight_stamp.json -> prune_tags.py --atomic refuses without a fresh matching stamp. Every other tag pusher must refuse pile tags via tag_ops.is_pile_tag(). A gate whose only output is an exit code is unobservable."
metadata:
  type: project
---

**THE LESSON (2026-09-07).** A whole session of hardening left the biggest hole open: `prune_tags.py` --
the script the RUNBOOK tells a human to run -- pushed the Transfer pile with **no keeper check at all**
(the word "preflight" did not appear in the file; a bare `python prune_tags.py` pushed all 46 tags
including Transfer by default; `--force` bypassed the only gate it had). Root cause was not a bypass but
**unobservability**: `preflight_transfer.py` produced only an exit code, so nothing downstream could
prove it had run. Then `apply_tagsets.py` turned out to be the same defect one directory over -- add-only
(a UNION that can never self-correct), writing the DB mirror directly (erasing the drift it caused), no
`--dry-run`. Three verifiers in a row correctly returned go=false; the third found `apply_tagsets` after
the first two holes were sealed.

**THE CONTRACT.** `system/analysis/preflight_stamp.json` is written by `preflight_transfer.py` ONLY on a
full pass (every failure/exit path deletes any stale stamp): `pile_sha256` = sha256 of the EXACT
`Transfer.txt` bytes vetted, `pile_uids`, `config_sha256` = `keep_config.fingerprint()` (NOT file bytes),
`db_sha256` = `pile_provenance.db_content_sha256`, `generated` UTC, `schema` 1. `prune_tags.py` refuses
(exit 2) any push naming the pile unless a stamp exists, parses, matches the CURRENT `Transfer.txt` hash,
the live config fingerprint and the live db hash, and is < 30 min old. FAIL CLOSED; `--force` does NOT
bypass it (it only bypasses `ready_gate`). Proven: 7/7 tamper cases, 16/16 stamp-integrity cases and
17/17 pile spellings refuse; non-pile tags are unaffected. A stamp (not a subprocess) because Frida is
single-client and the dashboard already runs preflight as a gate step.

**EVERY OTHER PUSHER REFUSES PILE TAGS** before `pg.get_session()` via `tag_ops.is_pile_tag(name)`, whose
`_norm_tag` strips a directory path and a `.txt` suffix (`Transfer.txt` slipped past it once).
`apply_tagsets.py`, `prune_server_tag.py`, `test_atomic_changes.py` (now uses a scratch tag) and the
`tag_ops.py apply` CLI all refuse. `audit_invariants.py` recognises a runtime `is_pile_tag(` + exit as
gated, and I7 stat-line fidelity + `regress_pvp_keepers.py` (18 historical lost-keeper spreads, all must
come back KEEP) run every cull as part of `full_audit.AUDITS`.

**Beware a detector that cannot see its own recommended fix** -- three false BLOCKs tonight were the
harness objecting to remediation it had asked for (CPM collapsed into `cpm_table.py`; a doc string
naming `push_armored_tags.py` matched as a call). Prefer importing the real runtime value over
AST-scraping a literal.

Related: [[pogo-forensic-cull-audit-2026-09]], [[pogo-capped-vs-keepall-bug-class]],
[[feedback-transfer-preflight-every-axis]], [[pogo-granular-tags-2026-09]].

**2026-09-24 hardening (design review of the one-session cull):** (X1) `reconcile_tags --fix-server` refuses the pile tag before any write -- it could bulk_tag_many onto Transfer with no stamp. (X3) full_audit fingerprints the pile's MEMBERSHIP right before the 11 audits and sends it with /api/sync; the dashboard passes `--expect-pile-members` to preflight, which FAILS (no stamp) if the pile it vets has other members -- a mid-pass recompute used to push an un-audited pile. (Stage 3, user "3. sure") no gym excuse: preflight never reads deployment and never attaches. B11: tag_ops.ensure_ready restarts the 8 s create gap. X4: proof-pending is recorded right after the sync, whatever its rc.
