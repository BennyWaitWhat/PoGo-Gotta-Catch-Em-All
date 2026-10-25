"""Verify EVERY server tag's membership against its definition -- correctness AND completeness.

For each definitional tag: does every member qualify, and is every qualifying mon a member?
Capped tags (XXL, GL/UL IV) are re-derived from their actual rule, both directions.
READ-ONLY.  python audit_tags_membership.py

LOCKDOWN 2026-09-02 -- one of the four gate audits full_audit.py greps. The passing verdict line MUST
keep the exact substring 'ALL TAG MEMBERSHIPS CORRECT'.
"""
import sqlite3, json, os, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
TD = os.path.join('system', 'analysis', 'tagsets')
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
# SELECT * IS DELIBERATE -- never narrow it (a missing column reads None and silently disarms a check).
_cur = con.execute('SELECT * FROM pokemon WHERE in_bag=1')
_cols = [d[0] for d in _cur.description]
rows = {}
for _t in _cur.fetchall():
    _d = dict(zip(_cols, _t))
    rows[_d['uid_hex']] = _d
try:
    from costume_forms import is_costume_form
except Exception:
    is_costume_form = lambda f: False
import keep_config

def load(name):
    p = os.path.join(TD, name + '.txt')
    return set(x for x in open(p).read().split() if x) if os.path.exists(p) else set()

FAILS = []
def verdict(tag, wrong, missing, note=''):
    bad = len(wrong) + len(missing)
    if bad:
        FAILS.append(tag)
    print('  %-16s members=%-5d  non-qualifying=%-4d  missing=%-4d  %s %s' % (
        tag, len(load(tag.replace(' ', '_'))), len(wrong), len(missing),
        'OK' if not bad else '*** FAIL ***', note))
    # sorted, not set-iteration order: two runs of an unchanged DB must print the same sample, or the
    # audit logs cannot be diffed against each other.
    for u in sorted(wrong)[:4]:
        r = rows.get(u, {})
        print('       non-qualifying: %s %s%%' % (r.get('species_name'), round((r.get('iv_total') or 0) / 45 * 100)))
    for u in sorted(missing)[:4]:
        r = rows.get(u, {})
        print('       MISSING: %s %s%%' % (r.get('species_name'), round((r.get('iv_total') or 0) / 45 * 100)))

def deco(r):
    d = r.get('costume_decoration_id')
    return d if (d and str(d) != '0') else 0

print('=' * 78)
print('TAG MEMBERSHIP AUDIT  (bag %d)' % len(rows))
print('=' * 78)

# Every capped rule below is re-derived from the LIVE keep_config. If the tagsets on disk were built
# from a different config the comparison is meaningless in BOTH directions, so say so. audit_cull owns
# the hard stale gate; here it is a banner so the tag-vs-rule detail still prints for diagnosis.
try:
    _pmt = os.path.getmtime(os.path.join(TD, 'Transfer.txt'))
    if os.path.getmtime('keep_config.json') > _pmt + 5:
        print('\n*** NOTE: keep_config.json is NEWER than the tagsets -- the capped-tag rules below are')
        print('*** re-derived from a config that did not build them. Re-run keep_policy + build_tagsets.')
except OSError:
    pass

# A tag file that is MISSING or empty made every check for it pass vacuously (members=0, non-qualifying
# 0, OK) -- verified by deleting six of them. build_tagsets swallows FileNotFoundError on its inputs and
# leaves the PREVIOUS run's file (or none) on disk, and prune_tags then pushes whatever is there to the
# phone, so an absent/empty tagset is a real defect and never a pass.
print('\nTAGSET FILES PRESENT')
EXPECTED = ('Hundo', 'Nundo', 'Traded_by_E+F', 'XXL',
            'Legacy_Moves', 'Transfer',   # Event retired 2026-09-09; the five evolve tags may be empty -- each is re-derived and set-compared below (2026-09-29)
            'Best_GL', 'Best_UL', 'Best_ML')   # rule 15d (2026-09-23): every species has a ranked non-shadow copy -> never empty

def _tag_legitimately_empty(tag):
    """A DEFINITIONAL tag the bag has nobody for is legitimately empty (2026-09-26, a second account with no E+F trades
    FAILed 'missing/empty Traded_by_E+F'). The file must still exist; empty is allowed only when the rule matches nobody."""
    import keep_config as _kcx
    _own = {o.lower() for o in _kcx.origin_owners()}
    _nobody = {'Traded_by_E+F': lambda r: (r.get('is_lucky') == 1 or r.get('is_traded') == 1 or r.get('is_traded_flag_v2') == 1)
                                          and (r.get('original_owner_name') or '').strip().lower() in _own,
               'Hundo': lambda r: (r.get('iv_total') or 0) == 45,
               'Nundo': lambda r: bool(r.get('is_zero')) and bool(r.get('pokemon_id'))}.get(tag)
    return _nobody is not None and not any(_nobody(r) for r in rows.values())
_absent = [t for t in EXPECTED if not load(t)
           and not (os.path.exists(os.path.join(TD, t + '.txt')) and _tag_legitimately_empty(t))]
# an EMPTY Transfer.txt is legitimate when keep_policy itself produced it (provenance pile_count=0, sha of nothing)
try:
    import hashlib as _h
    _prov = json.load(open('system/analysis/pile_provenance.json', encoding='utf-8'))
    if ('Transfer' in _absent and _prov.get('pile_count') == 0
            and _prov.get('pile_sha256') == _h.sha256(open(os.path.join(TD, 'Transfer.txt'), 'rb').read()).hexdigest()):
        _absent.remove('Transfer'); print('  Transfer.txt is EMPTY by keep_policy (pile_count=0, sha matches) -- allowed')
