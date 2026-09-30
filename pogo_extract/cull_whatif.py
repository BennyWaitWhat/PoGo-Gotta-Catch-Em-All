"""What-if explorer for cull_v9 rules. No DB writes; explore overrides.

Modes:
  --uid <hex>                  why was this pokemon kept/transferred?
  --rule-tweak NAME=VALUE      override a constant, diff vs current
  --species <name>             list all matching species with decision/reason
  --rule-disable <name>        drop a rule, diff vs current
  --form-protect <form>=topN   per-form bucket top-N override, diff vs current

Multiple flags can combine: tweaks/disables/form-protects all stack into one
re-run, then --uid or --species reports against THAT modified state.
"""
import argparse, sqlite3

import cull_v9
from cull_v9 import PROTECTION_RULES, build_ctx, PER_FORM_TOP2_PIDS

TWEAKABLE = {
    'SHINY_TOP_N', 'PRE_EVO_TOP_N', 'PRE_EVO_TOP2_N', 'FINAL_TOP_N',
    'PVP_RANK_KEEP',
}


def load_rows(conn, in_bag_only=True):
    c = conn.cursor()
    q = "SELECT * FROM pokemon" + (" WHERE in_bag=1" if in_bag_only else "")
    return [dict(r) for r in c.execute(q).fetchall()]


def load_gm():
    import json
    with open('pvpoke_gamemaster.json') as f:
        return json.load(f)


def build_ctx_with_form_protect(rows, gm, form_protect_topn):
    """build_ctx but with per-(form) top-N override for the species_form_bucket.

    form_protect_topn: dict[form_int] = top_n
    """
    if not form_protect_topn:
        return build_ctx(rows, gm)

    ctx = build_ctx(rows, gm)

    sf_buckets = {}
    for p in rows:
        if p['fresh_shiny'] or (p['fresh_costume'] or 0) != 0:
            continue
        sf_buckets.setdefault((p['pokemon_id'], p['form'] or 0), []).append(p)

    sf_reason = {}
    for (pid, form), lst in sf_buckets.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        if form in form_protect_topn:
            keep_n, label = form_protect_topn[form], 'form_override_top'
        elif pid in ctx['final_form_pids']:
            keep_n, label = cull_v9.FINAL_TOP_N, 'final_top'
        elif pid in PER_FORM_TOP2_PIDS:
            keep_n, label = cull_v9.PRE_EVO_TOP2_N, 'preevo2_top'
        else:
            keep_n, label = cull_v9.PRE_EVO_TOP_N, 'preevo_top'
        for i, p in enumerate(lst[:keep_n]):
            sf_reason[p['uid_hex']] = f'{label}{keep_n}_rank{i+1}'

    ctx['species_form_bucket_reason'] = sf_reason
    return ctx


def apply_tweaks(tweaks):
    """Mutate cull_v9 module-level constants. Returns dict of originals for restore."""
    originals = {}
    for k, v in tweaks.items():
        if k not in TWEAKABLE:
            raise SystemExit(f"unknown tweakable: {k} (allowed: {sorted(TWEAKABLE)})")
        if not hasattr(cull_v9, k):
            raise SystemExit(f"cull_v9 has no attribute {k}")
        originals[k] = getattr(cull_v9, k)
        setattr(cull_v9, k, int(v))
    return originals


def restore_tweaks(originals):
    for k, v in originals.items():
        setattr(cull_v9, k, v)


def filter_rules(disable_names):
    """Return PROTECTION_RULES with disabled rules removed (substring match on name)."""
    if not disable_names:
        return PROTECTION_RULES
    keep = []
    dropped = []
    for r in PROTECTION_RULES:
        if any(d.lower() in r.name.lower() for d in disable_names):
            dropped.append(r.name)
            continue
        keep.append(r)
    return keep, dropped


def run_cull(rows, ctx, rules):
    """Return uid_hex -> (decision, reason_str) using given rules + ctx."""
    out = {}
    for p in rows:
        reasons = []
        for r in rules:
            rs = r.reason_fn(p, ctx)
            if rs is not None:
                reasons.append(rs)
        if reasons:
            out[p['uid_hex']] = ('KEEP', ';'.join(reasons[:8]))
        else:
            out[p['uid_hex']] = ('TRANSFER', 'no_keep_rule')
    return out


def current_decisions(conn):
    """Read cull_decision_v9 for all in_bag pokemon."""
    out = {}
    for r in conn.execute(
        "SELECT uid_hex, cull_decision_v9, cull_reason_v9 FROM pokemon WHERE in_bag=1"
    ):
        out[r[0]] = (r[1] or 'TRANSFER', r[2] or '')
    return out


