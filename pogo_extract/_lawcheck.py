"""READ-ONLY third audit: independently re-derive WHY each Transfer-pile mon is in the pile, straight
from the agreed keep law (NOT from the engine's own policy_reasons). Every pile mon must reduce to one of:
  - over its SHADOW cap  (top-N by IV per (pid,cf), plus best GL and best UL)
  - over its SHINY cap   (top-N per (pid,cf), richer-first at the margin)
  - over its cosmetic-variant cap (costume/art-bg/deco/Dmax/Gmax bucket, top-N by IV then CP)
  - outside the plain floor (plain rank > cap: 2 for a still-evolvable stage, 3 for a final)
  - collapsed UP into a strictly-richer, strictly-higher-IV sibling
Anything left UNEXPLAINED is a potential wrongly-culled keeper -> FAIL, do not sync.

LOCKDOWN 2026-09-02 -- this is one of the four gate audits full_audit.py greps. Its passing line MUST
keep the exact substring 'UNEXPLAINED: 0'. (full_audit gates on rc==0 AND that substring, so a nonzero
exit still fails the gate even when the count is 0 -- that is how the stale-pile refusal below works.)

SHINY AND SHADOW SUBJECTS USED TO BE AUTO-EXPLAINED (audit F4, 2026-09-02). The plain-floor branch
built its occupancy `pool` from siblings that are `not shadow and not shiny`, so when the SUBJECT was
itself shiny or shadow it was excluded from its own pool, could never appear in `merged`, and fell
straight through to why='outside plain floor'. All three piled shadows were "explained" that way --
including the exact Amaura audit_cull simultaneously reported as a within-cap shadow keeper. 1385
shinies + 241 shadows were structurally un-flaggable. They now get their OWN cap re-derivations, and a
pile member that is INSIDE any cap it competes in stays UNEXPLAINED, which is the whole point.

The cosmetic-cap occupancy is keyed by the COSMETIC BUCKET (the costume-form value / fresh_costume / bg /
bread mode), NOT the full attribute set: a costume-form copy that ALSO carries a location card still
occupies a costume-cap slot (it just has an extra independent keep axis). An earlier version keyed by the
full attribute set, under-counted a 4-strong costume-form Lapras bucket, and false-flagged the correctly
culled 4th copy (2026-08-19).

SHINIES DISPLACE THE PLAIN FLOOR (blind spot #3, 2026-08-23): a non-hundo shiny OCCUPIES a plain-floor
slot by IV and WINS IV ties (user-approved precedent: the tied-IV 89% Wailmer transferred over its
same-IV shiny). An earlier version excluded shinies from the floor occupancy entirely and false-flagged
a 51% plain Skarmory whose third floor slot was legitimately taken by its tied 51% shiny. Shadows stay
excluded -- they live in their own bundle and never touch the plain floor.
"""
import sqlite3, json, collections, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, '.'); sys.path.insert(0, 'system/scripts')
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
# SELECT * IS DELIBERATE -- never narrow it. Every predicate reads columns by name, so a column absent
# from the projection reads None, its axis reads False, and the check silently passes everything.
_cur = con.execute('SELECT * FROM pokemon WHERE in_bag=1')
_cols = [d[0] for d in _cur.description]
rows = [dict(zip(_cols, t)) for t in _cur.fetchall()]
by = {r['uid_hex']: r for r in rows}
PILE = 'system/analysis/tagsets/Transfer.txt'
ps = set(x for x in open(PILE).read().split() if x)
from costume_forms import is_costume_form
import keep_config
import evolvable_forms   # BREAD_MODES / max_axis: the game's own Max-mode names
import pattern_pools   # pattern-pooled lines: ONE CAP_FINAL pool per pattern across the whole line (2026-09-08)
# (2026-09-26) fused components hold no ladder slot (user: "i think 2 are currently fused. So don't count those in the
# ladder."). A Reshiram/Zekrom HELD inside a fused Kyurem (keep_config.is_fused_component) is out of keep_policy's `rows`
# before ANY competition, so every pool / cap / Best GL/UL/ML / comb-up / form-0 vote below is taken without it. `by`
# (built above) stays WHOLE-bag, so a fused uid in the pile is still found -- and FAILs in the loop below.
FUSED = {r['uid_hex'] for r in rows if keep_config.is_fused_component(r)}
rows = [r for r in rows if r['uid_hex'] not in FUSED]
CAP_FINAL = keep_config.cap('plain_line'); CAP_PRE = keep_config.cap('plain_line_preevo')
CAP_COS = keep_config.cap('cosmetic'); CAP_DMAX = keep_config.cap('dynamax'); CAP_GMAX = keep_config.cap('gigantamax')

