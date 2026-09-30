"""Strict re-verification of bucket_701_750 candidates.

Criterion:
- iv_total < 37
- bucket (pokemon_id, fresh_form, fresh_costume) size >= 4
- not the only-rank-1 representative

Outputs agent_outputs/bucket_701_750_strict.json
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "pokemon.db"
IN_PATH = ROOT / "agent_outputs" / "bucket_701_750.json"
OUT_PATH = ROOT / "agent_outputs" / "bucket_701_750_strict.json"

# Protections that match cull_v9 "never marked" rules (same as upstream methodology)
PROTECTED_SQL = """
  is_hundo=1 OR is_zero=1 OR alignment=2 OR is_purified_flag=1
  OR is_lucky=1 OR is_best_buddy=1 OR is_deployed=1
  OR (gl_final_rank IS NOT NULL AND gl_final_rank<=15)
  OR (ul_final_rank IS NOT NULL AND ul_final_rank<=15)
  OR (ll_rank IS NOT NULL AND ll_rank<=15)
  OR (auth_tag_names IS NOT NULL AND auth_tag_names!='' AND auth_tag_names!='[]')
  OR is_legendary=1 OR is_mythical=1
  OR fresh_costume!=0
  OR display_pokemon_badge!=0
  OR (bread_move_count IS NOT NULL AND bread_move_count>0)
  OR has_location_card=1 OR is_strong_pokemon=1 OR is_mega_evolved=1
  OR pokemon_id IN (778,242,664,924,744)
