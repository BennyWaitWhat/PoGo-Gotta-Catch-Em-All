"""Thorough multi-layer audit of the current Transfer pile. READ-ONLY.

Every layer must pass before the pile is trusted. Reusable: run after any recrawl.
  python audit_cull.py

LOCKDOWN 2026-09-02 -- this file is one of the four gate audits full_audit.py greps. Its passing
verdict line MUST keep the exact substring 'ALL LAYERS PASS' (full_audit.AUDITS) or the gate starts
silently failing every run.
"""
import sqlite3, json, sys, glob, os, collections, re, math
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
TD = os.path.join('system', 'analysis', 'tagsets')
PILE = os.path.join(TD, 'Transfer.txt')
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
ps = set(x for x in open(PILE).read().split() if x)
# SELECT * IS DELIBERATE -- do NOT narrow the projection. Every predicate below reads its columns via
# dict .get(), so a column missing from the SELECT reads None -> the predicate is False -> that keep
# axis silently passes EVERYTHING. (The row build is dict(zip(cols, tuple)) rather than dict(sqlite3.Row)
# purely for speed: 6x faster, provably identical data -- no duplicate column names in SELECT *.)
_cur = con.execute('SELECT * FROM pokemon WHERE in_bag=1')
_cols = [d[0] for d in _cur.description]
rows = {}
for _t in _cur.fetchall():
    _d = dict(zip(_cols, _t))
    rows[_d['uid_hex']] = _d
# '_'-prefixed keys are metadata, never a uid_hex -- filtering them keeps LAYER 4's accounting correct
# if keep_policy ever stamps a '_meta' provenance block into policy_reasons.json (cross-package X1).
pol = {u: v for u, v in json.load(open('system/analysis/policy_reasons.json')).items() if not u.startswith('_')}
try:
    from costume_forms import is_costume_form
except Exception:
    is_costume_form = lambda f: False
import keep_config
import evolvable_forms   # BREAD_MODES / max_axis: the game's own Max-mode names
_EF = set(o.strip().lower() for o in keep_config.origin_owners())   # keep-all trade partners
# (2026-09-26) fused components hold no ladder slot (user: "i think 2 are currently fused. So don't count those in the
# ladder."). A Reshiram/Zekrom HELD inside a White/Black Kyurem (is_component=1) is kept as 'fused' and is NOT in
# keep_policy's `rows`, so every competition re-derived below (ladders, top-N, caps, Best GL/UL/ML, comb-up, one nundo
# per look, last-copy counts) runs over _crows. Whole-bag checks (not in bag, accounting, data completeness) keep `rows`;
# a fused component in the pile is its own LAYER 2 FAIL line.
_crows = [r for r in rows.values() if not keep_config.is_fused_component(r)]

FAILS = []
def chk(name, n):
    good = (n == 0)
    if not good:
        FAILS.append(name)
    return 'OK' if good else '*** FAIL ***'

def deco(r):
    d = r.get('costume_decoration_id')
    return d if (d and str(d) != '0') else 0

F = lambda p: [u for u in ps if u in rows and p(rows[u])]

# ---------------------------------------------------------------------------------------------------
# PILE PROVENANCE GATE (audit F3, 2026-09-02). NOTHING used to bind the pile to the keep_config that
# produced it, so a cap LOWERED after the pile was built silently MASKED a real leak: injecting a
# genuine within-cap shiny keeper into the pile FAILED the shiny layer, then editing caps.shiny 10->4
# (same pile, same DB) made that same leak report 0 OK. Every cap re-derivation below re-reads the
# LIVE keep_config, so it only means anything if the pile was built from that same config.
# This is a mtime heuristic ON PURPOSE so it needs no other package. When keep_policy starts stamping
# a config fingerprint (see system/analysis/pile_provenance.json below), REPLACE the heuristic with the
# hash comparison rather than keeping both.
# keep_config.json only ever changes by a human/dashboard edit, so "newer than the pile" is unambiguous.
# pokemon.db is deliberately NOT a hard failure: set_db_tags_from_files writes auth_tag_names back into
# the DB *after* build_tagsets on every normal cycle, so its mtime is routinely newer than the tagset --
# gating on it would deadlock the pipeline permanently. A DB that actually drifted is caught by content
# instead, by LAYER 2's 'not in bag' and LAYER 4's accounting identity.
_STALE = []
try:
    _pile_mt = os.path.getmtime(PILE)
    _prov = None
    for _pp in (os.path.join('system', 'analysis', 'pile_provenance.json'),):
        if os.path.exists(_pp):
            try:
                _prov = json.load(open(_pp, encoding='utf-8'))
            except Exception:
                _prov = None
    # KEY *AND* DIGEST must match keep_policy's writer exactly (cross-package X1, reconciled 2026-09-02).
    # keep_policy stamps 'config_sha256', computed by keep_config.fingerprint() (merged config, '_note'
    # excluded, compact separators). This consumer read 'keep_config_sha256' and recomputed
    # sha256(json.dumps(keep_config.raw(), sort_keys=True)) -- a different key AND a different digest
    # (default separators, '_note' included; measured 4719d2df... vs a9986176... on the live config).
    # The key mismatch silently disabled the whole check and fell back to mtime; fixing ONLY the key
    # would have been worse than leaving it, because the two digests can never agree -- every run would
    # report a PERMANENT false STALE and no re-run could ever clear the gate. fingerprint() is THE one
    # definition (that is why keep_config defines it); the old recompute survives only as a fallback for
    # a keep_config.py that predates it.
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
        _STALE.append('keep_config.json is NEWER than the pile (caps may have changed since it was built)')
    # ...AND THE ENGINE THAT BUILT IT (2026-09-20). The stamp pinned every INPUT but not the CODE, so editing a
    # keep rule and re-running `full_audit.py --audits-only` re-derived the OLD pile with the NEW engine and
    # reported all-green -- the audits agreeing with themselves about a pile neither of them built. Recompute the
    # same digest keep_policy stamps; None on either side means "cannot say" and is left to the mtime fallback,
    # never treated as a match. (2026-09-30: costume_forms.py + form_enum.json + gamemaster_pokeminers.json joined the list -- they decide
    # what a costume is -- so the pile stamped before that reads stale ONCE here, until the next keep_policy + build_tagsets run:
    # the cull's recrawl step does it before its audits; `--audits-only` and `--skip-crawl` do not.)
    _esig = (_prov or {}).get('engine_sha256')
    if _esig:
        import hashlib as _ehl
        _eh = _ehl.sha256()
        _emiss = False
        for _rel in ('system/scripts/keep_policy.py', 'system/scripts/build_tagsets.py',
                     'pvp_iv_rule.py', 'evolvable_forms.py', 'system/scripts/rank_cache.py',
                     'cpm_table.py', 'form_overrides_complete.py', 'pvpoke_gamemaster.json', 'size_line.py',
                     'costume_forms.py', 'form_enum.json', 'gamemaster_pokeminers.json'):   # = keep_policy._engine_sha (same list, same order)
            try:
                _eh.update(open(_rel, 'rb').read())
            except OSError:
                _emiss = True
                break
        if not _emiss and _eh.hexdigest() != _esig:
            _STALE.append('the ENGINE changed since this pile was built (keep_policy/build_tagsets/pvp_iv_rule/'
                          'evolvable_forms/rank_cache/cpm_table/form_overrides/pvpoke_gamemaster/size_line/'
                          'costume_forms/form_enum/gamemaster_pokeminers hash %s != the '
                          'pile stamp %s) -- re-run keep_policy.py + '
                          'build_tagsets.py before trusting these audits'
                          % (_eh.hexdigest()[:12], str(_esig)[:12]))
    if os.path.getmtime('pokemon.db') > _pile_mt + 5:
        print('  NOTE  pokemon.db is newer than the pile -- normal right after a tag sync (set_db writes '
              'auth_tag_names back); LAYER 2 "not in bag" + LAYER 4 accounting catch a real bag drift.')
except OSError as _e:
    _STALE.append('could not stat the pile/config (%s)' % _e)
if _STALE:
    FAILS.append('stale pile')

print('=' * 72)
print('CULL AUDIT  --  %d tagged for transfer, bag %d' % (len(ps), len(rows)))
print('=' * 72)
if _STALE:
    print('\n*** STALE PILE -- every cap below is re-derived from the LIVE keep_config, but this pile')
    print('*** was NOT built from it, so a cap change can both invent phantom leaks and HIDE real ones.')
    for _s in _STALE:
        print('***   %s' % _s)
    print('*** FIX: re-run keep_policy.py then build_tagsets.py, then re-run this audit.')
    print('*** (the layers still run below for diagnosis, but the verdict can never PASS while stale)')

