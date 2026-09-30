"""READ-ONLY fact-pack for the adversarial spot-audit: every keep-axis FACT about every pile mon,
emitted as JSON so a reviewing agent never has to write this SQL again.

Why (user 2026-08-31 "Why does the spot audit take so long?"): the spot-audit agent burned 440s -- 3-7x
every other auditor, and the critical path of the whole audit phase -- not because the data is big (5.7k
sqlite rows is nothing) but because an LLM was re-deriving the same schema knowledge and re-writing the same
SQL from scratch every run, across dozens of sequential tool calls. That work is deterministic, so it
belongs in a script.

DELIBERATELY INDEPENDENT: every fact here is derived straight from the DB columns. This does NOT import
keep_policy's decisions and does NOT read policy_reasons.json, so it cannot inherit the engine's
reasoning -- which is the entire point of an adversarial cross-check. It reports FACTS, never verdicts;
judging stays the agent's job. (The evolution GRAPH is imported from the engine: a hand-rolled copy of
it drifted from the real one on 15 live rows, and a wrong line graph is a wrong fact, not independence.)

    python _spotdata.py                 # JSON to stdout
    python _spotdata.py --out f.json    # write to a file + print the sweep summary

LOCKDOWN 2026-09-02. In --out mode the sweep summary is the ONLY thing printed, i.e. the only thing the
reviewing agent sees by default, and it used to omit costume, costume_form, decoration, art_bg, legacy,
rarity, protected, dex_only, xxs and evolve -- 9 of the 52 pile members carried costume_form:true and
the summary never said so, on the axis with the worst incident history. It also reported three
fabricated facts: 'buddy' read a column that does not exist (is_best_buddy does), 'deployed' rendered
NULL-unknown as a measured false on 43 of 52 pile members, and 'cull_v9' surfaced a May-30
decommissioned engine's verdict that reads KEEP on 31 of them.
"""
import sqlite3, json, collections, sys, math, re, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.'); sys.path.insert(0, 'system/scripts')
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
# SELECT * IS DELIBERATE -- never narrow it (a missing column reads None, its axis reads False, and the
# fact pack silently reports "no such axis" for every mon).
_cur = con.execute('SELECT * FROM pokemon WHERE in_bag=1')
_cols = [d[0] for d in _cur.description]
rows = [dict(zip(_cols, t)) for t in _cur.fetchall()]
by = {r['uid_hex']: r for r in rows}
TD = os.path.join('system', 'analysis', 'tagsets')
ps = set(x for x in open(os.path.join(TD, 'Transfer.txt')).read().split() if x)
from costume_forms import is_costume_form
import keep_config
import evolvable_forms   # BREAD_MODES / max_axis: the game's own Max-mode names
EF = set(o.strip().lower() for o in keep_config.origin_owners())
AE = keep_config.ae_pids()
import ae_moves as _aem                  # 2026-09-23: an Adventure Effect is a MOVE the specimen knows
_AE_MOVES = _aem.move_ids()              # was a hardcoded 7-pid tuple; the dashboard owns this roster
# (2026-09-26) fused components hold no ladder slot (user: "i think 2 are currently fused. So don't count those in the
# ladder."). A Reshiram/Zekrom HELD inside a fused Kyurem (keep_config.is_fused_component) is out of keep_policy's `rows`
# before ANY competition, so every rank / cap / Best GL/UL/ML / sibling list / last-copy count / form-0 vote below is
# taken without it. `by` (built above), _SID and the 'bag' count stay WHOLE-bag; a fused uid in the pile is still found
# and reported under axes.fused_component + sweeps.fused_component (must be 0 -- it can never be a pile candidate).
FUSED = {r['uid_hex'] for r in rows if keep_config.is_fused_component(r)}
rows = [r for r in rows if r['uid_hex'] not in FUSED]
# every gender-locked species in keep_policy.GENDER_TERMINALS. The old 3-pid tuple (Combee/Salandit/
# Burmy) told the reviewing agent that a female Ralts/Kirlia/Snorunt is not a gender-split keeper --
# 29 live mons.
GENDER_SPLIT = (280, 281, 361, 412, 415, 757)
iv = lambda r: (r['iv_total'] or 0)
pct = lambda r: round(iv(r) / 45 * 100)

# form-0 normalization (engine-identical rule, recomputed here rather than imported) -- INCLUDING
# keep_policy's _is_regional_code guard, without which a regional form code carrying a blank
# form_region can be elected the species' base form and the base-region copy collapses onto it.
from pvp_iv_rule import pvid
_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
def _is_regional_code(nm, f):
    return any(x in pvid(nm, f) for x in _REGSUF)
