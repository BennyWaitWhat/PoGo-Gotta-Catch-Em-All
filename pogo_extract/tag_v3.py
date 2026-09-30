"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Tagged the 125 'missing transferables' found by cull engine v2.

WHY IT WAS RETIRED
    Two dead inputs. It reads tag_list_v3.json, the output of the RETIRED cull engine v2, and writes the RETIRED CLAUDE_TX tag, which has 0 members in the live bag (verified 2026-09-07). Neither the pile it computes nor the tag it writes exists in the current system.

WHAT TO USE INSTEAD
    pogo_pipeline.py for the crawl; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in tag_v3.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import tag_v3` / `from tag_v3 import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: tag_v3.py is retired and cannot run.\n"
    "  Why:         Two dead inputs. It reads tag_list_v3.json, the output of the RETIRED cull engine v2, and writes the RETIRED CLAUDE_TX tag, which has 0 members in the live b...\n"
    "  Instead use: pogo_pipeline.py for the crawl; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py,...\n"
    "  Original body preserved verbatim in: tag_v3.py.bak\n"
)