print('\nLAYER 1  (not audited here -- preflight_transfer.py runs as its own gate step)')
# Was a bare unconditional print claiming 'PASS (this recrawl; live gym read)'. There is no code behind
# that: this file never references preflight_transfer, and full_audit.AUDITS does not include it. A
# fabricated PASS counted toward 'ALL LAYERS PASS'. Honest placeholder until preflight writes a result
# file this audit can assert on (cross-package X2).

print('\nLAYER 2  independent SQL on every keeper axis')
missing = len(ps) - len([u for u in ps if u in rows])
print('  %-18s %-5d %s' % ('not in bag', missing, chk('in-bag', missing)))

# --- engine-identical form-0 normalization, built ONCE (was built twice in this file, both times
# WITHOUT keep_policy's _is_regional_code guard -- a regional form code carrying a blank form_region
# could become the species' "base form" and collapse the Kantonian copy onto it). --------------------
try:
    from pvp_iv_rule import pvid as _pvid
except Exception:
    _pvid = None
_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
def _is_regional_code(nm, f):
    return any(x in _pvid(nm, f) for x in _REGSUF) if _pvid else False
_bc = collections.defaultdict(collections.Counter)
for r in _crows:                             # (2026-09-26) fused components hold no ladder slot -- engine elects without them
    _fo = r.get('form') or 0
    _rg = ((r.get('form_region') or '')).strip().lower()
    if _fo and _rg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], _fo) \
            and not __import__('costume_forms').is_costume_form(_fo):   # a costume is never a base form (2026-09-23)
        _bc[r['pokemon_id']][_fo] += 1
base = {p: c.most_common(1)[0][0] for p, c in _bc.items() if len(c) == 1}
cf = lambda r: (base.get(r['pokemon_id'], r.get('form') or 0) if not (r.get('form') or 0) else r.get('form'))
_cfa = cf                                    # legacy alias (this file used two names for one map)
# engine tiebreaks (keep_policy.topn): IV, then CP, then uid -- uid last so stat-identical dupes can
# never reshuffle between runs. The irreversible pile membership has to be reproducible.
_topn = lambda lst, n: keep_config.floor_top(sorted(lst, key=lambda r: (-(r.get('iv_total') or 0), -(r.get('cp') or 0), r['uid_hex'])))[:n]   # collection floor (2026-09-24)
def _best_by(lst, key):
    cand = [r for r in lst if r.get(key) is not None]
    return min(cand, key=lambda r: r[key]) if cand else None

# SWITCHABLE KEEP-ALL AXES. keep_config 'rules' can turn nundo / adventure_effect / mighty /
# location_card / dex_only OFF; the engine honors that, so a blanket predicate here reported every
# now-legitimately-culled mon as a leak and DEADLOCKED the pipeline (proven 2026-09-02: rules.
# location_card=false piled 161 more and this layer FAILED all 161). All toggles default ON, so this
# is behavior-neutral today.  NOTE cross-package X4: preflight_transfer re-asserts the same five axes
# unconditionally, so flipping a toggle still aborts there -- both must move together.
_R = {k: keep_config.rule_enabled(k) for k in ('nundo', 'adventure_effect', 'mighty', 'location_card', 'dex_only')}
def _ae_sids():
    try:
        import json as _j, time as _t
        _p = os.path.join(ROOT, 'system', 'analysis', 'ae_roster_derived.json')
        if os.path.exists(_p) and (_t.time() - os.path.getmtime(_p)) < 14 * 86400:
            s = set((_j.load(open(_p, encoding='utf-8')).get('species_ids') or {}).keys())
            if s:
                return s
    except Exception:
        pass
    return None
_AE_SIDS = _ae_sids()
import ae_moves as _aem
_AE_MOVES = _aem.move_ids()
def _ae_form_hit(r):
    """keep_policy rule 8 as of 2026-09-23: the SPECIMEN knows an Adventure-Effect move (live registry). Only an
    unreadable registry falls back to the FORM (pvid in the derived speciesIds), then the species list."""
    if _AE_MOVES is not None:
        return bool(_aem.known(r, _AE_MOVES))
    if _AE_SIDS is not None:
        try:
            from pvp_iv_rule import pvid as _pv
            return _pv(r['species_name'], r.get('form') or 0) in _AE_SIDS
        except Exception:
            pass
    return r['pokemon_id'] in keep_config.ae_pids()

# XXL is a CAPPED axis (top-N showcase per (pid,cf)) -- every other axis here used to be modelled as
# keep-all. A 3rd+ XXL beyond the cap is LEGITIMATELY cullable, so a blanket "no size-5 in pile"
# false-FAILED on a 3rd XXL Magikarp (2026-08-19). Grouped by cf(), NOT the raw form -- the engine
# keys on cf, and the raw key produced a 207th member (a form-0 Voltorb whose cf is 1047) the engine
# never keeps. The uid tiebreak mirrors keep_policy so tie-scored mons cannot swap on a recrawl.
# XXL (2026-09-23): per PvP identity, XXL badge only, ranked by the game's points (size_line) -- mirrors rule 7.
from pvp_iv_rule import pvid as _sc_pvid
import size_line as _slx
_SC_MIN = keep_config.showcase_weights()['min_points']
def _sc_ok(r):
    """A showcase WINNER (user 2026-09-23: "keep pokemon that score over 1000"): points >= min_points. An unknown
    template scores None -> protected (unknown data is never fodder)."""
    _p = _slx.best_points(r)   # evolution counts (2026-09-24)
    return _p is None or _p >= _SC_MIN
_xxl_grp = collections.defaultdict(list)
for r in _crows:                                   # (2026-09-26) fused components hold no ladder slot
    if (r.get('pokemon_size_category') or 0) == 5 and r.get('height_m') is not None and r.get('weight_kg') is not None and _sc_ok(r):
        _xxl_grp[_sc_pvid(r['species_name'], r.get('form') or 0)].append(r)
_XW = keep_config.showcase_weights()
def _showscore(r, gh, gw):
    return (_XW['height'] * ((r.get('height_m') or 0) / gh) + _XW['weight'] * ((r.get('weight_kg') or 0) / gw)
            + _XW['iv'] * ((r.get('iv_total') or 0) / 45))

# --- RULE 1a VARIANT FLOOR, re-derived (drives the Dynamax / Gigantamax layers) ---------------------
# DYNAMAX / GIGANTAMAX are CAPPED axes like XXL, not keep-all: a blanket "no Dmax/Gmax in the pile"
# false-FAILED on a 4th Dmax Eevee (2026-08-31) exactly as the blanket XXL rule false-failed on a 3rd
# XXL Magikarp. The earlier replica also over-counted 23 keepers: it pooled SHINIES and SHADOWS into
# the cap group (the engine keeps those on their own axes and excludes them from rule 1a), keyed on
# (pid,cf,bread) instead of the engine's full 7-tuple _vkey, used the GLOBAL cap where the engine uses
# species_cap, and ignored the same-variant shiny displacement.
def _bmn(r):        # every Max mode is a real collectible axis and its own bundle (evolvable_forms.BREAD_MODES)
    return r.get('fresh_bread_mode') or 0
def _vkey(r):
    return (r['pokemon_id'], cf(r), r.get('fresh_costume') or 0, 0,   # slot 4 was special_bg_id (retired)
            r.get('fresh_natural_art_bg') or 0, deco(r), _bmn(r))
def _truly_plain(r):
    return (not (r.get('fresh_costume') or 0) and not (r.get('fresh_natural_art_bg') or 0)
            and not deco(r) and _bmn(r) == 0 and not is_costume_form(r.get('fresh_form')))
def _slot_exempt(r):     # an unconditionally-kept trophy never consumes a capped slot
    if (r.get('iv_total') or 0) == 45:
        return True
    return bool(_R['nundo'] and r.get('is_zero') and r['pokemon_id'])
_vg = collections.defaultdict(list)
_shvar = collections.defaultdict(list)
for r in _crows:                                     # (2026-09-26) fused components hold no ladder slot
    if (r.get('fresh_alignment') or 0) == 1:
        continue                                     # shadow lives in its own bundle
    if r.get('fresh_shiny'):
        if (r.get('iv_total') or 0) != 45 and not _truly_plain(r):
            _shvar[_vkey(r)].append(((r.get('iv_total') or 0), (r.get('cp') or 0)))
        continue                                     # shinies are kept by the shiny cap, not rule 1a
    if _truly_plain(r) or _slot_exempt(r):
        continue
    _vg[_vkey(r)].append(r)
