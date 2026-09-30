"""RETIRED 2026-09-07 -- THIS SCRIPT IS INERT. It refuses to run.

WHAT IT USED TO DO
    Applied CLAUDE_TX to every pokemon marked TRANSFER by the FIRST cull generation.

WHY IT WAS RETIRED
    It selects on pokemon.cull_decision -- the v1 column, which still holds 142 stale TRANSFER rows against a sanctioned pile of 25. Running it would push 142 mons, the great majority of them keepers, onto a tag no preflight ever gated. It also hardcodes a dead service pointer (0x71bed7fe80) and writes the RETIRED CLAUDE_TX tag.

WHAT TO USE INSTEAD
    system/scripts/tag_ops.py apply for a single tag; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it from dashboard.py, which enforces the preflight gate)

PRESERVED
    The original body is kept verbatim in apply_tx_tag.py.bak. The invariant harness and the
    AST scanners skip *.bak, so the retired code survives as readable history
    that can no longer be executed or counted as a live pile pusher.

CONTEXT
    Retired by the unsanctioned-script sweep that followed the 2026-09 forensic
    audit, in which 24 pokemon were culled that a correct engine would have kept
    and 18 were lost for good (including a Great League #2-of-4096 Mudbray).
    This file could put mons onto a release tag that no preflight ever gated.
    Nothing in the tree imports it -- verified 2026-09-07 by a whole-tree scan
    for `import apply_tx_tag` / `from apply_tx_tag import`; the only inbound references were
    documentation rows in system/SCRIPTS_INDEX.md.
"""
import sys

sys.exit(
    "REFUSED: apply_tx_tag.py is retired and cannot run.\n"
    "  Why:         It selects on pokemon.cull_decision -- the v1 column, which still holds 142 stale TRANSFER rows against a sanctioned pile of 25. Running it would push 142 mo...\n"
    "  Instead use: system/scripts/tag_ops.py apply for a single tag; for a release pile, system/scripts/keep_policy.py -> system/scripts/build_tagsets.py -> system/scripts/preflight_transfer.py -> system/scripts/prune_tags.py (drive it ...\n"
    "  Original body preserved verbatim in: apply_tx_tag.py.bak\n"
)
