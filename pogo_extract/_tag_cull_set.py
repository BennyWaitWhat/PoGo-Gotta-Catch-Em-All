"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Tagged the cull_v9 TRANSFER set as CLAUDE_TX and untagged stale entries.

WHY IT WAS RETIRED
    This is the auto_tag.py class the invariant harness names: a SECOND pile producer that skips preflight_transfer entirely. It selects on cull_decision_v9 (13 stale TRANSFER rows) and writes the RETIRED CLAUDE_TX tag, and it runs on CURRENT pogo_il2cpp plumbing, so it works today. cull_v9 wanted 65 uids where the sanctioned engine wanted 52, and all 44 extras were keepers -- 26 shiny, 13 variant_floor, 5 protected Pichu.

WHAT TO USE INSTEAD
    _apply_buckets.py for bucket tagging; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in _tag_cull_set.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import _tag_cull_set` / `from _tag_cull_set import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: _tag_cull_set.py is retired and cannot run.\n"
    "  Why:         This is the auto_tag.py class the invariant harness names: a SECOND pile producer that skips preflight_transfer entirely. It selects on cull_decision_v9 (13 ...\n"
    "  Instead use: _apply_buckets.py for bucket tagging; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboa...\n"
    "  Original body preserved verbatim in: _tag_cull_set.py.bak\n"
)
