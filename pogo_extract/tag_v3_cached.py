"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Re-ran the v3 tagging against a cached service-instance pointer.

WHY IT WAS RETIRED
    Same retired cull-v2 input (tag_list_v3.json) and the same retired CLAUDE_TX tag, plus it hardcodes raw heap addresses (SERVICE_INSTANCE 0x6ff1d41f80, TAG_PROTO 0x70139999c0) captured from a PoGo process that exited in May 2026. Those pointers now name whatever happens to occupy that address.

WHAT TO USE INSTEAD
    pogo_pipeline.py for the crawl; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in tag_v3_cached.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import tag_v3_cached` / `from tag_v3_cached import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: tag_v3_cached.py is retired and cannot run.\n"
    "  Why:         Same retired cull-v2 input (tag_list_v3.json) and the same retired CLAUDE_TX tag, plus it hardcodes raw heap addresses (SERVICE_INSTANCE 0x6ff1d41f80, TAG_PR...\n"
    "  Instead use: pogo_pipeline.py for the crawl; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py,...\n"
    "  Original body preserved verbatim in: tag_v3_cached.py.bak\n"
)
