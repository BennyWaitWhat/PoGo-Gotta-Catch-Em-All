"""Apply the cull ruleset to pokemon.db and produce the cull plan.

Decision logic: a pokemon is KEPT if ANY of these rules say keep.
A pokemon is TRANSFERRED only if NO rule says keep.

Rules (all evaluated as union):
  R-untouchable: hundo / nundo / lucky / best-buddy / shadow / purified /
                 powered-up / traded / mega-evolved / costume-decoration /
                 postcard / location-bg / adventure-effects / deployed-in-gym /
                 legendary / mythical / ultra-beast / paradox /
                 adventure-effect-species / legacy-move /
                 size-XXS / size-XL-or-XXL /
                 has-known-tag (5 known from runtime memory dump)
  R-shiny:       within species, rank <= 10 by IV%
  R-shadow:      within species, rank <= 2 by IV% (subsumed by R-untouchable since
                 alignment != 0 already keeps all shadows)
  R-bucket:      within (species, form), rank <= 3 by IV%

Tags partial: only 5 bindings extracted from runtime so far; full extraction pending.
"""
import sqlite3, csv, json, os
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)

DB = 'pokemon.db'

# Known tag bindings from runtime memory dump (uid_to_tags.json)
TAGGED_UIDS = set()
TAG_BY_UID = {}  # uid_str -> tag_name
if os.path.exists('uid_to_tags.json'):
    try:
        d = json.load(open('uid_to_tags.json'))
        for uid_str, tags in d.items():
            TAGGED_UIDS.add(int(uid_str))
            TAG_BY_UID[int(uid_str)] = tags if isinstance(tags, list) else [tags]
    except Exception as e:
        print(f"warn: could not load uid_to_tags.json: {e}")
print(f"Loaded {len(TAGGED_UIDS)} known tag bindings from runtime")