def _var_eff_cap(key, cap, pool):
    sh = _shvar.get(key)
    if not sh:
        return cap
    merged = sorted([(i, c, 0) for i, c in sh]
                    + [((r.get('iv_total') or 0), (r.get('cp') or 0), 1) for r in pool],
                    key=lambda x: (-x[0], -x[1], x[2]))[:cap]       # tie -> shiny(0) first
    return sum(1 for x in merged if x[2] == 1)
_var_keep = set()
for _k, lst in _vg.items():
    _ax = evolvable_forms.max_axis(_k[-1])
    if _ax == 'dynamax':       _vc, _vcat = keep_config.cap('dynamax'), 'dynamax'
    elif _ax == 'gigantamax':  _vc, _vcat = keep_config.cap('gigantamax'), 'gigantamax'
    else:              _vc, _vcat = evolvable_forms.costume_cap(_k[0], _k[2], keep_config.cap('cosmetic')), 'cosmetic'   # middle-stage costumes 1 (2026-09-25)
    _cap = _var_eff_cap(_k, keep_config.species_cap(_vcat, _k[0], _vc), lst)
    _srt = sorted(lst, key=lambda r: (-(r.get('iv_total') or 0), -(r.get('cp') or 0), r['uid_hex']))
    for r in keep_config.floor_top(__import__('costume_forms').backgrounds_first(_srt))[:_cap]:   # backgrounds first (2026-09-24)
        _var_keep.add(r['uid_hex'])
_bread_keep = set(u for u in _var_keep if _bmn(rows[u]))
for r in rows.values():                              # a hundo/nundo Dmax/Gmax is always a keeper
    if _bmn(r) and (r.get('iv_total') or 0) in (0, 45):
        _bread_keep.add(r['uid_hex'])

# SHADOW and SHINY are ALSO capped, not keep-all -- the SIXTH instance of this bug class (after costume
# bucket, XXL, Dmax/Gmax). Shadow keeps cap('shadow') by IV PLUS the best GL rank PLUS the best UL rank
# per (pid,cf) -- up to 3 distinct mons -- so a 3rd/4th shadow with no claim is legitimate fodder; the
# blanket check false-FAILED on 2 Amaura + 1 Tyrunt (2026-09-02). Shiny keeps top-N per (pid,cf) by the
# engine's richer-first ordering. Both replicas verified set-for-set against the engine (symdiff 0).
_shadow_keep, _shiny_keep = set(), set()
_shg, _shyg = collections.defaultdict(list), collections.defaultdict(list)
for r in _crows:                                     # (2026-09-26) fused components hold no ladder slot
    if (r.get('fresh_alignment') or 0) == 1:
        _shg[(r['pokemon_id'], cf(r))].append(r)
    if r.get('fresh_shiny'):
        _shyg[(r['pokemon_id'], cf(r))].append(r)
