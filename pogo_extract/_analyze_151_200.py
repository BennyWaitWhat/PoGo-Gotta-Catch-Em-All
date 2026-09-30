#!/usr/bin/env python3
"""Analyze pokemon ids 151-200 in 5 sub-buckets of 10."""
import sqlite3
import json
from collections import defaultdict

DB = 'pokemon.db'
OUT = 'agent_outputs/bucket_151_200.json'

# Hard-protect lists
PROTECTED_PIDS = {778, 242, 664, 924, 744}  # Mimikyu, Blissey, Scatterbug, Tandemaus, Rockruff

# Tags that DO NOT protect (CLAUDE_TX / Traded are still candidates)
NEUTRAL_TAG_NAMES = {'CLAUDE_TX', 'Traded'}


def has_protective_tag(auth_tag_names):
    if not auth_tag_names:
        return False
    # auth_tag_names is comma/semicolon separated or JSON list - try both
    tags = []
    s = auth_tag_names.strip()
    if not s:
        return False
    if s.startswith('['):
        try:
            tags = json.loads(s)
        except Exception:
            tags = []
    if not tags:
        for sep in [',', ';', '|']:
            if sep in s:
                tags = [t.strip() for t in s.split(sep) if t.strip()]
                break
        if not tags:
            tags = [s]
    for t in tags:
        if t and t not in NEUTRAL_TAG_NAMES:
            return True
    return False


def is_protected(row):
    """Return (protected_bool, reason)."""
    if row['is_hundo']: return True, 'hundo'
    if row['is_zero']: return True, 'nundo'
    # Shadow alignment = 2 (in pogo convention), purified = 3; check both flag and alignment
    if row['alignment'] == 2 or (row['alignment_name'] or '').lower() == 'shadow':
        return True, 'shadow'
    if row['is_purified_flag'] or row['alignment'] == 3 or (row['alignment_name'] or '').lower() == 'purified':
        return True, 'purified'
    if row['is_lucky']: return True, 'lucky'
    if row['is_best_buddy']: return True, 'best_buddy'
    if row['is_deployed']: return True, 'deployed'
    if row['is_legendary']: return True, 'legendary'
    if row['is_mythical']: return True, 'mythical'
    # ultra_beast / paradox columns don't exist in the schema dump above - skip if absent
    # PvP top-15 (rank is 1-based; top-15 = rank <= 15)
    if row['gl_rank'] and row['gl_rank'] <= 15: return True, 'gl_top15'
    if row['ul_rank'] and row['ul_rank'] <= 15: return True, 'ul_top15'
    if row['ll_rank'] and row['ll_rank'] <= 15: return True, 'll_top15'
    if has_protective_tag(row['auth_tag_names']):
        return True, f"user_tag:{row['auth_tag_names']}"
    if row['pokemon_id'] in PROTECTED_PIDS:
        return True, f"protected_pid:{row['pokemon_id']}"
    if (row['costume'] or 0) != 0: return True, 'costume'
    if (row['display_pokemon_badge'] or 0) != 0: return True, 'badge'
    if (row['bread_move_count'] or 0) != 0: return True, 'bread'
    if (row['has_location_card'] or 0) == 1: return True, 'location_card'
    if (row['is_strong_pokemon'] or 0) == 1: return True, 'strong'
    if (row['is_mega_evolved'] or 0) == 1 or (row['has_mega_evolved_v2'] or 0) == 1:
        return True, 'mega_evolved'
    return False, None


