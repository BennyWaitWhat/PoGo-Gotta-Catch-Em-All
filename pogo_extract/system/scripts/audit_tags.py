"""audit_tags.py -- per-tag consistency audit, run EVERY recrawl (baked into pogo_pipeline.py).

Proves keep_policy's keep-reasons agree with build_tagsets' tag files, so a drift between the two
files (the recurring failure mode: Legacy-cap 2026-06-05, XXL form-vs-cf 2026-06-07) is caught
automatically instead of only when the user asks.

  EXACT tags  (Hundo / Nundo / GL IV / UL IV / Best Buddy / Traded-by-E+F[reason 'origin']):
              the tag MUST equal its keep-reason set exactly. Any difference = real drift.
  LABEL tags  (Event = cosmetic costume/bg/art ; Legacy Moves = all legacy-move mons ;
              XXL = size-5 showcase): the tag is a broader *label*, so the file may be a SUPERSET
              of the keep-reason (a mon kept for another reason can still carry the label). The
              real invariants: (a) NO tagged mon is in Transfer (keeper leak), and (b) every
              mon kept *for that reason* IS labeled (reason subset file). The benign superset is OK.
  Partition   every in-bag mon is either kept (>=1 reason) or in Transfer -- never both, never neither.

Reads only FRESH sources (policy_reasons.json + the tagset files) so it is valid in the pipeline
BEFORE the server sync (auth_tag_names lags until set_db). The server<->DB<->file leg is the separate
post-sync reconcile_tags.py. Exit 1 on any real drift, 0 on clean.
"""
import os, sys, json, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets')

pr = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))


def ru(reason):
    return set(u for u, rs in pr.items() if reason in rs)


def fu(fn):
    try:
        return set(x.strip() for x in open(os.path.join(TD, fn), encoding='utf-8') if x.strip())
    except FileNotFoundError:
        return set()


transfer = fu('Transfer.txt')
problems = []

EXACT = [('Hundo', 'Hundo.txt', 'hundo'), ('Nundo', 'Nundo.txt', 'nundo'),
         ('Traded by E+F', 'Traded_by_E+F.txt', 'origin')]   # Best Buddy retired 2026-06-07
LABEL = [('Legacy Moves', 'Legacy_Moves.txt', 'legacy'),      # 'Event' retired 2026-09-09 (native chips)
         ('XXL', 'XXL.txt', 'xxl')]
# 'GL IV' / 'UL IV' RETIRED 2026-09-09 (granular_tags.RETIRED_TAGS). The keep reason (gl_iv / ul_iv) is unchanged;
# its LABEL is now the union of the per-stage rank tags. Invariants: every mon kept for the reason carries one
# of them (miss), and none of them is in Transfer (leak). The union is a benign superset (Pokemod-style labels).
# PvP_Spread counts too: an over-cap keeper gets no Rank chip (it cannot enter that league) but is still the elite
# spread rule 15b keeps. audit_tags_membership.py learned this on 2026-09-19; this file had to as well.
_EVF = ['Evolve_to_Mid.txt', 'Evolve_to_Final.txt', 'Evolve_Needs_Item.txt', 'Evolve_Needs_Task.txt', 'Evolve_for_GL.txt', 'Evolve_for_UL.txt']
RANKED = [('gl_iv', 'GL rank tags', ['GL_Rank_1-5.txt', 'GL_1-5_No_Evolve.txt', 'Best_GL.txt'] + _EVF),   # 2026-09-30
          ('ul_iv', 'UL rank tags', ['UL_Rank_1-5.txt', 'UL_1-5_No_Evolve.txt', 'Best_UL.txt'] + _EVF)]

print("=== TAG AUDIT (keep_policy reason <-> build_tagsets file) ===")
# Best ML = the pvp_best_ml reason MINUS hundos (user 2026-09-23: the chip skips a hundo, the keep does not) and MINUS
# Variant #1 (2026-10-25, user picked "B": your top-IV copy is its stage's best ML copy -- the chip repeated Variant #1)
_bm_r, _bm_f = ru('pvp_best_ml') - ru('hundo') - fu('Variant_#1.txt'), fu('Best_ML.txt')
if _bm_r != _bm_f:
    problems.append(f"Best ML: reason-minus-hundo-and-Variant-#1 != file (missing={len(_bm_r - _bm_f)}, extra={len(_bm_f - _bm_r)})")
print(f"  {'Best ML':<15} reason-minus-hundo={len(_bm_r)} file={len(_bm_f)}  {'OK' if _bm_r == _bm_f else 'DRIFT'}")
# Best GL / Best UL = the pvp_best_gl / _ul reason MINUS the copy told to Evolve for that league (2026-09-30: the Evolve
# tag says it); rule 15d, 2026-09-23
for _lg in ('GL', 'UL'):
    _br, _bf = ru('pvp_best_' + _lg.lower()) - fu('Evolve_for_%s.txt' % _lg), fu('Best_%s.txt' % _lg)
    if _br != _bf:
        problems.append(f"Best {_lg}: reason-minus-Evolve-for != file (missing={len(_br - _bf)}, extra={len(_bf - _br)})")
    print(f"  {'Best ' + _lg:<15} reason-minus-evolve={len(_br)} file={len(_bf)}  {'OK' if _br == _bf else 'DRIFT'}")
