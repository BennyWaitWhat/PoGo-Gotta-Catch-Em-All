"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Tagged 45 shadow non-top-IV duplicates as CLAUDE_TX.

WHY IT WAS RETIRED
    Reads shadow_tag_list.json (a one-off list from a retired shadow pass), writes the RETIRED CLAUDE_TX tag, and attaches to a hardcoded PID (31828) that has not existed since May 2026. The live shadow axes are Shadow Best GL / Shadow Best UL / Shadow IV #1 / Shadow IV #2, produced by the keep engine.

WHAT TO USE INSTEAD
    system/scripts/tag_ops.py; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in tag_45_shadows.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import tag_45_shadows` / `from tag_45_shadows import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: tag_45_shadows.py is retired and cannot run.\n"
    "  Why:         Reads shadow_tag_list.json (a one-off list from a retired shadow pass), writes the RETIRED CLAUDE_TX tag, and attaches to a hardcoded PID (31828) that has no...\n"
    "  Instead use: system/scripts/tag_ops.py; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, whic...\n"
    "  Original body preserved verbatim in: tag_45_shadows.py.bak\n"
)
