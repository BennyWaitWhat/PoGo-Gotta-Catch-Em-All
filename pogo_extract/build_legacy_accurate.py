"""Accurate legacy/special-move detector.

Definition: a pokemon has a legacy/special move if it knows a move that is NOT
in its CURRENT (normal-catch) learnable movepool.

The pvpoke gamemaster lists fastMoves/chargedMoves as a SUPERSET that already
includes elite-TM and legacy moves. The current normal movepool is therefore:
    (fastMoves + chargedMoves) - eliteMoves - legacyMoves
A held move not in that set => legacy/special.

Mapping notes:
- DB move IDs are HoloPokemonMove enum ints. move1 is the fast slot, move2/move3
  are charged slots. move_id_to_name.json gives names; fast names carry a _FAST
  suffix and some carry a species suffix (WATER_GUN_FAST_BLASTOISE). pvpoke uses
  bare names for both slots, so we strip _FAST and known species suffixes.
- pvpoke keys movepools per form (speciesId). The DB form enum does not map 1:1
  to pvpoke speciesIds, and cross-form movepool differences in PoGO are almost
  entirely the signature/legacy charged moves we want to flag anyway. So the
  current movepool is aggregated across ALL pvpoke entries sharing the dex
  (the most permissive "normal" set), which is the conservative choice against
  the over-matching the old universal-list approach produced.
- Return (purified-normal) and Frustration (shadow) are never legacy.
"""
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "pokemon.db"
GM = ROOT / "pvpoke_gamemaster.json"
IDMAP = ROOT / "move_id_to_name.json"
OUT = ROOT / "legacy_accurate.json"

RETURN_ID = 323
FRUSTRATION_ID = 322
NEVER_LEGACY = {RETURN_ID, FRUSTRATION_ID}

# Species suffixes appended to a few move names in the enum that pvpoke drops.
_SPECIES_SUFFIXES = ("_BLASTOISE", "_HISUI", "_PURIFIED", "_SHADOW")


def normalize(name: str) -> str:
    """Turn a move name into a canonical bare form for comparison.

    Applied to both the DB enum names and pvpoke names so they meet in the
    middle. The DB stores Hidden Power as one generic move while pvpoke splits
    it into 16 typed variants (HIDDEN_POWER_BUG, ...); collapse all of them to
    HIDDEN_POWER so the generic held move matches the species' legal pool.
    """
    for sfx in _SPECIES_SUFFIXES:
        if name.endswith(sfx):
            name = name[: -len(sfx)]
    if name.endswith("_FAST"):
        name = name[: -len("_FAST")]
    if name.startswith("HIDDEN_POWER"):
        name = "HIDDEN_POWER"
    return name


def main() -> None:
    id_to_name = {int(k): v for k, v in json.loads(IDMAP.read_text()).items()}
    gm = json.loads(GM.read_text(encoding="utf-8"))

    # Per-dex aggregated NORMAL movepool (names, normalized) and the legacy/elite
    # set (for reporting which held move is the special one).
    normal_by_dex: dict[int, set[str]] = defaultdict(set)
    special_by_dex: dict[int, set[str]] = defaultdict(set)
    dex_seen: set[int] = set()
    for p in gm["pokemon"]:
        dex = p.get("dex")
        if dex is None:
            continue
        dex_seen.add(dex)
        fast = {normalize(m) for m in (p.get("fastMoves") or [])}
        charged = {normalize(m) for m in (p.get("chargedMoves") or [])}
        elite = {normalize(m) for m in (p.get("eliteMoves") or [])}
        legacy = {normalize(m) for m in (p.get("legacyMoves") or [])}
        full = fast | charged
        special = (elite | legacy) & full
        normal = full - special
        normal_by_dex[dex] |= normal
        special_by_dex[dex] |= special

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT uid_hex, pokemon_id, species_name, form, costume,
               move1, move2, move3, iv_total, iv_pct, cp,
               is_purified_flag, alignment, move2_is_purified_exclusive
        FROM pokemon WHERE in_bag = 1
        """
    ).fetchall()
    con.close()

    results = []
    skipped_no_dex = []  # dex absent from pvpoke (can't judge -> reported, not flagged)
    for r in rows:
        dex = r["pokemon_id"]
        if dex not in normal_by_dex:
            skipped_no_dex.append((r["uid_hex"], dex, r["species_name"]))
            continue
        normal = normal_by_dex[dex]
        held_ids = [r["move1"], r["move2"], r["move3"]]
        legacy_moves = []
        for mid in held_ids:
            if not mid or mid in NEVER_LEGACY:
                continue
            raw = id_to_name.get(mid)
            if raw is None:
                # Unknown enum id; treat as special (held but unmappable).
                legacy_moves.append(f"MOVE_{mid}")
                continue
            bare = normalize(raw)
            if bare not in normal:
                legacy_moves.append(bare)
        if legacy_moves:
            results.append(
                {
                    "uid_hex": r["uid_hex"],
                    "species_name": r["species_name"],
                    "legacy_moves": legacy_moves,
                    "iv_total": r["iv_total"],
                }
            )

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # ---- report ----
    by_species = defaultdict(int)
    for x in results:
        by_species[x["species_name"]] += 1
    top = sorted(by_species.items(), key=lambda kv: (-kv[1], kv[0]))[:20]

    print(f"wrote {OUT}")
    print(f"in_bag total          : {len(rows)}")
    print(f"legacy/special holders: {len(results)}")
    print(f"distinct species      : {len(by_species)}")
    print(f"dex not in pvpoke     : {len(skipped_no_dex)} (not flagged; listed below)")
    print()
    print("TOP 20 SPECIES BY HOLDER COUNT:")
    for name, c in top:
        print(f"  {c:5d}  {name}")
    if skipped_no_dex:
        uniq = sorted({(d, n) for _, d, n in skipped_no_dex})
        print()
        print("DEX MISSING FROM PVPOKE GAMEMASTER (could not evaluate):")
        for d, n in uniq[:40]:
            print(f"  dex={d}  {n}")


if __name__ == "__main__":
    main()
