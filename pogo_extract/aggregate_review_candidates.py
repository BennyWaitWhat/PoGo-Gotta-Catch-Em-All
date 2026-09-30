#!/usr/bin/env python3
"""
Aggregate additional_candidates across all agent_outputs/bucket_*.json files,
dedupe by uid_hex, and re-verify each against ALL protection rules in pokemon.db.
"""

import glob
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.join(ROOT, "agent_outputs")
DB_PATH = os.path.join(ROOT, "pokemon.db")
OUT_JSON = os.path.join(ROOT, "review_candidates_final.json")
OUT_MD = os.path.join(ROOT, "review_candidates_summary.md")

PROTECTED_PIDS = {778, 242, 664, 924, 744}
TAG_NAME_PASSTHROUGH = {None, "", "CLAUDE_TX", "Traded"}


def iter_sub_buckets(doc):
    sb = doc.get("sub_buckets")
    if isinstance(sb, dict):
        for k, v in sb.items():
            yield k, v
    elif isinstance(sb, list):
        for i, v in enumerate(sb):
            label = None
            if isinstance(v, dict):
                r = v.get("range")
                if isinstance(r, str):
                    label = r
                elif isinstance(r, list) and len(r) == 2:
                    label = f"{r[0]}-{r[1]}"
            yield label or f"idx{i}", v