_bc = collections.defaultdict(collections.Counter)
for r in rows:
    fo = r.get('form') or 0
    reg = ((r.get('form_region') or '')).strip().lower()
    if fo and reg in ('', 'normal', 'kantonian', 'none', 'null') and not _is_regional_code(r['species_name'], fo) \
            and not is_costume_form(fo):   # a costume is never a base form (2026-09-23)
        _bc[r['pokemon_id']][fo] += 1
base = {p: c.most_common(1)[0][0] for p, c in _bc.items() if len(c) == 1}
cf = lambda r: (base.get(r['pokemon_id'], r.get('form') or 0) if not (r.get('form') or 0) else r.get('form'))
_SID = {r['uid_hex']: pvid(r['species_name'], r.get('form') or 0) for r in by.values()}   # memoized: pvid is hot; whole bag
_bmn = lambda r: r.get('fresh_bread_mode') or 0   # every Max mode is its own bundle (evolvable_forms.BREAD_MODES)
_deco = lambda r: (r.get('costume_decoration_id') not in (None, 0, '0', ''))
_topn = lambda l, n: sorted(l, key=lambda r: (-iv(r), -(r.get('cp') or 0), r['uid_hex']))[:n]
def _best_by(l, k):
    c = [x for x in l if x.get(k) is not None]
    return min(c, key=lambda x: x[k]) if c else None

# --- the four axes that were absent from every audit until 2026-09-02, re-derived here too so the
# reviewing agent can see them as facts (audit F1) ---------------------------------------------------
try:
    from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
    RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
    _RARE_SRC = 'references.py'
except Exception as _e:
    RARE_PIDS = set(); _RARE_SRC = 'UNAVAILABLE (%s) -- falling back to the NULL-prone is_* columns' % _e
try:
    _la = json.load(open('legacy_accurate.json', encoding='utf-8'))
    LEGACY = {(e['uid_hex'] if isinstance(e, dict) else e) for e in _la} if isinstance(_la, list) else set(_la)
    _LEG_SRC = 'legacy_accurate.json (%d records)' % len(LEGACY)
except Exception as _e:
    LEGACY = set(); _LEG_SRC = 'UNREADABLE (%s)' % _e
PROTECTED = keep_config.protected_pids()
SPREADS = keep_config.pvp_spread_keep()

# rarity ranking, same grouping as the engine: (pid, cf, shadow, bread-mode), shinies excluded (kept in
# full by the shiny rule so they never eat a rarity slot); rarity_keep_all pids (Mewtwo) have no cap.
_rare_of = lambda r: (r['pokemon_id'] in RARE_PIDS or r.get('is_legendary') or r.get('is_mythical')
                      or r.get('is_ultra_beast') or r.get('is_paradox'))
rarity_rank = {}
_rg = collections.defaultdict(list)
for r in rows:
    if not r.get('fresh_shiny') and _rare_of(r):
        _rg[(r['pokemon_id'], cf(r), 1 if r.get('fresh_alignment') == 1 else 0,
             r.get('fresh_bread_mode') or 0)].append(r)
_KA = keep_config.rarity_keep_all()
try:
    _LEG = {e['uid_hex'] for e in json.load(open('legacy_accurate.json', encoding='utf-8'))}
except Exception:
    _LEG = None
for _k, _l in _rg.items():
    _cap = len(_l) if _k[0] in _KA else keep_config.species_cap('rarity', _k[0], keep_config.cap('rarity'))
    if _k[2] == 1 and _k[0] not in _KA:            # shadow legendaries: caps.rarity_shadow (2026-09-29)
        _cap = min(_cap, keep_config.species_cap('rarity_shadow', _k[0], keep_config.cap('rarity_shadow')))
    _lad = keep_config.rarity_ladder(_k[0])             # league ladders (Mewtwo, 2026-09-26): kept by the shared rule
    _lk = (({x['uid_hex'] for x in _l} if _LEG is None else keep_config.rarity_ladder_keep(_l, _LEG, _lad)) if _lad else None)
    for i, x in enumerate(_topn(_l, len(_l))):
        rarity_rank[x['uid_hex']] = {'rank': i + 1, 'of': len(_l), 'cap': _cap,
                                     'keep_all_species': _k[0] in _KA or bool(_lk and x['uid_hex'] in _lk),
                                     'floor_iv': keep_config.rarity_floor_iv(),                    # 3-star floor (2026-09-13)
                                     'kept_by_floor': (x.get('iv_total') or 0) >= keep_config.rarity_floor_iv()}