def untouchable_reasons(p):
    """Return list of reasons this pokemon is untouchable. Empty list = not L1."""
    rs = []
    if p['is_hundo']:                            rs.append("hundo")
    if p['is_zero']:                             rs.append("nundo")
    if p['is_lucky']:                            rs.append("lucky")
    if p['is_best_buddy']:                       rs.append("best_buddy")
    if p['is_deployed']:                         rs.append("deployed_in_gym")
    if (p['alignment'] or 0) != 0:               rs.append(f"alignment_{p['alignment_name'] or p['alignment']}")
    if (p['is_powered_up'] or 0) == 1:           rs.append("powered_up")
    # Use v2 is_traded_flag if available, else fall back to derived is_traded
    if (p['is_traded_flag_v2'] or 0) == 1 or (p['is_traded'] or 0) == 1:
        rs.append("traded")
    if (p['is_mega_evolved'] or 0) == 1:         rs.append("mega_evolved")
    if (p['special_bg_id'] or 0) > 0:            rs.append("postcard_special_bg")
    if (p['location_bg_id'] or 0) > 0:           rs.append("location_bg")
    if (p['adventure_effects_left'] or 0) > 0:   rs.append("adventure_effects_left")
    if p['costume_decoration_id']:               rs.append(f"costume_dec_{p['costume_decoration_id']}")

    # Size flag: XXS (1) or XL/XXL (5) - PoGo's special-size markers
    sc = p['pokemon_size_category'] or 0
    if sc == 1:                                  rs.append("size_XXS")
    elif sc == 5:                                rs.append("size_XL_or_XXL")

    # Known runtime tag bindings (only 5 so far, full extraction pending)
    uid_signed = p['uid']
    if uid_signed in TAGGED_UIDS:
        for t in TAG_BY_UID.get(uid_signed, []):
            rs.append(f"tag_{t}")

    pid = p['pokemon_id']
    if pid in LEGENDARY_IDS:                     rs.append("legendary")
    if pid in MYTHICAL_IDS:                      rs.append("mythical")
    if pid in ULTRA_BEAST_IDS:                   rs.append("ultra_beast")
    if pid in PARADOX_IDS:                       rs.append("paradox")
    if pid in ADVENTURE_EFFECT_IDS:              rs.append("adventure_effect_species")
    if has_legacy_move(pid, [p['move1'], p['move2'], p['move3']]):
        rs.append("legacy_move")
    return rs

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Add columns if missing
    cols = {r[1] for r in c.execute("PRAGMA table_info(pokemon)").fetchall()}
    if 'cull_decision' not in cols:
        c.execute("ALTER TABLE pokemon ADD COLUMN cull_decision TEXT")
    if 'cull_reason' not in cols:
        c.execute("ALTER TABLE pokemon ADD COLUMN cull_reason TEXT")
    conn.commit()

    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon").fetchall()]
    print(f"Loaded {len(rows)} pokemon")

    # Map uid -> set of keep-reasons
    keep_reasons = {}  # uid_hex -> list of reason strings
    def add_reason(uid, reason):
        keep_reasons.setdefault(uid, []).append(reason)

    # Rule: untouchable
    for p in rows:
        for r in untouchable_reasons(p):
            add_reason(p['uid_hex'], r)

    # Rule: top 10 shinies per species (by IV%, ties broken by CP)
    by_species_shiny = {}
    for p in rows:
        if p['is_shiny']:
            by_species_shiny.setdefault(p['pokemon_id'], []).append(p)
    for pid, lst in by_species_shiny.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:10]):
            add_reason(p['uid_hex'], f"shiny_top10_rank{i+1}")

    # Rule: top 3 per (species, form) by IV%
    by_bucket = {}
    for p in rows:
        key = (p['pokemon_id'], p['form'] or 0)
        by_bucket.setdefault(key, []).append(p)
    for key, lst in by_bucket.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:3]):
            add_reason(p['uid_hex'], f"top3_form_rank{i+1}")

    # Rule: top 2 shadows per species. (Subsumed: alignment != 0 already in
    # untouchable. Redundant but explicit.)
    by_species_shadow = {}
    for p in rows:
        if (p['alignment'] or 0) == 1:  # SHADOW
            by_species_shadow.setdefault(p['pokemon_id'], []).append(p)
    for pid, lst in by_species_shadow.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:2]):
            add_reason(p['uid_hex'], f"shadow_top2_rank{i+1}")

    # Compose decisions
    keep_count = 0
    xfer_count = 0
    print("\nWriting decisions back to DB...")
    for p in rows:
        uid = p['uid_hex']
        reasons = keep_reasons.get(uid, [])
        if reasons:
            decision = "KEEP"
            reason_str = ";".join(reasons[:6])  # cap at 6 to keep cell short
            keep_count += 1
        else:
            decision = "TRANSFER"
            reason_str = "no_keep_rule_matched"
            xfer_count += 1
        c.execute("UPDATE pokemon SET cull_decision=?, cull_reason=? WHERE uid_hex=?",
                  (decision, reason_str, uid))
    conn.commit()

    print(f"\n=== FINAL ===")
    print(f"  Total: {len(rows)}")
    print(f"  KEEP:     {keep_count} ({keep_count/len(rows)*100:.1f}%)")
    print(f"  TRANSFER: {xfer_count} ({xfer_count/len(rows)*100:.1f}%)")

    print(f"\n=== Top species by transfer count ===")
    for row in c.execute("""SELECT species_name, COUNT(*) as n FROM pokemon
                            WHERE cull_decision='TRANSFER' GROUP BY species_name
                            ORDER BY n DESC LIMIT 25""").fetchall():
        print(f"  {row[0]:25s} {row[1]}")

    print(f"\n=== Top INDIVIDUAL keep reasons (across all keepers) ===")
    # break out the joined reason strings
    reason_counts = {}
    for r in c.execute("SELECT cull_reason FROM pokemon WHERE cull_decision='KEEP'").fetchall():
        for tok in r[0].split(";"):
            reason_counts[tok] = reason_counts.get(tok, 0) + 1
    for tok, n in sorted(reason_counts.items(), key=lambda x: -x[1])[:30]:
        print(f"  {n:5d}  {tok}")

    print("\nExporting cull_plan.csv...")
    with open('cull_plan.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['uid_hex','pokemon_id','species_name','form','cp',
                    'iv_pct','iv_total','iv_atk','iv_def','iv_sta',
                    'is_shiny','is_lucky','is_traded','alignment_name',
                    'level','nickname','cull_decision','cull_reason'])
        for r in c.execute("""SELECT uid_hex,pokemon_id,species_name,form,cp,
                                     iv_pct,iv_total,iv_atk,iv_def,iv_sta,
                                     is_shiny,is_lucky,is_traded,alignment_name,
                                     level,nickname,cull_decision,cull_reason
                              FROM pokemon
                              ORDER BY species_name, form, cull_decision, iv_pct DESC"""):
            w.writerow(r)
    print("  cull_plan.csv written")

    conn.close()

if __name__ == '__main__':
    main()