def gather_candidates():
    files = sorted(glob.glob(os.path.join(AGENT_DIR, "bucket_*.json")))
    raw = []
    per_file_counts = []
    for fp in files:
        bname = os.path.basename(fp)
        with open(fp, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        file_count = 0
        for sb_label, sv in iter_sub_buckets(doc):
            if not isinstance(sv, dict):
                continue
            ac = sv.get("additional_candidates") or []
            for c in ac:
                if not isinstance(c, dict):
                    continue
                uid_hex = c.get("uid_hex")
                if not uid_hex:
                    continue
                raw.append({
                    "uid_hex": uid_hex.lower(),
                    "source_bucket": bname,
                    "sub_bucket": sb_label,
                    "candidate": c,
                })
                file_count += 1
        per_file_counts.append((bname, file_count))
    return raw, per_file_counts, len(files)


def dedupe(raw):
    seen = {}
    for entry in raw:
        uh = entry["uid_hex"]
        if uh not in seen:
            seen[uh] = entry
    return list(seen.values())


def parse_tag_names(raw_val):
    if raw_val is None:
        return []
    if isinstance(raw_val, list):
        items = raw_val
    else:
        s = str(raw_val).strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                items = json.loads(s)
            except Exception:
                items = [t.strip().strip("'\"") for t in s[1:-1].split(",") if t.strip()]
        else:
            items = [t.strip() for t in re.split(r"[,;|]", s) if t.strip()]
    return [str(t) for t in items if t is not None and str(t).strip() != ""]


def check_row(row):
    """Return list of violation reasons. Empty list = passes."""
    v = []
    if row["is_hundo"]:
        v.append("is_hundo")
    if row["is_zero"]:
        v.append("is_zero")
    if row["is_lucky"]:
        v.append("is_lucky")
    if row["is_best_buddy"]:
        v.append("is_best_buddy")
    if row["is_deployed"]:
        v.append("is_deployed")

    if row["fresh_alignment"] in (1, 2):
        v.append(f"fresh_alignment={row['fresh_alignment']}")
    if row["fresh_costume"] and row["fresh_costume"] != 0:
        v.append(f"fresh_costume={row['fresh_costume']}")
    if row["fresh_pokemon_badge"] and row["fresh_pokemon_badge"] != 0:
        v.append(f"fresh_pokemon_badge={row['fresh_pokemon_badge']}")
    if row["fresh_is_strong"] == 1:
        v.append("fresh_is_strong=1")
    if row["fresh_bread_mode"] and row["fresh_bread_mode"] != 0:
        v.append(f"fresh_bread_mode={row['fresh_bread_mode']}")

    if row["fresh_has_location_card"] == 1:
        v.append("fresh_has_location_card=1")
    if row["fresh_current_temp_evolution"] and row["fresh_current_temp_evolution"] != 0:
        v.append(f"fresh_current_temp_evolution={row['fresh_current_temp_evolution']}")
    if row["fresh_has_mega_level"] == 1:
        v.append("fresh_has_mega_level=1")

    if row["is_traded_flag_v2"] and row["is_traded_flag_v2"] != 0:
        v.append(f"is_traded_flag_v2={row['is_traded_flag_v2']}")

    tags = parse_tag_names(row["auth_tag_names"])
    bad_tags = [t for t in tags if t not in TAG_NAME_PASSTHROUGH]
    if bad_tags:
        v.append(f"auth_tag_names={bad_tags}")

    gl = row["gl_rank"]
    if gl is not None and gl <= 15:
        v.append(f"gl_rank={gl}")
    ul = row["ul_rank"]
    if ul is not None and ul <= 15:
        v.append(f"ul_rank={ul}")
    ll = row["ll_rank"]
    if ll is not None and ll <= 15:
        v.append(f"ll_rank={ll}")

    pid = row["pokemon_id"]
    if pid in PROTECTED_PIDS:
        v.append(f"protected_pid={pid}")
    if row["is_legendary"]:
        v.append("is_legendary")
    if row["is_mythical"]:
        v.append("is_mythical")

    return v


SELECT_COLS = [
    "uid_hex", "uid", "species_name", "pokemon_id", "form", "iv_total", "cp",
    "is_hundo", "is_zero", "is_lucky", "is_best_buddy", "is_deployed",
    "fresh_alignment", "fresh_costume", "fresh_pokemon_badge",
    "fresh_is_strong", "fresh_bread_mode",
    "fresh_has_location_card", "fresh_current_temp_evolution", "fresh_has_mega_level",
    "is_traded_flag_v2", "auth_tag_names",
    "gl_rank", "ul_rank", "ll_rank",
    "is_legendary", "is_mythical",
]


def load_rows(uid_hexes):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out = {}
    missing = []
    chunk = 500
    cols = ", ".join(SELECT_COLS)
    for i in range(0, len(uid_hexes), chunk):
        batch = uid_hexes[i:i + chunk]
        placeholders = ",".join("?" for _ in batch)
        cur.execute(
            f"SELECT {cols} FROM pokemon WHERE LOWER(uid_hex) IN ({placeholders})",
            batch,
        )
        for r in cur.fetchall():
            out[r["uid_hex"].lower()] = dict(r)
    for uh in uid_hexes:
        if uh.lower() not in out:
            missing.append(uh)
    con.close()
    return out, missing


def pick(cand, *keys):
    for k in keys:
        if k in cand and cand[k] not in (None, ""):
            return cand[k]
    return None


def main():
    raw, per_file_counts, n_files = gather_candidates()
    total_raw = len(raw)

    deduped = dedupe(raw)
    n_dedup = len(deduped)

    uid_list = [e["uid_hex"] for e in deduped]
    rows, missing = load_rows(uid_list)

    final = []
    dropped = []
    violation_counter = Counter()

    for entry in deduped:
        uh = entry["uid_hex"]
        cand = entry["candidate"]
        row = rows.get(uh.lower())
        if not row:
            dropped.append({
                "uid_hex": uh,
                "source_bucket": entry["source_bucket"],
                "sub_bucket": entry["sub_bucket"],
                "violations": ["not_in_pokemon_db"],
            })
            violation_counter["not_in_pokemon_db"] += 1
            continue

        violations = check_row(row)
        if violations:
            dropped.append({
                "uid_hex": uh,
                "source_bucket": entry["source_bucket"],
                "sub_bucket": entry["sub_bucket"],
                "species_name": row["species_name"],
                "pokemon_id": row["pokemon_id"],
                "violations": violations,
            })
            for vstr in violations:
                violation_counter[vstr.split("=")[0]] += 1
            continue

        reason = pick(cand, "reason", "rationale", "reason_candidate",
                      "reason_for_candidate", "reason_to_transfer",
                      "surplus_reason", "cull_reason_v9",
                      "cull_reason_v9_current", "current_cull_reason_v9",
                      "current_reason_v9", "cull_v9_reason")
        if reason is None:
            reason = ""

        final.append({
            "uid_hex": row["uid_hex"],
            "uid_int_signed": row["uid"],
            "species_name": row["species_name"],
            "pokemon_id": row["pokemon_id"],
            "form": row["form"],
            "iv_total": row["iv_total"],
            "cp": row["cp"],
            "reason": str(reason),
            "source_bucket": entry["source_bucket"],
            "sub_bucket": entry["sub_bucket"],
        })

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(final, fh, indent=2)

    by_bucket = defaultdict(list)
    for item in final:
        by_bucket[item["source_bucket"]].append(item)

    md_lines = []
    md_lines.append("# Review Candidates Summary")
    md_lines.append("")
    md_lines.append(f"- Agent files read: {n_files}")
    md_lines.append(f"- Total raw `additional_candidates`: {total_raw}")
    md_lines.append(f"- After dedupe (uid_hex): {n_dedup}")
    md_lines.append(f"- Final after re-verify: {len(final)}")
    md_lines.append(f"- Dropped (violations or missing): {len(dropped)}")
    md_lines.append("")
    md_lines.append("## Violations dropped (by rule)")
    md_lines.append("")
    if violation_counter:
        for rule, n in violation_counter.most_common():
            md_lines.append(f"- `{rule}`: {n}")
    else:
        md_lines.append("- (none)")
    md_lines.append("")
    md_lines.append("## Per-bucket breakdown")
    md_lines.append("")
    md_lines.append("| Bucket | Final candidates | Top reasons |")
    md_lines.append("|---|---|---|")
    for bname in sorted(by_bucket.keys()):
        items = by_bucket[bname]
        reasons = Counter()
        for it in items:
            r = it["reason"] or "(no reason)"
            key = r[:80]
            reasons[key] += 1
        top = "; ".join(f"{k} ({n})" for k, n in reasons.most_common(3))
        md_lines.append(f"| {bname} | {len(items)} | {top} |")

    md_lines.append("")
    md_lines.append("## Per-bucket raw vs final")
    md_lines.append("")
    md_lines.append("| Bucket | Raw candidates | Final after verify |")
    md_lines.append("|---|---|---|")
    raw_per_file = Counter(e["source_bucket"] for e in raw)
    for bname, raw_n in sorted(per_file_counts):
        md_lines.append(f"| {bname} | {raw_per_file.get(bname, 0)} | {len(by_bucket.get(bname, []))} |")

    md_lines.append("")
    md_lines.append("## Dropped sample (first 25)")
    md_lines.append("")
    for d in dropped[:25]:
        md_lines.append(f"- `{d['uid_hex']}` ({d.get('species_name','?')} #{d.get('pokemon_id','?')}) "
                        f"[{d['source_bucket']}]: {', '.join(d['violations'])}")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md_lines) + "\n")

    print("=" * 60)
    print(f"Agent files read:        {n_files}")
    print(f"Total raw candidates:    {total_raw}")
    print(f"Deduped (uid_hex):       {n_dedup}")
    print(f"Post-verify final:       {len(final)}")
    print(f"Violations dropped:      {len(dropped)}")
    print()
    print("Top violation rules:")
    for rule, n in violation_counter.most_common(15):
        print(f"  {rule}: {n}")
    print()
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