def axes(r):
    """every keep axis as a raw fact -- no judgement about caps"""
    return {
        'hundo': iv(r) == 45, 'nundo': iv(r) == 0,
        'shiny': bool(r['fresh_shiny']),
        'costume': r.get('fresh_costume') or 0,
        'costume_form': bool(is_costume_form(r.get('fresh_form') or 0) or is_costume_form(r.get('form') or 0)),
        'decoration': _deco(r),
        'special_bg': 0,   # special_bg_id RETIRED -- garbage column, no writer (see keep_policy)
        'art_bg': r.get('fresh_natural_art_bg') or 0,
        'bread_mode': _bmn(r),           # raw Max mode -- evolvable_forms.BREAD_MODES names it, max_axis caps it
        'bread_mode_raw': r.get('fresh_bread_mode') or 0,
        'shadow': (r.get('fresh_alignment') or 0) == 1,
        'size_cat': r.get('pokemon_size_category') or 0,        # 5 = XXL, 1 = XXS
        'location_card': r.get('fresh_has_location_card') == 1,
        'loc_card_enum': r.get('fresh_loc_card_enum'),
        'mighty': r.get('fresh_is_strong') == 1,
        'traded': bool(r.get('is_traded') or r.get('is_traded_flag_v2')),
        'lucky': bool(r.get('is_lucky')),
        'original_owner': (r.get('original_owner_name') or '').strip(),
        'ef_origin': bool((r.get('is_lucky') == 1 or r.get('is_traded') == 1 or r.get('is_traded_flag_v2') == 1)
                          and (r.get('original_owner_name') or '').strip().lower() in EF),
        'ae_roster': (bool(_aem.known(r, _AE_MOVES)) if _AE_MOVES is not None else r['pokemon_id'] in AE)
                     or (r.get('adventure_effects_left') or 0) > 0,   # PER MON: knows the effect's move (2026-09-23)
        'rare_species': bool(_rare_of(r)),
        'fused_component': r['uid_hex'] in FUSED,   # held inside a fused Kyurem: no ladder slot, never a pile candidate
        'legacy_moves': r['uid_hex'] in LEGACY,
        'protected_pid': r['pokemon_id'] in PROTECTED,
        'pvp_spread_trophy': (r.get('iv_atk'), r.get('iv_def'), r.get('iv_sta')) in SPREADS,
        'unown': r['pokemon_id'] == 201,
        'gender_split_species': r['pokemon_id'] in GENDER_SPLIT or r['pokemon_id'] in evolvable_forms.GENDER_VARIANT_PIDS, 'gender': r.get('gender'),
        'gl_rank': r.get('gl_rank'), 'ul_rank': r.get('ul_rank'),
        'gl_stage': r.get('gl_stage'), 'ul_stage': r.get('ul_stage'),
        # TRI-STATE, not a bool. is_deployed is NULL on 1854 in-bag rows and on 43 of the 52 pile
        # members; rendering unknown as a measured `false` violated "NULL = PROTECTED" and the standing
        # rule that deployment must be read LIVE off the proto. True/False/None -- and the LIVE truth
        # comes from preflight_transfer's gym read, never from this column.
        'deployed': (True if r.get('is_deployed') == 1 else (False if r.get('is_deployed') == 0 else None)),
        'deployed_source': 'DB column (unreliable) -- live truth is preflight_transfer gym read',
        # is_best_buddy is the real column ('is_buddy' does not exist in the schema, so this key used to
        # report false for all 52 while 2 of them are in fact best buddies). NOT a keep axis: the
        # best_buddy keep reason was removed 2026-06-07.
        'best_buddy_NOT_A_KEEP_AXIS': bool(r.get('is_best_buddy')),
        # decommissioned May-30 engine; reads KEEP on 31 of 52 pile members. Kept under an explicit name
        # so nobody mistakes it for a current verdict.
        'cull_v9_stale_legacy_column': r.get('cull_decision_v9'),
    }


# --- XXL showcase ranking, recomputed independently -------------------------------------------------
# grouped by cf(), NOT the raw form: the engine keys on cf and the raw key produced a 207th "keeper"
# (a form-0 Voltorb whose cf is 1047). uid tiebreak mirrors keep_policy so a tie cannot reshuffle.
XW = keep_config.showcase_weights()
xxl_rank = {}                                   # XXL showcase rank (2026-09-23): per PvP identity, XXL only, the game's points
import size_line as _sl
from pvp_iv_rule import pvid as _sd_pvid
_g = collections.defaultdict(list)
_SC_MIN = keep_config.showcase_weights()['min_points']
for r in rows:
    if (r.get('pokemon_size_category') or 0) == 5 and r.get('height_m') is not None and r.get('weight_kg') is not None \
            and (_sl.best_points(r) is None or _sl.best_points(r) >= _SC_MIN):   # evolution counts (2026-09-24)
        _g[_sd_pvid(r['species_name'], r.get('form') or 0)].append(r)