def _pile_legitimately_empty(pile_path):
    """True iff keep_policy itself produced an EMPTY pile: pile_provenance.json says pile_count 0 and its
    pile_sha256 equals the sha of the file on disk (sha256 of nothing). A vanished or truncated file does not
    match and is still refused. 2026-09-12: the user released everything and the next pass had nothing to cull."""
    try:
        import hashlib as _h
        _prov = json.load(open('system/analysis/pile_provenance.json', encoding='utf-8'))
        return (_prov.get('pile_count') == 0
                and _prov.get('pile_sha256') == _h.sha256(open(pile_path, 'rb').read()).hexdigest())
    except Exception:
        return False

# An EMPTY pile used to sail through this audit: no subjects, no unexplained, 'UNEXPLAINED: 0', rc 0.
# A vanished/truncated Transfer.txt is a defect, never a pass.
if not ps:
    if _pile_legitimately_empty(PILE):
        print('pile is EMPTY by keep_policy (provenance pile_count=0, sha matches) -- nothing to re-derive. UNEXPLAINED: 0')
        sys.exit(0)
    print('*** REFUSING: %s is empty -- there is nothing to re-derive, which is not a PASS' % PILE)
    sys.exit(1)

# PILE PROVENANCE GATE (audit F3) -- every cap below is read LIVE from keep_config, so it only means
# anything if this pile was built from that same config. A cap LOWERED after the pile was built HIDES a
# real leak (demonstrated: a genuine within-cap shiny keeper injected into the pile FAILED, then editing
# caps.shiny 10->4 made the same leak report clean). keep_config.json only changes by a human/dashboard
# edit, so "newer than the pile" is unambiguous; pokemon.db is deliberately NOT gated, because set_db
# writes auth_tag_names back into it after every sync and gating on that would deadlock the pipeline.
# When keep_policy starts stamping system/analysis/pile_provenance.json, the hash REPLACES the mtime
# heuristic -- do not keep both (cross-package X1).
_STALE = []
try:
    _pile_mt = os.path.getmtime(PILE)
    _prov = None
    if os.path.exists('system/analysis/pile_provenance.json'):
        try:
            _prov = json.load(open('system/analysis/pile_provenance.json', encoding='utf-8'))
        except Exception:
            _prov = None
    # KEY *AND* DIGEST must match keep_policy's writer exactly (cross-package X1, reconciled 2026-09-02).
    # keep_policy stamps 'config_sha256' from keep_config.fingerprint() ('_note' excluded, compact
    # separators). This read 'keep_config_sha256' and recomputed sha256(json.dumps(keep_config.raw(),
    # sort_keys=True)): different key AND different digest. The key mismatch silently disabled the check;
    # fixing only the key would have made every run a PERMANENT false STALE that no re-run could clear.
    _stamp = (_prov or {}).get('config_sha256') or (_prov or {}).get('keep_config_sha256')
    if _stamp:
        _fp = getattr(keep_config, 'fingerprint', None)
        if _fp is not None:
            _live = _fp()
        else:
            import hashlib
            _live = hashlib.sha256(json.dumps(keep_config.raw(), sort_keys=True).encode('utf-8')).hexdigest()
        if _live != _stamp:
            _STALE.append('keep_config fingerprint %s != the pile stamp %s' % (_live[:12], str(_stamp)[:12]))
    elif os.path.getmtime('keep_config.json') > _pile_mt + 5:
        _STALE.append('keep_config.json is NEWER than the pile -- caps may have changed since it was built')
except OSError as _e:
    _STALE.append('could not stat the pile/config (%s)' % _e)
if _STALE:
    print('*** STALE PILE -- the caps below come from the LIVE keep_config, which did not build this pile.')
    for _s in _STALE:
        print('***   %s' % _s)
    print('*** FIX: re-run keep_policy.py then build_tagsets.py, then re-run this audit.')
    print('*** (the re-derivation still runs, but this audit exits nonzero so the gate cannot pass)')

# engine-identical form-0 normalization, INCLUDING keep_policy's _is_regional_code guard. Without it a
# regional form code carrying a blank/NULL form_region can be elected the species' base form, and the
# base-region copy then collapses onto it (the guarded map has 702 entries, the unguarded 701).
from pvp_iv_rule import pvid
_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
def _is_regional_code(nm, f):
    return any(x in pvid(nm, f) for x in _REGSUF)
