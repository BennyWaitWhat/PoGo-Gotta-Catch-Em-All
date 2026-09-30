"""Verify computed PvP ranks against Pokemod's UI.

Reads the 20-pokemon verification sample from pokemon.db (gl_rank/ul_rank/ll_rank
columns are populated by compute_all_ranks.py) and prints a markdown table the
user can compare side-by-side with what Pokemod displays in-game.
"""
import sqlite3, os, sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pokemon.db")

UIDS = [
    "9035d0798fa45089",  # 1  Azumarill
    "57eaa94cc6ad0ebf",  # 2  Trevenant
    "3e05deedb7b251f7",  # 3  Annihilape (unique)
    "1539a9a4e410675f",  # 4  Dudunsparce
    "5e4c01ac294b1f5b",  # 5  Blastoise (mega)
    "7990551e11a90751",  # 6  Garchomp (mega)
    "30eb52e8318c19ed",  # 7  Entei
    "88777a0981d251d4",  # 8  Zacian
    "fb6831096285e720",  # 9  Mewtwo (purified, mega)
    "e7d232edac415bf9",  # 10 Typhlosion shadow
    "60f702931882e75a",  # 11 Ninetales-Alolan purified
    "502c3884f3fe57ff",  # 12 Golem-Alolan
    "aad2a12c421efe9c",  # 13 Typhlosion-Hisuian
    "44abd7eeb43f54b0",  # 14 Sneasel-Hisuian
    "d793debf94c41451",  # 15 Slowbro-Galarian
    "efc4d75991bf3c9f",  # 16 Darmanitan-Galarian
    "f142ca2effaed3be",  # 17 Throh
    "6fa93f9533fa1a07",  # 18 Diancie (unique)
    "8b6251c2203efe42",  # 19 Heatran shadow
    "c69b5e1bd4f731a2",  # 20 Regigigas purified
]

REGIONAL = {
    52:'Alolan',54:'Alolan',56:'Alolan',58:'Alolan',60:'Alolan',62:'Alolan',64:'Alolan',
    66:'Alolan',68:'Alolan',70:'Alolan',72:'Alolan',74:'Alolan',76:'Alolan',78:'Alolan',
    80:'Alolan',46:'Alolan',48:'Alolan',50:'Alolan',
    2335:'Galarian',2582:'Galarian',2583:'Galarian',2336:'Galarian',2337:'Galarian',
    2338:'Galarian',2339:'Galarian',2341:'Galarian',2342:'Galarian',2345:'Galarian',
    946:'Galarian',948:'Galarian',2516:'Galarian',2507:'Galarian',2276:'Galarian',
    2793:'Hisuian',2795:'Hisuian',2786:'Hisuian',2792:'Hisuian',2728:'Hisuian',
    2735:'Hisuian',2108:'Hisuian',2111:'Hisuian',2789:'Hisuian',2794:'Hisuian',
    2812:'Hisuian',2815:'Hisuian',2785:'Hisuian',2788:'Hisuian',2790:'Hisuian',
}

def form_label(form):
    if not form: return "-"
    return f"{REGIONAL[form]} ({form})" if form in REGIONAL else str(form)

def fmt_rank(rank, pct, stage):
    if rank is None:
        return "n/a"
    pct_s = f"{pct:.2f}%" if pct is not None else "?"
    stage_s = f" ({stage})" if stage else ""
    return f"#{rank} {pct_s}{stage_s}"

def fmt_chain(chain_str):
    if not chain_str: return "-"
    parts = chain_str.split(';')
    if len(parts) == 1: return parts[0]
    return "<br>".join(parts)

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    placeholders = ",".join("?" * len(UIDS))
    rows = c.execute(f"""SELECT uid_hex, species_name, form, cp, level, iv_atk, iv_def, iv_sta,
        alignment_name,
        gl_rank, gl_pct, gl_stage, gl_chain_ranks,
        ul_rank, ul_pct, ul_stage, ul_chain_ranks,
        ll_rank, ll_pct, ll_stage, ll_chain_ranks
        FROM pokemon WHERE uid_hex IN ({placeholders})""", UIDS).fetchall()

    by_uid = {r['uid_hex']: r for r in rows}
    missing = [u for u in UIDS if u not in by_uid]
    if missing:
        print(f"# WARNING: Missing UIDs in DB: {missing}", file=sys.stderr)

    print("# PvP Rank Verification - Computed Ranks")
    print()
    print("Compare against Pokemod's display for each pokemon.")
    print()
    print("| # | UID | Species | Form | IVs | CP | Lv | Align | GL rank | UL rank | LL rank | GL chain | UL chain | LL chain |")
    print("|---|-----|---------|------|-----|----|----|-------|---------|---------|---------|----------|----------|----------|")
    for i, uid in enumerate(UIDS, 1):
        r = by_uid.get(uid)
        if not r:
            print(f"| {i} | `{uid}` | MISSING | - | - | - | - | - | - | - | - | - | - | - |")
            continue
        ivs = f"{r['iv_atk']}/{r['iv_def']}/{r['iv_sta']}"
        align = r['alignment_name'] or '?'
        print(f"| {i} | `{uid}` | {r['species_name']} | {form_label(r['form'])} | "
              f"{ivs} | {r['cp']} | {r['level']} | {align} | "
              f"{fmt_rank(r['gl_rank'], r['gl_pct'], r['gl_stage'])} | "
              f"{fmt_rank(r['ul_rank'], r['ul_pct'], r['ul_stage'])} | "
              f"{fmt_rank(r['ll_rank'], r['ll_pct'], r['ll_stage'])} | "
              f"{fmt_chain(r['gl_chain_ranks'])} | "
              f"{fmt_chain(r['ul_chain_ranks'])} | "
              f"{fmt_chain(r['ll_chain_ranks'])} |")

    print()
    print("**Notes:**")
    print("- `GL/UL/LL rank` is the BEST rank across all evolution stages (lower is better).")
    print("- `Stage` shown in parentheses is the PvPoke speciesId of the form ranked.")
    print("- `chain` columns show per-stage rank for transparency: each entry is `species_id:rank(pct%)`.")
    print("- `n/a` means the species isn't in the PvPoke gamemaster (mythicals like Diancie may show this for some leagues).")
    print()
    print("**To add a comparison column,** copy this table into a doc and add a `Pokemod GL` / `Pokemod UL` / `Pokemod LL` column.")

if __name__ == "__main__":
    main()
