"""Extract HoloPokemonMove integer -> name map from global-metadata.dat.

Niantic stores per-move template IDs as `Vnnnn_MOVE_<NAME>` strings in the
IL2CPP metadata, where nnnn is the move's enum value. Fast moves additionally
carry a `_FAST` suffix (e.g. 205 -> THUNDER_SHOCK_FAST) while the same base
name without suffix is the charged-move slot (1 -> THUNDER_SHOCK). The DB
stores fast IDs (move1) and charged IDs (move2/move3) in this same enum space.

Output: move_id_to_name.json  ({ "1": "THUNDER_SHOCK", "205": "THUNDER_SHOCK_FAST", ... })
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
META = ROOT / "global-metadata.dat"
OUT = ROOT / "move_id_to_name.json"


def main() -> None:
    data = META.read_bytes()
    toks = re.findall(rb"V(\d{4})_MOVE_([A-Z0-9_]+)", data)
    id_to_name: dict[int, str] = {}
    for num, name in toks:
        id_to_name.setdefault(int(num), name.decode("ascii"))

    OUT.write_text(
        json.dumps({str(k): id_to_name[k] for k in sorted(id_to_name)}, indent=2),
        encoding="utf-8",
    )
    fast = sum(1 for v in id_to_name.values() if v.endswith("_FAST"))
    print(f"wrote {OUT}")
    print(f"  entries={len(id_to_name)} range={min(id_to_name)}-{max(id_to_name)} fast={fast}")


if __name__ == "__main__":
    main()
