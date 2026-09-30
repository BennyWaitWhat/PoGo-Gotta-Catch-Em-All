"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Tagged the 80 cull-v8 TRANSFER pokemon as CLAUDE_TX.

WHY IT WAS RETIRED
    Selects on cull_decision_v8, a RETIRED column (0 TRANSFER rows in the live bag), and writes the RETIRED CLAUDE_TX tag. That the column is empty today is an accident of data, not a gate -- any re-run of a v8-era engine refills it.

WHAT TO USE INSTEAD
    system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in tag_v8_transfers.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import tag_v8_transfers` / `from tag_v8_transfers import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: tag_v8_transfers.py is retired and cannot run.\n"
    "  Why:         Selects on cull_decision_v8, a RETIRED column (0 TRANSFER rows in the live bag), and writes the RETIRED CLAUDE_TX tag. That the column is empty today is an a...\n"
    "  Instead use: system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)\n"
    "  Original body preserved verbatim in: tag_v8_transfers.py.bak\n"
)