# 2026-09-23: shadows are kept per PvP IDENTITY as the best ML (top cap('shadow') by ml_rank, uid), the best GL and
# the best UL -- keep_policy rule 2, re-derived here. GL / UL are USABLE ONLY (user 2026-09-23): _pvp_usable() below.
from pvp_iv_rule import pvid as _sh_pvid, maxcp as _sh_maxcp, GL_CAP as _SH_GL, UL_CAP as _SH_UL, VIABILITY_MARGIN as _SH_VM
from pvp_iv_rule import fits as _pu_fits          # the ONE shared CP/level helper (true level, CP at a stage)
_SH_BS = {p['speciesId']: p.get('baseStats', {}) for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
_sh_via = lambda sid, cap: bool(sid) and _sh_maxcp(sid, _SH_BS) > cap + _SH_VM
# WHICH STAGES A SPECIMEN CAN BECOME is a FACT, read off the engine's ONE evolution graph (like _lawcheck / _spotdata:
# a hand copy of a graph is what drifts); WHO WINS is re-derived here. Import failure -> the ranker's chain as it
# stands, which is looser and can only report a leak, never hide one.
try:
    import keep_policy as _kp_g
    _PU_GRAPH = _kp_g.build_evo_graph(json.load(open('pvpoke_gamemaster.json', encoding='utf-8')),
                                      {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']},
                                      with_all=True)
    _pu_later = lambda r: _kp_g.pvp_later_stages(r, _PU_GRAPH)
except Exception as _e:
    print('  *** evolution graph unavailable (%s) -- Best GL/UL judged on the ranker\'s chain as it stands' % _e)
    _pu_later = lambda r: None
def _pvp_usable(r, lg, cap):
    """(reaches-the-cap-first key, rank) of the best stage this copy can REACH (own, or a later stage its form /
    costume / gender can become) and ENTER (fits: its CP there at its TRUE level inside the cap), or None."""
    own = _sh_pvid(r['species_name'], r.get('form') or 0)
    later = _pu_later(r)
    stages = []
    for _part in str(r.get(lg + '_chain_ranks') or '').split(';'):
        if ':' in _part:
            try:
                stages.append((_part.split(':')[0].strip(), int(_part.split(':')[1].split('(')[0])))
            except ValueError:
                pass
    if not stages and r.get(lg + '_rank') is not None:
        stages = [(r.get(lg + '_stage'), r.get(lg + '_rank'))]
    reach = [(s, k) for s, k in stages if s and (s == own or later is None or s in later)]   # evolution counts everywhere (2026-09-24)
    if not any(_pu_fits(r, s, cap, _SH_BS) for s, _k in reach):
        return None                                       # cannot ENTER the league at any stage it can reach
    best = None
    for _stg, _rnk in reach:
        _k = (0 if _sh_via(_stg, cap) else 1, _rnk)
        best = _k if best is None or _k < best else best
    return best
def _pvp_usable_winner(lst, lg, cap):
    _c = [(k, x) for x in lst for k in (_pvp_usable(x, lg, cap),) if k is not None]
    return min(_c, key=lambda y: (y[0][0], y[0][1], y[1]['uid_hex']))[1]['uid_hex'] if _c else None
def _pvp_usable_winner_rk(lst, lg, cap):                     # (uid, usable rank) -- the shadow floor needs the rank
    _c = [(k, x) for x in lst for k in (_pvp_usable(x, lg, cap),) if k is not None]
    _b = min(_c, key=lambda y: (y[0][0], y[0][1], y[1]['uid_hex'])) if _c else None
    return (_b[1]['uid_hex'], _b[0][1]) if _b else (None, None)
_SRF = keep_config.pvp('shadow_rank_floor')                 # rule 7 shadow rank floor (2026-09-24): top half only
_shp = collections.defaultdict(list)
for r in _crows:                                     # (2026-09-26) fused components hold no ladder slot
    if (r.get('fresh_alignment') or 0) == 1:
        _shp[_sh_pvid(r['species_name'], r.get('form') or 0)].append(r)
for lst in _shp.values():
    for r in sorted((x for x in lst if x.get('ml_rank') is not None and x['ml_rank'] <= _SRF), key=lambda x: (x['ml_rank'], x['uid_hex']))[:keep_config.cap('shadow')]:
        _shadow_keep.add(r['uid_hex'])
    for _lg, _cap in (('gl', _SH_GL), ('ul', _SH_UL)):
        if _lg not in keep_config.shadow_leagues():          # UL only since 2026-09-26
            continue
        _w, _wr = _pvp_usable_winner_rk(lst, _lg, _cap)
        if _w and _wr <= _SRF:
            _shadow_keep.add(_w)
def _scoll(r):                                                # engine's identity set, minus retired special_bg_id
    z = set()
    if (r.get('fresh_natural_art_bg') or 0): z.add(('abg', r['fresh_natural_art_bg']))
    if r.get('fresh_has_location_card') and (r.get('fresh_loc_card_enum') or 0): z.add(('loc', r['fresh_loc_card_enum']))
    if (r.get('fresh_costume') or 0): z.add(('cos', r['fresh_costume']))
    elif is_costume_form(r.get('fresh_form')): z.add(('cosf', r['fresh_form']))
    _ax = evolvable_forms.max_axis(_bmn(r))
    if _ax: z.add(('gmax' if _ax == 'gigantamax' else 'dmax', 1))
    if r.get('fresh_alignment') == 1: z.add(('shadow', 1))
    return z
for _k, lst in _shyg.items():
    _n = keep_config.species_cap('shiny', _k[0], keep_config.cap('shiny'))
    # at most cap('shiny_plain') PLAIN shinies (no bg/card/costume/Max/shadow); a per-species exception covers plains too
    _np = _n if keep_config.species_cap('shiny', _k[0], None) is not None else min(_n, keep_config.cap('shiny_plain'))
    _rk = sorted(lst, key=lambda x: (-(x.get('iv_total') or 0), -len(_scoll(x)), -(x.get('cp') or 0), x['uid_hex']))
    _sfl = keep_config.shiny_floor_iv(); _first = _rk[0]['uid_hex'] if _rk else None      # shiny floor, best of the form stays (2026-09-24)
    _plsh = [x for x in _rk if not _scoll(x)]; _first_pl = _plsh[0]['uid_hex'] if _plsh else None   # ...and the best PLAIN one
    _lk = {}                                  # every look first, comb up, cap stays (user 2026-09-30, LAW bucket 4)
    for x in _rk:
        _lk.setdefault(((x.get('fresh_costume') or 0), evolvable_forms.gender_key(x['pokemon_id'], x.get('gender'))), x['uid_hex'])
    _lt = set(_lk.values())
    _pok = {x['uid_hex'] for x in ([x for x in _plsh if x['uid_hex'] in _lt]
                                   + [x for x in _plsh if x['uid_hex'] not in _lt
                                      and ((x.get('iv_total') or 0) >= _sfl or x['uid_hex'] in (_first, _first_pl))])[:_np]}
    _el = [x for x in _rk if _scoll(x) or x['uid_hex'] in _pok]
    for r in ([x for x in _el if x['uid_hex'] in _lt] + [x for x in _el if x['uid_hex'] not in _lt])[:_n]:
        _shiny_keep.add(r['uid_hex'])

# PvP COMB-UP (rule 15e, 2026-09-24) -- pvp_combup.pick on the same bag and files the engine reads.
import pvp_combup as _pcu
_combup_res = _pcu.pick_default(_crows)       # (2026-09-26) fused components hold no ladder slot -- engine passes its rows
_combup_keep = set(_combup_res['gl']) | set(_combup_res['ul'])

# location_card top-N per (pid, cf, CARD ENUM), recomputed independently of the engine. A holder whose
# card enum is still UNKNOWN is uncapped/protected, exactly as keep_policy treats it.
_loc_keep = set()
_lg = collections.defaultdict(list)
for r in _crows:                                     # (2026-09-26) fused components hold no ladder slot
    if r.get('fresh_has_location_card') == 1:
        _e = r.get('fresh_loc_card_enum') or 0
        if not _e:
            _loc_keep.add(r['uid_hex'])          # unknown card -> never capped
        elif not __import__('costume_forms').card_folds_into_costume(r):   # costume + background = one ladder (2026-09-24)
            _lg[(r['pokemon_id'], _cfa(r), _e)].append(r)
for _k, _l in _lg.items():
    _n = keep_config.species_cap('location_card', _k[0], keep_config.cap('location_card'))
    _rank = [r for r in _l if (r.get('iv_total') or 0) not in (0, 45)]
    for r in keep_config.floor_top(sorted(_rank, key=lambda x: (-(x.get('iv_total') or 0), -(x.get('cp') or 0), x['uid_hex'])))[:_n]:   # collection floor
        _loc_keep.add(r['uid_hex'])
    for r in _l:
        if (r.get('iv_total') or 0) in (0, 45):
            _loc_keep.add(r['uid_hex'])          # trophies never consume a capped slot

def _scpts(r, gh, gw):
    import size_line as _sl
    _p = _sl.best_points(r)   # evolution counts (2026-09-24)
    return _p if _p is not None else _showscore(r, gh, gw)
_xxl_keep = set()
for _k, lst in _xxl_grp.items():
    pid = lst[0]['pokemon_id']
    gh = max((r.get('height_m') or 0) for r in lst) or 1
    gw = max((r.get('weight_kg') or 0) for r in lst) or 1
    ncap = keep_config.species_cap('xxl', pid, keep_config.cap('xxl'))
    for r in sorted(lst, key=lambda x: (-_scpts(x, gh, gw), x['uid_hex']))[:ncap]:
        _xxl_keep.add(r['uid_hex'])
# XXL TRIM (user 2026-09-29, only when he says): + the top caps.xxl_per_type per TYPE, re-derived HERE on its own -- types
# from pvpoke_gamemaster.json (the engine reads the game master through size_line), stages from size_line's graph.
_ptn = keep_config.cap('xxl_per_type')
if _ptn:
    _pvt = {p['speciesId']: [x for x in p.get('types', []) if x and x != 'none']
            for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
    _tbest = collections.defaultdict(dict)
    for lst in _xxl_grp.values():
        for r in lst:
            _stg = [(_sc_pvid(r['species_name'], r.get('form') or 0), _slx.showcase_points(r))]
            _stg += [(s, _slx.projected_points(r, s)) for s in _slx.later_stages(r)]
            for _sid0, _pt in _stg:
                if _pt is None or _pt < _SC_MIN:
                    continue
                for _ty in (_pvt.get(_sid0) or _pvt.get(_sid0.split('_')[0]) or []):
                    if _pt > _tbest[_ty].get(r['uid_hex'], -1):
                        _tbest[_ty][r['uid_hex']] = _pt
    for _d in _tbest.values():
        _xxl_keep |= {u for u, _ in sorted(_d.items(), key=lambda kv: (-kv[1], kv[0]))[:_ptn]}

# ---- FOUR AXES THAT HAD ZERO COVERAGE IN ANY OF THE FIVE AUDITS (audit F1, 2026-09-02) --------------
# rarity / legacy / protected / pvp_spread appeared NOWHERE in audit_cull, audit_tags_membership,
# _lawcheck, _spotdata or _evocheck. PROVEN BY INJECTION: one within-cap keeper per axis added to
# Transfer.txt (and removed from policy_reasons + the keep tagsets, exactly what build_tagsets does)
# and all four gate audits still reported PASS. Each is re-derived INDEPENDENTLY below from the DB +
# keep_config -- never imported from the engine, which is the whole point of a cross-check.
try:
    from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
    _RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
except Exception as _e:
    _RARE_PIDS = set()
    FAILS.append('references roster unreadable')
    print('  *** references.py unreadable (%s) -- rarity falls back to the NULL-prone is_* columns' % _e)
# THE SHINY EXEMPTION IS ONLY VALID WHILE THE SHINY RULE ACTUALLY KEEPS IT (cross-package, 2026-09-02).
# This replica skipped every shiny with the comment "shinies are kept in full by rule 3" -- but rule 3 is
# a CAP (top-N per (pid,cf)), not a keep-all, which is the exact "capped axis modelled as keep-all" class
# this review exists to remove. keep_policy fixed it the same day: a rare shiny the shiny cap DROPPED now
# forms its own rarity group under the SAME cap (keep_policy rule 5 `_rg_shiny`). Mirrored here, or this
# cross-check would bless a pile the current engine cannot build and would go blind the moment anyone
# reverted the engine fix. Deliberately a SEPARATE group, exactly like the engine: a cap-dropped shiny
# must never displace a non-shiny out of the rarity top-N. `_shiny_keep` above is this file's own
# independent re-derivation of rule 3, so the cross-check stays independent of the engine.
_rg, _rgpf = collections.defaultdict(list), collections.defaultdict(list)
_rg_shiny = collections.defaultdict(list)
for r in _crows:                                     # (2026-09-26) fused components hold no ladder slot
    if (r['pokemon_id'] in _RARE_PIDS or r.get('is_legendary') or r.get('is_mythical')
            or r.get('is_ultra_beast') or r.get('is_paradox')):
        _vk = (r['pokemon_id'], cf(r), 1 if r.get('fresh_alignment') == 1 else 0,
               r.get('fresh_bread_mode') or 0)
        if r.get('fresh_shiny'):
            if r['uid_hex'] not in _shiny_keep:      # "the shiny cap dropped it" -> own rarity group
                _rg_shiny[_vk].append(r)
            continue                                 # within the shiny cap -> exempt, as before
        _rg[_vk].append(r)
        _rgpf[(r['pokemon_id'], cf(r))].append(r)    # best GL/UL stays NON-shiny, exactly like the engine
_rarity_keep = set()
_KA = keep_config.rarity_keep_all()
try:
    _LEG_UIDS = {e['uid_hex'] for e in json.load(open('legacy_accurate.json', encoding='utf-8'))}
except Exception:
    _LEG_UIDS = None                                     # unreadable -> a laddered legendary keeps EVERY copy below
for _k, lst in list(_rg_shiny.items()) + list(_rg.items()):
    _lad = keep_config.rarity_ladder(_k[0])             # league ladders (Mewtwo, 2026-09-26) -- same function as the engine
    if _lad:
        _rarity_keep |= ({r['uid_hex'] for r in lst} if _LEG_UIDS is None
                         else keep_config.rarity_ladder_keep(lst, _LEG_UIDS, _lad))
        continue
    _n = len(lst) if _k[0] in _KA else keep_config.species_cap('rarity', _k[0], keep_config.cap('rarity'))
    if _k[2] == 1 and _k[0] not in _KA:            # shadow legendaries: caps.rarity_shadow (2026-09-29) -- mirrors rule 5
        _n = min(_n, keep_config.species_cap('rarity_shadow', _k[0], keep_config.cap('rarity_shadow')))
    for r in _topn(lst, _n):
        _rarity_keep.add(r['uid_hex'])
_rfloor = keep_config.rarity_floor_iv()                 # 3-star floor (2026-09-13) -- mirrors keep_policy rule 5
for lst in list(_rg_shiny.values()) + list(_rg.values()):
    for r in lst:
        if (r.get('iv_total') or 0) >= _rfloor:
            _rarity_keep.add(r['uid_hex'])
# (the legendary rule's own best GL/UL clause was removed 2026-09-23 -- rule 15d / Best GL/UL/ML covers it)

_legacy_keep = set()
try:
    _la = json.load(open('legacy_accurate.json', encoding='utf-8'))
    _legrec = {(e['uid_hex'] if isinstance(e, dict) else e) for e in _la} if isinstance(_la, list) else set(_la)
except Exception as _e:
    _legrec = set()
    FAILS.append('legacy_accurate.json unreadable')
    print('  *** legacy_accurate.json unreadable (%s) -- the legacy layer cannot run' % _e)
if _legrec is not None and not _legrec:
    if 'legacy_accurate.json unreadable' not in FAILS:
        FAILS.append('legacy source empty')
        print('  *** legacy_accurate.json holds 0 records -- the legacy layer would pass vacuously')
_LSC, _LDC = keep_config.legacy_caps(), keep_config.legacy_default_cap()
_legcap = lambda pid: _LSC.get(pid, _LDC)
_lc = collections.defaultdict(list)
for r in _crows:                                     # (2026-09-26) fused components hold no ladder slot (legacy cap)
    if r['uid_hex'] not in _legrec:
        continue
    if _legcap(r['pokemon_id']) is not None:
        _lc[r['pokemon_id']].append(r)
    else:
        _legacy_keep.add(r['uid_hex'])                 # uncapped species -> keep EVERY legacy specimen
for _pid, lst in _lc.items():
    _ks = set()
    for r in lst:                                      # specials are never cut from a capped species
        if (r.get('fresh_shiny') or r.get('fresh_alignment') == 1 or (r.get('fresh_costume') or 0)
                or is_costume_form(r.get('fresh_form')) or (r.get('iv_total') or 0) == 45):
            _ks.add(r['uid_hex'])
    for _key in ('gl_rank', 'ul_rank'):
        b = _best_by(lst, _key)
        if b:
            _ks.add(b['uid_hex'])
    for r in _topn([x for x in lst if x['uid_hex'] not in _ks], max(0, _legcap(_pid) - len(_ks))):
        _ks.add(r['uid_hex'])
    _legacy_keep |= _ks

_PROT = keep_config.protected_pids()                   # keep EVERY copy (Pichu) -- not switchable
import trophy_pick
_NUNDO_KEEP = trophy_pick.pick_nundos(_crows)   # one nundo per look (2026-09-17); (2026-09-26) fused components hold no ladder slot
_SPREAD = keep_config.pvp_spread_keep()                # named PvP trophy spreads (0/15/15) -- not switchable

# Best GL / Best UL (keep_policy rule 15d, user 2026-09-23): the best NON-shadow copy per PvP IDENTITY. GL / UL are
# USABLE ONLY (user 2026-09-23, "Best GL/UL must be able to enter the league"): key (the usable stage reaches the cap
# first, its rank, uid_hex) over the copies with a stage they can reach AND enter -- _pvp_usable() above. ML unchanged:
# (viable ml_stage first, ml_rank, uid_hex). The engine's exact TOTAL order, NOT the rowid-ordered _best_by above;
# viability = pvp_iv_rule.maxcp > cap + VIABILITY_MARGIN exactly as keep_policy._viable. Not switchable.
from pvp_iv_rule import (maxcp as _pb_maxcp, GL_CAP as _PB_GL, UL_CAP as _PB_UL, ML_CAP as _PB_ML,
                         VIABILITY_MARGIN as _PB_VM, pvid as _pb_pvid)
_PB_BS = {p['speciesId']: p.get('baseStats', {})
          for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
_pb_via = lambda sid, cap: bool(sid) and _pb_maxcp(sid, _PB_BS) > cap + _PB_VM
_pvp_best_keep = set()
_pbg = collections.defaultdict(list)
for r in _crows:                                     # (2026-09-26) fused components hold no ladder slot (Best GL/UL/ML)
    if r.get('fresh_alignment') == 1:
        continue
    _pbg[_pb_pvid(r['species_name'], r.get('form') or 0)].append(r)   # PvP identity (2026-09-23)
_BRF = keep_config.pvp('best_rank_floor')                   # rule 15d best rank floor (2026-09-24): top 20% only
for lst in _pbg.values():
    for _lg, _cap in (('gl', _PB_GL), ('ul', _PB_UL)):
        _w, _wr = _pvp_usable_winner_rk(lst, _lg, _cap)
        if _w and (_wr <= _BRF or rows[_w]['pokemon_id'] in _RARE_PIDS):   # legendaries: no rank floor (2026-09-24)
            _pvp_best_keep.add(_w)
    _c = [x for x in lst if x.get('ml_rank') is not None and (x['ml_rank'] <= _BRF or x['pokemon_id'] in _RARE_PIDS)]
    if _c:
        _pvp_best_keep.add(min(_c, key=lambda x: (0 if _pb_via(x.get('ml_stage'), _PB_ML) else 1, x['ml_rank'], x['uid_hex']))['uid_hex'])

for nm, p in [('hundo', lambda r: (r['iv_total'] or 0) == 45),
              # was `(r['iv_total'] or -1) == 0`, which evaluates 0 or -1 -> -1 and is therefore
              # UNSATISFIABLE: this layer printed 'nundo 0 OK' for a check that had never once run,
              # against 43 real nundos in the bag. Mirrors keep_policy's `is_zero and pokemon_id`.
              ('nundo', lambda r: _R['nundo'] and (r['iv_total'] or 0) == 0 and r['pokemon_id'] and r['uid_hex'] in _NUNDO_KEEP),
              ('shiny (top-N)', lambda r: r['fresh_shiny'] and r['uid_hex'] in _shiny_keep),
              # capped axes: only a WITHIN-CAP copy in the pile is a leak (an over-cap dupe is fodder)
              ('gigantamax (top-N)', lambda r: evolvable_forms.max_axis(_bmn(r)) == 'gigantamax' and r['uid_hex'] in _bread_keep),
              ('dynamax (top-N)', lambda r: evolvable_forms.max_axis(_bmn(r)) == 'dynamax' and r['uid_hex'] in _bread_keep),
              # E+F ORIGIN (engine reason: 'origin'; tag: "Traded by E+F"). Lucky is NOT required --
              # ANY trade whose ORIGINAL OWNER is a keep-all partner qualifies (most of Ethan's are
              # traded-but-not-lucky). Trades/luckies from anyone else are NORMAL and cullable.
              # Naming it "lucky" was wrong (user 2026-07-26); flagging every lucky was also wrong --
              # that false-alarmed on a Marowak traded from OyeBenny.
              ('E+F origin', lambda r: (r.get('is_lucky') == 1 or r.get('is_traded') == 1
                                        or r.get('is_traded_flag_v2') == 1)
                  and (r.get('original_owner_name') or '').strip().lower() in _EF),
              # CAPPED 2026-09-02 (top-N per (pid,cf,card enum)) -- a 7th+ holder of the SAME card is
              # legitimate fodder. The blanket keep-all check false-FAILED on 17 of them, the 8th
              # instance of the capped-axis-modelled-as-keep-all class.
              ('location card (top-N)', lambda r: _R['location_card']
                  and r.get('fresh_has_location_card') == 1 and r['uid_hex'] in _loc_keep),
              ('art bg', lambda r: (r.get('fresh_natural_art_bg') or 0)),   # special_bg_id retired: garbage column
              # PvP COMB-UP (rule 15e, 2026-09-24): the copy that would make a better GL / UL copy of a stage after evolving
              ('PvP comb-up (evolve)', lambda r: r['uid_hex'] in _combup_keep),
              # PER MON since 2026-09-23 (knows the effect's move); form / species roster only as fallback.
              # adventure_effects_left is NOT a keep signal on its own (2026-09-24: a shiny Rapidash 27% carried 1 and
              # false-FAILED the shiny-floor pile); it only backs the roster up when the live registry is unreadable.
              ('AE roster', lambda r: _R['adventure_effect']
                  and (_ae_form_hit(r) or (_AE_MOVES is None and (r.get('adventure_effects_left') or 0) > 0))),
              ('mighty', lambda r: _R['mighty'] and r.get('fresh_is_strong') == 1),
              ('shadow (top-N)', lambda r: (r.get('fresh_alignment') or 0) == 1 and r['uid_hex'] in _shadow_keep),
              # capped axis: only a TOP-N-showcase XXL in the pile is a leak; a 3rd+ XXL is cullable
              ('XXL (top-N kept)', lambda r: r['uid_hex'] in _xxl_keep),
              # --- the four axes that had no coverage at all until 2026-09-02 (audit F1) ---
              ('rarity (top-N)', lambda r: r['uid_hex'] in _rarity_keep),
              ('legacy (kept)', lambda r: r['uid_hex'] in _legacy_keep),
              ('protected pid', lambda r: r['pokemon_id'] in _PROT),
              ('pvp spread', lambda r: (r.get('iv_atk'), r.get('iv_def'), r.get('iv_sta')) in _SPREAD),
              ('best gl/ul', lambda r: r['uid_hex'] in _pvp_best_keep),
              # (2026-09-26) fused components hold no ladder slot -- and are NEVER pile candidates: the game holds
              # them inside a Kyurem (hidden, not releasable). Engine keeps them as 'fused'; any in the pile is a leak.
              ('fused component', lambda r: keep_config.is_fused_component(r))]:
    n = len(F(p))
    print('  %-18s %-5d %s' % (nm, n, chk(nm, n)))

# INDEPENDENT OF THE ENGINE'S SELECTORS (H08, 2026-09-29). The 'nundo' and 'PvP comb-up (evolve)' lines above ask
# trophy_pick.pick_nundos / pvp_combup.pick_default -- the very functions keep_policy and preflight_transfer call -- so a
# bug in either could never be seen here (45 of the 47 kept nundos rest on pick_nundos alone). These two re-derive LAW
# buckets 1 and 2c from LAW.md's words in independent_law.py, which imports neither (audit_invariants I1.8 checks that).
import independent_law as _il
_il_nundo = _il.nundo_violations(_crows, ps, keep_config.cap('nundo'), cf, is_costume_form) if _R['nundo'] else []
print('  %-18s %-5d %s   (LAW bucket 1 re-derived: one per look, farthest from Atlanta first)'
      % ('nundo look (law)', len(_il_nundo), chk('nundo look (law)', len(_il_nundo))))
for _u, _why in _il_nundo[:6]:
    print('     ! %s %s: %s' % (rows[_u]['species_name'], _u, _why))
try:
    _il_labels = json.load(open(os.path.join('system', 'analysis', 'pvp_combup_labels.json'), encoding='utf-8'))
except (OSError, ValueError):
    _il_labels = None                                   # no record of the picks: every opportunity below reads uncovered
_il_cu = _il.combup_uncovered(
    _crows, ps, _il_labels or {}, own_of=lambda r: _sh_pvid(r['species_name'], r.get('form') or 0), later_fn=_pu_later,
    fits_fn=lambda r, s, c: _pu_fits(r, s, c, _SH_BS), reaches_fn=_sh_via, caps={'gl': _SH_GL, 'ul': _SH_UL},
    floor=keep_config.pvp('best_rank_floor'), rare_pids=_RARE_PIDS, legacy_uids=_legrec,
    protected_pids=keep_config.protected_pids(), cf=cf)
print('  %-18s %-5d %s   (LAW bucket 2c re-derived: a piled copy that would beat your best of a stage after evolving)'
      % ('comb-up (law)', len(_il_cu), chk('comb-up (law)', len(_il_cu))))
for _u, _lg, _st, _rk, _why in _il_cu[:6]:
    print('     ! %s %s: %s' % (rows[_u]['species_name'], _u, _why))
# THE SHINY LADDER'S HOLD (LAW "Shiny ladder"), re-derived without refresh_evolve_shiny.compute_target -- the function the
# engine and preflight_transfer mark it from. The shiny line above judges only the top-N cap, and _lawcheck explains
# any piled shiny as "over the shiny cap", so a spare that earns a shiny spot one stage up could be piled unseen.
_il_dex = {p['speciesId']: p.get('dex') for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
_il_reach = (_PU_GRAPH[4] if '_PU_GRAPH' in globals() else {})
def _il_next(r):
    _l = _pu_later(r)
    _l = set(_l or ())
    return {t for t in _l if not any(t in _il_reach.get(s, ()) for s in _l if s != t)}
def _il_shcap(t):
    return keep_config.species_cap('shiny', _il_dex.get(t), keep_config.cap('shiny'))
def _il_shpcap(t):
    _c = _il_shcap(t)
    return _c if keep_config.species_cap('shiny', _il_dex.get(t), None) is not None else min(_c, keep_config.cap('shiny_plain'))
_il_sh = _il.shiny_ladder_violations(
    _crows, ps, own_of=lambda r: _sh_pvid(r['species_name'], r.get('form') or 0), next_of=_il_next,
    can_evolve=lambda r: bool(_pu_later(r)), cap_of=_il_shcap, plain_cap_of=_il_shpcap, floor_iv=keep_config.shiny_floor_iv(),
    is_collectible=lambda r: bool(_scoll(r) - {('shadow', 1)}), protected_pids=keep_config.protected_pids())
print('  %-18s %-5d %s   (LAW shiny ladder re-derived: a spare shiny that earns a spot one stage up is held)'
      % ('shiny ladder (law)', len(_il_sh), chk('shiny ladder (law)', len(_il_sh))))
for _u, _why in _il_sh[:6]:
    print('     ! %s %s: %s' % (rows[_u]['species_name'], _u, _why))

print('\nLAYER 3  pile vs every KEEP tagset')
# A tagset file that is MISSING or empty used to make this loop (and audit_tags_membership) pass
# vacuously -- no file, no overlap, no signal. The pile is pushed from these files, so an absent one
# is a real defect (build_tagsets swallows FileNotFoundError on its inputs and leaves the PREVIOUS
# run's file, or none, on disk).
EXPECTED = ('Hundo', 'Nundo', 'Traded_by_E+F', 'XXL',
            'Legacy_Moves', 'Evolve_Once', 'Evolve_Twice',   # GL_IV/UL_IV/Evolve_1/2/Event retired 2026-09-09; Evolve_Next -> Evolve_Once (the fold, 2026-09-29)
            'Best_GL', 'Best_UL', 'Best_ML')                 # rule 15d (2026-09-23)

def _evolve_tag_legitimately_empty(tag):
    """An evolve tag may be EMPTY (the worth-it and candy rules, 2026-09-17): the file must still exist, and since the fold
    (2026-09-29) empty is allowed only when no row of the ONE advice table, evolve_advice.json, carries that tag -- and
    the table holds every promise (a keeper with an evolve_1 / evolve_2 reason and no row means the table is short)."""
    import json as _j
    # A DEFINITIONAL tag the bag has nobody for is legitimately empty (2026-09-26, a second account with no E+F trades
    # FAILed 'missing/empty Traded_by_E+F'). The file must still exist; empty is allowed only when the rule matches nobody.
    import keep_config as _kcx
    _own = {o.lower() for o in _kcx.origin_owners()}
    _nobody = {'Traded_by_E+F': lambda r: (r.get('is_lucky') == 1 or r.get('is_traded') == 1 or r.get('is_traded_flag_v2') == 1)
                                          and (r.get('original_owner_name') or '').strip().lower() in _own,
               'Hundo': lambda r: (r.get('iv_total') or 0) == 45,
               'Nundo': lambda r: bool(r.get('is_zero')) and bool(r.get('pokemon_id'))}.get(tag)
    if _nobody is not None:
        return not any(_nobody(r) for r in rows.values())
    import granular_tags as _gtx                                 # (2026-09-29) the advice table decides, not the reasons
    _t = {_gtx.filename(x)[:-4]: x for x in _gtx.EVOLVE_TAGS}.get(tag)
    if not _t:
        return False
    try:
        _adv = _j.load(open(_gtx.EVOLVE_ADVICE, encoding='utf-8'))
    except Exception:
        return False                                            # no table proves nothing
    if not isinstance(_adv, dict) or any(set(v or ()) & {'evolve_1', 'evolve_2'} and k not in _adv for k, v in pol.items()):
        return False                                            # a promise with no row: the table is short, not "nobody"
    return not any(isinstance(e, dict) and _t in (e.get('tags') or ()) for e in _adv.values())
_absent = [t for t in EXPECTED
           if not os.path.exists(os.path.join(TD, t + '.txt'))
           or (not open(os.path.join(TD, t + '.txt')).read().split() and not _evolve_tag_legitimately_empty(t))]
print('  %-18s %-5d %s   %s' % ('missing/empty tags', len(_absent), chk('tagset present', len(_absent)),
                                ', '.join(_absent) or ''))
bad = 0
for fp in sorted(glob.glob(os.path.join(TD, '*.txt'))):
    nm = os.path.basename(fp)
    if nm in ('Transfer.txt', '6_Transfer.txt'):
        continue
    i = ps & set(open(fp).read().split())
    if i:
        bad += 1
        print('   OVERLAP %s: %d' % (nm, len(i)))
print('  %-18s %-5d %s' % ('overlaps', bad, chk('tagset overlap', bad)))

print('\nLAYER 4  engine bookkeeping')
leak = [u for u in ps if pol.get(u)]
print('  %-18s %-5d %s' % ('tagged w/ reason', len(leak), chk('keep-reason leak', len(leak))))
tot = len(pol) + len(ps)
okacct = (tot == len(rows))
if not okacct:
    FAILS.append('accounting')
print('  accounting: %d keep + %d pile = %d vs in_bag %d  %s' % (len(pol), len(ps), tot, len(rows), 'OK' if okacct else '*** FAIL ***'))

print('\nLAYER 5  variant integrity (nothing unique culled)')
# ident() decides whether a culled SPECIAL still has a kept same-variant copy. It used to omit two of
# the axes its own special() tests -- form-ENCODED costumes and location cards -- so a costume/loc-card
# mon ALIASED onto a plain sibling: 381 in-bag rows are special only via those two axes, 212 collide
# with a NON-special sibling, and 32 are the SOLE copy of their real variant (a loc-card Ponyta with 3
# plain same-ident siblings, a loc-card Zamazenta with 11, Genesect, Malamar, Landorus, Oshawott...).
# For all 32 the layer said "covered" and would have blessed releasing the only copy of that variant.
# bread mode is the raw Max mode (_bmn): every mode is its own variant (evolvable_forms.BREAD_MODES), so a piled
# BREAD_SPECIAL_MODE copy with no same-ident sibling IS the sole copy of its variant -- an ORPHAN FAIL, correctly.
ident = lambda r: (r['pokemon_id'], cf(r), r.get('fresh_costume') or 0, 0,
                   r.get('fresh_natural_art_bg') or 0, deco(r), _bmn(r),
                   1 if r.get('fresh_shiny') else 0, r.get('fresh_alignment') or 0,
                   (r.get('fresh_form') or 0) if is_costume_form(r.get('fresh_form') or 0) else 0,
                   0 if __import__('costume_forms').card_folds_into_costume(r)   # costume + background = one look (2026-09-24)
                   else r.get('fresh_loc_card_enum') or (1 if r.get('fresh_has_location_card') == 1 else 0))
# (2026-09-26) fused components hold no ladder slot: a copy held inside a Kyurem is not a "kept same-variant copy"
# (keep_policy's variant floor runs without it), so it never covers a piled visible special.
kept = collections.Counter(ident(r) for r in _crows if r['uid_hex'] not in ps)
special = lambda r: bool(r.get('fresh_shiny') or (r.get('fresh_costume') or 0)
                         or (r.get('fresh_natural_art_bg') or 0) or deco(r) or _bmn(r)
                         or is_costume_form(r.get('fresh_form') or 0) or r.get('fresh_has_location_card') == 1
                         or (r.get('fresh_alignment') or 0) == 1)
sp = [u for u in ps if u in rows and special(rows[u])]
# SHADOW RANK FLOOR (2026-09-24): a species whose best shadow ranks below pvp.shadow_rank_floor keeps NO shadow -- by law.
# So a piled shadow whose identity has no shadow in _shadow_keep (the re-derived law above) is lawful, not an orphan;
# the net still catches every cosmetic orphan and any shadow piled while a sibling of its identity IS kept.
_sh_ident_kept = {_sh_pvid(x['species_name'], x.get('form') or 0) for lst in _shp.values() for x in lst if x['uid_hex'] in _shadow_keep}
_floor_dropped = lambda r: (r.get('fresh_alignment') or 0) == 1 and _sh_pvid(r['species_name'], r.get('form') or 0) not in _sh_ident_kept
orph = [u for u in sp if kept.get(ident(rows[u]), 0) == 0 and not _floor_dropped(rows[u])]
print('  specials tagged %d | none with a kept same-variant copy: %d %s' % (len(sp), len(orph), chk('orphan variant', len(orph))))
for u in sorted(orph, key=lambda z: (-(rows[z].get('iv_total') or 0), z))[:10]:
    r = rows[u]
    print('     ! %s %d%% costume=%s cosform=%s artbg=%s loc=%s dmax=%s shiny=%s' % (
        r['species_name'], round((r['iv_total'] or 0) / 45 * 100), r.get('fresh_costume'),
        is_costume_form(r.get('fresh_form') or 0), r.get('fresh_natural_art_bg'),
        r.get('fresh_has_location_card'), _bmn(r), r.get('fresh_shiny')))
cnt = collections.Counter(r['pokemon_id'] for r in rows.values())         # whole bag -- the "you keep N" display below
pp = collections.Counter(rows[u]['pokemon_id'] for u in ps if u in rows)
# (2026-09-26) fused components hold no ladder slot: last-copy counts use VISIBLE copies only (keep_policy's dex_only
# rule runs without them), so a species / form whose only non-piled copy is held inside a Kyurem counts as WIPED.
_ps_v = [u for u in ps if u in rows and not keep_config.is_fused_component(rows[u])]
_cnt_v = collections.Counter(r['pokemon_id'] for r in _crows)
_pp_v = collections.Counter(rows[u]['pokemon_id'] for u in _ps_v)
w = [p for p, n in _pp_v.items() if _cnt_v[p] == n]
if keep_config.line_pool_all():
    # EVERY-LINE POOLS (florandez 2026-09-26): a species / form may leave the bag while its LINE keeps its best copies
    # (the Pokedex is lifetime). The loss that matters is a whole POOL wiped: every copy of (line, look, gender) piled.
    import pattern_pools as _ppx
    _pkx = lambda r: _ppx.pool_key(r['pokemon_id'], r['species_name'], r.get('form') or 0, r.get('gender'))
    _pcnt = collections.Counter(_pkx(r) for r in _crows if _pkx(r))
    _ppil = collections.Counter(_pkx(rows[u]) for u in _ps_v if _pkx(rows[u]))
    _pooled_pids = {rows[u]['pokemon_id'] for u in _ps_v if _pkx(rows[u])}
    w = [p for p in w if p not in _pooled_pids] + [k for k, n in _ppil.items() if _pcnt[k] == n]
print('  %-18s %-5d %s' % ('species wiped', len(w), chk('species wiped', len(w))))
fc = collections.Counter((r['pokemon_id'], cf(r)) for r in _crows)
fp2 = collections.Counter((rows[u]['pokemon_id'], cf(rows[u])) for u in _ps_v)
fw = [k for k, n in fp2.items() if fc[k] == n]
if keep_config.line_pool_all():
    fw = [k for k in fw if not any(_pkx(rows[u]) for u in _ps_v if (rows[u]['pokemon_id'], cf(rows[u])) == k)]
print('  %-18s %-5d %s   (Unown letters / regional colors)' % ('FORMS wiped', len(fw), chk('forms wiped', len(fw))))
for k in sorted(fw)[:8]:
    u = sorted([x for x in ps if x in rows and (rows[x]['pokemon_id'], cf(rows[x])) == k])[0]
    print('     ! %s form=%s' % (rows[u]['species_name'], k[1]))

print('\nLAYER 6  trophy slot exemptions in force')
hs = [r for r in rows.values() if r['iv_total'] == 45 and 'variant_floor' in pol.get(r['uid_hex'], [])]
ns = [r for r in rows.values() if r['iv_total'] == 0 and 'variant_floor' in pol.get(r['uid_hex'], [])]
print('  %-18s %-5d %s' % ('hundos in floor', len(hs), chk('hundo slot', len(hs))))
print('  %-18s %-5d %s' % ('nundos in floor', len(ns), chk('nundo slot', len(ns))))

print('\nLAYER 7  PvP rank sanity on tagged')
# READY_RANK and the viability margin are keep_config values, not literals -- raising ready_rank in the
# dashboard used to silently shrink this layer's coverage (audit_tags_membership already reads it live).
RR = keep_config.pvp('ready_rank')
VM = keep_config.pvp('viability_margin')
# The CPM table used to be REGEX-SCRAPED out of compute_all_ranks.py's source text here --
# duplication with extra steps, and it would break silently the moment that file stopped
# holding a literal. It now comes from cpm_table.py, the single source of truth (defect D4).
from cpm_table import CPM, GL_CAP, UL_CAP, MAX_LEVEL_IDX
BS = {p['speciesId']: p['baseStats'] for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
def mcp(st):
    b = BS.get(st or '')
    return max(10, math.floor((b['atk'] + 15) * math.sqrt(b['def'] + 15) * math.sqrt(b['hp'] + 15) * CPM[MAX_LEVEL_IDX] ** 2 / 10)) if b else 0
t5 = [u for u in ps if u in rows and ((rows[u].get('gl_rank') or 999) <= RR or (rows[u].get('ul_rank') or 999) <= RR)]
viol = 0
# A pile mon with a top-RR rank is lawful when that rank is NOISE (the stage never reaches the cap) or when THIS COPY
# can never play it (over the cap there now, or after evolving at its true level -- user 2026-09-30: "Why would I keep
# any GL and UL pokemon that cant participate?"). The play test is pvp_iv_rule.plays(), the engine's own rule 15b
# (every chain stage; unknown data => fits => a violation, never a pass).
from pvp_iv_rule import plays as _l7_plays
for u in sorted(t5, key=lambda z: (-(rows[z].get('iv_total') or 0), z)):
    r = rows[u]
    gl = mcp(r.get('gl_stage')) if (r.get('gl_rank') or 999) <= RR else None
    ul = mcp(r.get('ul_stage')) if (r.get('ul_rank') or 999) <= RR else None
    noise = (gl is None or gl <= GL_CAP + VM) and (ul is None or ul <= UL_CAP + VM)
    can = [lg for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)) if _l7_plays(r, lg, cap, BS, RR) is not None]
    good = noise or not can
    if not good:
        viol += 1
    print('    %-13s GL#%-5s(stage max %s)  UL#%-5s(stage max %s)  %s' % (
        r['species_name'], r.get('gl_rank'), gl, r.get('ul_rank'), ul,
        'cap-unreachable -> rank is noise, OK' if noise else
        'over the cap at every top-%d stage -> this copy cannot play it, OK' % RR if good else
        '*** CAN PLAY %s, CHECK ***' % '/'.join(x.upper() for x in can)))
print('  %-18s %-5d %s' % ('rank<=%d violations' % RR, viol, chk('pvp rank', viol)))

print('\nLAYER 8  data quality (incomplete display reads)')
barecos = [r for r in rows.values() if (r.get('fresh_costume') or deco(r)) and not (r.get('form') or r.get('fresh_form'))]
tagged_bare = set(r['uid_hex'] for r in barecos) & ps
print('  costume/deco with blank form: %d | of those TAGGED: %d %s' % (len(barecos), len(tagged_bare), chk('bare-form tagged', len(tagged_bare))))
# WRITER-REGRESSION SENTINEL for the cosmetic columns the pile is judged on. fresh_natural_art_bg has
# NO writer today (0 non-zero rows bag-wide -- which is also why the 'art bg' layer above is vacuous),
# so a NULL there cannot currently hide a keeper and must NOT deadlock the gate. The moment a writer
# lands (cross-package X6) the column goes live, and an UNREAD value on a mon in the irreversible pile
# becomes exactly the "NULL protection input = PROTECTED" case -- so this arms itself automatically.
for _col, _rel in (('fresh_natural_art_bg', lambda r: True),
                   ('fresh_loc_card_enum', lambda r: bool(r.get('fresh_has_location_card')))):
    _live = any((r.get(_col) or 0) for r in rows.values())
    _unread = [u for u in ps if u in rows and rows[u].get(_col) is None and _rel(rows[u])]
    _bagnull = sum(1 for r in rows.values() if r.get(_col) is None)
    if _live:
        print('  %-22s writer LIVE | bag NULL=%-4d | UNREAD in pile: %d %s'
              % (_col, _bagnull, len(_unread), chk('%s unread in pile' % _col, len(_unread))))
    else:
        print('  %-22s writer DORMANT (0 non-zero rows bag-wide) | bag NULL=%-4d | pile NULL=%d  INFO'
              % (_col, _bagnull, len(_unread)))

# DATA-COMPLETENESS, RE-DERIVED INDEPENDENTLY (2026-09-20). audit_invariants I1 had flagged
# 'data_incomplete' as the one keep axis NO consumer re-derives: keep_policy marks it, and every
# result-checking audit then reported PASS whether or not the rule had actually run. It is also the
# axis that protects the rows we know LEAST about, so a silent regression there is a silent release.
# The column list is read out of keep_policy's SOURCE rather than copied, so deleting the rule breaks
# this check loudly instead of making it vacuous; the KEEP itself is re-derived here from the live DB.
_kp_src = open(os.path.join('system', 'scripts', 'keep_policy.py'), encoding='utf-8').read()
_m = re.search(r'_PROT_COLS = \(([^)]*)\)', _kp_src)
if not _m:
    print('  protection columns: *** FAIL *** keep_policy._PROT_COLS is GONE -- the '
          '"never cull on incomplete data" rule cannot be re-derived')
    FAILS.append('_PROT_COLS missing from keep_policy')
else:
    _pc = re.findall(r"'([a-z0-9_]+)'", _m.group(1))
    _cols = set(next(iter(rows.values())).keys()) if rows else set()
    _gone = [c for c in _pc if c not in _cols]
    _null = {u for u, r in rows.items() if any(r.get(c) is None for c in _pc)}
    print('  protection columns: %d | rows with a NULL input: %d | of those TAGGED: %d %s'
          % (len(_pc), len(_null), len(_null & ps), chk('data_incomplete row tagged', len(_null & ps))))
    if _gone:
        print('    schema no longer carries %s %s' % (_gone, chk('data_incomplete column vanished', len(_gone))))

print('\n' + '=' * 72)
print('THE %d TAGGED FOR TRANSFER' % len(ps))
print('=' * 72)
# uid tiebreak: sorting a set on a non-unique key made two runs of an UNCHANGED DB print in different
# orders (three consecutive runs, three different md5s), so audit logs could not be diffed.
for u in sorted(ps, key=lambda z: (-(rows[z]['iv_total'] or 0) if z in rows else 0, z)):
    r = rows.get(u)
    if not r:
        continue
    # 'bg' used to be read from special_bg_id -- a RETIRED garbage column with no writer, whose
    # power-of-two read artifacts printed a phantom 'bg' attribute on 6 of the pile members.
    a = [x for x, c in (('shiny', r['fresh_shiny']), ('costume', r.get('fresh_costume')),
                        ('cos-form', is_costume_form(r.get('fresh_form') or 0)),
                        ('artbg', r.get('fresh_natural_art_bg')),
                        ('loc', r.get('fresh_has_location_card') == 1),
                        ('shadow', (r.get('fresh_alignment') or 0) == 1),
                        ('Dmax', evolvable_forms.max_axis(_bmn(r)) == 'dynamax'), ('Gmax', evolvable_forms.max_axis(_bmn(r)) == 'gigantamax')) if c]
    kc = cnt[r['pokemon_id']] - pp[r['pokemon_id']]
    print('  %-15s %3d%%  cp%-5s %-24s (you keep %d of this species)' % (
        r['species_name'], round((r['iv_total'] or 0) / 45 * 100), r['cp'], '+'.join(a) or 'plain', kc))

# storage capacity is READ LIVE, never hardcoded (standing rule; the old literal 5700 under-reported
# the free slots by 50 against the real 5750). UNKNOWN rather than a guess if the read fails.
try:
    _capn = int(json.load(open('player_state.json', encoding='utf-8'))['max_pokemon_storage'])
    print('\nbag %d / %d  (%d free)' % (len(rows), _capn, _capn - len(rows)))
except Exception as _e:
    print('\nbag %d / UNKNOWN  (player_state.json unreadable: %s)' % (len(rows), _e))

print('\nVERDICT: %s' % ('ALL LAYERS PASS -- pile is keeper-free' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)))
sys.exit(1 if FAILS else 0)