_XK = _sl.xxl_keepers(rows)
for k, lst in _g.items():
    gh = max((x.get('height_m') or 0) for x in lst) or 1
    gw = max((x.get('weight_kg') or 0) for x in lst) or 1
    sc = lambda x: (_sl.best_points(x) if _sl.best_points(x) is not None else
                    XW['height'] * ((x.get('height_m') or 0) / gh) + XW['weight'] * ((x.get('weight_kg') or 0) / gw) + XW['iv'] * (iv(x) / 45))
    for i, x in enumerate(sorted(lst, key=lambda y: (-sc(y), y['uid_hex']))):
        xxl_rank[x['uid_hex']] = {'rank': i + 1, 'of': len(lst), 'points': _sl.showcase_points(x), 'best_points': _sl.best_points(x), 'min_points': _SC_MIN,
                                  'kept_by': _XK.get(x['uid_hex']),   # size_line.xxl_keepers: 'species' / 'type:<t>' / None (2026-09-29)
                                  'cap': keep_config.species_cap('xxl', lst[0]['pokemon_id'], keep_config.cap('xxl'))}
# XXS (rule 7b) -- OFF by default in keep_config, reported as a fact either way so the agent can see
# whether a pile mon would be a smallest-trophy if the knob were on.
xxs_rank = {}
_g1 = collections.defaultdict(list)
for r in rows:
    if (r.get('pokemon_size_category') or 0) == 1:
        _g1[(r['pokemon_id'], cf(r))].append(r)
for k, lst in _g1.items():
    for i, x in enumerate(sorted(lst, key=lambda y: ((y.get('height_m') or 9e9), (y.get('weight_kg') or 9e9),
                                                     -iv(y), y['uid_hex']))):
        xxs_rank[x['uid_hex']] = {'rank': i + 1, 'of': len(lst),
                                  'cap': keep_config.species_cap('xxs', k[0], keep_config.cap('xxs')),
                                  'rule_enabled': keep_config.rule_enabled('xxs')}
# cosmetic-variant occupancy (rule 1a) -- the bucket with the worst incident history, and the one the
# --out summary never mentioned. Keyed like keep_policy._vkey; shiny/shadow live on their own axes.
_vkey = lambda r: (r['pokemon_id'], cf(r), r.get('fresh_costume') or 0, 0,
                   r.get('fresh_natural_art_bg') or 0,
                   (r.get('costume_decoration_id') if _deco(r) else 0), _bmn(r))
_truly_plain = lambda r: not ((r.get('fresh_costume') or 0) or (r.get('fresh_natural_art_bg') or 0)
                              or _deco(r) or _bmn(r) or is_costume_form(r.get('fresh_form')))
cos_rank = {}
_vg = collections.defaultdict(list)
for r in rows:
    if r.get('fresh_shiny') or (r.get('fresh_alignment') or 0) == 1 or _truly_plain(r):
        continue
    _vg[_vkey(r)].append(r)
for k, lst in _vg.items():
    _ax = evolvable_forms.max_axis(k[-1])
    _cat = 'gigantamax' if _ax == 'gigantamax' else 'dynamax' if _ax == 'dynamax' else 'cosmetic'
    _cap = keep_config.species_cap(_cat, k[0], evolvable_forms.costume_cap(k[0], k[2], keep_config.cap(_cat))
                                   if _cat == 'cosmetic' else keep_config.cap(_cat))   # middle-stage costumes 1 (2026-09-25)
    for i, x in enumerate(_topn(lst, len(lst))):
        cos_rank[x['uid_hex']] = {'rank': i + 1, 'of': len(lst), 'cap': _cap, 'category': _cat}

