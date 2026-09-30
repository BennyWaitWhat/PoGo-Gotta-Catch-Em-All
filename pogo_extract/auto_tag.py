"""auto_tag.py -- RETIRED 2026-09-02. This script is a SECOND, UNGATED pile producer. Do not re-arm it.

WHAT IT USED TO DO
  Recrawl -> cull_v9 decision pass -> its own local pre-flight -> rewrite pokemon.db
  auth_tag_names from `cull_decision_v9` -> push the "Transfer" tag -> prune_server_tag.py
  strip every server member NOT in that column.

WHY IT IS RETIRED (measured against the live DB on 2026-09-02, read-only)
  * cull_v9's TRANSFER set was 65 uids; the SANCTIONED engine's pile (keep_policy.py ->
    build_tagsets.py -> Transfer.txt) was 52. The 44 uids cull_v9 wanted that keep_policy does
    NOT are all KEEPERS by the user's own config: 26 shiny, 13 variant_floor, 5 protected
    (pid 172 Pichu -- the sole entry in keep_config `protected_keep_all_pids`), 2 of them
    PvP rank <= 5.
  * The push was a REPLACEMENT, not an addition: set_tags() rewrote auth_tag_names wholesale,
    tag_ops.py apply read that column, then prune_server_tag.py removed every server member
    absent from it. Net effect on the phone: those 44 keepers TAGGED "Transfer" and 31 correct
    pile members UNTAGGED -- in the one tag the user hand-releases from.
  * Nothing here read keep_config.py, keep_policy.py or preflight_transfer.py. cull_v9's caps
    are hardcoded and historical (SHINY_TOP_N=5 vs the live config's 8) and it models no
    cosmetic / dynamax / gigantamax / rarity / shadow axis at all.
  * Its own preflight() could not catch this: measured, it returned ZERO hits on that pile.
    The shiny guard groups by species_name and only fires when kept < 5, so all 26 piled
    shinies passed it; its LEGENDARY rule reads is_legendary=1, a column that is NULL for
    1854 / 5559 in-bag rows.

THE ONE SANCTIONED PILE PRODUCER
  keep_policy.py -> build_tagsets.py -> preflight_transfer.py (rc != 0 ABORTS)
  -> prune_tags.py --atomic -> set_db_tags_from_files.py
  Drive it from the dashboard (POST /api/sync, or the rewired Auto-tag button), never from here.

The original body is preserved at auto_tag.py.prelockdown.bak for forensics only. Restoring it
re-creates the defect above; if some piece of it is wanted (the catcher pause/resume, say), port
that piece into the sanctioned path instead of reviving this file.
"""
import sys

MSG = (
    "auto_tag.py is RETIRED -- it was a second, ungated Transfer-pile producer.\n"
    "Measured on the live DB it would have tagged 44 KEEPERS (26 shiny, 13 variant_floor,\n"
    "5 unconditionally-protected Pichu) for release and untagged 31 real pile members.\n"
    "\n"
    "Use the sanctioned path instead:\n"
    "    python system/scripts/keep_policy.py\n"
    "    python system/scripts/build_tagsets.py\n"
    "    python system/scripts/preflight_transfer.py     # rc != 0 means STOP\n"
    "    python system/scripts/prune_tags.py --atomic\n"
    "    python system/scripts/set_db_tags_from_files.py\n"
    "or the dashboard: POST /api/sync (the Auto-tag button now runs exactly these steps).\n"
    "\n"
    "Rationale + the original body: see this file's docstring and auto_tag.py.prelockdown.bak.\n"
)


def main():
    sys.stderr.write(MSG)
    return 2


if __name__ == "__main__":
    sys.exit(main())
