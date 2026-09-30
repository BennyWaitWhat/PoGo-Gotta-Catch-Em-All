"""Build form_category.json and form_category.py from form_enum + pvpoke + DB.

Categories:
  default   - Species default form (XXXNormal or Unset)
  regional  - Alolan, Galarian, Hisuian, Paldean, Unovan variants
  event     - Costumes, seasonal/event variants, dated forms (Spring2020, Gofest, etc.)
  cosmetic  - Aesthetic-only forms with no stat/move impact (Unown letters, Vivillon patterns, Spinda, Pikachu Cap, etc.)
  mega      - Mega evolutions / Primal (NOT typically in form_enum - mega is tracked via current_temp_evolution)
  dynamax   - Dynamax forms
  gmax      - Gigantamax forms

In PoGo's form_enum, Mega/Dynamax/Gmax forms are not enumerated separately; they live in other
fields. Categories `mega`, `dynamax`, `gmax` will therefore be empty for form_enum entries
unless a future patch surfaces them by form_id.
"""

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent

REGIONAL_TOKENS = {"Alola", "Alolan", "Galarian", "Galar", "Hisuian", "Hisui", "Paldea", "Paldean", "Unova", "Unovan"}

GIGANTAMAX_TOKENS = {"Gigantamax", "Gmax"}
DYNAMAX_TOKENS = {"Dynamax", "Dmax"}
MEGA_TOKENS = {"Mega", "MegaX", "MegaY", "Primal"}

EVENT_TOKENS = {
    "Costume", "Holiday", "Halloween", "Christmas", "Easter", "Anniversary", "Anniv",
    "Gofest", "Gotour", "Wcs", "Diwali", "Wildarea",
    "Party", "Witch", "Adventure",
    "Visor", "Bb", "Fossil", "Cap", "Goggles", "Monocle", "Glasses",
    "Copy", "Pop", "Vs", "Tshirt",
    "Flying01", "Flying02", "Flying03", "Flying04",
    "Flying05", "Flying06", "Flying07", "Flying08",
    "Horizons",
    "Sscarf", "Mscarf", "Kurta", "Train", "Conductor",
    "Jeju", "Doctor", "Coin", "Swim", "Okinawa", "Kariyushi",
}

COSMETIC_FAMILY_TOKENS = {
    "Plant", "Sandy", "Trash",
    "Archipelago", "Continental", "Elegant", "Fancy", "Garden",
    "Plains", "Snow", "Icy", "Jungle", "Marine", "Meadow", "Modern",
    "Monsoon", "Ocean", "Pokeball", "Polar", "River", "Sandstorm",
    "Savanna", "Sun", "Tundra", "High",
    "Sea", "Female", "Male",
    "Red", "Blue", "Yellow", "Orange", "White", "Green", "Black",
    "Indigo", "Violet", "Teal", "Wellspring", "Hearthflame", "Cornerstone",
    "Curly", "Droopy", "Stretchy",
    "Striped", "Star", "Diamond", "Heart",
    "Debutante", "Matron", "Dandy", "LaReine", "Kabuki", "Pharaoh", "La", "Reine",
    "Phony", "Antique",
    "Single", "Rapid",
    "Baile", "Pompom", "Pau", "Sensu",
    "Natural",
    "Small", "Average", "Large", "Super",
    "Counterfeit", "Artisan", "Unremarkable", "Masterpiece",
    "Exclamation", "Point", "Question", "Mark",
    "Fall", "Winter", "Spring", "Summer", "Autumn",
}

FORM_DIFFERENT_TOKENS = {
    "Origin", "Altered", "Sky", "Land", "Therian", "Incarnate",
    "Attack", "Defense", "Speed",
    "Sunny", "Rainy", "Snowy", "Overcast",
    "Heat", "Wash", "Frost", "Fan", "Mow",
    "Aria", "Pirouette",
    "Ordinary", "Resolute",
    "Shock", "Burn", "Chill", "Douse",
    "Low", "Key", "Amped",
    "Confined", "Unbound",
    "Hero",
    "Midday", "Midnight", "Dusk", "Dawn",
    "Solo", "School",
    "Busted", "Disguised",
    "Mane", "Wings",
    "Ultra",
    "Combat", "Blaze", "Aqua",
    "Apex", "Ultimate",
    "Terastal", "Stellar",
    "Four", "Zero", "Two", "Ten", "Fifty",
    "Complete", "Percent",
    "Sword", "Shield", "Crowned",
    "Full", "Belly", "Hangry",
    "Standard", "Zen", "Rime", "Noice",
    "Strike", "Rider",
    "Stiara", "Mtiara",
    "Koko", "Lele", "Bulu", "Fini",
    "Original", "Color",
    "Eternamax",
    "Null",
}


