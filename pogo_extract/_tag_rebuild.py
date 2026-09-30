"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Rebuilt a 16-tag set from scratch on a freshly-nuked server.

WHY IT WAS RETIRED
    Its stated precondition is 'server has 0 tags', which is false today and destructive to assume against the live 47-tag set. Its TAG_PLAN names tags that do not exist in the live registry (Hundos, Nundos, JUMBO, From Ethan, From Florandez, TopShiny, Premium, Cull) and its 'Cull' tag is built from cull_decision_v9='TRASH', a RETIRED column.

WHAT TO USE INSTEAD
    system/scripts/tag_ops.py apply; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in _tag_rebuild.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import _tag_rebuild` / `from _tag_rebuild import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: _tag_rebuild.py is retired and cannot run.\n"
    "  Why:         Its stated precondition is 'server has 0 tags', which is false today and destructive to assume against the live 47-tag set. Its TAG_PLAN names tags that do n...\n"
    "  Instead use: system/scripts/tag_ops.py apply; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py...\n"
    "  Original body preserved verbatim in: _tag_rebuild.py.bak\n"
)
