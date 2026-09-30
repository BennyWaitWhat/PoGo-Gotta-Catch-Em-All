"""Emit the on-catch fodder gate that the phone-side pre-filter reads.

PURPOSE. Tag obvious junk AT CATCH TIME so less accumulates for the batch cull. This is a
PRE-FILTER, not a replacement for the cull -- it is deliberately high-precision / low-recall.

WHY IT IS SHAPED THIS WAY (all measured against the live bag, 2026-08-31):
  * Pokemod's own Transfer-on-Catch rule, copied exactly, tags 2518 of this collection's KEEPERS.
    Their law is per-mon; this collection's is cohort/cap based. On FRESH catches alone it still
    tags 24 keepers/day vs 38 real fodder. Unusable as-is.
  * Adding a COHORT SURPLUS gate (species+form already holds >= N kept copies and every one of them
    beats this mon) plus LEGACY-MOVE protection drops it to ZERO false positives across 7 days
    while still catching ~11 genuine fodder. surplus>=10 measured: 0 FP @1d, 0 FP @7d, 1 FP @30d.
    Raising the threshold does not remove that last one and guts recall (11 -> 1), so 10 it is.
  * The batch (full_audit.py) reconciles tags in BOTH directions, so a rare mistake here is stripped
    before the user ever releases. That backstop is what makes an optimistic pre-filter safe.

SAFETY: emits data only. Never tags, never releases. The consumer treats a missing/stale gate as
"tag nothing".
"""
import collections
import io
import json
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "pokemon.db")
REASONS = os.path.join(HERE, "system", "analysis", "policy_reasons.json")
LEGACY = os.path.join(HERE, "legacy_accurate.json")
OUT = os.path.join(HERE, "system", "analysis", "catch_gate.json")

SURPLUS = 10   # measured sweet spot: 0 FP over 7 days, 11 fodder caught


def main():
    keep = {k.lower() for k in json.load(io.open(REASONS, encoding="utf-8"))}
    legacy_uids = {e["uid_hex"].lower() for e in json.load(io.open(LEGACY, encoding="utf-8"))}

    c = sqlite3.connect(DB)
    # Per (species, form) cohort of KEPT copies, IVs descending. The bar is the SURPLUS-th best:
    # a new catch at or below it cannot displace anything, because the cohort already holds
    # SURPLUS copies that all beat it.
    coh = collections.defaultdict(list)
    for uid, nm, form, iv in c.execute(
            "SELECT lower(uid_hex), species_name, COALESCE(form,0), COALESCE(iv_total,-1) "
            "FROM pokemon WHERE in_bag=1"):
        if iv >= 0 and uid in keep:
            coh[(nm, form or 0)].append(iv)

    # Which MOVES make a mon legacy-protected. Derived from the mons the engine already flags, so
    # this tracks the engine rather than duplicating its move tables.
    legacy_moves = set()
    for uid, m1, m2, m3 in c.execute(
            "SELECT lower(uid_hex), COALESCE(move1,0), COALESCE(move2,0), COALESCE(move3,0) "
            "FROM pokemon WHERE in_bag=1"):
        if uid in legacy_uids:
            for m in (m1, m2, m3):
                if m:
                    legacy_moves.add(int(m))
    c.close()

    bars = {}
    for (nm, form), ivs in coh.items():
        if len(ivs) >= SURPLUS:
            ivs.sort(reverse=True)
            bars[f"{nm}|{form}"] = ivs[SURPLUS - 1]

    gate = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "surplus": SURPLUS,
        "note": ("tag a NEW catch only if it carries no protected axis, its moves are not legacy, "
                 "and its (species|form) bar exists and its iv_total is strictly below it"),
        "bars": bars,
        "legacy_moves": sorted(legacy_moves),
    }
    io.open(OUT, "w", encoding="utf-8").write(json.dumps(gate))
    print(f"wrote {OUT}")
    print(f"  cohorts with a bar : {len(bars)}  (species+form holding >= {SURPLUS} kept copies)")
    print(f"  legacy move ids    : {len(legacy_moves)}")
    print(f"  size               : {os.path.getsize(OUT)} bytes")


main()