def split_camel(s: str) -> list[str]:
    parts = re.findall(r"[A-Z][a-z]*\d*", s) or [s]
    return parts


def to_upper_snake(camel: str) -> str:
    """Convert CamelCase form name to PoGo-style UPPER_SNAKE."""
    parts = split_camel(camel)
    return "_".join(p.upper() for p in parts)


def classify_form(form_name: str, species_token: str) -> str:
    """Return one of: default, regional, event, cosmetic, mega, dynamax, gmax."""
    parts = split_camel(form_name)
    suffix = parts[1:] if len(parts) > 1 else []
    suffix_set = set(suffix)

    if len(parts) == 1 and re.search(r"\d+$", parts[0]):
        return "cosmetic"

    if not suffix or suffix == ["Normal"]:
        return "default"

    if suffix_set & GIGANTAMAX_TOKENS:
        return "gmax"
    if suffix_set & DYNAMAX_TOKENS:
        return "dynamax"
    if suffix_set & MEGA_TOKENS:
        return "mega"

    if suffix_set & REGIONAL_TOKENS:
        return "regional"

    has_year = any(re.search(r"\d{4}", p) for p in suffix)
    has_event_token = bool(suffix_set & EVENT_TOKENS)
    if has_year or has_event_token:
        return "event"

    if suffix_set & COSMETIC_FAMILY_TOKENS:
        return "cosmetic"
    if suffix_set & FORM_DIFFERENT_TOKENS:
        return "cosmetic"

    if len(suffix) == 1 and len(suffix[0]) <= 3 and suffix[0].isalpha():
        return "cosmetic"
    if len(suffix) == 1 and re.fullmatch(r"[A-Z]\d*", suffix[0]):
        return "cosmetic"

    return "cosmetic"


def load_inputs():
    with open(ROOT / "form_enum.json", "r", encoding="utf-8") as f:
        form_enum = json.load(f)
    with open(ROOT / "pvpoke_gamemaster.json", "r", encoding="utf-8") as f:
        gamemaster = json.load(f)
    return form_enum, gamemaster


def build_form_to_pid(form_enum: dict, gamemaster: dict) -> tuple[dict, list]:
    """Return (form_id -> (pid, species_name), list of all (pid, form, species) seen in DB).

    Strategy:
    1. Read DB for observed (pid, form) pairs. The MOST COMMON pid per form_id is the canonical
       owner; rare pairings are usually data noise but still need classification entries.
    2. For forms not in DB, parse the species token from CamelCase name and look up via pvpoke gamemaster.
    """
    form_to_pid: dict[int, tuple[int, str]] = {}
    db_pairs: list[tuple[int, int, str]] = []

    db_path = ROOT / "pokemon.db"
    if db_path.exists():
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute(
            "SELECT pokemon_id, form, species_name, COUNT(*) FROM pokemon "
            "WHERE form > 0 AND form < 100000 "
            "GROUP BY pokemon_id, form, species_name"
        )
        per_form: dict[int, list[tuple[int, str, int]]] = defaultdict(list)
        for pid, form, name, n in cur.fetchall():
            per_form[int(form)].append((int(pid), name, int(n)))
            db_pairs.append((int(pid), int(form), name))
        for form_id, candidates in per_form.items():
            candidates.sort(key=lambda x: -x[2])
            pid, name, _ = candidates[0]
            form_to_pid[form_id] = (pid, name)
        con.close()

    species_to_dex: dict[str, int] = {}
    for entry in gamemaster.get("pokemon", []):
        species_id = entry.get("speciesId", "")
        dex = entry.get("dex")
        base_name = species_id.split("_")[0]
        if base_name and dex and base_name not in species_to_dex:
            species_to_dex[base_name] = dex
        species_name_compact = (entry.get("speciesName") or "").split(" (")[0]
        flat = re.sub(r"[^A-Za-z0-9]", "", species_name_compact).lower()
        if flat and dex and flat not in species_to_dex:
            species_to_dex[flat] = dex

    for form_id_str, form_name in form_enum.items():
        fid = int(form_id_str)
        if fid in form_to_pid:
            continue
        parts = split_camel(form_name)
        if not parts:
            continue
        species_token = parts[0].lower()
        dex = species_to_dex.get(species_token)
        if dex is None:
            for L in range(min(3, len(parts)), 0, -1):
                joined = "".join(parts[:L]).lower()
                dex = species_to_dex.get(joined)
                if dex is not None:
                    break
        if dex is not None:
            form_to_pid[fid] = (dex, parts[0])

    return form_to_pid, db_pairs


