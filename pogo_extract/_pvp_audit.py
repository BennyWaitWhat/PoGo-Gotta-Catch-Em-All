"""PVP top-tier audit (GL/UL/LL).

Inputs: pokemon.db (only rows where in_bag=1).
Output: agent_outputs/pvp_audit.json
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).parent / "pokemon.db"
OUT = Path(__file__).parent / "agent_outputs" / "pvp_audit.json"

LEAGUES = ("gl", "ul", "ll")
LEAGUE_LABELS = {"gl": "Great League (1500 CP)", "ul": "Ultra League (2500 CP)", "ll": "Little League (500 CP)"}


def display_name(row):
    base = row["species_name"]
    stage = row[f"{row['_lead_league']}_stage"] if row.get("_lead_league") else None
    parts = [base]
    if stage and stage != base.lower():
        parts.append(f"-> {stage}")
    if row["form"] not in (0, 1):
        parts.append(f"form={row['form']}")
    if row["is_shiny"]:
        parts.append("shiny")
    return " ".join(parts)


def serialize_row(row, lead_league=None):
    r = dict(row)
    r["_lead_league"] = lead_league
    return {
        "uid_hex": r["uid_hex"],
        "species": r["species_name"],
        "form": r["form"],
        "gl_stage": r["gl_stage"],
        "ul_stage": r["ul_stage"],
        "ll_stage": r["ll_stage"],
        "level": r["level"],
        "cp": r["cp"],
        "iv_pct": round(r["iv_pct"], 1) if r["iv_pct"] is not None else None,
        "iv_atk": r["iv_atk"],
        "iv_def": r["iv_def"],
        "iv_sta": r["iv_sta"],
        "gl_rank": r["gl_rank"],
        "gl_pct": round(r["gl_pct"], 2) if r["gl_pct"] is not None else None,
        "ul_rank": r["ul_rank"],
        "ul_pct": round(r["ul_pct"], 2) if r["ul_pct"] is not None else None,
        "ll_rank": r["ll_rank"],
        "ll_pct": round(r["ll_pct"], 2) if r["ll_pct"] is not None else None,
        "gl_fits_at_current_level": r["gl_fits_at_current_level"],
        "ul_fits_at_current_level": r["ul_fits_at_current_level"],
        "is_powered_up": r["is_powered_up"],
        "is_shiny": bool(r["is_shiny"]),
        "is_lucky": bool(r["is_lucky"]),
        "is_best_buddy": bool(r["is_best_buddy"]),
        "name": display_name(r),
    }


def top_per_species(rows, league):
    """Group by gl_stage / ul_stage / ll_stage (the final-form key the ranker uses)."""
    stage_col = f"{league}_stage"
    rank_col = f"{league}_rank"
    by_stage = defaultdict(list)
    for r in rows:
        key = r[stage_col] or r["species_name"].lower()
        by_stage[key].append(serialize_row(r, lead_league=league))
    out = {}
    for stage, picks in by_stage.items():
        picks.sort(key=lambda x: (x[rank_col] if x[rank_col] is not None else 99999, -(x["iv_pct"] or 0)))
        out[stage] = picks
    return dict(sorted(out.items(), key=lambda kv: kv[1][0][rank_col]))


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    cur = con.execute(
        """
        SELECT *
        FROM pokemon
        WHERE in_bag = 1
          AND (gl_rank IS NOT NULL OR ul_rank IS NOT NULL OR ll_rank IS NOT NULL)
        """
    )
    all_rows = [dict(r) for r in cur.fetchall()]
    con.close()

    # Top picks per league: rank <= 5
    gl_rows = [r for r in all_rows if r["gl_rank"] is not None and r["gl_rank"] <= 5]
    ul_rows = [r for r in all_rows if r["ul_rank"] is not None and r["ul_rank"] <= 5]
    ll_rows = [r for r in all_rows if r["ll_rank"] is not None and r["ll_rank"] <= 5]

    gl_top = top_per_species(gl_rows, "gl")
    ul_top = top_per_species(ul_rows, "ul")
    ll_top = top_per_species(ll_rows, "ll")

    # Multi-tier all-stars: top 15 in 2+ leagues
    all_stars = []
    for r in all_rows:
        leagues_in = []
        if r["gl_rank"] is not None and r["gl_rank"] <= 15:
            leagues_in.append("GL")
        if r["ul_rank"] is not None and r["ul_rank"] <= 15:
            leagues_in.append("UL")
        if r["ll_rank"] is not None and r["ll_rank"] <= 15:
            leagues_in.append("LL")
        if len(leagues_in) >= 2:
            entry = serialize_row(r, lead_league="gl")
            entry["leagues_top15"] = leagues_in
            entry["best_rank"] = min(
                rk for rk in (r["gl_rank"], r["ul_rank"], r["ll_rank"]) if rk is not None
            )
            all_stars.append(entry)
    all_stars.sort(key=lambda x: (-len(x["leagues_top15"]), x["best_rank"]))

    # Power-up candidates: rank<=5 AND not powered up AND high IV
    # The strong signal is gl_fits_at_current_level=0 / ul_fits_at_current_level=0 which means
    # the mon is below the CP cap and powering up would help.
    power_up_candidates = []
    for r in all_rows:
        if r["is_powered_up"] == 1:
            continue
        signals = []
        if r["gl_rank"] is not None and r["gl_rank"] <= 5 and r["gl_fits_at_current_level"] == 0:
            signals.append({"league": "GL", "rank": r["gl_rank"], "pct": round(r["gl_pct"], 2)})
        if r["ul_rank"] is not None and r["ul_rank"] <= 5 and r["ul_fits_at_current_level"] == 0:
            signals.append({"league": "UL", "rank": r["ul_rank"], "pct": round(r["ul_pct"], 2)})
        # LL: cap is 500 CP, "fits" flag isn't stored; use level<=4 heuristic for room-to-grow
        if r["ll_rank"] is not None and r["ll_rank"] <= 5 and (r["level"] or 0) < 4:
            signals.append({"league": "LL", "rank": r["ll_rank"], "pct": round(r["ll_pct"], 2)})
        if not signals:
            continue
        entry = serialize_row(r, lead_league=signals[0]["league"].lower())
        entry["power_up_signals"] = signals
        power_up_candidates.append(entry)
    power_up_candidates.sort(
        key=lambda x: (-len(x["power_up_signals"]), min(s["rank"] for s in x["power_up_signals"]))
    )

    # Counts
    summary = {
        "total_in_bag_with_pvp": len(all_rows),
        "gl_top5_count": len(gl_rows),
        "ul_top5_count": len(ul_rows),
        "ll_top5_count": len(ll_rows),
        "gl_species_with_top5": len(gl_top),
        "ul_species_with_top5": len(ul_top),
        "ll_species_with_top5": len(ll_top),
        "multi_tier_all_stars": len(all_stars),
        "power_up_candidates": len(power_up_candidates),
    }

    payload = {
        "summary": summary,
        "league_labels": LEAGUE_LABELS,
        "gl_top5_by_species": gl_top,
        "ul_top5_by_species": ul_top,
        "ll_top5_by_species": ll_top,
        "multi_tier_all_stars": all_stars,
        "power_up_candidates": power_up_candidates,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {OUT}")
    print(json.dumps(summary, indent=2))

    # Print top power-up recommendations
    print("\n=== TOP POWER-UP RECOMMENDATIONS ===")
    for p in power_up_candidates[:25]:
        sigs = ", ".join(f"{s['league']}#{s['rank']}({s['pct']}%)" for s in p["power_up_signals"])
        print(f"  L{p['level']:5} {p['cp']:5}CP {p['iv_pct']:5}%  {p['name']:40} {sigs}")


if __name__ == "__main__":
    main()