except Exception:
    pass
if _absent:
    FAILS.append('missing/empty tagsets')
print('  missing or empty: %d %s  %s' % (len(_absent), 'OK' if not _absent else '*** FAIL ***', ', '.join(_absent)))
# RETIRED tags (2026-09-09) must have NO tagset file -- a leftover file is a stale producer prune would push.
import granular_tags as _gt
# THE FOLD (2026-09-29): its names, and every Stop tag by prefix, are retired by this audit's own word, not only the registry's
_FOLD_RETIRED = ('Evolve Next', 'Stop at Mid Stage', 'Evo Best Gated', 'Evolve Shiny', 'Evolve Shiny Gated', 'Evolve for Size',
                 'Evo Best GL', 'Evo Best UL', 'Evo GL Rank 1-5', 'Evo UL Rank 1-5')   # THE SECOND FOLD (2026-09-30)
_retired_files = sorted({t for t in set(_gt.RETIRED_TAGS) | set(_FOLD_RETIRED) if os.path.exists(os.path.join(TD, _gt.filename(t)))}
                        | {f[:-4].replace('_', ' ') for f in os.listdir(TD) if f.startswith('Stop_') and f.endswith('.txt')})
if _retired_files:
    FAILS.append('retired tag file present')
print('  retired tag files present: %d %s  %s' % (len(_retired_files), 'OK' if not _retired_files else '*** FAIL ***', ', '.join(_retired_files)))
# EMPTY-SET CONTRACT: every registered tag has a file (possibly empty) so prune can strip stale members.
_nofile = [t for t, (fn, _c) in _gt.registry().items() if not os.path.exists(os.path.join(TD, fn))]
if _nofile:
    FAILS.append('registered tag without file')
print('  registered tags without a file: %d %s  %s' % (len(_nofile), 'OK' if not _nofile else '*** FAIL ***', ', '.join(_nofile)))

print('\nDEFINITIONAL TAGS -- membership must match the rule exactly')

EVO5 = ('Evolve to Mid', 'Evolve to Final', 'Evolve Needs Item', 'Evolve Needs Task', 'Evolve for GL', 'Evolve for UL')   # THE evolve tags (2026-10-25)

def _evolve_labelled():
    """(2026-09-29) copies being told to evolve = the union of the evolve tag files: advice never sits beside one."""
    return set().union(*(load(t.replace(' ', '_')) for t in EVO5))


# (2026-09-26) fused components hold no ladder slot: a held component carries only the Legacy Moves fact tag,
# as the engine keeps it for 'fused' alone
_vis = {u: r for u, r in rows.items() if not keep_config.is_fused_component(r)}

# Hundo
t = load('Hundo'); q = {u for u, r in _vis.items() if (r['iv_total'] or 0) == 45}
verdict('Hundo', t - q, q - t)

# Nundo
t = load('Nundo'); q = {u for u, r in _vis.items() if r.get('is_zero') and r['pokemon_id']} - set(load('Transfer'))   # a duplicate nundo in the pile is not tagged (one per look, 2026-09-17)
verdict('Nundo', t - q, q - t)

# 'Event' RETIRED 2026-09-09 (native Event + Background chips). The pile set is still needed below.
pile = load('Transfer')

# Traded by E+F
own = set(o.lower() for o in keep_config.origin_owners())
t = load('Traded_by_E+F')
q = {u for u, r in _vis.items() if (r.get('is_lucky') == 1 or r.get('is_traded') == 1 or r.get('is_traded_flag_v2') == 1)
     and (r.get('original_owner_name') or '').strip().lower() in own}
verdict('Traded by E+F', t - q, (q - t) - pile)

print('\nCAPPED TAGS -- the RULE re-derived, both directions')
# These used to check ONE direction and ONE property: "every XXL member is size 5" (never the cap,
# never the missing side) and "every GL/UL member has rank<=READY_RANK" (never viability, never the
# missing side). A member build_tagsets adds that the engine does NOT keep passed cleanly as long as it
# was size-5 -- which is exactly how the 207th XXL member (a form-0 Voltorb grouped by raw form instead
# of cf) sat in the tag advertising a keeper the engine never kept.

# --- cf(): keep_policy's form-0 collapse, INCLUDING the _is_regional_code guard. Any (pid,form)-keyed
# cap must use it, or a species splits into a form-0 group and an explicit-base-form group and quietly
# gets DOUBLE the cap slots.
try:
    from pvp_iv_rule import pvid as _pvid
except Exception:
    _pvid = None
_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
def _is_regional_code(nm, f):
    return any(x in _pvid(nm, f) for x in _REGSUF) if _pvid else False
_bc = collections.defaultdict(collections.Counter)
for r in rows.values():
    _f = r.get('form') or 0
    _reg = ((r.get('form_region') or '')).strip().lower()
    if _f and _reg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], _f) \
            and not __import__('costume_forms').is_costume_form(_f):   # a costume is never a base form (2026-09-23)
        _bc[r['pokemon_id']][_f] += 1
_base = {p: c.most_common(1)[0][0] for p, c in _bc.items() if len(c) == 1}
cf = lambda r: (_base.get(r['pokemon_id'], r.get('form') or 0) if not (r.get('form') or 0) else r.get('form'))

