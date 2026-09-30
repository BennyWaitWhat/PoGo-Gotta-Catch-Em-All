"""
query.py -- Fast instant-answer CLI over pre-computed deep_profiles.json.

Usage:
    python -m system.scripts.query <subcommand> [args]
    python system/scripts/query.py <subcommand> [args]

Subcommands:
    stats               Collection-wide counts (flags, opps, pvp-viable, fodder)
    mon <name|uid>      Full dossier for matching specimens
    best gl|ul          Top meta-viable specimens by pvp.rank
    powerup [gl|ul|ml]  Specimens with a power-up opportunity, sorted by value
    evolve              Evolve-to-meta gems (pvp.evolve_to set), by rank
    lucky               Lucky-trade candidates (legendary/mythical non-lucky)
    purify              Purify-option shadows, best IV first
    fodder              Safe-to-transfer dupes, grouped by species
    flag <FLAG>         All specimens with a given flag
    tag <name>          Specimens carrying a tag
    need-moves [gl|ul]  PVP specimens needing moves, split normal-TM vs ELITE-TM
    max [dyn|gmax]      Dynamax/GMax roster with extracted Max-move levels
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent          # pogo_extract/
_PROFILES = _ROOT / "system" / "analysis" / "deep_profiles.json"

# ---------------------------------------------------------------------------
# Load once
# ---------------------------------------------------------------------------
def _load():
    with open(_PROFILES, "r", encoding="utf-8") as f:
        return json.load(f)

_DATA = None

def data():
    global _DATA
    if _DATA is None:
        _DATA = _load()
    return _DATA

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
MAX_ROWS = 60  # cap long tables

def _trunc(rows, label="specimens"):
    if len(rows) <= MAX_ROWS:
        return rows
    extra = len(rows) - MAX_ROWS
    return rows[:MAX_ROWS] + [f"  ...and {extra} more {label}"]

def _s(val, default="-"):
    """Stringify a value, replacing None/empty with default."""
    if val is None:
        return default
    if isinstance(val, list):
        return ", ".join(str(v) for v in val) if val else default
    if isinstance(val, bool):
        return "Y" if val else "N"
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val)

def _label(p):
    """Short species label with form/align."""
    parts = [p["species"]]
    if p.get("form_name"):
        parts.append(f'({p["form_name"]})')
    if p.get("align") and p["align"] != "Normal":
        parts.append(f'[{p["align"]}]')
    return " ".join(parts)

def _row_fmt(widths, vals):
    """Left-align columns."""
    parts = []
    for w, v in zip(widths, vals):
        parts.append(str(v).ljust(w))
    return "  ".join(parts)

def _print_table(headers, rows, max_rows=MAX_ROWS):
    """Print a formatted table with auto-width columns."""
    if not rows:
        print("  (none)")
        return
    all_rows = [headers] + rows
    # compute widths from actual data (cap per column at 50)
    ncols = len(headers)
    widths = [0] * ncols
    for r in all_rows:
        if isinstance(r, str):
            continue  # overflow line
        for i, v in enumerate(r):
            widths[i] = min(50, max(widths[i], len(str(v))))
    # print header + separator
    print("  " + _row_fmt(widths, headers))
    print("  " + "  ".join("-" * w for w in widths))
    count = 0
    for r in rows:
        if isinstance(r, str):
            print(r)
            continue
        count += 1
        if count > max_rows:
            print(f"  ...and {len(rows) - max_rows} more")
            break
        print("  " + _row_fmt(widths, r))

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_stats(_args):
    """Collection-wide counts: per flag, per opp-type, pvp-viable, fodder."""
    profiles = data()
    total = len(profiles)

    # Flag counts
    flag_ctr = Counter()
    for p in profiles:
        for f in p.get("flags", []):
            flag_ctr[f] += 1

    # Opp-type counts (bucket by prefix before first space/paren)
    opp_ctr = Counter()
    for p in profiles:
        for o in p.get("opps", []):
            if o.startswith("power-up"):
                opp_ctr["power-up"] += 1
            elif o.startswith("evolve"):
                opp_ctr["evolve"] += 1
            elif o.startswith("purify"):
                opp_ctr["purify"] += 1
            elif o.startswith("lucky"):
                opp_ctr["lucky-trade"] += 1
            elif o.startswith("safe to transfer"):
                opp_ctr["safe-to-transfer"] += 1
            else:
                opp_ctr[o[:30]] += 1

    # PVP-viable / fodder
    pvp_any = sum(1 for p in profiles if p.get("pvp"))
    pvp_meta = sum(1 for p in profiles if p.get("pvp") and p["pvp"].get("meta"))
    pvp_gl = sum(1 for p in profiles if p.get("pvp") and p["pvp"].get("league") == "GL")
    pvp_ul = sum(1 for p in profiles if p.get("pvp") and p["pvp"].get("league") == "UL")
    fodder_n = sum(1 for p in profiles if p.get("fodder"))

    print(f"=== Collection Stats ({total} specimens) ===\n")

    print("Flags:")
    _print_table(
        ["Flag", "Count"],
        [[f, str(c)] for f, c in flag_ctr.most_common()],
        max_rows=40,
    )

    print("\nOpportunities:")
    _print_table(
        ["Type", "Count"],
        [[k, str(v)] for k, v in opp_ctr.most_common()],
    )

    print(f"\nPVP summary:")
    print(f"  PVP-viable total:  {pvp_any}")
    print(f"    Meta-viable:     {pvp_meta}")
    print(f"    GL picks:        {pvp_gl}")
    print(f"    UL picks:        {pvp_ul}")
    print(f"  Fodder (safe xfr): {fodder_n}")


def cmd_mon(args):
    """Full dossier for specimens matching species name or uid prefix."""
    query = args.query.lower()
    profiles = data()
    matches = [
        p for p in profiles
        if query in p["species"].lower()
        or p["uid"].lower().startswith(query)
        or (p.get("form_name") and query in p["form_name"].lower())
    ]
    if not matches:
        print(f"No specimens matching '{args.query}'")
        return

    print(f"=== {len(matches)} specimen(s) matching '{args.query}' ===\n")
    shown = 0
    for p in sorted(matches, key=lambda x: (-x.get("ivt", 0), -x.get("cp", 0))):
        shown += 1
        if shown > MAX_ROWS:
            print(f"  ...and {len(matches) - MAX_ROWS} more specimens")
            break
        pvp = p.get("pvp") or {}
        print(f"--- {_label(p)} ---")
        print(f"  UID:      {p['uid']}")
        print(f"  IV:       {p['iv']}  (total {p['ivt']})")
        print(f"  Level:    {_s(p['level'])}   CP: {p['cp']}")
        print(f"  Gender:   {p['gender']}   Shiny: {_s(p['shiny'])}  Lucky: {_s(p['lucky'])}")
        print(f"  Align:    {p['align']}")
        print(f"  Moves:    {_s(p.get('moves'))}")
        print(f"  GL rank:  {_s(p.get('gl_rank'))}   UL rank: {_s(p.get('ul_rank'))}")
        print(f"  Tags:     {_s(p.get('tags'))}")
        print(f"  Flags:    {_s(p.get('flags'))}")
        print(f"  Opps:     {_s(p.get('opps'))}")
        if pvp:
            print(f"  PVP:      {pvp.get('league')} rank {pvp.get('rank')} "
                  f"({pvp.get('species_id')}) meta={pvp.get('meta')}")
            if pvp.get("need_moves"):
                print(f"            need: {_s(pvp['need_moves'])}")
            if pvp.get("evolve_to"):
                print(f"            evolve_to: {pvp['evolve_to']}")
        print(f"  Fodder:   {_s(p.get('fodder'))}")
        print()


def cmd_best(args):
    """Top meta-viable specimens by pvp.rank."""
    league = args.league.upper()
    profiles = data()
    picks = [
        p for p in profiles
        if p.get("pvp")
        and p["pvp"].get("meta")
        and p["pvp"].get("league") == league
    ]
    picks.sort(key=lambda x: x["pvp"]["rank"])

    print(f"=== Best {league} Meta-Viable ({len(picks)}) ===\n")
    rows = []
    for p in picks:
        pv = p["pvp"]
        rows.append([
            str(pv["rank"]),
            _label(p),
            pv.get("species_id", "-"),
            p["iv"],
            _s(p["level"]),
            str(p["cp"]),
            _s(pv.get("need_moves")),
            _s(pv.get("evolve_to")),
        ])
    _print_table(
        ["Rank", "Specimen", "As", "IV", "Lv", "CP", "Need Moves", "Evolve To"],
        rows,
    )


def cmd_powerup(args):
    """Specimens with a power-up opp, sorted by value."""
    league_filter = args.league.upper() if args.league else None
    profiles = data()
    picks = []
    for p in profiles:
        for o in p.get("opps", []):
            if o.startswith("power-up"):
                # Filter by league if requested
                if league_filter:
                    pvp = p.get("pvp")
                    if league_filter == "ML":
                        # ML = hundos / high IV
                        if p.get("ivt", 0) < 43:
                            continue
                    elif pvp and pvp.get("league") != league_filter:
                        continue
                    elif not pvp and league_filter != "ML":
                        continue
                picks.append((p, o))
                break

    # Sort: rank-1 and hundos first, then by lowest level (most to gain)
    def _sort_key(item):
        p, _ = item
        pvp = p.get("pvp")
        rank = pvp["rank"] if pvp else 9999
        is_hundo = 0 if "HUNDO" in p.get("flags", []) else 1
        return (is_hundo, rank, p.get("level", 99))

    picks.sort(key=_sort_key)

    title = f"Power-Up Candidates"
    if league_filter:
        title += f" ({league_filter})"
    print(f"=== {title} ({len(picks)}) ===\n")

    rows = []
    for p, opp in picks:
        pvp = p.get("pvp") or {}
        # Extract cost from the opp string
        cost = opp.split("(", 1)[1].rstrip(")") if "(" in opp else "-"
        rows.append([
            _label(p),
            p["iv"],
            _s(p["level"]),
            str(p["cp"]),
            _s(pvp.get("rank")),
            _s(pvp.get("league")),
            cost,
        ])
    _print_table(
        ["Specimen", "IV", "Lv", "CP", "PVP Rank", "League", "Cost"],
        rows,
    )


def cmd_evolve(_args):
    """Evolve-to-meta gems (pvp.evolve_to set), by rank."""
    profiles = data()
    picks = [
        p for p in profiles
        if p.get("pvp") and p["pvp"].get("evolve_to")
    ]
    picks.sort(key=lambda x: (x["pvp"]["rank"], x["species"]))

    print(f"=== Evolve-to-Meta Gems ({len(picks)}) ===\n")
    rows = []
    for p in picks:
        pv = p["pvp"]
        rows.append([
            str(pv["rank"]),
            _label(p),
            pv["evolve_to"],
            pv["league"],
            p["iv"],
            _s(p["level"]),
            str(p["cp"]),
            "Y" if pv.get("meta") else "N",
            _s(pv.get("need_moves")),
        ])
    _print_table(
        ["Rank", "Specimen", "Evolve To", "Lg", "IV", "Lv", "CP", "Meta", "Need Moves"],
        rows,
    )


def cmd_lucky(_args):
    """Lucky-trade candidates: legendary/mythical that are not already lucky."""
    profiles = data()
    picks = []
    for p in profiles:
        flags = p.get("flags", [])
        if ("Legendary" in flags or "Mythical" in flags or "UltraBeast" in flags) and not p.get("lucky"):
            # Also check opps for lucky-trade mention
            picks.append(p)

    picks.sort(key=lambda x: (-x.get("cp", 0), x["species"]))

    print(f"=== Lucky-Trade Candidates ({len(picks)}) ===\n")
    rows = []
    for p in picks:
        flags_str = ", ".join(f for f in p.get("flags", [])
                              if f in ("Legendary", "Mythical", "UltraBeast",
                                       "HUNDO", "SHUNDO", "ShinyShadow"))
        rows.append([
            _label(p),
            p["iv"],
            str(p["cp"]),
            _s(p["level"]),
            "Y" if p.get("shiny") else "N",
            p["align"],
            flags_str or "-",
        ])
    _print_table(
        ["Specimen", "IV", "CP", "Lv", "Shiny", "Align", "Notable Flags"],
        rows,
    )


def cmd_purify(_args):
    """Purify-option shadows, sorted by best IV first."""
    profiles = data()
    picks = []
    for p in profiles:
        for o in p.get("opps", []):
            if o.startswith("purify"):
                picks.append(p)
                break

    picks.sort(key=lambda x: (-x.get("ivt", 0), -x.get("cp", 0)))

    print(f"=== Purify-Option Shadows ({len(picks)}) ===\n")
    rows = []
    for p in picks:
        rows.append([
            _label(p),
            p["iv"],
            str(p["ivt"]),
            _s(p["level"]),
            str(p["cp"]),
            "Y" if p.get("shiny") else "N",
            _s(p.get("gl_rank")),
            _s(p.get("ul_rank")),
        ])
    _print_table(
        ["Specimen", "IV", "IVT", "Lv", "CP", "Shiny", "GL Rank", "UL Rank"],
        rows,
    )


def cmd_fodder(_args):
    """Safe-to-transfer dupes, grouped by species with counts."""
    profiles = data()
    groups = defaultdict(list)
    for p in profiles:
        if p.get("fodder"):
            groups[p["species"]].append(p)

    # Sort species by count descending
    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    total = sum(len(v) for v in groups.values())

    print(f"=== Fodder / Safe-to-Transfer ({total} across {len(groups)} species) ===\n")
    rows = []
    for sp, plist in sorted_groups:
        cps = sorted([p["cp"] for p in plist])
        cp_range = f"{cps[0]}-{cps[-1]}" if len(cps) > 1 else str(cps[0])
        shiny_n = sum(1 for p in plist if p.get("shiny"))
        note = f"{shiny_n} shiny" if shiny_n else ""
        rows.append([sp, str(len(plist)), cp_range, note])

    _print_table(["Species", "Count", "CP Range", "Note"], rows, max_rows=80)


def cmd_flag(args):
    """All specimens with a given flag."""
    flag = args.flag
    profiles = data()
    picks = [p for p in profiles if flag in p.get("flags", [])]
    if not picks:
        # Try case-insensitive
        picks = [p for p in profiles
                 if any(flag.lower() == f.lower() for f in p.get("flags", []))]
    if not picks:
        all_flags = set()
        for p in profiles:
            all_flags.update(p.get("flags", []))
        print(f"No specimens with flag '{flag}'.")
        print(f"Available flags: {', '.join(sorted(all_flags))}")
        return

    picks.sort(key=lambda x: (-x.get("ivt", 0), -x.get("cp", 0)))

    print(f"=== Flag: {flag} ({len(picks)} specimens) ===\n")
    rows = []
    for p in picks:
        rows.append([
            _label(p),
            p["iv"],
            _s(p["level"]),
            str(p["cp"]),
            "Y" if p.get("shiny") else "N",
            "Y" if p.get("lucky") else "N",
            p["align"],
            p["uid"][:8],
        ])
    _print_table(
        ["Specimen", "IV", "Lv", "CP", "Shiny", "Lucky", "Align", "UID"],
        rows,
    )


def cmd_tag(args):
    """Specimens carrying a tag."""
    tag = args.name
    profiles = data()
    picks = [p for p in profiles if tag in p.get("tags", [])]
    if not picks:
        # Case-insensitive fallback
        picks = [p for p in profiles
                 if any(tag.lower() == t.lower() for t in p.get("tags", []))]
    if not picks:
        all_tags = set()
        for p in profiles:
            all_tags.update(p.get("tags", []))
        print(f"No specimens with tag '{tag}'.")
        print(f"Available tags: {', '.join(sorted(all_tags))}")
        return

    picks.sort(key=lambda x: (-x.get("cp", 0)))

    print(f"=== Tag: {tag} ({len(picks)} specimens) ===\n")
    rows = []
    for p in picks:
        rows.append([
            _label(p),
            p["iv"],
            _s(p["level"]),
            str(p["cp"]),
            "Y" if p.get("shiny") else "N",
            p["align"],
            _s(p.get("flags")),
            p["uid"][:8],
        ])
    _print_table(
        ["Specimen", "IV", "Lv", "CP", "Shiny", "Align", "Flags", "UID"],
        rows,
    )


def cmd_need_moves(args):
    """PVP specimens needing moves, split by normal-TM vs ELITE-TM."""
    league_filter = args.league.upper() if args.league else None
    profiles = data()

    normal_tm = []
    elite_tm = []
    for p in profiles:
        pvp = p.get("pvp")
        if not pvp or not pvp.get("need_moves"):
            continue
        if league_filter and pvp.get("league") != league_filter:
            continue
        for m in pvp["need_moves"]:
            move_name = m.split("[")[0]
            tm_type = "ELITE" if "ELITE" in m else "normal"
            entry = (p, pvp, move_name, tm_type)
            if tm_type == "ELITE":
                elite_tm.append(entry)
            else:
                normal_tm.append(entry)

    normal_tm.sort(key=lambda x: x[1]["rank"])
    elite_tm.sort(key=lambda x: x[1]["rank"])

    title = "Need Moves"
    if league_filter:
        title += f" ({league_filter})"

    print(f"=== {title} ===\n")

    print(f"-- Normal TM ({len(normal_tm)} moves needed) --")
    rows = []
    for p, pv, move, _ in normal_tm:
        rows.append([
            str(pv["rank"]),
            _label(p),
            pv.get("species_id", "-"),
            pv["league"],
            move,
            "Y" if pv.get("meta") else "N",
        ])
    _print_table(["Rank", "Specimen", "As", "Lg", "Move", "Meta"], rows)

    print(f"\n-- ELITE TM ({len(elite_tm)} moves needed) --")
    rows = []
    for p, pv, move, _ in elite_tm:
        rows.append([
            str(pv["rank"]),
            _label(p),
            pv.get("species_id", "-"),
            pv["league"],
            move,
            "Y" if pv.get("meta") else "N",
        ])
    _print_table(["Rank", "Specimen", "As", "Lg", "Move", "Meta"], rows)


def cmd_max(args):
    """Dynamax/Gigantamax roster with extracted Max-move levels (breadMoves_).

    Each Max move (Max Attack/Guard/Spirit etc.) levels 1->3; level 3 is the
    investment goal. Shows the highest move level per specimen so you can see
    which Max mons still need Max Particles.
    """
    profiles = data()
    want = args.kind.lower() if args.kind else None
    picks = []
    for p in profiles:
        fl = p.get("flags", [])
        is_gmax = "Gigantamax" in fl
        is_dyn = "Dynamax" in fl
        if not (is_gmax or is_dyn):
            continue
        if want == "gmax" and not is_gmax:
            continue
        if want == "dyn" and not is_dyn:
            continue
        picks.append((p, "GMAX" if is_gmax else "DYN"))

    # highest move level first (3 = maxed), then GMAX before DYN, then IV
    picks.sort(key=lambda x: (-(x[0].get("max_move_level") or 0),
                              x[1], -x[0].get("ivt", 0)))
    maxed = sum(1 for p, _ in picks if (p.get("max_move_level") or 0) >= 3)
    nolvl = sum(1 for p, _ in picks if not p.get("max_move_level"))
    title = "Max / Gigantamax roster"
    if want:
        title += f" ({want})"
    print(f"=== {title} ({len(picks)}; {maxed} at move-Lv3, "
          f"{nolvl} no level data) ===\n")
    rows = []
    for p, kind in picks:
        lvl = p.get("max_move_level")
        rows.append([
            _label(p),
            kind,
            f"L{lvl}" if lvl else "-",
            p["iv"],
            _s(p["level"]),
            str(p["cp"]),
            "Y" if p.get("shiny") else "N",
            _s(p.get("purpose")) if p.get("purpose") else "-",
            p["uid"][:8],
        ])
    _print_table(
        ["Specimen", "Mode", "MaxMove", "IV", "Lv", "CP", "Shiny", "Purpose", "UID"],
        rows, max_rows=120,
    )


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        prog="query",
        description="Fast instant-answer CLI over deep_profiles.json",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="Collection-wide counts")

    p_mon = sub.add_parser("mon", help="Full dossier for matching specimens")
    p_mon.add_argument("query", help="Species name or UID prefix")

    p_best = sub.add_parser("best", help="Top meta-viable specimens")
    p_best.add_argument("league", choices=["gl", "ul", "GL", "UL"],
                        help="GL or UL")

    p_pu = sub.add_parser("powerup", help="Power-up candidates")
    p_pu.add_argument("league", nargs="?", default=None,
                      choices=["gl", "ul", "ml", "GL", "UL", "ML"],
                      help="Filter by league (optional)")

    sub.add_parser("evolve", help="Evolve-to-meta gems")

    sub.add_parser("lucky", help="Lucky-trade candidates")

    sub.add_parser("purify", help="Purify-option shadows")

    sub.add_parser("fodder", help="Safe-to-transfer dupes by species")

    p_flag = sub.add_parser("flag", help="Specimens with a given flag")
    p_flag.add_argument("flag", help="Flag name (e.g. SHUNDO, OnlyOne)")

    p_tag = sub.add_parser("tag", help="Specimens carrying a tag")
    p_tag.add_argument("name", help="Tag name (e.g. Hundos, Reserve)")

    p_nm = sub.add_parser("need-moves", help="PVP specimens needing moves")
    p_nm.add_argument("league", nargs="?", default=None,
                      choices=["gl", "ul", "GL", "UL"],
                      help="Filter by league (optional)")

    p_max = sub.add_parser("max", help="Dynamax/GMax roster with Max-move levels")
    p_max.add_argument("kind", nargs="?", default=None,
                       choices=["dyn", "gmax", "DYN", "GMAX"],
                       help="Filter to dyn or gmax (optional)")

    args = parser.parse_args()

    dispatch = {
        "stats": cmd_stats,
        "mon": cmd_mon,
        "best": cmd_best,
        "powerup": cmd_powerup,
        "evolve": cmd_evolve,
        "lucky": cmd_lucky,
        "purify": cmd_purify,
        "fodder": cmd_fodder,
        "flag": cmd_flag,
        "tag": cmd_tag,
        "need-moves": cmd_need_moves,
        "max": cmd_max,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