def diff_decisions(before, after):
    """Return (kept_now_xfer, xfer_now_kept) lists of uid_hex."""
    kept_to_xfer = []
    xfer_to_kept = []
    for uid in after:
        b = before.get(uid, ('TRANSFER', ''))[0]
        a = after[uid][0]
        if b == 'KEEP' and a == 'TRANSFER':
            kept_to_xfer.append(uid)
        elif b == 'TRANSFER' and a == 'KEEP':
            xfer_to_kept.append(uid)
    return kept_to_xfer, xfer_to_kept


def explain_uid(conn, rows, ctx, uid_hex, rules):
    """Print which rules fired and which didn't for this uid."""
    p = next((r for r in rows if r['uid_hex'] == uid_hex), None)
    if p is None:
        all_rows = load_rows(conn, in_bag_only=False)
        p = next((r for r in all_rows if r['uid_hex'] == uid_hex), None)
        if p is None:
            print(f"uid {uid_hex} not in pokemon table")
            return
        print(f"uid {uid_hex} is not in_bag (in_bag={p['in_bag']}) - simulating anyway")
        print()

    sp = p['species_name']
    form = p['form'] or 0
    print(f"=== {uid_hex}  {sp}  pid={p['pokemon_id']} form={form} ===")
    print(f"    iv_total={p['iv_total']} cp={p['cp']} level={p['level']}")
    print(f"    is_hundo={bool(p['is_hundo'])} is_zero={bool(p['is_zero'])} "
          f"shiny={bool(p['fresh_shiny'])} lucky={bool(p['is_lucky'])} "
          f"shadow/purified={p['fresh_alignment']} costume={p['fresh_costume']}")
    print(f"    gl_rank={p['gl_rank']} ul_rank={p['ul_rank']} ll_rank={p['ll_rank']}")
    print(f"    is_traded_v2={p['is_traded_flag_v2']} owner={p['original_owner_name']!r}")
    print(f"    user_tags={p['auth_tag_names']!r}")
    print()

    fired, missed = [], []
    for r in rules:
        try:
            rs = r.reason_fn(p, ctx)
        except Exception as e:
            rs = None
            missed.append((r.name, f'EXCEPTION: {e}'))
            continue
        if rs is not None:
            fired.append((r.name, rs))
        else:
            missed.append((r.name, '-'))

    print(f"Rules that FIRED ({len(fired)}):")
    for n, rs in fired:
        print(f"  + {n:30s} -> {rs}")
    if not fired:
        print("  (none) -> TRANSFER")
    print()
    print(f"Rules that did NOT apply ({len(missed)}):")
    for n, why in missed:
        print(f"  - {n:30s} {why}")
    print()
    if fired:
        truncated = ';'.join(rs for _, rs in fired[:8])
        print(f"Final decision: KEEP    reason: {truncated}")
    else:
        print("Final decision: TRANSFER  reason: no_keep_rule")


def show_species(rows, ctx, rules, species_query):
    """Print decision + reason for every pokemon matching species name."""
    q = species_query.lower()
    matches = [p for p in rows if q in (p['species_name'] or '').lower()]
    if not matches:
        print(f"no in_bag pokemon match species like {species_query!r}")
        return
    print(f"=== {len(matches)} in_bag pokemon matching {species_query!r} ===")
    keep_n = xfer_n = 0
    for p in sorted(matches, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0))):
        reasons = []
        for r in rules:
            rs = r.reason_fn(p, ctx)
            if rs is not None:
                reasons.append(rs)
        if reasons:
            keep_n += 1
            d, rs = 'KEEP', ';'.join(reasons[:8])
        else:
            xfer_n += 1
            d, rs = 'TRANSFER', 'no_keep_rule'
        form = p['form'] or 0
        iv = p['iv_total'] or 0
        cp = p['cp'] or 0
        print(f"  {p['uid_hex']}  form={form:>5}  IV={iv:>2} CP={cp:>5}  {d:<9} {rs}")
    print(f"\nTotal: KEEP={keep_n}  TRANSFER={xfer_n}")