_bc = collections.defaultdict(collections.Counter)
for r in rows:
    fo = r.get('form') or 0; reg = ((r.get('form_region') or '')).strip().lower()
    if fo and reg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], fo) \
            and not is_costume_form(fo):   # a costume is never a base form (2026-09-23)
        _bc[r['pokemon_id']][fo] += 1
base = {p: c.most_common(1)[0][0] for p, c in _bc.items() if len(c) == 1}
cf = lambda r: (base.get(r['pokemon_id'], r.get('form') or 0) if not (r.get('form') or 0) else r.get('form'))

def _bmn(r):     # every Max mode is a collectible axis and its own bundle (evolvable_forms.BREAD_MODES)
    return r['fresh_bread_mode'] or 0

def domattr(r):
    s = set()
    if r['fresh_shiny']: s.add(('shiny', 1))
    # ('sbg',...) REMOVED 2026-09-02 -- special_bg_id is a garbage column with no writer (see keep_policy)
    if (r['fresh_natural_art_bg'] or 0): s.add(('abg', r['fresh_natural_art_bg']))
    if r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0): s.add(('loc', r['fresh_loc_card_enum']))
    if (r['fresh_costume'] or 0): s.add(('cos', r['fresh_costume']))
    elif is_costume_form(r['fresh_form']): s.add(('cosf', r['fresh_form']))
    _ax = evolvable_forms.max_axis(_bmn(r))
    if _ax: s.add(('gmax' if _ax == 'gigantamax' else 'dmax', 1))
    if r['fresh_alignment'] == 1: s.add(('shadow', 1))
    return frozenset(s)

def cosbucket(r):
    """the cosmetic identity that defines the rule-1a cap group (loc/shiny are SEPARATE axes)."""
    if r['fresh_costume']: return ('cos', r['fresh_costume'])
    if is_costume_form(r['fresh_form'] or 0): return ('cosf', r['fresh_form'])
    if is_costume_form(r['form'] or 0): return ('cosf', r['form'])
    if r['fresh_natural_art_bg']: return ('abg', r['fresh_natural_art_bg'])
    bm = _bmn(r)
    if bm: return ('bread', bm)
    return None

def truly_plain(r):
    return (not (r['fresh_costume'] or 0) and not (r['fresh_natural_art_bg'] or 0)
            and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
            and _bmn(r) == 0 and not is_costume_form(r['fresh_form']))
# nundo is slot-exempt only while its keep-all is ON -- keep_policy._slot_exempt gates on the same
# toggle, and with rules.nundo OFF a nundo competes for a slot like any other plain.
_NUNDO_ON = keep_config.rule_enabled('nundo')
trophy = lambda r: (r['iv_total'] or 0) == 45 or (_NUNDO_ON and (r['iv_total'] or 0) == 0 and r['pokemon_id'])

gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
BS = {p['speciesId']: p for p in gm['pokemon']}; S2D = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
# SEEN = EVERY dex entry, matching keep_policy:123. The old `times > 0` filter dropped pid 983
# (Kingambit), which is precisely why can_evo() disagreed with the engine on 3 Bisharp.
SEEN = {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']}
SEEN |= set(json.load(open('released_pids.json'))) if os.path.exists('released_pids.json') else set()   # any account (2026-09-26)

# EVOLVABILITY MUST MATCH THE ENGINE (audit F14). The hand-rolled version had no BST-monotonic gate, no
# "target exists in the gamemaster" gate, no curated EVO_FIX edges and no gender rule, and diverged on
# 15 live rows -- 10 of them in the UNDER-detect direction (7 male Combee, 2 male Salandit, 1 Sinistcha
# were treated as evolvable, applying the TIGHTER pre-evo floor and OVER-explaining the pile). The
# graph builder is imported from the engine because a hand copy is exactly what drifted; the fallback
# keeps this audit runnable (loudly degraded) if that import ever breaks.
_GRAPH_SRC = 'keep_policy.build_evo_graph'
try:
    from keep_policy import build_evo_graph as _build_evo_graph
    _is_pre_sp, _term_sp, _dist_sp_, _s2d_, _allreach_sp = _build_evo_graph(gm, SEEN, with_all=True)
    _HAS_PARENT = {t for _ts in _allreach_sp.values() for t in _ts}   # middle-stage test (2026-09-13)
except Exception as _e:
    _GRAPH_SRC = 'LOCAL FALLBACK (%s)' % _e
    print('*** WARNING: could not import keep_policy.build_evo_graph (%s) -- falling back to the raw'
          ' gamemaster family graph, which is LOOSER than the engine.' % _e)
    _is_pre_sp, _term_sp = {}, {}
    _HAS_PARENT = {e for _p in gm['pokemon'] for e in ((_p.get('family') or {}).get('evolutions') or [])}
    for _p in gm['pokemon']:
        _ev = [e for e in ((_p.get('family') or {}).get('evolutions') or []) if S2D.get(e) in SEEN]
        _is_pre_sp[_p['speciesId']] = bool(_ev)
        _term_sp[_p['speciesId']] = {S2D.get(e) for e in _ev if S2D.get(e)}
# gender decides the terminal (or blocks evolution) for these six -- the gamemaster family graph cannot
# express it, so keep_policy hardcodes the same table inside main(). Kept in sync by hand until it is
# hoisted to module scope in keep_policy and can be imported (cross-package note).
GENDER_TERMINALS = {
    415: {1: set(), 2: {416}},          # Combee:   M dead-end, F -> Vespiquen
    757: {1: set(), 2: {758}},          # Salandit: M dead-end, F -> Salazzle
    361: {1: {362}, 2: {478, 362}},     # Snorunt:  M -> Glalie, F -> Froslass/Glalie
    281: {1: {475, 282}, 2: {282}},     # Kirlia:   M -> Gallade/Gardevoir, F -> Gardevoir
    280: {1: {475, 282}, 2: {282}},     # Ralts:    (same downstream)
    412: {1: {414}, 2: {413}},          # Burmy:    M -> Mothim, F -> Wormadam
}
def can_evo(r):
    gt = GENDER_TERMINALS.get(r['pokemon_id'])
    if gt is not None:
        return bool(gt.get(r['gender'], set()))   # UNKNOWN gender -> DON'T guess: treated as not evolvable
    sid = pvid(r['species_name'], r['form'] or 0)
    return bool(_term_sp.get(sid, set())) if _is_pre_sp.get(sid) else False

iv = lambda r: (r['iv_total'] or 0)
_cp = lambda r: (r['cp'] or 0)

# ---- SHADOW and SHINY cap re-derivations (the F4 fix) ----------------------------------------------
# shadow: top-cap('shadow') by IV per (pid,cf), PLUS the best GL rank and the best UL rank -- up to 3
# distinct specimens. shiny: top-N per (pid,cf) with the engine's richer-first ordering at the margin.
def _best_by(lst, key):
    c = [x for x in lst if x[key] is not None]
    return min(c, key=lambda x: x[key]) if c else None
def _scoll(r):                       # engine's collectible identity set (keep_policy._scollect)
    z = set()
    if (r['fresh_natural_art_bg'] or 0): z.add(('abg', r['fresh_natural_art_bg']))
    if r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0): z.add(('loc', r['fresh_loc_card_enum']))
    if (r['fresh_costume'] or 0): z.add(('cos', r['fresh_costume']))
    elif is_costume_form(r['fresh_form']): z.add(('cosf', r['fresh_form']))
    _ax = evolvable_forms.max_axis(_bmn(r))
    if _ax: z.add(('gmax' if _ax == 'gigantamax' else 'dmax', 1))
    if r['fresh_alignment'] == 1: z.add(('shadow', 1))
    return z
_shadow_keep, _shiny_keep = set(), set()
_shg, _shyg = collections.defaultdict(list), collections.defaultdict(list)
for r in rows:
    if r['fresh_alignment'] == 1:
        _shg[(r['pokemon_id'], cf(r))].append(r)
    if r['fresh_shiny']:
        _shyg[(r['pokemon_id'], cf(r))].append(r)
