"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    One-off cleanup pass that realigned the CLAUDE_TX and 'Max Battle' tags.

WHY IT WAS RETIRED
    Both tags it maintains are retired: CLAUDE_TX has 0 members in the live bag and 'Max Battle' is not in the live registry. It also reads cull_decision_v9, a RETIRED column.

WHAT TO USE INSTEAD
    system/scripts/reconcile_tags.py --fix-server

PRESERVED
    The original body is kept verbatim in _fix_claude_tx.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import _fix_claude_tx` / `from _fix_claude_tx import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: _fix_claude_tx.py is retired and cannot run.\n"
    "  Why:         Both tags it maintains are retired: CLAUDE_TX has 0 members in the live bag and 'Max Battle' is not in the live registry. It also reads cull_decision_v9, a R...\n"
    "  Instead use: system/scripts/reconcile_tags.py --fix-server\n"
    "  Original body preserved verbatim in: _fix_claude_tx.py.bak\n"
)