"""

# Form-character distinctions to flag (these are NOT culled lightly because
# they represent distinct character variants where 1-of-each is valuable):
ORICORIO_FORMS = {2678, 2679, 2680, 2681}  # baile, pom-pom, pa'u, sensu
PUMPKABOO_FORMS = {2641, 2642, 2643, 2644}  # small, average, large, super
GOURGEIST_FORMS = {2645, 2646, 2647, 2648}  # small, average, large, super
LYCANROC_FORMS = {2684, 2685, 2849}  # midday, midnight, dusk


def main():
    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    candidates = []
    for sb in data["sub_buckets"]:
        for c in sb.get("additional_candidates", []) or []:
            candidates.append(c)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    strict_kept = []  # candidates that PASS strict (still recommended for transfer)
    strict_rejected = []  # candidates filtered OUT by strict re-verification

    for cand in candidates:
        pid = cand["pokemon_id"]
        species = cand["species"]
        fresh_form = cand["fresh_form"]
        fresh_costume = cand["fresh_costume"]
        iv_total = cand["iv_total"]
        uid_hex = cand["uid_hex"]

        rec = dict(cand)  # start from candidate

        # ----- 1. iv_total < 37 -----
        passes_iv = iv_total < 37
        rec["strict_iv_check"] = passes_iv
        rec["strict_iv_threshold"] = 37

        # ----- 2. bucket (pid, fresh_form, fresh_costume) size >= 4 -----
        # bucket = pokemon in bag with same pid/fresh_form/fresh_costume
        cur.execute(
            """SELECT COUNT(*) AS c FROM pokemon
               WHERE in_bag=1 AND pokemon_id=? AND fresh_form=? AND fresh_costume=?""",
            (pid, fresh_form, fresh_costume),
        )
        bucket_size = cur.fetchone()["c"]
        rec["strict_bucket_size"] = bucket_size
        passes_size = bucket_size >= 4

        # ----- 3. Not the only-rank-1 representative -----
        # Get all members of the bucket with IV totals, sort by IV desc to compute rank.
        # The candidate fails this check if it would be the only top-tier (rank 1) in its bucket.
        cur.execute(
            f"""SELECT uid_hex, iv_total, iv_atk, iv_def, iv_sta, cp, is_shiny,
                       (CASE WHEN {PROTECTED_SQL} THEN 1 ELSE 0 END) AS protected
                FROM pokemon
                WHERE in_bag=1 AND pokemon_id=? AND fresh_form=? AND fresh_costume=?
                ORDER BY iv_total DESC, cp DESC, uid_hex""",
            (pid, fresh_form, fresh_costume),
        )
        rows = [dict(r) for r in cur.fetchall()]
        # Compute IV-based rank (1 = best). Ties broken by cp then uid_hex (deterministic).
        for i, r in enumerate(rows, start=1):
            r["iv_rank"] = i

        cand_row = next((r for r in rows if r["uid_hex"] == uid_hex), None)
        if cand_row is None:
            rec["strict_size_check"] = False
            rec["strict_rank_check"] = False
            rec["strict_pass"] = False
            rec["strict_reject_reasons"] = ["candidate UID not found in DB"]
            strict_rejected.append(rec)
            continue

        cand_rank = cand_row["iv_rank"]
        rec["strict_iv_rank"] = cand_rank
        rec["strict_size_check"] = passes_size

        # "Not the only-rank-1 representative":
        # Strictly, only-rank-1 means: the candidate IS rank 1 AND no other unprotected
        # pokemon in the bucket is also rank 1 (tie). Since we use deterministic ordering,
        # there is exactly one rank-1 row, so this collapses to: candidate is rank 1.
        # If the candidate is at rank 1, it IS the only representative and we should NOT cull it.
        is_only_rank_1 = (cand_rank == 1)
        passes_rank = not is_only_rank_1
        rec["strict_rank_check"] = passes_rank

        # ----- form-character flags -----
        form_flags = []
        if pid == 741 and fresh_form in ORICORIO_FORMS:
            form_flags.append(f"Oricorio form variant ({fresh_form})")
        if pid == 710 and fresh_form in PUMPKABOO_FORMS:
            form_flags.append(f"Pumpkaboo size variant ({fresh_form})")
        if pid == 711 and fresh_form in GOURGEIST_FORMS:
            form_flags.append(f"Gourgeist size variant ({fresh_form})")
        if pid == 745 and fresh_form in LYCANROC_FORMS:
            form_flags.append(f"Lycanroc form variant ({fresh_form})")
        rec["form_variant_flags"] = form_flags

        # ----- final pass/fail -----
        reject_reasons = []
        if not passes_iv:
            reject_reasons.append(
                f"iv_total {iv_total} >= 37 (does not meet < 37 threshold)"
            )
        if not passes_size:
            reject_reasons.append(
                f"bucket size {bucket_size} < 4 (needs >= 4 in-bag in same pid/fresh_form/fresh_costume)"
            )
        if not passes_rank:
            reject_reasons.append(
                "candidate is rank 1 (best IV) in its bucket - the only-rank-1 representative"
            )

        rec["strict_pass"] = (passes_iv and passes_size and passes_rank)
        rec["strict_reject_reasons"] = reject_reasons

        # surface the bucket itself for transparency on flagged variants
        if form_flags or not rec["strict_pass"]:
            rec["bucket_snapshot"] = [
                {
                    "uid_hex": r["uid_hex"],
                    "iv_total": r["iv_total"],
                    "iv_atk": r["iv_atk"],
                    "iv_def": r["iv_def"],
                    "iv_sta": r["iv_sta"],
                    "cp": r["cp"],
                    "is_shiny": bool(r["is_shiny"]),
                    "protected": bool(r["protected"]),
                    "iv_rank": r["iv_rank"],
                    "is_candidate": r["uid_hex"] == uid_hex,
                }
                for r in rows
            ]

        if rec["strict_pass"]:
            strict_kept.append(rec)
        else:
            strict_rejected.append(rec)

    # ---- Aggregate stats ----
    by_pid_kept = {}
    by_pid_rejected = {}
    for r in strict_kept:
        by_pid_kept[r["pokemon_id"]] = by_pid_kept.get(r["pokemon_id"], 0) + 1
    for r in strict_rejected:
        by_pid_rejected[r["pokemon_id"]] = by_pid_rejected.get(r["pokemon_id"], 0) + 1

    form_variants_in_rejected = [r for r in strict_rejected if r.get("form_variant_flags")]
    form_variants_in_kept = [r for r in strict_kept if r.get("form_variant_flags")]

    out = {
        "range": [701, 750],
        "source": str(IN_PATH.relative_to(ROOT)),
        "criterion": {
            "iv_total_max_exclusive": 37,
            "bucket_min_size": 4,
            "rule": "iv_total < 37 AND bucket(pid,fresh_form,fresh_costume) >= 4 AND NOT only-rank-1",
            "bucket_definition": "in_bag=1 AND same pokemon_id AND same fresh_form AND same fresh_costume",
            "rank_definition": "Ordered by iv_total DESC, cp DESC, uid_hex; only-rank-1 = candidate at position 1",
        },
        "summary": {
            "input_candidates": len(candidates),
            "passed_strict": len(strict_kept),
            "rejected_strict": len(strict_rejected),
            "rejected_by_iv": sum(1 for r in strict_rejected if not r["strict_iv_check"]),
            "rejected_by_size": sum(1 for r in strict_rejected if not r["strict_size_check"]),
            "rejected_by_rank": sum(1 for r in strict_rejected if not r["strict_rank_check"]),
            "form_variant_flags_in_kept": len(form_variants_in_kept),
            "form_variant_flags_in_rejected": len(form_variants_in_rejected),
            "kept_by_pid": dict(sorted(by_pid_kept.items())),
            "rejected_by_pid": dict(sorted(by_pid_rejected.items())),
        },
        "form_attention_notes": {
            "oricorio_forms_2678_2681": "Each fresh_form is a distinct character variant (Baile/Pom-Pom/Pa'u/Sensu).",
            "pumpkaboo_710_forms_2641_2644": "Size variants (small/avg/large/super) - 1-of-each preserved.",
            "gourgeist_711_forms_2645_2648": "Size variants (small/avg/large/super) - 1-of-each preserved.",
            "lycanroc_745_forms_2684_2685_2849": "Midday/Midnight/Dusk - distinct character forms.",
            "policy": "Strict rule already preserves rank-1 of each (pid,fresh_form,fresh_costume) bucket; form-character variants are inherently safe since fresh_form distinguishes them.",
        },
        "strict_kept": strict_kept,
        "strict_rejected": strict_rejected,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {OUT_PATH}")
    print(f"Input candidates: {len(candidates)}")
    print(f"Strict passed (still recommended transfer): {len(strict_kept)}")
    print(f"Strict rejected (now KEEP): {len(strict_rejected)}")
    print(f"  rejected by IV (>=37): {out['summary']['rejected_by_iv']}")
    print(f"  rejected by bucket size (<4): {out['summary']['rejected_by_size']}")
    print(f"  rejected by only-rank-1: {out['summary']['rejected_by_rank']}")
    print()
    print("Form-variant flagged candidates (kept):")
    for r in form_variants_in_kept:
        print(f"  {r['uid_hex']} pid={r['pokemon_id']} {r['species']} form={r['fresh_form']} iv={r['iv_total']} rank={r['strict_iv_rank']}/{r['strict_bucket_size']} - {r['form_variant_flags']}")
    print()
    print("Form-variant flagged candidates (rejected):")
    for r in form_variants_in_rejected:
        print(f"  {r['uid_hex']} pid={r['pokemon_id']} {r['species']} form={r['fresh_form']} iv={r['iv_total']} rank={r.get('strict_iv_rank','?')}/{r.get('strict_bucket_size','?')} - {r['strict_reject_reasons']}")


if __name__ == "__main__":
    main()