# XXL (2026-09-23): the top-N by the GAME'S showcase POINTS per PvP identity (species + battle form; cosmetics fold),
# XXL badge only -- keep_policy rule 7, re-derived here with size_line.showcase_points.
import size_line as _sl
from pvp_iv_rule import pvid as _sc_pvid
import size_line as _slx
_SC_MIN = keep_config.showcase_weights()['min_points']
def _sc_ok(r):
    """A showcase WINNER (user 2026-09-23: "keep pokemon that score over 1000"): points >= min_points. An unknown
    template scores None -> protected (unknown data is never fodder)."""
    _p = _slx.best_points(r)   # evolution counts (2026-09-24)
    return _p is None or _p >= _SC_MIN
_g = collections.defaultdict(list)
for r in _vis.values():
    if (r.get('pokemon_size_category') or 0) == 5 and r.get('height_m') is not None and r.get('weight_kg') is not None and _sc_ok(r):
        _g[_sc_pvid(r['species_name'], r.get('form') or 0)].append(r)
t = load('XXL')
qx = set(_slx.xxl_keepers(list(_vis.values())))    # ONE SELECTION (2026-09-29): per species (+ per type during an XXL trim)
qx |= {x['uid_hex'] for _l in _g.values() for x in _l if _sl.best_points(x) is None} & t   # unknown template: not judged here
# EVO BEST GL / UL (rule 15e, 2026-09-24): pvp_combup.pick re-derived here; its tags are checked with the other evolve
# tags below (the fold, 2026-09-29).
import pvp_combup as _pcu
_cu = _pcu.pick_default(list(_vis.values()))
try:      # the engine's label decision (2026-09-24 split): now / gated -> an evolve tag + Evolve for GL/UL, hold -> none
    _cul = json.load(open(os.path.join('system', 'analysis', 'pvp_combup_labels.json'), encoding='utf-8'))
except (OSError, ValueError):
    _cul = {}             # (2026-09-29) missing = no labels: evolve_advice drops every pick, so the check below FAILs
if set(_cul) != set(_cu['gl']) | set(_cu['ul']):
    FAILS.append('pvp_combup_labels.json does not cover exactly the comb-up picks')
    print('  *** pvp_combup_labels.json covers %d uids, the picks are %d -- labels and rule disagree'
          % (len(_cul), len(set(_cu['gl']) | set(_cu['ul']))))
_notsize = {u for u in t if (rows.get(u, {}).get('pokemon_size_category') or 0) != 5}
verdict('XXL', (t - qx) | _notsize, (qx - t) - pile, '(size_line.xxl_keepers: best per species+battle form by showcase points >= %d%s, XXL only; non-XXL members: %d)' % (_SC_MIN, (' + top-%d per type (XXL TRIM)' % keep_config.cap('xxl_per_type')) if keep_config.cap('xxl_per_type') else '', len(_notsize)))

# PvP-IV keepers: pvp_iv_rule.qualifies is the keep rule; its LABEL is now the GL/UL Rank + Evo Rank tags
# ('GL IV'/'UL IV' retired 2026-09-09). Every qualifies() keeper must carry one of them -- this keeps the axis
# independently re-derived (audit_invariants I1.8) with the tags that actually exist.
RR = keep_config.pvp('ready_rank')
try:
    from pvp_iv_rule import qualifies as _pvpq, GL_CAP as _GLC, UL_CAP as _ULC
    _gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
    _BS = {p['speciesId']: p.get('baseStats', {}) for p in _gm['pokemon']}
    _GF, _UF = keep_config.pvp('gl_floor'), keep_config.pvp('ul_floor')
    for lg, _st, _rk, _fl, _cap in (('GL', 'gl_stage', 'gl_rank', _GF, _GLC),
                                    ('UL', 'ul_stage', 'ul_rank', _UF, _ULC)):
        q = {u for u, r in rows.items()
             if _pvpq(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'],
                      r[_st], r[_rk], _fl, _BS, r['cp'], _cap)}
        # an over-cap keeper gets no Rank chip (that chip claims this copy can play the league). Until 2026-09-23 it
        # was always its identity's Best GL/UL, which labelled it; Best GL/UL is USABLE-ONLY now (keep_policy 15d),
        # so an over-cap spread is no longer that league's Best -- a MISSING here is that case, and it is the
        # user's call how (or whether) to label it. The keep itself (rule 15b) is untouched.
        # (2026-09-30, THE SECOND FOLD) a later-stage spread wears '<league> 1-5 No Evolve', or the evolve tags when it is
        # the copy to evolve (Evolve for <league> beside the count -- its Best chip comes off then)
        t = load('%s_Rank_1-5' % lg) | load('%s_1-5_No_Evolve' % lg) | load('Best_%s' % lg) | _evolve_labelled()
        # OVER-CAP SPREADS CARRY NO LEAGUE CHIP (user 2026-09-23, on over-cap spreads: "why are they even tagged"):
        # a keeper none of whose rank-<=ready_rank stages it can still ENTER (pvp_iv_rule.fits, true level) needs no
        # GL/UL tag -- the chip would claim it can play. It stays KEPT (rule 15b; the 8-layer and fixture audits prove
        # that); it is listed here so it is never silent.
        from pvp_iv_rule import fits as _fits, chain_stage_ranks as _csr
        _oc = {u for u in q if u not in t
               and not any(_rk2 <= RR and _fits(rows[u], _st2, _cap, _BS) for _st2, _rk2 in _csr(rows[u], lg.lower()))}
        verdict('%s Rank tags' % lg, set(), (q - t) - pile - _oc,
                '(every pvp_iv_rule %s keeper that can still ENTER the league carries a %s Rank / %s 1-5 No Evolve / Best %s '
                '/ evolve tag; keepers=%d, over the cap and untagged by design=%d%s)'
                % (lg, lg, lg, lg, len(q), len(_oc), (': ' + ', '.join(sorted('%s %d%%' % (rows[u]['species_name'],
                   round((rows[u]['iv_total'] or 0) * 100 / 45)) for u in _oc))) if _oc else ''))
