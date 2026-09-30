"""Interpretation C (improvement-gated, minimize evolutions) -- READ-ONLY sandbox.

Replicates keep_policy.py rule 1b's reach()/GENDER_TERMINALS/cf/_truly_plain/
form-collectible/build_evo_graph EXACTLY, then changes ONLY the plain-line promotion
logic to Interpretation C:

  * Keep top-1 by IV of each (pid, cf-form) STAGE as 'variant_floor' (stage-best).
  * The TERMINAL (final form) independently keeps its current top-3 by IV.
  * A pre-evo is tagged 'evolve' ONLY IF evolving it would STRICTLY improve the
    final form's top-3: its IV > the final form's current 3rd-best IV (culls another)
    OR the final form has < 3 specimens (fills an open cap slot). Promote the FEWEST
    pre-evos that still maxes the final caps (greedy, descending IV).
  * Hundo pre-evos are NEVER promoted (kept as stage).
  * Otherwise a pre-evo stays at its stage if it's a stage-best, else TRANSFER.

Does NOT modify keep_policy. Does NOT write tagsets/reasons/prune. Only reads + prints.
"""
import sqlite3, json, os, sys
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(ROOT, 'pokemon.db')
GM = os.path.join(ROOT, 'pvpoke_gamemaster.json')


# ---- replicated verbatim from keep_policy.build_evo_graph ----
def build_evo_graph(gm):
    by_sp = {p['speciesId']: p for p in gm['pokemon']}
    sp_to_dex = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
    dex_to_sp = {}
    for p in gm['pokemon']:
        sid, d = p['speciesId'], p.get('dex')
        if not d or any(x in sid for x in ('_shadow', '_mega', '_xl')):
            continue
        if d not in dex_to_sp or '_' not in sid:
            dex_to_sp[d] = sid

    def direct(sid):
        return ((by_sp.get(sid, {}).get('family', {})) or {}).get('evolutions', []) or []

    def terminals(sid, seen=None):
        if seen is None: seen = set()
        evos = direct(sid)
        if not evos:
            d = sp_to_dex.get(sid)
            return {d} if d else set()
        out = set()
        for e in evos:
            if e in seen: continue
            seen.add(e)
            out |= terminals(e, seen)
        return out

    is_pre, term = {}, {}
    for d, sid in dex_to_sp.items():
        is_pre[d] = bool(direct(sid))
        term[d] = terminals(sid)
    return is_pre, term