# 2026-09-23: shadows per PvP IDENTITY -- best ML (top cap('shadow') by ml_rank, uid), best GL, best UL. GL / UL are
# USABLE ONLY (user 2026-09-23): _usable() below. Re-derived independently of keep_policy rule 2.
from pvp_iv_rule import maxcp as _sh_maxcp, GL_CAP as _SH_GL, UL_CAP as _SH_UL, VIABILITY_MARGIN as _SH_VM
from pvp_iv_rule import fits as _u_fits            # the ONE shared CP/level helper (true level, CP at a stage)
_SH_BS = {p['speciesId']: p.get('baseStats', {}) for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
_sh_via = lambda sid, cap: bool(sid) and _sh_maxcp(sid, _SH_BS) > cap + _SH_VM
# the later stages a specimen can become: a FACT off the engine's ONE graph (imported above for the same reason);
# the graph fallback cannot say -> the ranker's chain as it stands (looser: can only report, never hide, a leak).
try:
    from keep_policy import pvp_later_stages as _pls
    _U_GRAPH = (_is_pre_sp, _term_sp, _dist_sp_, _s2d_, _allreach_sp)
    _u_later = lambda r: _pls(r, _U_GRAPH)
except Exception as _e:
    _u_later = lambda r: None
def _usable(r, lg, cap):
    """(reaches-the-cap-first key, rank) of the best stage this copy can REACH and ENTER (fits: its CP there at its
    TRUE level inside the cap), or None -- such a copy can never be that league's best."""
    own = pvid(r['species_name'], r['form'] or 0)
    later = _u_later(r)
    st = []
    for p in str(r[lg + '_chain_ranks'] if (lg + '_chain_ranks') in r.keys() else '').split(';'):
        if ':' in p:
            try:
                st.append((p.split(':')[0].strip(), int(p.split(':')[1].split('(')[0])))
            except ValueError:
                pass
    if not st and r[lg + '_rank'] is not None:
        st = [(r[lg + '_stage'], r[lg + '_rank'])]
    reach = [(s, k) for s, k in st if s and (s == own or later is None or s in later)]   # evolution counts everywhere (2026-09-24)
    if not any(_u_fits(r, s, cap, _SH_BS) for s, _k in reach):
        return None
    best = None
    for s, k in reach:
        best = min(best, (0 if _sh_via(s, cap) else 1, k)) if best is not None else (0 if _sh_via(s, cap) else 1, k)
    return best
def _usable_winner(lst, lg, cap):
    c = [(k, y) for y in lst for k in (_usable(y, lg, cap),) if k is not None]
    return min(c, key=lambda z: (z[0][0], z[0][1], z[1]['uid_hex']))[1]['uid_hex'] if c else None
def _usable_winner_rk(lst, lg, cap):                          # (uid, usable rank) for the shadow floor (2026-09-24)
    c = [(k, y) for y in lst for k in (_usable(y, lg, cap),) if k is not None]
    b = min(c, key=lambda z: (z[0][0], z[0][1], z[1]['uid_hex'])) if c else None
    return (b[1]['uid_hex'], b[0][1]) if b else (None, None)
_SRF = keep_config.pvp('shadow_rank_floor')
_shp = collections.defaultdict(list)
for r in rows:
    if r['fresh_alignment'] == 1:
        _shp[pvid(r['species_name'], r['form'] or 0)].append(r)
for _l in _shp.values():
    for x in sorted((y for y in _l if (y['ml_rank'] if 'ml_rank' in y.keys() else None) is not None and y['ml_rank'] <= _SRF),
                    key=lambda y: (y['ml_rank'], y['uid_hex']))[:keep_config.cap('shadow')]:
        _shadow_keep.add(x['uid_hex'])
    for _lg, _cap in (('gl', _SH_GL), ('ul', _SH_UL)):
        if _lg not in keep_config.shadow_leagues():          # UL only since 2026-09-26
            continue
        _w, _wr = _usable_winner_rk(_l, _lg, _cap)
        if _w and _wr <= _SRF:
            _shadow_keep.add(_w)
    if not any(y['uid_hex'] in _shadow_keep for y in _l):    # rule 7 (2026-10-25): the identity's last shadow always stays
        _mlr = lambda y: (y['ml_rank'] if 'ml_rank' in y.keys() else None)
        _shadow_keep.add(min(_l, key=lambda y: (_mlr(y) if _mlr(y) is not None else 10 ** 6, -iv(y), y['uid_hex']))['uid_hex'])
for _k, _l in _shyg.items():
    _n = keep_config.species_cap('shiny', _k[0], keep_config.cap('shiny'))
    # 2026-09-23: at most cap('shiny_plain') PLAIN shinies; a per-species exception covers plains too
    _np = _n if keep_config.species_cap('shiny', _k[0], None) is not None else min(_n, keep_config.cap('shiny_plain'))
    _rk = sorted(_l, key=lambda y: (-iv(y), -len(_scoll(y)), -_cp(y), y['uid_hex']))
    _sfl = keep_config.shiny_floor_iv(); _first = _rk[0]['uid_hex'] if _rk else None      # shiny floor, best of the form stays (2026-09-24)
    _ffree = {z['uid_hex'] for z in _rk[:keep_config.shiny_floor_keep()]}   # ... its N best stay (2026-10-25: "at least keep 2")
    _plsh = [y for y in _rk if not _scoll(y)]; _first_pl = _plsh[0]['uid_hex'] if _plsh else None   # ...and the best PLAIN one
    _lk = {}                                  # every look first, comb up, cap stays (user 2026-09-30, LAW bucket 4)
    for y in _rk:
        _lk.setdefault(((y['fresh_costume'] or 0), evolvable_forms.gender_key(y['pokemon_id'], y['gender'])), y['uid_hex'])
    _lt = set(_lk.values())
    _pok = {y['uid_hex'] for y in ([y for y in _plsh if y['uid_hex'] in _lt]
                                   + [y for y in _plsh if y['uid_hex'] not in _lt
                                      and (iv(y) >= _sfl or y['uid_hex'] in _ffree or y['uid_hex'] == _first_pl)])[:_np]}
    _el = [y for y in _rk if _scoll(y) or y['uid_hex'] in _pok]
    for x in ([y for y in _el if y['uid_hex'] in _lt] + [y for y in _el if y['uid_hex'] not in _lt])[:_n]:
        _shiny_keep.add(x['uid_hex'])

# ---- BEST GL / BEST UL (LAW bucket 2b = keep_policy rule 15d, user 2026-09-23) -----------------------------
# The best NON-shadow copy per PvP IDENTITY. GL / UL are USABLE ONLY (user 2026-09-23): key (the usable stage reaches
# the cap first, its rank, uid_hex) over the copies with a stage they can reach AND enter (_usable above); a copy with
# none never wins. ML unchanged: (viable ml_stage first, ml_rank, uid_hex). The engine's exact total order. Such a
# copy is never fodder: if one is in the pile, no other explanation applies.
from pvp_iv_rule import (maxcp as _pb_maxcp, GL_CAP as _PB_GL, UL_CAP as _PB_UL, ML_CAP as _PB_ML,
                         VIABILITY_MARGIN as _PB_VM, pvid as _pb_pvid)
_PB_BS = {p['speciesId']: p.get('baseStats', {})
          for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
_pb_via = lambda sid, cap: bool(sid) and _pb_maxcp(sid, _PB_BS) > cap + _PB_VM
_cu_res = __import__('pvp_combup').pick_default(rows)
_combup_keep = set(_cu_res['gl']) | set(_cu_res['ul'])   # rule 15e (2026-09-24)
_pvp_best_keep = set()
_pbg = collections.defaultdict(list)
for r in rows:
    if r['fresh_alignment'] == 1:
        continue
    _pbg[_pb_pvid(r['species_name'], r['form'] or 0)].append(r)   # PvP identity (2026-09-23)
_BRF = keep_config.pvp('best_rank_floor')                   # rule 15d best rank floor (2026-09-24)
from references import LEGENDARY_IDS as _LI, MYTHICAL_IDS as _MI, ULTRA_BEAST_IDS as _UI, PARADOX_IDS as _PI
_LAW_RARE = _LI | _MI | _UI | _PI                            # legendaries: no rank floor (user 2026-09-24)
_pid_of = {r['uid_hex']: r['pokemon_id'] for r in rows}
for _l in _pbg.values():
    for _lg, _cap in (('gl', _PB_GL), ('ul', _PB_UL)):
        _w, _wr = _usable_winner_rk(_l, _lg, _cap)
        if _w and (_wr <= _BRF or _pid_of.get(_w) in _LAW_RARE):
            _pvp_best_keep.add(_w)
    _c = [x for x in _l if (x['ml_rank'] if 'ml_rank' in x.keys() else None) is not None and (x['ml_rank'] <= _BRF or x['pokemon_id'] in _LAW_RARE)]
    if _c:
        _pvp_best_keep.add(min(_c, key=lambda x: (0 if _pb_via(x['ml_stage'], _PB_ML) else 1, x['ml_rank'], x['uid_hex']))['uid_hex'])

# the dominance/plain groups are keyed (pid, cf, gender-for-gender-evolvers) exactly like the engine's
# _domgrp / _stage_key. Without the gender component the audit cannot detect a regression of the guard
# that stops a MALE special from eating a rare FEMALE Combee/Salandit/Burmy's floor slot (59 such mons).
_gterm = lambda r: evolvable_forms.gender_key(r['pokemon_id'], r['gender'])   # gender-locked OR dimorphic (2026-09-23)
grp = collections.defaultdict(list)
for r in rows: grp[(r['pokemon_id'], cf(r), _gterm(r))].append(r)
grp_nog = collections.defaultdict(list)          # gender-blind siblings for the costume-variant cap
for r in rows: grp_nog[(r['pokemon_id'], cf(r))].append(r)
# PATTERN-POOLED lines (keep_policy._stage_key via pattern_pools): every stage of one pattern is ONE plain
# pool with CAP_FINAL slots. The dominance collapse stays per (pid, cf, gender) -- only the floor is pooled.
_pk = lambda r: pattern_pools.pool_key(r['pokemon_id'], r['species_name'], r.get('form') or 0, r.get('gender'))
pgrp = collections.defaultdict(list)
for r in rows:
    _k = _pk(r)
    if _k: pgrp[_k].append(r)

unexplained = []; summary = collections.Counter()
def _below_floor(P, pool):
    """COLLECTION FLOOR (2026-09-24): a plain copy under keep_config.collection_floor_iv holds no slot unless it is the
    pool's best copy (keep_config.floor_top on the IV-sorted pool -- the engine's topn)."""
    kept_by_floor = {x['uid_hex'] for x in keep_config.floor_top(sorted(pool, key=lambda x: (-iv(x), -_cp(x), x['uid_hex'])))}
    return P['uid_hex'] not in kept_by_floor
for u in sorted(ps):
    if u not in by:
        summary['NOT IN BAG'] += 1
        continue
    P = by[u]
    if u in FUSED:                           # (2026-09-26) held inside a fused Kyurem: the engine keeps it as 'fused'
        summary['UNEXPLAINED (fused component)'] += 1   # and the game cannot release it -- never a pile candidate
        unexplained.append(P)
        continue
    gkey = (P['pokemon_id'], cf(P), _gterm(P))
    sib = [x for x in grp[gkey] if x['uid_hex'] != u]
    # COSTUME buckets are gender-BLIND like the engine's _vkey (2026-09-23): the plain floor splits dimorphic species by
    # gender, a costume variant does not (the user cut Pikachu 6 -> 4 to have FEWER; a per-gender bucket would double it).
    sib_nog = [x for x in grp_nog[(P['pokemon_id'], cf(P))] if x['uid_hex'] != u]
    kept = [x for x in sib if x['uid_hex'] not in ps]
    why = None
    if u in _combup_keep:                    # rule 15e (2026-09-24): the copy to evolve for a better GL / UL stage copy
        summary['UNEXPLAINED (PvP comb-up copy)'] += 1
        unexplained.append(P)
        continue
    if u in _pvp_best_keep:                  # a Best GL / Best UL copy is never fodder -- nothing explains it
        summary['UNEXPLAINED (Best GL/UL copy)'] += 1
        unexplained.append(P)
        continue
    # --- shadow / shiny subjects: they never compete for the plain floor or the rule-1a cosmetic cap
    # (the engine excludes both pools from `plain`), so being OUTSIDE their own cap is the complete and
    # only explanation. A subject inside ANY cap it competes in stays UNEXPLAINED -> FAIL.
    _axes = []
    if P['fresh_alignment'] == 1:
        _axes.append(('shadow', u in _shadow_keep))
    if P['fresh_shiny']:
        _axes.append(('shiny', u in _shiny_keep))
    if _axes:
        if not any(k for _n, k in _axes):
            why = 'over %s cap' % '+'.join(n for n, _k in _axes)
    elif not truly_plain(P):
        # cosmetic cap: occupancy keyed by the COSMETIC BUCKET (all copies of this costume/bg/bread identity),
        # NOT the full attr set -- a same-bucket copy that also carries loc/shiny still eats a cap slot.
        bkt = cosbucket(P)
        bm = _bmn(P)
        _ax = evolvable_forms.max_axis(bm)
        _cat = 'gigantamax' if _ax == 'gigantamax' else 'dynamax' if _ax == 'dynamax' else 'cosmetic'
        _glob = CAP_GMAX if _ax == 'gigantamax' else CAP_DMAX if _ax == 'dynamax' else CAP_COS
        # per-species override (Curation Studio) where the engine uses it -- the global cap was hardcoded
        # here for cosmetic/Dmax/Gmax even though this file already routes shiny through species_cap.
        if _cat == 'cosmetic':
            _glob = evolvable_forms.costume_cap(P['pokemon_id'], P['fresh_costume'] or 0, _glob)   # middle-stage costumes 1 (2026-09-25)
        cap = keep_config.species_cap(_cat, P['pokemon_id'], _glob)
        bucketmates =[x for x in sib_nog + [P] if cosbucket(x) == bkt and not trophy(x)]
        ranked = keep_config.floor_top(__import__('costume_forms').backgrounds_first(   # backgrounds first (2026-09-24)
            sorted(bucketmates, key=lambda x: (-iv(x), -_cp(x), x['uid_hex']))))   # collection floor (2026-09-24)
        if u in [x['uid_hex'] for x in ranked[cap:]]:
            why = 'over-cap cosmetic variant'
        elif u not in [x['uid_hex'] for x in ranked]:       # floor_top dropped it: under the collection floor, not the bucket's best
            why = 'below the collection floor'
    else:
        _pool_key = _pk(P)
        _fsib = [x for x in pgrp[_pool_key] if x['uid_hex'] != u] if _pool_key else sib   # floor siblings: the pattern pool, else (pid,cf,gender)
        pool = [x for x in _fsib + [P] if x['fresh_alignment'] != 1 and not x['fresh_shiny'] and truly_plain(x) and not trophy(x)]
        # floor OCCUPANTS beyond the plains: cosmetic specials AND shinies (shinies displace the plain
        # floor and win IV ties -- Wailmer precedent). Trophies never occupy (slot-exempt). No shadows.
        specials = [x for x in _fsib if x['fresh_alignment'] != 1 and (not truly_plain(x) or x['fresh_shiny'])
                    and not trophy(x)]
        _sidP = pvid(P['species_name'], P['form'] or 0)
        cap = CAP_FINAL if _pool_key else evolvable_forms.ladder_cap(   # MIDDLE stages only get CAP_PRE (2026-09-13)
            CAP_PRE if (can_evo(P) and _sidP in _HAS_PARENT) else CAP_FINAL, P['pokemon_id'], _gterm(P))   # 2 per gender, dimorphic (2026-09-25)
        if P['pokemon_id'] == 201:
            # UNOWN CARVE-OUT (blind spot #4, 2026-08-29): Unown keeps the ORIGINAL COUNT-BASED rule --
            # plain cap = LINE_CAP minus the NUMBER of non-hundo shinies of that letter, regardless of IV
            # order (keep_policy._line_cap). The generic IV-merged rule only lets a shiny displace a plain
            # it OUTRANKS; for Unown a LOWER-IV shiny still burns a slot. Modelling Unown generically
            # false-flagged the correctly culled 3rd plain of letter 6 (its 71% shiny cuts the cap to 2).
            cap = max(0, cap - len([x for x in sib if x['fresh_shiny'] and iv(x) != 45]))
            merged = sorted([(iv(x), _cp(x), 1, x['uid_hex']) for x in pool],
                            key=lambda t: (-t[0], -t[1]))[:cap]
            if not any(t[3] == u for t in merged):
                why = 'outside plain floor'
            elif _below_floor(P, pool):
                why = 'below the collection floor'
            summary[why or 'UNEXPLAINED'] += 1
            if not why: unexplained.append(P)
            continue
        merged = sorted([(iv(x), _cp(x), 0, x['uid_hex']) for x in specials]
                        + [(iv(x), _cp(x), 1, x['uid_hex']) for x in pool],
                        key=lambda t: (-t[0], -t[1], t[2]))[:cap]
        if not any(t[3] == u for t in merged):
            why = 'outside plain floor'
        elif _below_floor(P, pool):
            why = 'below the collection floor'
        elif [x for x in kept if not trophy(x) and domattr(x) and (domattr(x) | domattr(P)) == domattr(x) and iv(x) > iv(P)]:
            why = 'collapsed UP'
    summary[why or 'UNEXPLAINED'] += 1
    if not why: unexplained.append(P)

print('pile %d | evo graph: %s | fused components out of every ladder: %d | justification tally: %s' % (
    len(ps), _GRAPH_SRC, len(FUSED), dict(summary)))
for P in sorted(unexplained, key=lambda x: (-iv(x), x['uid_hex'])):
    print('  *** UNEXPLAINED: %s %d%% cp%s form=%s shiny=%s shadow=%s' % (
        P['species_name'], round(iv(P) / 45 * 100), P['cp'], P['form'],
        bool(P['fresh_shiny']), P['fresh_alignment'] == 1))
print('UNEXPLAINED: %d -> %s' % (len(unexplained), 'FAIL -- do NOT sync' if unexplained else 'every pile mon derives from the agreed law'))
if _STALE:
    print('(exiting nonzero: the pile is STALE relative to keep_config -- see the banner above)')
sys.exit(1 if (unexplained or _STALE) else 0)