except Exception as _e:
    FAILS.append('GL/UL rule unavailable')
    print('  *** could not re-derive the GL/UL rule (%s) -- these tags are UNVERIFIED' % _e)

# Best GL / Best UL = keep_policy rule 15d (user 2026-09-23), re-derived independently: the best NON-shadow copy
# per PvP IDENTITY. GL / UL are USABLE ONLY (user 2026-09-23, "Best GL/UL must be able to enter the league"): a copy
# competes with a stage it can REACH (the engine's ONE evolution graph, a fact) and ENTER (pvp_iv_rule.fits, the ONE
# CP/level helper: its CP there at its TRUE level inside the cap), key (that stage reaches the cap first, its rank,
# uid_hex); a copy with none never wins. ML unchanged: (viable ml_stage first, ml_rank, uid_hex). Viability =
# pvp_iv_rule.maxcp > cap + VIABILITY_MARGIN exactly as keep_policy._viable.
try:
    from pvp_iv_rule import (maxcp as _mcp, GL_CAP as _G2, UL_CAP as _U2, ML_CAP as _M2, VIABILITY_MARGIN as _VM2,
                             pvid as _pv2, fits as _fits2)
    _gm2 = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
    _BS2 = {p['speciesId']: p.get('baseStats', {}) for p in _gm2['pokemon']}
    _via = lambda sid, cap: bool(sid) and _mcp(sid, _BS2) > cap + _VM2
    try:
        import keep_policy as _kp2
        _G2RAPH = _kp2.build_evo_graph(_gm2, {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']},
                                       with_all=True)
        _later2 = lambda r: _kp2.pvp_later_stages(r, _G2RAPH)
    except Exception as _e:
        print('  *** evolution graph unavailable (%s) -- Best GL/UL judged on the ranker\'s chain as it stands' % _e)
        _later2 = lambda r: None

    def _usable2(r, lg, cap):
        own, later, st = _pv2(r['species_name'], r.get('form') or 0), _later2(r), []
        for p in str(r.get(lg + '_chain_ranks') or '').split(';'):
            if ':' in p:
                try:
                    st.append((p.split(':')[0].strip(), int(p.split(':')[1].split('(')[0])))
                except ValueError:
                    pass
        if not st and r.get(lg + '_rank') is not None:
            st = [(r.get(lg + '_stage'), r.get(lg + '_rank'))]
        reach = [(s, k) for s, k in st if s and (s == own or later is None or s in later)]   # evolution counts everywhere (2026-09-24)
        if not any(_fits2(r, s, cap, _BS2) for s, _k in reach):
            return None
        ok = [(0 if _via(s, cap) else 1, k) for s, k in reach]
        return min(ok) if ok else None
    _grp = collections.defaultdict(list)
    for r in rows.values():
        if r.get('fresh_alignment') == 1 or keep_config.is_fused_component(r):
            continue                        # a fusion component holds no ladder slot (2026-09-26)
        _grp[_pv2(r['species_name'], r.get('form') or 0)].append(r)   # PvP identity (2026-09-23)
    for _lg, _rk, _st, _cap in (('GL', 'gl_rank', 'gl_stage', _G2), ('UL', 'ul_rank', 'ul_stage', _U2),
                                ('ML', 'ml_rank', 'ml_stage', _M2)):
        q = set()
        _BRF = keep_config.pvp('best_rank_floor')          # rule 15d best rank floor (2026-09-24): top 20% only
        from references import LEGENDARY_IDS as _LI, MYTHICAL_IDS as _MI, ULTRA_BEAST_IDS as _UI, PARADOX_IDS as _PI
        _RARE_M = _LI | _MI | _UI | _PI                     # legendaries: no rank floor (user 2026-09-24)
        for _l in _grp.values():
            if _lg in ('GL', 'UL'):
                _c = [(k, x) for x in _l for k in (_usable2(x, _lg.lower(), _cap),) if k is not None]
                if _c:
                    _bk, _bx = min(_c, key=lambda y: (y[0][0], y[0][1], y[1]['uid_hex']))
                    if _bk[1] <= _BRF or _bx['pokemon_id'] in _RARE_M:
                        q.add(_bx['uid_hex'])
                continue
            _c = [x for x in _l if x.get(_rk) is not None and (x.get(_rk) <= _BRF or x['pokemon_id'] in _RARE_M)]
            if _c:
                q.add(min(_c, key=lambda x: (0 if _via(x.get(_st), _cap) else 1, x[_rk], x['uid_hex']))['uid_hex'])
        if _lg == 'ML':                     # the Best ML chip skips hundos (2026-09-23) and Variant #1 (2026-10-25); the keep does not
            q = {u for u in q if (rows[u].get('iv_total') or 0) != 45} - load('Variant_#1')
        else:                               # (2026-09-30) the Best GL/UL chip comes off the copy told to Evolve for it
            q -= load('Evolve_for_%s' % _lg)
        t = load('Best_%s' % _lg)
        verdict('Best %s' % _lg, t - q, (q - t) - pile,
                '(best non-shadow copy per PvP identity -- species + battle form; winners=%d, winners in pile=%d)'
                % (len(q), len(q & pile)))
        if q & pile:
            FAILS.append('Best %s winner in the pile' % _lg)
            print('  *** %d Best %s winner(s) are in the Transfer pile' % (len(q & pile), _lg))
except Exception as _e:
    FAILS.append('Best GL/UL rule unavailable')
    print('  *** could not re-derive Best GL/UL (%s) -- these tags are UNVERIFIED' % _e)

print('\nSOURCE-BACKED TAGS')
# Legacy Moves: every member must appear in legacy_accurate.json (list of {uid_hex: ...} records --
# an earlier version parsed it as a dict/flat list and silently read 0 entries).
# AN UNREADABLE OR EMPTY SOURCE USED TO BE A PASS: the except branch never touched FAILS, and the
# `leg and` guard made `wrong` empty whenever leg was empty, so a corrupt legacy_accurate.json printed
# 'Legacy Moves members=336 source=0 not-in-source=0 missing=0 OK' and the gate went green. That is the
# "VERIFIED over an EMPTY comparison" shape verify_tags_live.py already closed for itself.
leg, _legerr = set(), None
try:
    la = json.load(open('legacy_accurate.json', encoding='utf-8'))
    if isinstance(la, list):
        leg = {e['uid_hex'] if isinstance(e, dict) else e for e in la}
    elif isinstance(la, dict):
        leg = set(la.keys())
except Exception as e:
    _legerr = e
    print('   (could not read legacy_accurate.json: %s)' % e)
    FAILS.append('Legacy Moves source unreadable')
if _legerr is None and not leg:
    FAILS.append('Legacy Moves source empty')
    print('   *** legacy_accurate.json holds 0 records -- the comparison below would be vacuous')
t = load('Legacy_Moves')
wrong = {u for u in t if u not in leg}          # no `leg and` guard: an empty source must FAIL, not pass
inbag_leg = {u for u in leg if u in rows}
missing = (inbag_leg - t) - pile
bad = len(wrong) + len(missing)
if bad:
    FAILS.append('Legacy Moves')
print('  %-16s members=%-5d  source=%-5d  not-in-source=%-4d  missing=%-4d  %s' % (
    'Legacy Moves', len(t), len(leg), len(wrong), len(missing), 'OK' if not bad else '*** FAIL ***'))
for u in sorted(wrong)[:3]:
    print('       not-in-source: %s' % rows.get(u, {}).get('species_name'))
for u in sorted(missing)[:3]:
    print('       MISSING: %s' % rows.get(u, {}).get('species_name'))

print('\nEVOLVE TAGS (2026-09-29) -- one advice per kept copy, re-derived both directions')
# THE FOLD (user 2026-09-29: "I either evolve once or evolve twice" + "I also like to see the separate PVP ones"). Every
# producer is called HERE -- never read from evolve_advice.json, which is then checked against this. When a copy is in
# several, the first fixes its target: (1) the engine's promises (policy_reasons evolve_1 / evolve_2 + promises.json),
# (2) the PvP comb-ups (the pick above; pvp_combup_labels.json now / gated, hold = no tag), (3) the shiny upgrades
# (refresh_evolve_shiny.compute_target), (4) the showcase picks (sync_evolve_size.picks, each copy's best score); a
# comb-up also adds its leagues. Tag: a gate on ANY stage of the way (evolvable_forms.gate_reason -- Happiny -> Chansey
# -> Blissey is gated at Chansey) -> Evolve Needs Item (every gate an item / lure) or Evolve Needs Task, else Evolve to Final
# (every target ends its line on the engine's graph) or Evolve to Mid (2026-10-25: where it ends, true after it too); + Evolve
# for GL / UL per comb-up league. The WAY is keep_policy's ONE graph (granular_tags.path_between only where that graph
# has none). Never a pile mon, never a fused component.
_adv, _notg = None, set()
try:
    import keep_policy as _kpe, evolvable_forms as _efe, refresh_evolve_shiny as _res, sync_evolve_size as _ses
    from pvp_iv_rule import pvid as _pve
    _pol = json.load(open(os.path.join('system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))
    _prom = json.load(open(os.path.join('system', 'analysis', 'promises.json'), encoding='utf-8'))
    _rch = _kpe.build_evo_graph(json.load(open('pvpoke_gamemaster.json', encoding='utf-8')),
                                {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']}, with_all=True)[4]

    def _way(a, b):
        """The stages from a (exclusive) to b (inclusive) in the engine's graph; None when it shows no way."""
        if b not in _rch.get(a, ()):
            return None
        return [m for m in _rch[a] if m != b and b in _rch.get(m, ())] + [b]
    _adv = {}

    def _put(u, tg, src, lgs=(), gated=False):
        if u not in _vis or u in pile:
            return
        tg = [tg] if isinstance(tg, str) else [x for x in (tg or ()) if x]
        if not tg:
            _notg.add(u)                                # an evolve advice with no target would carry no evolve tag
            return
        if u not in _adv:
            own = _pve(_vis[u]['species_name'], _vis[u].get('form') or 0)
            ws = {x: _way(own, x) or _gt.path_between(own, x) for x in tg}
            st = [len(w) for w in ws.values() if w]
            _gk = [g for x in tg for s in (ws[x] or [x]) for g in (_efe.gate_reason(s) or [])]
            _adv[u] = {'targets': tg, 'source': src, 'leagues': set(),
                       'steps': min(st) if st else (2 if 'evolve_2' in (_pol.get(u) or ()) else 1),
                       'gated': bool(gated) or bool(_gk),
                       'item': bool(_gk) and all(g in ('evolutionItemRequirement', 'lureItemRequirement') for g in _gk),
                       'final': all(not _rch.get(x) for x in tg)}
        _adv[u]['leagues'] |= set(lgs)
    for u, v in _pol.items():                           # 1. the engine's promises
        if set(v or ()) & {'evolve_1', 'evolve_2'}:
            _put(u, _prom.get(u), 'promise')
    for u in sorted(set(_cu['gl']) | set(_cu['ul'])):   # 2. the PvP comb-ups (one stage per copy, in both leagues)
        if (_cul.get(u) or {}).get('status') in ('now', 'gated'):
            _put(u, (_cu['gl'].get(u) or _cu['ul'].get(u))[0], 'combup', [lg for lg in ('gl', 'ul') if u in _cu[lg]],
                 _cul[u]['status'] == 'gated')
    _sd, _sg = {}, {}
    for u in _res.compute_target(detail=_sd, gated=_sg):   # 3. the shiny upgrades, then the ones the game gates
        _put(u, _sd.get(u), 'shiny')
    for u, v in _sg.items():
        _put(u, (v or {}).get('target'), 'shiny', gated=True)
    _big = {}
    for e in _ses.picks(pile)[1]:                       # 4. the showcase picks: one branch per copy, its best score
        if e['uid'] not in _big or (e['score_after'] or 0) > (_big[e['uid']]['score_after'] or 0):
            _big[e['uid']] = e
    # a showcase pick never sits on a copy another bucket will not give up (the producer's rule since 2026-09-29, after
    # the label law caught an only-Floette-Orange XXL advised to Florges): the same block set, re-derived here
    _SIZE_BLOCK = {'protected', 'legacy', 'location_card', 'mighty', 'dex_only_copy', 'rarity', 'adventure_effect',
                   'shadow_best', 'hundo', 'nundo', 'fused'}
    _polz = json.load(open(os.path.join('system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))
    for u, e in _big.items():
        if _SIZE_BLOCK & set(_polz.get(format(int(u, 16), '016x')) or ()):
            continue
        _put(u, e['target'], 'size')
    for e in _adv.values():
        e['tags'] = ({('Evolve Needs Item' if e['item'] else 'Evolve Needs Task') if e['gated']
                      else ('Evolve to Final' if e['final'] else 'Evolve to Mid')}
                     | {'Evolve for ' + lg.upper() for lg in e['leagues']})
except Exception as _e:
    _adv = None
    FAILS.append('Evolve rule unavailable')
    print('  *** could not re-derive the evolve tags (%s) -- %s are UNVERIFIED' % (_e, ' / '.join(EVO5)))
if _adv is not None:
    for _tn, _why in zip(EVO5, ('(its target evolves again -- stop there; doable now)', '(its target ends the line; doable now)',
                                '(the game gates the way with an item or a lure only)',
                                '(the game gates the way with a task / buddy walk / time / move)',
                                '(beside the count: the copy to evolve for a better GL copy of a stage -- pvp_combup.pick)',
                                '(beside the count: the copy to evolve for a better UL copy of a stage -- pvp_combup.pick)')):
        _want = {u for u, e in _adv.items() if _tn in e['tags']}
        _have = load(_tn.replace(' ', '_'))
        verdict(_tn, _have - _want, _want - _have, _why)
    # '<league> 1-5 No Evolve' (THE SECOND FOLD, 2026-09-30): every kept copy a later stage ranks 1-5 (the ranker's chain,
    # a stage that reaches the cap, fits there at its true level, its form and gender can become it) that NO producer
    # above advises to evolve -- exactly those. An evolve tag and No Evolve never sit on one copy.
    for _lbl, _cap in (('GL', _gt.GL_CAP), ('UL', _gt.UL_CAP)):
        _mx = _gt._maxcp_fn()
        _via5 = lambda sid, _c=_cap: bool(sid) and _mx(sid) > _c + _gt.VIABILITY_MARGIN
        _want = set()
        for u, r in _vis.items():
            if u in pile:
                continue
            _ev5 = _gt.own_and_evo_rank(r, _lbl.lower(), viable=_via5, cap=_cap)[1]
            if _ev5 is not None and _ev5 <= 5 and u not in _adv:
                _want.add(u)
        _have = load('%s_1-5_No_Evolve' % _lbl)
        verdict('%s 1-5 No Evolve' % _lbl, _have - _want, _want - _have,
                '(a later stage ranks it 1-5 and it is NOT the copy to evolve -- no producer advises it)')
    if _notg:
        FAILS.append('evolve advice with no target')
        print('  *** %d kept copy(ies) advised to evolve with no target -- no evolve tag tells him: %s'
              % (len(_notg), ', '.join('%s %s' % (rows[u]['species_name'], u) for u in sorted(_notg)[:6])))
    # THE TABLE build_tagsets wrote (evolve_advice.json -- evolve_targets and the report read it) must say the same
    try:
        _aj = json.load(open(_gt.EVOLVE_ADVICE, encoding='utf-8'))
    except (OSError, ValueError) as _e:
        _aj = None
        print('  *** evolve_advice.json unreadable (%s)' % _e)
    _k = lambda e: (sorted(e.get('targets') or ()), e.get('steps'), bool(e.get('gated')), sorted(e.get('leagues') or ()),
                    e.get('source'), sorted(e.get('tags') or ()))
    _dis = [] if _aj is None else sorted(u for u in set(_adv) | set(_aj)
                                         if u not in _adv or u not in _aj or _k(_adv[u]) != _k(_aj[u]))
    if _aj is None or _dis:
        FAILS.append('evolve_advice.json disagrees with the re-derivation')
    print('  %-16s copies=%-5s  re-derived=%-4d  disagree=%-4d  %s' % ('evolve_advice', '?' if _aj is None else len(_aj),
          len(_adv), len(_dis), 'OK' if _aj is not None and not _dis else '*** FAIL ***'))
    for u in _dis[:4]:
        print('       %s %s: table %s / re-derived %s' % (rows.get(u, {}).get('species_name'), u,
              _k(_aj[u]) if u in _aj else '-', _k(_adv[u]) if u in _adv else '-'))
    # a shiny upgrade must BE a shiny (the producer reads is_shiny, this the fresh flag) -- was the Evolve Shiny check
    _nsh = {u for u, e in _adv.items() if e['source'] == 'shiny' and not rows[u].get('fresh_shiny')}
    print('  %-16s non-shiny=%d %s' % ('  -> shiny check', len(_nsh), 'OK' if not _nsh else '*** FAIL ***'))
    if _nsh: FAILS.append('shiny upgrade on a non-shiny')

print('\nWHAT-TO-DO TAGS (2026-09-26) -- advice on kept mons, re-derived both directions')
# POWER UP TO 1500 / 2500 (user 2026-09-29: "I also only want to power pokemon who are ranked in the top 100 of pvpoke"):
# own-stage rank <= keep_config pvp.action_rank in that league, the stage reaches the cap, CP inside it now, the species in
# pvpoke's top-N META for that league (pvp.power_up_meta_top; rankings-<cap>.json read HERE, by score; a shadow counts as
# '<id>_shadow' or '<id>'; N=0 = no gate), TRUE level (pvp_iv_rule.true_level, the ONE level) below the highest half-level
# <= L50 still inside the cap -- that level computed here from cpm_table. ONE per (league, stage) (2026-09-29): none when a
# candidate copy of the stage already sits at its best level, else the best rank, then the highest level, then uid. Never
# 2500 on a Great League keeper (Best GL, or own-stage GL rank <= ready_rank inside 1500). Fused components hold no slot.
# 2nd MOVE (user 2026-09-29: "I only want Rank 1-5 PVP pokemon to have their 2nd moves unlocked"): own-stage rank <=
# action_rank in a league it can ENTER, no second charged move; the meta gate only when pvp.unlock_meta_top > 0, judged in
# its best-ranked league (Great on a tie -- game_opportunities.second_moves' pick).
try:
    from pvp_iv_rule import true_level as _tl3, maxcp as _mcp3, pvid as _pv3, VIABILITY_MARGIN as _VM3, \
        GL_CAP as _GC3, UL_CAP as _UC3
    from cpm_table import CPM as _CPM3, MAX_LEVEL_IDX as _MLI3
    _BS3 = {p['speciesId']: p.get('baseStats', {}) for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
    _pol3 = json.load(open(os.path.join('system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))
    _cp3 = lambda b, r, i: max(10, int((b.get('atk', 0) + r['iv_atk']) * (b.get('def', 0) + r['iv_def']) ** 0.5
                                       * (b.get('hp', 0) + r['iv_sta']) ** 0.5 * _CPM3[i] ** 2 / 10))
    _AR3, _PMN, _SMN = keep_config.pvp('action_rank'), keep_config.pvp('power_up_meta_top'), keep_config.pvp('unlock_meta_top')
    _ML3 = {}                                        # (2026-09-29) league -> pvpoke speciesIds, best score first; None = no list
    for lg, cap in (('gl', _GC3), ('ul', _UC3)):
        try:
            _l3 = json.load(open(os.path.join('system', 'analysis', 'pvpoke_rankings', 'rankings-%d.json' % cap), encoding='utf-8'))
            _ML3[lg] = [x['speciesId'] for x in sorted(_l3, key=lambda x: -(x.get('score') or 0))] or None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _ML3[lg] = None
    # a gate that is ON with no list to read cannot honour "top 100": the tags are then unverified against his rule
    _nol = [lg for lg in ('gl', 'ul') if (_PMN or _SMN) and _ML3[lg] is None]
    if _nol:
        FAILS.append('pvpoke meta ranking unreadable')
        print('  *** pvpoke rankings unreadable or empty for %s -- the top-N meta gate cannot be checked' % ', '.join(_nol))

    def _meta3(r, own, lg, n):
        """In pvpoke's top-n for the league (2026-09-29); n=0 or no list = no gate."""
        if not n or _ML3[lg] is None:
            return True
        top = set(_ML3[lg][:n])
        return own in top or ((r.get('fresh_alignment') or 0) == 1 and own + '_shadow' in top)

    def _own3(r, lg):
        """Own-stage rank in lg when it is <= action_rank (2026-09-29), else None."""
        own, rk = _pv3(r['species_name'], r.get('form') or 0), r.get(lg + '_rank')
        return rk if r.get(lg + '_stage') == own and rk is not None and rk <= _AR3 else None
    _EVL = _evolve_labelled()                        # advice never beside an evolve label (the five files, 2026-09-29)
    _pc, _sm = collections.defaultdict(list), set()
    for u, r in _vis.items():
        own = _pv3(r['species_name'], r.get('form') or 0)
        b = _BS3.get(own)
        if u in pile or not b:
            continue
        _ok = [(lg, cap, _own3(r, lg)) for lg, cap in (('gl', _GC3), ('ul', _UC3))
               if _own3(r, lg) is not None and _mcp3(own, _BS3) > cap + _VM3
               and (r.get('cp') or 0) <= cap]        # a league it can ENTER (2026-09-26)
        if not r.get('move3') and _ok and _meta3(r, own, min(_ok, key=lambda x: x[2])[0], _SMN):
            _sm.add(u)
        if r.get('iv_atk') is None:
            continue
        for lg, cap, rk in _ok:
            if not _meta3(r, own, lg, _PMN):
                continue
            if lg == 'ul' and ('pvp_best_gl' in (_pol3.get(u) or ())
                               or (r.get('gl_stage') == own and (r.get('gl_rank') or 9999) <= RR and (r.get('cp') or 0) <= _GC3)):
                continue                                # powering a Great League keeper for Ultra burns it
            lv, top = _tl3(r, _BS3), [i for i in range(_MLI3 + 1) if _cp3(b, r, i) <= cap]
            if lv is not None and top:
                _pc[(lg, own)].append((rk, lv, 1 + max(top) / 2.0, u))
    _pu = {'gl': set(), 'ul': set()}
    for (lg, _o), lst in _pc.items():
        if all(lv < bl for _k, lv, bl, _u in lst):  # a copy of the stage at its best level satisfies it (2026-09-29)
            _pu[lg].add(min(lst, key=lambda x: (x[0], -x[1], x[3]))[3])   # best rank, then closest to done, then uid
    for lg, _tn in (('gl', 'Power Up to 1500'), ('ul', 'Power Up to 2500')):
        t = load(_tn.replace(' ', '_'))
        _pu[lg] -= _EVL
        verdict(_tn, t - _pu[lg], _pu[lg] - t, '(own-stage rank 1-%d, pvpoke top-%s, under the cap and below its best level; '
                'one per stage)' % (_AR3, _PMN or 'all'))
    # LAW: the two instructions must not contradict on screen -- no 'Power Up to 2500' on a copy wearing a GL chip
    _burn = load('Power_Up_to_2500') & (load('Best_GL') | load('GL_Rank_1-5'))
    print('  %-16s on a Best GL / GL Rank 1-5 copy=%d %s' % ('  -> 2500 law', len(_burn), 'OK' if not _burn else '*** FAIL ***'))
    if _burn: FAILS.append('Power Up to 2500 on a GL keeper')
    # LAW (user 2026-09-29), read off the FILES: no Power Up outside own-stage rank 1-N or the league's pvpoke top-N, no 2nd
    # Move outside own-stage rank 1-N (+ its top-N when unlock_meta_top is on) in both leagues
    _pvr = lambda u: _pv3(rows[u]['species_name'], rows[u].get('form') or 0)
    _out = {u for lg, _tn in (('gl', 'Power_Up_to_1500'), ('ul', 'Power_Up_to_2500')) for u in load(_tn)
            if u not in rows or _own3(rows[u], lg) is None or not _meta3(rows[u], _pvr(u), lg, _PMN)}
    _out |= {u for u in load('Unlock_2nd_Move') if u not in rows
             or not any(_own3(rows[u], lg) is not None and _meta3(rows[u], _pvr(u), lg, _SMN) for lg in ('gl', 'ul'))}
    print('  %-16s outside own-stage rank 1-%d or the pvpoke top-N (Power Up %s, 2nd Move %s)=%d %s' % (
          '  -> rank law', _AR3, _PMN or 'no gate', _SMN or 'no gate', len(_out), 'OK' if not _out else '*** FAIL ***'))
    if _out: FAILS.append('dust advice outside rank 1-%d / the pvpoke meta' % _AR3)
    t = load('Unlock_2nd_Move')
    _sm -= _EVL
    verdict('Unlock 2nd Move', t - _sm, _sm - t, '(own-stage rank 1-%d in a league it can enter%s, no second charged move)'
            % (_AR3, (', pvpoke top-%d' % _SMN) if _SMN else ''))
except Exception as _e:
    FAILS.append('Power Up / 2nd Move rule unavailable')
    print('  *** could not re-derive Power Up / Unlock 2nd Move (%s) -- these tags are UNVERIFIED' % _e)

print('\nTRANSFER -- must be disjoint from every keep tag')
# NOTE: build_tagsets subtracts the pile from every keep tag before writing, so for 10 of the 11 tags
# this can only fire if a file was hand-edited or written by something else. Evolve_Shiny.txt (written
# by refresh_evolve_shiny.py, not build_tagsets) is the one that can genuinely overlap. audit_cull's
# LAYER 3 runs the identical file comparison -- kept in both deliberately, since the two audits are run
# independently and either one alone must catch it.
bad = 0
for fp in sorted(os.listdir(TD)):
    if not fp.endswith('.txt') or fp in ('Transfer.txt', '6_Transfer.txt'):
        continue
    i = pile & load(fp[:-4])
    if i:
        bad += 1
        print('   OVERLAP %s: %d' % (fp, len(i)))
print('  overlaps=%d %s' % (bad, 'OK' if not bad else '*** FAIL ***'))
if bad: FAILS.append('transfer overlap')

print('\nDB MIRROR -- INFO ONLY, NOT GATED  (auth_tag_names lags until set_db_tags_from_files runs)')
# Deliberately not a FAIL: this audit runs BEFORE the sync, when the DB mirror legitimately still holds
# the previous cycle's tags. Labelled so it is not mistaken for a check that is passing.
mism = 0
for fp in sorted(os.listdir(TD)):
    if not fp.endswith('.txt') or fp.startswith('6_'):
        continue
    tag = fp[:-4].replace('_', ' ')
    files = load(fp[:-4])
    dbm = {u for u, r in rows.items() if tag in [x for x in (r.get('auth_tag_names') or '').split(';') if x]}
    if files != dbm:
        mism += 1
        print('   %-16s file=%-5d db=%-5d  file_only=%-4d db_only=%-4d' % (tag, len(files), len(dbm), len(files - dbm), len(dbm - files)))
print('  mismatched tags=%d %s' % (mism, '(in sync)' if not mism else '(sync/set_db pending -- informational)'))

print('\n' + '=' * 78)
print('VERDICT: %s' % ('ALL TAG MEMBERSHIPS CORRECT' if not FAILS else 'FAILURES: ' + ', '.join(sorted(set(FAILS)))))
sys.exit(1 if FAILS else 0)