# --- PvP cap-reachability, recomputed from the gamemaster ---
# cpm_table is the single source of truth (defect D4). This used to REGEX-SCRAPE `CPM = [...]` out of
# compute_all_ranks.py, which stopped holding a literal when D4 landed (it now reads `CPM = cpm_list()`), so the
# scrape raised AttributeError and this whole fact pack could not run (found 2026-09-23).
from cpm_table import CPM
GM = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
BS = {p['speciesId']: p for p in GM['pokemon']}
S2D = {p['speciesId']: p.get('dex') for p in GM['pokemon']}
# EVERY dex entry, matching keep_policy:123 -- the old `times > 0` filter dropped pid 983 (Kingambit)
# and made this file's line graph disagree with the engine's.
SEEN = {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']}
SEEN |= set(json.load(open('released_pids.json'))) if os.path.exists('released_pids.json') else set()   # any account (2026-09-26)
RR = keep_config.pvp('ready_rank')
VM = keep_config.pvp('viability_margin')
try:
    from pvp_iv_rule import GL_CAP, UL_CAP
except Exception:
    GL_CAP, UL_CAP = 1500, 2500


def maxcp(sid):
    b = (BS.get(sid or '') or {}).get('baseStats')
    return (max(10, math.floor((b['atk'] + 15) * math.sqrt(b['def'] + 15) * math.sqrt(b['hp'] + 15)
                               * CPM[98] ** 2 / 10)) if b else 0)


# --- Best GL / Best UL (LAW bucket 2b = keep_policy rule 15d, user 2026-09-23): the best NON-shadow copy per PvP
# IDENTITY. GL / UL are USABLE ONLY (user 2026-09-23): a copy competes with a stage it can REACH (the engine's ONE
# evolution graph -- a fact, like the line graph below) and ENTER (pvp_iv_rule.fits: its CP there at its TRUE level
# inside the cap), key (that stage reaches the cap first, its rank, uid_hex). ML unchanged. Viability uses
# pvp_iv_rule.maxcp (unknown species -> huge -> viable) exactly as keep_policy._viable, NOT this file's maxcp().
from pvp_iv_rule import maxcp as _pb_maxcp, VIABILITY_MARGIN as _PB_VM, ML_CAP as _PB_ML, pvid as _pb_pvid, fits as _pb_fits
_PB_BS = {s: (p.get('baseStats') or {}) for s, p in BS.items()}
_pb_via = lambda sid, cap: bool(sid) and _pb_maxcp(sid, _PB_BS) > cap + _PB_VM
try:
    from keep_policy import build_evo_graph as _pb_beg, pvp_later_stages as _pb_pls
    _PB_GRAPH = _pb_beg(GM, SEEN, with_all=True)
    _pb_later = lambda r: _pb_pls(r, _PB_GRAPH)
except Exception:
    _pb_later = lambda r: None               # the ranker's chain as it stands (looser -- reports more, hides nothing)
def _pb_usable(r, lg, cap):
    own = _pb_pvid(r['species_name'], r.get('form') or 0)
    later = _pb_later(r)
    st = []
    for p in str(r.get(lg + '_chain_ranks') or '').split(';'):
        if ':' in p:
            try:
                st.append((p.split(':')[0].strip(), int(p.split(':')[1].split('(')[0])))
            except ValueError:
                pass
    if not st and r.get(lg + '_rank') is not None:
        st = [(r.get(lg + '_stage'), r.get(lg + '_rank'))]
    reach = [(s, k) for s, k in st if s and (s == own or later is None or s in later)]   # evolution counts everywhere (2026-09-24)
    if not any(_pb_fits(r, s, cap, _PB_BS) for s, _k in reach):
        return None
    ok = [(0 if _pb_via(s, cap) else 1, k) for s, k in reach]
    return min(ok) if ok else None
pvp_best = collections.defaultdict(set)
_pbg = collections.defaultdict(list)
for r in rows:
    if r.get('fresh_alignment') == 1:
        continue
    _pbg[_pb_pvid(r['species_name'], r.get('form') or 0)].append(r)   # PvP identity (2026-09-23)
_BRF = keep_config.pvp('best_rank_floor')                   # rule 15d best rank floor (2026-09-24): top 20% only
from references import LEGENDARY_IDS as _LI, MYTHICAL_IDS as _MI, ULTRA_BEAST_IDS as _UI, PARADOX_IDS as _PI
_SD_RARE = _LI | _MI | _UI | _PI                             # legendaries: no rank floor (user 2026-09-24)
for _l in _pbg.values():
    for _lg, _cap in (('gl', GL_CAP), ('ul', UL_CAP)):
        _c = [(k, x) for x in _l for k in (_pb_usable(x, _lg, _cap),) if k is not None]
        if _c:
            _bk, _bx = min(_c, key=lambda y: (y[0][0], y[0][1], y[1]['uid_hex']))
            if _bk[1] <= _BRF or _bx['pokemon_id'] in _SD_RARE:
                pvp_best[_bx['uid_hex']].add(_lg.upper())
    _c = [x for x in _l if x.get('ml_rank') is not None and (x['ml_rank'] <= _BRF or x['pokemon_id'] in _SD_RARE)]
    if _c:
        pvp_best[min(_c, key=lambda x: (0 if _pb_via(x.get('ml_stage'), _PB_ML) else 1, x['ml_rank'], x['uid_hex']))['uid_hex']].add('ML')


# the evolution graph comes from the engine's builder: the hand-rolled recursion here had no
# BST-monotonic gate, no curated EVO_FIX edges and no "target exists" gate, so it modelled a looser
# line than the law and reported reachable stages the engine will never promote into.
_GRAPH_SRC = 'keep_policy.build_evo_graph'
try:
    from keep_policy import build_evo_graph as _beg
    _is_pre_sp, _term_sp, _dist_sp, _sp2dex, _allreach = _beg(GM, SEEN, with_all=True)
except Exception as _e:
    _GRAPH_SRC = 'LOCAL FALLBACK (%s)' % _e
    def _direct(sid):
        return [e for e in ((BS.get(sid, {}).get('family') or {}).get('evolutions') or [])
                if S2D.get(e) in SEEN and e in BS]
    def _all(sid, seen=None):
        seen = set() if seen is None else seen
        out = set()
        for e in _direct(sid):
            out.add(e)
            if e not in seen:
                seen.add(e); out |= _all(e, seen)
        return out
    _is_pre_sp = {s: bool(_direct(s)) for s in BS}
    _allreach = {s: _all(s) for s in BS}
GENDER_TERMINALS = {
    415: {1: set(), 2: {416}}, 757: {1: set(), 2: {758}}, 361: {1: {362}, 2: {478, 362}},
    281: {1: {475, 282}, 2: {282}}, 280: {1: {475, 282}, 2: {282}}, 412: {1: {414}, 2: {413}},
}
def reach_of(r):
    gt = GENDER_TERMINALS.get(r['pokemon_id'])
    if gt is not None and not gt.get(r.get('gender'), set()):
        return set()                      # gender-locked dead end (or UNKNOWN gender -> don't guess)
    return _allreach.get(_SID[r['uid_hex']], set())


# --- counts for only-copy / dex integrity ---
by_pid = collections.Counter(r['pokemon_id'] for r in rows)
by_pidform = collections.Counter((r['pokemon_id'], r.get('form') or 0) for r in rows)
by_pidcf = collections.Counter((r['pokemon_id'], cf(r)) for r in rows)
kept_pid = collections.Counter(r['pokemon_id'] for r in rows if r['uid_hex'] not in ps)
kept_pidform = collections.Counter((r['pokemon_id'], r.get('form') or 0) for r in rows if r['uid_hex'] not in ps)
kept_pidcf = collections.Counter((r['pokemon_id'], cf(r)) for r in rows if r['uid_hex'] not in ps)
# indexes, built once (these were two O(|pile| x |bag|) rescans plus a pvid() call per row per stage)
_sibs = collections.defaultdict(list)
for r in rows:
    _sibs[(r['pokemon_id'], cf(r))].append(r)
_kept_at_stage = collections.defaultdict(list)
for r in rows:
    if r['uid_hex'] not in ps:
        _kept_at_stage[_SID[r['uid_hex']]].append(iv(r))
for _v in _kept_at_stage.values():
    _v.sort(reverse=True)


def sibling(x):
    a = axes(x)
    tags = [k for k in ('shiny', 'costume_form', 'shadow', 'location_card', 'mighty', 'ef_origin',
                        'hundo', 'nundo', 'legacy_moves', 'protected_pid', 'pvp_spread_trophy') if a[k]]
    if a['costume']:
        tags.append('costume%s' % a['costume'])
    if a['decoration']:
        tags.append('deco')
    if a['art_bg']:
        tags.append('artbg')
    if evolvable_forms.max_axis(a['bread_mode']) == 'dynamax':
        tags.append('Dmax')
    if evolvable_forms.max_axis(a['bread_mode']) == 'gigantamax':
        tags.append('Gmax')
    if a['size_cat'] == 5:
        tags.append('XXL')
    if a['size_cat'] == 1:
        tags.append('XXS')
    return {'uid': x['uid_hex'], 'pct': pct(x), 'cp': x['cp'], 'form': x.get('form'),
            'attrs': tags or ['plain'], 'in_pile': x['uid_hex'] in ps}


out = {'pile_size': len(ps), 'bag': len(by), 'fused_components': len(FUSED), 'evo_graph': _GRAPH_SRC,
       'rare_roster': _RARE_SRC, 'legacy_source': _LEG_SRC,
       'caps_from': 'keep_config.json (live)', 'mons': []}
for u in sorted(ps, key=lambda z: (-(iv(by[z]) if z in by else 0), z)):
    r = by.get(u)
    if not r:
        out['mons'].append({'uid': u, 'ERROR': 'tagged uid is NOT in the bag'})
        continue
    a = axes(r)
    sid = _SID[u]
    tg = sorted(reach_of(r))
    sibs = [x for x in _sibs[(r['pokemon_id'], cf(r))] if x['uid_hex'] != u]
    # UNREAD (NULL) cosmetic inputs on a mon in the irreversible pile -- surfaced explicitly so the
    # reviewing agent sees "unknown", never a fabricated zero.
    gaps = [c for c in ('fresh_costume', 'fresh_form', 'fresh_shiny', 'fresh_alignment',
                        'fresh_bread_mode', 'fresh_has_location_card', 'fresh_loc_card_enum',
                        'fresh_natural_art_bg', 'fresh_is_strong', 'is_deployed', 'iv_total')
            if r.get(c) is None]
    out['mons'].append({
        'uid': u, 'species': r['species_name'], 'pid': r['pokemon_id'], 'pct': pct(r), 'iv': iv(r),
        'cp': r['cp'], 'form': r.get('form'), 'cf': cf(r), 'form_region': r.get('form_region'),
        'created': r.get('creation_date'), 'axes': a, 'null_columns': gaps,
        'counts': {'species_total': by_pid[r['pokemon_id']], 'species_kept': kept_pid[r['pokemon_id']],
                   'pidform_total': by_pidform[(r['pokemon_id'], r.get('form') or 0)],
                   'pidform_kept': kept_pidform[(r['pokemon_id'], r.get('form') or 0)],
                   'pidcf_total': by_pidcf[(r['pokemon_id'], cf(r))],
                   'pidcf_kept': kept_pidcf[(r['pokemon_id'], cf(r))]},
        'only_copy_of_pidform': by_pidform[(r['pokemon_id'], r.get('form') or 0)] == 1,
        # BOTH keys: the raw-form and cf() answers to "does this release wipe the form" disagree (raw
        # says 2, cf says 0 -- Mankey form 0/cf 999 with 8 kept at cf, Amaura form 0/cf 3060 with 4),
        # and audit_cull reports the cf answer. Emitting one of them alone silently contradicted it.
        'wipes_pidform_raw': kept_pidform[(r['pokemon_id'], r.get('form') or 0)] == 0,
        'wipes_pidcf': kept_pidcf[(r['pokemon_id'], cf(r))] == 0,
        'wipes_species': kept_pid[r['pokemon_id']] == 0,
        'xxl': xxl_rank.get(u), 'xxs': xxs_rank.get(u),
        'cosmetic_variant': cos_rank.get(u), 'rarity': rarity_rank.get(u),
        'best_gl_ul_of_species_or_form': sorted(pvp_best.get(u, ())),   # non-empty = a keeper (rule 15d)
        'pvp': {'gl_rank': a['gl_rank'], 'gl_stage_maxcp': maxcp(a['gl_stage']),
                'ul_rank': a['ul_rank'], 'ul_stage_maxcp': maxcp(a['ul_stage']),
                'ready_rank': RR, 'viability_margin': VM,
                'gl_cap_reachable': maxcp(a['gl_stage']) > GL_CAP + VM,
                'ul_cap_reachable': maxcp(a['ul_stage']) > UL_CAP + VM},
        'evolution': {'species_id': sid, 'reachable_stages': tg,
                      'best_kept_at_each_stage': {t: _kept_at_stage.get(t, [])[:4] for t in tg}},
        'kept_siblings': [sibling(x) for x in sorted(sibs, key=lambda y: (-iv(y), y['uid_hex'])) if x['uid_hex'] not in ps][:14],
        'piled_siblings': [sibling(x) for x in sorted(sibs, key=lambda y: (-iv(y), y['uid_hex'])) if x['uid_hex'] in ps][:14],
    })

g = lambda m, *k: (m.get(k[0]) or {}).get(k[1]) if len(k) > 1 else m.get(k[0])
_cnt = lambda f: sum(1 for m in out['mons'] if f(m))
_within = lambda m, k: bool(m.get(k)) and m[k]['rank'] <= m[k]['cap']
out['sweeps'] = {
    'not_in_bag': sum(1 for u in ps if u not in by),
    'fused_component': sum(1 for u in ps if u in FUSED),   # (2026-09-26) must be 0: a fused component is never fodder
    'hundo': _cnt(lambda m: g(m, 'axes', 'hundo')),
    'nundo': _cnt(lambda m: g(m, 'axes', 'nundo')),
    'shiny': _cnt(lambda m: g(m, 'axes', 'shiny')),
    'shadow': _cnt(lambda m: g(m, 'axes', 'shadow')),
    'ef_origin': _cnt(lambda m: g(m, 'axes', 'ef_origin')),
    'location_card': _cnt(lambda m: g(m, 'axes', 'location_card')),
    'mighty': _cnt(lambda m: g(m, 'axes', 'mighty')),
    'ae_roster': _cnt(lambda m: g(m, 'axes', 'ae_roster')),
    'unown': _cnt(lambda m: g(m, 'axes', 'unown')),
    'gmax': _cnt(lambda m: evolvable_forms.max_axis(g(m, 'axes', 'bread_mode')) == 'gigantamax'),
    'dmax': _cnt(lambda m: evolvable_forms.max_axis(g(m, 'axes', 'bread_mode')) == 'dynamax'),
    # the cosmetic bucket: costume id OR form-encoded costume OR decoration OR art background. 9 of the
    # current 52 carry costume_form and the old summary never mentioned any of these.
    'costume_any': _cnt(lambda m: g(m, 'axes', 'costume') or g(m, 'axes', 'costume_form')
                        or g(m, 'axes', 'decoration') or g(m, 'axes', 'art_bg')),
    'costume_id': _cnt(lambda m: g(m, 'axes', 'costume')),
    'costume_form': _cnt(lambda m: g(m, 'axes', 'costume_form')),
    'decoration': _cnt(lambda m: g(m, 'axes', 'decoration')),
    'art_bg': _cnt(lambda m: g(m, 'axes', 'art_bg')),
    'cosmetic_within_cap': _cnt(lambda m: _within(m, 'cosmetic_variant')),
    'xxl': _cnt(lambda m: g(m, 'axes', 'size_cat') == 5),
    'xxl_within_cap': _cnt(lambda m: _within(m, 'xxl')),
    'xxs': _cnt(lambda m: g(m, 'axes', 'size_cat') == 1),
    'xxs_within_cap_if_enabled': _cnt(lambda m: _within(m, 'xxs')),
    'rare_species': _cnt(lambda m: g(m, 'axes', 'rare_species')),
    'rarity_within_cap': _cnt(lambda m: bool(m.get('rarity'))
                              and (m['rarity']['keep_all_species'] or m['rarity']['rank'] <= m['rarity']['cap'])),
    'legacy_moves': _cnt(lambda m: g(m, 'axes', 'legacy_moves')),
    'protected_pid': _cnt(lambda m: g(m, 'axes', 'protected_pid')),
    'pvp_spread_trophy': _cnt(lambda m: g(m, 'axes', 'pvp_spread_trophy')),
    'dex_only_pidcf': _cnt(lambda m: m.get('wipes_pidcf')),
    'evolvable': _cnt(lambda m: g(m, 'evolution', 'reachable_stages')),
    'wipes_species': _cnt(lambda m: m.get('wipes_species')),
    'wipes_pidform_raw': _cnt(lambda m: m.get('wipes_pidform_raw')),
    'wipes_pidcf': _cnt(lambda m: m.get('wipes_pidcf')),
    'gl_rank_ready_viable': _cnt(lambda m: g(m, 'pvp', 'gl_rank') is not None
                                 and m['pvp']['gl_rank'] <= RR and m['pvp']['gl_cap_reachable']),
    'ul_rank_ready_viable': _cnt(lambda m: g(m, 'pvp', 'ul_rank') is not None
                                 and m['pvp']['ul_rank'] <= RR and m['pvp']['ul_cap_reachable']),
    'female_gender_split': _cnt(lambda m: g(m, 'axes', 'gender_split_species')),
    'deployed_true': _cnt(lambda m: g(m, 'axes', 'deployed') is True),
    'deployed_UNKNOWN': _cnt(lambda m: g(m, 'axes', 'deployed') is None),
    'rows_with_null_columns': _cnt(lambda m: m.get('null_columns')),
}
txt = json.dumps(out, indent=1, default=str)
if '--out' in sys.argv:
    p = sys.argv[sys.argv.index('--out') + 1]
    open(p, 'w', encoding='utf-8').write(txt)
    print('wrote %s (%d KB, %d mons)' % (p, len(txt) // 1024, len(out['mons'])))
    print('evo graph: %s | rare roster: %s | legacy: %s' % (_GRAPH_SRC, _RARE_SRC, _LEG_SRC))
    print('sweeps: %s' % json.dumps(out['sweeps']))
    print('NOTE: deployed_UNKNOWN counts pile mons whose is_deployed column is NULL -- unknown, NOT'
          ' "not deployed". Live deployment truth comes from preflight_transfer\'s gym read.')
else:
    print(txt)