def report_diff(before, after, label):
    kept_to_xfer, xfer_to_kept = diff_decisions(before, after)
    cur_keep = sum(1 for d, _ in before.values() if d == 'KEEP')
    cur_xfer = sum(1 for d, _ in before.values() if d == 'TRANSFER')
    new_keep = sum(1 for d, _ in after.values() if d == 'KEEP')
    new_xfer = sum(1 for d, _ in after.values() if d == 'TRANSFER')
    print(f"=== {label} ===")
    print(f"Current:    KEEP={cur_keep}  TRANSFER={cur_xfer}")
    print(f"With override: KEEP={new_keep}  TRANSFER={new_xfer}")
    print(f"Newly KEPT (was TRANSFER):    {len(xfer_to_kept)}")
    print(f"Newly TRANSFER (was KEEP):    {len(kept_to_xfer)}")
    return kept_to_xfer, xfer_to_kept


def show_diff_pokemon(rows, uids, label, after, limit=20):
    if not uids:
        return
    print(f"\n  {label} (first {min(limit, len(uids))} of {len(uids)}):")
    by_uid = {p['uid_hex']: p for p in rows}
    for uid in uids[:limit]:
        p = by_uid.get(uid)
        if p is None:
            print(f"    {uid}  (not in current rows)")
            continue
        sp = p['species_name']
        form = p['form'] or 0
        iv = p['iv_total'] or 0
        cp = p['cp'] or 0
        new_reason = after[uid][1]
        print(f"    {uid}  {sp:<22} form={form:>5} IV={iv:>2} CP={cp:>5}  {new_reason}")


def parse_kv(s):
    if '=' not in s:
        raise SystemExit(f"expected KEY=VALUE, got {s!r}")
    k, _, v = s.partition('=')
    return k.strip(), v.strip()


def parse_form_protect(s):
    """form=topN  e.g.  2344=top3  or  2344=3"""
    k, v = parse_kv(s)
    v = v.lower()
    if v.startswith('top'):
        v = v[3:]
    return int(k), int(v)


def main():
    ap = argparse.ArgumentParser(description='Cull v9 what-if explorer (no DB writes)')
    ap.add_argument('--uid', help='show why this pokemon was kept/transferred')
    ap.add_argument('--species', help='list all in_bag pokemon matching species name')
    ap.add_argument('--rule-tweak', action='append', default=[],
                    metavar='NAME=VALUE',
                    help=f'override a constant. Allowed: {sorted(TWEAKABLE)}')
    ap.add_argument('--rule-disable', action='append', default=[],
                    metavar='RULE',
                    help='drop any rule whose name contains this substring')
    ap.add_argument('--form-protect', action='append', default=[],
                    metavar='FORM=topN',
                    help='per-form bucket top-N override (e.g. 2344=top3)')
    ap.add_argument('--show-diff-limit', type=int, default=20,
                    help='max number of changed-decision pokemon to list (default 20)')
    args = ap.parse_args()

    tweaks = dict(parse_kv(s) for s in args.rule_tweak)
    form_protect = dict(parse_form_protect(s) for s in args.form_protect)
    disable_names = args.rule_disable

    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row

    before = current_decisions(conn)
    rows = load_rows(conn, in_bag_only=True)
    gm = load_gm()

    originals = apply_tweaks(tweaks) if tweaks else {}
    try:
        ctx = build_ctx_with_form_protect(rows, gm, form_protect)
        if disable_names:
            rules, dropped = filter_rules(disable_names)
            if not dropped:
                print(f"WARN: --rule-disable {disable_names} matched no rules")
            else:
                print(f"Disabled rules: {dropped}")
        else:
            rules = PROTECTION_RULES

        has_override = bool(tweaks or form_protect or disable_names)
        override_label_parts = []
        if tweaks:
            override_label_parts.append(', '.join(f'{k}={v}' for k, v in tweaks.items()))
        if disable_names:
            override_label_parts.append(f'disabled={disable_names}')
        if form_protect:
            override_label_parts.append(
                'form_protect=' + ','.join(f'{k}=top{v}' for k, v in form_protect.items())
            )
        override_label = '  '.join(override_label_parts) or 'no overrides'

        if has_override:
            after = run_cull(rows, ctx, rules)
            kept_to_xfer, xfer_to_kept = report_diff(before, after, override_label)
            show_diff_pokemon(rows, xfer_to_kept, 'Newly KEPT', after, args.show_diff_limit)
            show_diff_pokemon(rows, kept_to_xfer, 'Newly TRANSFER', after, args.show_diff_limit)
            print()

        if args.uid:
            print()
            explain_uid(conn, rows, ctx, args.uid, rules)

        if args.species:
            print()
            show_species(rows, ctx, rules, args.species)

        if not has_override and not args.uid and not args.species:
            ap.print_help()
    finally:
        if originals:
            restore_tweaks(originals)


if __name__ == '__main__':
    main()
