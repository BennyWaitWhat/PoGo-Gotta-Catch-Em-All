"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Tagged 59 Dynamax non-top-3-IV duplicates as CLAUDE_TX.

WHY IT WAS RETIRED
    The tag it maintained was nuked and is not in the live registry (system/SCRIPTS_INDEX.md records it as 'Nuked tag; no longer needed'). It reads dmax_xfer_list_v2.json, writes the RETIRED CLAUDE_TX tag, and hardcodes a dead PID (22409) plus stale SERVICE/BAG pointers. Dynamax and Gigantamax are now capped axes inside keep_config.json.

WHAT TO USE INSTEAD
    nothing -- the axis it served is handled by the keep engine via keep_config.json

PRESERVED
    The original body is kept verbatim in tag_dmax_strict.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import tag_dmax_strict` / `from tag_dmax_strict import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: tag_dmax_strict.py is retired and cannot run.\n"
    "  Why:         The tag it maintained was nuked and is not in the live registry (system/SCRIPTS_INDEX.md records it as 'Nuked tag; no longer needed'). It reads dmax_xfer_lis...\n"
    "  Instead use: nothing -- the axis it served is handled by the keep engine via keep_config.json\n"
    "  Original body preserved verbatim in: tag_dmax_strict.py.bak\n"
)