for tag, fn, reason in EXACT:
    R, F = ru(reason), fu(fn)
    if R != F:
        problems.append(f"{tag}: EXACT reason!=file (reason-not-file={len(R - F)}, file-not-reason={len(F - R)})")
    print(f"  {tag:<15} reason={len(R)} file={len(F)}  {'OK' if R == F else 'DRIFT'}")

def _overcap_spreads(uids, reason):
    """Spreads kept by rule 15b that cannot ENTER their league at any rank<=ready stage (pvp_iv_rule.fits at the true
    level) carry NO rank chip by design (user 2026-09-23: "why are they even tagged"); the keep itself is untouched.
    Same exemption as audit_tags_membership.py. Unknown data (no row, no template) is never exempted."""
    try:
        import sqlite3 as _sq
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, _root)
        import keep_config as _kc
        from pvp_iv_rule import fits as _fits, chain_stage_ranks as _csr, maxcp as _maxcp, GL_CAP as _G, UL_CAP as _U, VIABILITY_MARGIN as _VM
        lg = 'gl' if reason == 'gl_iv' else 'ul'
        cap = _G if lg == 'gl' else _U
        BS = {p['speciesId']: p.get('baseStats', {}) for p in json.load(open(os.path.join(_root, 'pvpoke_gamemaster.json'), encoding='utf-8'))['pokemon']}
        rr = _kc.pvp('ready_rank')
        con = _sq.connect('file:%s?mode=ro' % os.path.join(_root, 'pokemon.db').replace('\\', '/'), uri=True)
        con.row_factory = _sq.Row
        out = set()
        for u in uids:
            r = con.execute('SELECT * FROM pokemon WHERE uid_hex=?', (u,)).fetchone()
            if r is None:
                continue
            usable = any(rk <= rr and _maxcp(st, BS) > cap + _VM and _fits(r, st, cap, BS) for st, rk in _csr(r, lg))
            if not usable:
                out.add(u)
        con.close()
        return out
    except Exception as _e:
        print('  (over-cap exemption unavailable: %s)' % _e)
        return set()


for reason, tag, fns in RANKED:
    R = ru(reason)
    F = set().union(*(fu(fn) for fn in fns))
    leak, miss = F & transfer, R - F
    _oc = _overcap_spreads(miss, reason) if miss else set()
    if _oc:
        print(f"  {tag:<15} {len(_oc)} kept spread(s) cannot enter the league at any rank<=ready stage -> no chip by design")
        miss = miss - _oc
    if leak:
        problems.append(f"{tag}: {len(leak)} tagged mon(s) ALSO in Transfer (keeper leak)")
    if miss:
        problems.append(f"{tag}: {len(miss)} mon(s) kept-for-{reason} but carrying NO rank tag")
    print(f"  {tag:<15} reason={len(R)} file={len(F)} (label union, benign-superset extra={len(F - R)}) "
          f"leak={len(leak)} miss={len(miss)}  {'OK' if not leak and not miss else 'DRIFT'}")

for tag, fn, reason in LABEL:
    F = fu(fn)
    R = ru(reason) if reason else set()
    leak = F & transfer
    miss = (R - F) if reason else set()      # kept FOR this reason but NOT labeled -> real bug
    if leak:
        problems.append(f"{tag}: {len(leak)} tagged mon(s) ALSO in Transfer (keeper leak)")
    if miss:
        problems.append(f"{tag}: {len(miss)} mon(s) kept-for-{reason} but missing the tag")
    extra = len(F - R) if reason else '-'
    print(f"  {tag:<15} reason={len(R)} file={len(F)} (label, benign-superset extra={extra}) "
          f"leak={len(leak)} miss={len(miss)}  {'OK' if not leak and not miss else 'DRIFT'}")

# partition integrity
c = sqlite3.connect(os.path.join(ROOT, 'pokemon.db'))
allu = set(r[0] for r in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1"))
keepu = set(pr.keys()) & allu
overlap = keepu & transfer
uncl = allu - keepu - transfer
if overlap:
    problems.append(f"partition: {len(overlap)} mon(s) BOTH kept AND in Transfer")
if uncl:
    problems.append(f"partition: {len(uncl)} mon(s) NEITHER kept nor in Transfer (unclassified)")
print(f"  partition: bag={len(allu)} kept={len(keepu)} transfer={len(transfer)} "
      f"overlap={len(overlap)} unclassified={len(uncl)}")

if problems:
    print("\n!! TAG AUDIT FAIL:")
    for p in problems:
        print("   - " + p)
    sys.exit(1)
print("\nTAG AUDIT: PASS -- exact tags match their keep-reason; label tags keeper-free; partition clean.")
