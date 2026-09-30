"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Tagged the cull-v8 TRANSFER set as CLAUDE_TX (fast singleton discovery).

WHY IT WAS RETIRED
    RETIRED pile generation on LIVE plumbing -- the most dangerous of this set. It selects on cull_decision_v8 and writes the RETIRED CLAUDE_TX tag, but unlike its siblings it uses the CURRENT pogo_il2cpp helpers (get_session, find_singleton, find_protos_for_uids), so it attaches and writes successfully today. It never calls preflight_transfer and has no ready_gate.

WHAT TO USE INSTEAD
    system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in tag_v8_transfers_v2.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import tag_v8_transfers_v2` / `from tag_v8_transfers_v2 import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: tag_v8_transfers_v2.py is retired and cannot run.\n"
    "  Why:         RETIRED pile generation on LIVE plumbing -- the most dangerous of this set. It selects on cull_decision_v8 and writes the RETIRED CLAUDE_TX tag, but unlike i...\n"
    "  Instead use: system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)\n"
    "  Original body preserved verbatim in: tag_v8_transfers_v2.py.bak\n"
)
