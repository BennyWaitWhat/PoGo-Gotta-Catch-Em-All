"""Adversarial independent verifier for server tag '1 GL Meta'.
Re-derives membership from the RULE using raw data, compares to DB membership
and the computed tagset file. Does NOT import build_tagsets logic.
"""
import sqlite3, json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, 'pokemon.db')
TAG = '1 GL Meta'
TOPN = 30
STRICT = 5
COMPUTED = os.path.join(ROOT, 'system', 'analysis', 'tagsets', '1_GL_Meta.txt')

# ---- 1. META universe = top-30 speciesId by score ----
gl = json.load(open(os.path.join(ROOT, '_gl1500.json'), encoding='utf-8'))
score = {e['speciesId']: (e.get('score') or 0) for e in gl}
# stable sort, score desc -> ties keep JSON order (matches generator)
ordered = sorted(score, key=lambda s: -score[s])
meta_std = set(ordered[:TOPN])
# boundary tie diagnostics
b_score = score[ordered[TOPN-1]]
tie_in = [s for s in ordered[:TOPN] if score[s] == b_score]
tie_out = [s for s in ordered[TOPN:] if score[s] == b_score]

# ---- raw rows ----
c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("""SELECT uid_hex, species_name, alignment_name, fresh_alignment,
    in_bag, gl_chain_ranks, auth_tag_names FROM pokemon WHERE in_bag=1""").fetchall()

def parse_chain(s):
    d = {}
    for part in (s or '').split(';'):
        if ':' in part:
            f, rk = part.rsplit(':', 1)
            rk = rk.split('(')[0].strip()
            try: d[f] = int(rk)
            except ValueError: pass
    return d

def derive(meta):
    """Return set of tagged uid_hex per rule for given meta universe.
    Also return per-species best (rank, uid) for audit."""
    cand = {}  # sid -> list of (rank, uid_hex, species_name, shadow)
    for r in rows:
        shadow = (r['fresh_alignment'] == 1)
        for form, rank in parse_chain(r['gl_chain_ranks']).items():
            sid = f'{form}_shadow' if shadow else form
            if sid in meta:
                cand.setdefault(sid, []).append((rank, r['uid_hex'], r['species_name'], shadow))
    tagged = {}  # uid -> list of (sid, rank) for which it is the strict winner
    best_per = {}
    for sid, lst in cand.items():
        lst.sort(key=lambda x: x[0])
        rank, uid, name, sh = lst[0]
        best_per[sid] = (rank, uid, name, sh)
        if rank <= STRICT:
            tagged.setdefault(uid, []).append((sid, rank))
    return set(tagged), tagged, best_per

rule_set, tag_detail, best_per = derive(meta_std)

# ---- 2. DB membership ----
db_rows = c.execute(
    "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND "
    "(';'||COALESCE(auth_tag_names,'')||';') LIKE '%;' || ? || ';%'", (TAG,)).fetchall()
db_set = {r[0] for r in db_rows}

# ---- computed file ----
comp_set = set()
if os.path.exists(COMPUTED):
    comp_set = {ln.strip() for ln in open(COMPUTED, encoding='utf-8') if ln.strip()}

# ---- alt cut: swap dondozo<->ninetales tie to test sensitivity ----
alt_set = None
if tie_in and tie_out:
    meta_alt = (meta_std - {tie_in[-1]}) | {tie_out[0]}
    alt_set, _, _ = derive(meta_alt)

# ---- report ----
out = {}
out['meta_universe'] = sorted(meta_std)
out['boundary_score'] = b_score
out['tie_in_top30'] = tie_in
out['tie_out_top30'] = tie_out
out['db_count'] = len(db_set)
out['rule_count'] = len(rule_set)
out['comp_count'] = len(comp_set)

fp = sorted(db_set - rule_set)  # tagged but fails rule
fn = sorted(rule_set - db_set)  # passes rule but not tagged
out['false_positives'] = fp
out['false_negatives'] = fn
out['db_vs_comp_only_in_db'] = sorted(db_set - comp_set)
out['db_vs_comp_only_in_comp'] = sorted(comp_set - db_set)
out['rule_vs_comp_diff'] = sorted(rule_set ^ comp_set)

# alt-cut sensitivity
if alt_set is not None:
    out['alt_cut_swap'] = {'drop': tie_in[-1], 'add': tie_out[0],
                           'alt_rule_count': len(alt_set),
                           'diff_vs_std': sorted(alt_set ^ rule_set)}

# enrich FP/FN with reasons
def name_of(uid):
    for r in rows:
        if r['uid_hex'] == uid: return r['species_name'], r['alignment_name'], r['gl_chain_ranks']
    return ('?','?','?')

fp_detail = []
for u in fp:
    nm, al, ch = name_of(u)
    # why does it fail? find best rank per meta species it could claim
    reasons = []
    shadow = (al == 'SHADOW')
    for form, rank in parse_chain(ch).items():
        sid = f'{form}_shadow' if shadow else form
        if sid in meta_std:
            br = best_per.get(sid)
            iswin = (br and br[1] == u)
            reasons.append(f"{sid}: thisrank={rank} bestowned_rank={br[0] if br else None} isbest={iswin}")
    fp_detail.append(f"{u} {nm}/{al} chain=[{ch}] meta_matches={reasons or 'NONE_IN_META'}")

fn_detail = []
for u in fn:
    nm, al, ch = name_of(u)
    wins = tag_detail.get(u, [])
    fn_detail.append(f"{u} {nm}/{al} strict_wins={wins} chain=[{ch}]")

out['fp_detail'] = fp_detail
out['fn_detail'] = fn_detail
out['verdict'] = 'PASS' if (len(db_set)==len(rule_set) and not fp and not fn) else 'ISSUES'
out['comp_matches_db'] = (comp_set == db_set)

print(json.dumps(out, indent=2, ensure_ascii=False))
c.close()