def topn(rows, n):
    return sorted(rows, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[:n]


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
    gm = json.load(open(GM, encoding='utf-8'))
    is_preevo, term_of = build_evo_graph(gm)

    plain = [r for r in rows if r['fresh_alignment'] != 1 and not r['fresh_shiny']]

    # ---- cf() replicated verbatim ----
    _basecnt = defaultdict(Counter)
    for r in rows:
        _f = r['form'] or 0
        _reg = (r['form_region'] or '').strip().lower()
        if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null'):
            _basecnt[r['pokemon_id']][_f] += 1
    base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}
    def cf(r):
        _f = r['form'] or 0
        return base_form.get(r['pokemon_id'], _f) if _f == 0 else _f

    # ---- GENDER_TERMINALS / reach() / _can_evo / _truly_plain replicated verbatim ----
    GENDER_TERMINALS = {
        415: {1: set(), 2: {416}},
        757: {1: set(), 2: {758}},
        361: {1: {362}, 2: {478, 362}},
        281: {1: {475, 282}, 2: {282}},
        280: {1: {475, 282}, 2: {282}},
        412: {1: {414}, 2: {413}},
    }
    def reach(r):
        gt = GENDER_TERMINALS.get(r['pokemon_id'])
        if gt is not None:
            return gt.get(r['gender'], set())
        return term_of.get(r['pokemon_id'], set()) if is_preevo.get(r['pokemon_id']) else set()
    def _can_evo(r):
        return bool(reach(r))
    def _truly_plain(r):
        return (not (r['fresh_costume'] or 0) and not (r['special_bg_id'] or 0)
                and not (r['natural_art_background'] or 0)
                and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
                and not (r['fresh_bread_mode'] or 0))

    # ---- form-collectible detection replicated verbatim ----
    _formreg = defaultdict(lambda: defaultdict(set))
    for r in plain:
        if _truly_plain(r):
            _formreg[r['pokemon_id']][r['form_region'] or 'kantonian'].add(cf(r))
    FORM_COLLECTIBLE = {pid for pid, regs in _formreg.items() if any(len(f) > 1 for f in regs.values())}
    def _poolable(r):
        return (r['pokemon_id'] not in FORM_COLLECTIBLE
                and not any(t in FORM_COLLECTIBLE for t in reach(r)))

    LINE_CAP = 3

    # =====================================================================
    # INTERPRETATION C  (changed logic; everything above is 1b verbatim)
    # =====================================================================
    keep = defaultdict(set)
    def mark(uid, why): keep[uid].add(why)

    # Build line pools exactly as 1b: key = (terminal-pid, region) for poolable lines;
    # form-collectibles handled per (pid, cf) with their own top-3.
    line_pool = defaultdict(list)
    fc_pool = defaultdict(list)
    truly_plain_rows = [r for r in plain if _truly_plain(r)]
    for r in truly_plain_rows:
        if _poolable(r):
            region = r['form_region'] or 'kantonian'
            terms = reach(r)
            if terms:
                for t in terms:
                    line_pool[(t, region)].append(r)
            else:
                line_pool[(r['pokemon_id'], region)].append(r)
        else:
            fc_pool[(r['pokemon_id'], cf(r))].append(r)

    # Form-collectibles: unchanged from 1b -- each form keeps its own top-3.
    for lst in fc_pool.values():
        for r in topn(lst, LINE_CAP):
            mark(r['uid_hex'], 'variant_floor')

    # Per-line Interpretation-C promotion.
    for (_term, _region), lst in line_pool.items():
        # Dead-end own-pool (male Combee/Salandit etc. or a true terminal with no
        # pre-evos pooled here): 1b keeps cap=1 if the key pid is itself a pre-evo
        # (gender dead-end living specimen), else LINE_CAP. Replicate that and skip
        # promotion (nothing to evolve into within this pool).
        # Partition the pool into terminal-stage vs pre-evo specimens.
        term_rows = [r for r in lst if r['pokemon_id'] == _term and not _can_evo(r)]
        # NOTE: a specimen could equal _term yet still be evolvable in a branched/
        # multi-terminal family; the line cap pools by reachable terminal, so a row
        # is "terminal here" iff its own pid == this pool's terminal AND it cannot
        # evolve further. Everything else in lst is a pre-evo feeding this terminal.
        pre_rows = [r for r in lst if not (r['pokemon_id'] == _term and not _can_evo(r))]

        if is_preevo.get(_term):
            # The pool key is itself a pre-evo => gender dead-end "own line" (male
            # Combee/Salandit): 1b keeps 1 living specimen, no evolve. Keep top-1.
            for r in topn(lst, 1):
                mark(r['uid_hex'], 'variant_floor')
            continue

        # (1) Terminal independently keeps its current top-3 by IV.
        term_keepers = topn(term_rows, LINE_CAP)
        term_keep_uids = {r['uid_hex'] for r in term_keepers}
        for r in term_keepers:
            mark(r['uid_hex'], 'variant_floor')

        # (2) Stage-best per (pid, cf-form) among pre-evos -> kept at stage by default.
        stage_groups = defaultdict(list)
        for r in pre_rows:
            stage_groups[(r['pokemon_id'], cf(r))].append(r)
        stage_best = {}            # (pid,cf) -> the top-1 row (stage keeper candidate)
        for key, grp in stage_groups.items():
            stage_best[key] = topn(grp, 1)[0]

        # (3) Improvement-gated promotion: simulate the terminal's TOP-3 keeper
        # slots and promote the FEWEST pre-evos (greedy, descending IV) that each
        # STRICTLY improve it. A promotion is admitted iff the terminal currently
        # holds < 3 specimens (fills an open cap slot) OR the candidate IV > the
        # terminal's current 3rd-best (weakest KEEPER) IV (culls that keeper).
        # The sim pool is CAPPED AT 3 -- already-transferred 4th/5th terminals are
        # not "culled" by a promotion, so they must not lower the bar. Hundo
        # pre-evos NEVER promoted. Candidates = ALL pre-evos (any stage), strongest
        # first; each admitted promotion enters the pool so the gate tightens and
        # only the fewest needed to MAX the 3 keeper slots are evolved.
        sim_pool = sorted((r['iv_total'] or 0) for r in term_rows)[-LINE_CAP:]  # top-3 keeper IVs, asc
        promoted_uids = set()
        cand = sorted(pre_rows, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))
        for r in cand:
            if (r['iv_total'] or 0) == 45:           # hundo pre-evo: never promote
                continue
            iv = r['iv_total'] or 0
            if len(sim_pool) < LINE_CAP:             # open slot -> fills cap
                sim_pool.append(iv); sim_pool.sort()
                promoted_uids.add(r['uid_hex'])
            elif iv > sim_pool[0]:                   # strictly beats weakest keeper -> culls
                sim_pool[0] = iv; sim_pool.sort()
                promoted_uids.add(r['uid_hex'])
            # else: cannot improve the terminal top-3 -> not promoted.

        for r in pre_rows:
            if r['uid_hex'] in promoted_uids:
                mark(r['uid_hex'], 'evolve')
            elif stage_best.get((r['pokemon_id'], cf(r))) is r:
                mark(r['uid_hex'], 'variant_floor')   # stage-best stays at its stage
            # else: a non-stage-best, non-promoted pre-evo -> TRANSFER (no mark)

    # ---- report ----
    plain_uids = {r['uid_hex'] for r in truly_plain_rows}
    # also include fc_pool rows that were marked (they're truly_plain too, already in plain_uids)
    by_uid = {r['uid_hex']: r for r in rows}

    keep_reason = {}
    for u, rs in keep.items():
        keep_reason[u] = 'evolve' if 'evolve' in rs else 'variant_floor'

    # totals across the PLAIN line/fc universe (the only thing this rule governs)
    n_keep = sum(1 for u in plain_uids if keep_reason.get(u) == 'variant_floor')
    n_evo = sum(1 for u in plain_uids if keep_reason.get(u) == 'evolve')
    n_xfer = sum(1 for u in plain_uids if u not in keep_reason)

    def line_label(r):
        e = 'EVOLVE' if keep_reason.get(r['uid_hex']) == 'evolve' else (
            'KEEP' if r['uid_hex'] in keep_reason else 'TRANSFER')
        return f"{r['species_name']} iv={r['iv_total']} stage(pid={r['pokemon_id']},form={cf(r)},g={r['gender']}) -> {e}"

    def dump(title, pids):
        print(f"\n=== {title} ===")
        sel = [r for r in truly_plain_rows if r['pokemon_id'] in pids]
        sel.sort(key=lambda r: (r['pokemon_id'], -(r['iv_total'] or 0)))
        for r in sel:
            print("  " + line_label(r))
        if not sel:
            print("  (none in bag)")

    print(f"INTERP C totals over PLAIN universe ({len(plain_uids)} truly-plain in_bag):")
    print(f"  KEEP(variant_floor)={n_keep}  EVOLVE={n_evo}  TRANSFER={n_xfer}")

    dump("Bulbasaur line (1,2,3)", {1, 2, 3})
    dump("Combee line (415->416)", {415, 416})
    dump("Dratini line (147,148,149)", {147, 148, 149})
    dump("Eevee line (133 + eeveelutions)", {133, 134, 135, 136, 196, 197, 470, 471, 700})

    # machine-readable summary line for the orchestrator
    print("\nJSON_SUMMARY " + json.dumps({
        "plain_total": len(plain_uids),
        "keep": n_keep, "evolve": n_evo, "transfer": n_xfer,
    }))


if __name__ == '__main__':
    main()