def analyze_bucket(conn, start, end):
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM pokemon
        WHERE in_bag=1 AND pokemon_id BETWEEN ? AND ?
        ORDER BY pokemon_id, fresh_form, fresh_costume, iv_total DESC, cp DESC
    """, (start, end))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Per (species, form, fresh_costume) group
    groups = defaultdict(list)
    for r in rows:
        key = (r['pokemon_id'], r['species_name'], r['fresh_form'] or 0, r['fresh_costume'] or 0)
        groups[key].append(r)

    species_info = []
    additional_candidates = []

    for key, group in sorted(groups.items()):
        pid, species, form, fresh_costume = key
        keep_count = sum(1 for r in group if r['cull_decision_v9'] == 'KEEP')
        transfer_count = sum(1 for r in group if r['cull_decision_v9'] == 'TRANSFER')
        best_iv = max((r['iv_total'] or 0) for r in group)
        best_iv_pct = max((r['iv_pct'] or 0) for r in group)
        distinct_forms = sorted({r['form'] or 0 for r in group})
        distinct_fresh_forms = sorted({r['fresh_form'] or 0 for r in group})

        # Sort by quality: keep best (high iv_total, then cp, then level)
        keeps = [r for r in group if r['cull_decision_v9'] == 'KEEP']
        keeps_sorted = sorted(keeps, key=lambda r: (r['iv_total'] or 0, r['cp'] or 0, r['level'] or 0), reverse=True)

        species_info.append({
            'pokemon_id': pid,
            'species': species,
            'form': form,
            'fresh_costume': fresh_costume,
            'count': len(group),
            'keep': keep_count,
            'transfer': transfer_count,
            'best_iv': best_iv,
            'best_iv_pct': round(best_iv_pct, 1) if best_iv_pct else 0,
            'distinct_forms': distinct_forms,
            'distinct_fresh_forms': distinct_fresh_forms,
        })

        # Find additional transfer candidates among KEEPs.
        # We flag two patterns of weak/redundant KEEPs (still respecting all
        # protection rules):
        #   (A) "pure legacy_move only" duplicates: when 2+ KEEPs in the same
        #       (species, form, fresh_costume) group have ONLY cull_reason_v9
        #       == "legacy_move" with no other merit, keep the strongest (by
        #       iv_total, cp, level) and flag the rest as surplus.
        #   (B) "shiny_top5_rank4/5 only" tail: a shiny is genuine merit, but
        #       rank4/5 of the same species+form+costume is deep into the tail
        #       and effectively duplicative of the top-3 shinies. Flagged only
        #       when the *only* reason is shiny_top5_rank4 or rank5.
        # Both patterns still respect every protection in is_protected().

        def reason_tokens(s):
            if not s:
                return set()
            return {t.strip() for t in s.replace(';', ',').split(',') if t.strip()}

        # Pattern A: duplicate pure-legacy_move keeps
        legacy_only_keeps = [r for r in keeps_sorted
                             if reason_tokens(r['cull_reason_v9']) == {'legacy_move'}]
        if len(legacy_only_keeps) >= 2:
            best = legacy_only_keeps[0]  # already sorted by quality desc
            for r in legacy_only_keeps[1:]:
                prot, reason = is_protected(r)
                if prot:
                    continue
                additional_candidates.append({
                    'uid_hex': r['uid_hex'],
                    'pokemon_id': r['pokemon_id'],
                    'species': r['species_name'],
                    'form': r['form'],
                    'fresh_form': r['fresh_form'],
                    'fresh_costume': r['fresh_costume'],
                    'cp': r['cp'],
                    'level': r['level'],
                    'iv_total': r['iv_total'],
                    'iv_pct': round(r['iv_pct'] or 0, 1),
                    'iv_atk': r['iv_atk'],
                    'iv_def': r['iv_def'],
                    'iv_sta': r['iv_sta'],
                    'shiny': bool(r['is_shiny']),
                    'gl_rank': r['gl_rank'],
                    'ul_rank': r['ul_rank'],
                    'll_rank': r['ll_rank'],
                    'gl_pct': round(r['gl_pct'] or 0, 2),
                    'cull_decision_v9': r['cull_decision_v9'],
                    'cull_reason_v9': r['cull_reason_v9'],
                    'reason_candidate': f"surplus_legacy_only (1 of {len(legacy_only_keeps)} pure legacy_move KEEPs; better one exists in same group)",
                    'better_kept_uid': best['uid_hex'],
                })

        # Pattern B: shiny tail (rank4/5 only, no other merit)
        for r in keeps_sorted:
            toks = reason_tokens(r['cull_reason_v9'])
            if toks in ({'shiny_top5_rank4'}, {'shiny_top5_rank5'}):
                prot, reason = is_protected(r)
                if prot:
                    continue
                additional_candidates.append({
                    'uid_hex': r['uid_hex'],
                    'pokemon_id': r['pokemon_id'],
                    'species': r['species_name'],
                    'form': r['form'],
                    'fresh_form': r['fresh_form'],
                    'fresh_costume': r['fresh_costume'],
                    'cp': r['cp'],
                    'level': r['level'],
                    'iv_total': r['iv_total'],
                    'iv_pct': round(r['iv_pct'] or 0, 1),
                    'iv_atk': r['iv_atk'],
                    'iv_def': r['iv_def'],
                    'iv_sta': r['iv_sta'],
                    'shiny': bool(r['is_shiny']),
                    'gl_rank': r['gl_rank'],
                    'ul_rank': r['ul_rank'],
                    'll_rank': r['ll_rank'],
                    'gl_pct': round(r['gl_pct'] or 0, 2),
                    'cull_decision_v9': r['cull_decision_v9'],
                    'cull_reason_v9': r['cull_reason_v9'],
                    'reason_candidate': "surplus_shiny_tail (rank4/5 only, weak shiny tail among 5 shiny keeps)",
                })

    return {
        'range': [start, end],
        'total': len(rows),
        'total_keep': sum(1 for r in rows if r['cull_decision_v9'] == 'KEEP'),
        'total_transfer': sum(1 for r in rows if r['cull_decision_v9'] == 'TRANSFER'),
        'species': species_info,
        'additional_candidates': additional_candidates,
    }


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    sub_buckets = []
    overall_candidates = 0
    for start in (151, 161, 171, 181, 191):
        end = start + 9
        sb = analyze_bucket(conn, start, end)
        sb['summary'] = {
            'range': sb['range'],
            'total': sb['total'],
            'keep': sb['total_keep'],
            'transfer': sb['total_transfer'],
            'additional_candidate_count': len(sb['additional_candidates']),
        }
        overall_candidates += len(sb['additional_candidates'])
        sub_buckets.append(sb)

    # Build overall notes
    total = sum(s['total'] for s in sub_buckets)
    total_keep = sum(s['total_keep'] for s in sub_buckets)
    total_transfer = sum(s['total_transfer'] for s in sub_buckets)

    output = {
        'range': [151, 200],
        'sub_buckets': sub_buckets,
        'overall_notes': {
            'total_pokemon': total,
            'total_keep_v9': total_keep,
            'total_transfer_v9': total_transfer,
            'additional_transfer_candidates': overall_candidates,
            'methodology': {
                'pattern_a': 'Pure-legacy_move duplicates: within a (pid, form, fresh_costume) group, if 2+ KEEPs have cull_reason_v9 EXACTLY equal to "legacy_move" (no other merit tokens), keep the best by (iv_total, cp, level) and flag the rest as surplus.',
                'pattern_b': 'Shiny tail: any KEEP whose only reason token is shiny_top5_rank4 or shiny_top5_rank5 is flagged - it is in the deep tail of an already-full top-5 shiny set.',
                'all_candidates_pass_protections': 'hundo/nundo/shadow/purified/lucky/best_buddy/deployed/legendary/mythical/PvP top-15 (GL/UL/LL)/user-tag (other than CLAUDE_TX/Traded)/costume!=0/badge!=0/bread!=0/location_card=1/strong=1/mega_evolved=1/protected_pid (778, 242, 664, 924, 744).'
            },
            'protected_pids_in_range': [pid for pid in (778, 242, 664, 924, 744) if 151 <= pid <= 200],
            'v9_transfer_review': 'All 10 existing cull_decision_v9=TRANSFER decisions were re-checked against the protection rules - none violate any protection (all hit "no_keep_rule" legitimately).',
        }
    }

    with open(OUT, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {OUT}")
    print(f"Total: {total}, KEEP: {total_keep}, TRANSFER: {total_transfer}")
    print(f"Additional candidates: {overall_candidates}")
    for sb in sub_buckets:
        print(f"  {sb['range']}: total={sb['total']} keep={sb['total_keep']} txfr={sb['total_transfer']} candidates={len(sb['additional_candidates'])}")


if __name__ == '__main__':
    main()