FALLBACK_PID = {
    "Spinda": 327,
    "Slowpoke": 79,
    "Slowbro": 80,
}


def main():
    form_enum, gamemaster = load_inputs()
    form_to_pid, db_pairs = build_form_to_pid(form_enum, gamemaster)

    for form_id_str, form_name in form_enum.items():
        fid = int(form_id_str)
        if fid in form_to_pid or fid == 0:
            continue
        parts = split_camel(form_name)
        if not parts:
            continue
        first = re.sub(r"\d+$", "", parts[0])
        if first in FALLBACK_PID:
            form_to_pid[fid] = (FALLBACK_PID[first], first)

    out_json: dict[str, dict] = {}
    out_py: dict[tuple[int, int], str] = {}
    unknown_pid: list[tuple[int, str]] = []
    cat_counter: Counter = Counter()

    for form_id_str, form_name in form_enum.items():
        fid = int(form_id_str)
        if fid == 0:
            continue

        parts = split_camel(form_name)
        species_token = parts[0] if parts else form_name

        if fid not in form_to_pid:
            unknown_pid.append((fid, form_name))
            continue

        pid, species = form_to_pid[fid]
        category = classify_form(form_name, species_token)
        upper_form = to_upper_snake(form_name)

        key = f"{pid}_{fid}"
        out_json[key] = {
            "species": species,
            "form_name": upper_form,
            "category": category,
        }
        out_py[(pid, fid)] = category
        cat_counter[category] += 1

    for pid, form, sname in db_pairs:
        if form == 0:
            continue
        key = f"{pid}_{form}"
        if key in out_json:
            continue
        form_name = form_enum.get(str(form))
        if not form_name:
            continue
        parts = split_camel(form_name)
        species_token = parts[0] if parts else form_name
        category = classify_form(form_name, species_token)
        upper_form = to_upper_snake(form_name)
        out_json[key] = {
            "species": sname,
            "form_name": upper_form,
            "category": category,
        }
        out_py[(pid, form)] = category
        cat_counter[category] += 1

    with open(ROOT / "form_category.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2, ensure_ascii=False)

    py_lines = [
        '"""Auto-generated form classification. See build_form_category.py."""',
        "",
        "FORM_CATEGORY: dict[tuple[int, int], str] = {",
    ]
    for (pid, fid), cat in sorted(out_py.items()):
        py_lines.append(f"    ({pid}, {fid}): {cat!r},")
    py_lines.append("}")
    py_lines.append("")
    with open(ROOT / "form_category.py", "w", encoding="utf-8") as f:
        f.write("\n".join(py_lines))

    print(f"Wrote form_category.json with {len(out_json)} entries")
    print(f"Wrote form_category.py with {len(out_py)} entries")
    print()
    print("Category breakdown:")
    for cat in ("default", "regional", "event", "cosmetic", "mega", "dynamax", "gmax"):
        print(f"  {cat:10s}: {cat_counter.get(cat, 0)}")
    print()
    if unknown_pid:
        print(f"Forms without resolvable pokemon_id ({len(unknown_pid)}):")
        for fid, name in unknown_pid[:25]:
            print(f"  form_id={fid} name={name}")
        if len(unknown_pid) > 25:
            print(f"  ... and {len(unknown_pid) - 25} more")
    print()

    db_path = ROOT / "pokemon.db"
    if not db_path.exists():
        print("pokemon.db missing - skipping bag validation")
        return

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("SELECT DISTINCT pokemon_id, form, species_name FROM pokemon WHERE in_bag=1")
    in_bag_pairs = cur.fetchall()
    con.close()

    unclassified_in_bag = []
    classified_keys = set(out_json.keys())
    for pid, form, sname in in_bag_pairs:
        if form > 100000:
            continue
        if form == 0:
            continue
        key = f"{pid}_{form}"
        if key not in classified_keys:
            unclassified_in_bag.append((pid, form, sname))

    print(f"Bag-side validation:")
    print(f"  distinct (pid, form) in_bag with non-zero form: {sum(1 for r in in_bag_pairs if 0 < r[1] < 100000)}")
    print(f"  unclassified (pid, form) in bag: {len(unclassified_in_bag)}")
    for pid, form, sname in unclassified_in_bag[:40]:
        in_enum = str(form) in form_enum
        print(f"    pid={pid} form={form} ({sname})  in_enum={in_enum}  enum_name={form_enum.get(str(form), '???')}")


if __name__ == "__main__":
    main()
