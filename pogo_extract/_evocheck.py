"""READ-ONLY: for every mon tagged for transfer, would EVOLVING it improve any stage of its line?

IV is preserved through evolution, so a 93% Popplio becomes a 93% Primarina. This independently
re-derives the comb-up question the engine's evo_extra pass is supposed to answer, and reports any
tagged mon whose evolution would beat the user's best copy of a reachable later stage.

LOCKDOWN 2026-09-02 -- one of the four gate audits full_audit.py greps. The passing line MUST keep the
exact substring 'none of the tagged mons would improve'.
2026-09-26: also BLOCKS an advice label (an evolve tag / Power Up / Unlock 2nd Move) on a pile mon, and (2026-09-29, the
fold) an engine promise whose advised stage (evolve_advice.json) is not the one this replay commits that copy to.

WHAT WAS WRONG BEFORE (audit F10-F13). Every defect pushed the bar UP, so this audit could only ever
MISS a real comb-up, never invent one -- and it printed PASS every run:
  * every evolve_*-earmarked pre-evo was credited to EVERY stage it can reach, while the engine's
    _commit_stage commits each to exactly ONE. Visible in its own output: all eight eeveelutions
    printed the identical contender list [100,98,96] when Glaceon actually holds [45,41,35].
  * the stage capacity was hardcoded `2 if reach(t) else 3`. This was the ONLY audit that never
    imported keep_config, so raising plain_line in the dashboard silently raised the bar it reads.
  * two different speciesId resolvers were used -- dex+form_region for the CANDIDATE's reachable
    stages, pvid+FORM_OVERRIDES for its HOLDINGS. They disagree on 252 in-bag rows (Mewtwo, Burmy
    cloaks, Tauros, Oricorio, Toxtricity, Pumpkaboo), so a piled Burmy had its targets computed from
    the wrong cloak's family. One resolver (pvid) is now used on both sides.
  * the evolution graph was hand-rolled with no BST-monotonic gate, no curated EVO_FIX edges and no
    gender rule, so it modelled a looser line than the engine.
  * `held` counted every non-piled copy at a stage regardless of variant, where the law counts only
    the ordinary plain copies that actually occupy a stage slot.

TWO PASSES, ONE GATE. The GATE pass models stage occupancy exactly as keep_policy._stage_hold does and
reproduces the engine set-for-set -- that is what makes a FAIL here mean "the pile disagrees with the
law as implemented". The ADVISORY pass re-runs it with hundo/nundo trophies and pile members removed
from the occupancy, because the rest of the law says a trophy is SLOT-EXEMPT (keep_policy._slot_exempt,
user 2026-07-25 "owning a trophy must never cost you a normal one") and _stage_hold is the one place
that still lets them fill a slot. Anything the advisory finds is a real ENGINE inconsistency, not a
pile defect, so it is printed loudly and does NOT gate -- a permanent un-clearable FAIL would just
train everyone to bypass the gate on the one output that cannot be undone.
"""
import sqlite3, json, sys, os, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, '.'); sys.path.insert(0, 'system/scripts')
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
PILE = 'system/analysis/tagsets/Transfer.txt'
ps = set(x for x in open(PILE).read().split() if x)
# '_'-prefixed keys are metadata, never a uid_hex (guards a future policy_reasons '_meta' block)
pol = {u: v for u, v in json.load(open('system/analysis/policy_reasons.json')).items() if not u.startswith('_')}
# SELECT * IS DELIBERATE -- never narrow it (a missing column reads None and silently disarms a check).
_cur = con.execute('SELECT * FROM pokemon WHERE in_bag=1')
_cols = [d[0] for d in _cur.description]
rows = [dict(zip(_cols, t)) for t in _cur.fetchall()]
by = {r['uid_hex']: r for r in rows}
gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
BS = {p['speciesId']: p for p in gm['pokemon']}
S2D = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
import keep_config
import evolvable_forms
from pvp_iv_rule import pvid
try:
    from costume_forms import is_costume_form
except Exception:
    is_costume_form = lambda f: False
try:
    from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
    RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
except Exception as _e:
    RARE_PIDS = set()
    print('*** WARNING: references.py unreadable (%s) -- rares will be judged like ordinary mons' % _e)

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

# An EMPTY pile used to sail through: no subjects, no problems, the PASS needle printed, rc 0.
if not ps:
    if _pile_legitimately_empty(PILE):
        print('pile is EMPTY by keep_policy (provenance pile_count=0, sha matches) -- nothing to comb-up-check: '
              'none of the tagged mons would improve any later stage')
        sys.exit(0)
    print('*** REFUSING: %s is empty -- nothing to comb-up-check, which is not a PASS' % PILE)
    sys.exit(1)

# PoGo-availability gate: an evolution only counts if its TARGET has been SEEN in the dex. Without it
# the checker reached Farigiraf (dex 981, not released in PoGo) and false-flagged a Girafarig. EVERY
# dex entry counts, matching keep_policy:123 -- the old `times > 0` filter dropped pid 983 (Kingambit),
# which is exactly why the evolvability answer diverged from the engine on 3 Bisharp.
_DEX_SEEN = {e['pid'] for e in json.load(open('pokedex_hundos_live.json'))['entries']}
_DEX_SEEN |= set(json.load(open('released_pids.json'))) if os.path.exists('released_pids.json') else set()   # any account (2026-09-26)

# The evolution graph comes from the engine's own builder: the hand-rolled copy had none of its gates
# and drifted. The fallback keeps this audit runnable -- loudly degraded -- if that import breaks.
_GRAPH_SRC = 'keep_policy.build_evo_graph'
try:
    from keep_policy import build_evo_graph as _build_evo_graph
    _is_pre_sp, _term_sp, _dist_sp, _sp2dex, _allreach = _build_evo_graph(gm, _DEX_SEEN, with_all=True)
except Exception as _e:
    _GRAPH_SRC = 'LOCAL FALLBACK (%s)' % _e
    print('*** WARNING: could not import keep_policy.build_evo_graph (%s) -- falling back to the raw'
          ' gamemaster family graph, which is LOOSER than the engine.' % _e)
    def _direct(sid):
        return [e for e in ((BS.get(sid, {}).get('family') or {}).get('evolutions') or [])
                if S2D.get(e) in _DEX_SEEN and e in BS]
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

# gender decides the terminal (or blocks evolution) for these six; keep_policy hardcodes the same table
# inside main(), so it is mirrored here until it is hoisted to module scope and can be imported.
GENDER_TERMINALS = {
    415: {1: set(), 2: {416}}, 757: {1: set(), 2: {758}}, 361: {1: {362}, 2: {478, 362}},
    281: {1: {475, 282}, 2: {282}}, 280: {1: {475, 282}, 2: {282}}, 412: {1: {414}, 2: {413}},
}

# ONE speciesId resolver for BOTH the candidate and its holdings (keying by pokemon_id or by
# dex+form_region lumps 'rapidash' with 'rapidash_galarian' and made this checker blind to the exact
# bug it was meant to catch -- it passed a Galarian Ponyta that should have been promoted, 2026-07-26).
_SID = {r['uid_hex']: pvid(r['species_name'], r['form'] or 0) for r in rows}     # memoized: pvid is hot
sid_of = lambda r: _SID[r['uid_hex']]

iv = lambda r: (r['iv_total'] or 0)
_cp = lambda r: (r['cp'] or 0)
_trophy = lambda r: iv(r) in (0, 45)

def can_evo(r):
    if r['pokemon_id'] in keep_config.protected_pids():
        return False                                   # protected keep-all species: never an evolve candidate (2026-09-16)
    if evolvable_forms.row_can_evolve(r) is False:
        return False                                   # the form has no evolution branch in the game master (2026-09-16)
    gt = GENDER_TERMINALS.get(r['pokemon_id'])
    if gt is not None:
        return bool(gt.get(r['gender'], set()))    # UNKNOWN gender -> DON'T guess: not evolvable
    return bool(_is_pre_sp.get(sid_of(r)))

def targets(r):
    """every later stage as a speciesId. Gender gates ELIGIBILITY (can_evo) but NOT the target set --
    keep_policy's comb-up reads the gender-blind allreach_sp, and modelling it tighter here would make
    this audit report FEWER missed comb-ups than the engine can actually miss."""
    ts = _allreach.get(sid_of(r), set()) if can_evo(r) else set()
    src = sid_of(r)
    def _kids(p):
        ch = _allreach.get(p, set())
        return {c for c in ch if not any(c in _allreach.get(s, ()) for s in ch if s != c)}
    out = set()
    for t in ts:     # mirrors keep_policy._promisable (2026-09-13): item branch skipped only beside a candy sibling
        if t in ITEM_GATED:
            parents = [p for p in ({src} | ts) if t in _kids(p)]
            if any(c not in ITEM_GATED for p in parents for c in _kids(p) if c != t):
                continue
        out.add(t)
    return out

def _truly_plain(r):
    return (not (r['fresh_costume'] or 0) and not (r['fresh_natural_art_bg'] or 0)
            and not (r['costume_decoration_id'] and str(r['costume_decoration_id']) != '0')
            and not evolvable_forms.max_axis(r['fresh_bread_mode']) and not is_costume_form(r['fresh_form']))
def _attrs(r):
    """mirror of keep_policy._domattr: the collectible attributes the dominance pass compares as sets."""
    s = set()
    if r['fresh_shiny']: s.add(('shiny', 1))
    if (r['fresh_natural_art_bg'] or 0): s.add(('abg', r['fresh_natural_art_bg']))
    if r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0): s.add(('loc', r['fresh_loc_card_enum']))
    if (r['fresh_costume'] or 0): s.add(('cos', r['fresh_costume']))
    elif is_costume_form(r['fresh_form']) or is_costume_form(r['form']): s.add(('cosf', r['fresh_form'] or r['form']))
    _ax = evolvable_forms.max_axis(r['fresh_bread_mode'])
    if _ax: s.add(('gmax' if _ax == 'gigantamax' else 'dmax', 1))
    if r['fresh_alignment'] == 1: s.add(('shadow', 1))
    return frozenset(s)
# the law's comb-up pool: shiny and shadow live in their own bundles and never occupy a plain stage
# slot, and a cosmetic variant is capped by rule 1a instead of the line cap (keep_policy `plain` +
# `_truly_plain`). A mon outside this pool is not a comb-up candidate at all under the law.
# PATTERN-POOLED lines (pattern_pools / keep_policy._pkey, 2026-09-08) never comb up and never occupy a
# speciesId stage slot: their cap is one pool per pattern across the whole line, so evolving a member
# cannot change its rank. keep_policy._evo_ok returns False for them and _stage_hold skips them.
import pattern_pools
from keep_policy import ITEM_GATED_TARGETS as ITEM_GATED   # item-gated targets: promised only without a candy target (2026-09-13)
_in_pool = lambda r: ((not r['fresh_shiny']) and r['fresh_alignment'] != 1 and _truly_plain(r)
                      and not pattern_pools.is_pooled(r['pokemon_id']))

CAP_PRE = keep_config.cap('plain_line_preevo')
CAP_FIN = keep_config.cap('plain_line')
_HAS_PARENT = {t for _ts in _allreach.values() for t in _ts}
_DEX_SID = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
cap_of = lambda t, g=0: evolvable_forms.ladder_cap(   # MIDDLE stages only (2026-09-13); 2 per gender, dimorphic (2026-09-25)
    CAP_PRE if (_is_pre_sp.get(t) and t in _HAS_PARENT) else CAP_FIN, _DEX_SID.get(t), g)

# earmarked = the pre-evos the engine already decided to hold back and evolve. THE ENGINE COMMITS EACH
# TO EXACTLY ONE STAGE, in one merged IV-sorted pass, so replaying that order matters: crediting every
# earmarked mon to every stage it can reach inflated every bar. Pile mons are interleaved at their own
# position in that order, so each is judged against the bar the engine would have shown it -- not one
# raised by promotions the engine would only have made afterwards.
# (2026-09-26) fused components hold no ladder slot: a Reshiram/Zekrom held inside a Kyurem fusion is not in the
# engine's `rows` (keep_policy "FUSION COMPONENTS HOLD NO LADDER SLOT"), so it is never earmarked, never a comb-up
# candidate and never a stage occupant here either. One piled is a FAIL line below, never a candidate.
# UNPAID HOLDS COMMIT TOO (2026-09-29): the engine now commits an earned-but-unpaid hold's slot like a paid promise
# (keep_policy writes them to unpaid_holds.json), so they are earmarked here as well. The file only NAMES the copies to
# replay; whether each one earns a slot -- and whether it may use the RESCUE bar -- is re-derived below (_rescue_ok,
# H08 2026-09-29), so a hold the engine should not have made raises no bar here. Missing file -> none (the old engine).
try:
    _UNPAID = set(json.load(open(os.path.join('system', 'analysis', 'unpaid_holds.json'), encoding='utf-8')))
except (OSError, ValueError):
    _UNPAID = set()
_earmarked = [r for r in rows if r['uid_hex'] not in ps and not pattern_pools.is_pooled(r['pokemon_id'])
              and not keep_config.is_fused_component(r)
              and (any(str(x).startswith('evolve_') for x in pol.get(r['uid_hex'], [])) or r['uid_hex'] in _UNPAID)]   # pooled-line Evolve labels are advisory, not comb-up commits
_cands = [by[u] for u in ps if u in by and _in_pool(by[u]) and not _trophy(by[u]) and can_evo(by[u])
          and not keep_config.is_fused_component(by[u])]

# KEPT ANYWAY AT ITS OWN STAGE -- re-derived HERE from the bag, never read from the engine (H08, 2026-09-29).
# LAW "Worth it": filling a spare slot under a better copy is a reason ONLY for a copy "kept for nothing else, whose
# alternative is release". Both sides used to answer that from the ENGINE's bookkeeping -- keep_policy._earns_slot from
# "no keep reason yet", this replay from policy_reasons.json + unpaid_holds.json -- and a within-cap STOCK copy carries
# no reason at comb-up time (its 'variant_floor' is marked only after it fails to move up). So 9 stock copies (two 93%
# Farfetch'd under a 98% Sirfetch'd, a 91% Floette under a 98% Florges ...) were told to Evolve Once into spare slots
# and 16 more HELD spare slots they never needed, and all 11 audits passed it: the replay granted the same rescue
# because it read the same files. The answer is a fact about the copy's OWN stage, computed here like the engine's
# plain ladder (keep_policy stage_pool / _eff_cap / topn): the plain, slot-holding copies of (speciesId, form, gender),
# the non-hundo shinies and cosmetic copies of that stage displacing them by IV (special wins ties), the stage cap
# (middle = plain_line_preevo, else plain_line; 2 per gender where the look differs), the collection floor. A copy
# inside that top-cap stays as stock whatever happens -- it is never rescued.
_FLOOR_IV = keep_config.collection_floor_iv()
_NUNDO_ON = keep_config.rule_enabled('nundo')
def _own_key(r):
    _s = sid_of(r)
    return evolvable_forms.stage_of(_s, r['form'] or 0) + (evolvable_forms.gender_key(r['pokemon_id'], r['gender']),)
def _holds_slot(r):                                   # the engine's stage_pool: plain, truly plain, not slot-exempt
    return ((r['fresh_alignment'] or 0) != 1 and not r['fresh_shiny'] and _truly_plain(r) and iv(r) != 45
            and not (_NUNDO_ON and r['is_zero'] and r['pokemon_id']) and not pattern_pools.is_pooled(r['pokemon_id']))
_own_plain, _own_spec, _own_evo = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(bool)
for r in rows:
    if keep_config.is_fused_component(r):             # fused components hold no ladder slot (2026-09-26)
        continue
    _k0 = _own_key(r)
    if (r['fresh_alignment'] or 0) != 1 and not r['fresh_shiny']:
        _own_evo[_k0] = _own_evo[_k0] or can_evo(r)   # the engine's stage rep: one evolvable plain-pool copy makes it a step
    if _holds_slot(r):
        _own_plain[_k0].append(r)
    elif iv(r) != 45 and (r['fresh_shiny'] or ((r['fresh_alignment'] or 0) != 1 and not _truly_plain(r))):
        _own_spec[_k0].append((iv(r), _cp(r)))       # a non-hundo shiny (any alignment) or cosmetic copy displaces by IV
_STOCK = set()
for _k0, _pl in _own_plain.items():
    _c0 = evolvable_forms.ladder_cap(CAP_PRE if (_own_evo[_k0] and _is_pre_sp.get(_k0[0]) and _k0[0] in _HAS_PARENT)
                                     else CAP_FIN, _DEX_SID.get(_k0[0]), _k0[2])
    _m0 = sorted([(a, b, 0) for a, b in _own_spec.get(_k0, ())] + [(iv(x), _cp(x), 1) for x in _pl],
                 key=lambda t: (-t[0], -t[1], t[2]))[:_c0]
    _srt0 = [x for i, x in enumerate(sorted(_pl, key=lambda x: (-iv(x), -_cp(x), x['uid_hex'])))
             if i == 0 or iv(x) >= _FLOOR_IV]          # the collection floor: under it, only the stage's best stays
    _STOCK |= {x['uid_hex'] for x in _srt0[:sum(1 for t in _m0 if t[2] == 1)]}
def _rescue_ok(r):
    """The engine's RESCUE, from the law: not stock at its own stage (above), and kept by nothing but the evolve
    promise / its hold ('variant_floor' on a copy beyond its stage cap is the hold itself)."""
    return (r['uid_hex'] not in _STOCK
            and not (set(pol.get(r['uid_hex'], [])) - {'evolve_1', 'evolve_2', 'variant_floor'}))
# ... BUT STOCK-NESS NEVER VETOES THE COLLAPSE'S SECOND CHANCE (R-A review, 2026-09-29). keep_policy's dominance collapse
# DELETES a true-plain stock copy kept by nothing but its stage slot when a KEPT copy of its own stage with a collectible
# attribute (shiny, background, card, costume, Max, shadow -- any such set is a strict superset of none) has a higher IV
# (a trophy never dominates). Its alternative IS release, so the engine judges its evolution as a RESCUE
# (keep_policy._collapsing, the 2026-09-23 Minccino) -- after its main pass found no slot without one. Without this the
# replay commits that lawful promise / hold to no stage: 'EVOLVE PROMISE(S) THE COMB-UP REPLAY COMMITS ELSEWHERE', or the
# hold's slot reads open and a piled copy reads as a missed upgrade. Read from the bag, never from the engine.
_DOM_IV = collections.defaultdict(list)                # own stage -> IVs of the KEPT, non-trophy copies with an attribute
for r in rows:
    if (keep_config.is_fused_component(r) or r['uid_hex'] not in pol or iv(r) == 45
            or (_NUNDO_ON and r['is_zero'] and r['pokemon_id']) or not _attrs(r)):
        continue
    _DOM_IV[_own_key(r)].append(iv(r))
def _collapse_victim(r):
    """keep_policy's dominance collapse deletes this copy (its alternative is release): a true plain, kept by nothing
    but its slot / the evolve promise, with a KEPT richer copy of its own stage at a higher IV."""
    return (not _attrs(r) and not (set(pol.get(r['uid_hex'], [])) - {'evolve_1', 'evolve_2', 'variant_floor'})
            and any(v > iv(r) for v in _DOM_IV.get(_own_key(r), ())))
_ORDER = sorted([(r, False) for r in _earmarked] + [(r, True) for r in _cands],
                key=lambda x: (-iv(x[0]), -_cp(x[0]), x[0]['uid_hex']))


# CANDY mirror (2026-09-17): the engine promises only what the family can afford, best-first, after Evolve Shiny.
_CANDY = evolvable_forms.candy_now(walk=max((str(r['last_scanned']) for r in rows if r.get('last_scanned')), default=None))   # the walk, not the clock (2026-09-29)
if _CANDY is not None:
    try:
        import refresh_evolve_shiny as _res
        _sp = {}
        _res.compute_target(why={u: set(v) for u, v in pol.items()}, spent=_sp)
        for _f, _n in _sp.items():
            _CANDY[_f] = _CANDY.get(_f, 0) - _n
    except Exception as _e:
        print('Evolve Shiny candy mirror skipped:', _e)


def sweep(drop_trophies, drop_piled, commits=None):
    """Replay the engine's comb-up. Returns {uid: (lines, [improving stages])} for the pile mons.
    drop_trophies/drop_piled remove those copies from the stage occupancy (the advisory pass).
    commits (2026-09-26): a dict that receives {uid: [stage(s)]} -- where each earmarked copy is committed."""
    held = collections.defaultdict(list)
    spec = collections.defaultdict(list)     # displacing specials per stage: non-hundo shiny or cosmetic/Dmax/Gmax, not shadow
    held_cp = collections.defaultdict(list)  # the same two lists as (iv, cp): the engine ranks by IV, CP breaks ties (LAW row 9)
    spec_cp = collections.defaultdict(list)
    doms = collections.defaultdict(list)     # stage -> [(attrs, iv)] of KEPT non-trophy rows with collectible attributes
    best = collections.defaultdict(lambda: -1)   # stage -> best plain IV of copies that HOLD a slot (hundos excluded 2026-09-23)
    # A STAGE IS A (speciesId, FORM) (2026-09-20). pvpoke calls every Florges colour 'florges', both Gastrodon
    # seas 'gastrodon', every Sawsbuck season 'sawsbuck' and all 28 Unown letters 'unown', so one colour's copies
    # answered for another's. Gender terminals, pattern-pooled lines and form-encoded costumes are already split
    # by their own rules above; this covers the rest. Every pool is filled under BOTH the bare speciesId and the
    # form, and read under the form ONLY when the game names which form the specimen becomes -- so when it cannot
    # say, the bar is the whole speciesId exactly as before and nothing here can read as an empty stage.
    _GMD = {p['speciesId']: p.get('dex') for p in json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))['pokemon']}
    def _gk(sid, r):
        # GENDER IS A LOOK (2026-09-23): the engine keys a dimorphic / gender-locked stage by gender, so must this audit
        return evolvable_forms.gender_key(_GMD.get(sid) or (r['pokemon_id'] if r is not None else 0), r['gender'] if r is not None else 0)
    def _kk(sid, form, r=None):
        # a SET: for a plain form (0 or <SPECIES>_NORMAL) stage_of IS (sid, ''), and a list filed every such copy
        # twice -- one Krokorok read as [96, 96], a full stage, so a copy that could fill its open slot passed.
        g = _gk(sid, r)
        return {(sid, '', g), evolvable_forms.stage_of(sid, form or 0) + (g,)}

    def _tk(t, r):
        if r is None:
            return (t, '', 0)
        _tf = evolvable_forms.target_form(r['fresh_form'] or r['form'], t, sid_of(r), r['gender'])
        return (t, evolvable_forms.canon_form(t, _tf), _gk(t, r))   # same canonicalisation the fill side uses, or they miss
    for r in rows:
        if drop_piled and r['uid_hex'] in ps:
            continue
        if keep_config.is_fused_component(r):     # (2026-09-26) fused components hold no ladder slot
            continue
        # a form-ENCODED costume is its own stage key in the engine: it neither displaces nor dominates the plain form
        _split = (r['pokemon_id'] in GENDER_TERMINALS or pattern_pools.is_pooled(r['pokemon_id'])
                  or is_costume_form(r['fresh_form']) or is_costume_form(r['form']))
        if (r['fresh_alignment'] or 0) != 1 and iv(r) != 45 and (r['fresh_shiny'] or not _truly_plain(r)) and not _split:
            for _k in _kk(sid_of(r), r['form'], r):
                spec[_k].append(iv(r)); spec_cp[_k].append((iv(r), _cp(r)))
        if not _split and not _trophy(r) and r['uid_hex'] in pol and _attrs(r):
            for _k in _kk(sid_of(r), r['form'], r): doms[_k].append((_attrs(r), iv(r)))   # a transferred mon is never a dominator
        if _in_pool(r) and not _trophy(r):   # a hundo holds no slot, so it never sets the ladder's bar (2026-09-23)
            for _k in _kk(sid_of(r), r['form'], r): best[_k] = max(best[_k], iv(r))
        if not _in_pool(r) or (drop_trophies and _trophy(r)):
            continue
        for _k in _kk(sid_of(r), r['form'], r):
            held[_k].append(iv(r)); held_cp[_k].append((iv(r), _cp(r)))
    for v in held.values():
        v.sort(reverse=True)
    def improves(t, i, r=None, rescue=False):
        # THE ENGINE'S SLOT MODEL (keep_policy._earns_slot + _eff_cap; review 2026-09-29). Specials share the plain slots
        # by IV, CP breaking ties (LAW row 9); the plain slots are those the merged top-cap leaves plain copies WITH the
        # arrival counted. When the arrival only pushes a SPECIAL out of that count (the special stays kept by its own
        # rule, no plain copy goes), the plain ladder just grows: an OPEN slot, worth it only as a rescue or a new best.
        # The old IV-only merge let a special win every IV tie and called that case an upgrade, so a 96% Smoliv kept as
        # stock was "committed" to Arboliva (98 / 93 / shiny 93) while the engine rightly promised Dolliv -- gate failed.
        tk = _tk(t, r)
        c = cap_of(t, tk[2])
        # COLLECTION FLOOR (2026-09-24): a copy under keep_config.collection_floor_iv never takes a slot beside an existing
        # copy of that stage (keep_policy.topn drops it unless it is the ladder's best) -- so it upgrades nothing there.
        if i < keep_config.collection_floor_iv() and (spec_cp.get(tk) or held_cp.get(tk)):
            return False
        if r is not None:                    # the dominance pass, exactly: a KEPT strict-superset copy with higher IV collapses it
            mv = _attrs(r)
            if any(ma != mv and (ma | mv) == ma and a_iv > i for ma, a_iv in doms.get(tk, ())):
                return False
        cpc = _cp(r) if r is not None else 0
        pool = sorted([(v, cp_, 0) for v, cp_ in held_cp.get(tk, ())] + [(i, cpc, 1)],   # 1 = the arrival; an exact
                      key=lambda x: (-x[0], -x[1], x[2]))                                  # tie keeps the copy you hold
        merged = sorted([(v, cp_, 0) for v, cp_ in spec_cp.get(tk, ())] + [(v, cp_, 1) for v, cp_, _a in pool],
                        key=lambda x: (-x[0], -x[1], x[2]))[:c]                            # special first on a full tie
        n = sum(1 for x in merged if x[2] == 1)
        if not any(x[2] == 1 for x in pool[:n]):
            return False                     # no plain slot for it: beyond the cap or displaced by a special
        if len(pool) - 1 < n:                # open slot: worth it only as the stage's first copy or a new best --
            return rescue or i > best[tk]    # UNLESS the alternative is release (keep_policy._earns_slot, 2026-09-20)
        return max(x[0] for x in pool[n:]) < i   # full: it must push out a plain copy weaker on IV, never on CP alone
    left = dict(_CANDY) if _CANDY is not None else None
    def cost(r, ts):
        cs = [evolvable_forms.path_cost(sid_of(r), t, _allreach) for t in ts]
        return None if (not cs or any(c is None for c in cs)) else max(cs)
    def afford(r, ts):
        c, f = cost(r, ts), evolvable_forms.family(sid_of(r))
        return left is None or c is None or f is None or left.get(f, 0) >= c
    def spend(r, ts):
        c, f = cost(r, ts), evolvable_forms.family(sid_of(r))
        if left is not None and c is not None and f is not None:
            left[f] = left.get(f, 0) - c
    out = {}
    for r, is_pile in _ORDER:
        tg = targets(r)
        if not is_pile:
            # an UNPAID hold (H09-1, 2026-09-29): keep_policy committed it to the first target that earns and spent
            # nothing -- it is held BECAUSE it could not pay. A copy that also wears an evolve label was paid after all.
            _unp = r['uid_hex'] in _UNPAID and not any(str(x).startswith('evolve_') for x in pol.get(r['uid_hex'], []))
            # the engine's RESCUE (2026-09-20): a copy kept by nothing but its evolve promise may fill an open slot
            # (H08, 2026-09-29) re-derived: never "only evolve reasons in policy_reasons" / "listed in unpaid_holds.json"
            _rs = _rescue_ok(r)
            _f = sorted(x for x in tg if not _is_pre_sp.get(x))   # mirrors keep_policy._promise_targets (2026-09-17)
            _order = _f if len(_f) > 1 else _f + sorted(x for x in tg if _is_pre_sp.get(x))
            def _choose(rs):
                if len(_f) > 1:
                    return _f if all(improves(t, iv(r), r, rs) for t in _f) else []
                # the engine's choice: the first target that earns a slot AND is affordable, else the first that earns
                return (next(([t] for t in _order if improves(t, iv(r), r, rs)), []) if _unp else   # H09-1
                        next(([t] for t in _order if improves(t, iv(r), r, rs) and afford(r, [t])), None) or
                        next(([t] for t in _order if improves(t, iv(r), r, rs)), []))
            _to = _choose(_rs)
            if not _to and not _rs and _collapse_victim(r):
                _to = _choose(True)                         # the engine's collapse pass: the same copy, judged as a RESCUE
            if _to and not _unp:                            # H09-1: an unpaid hold spends nothing
                spend(r, _to)
            if commits is not None:
                commits[r['uid_hex']] = _to
            for t in _to:
                for _k in {(t, ''), _tk(t, r)}:
                    held[_k].append(iv(r)); held[_k].sort(reverse=True)   # raise the bar where the engine does
                    held_cp[_k].append((iv(r), _cp(r)))
                    best[_k] = max(best[_k], iv(r))
                    if _attrs(r) and not _trophy(r):
                        doms[_k].append((_attrs(r), iv(r)))        # a promoted card copy dominates there (2026-09-13)
            continue
        lines, up = [], []
        _fins = [t for t in tg if not _is_pre_sp.get(t)]
        _rand = len(_fins) > 1                                  # split line: EVERY final must hold (2026-09-17)
        # A PILED mon has no other keep reason, so both 2026-09-20 engine rules apply to it: RESCUE (an open slot beats
        # release, even beneath better copies) and HOLD (a slot it cannot pay for today is held, never released --
        # keep_policy._earned_unpaid). Candy is therefore irrelevant here: any slot it earns means it must not be piled.
        _all_fin = bool(_fins) and all(improves(t, iv(r), r, True) for t in _fins)
        for t in sorted(tg):
            c, h = cap_of(t, _tk(t, r)[2]), held[_tk(t, r)]
            better = improves(t, iv(r), r, True) if not _rand else (_all_fin and t in _fins)
            if better:
                up.append(t)
            nm = (BS.get(t) or {}).get('speciesName', t)
            lines.append('%s(contenders %s, cap %d%s)' % (nm, [round(x / 45 * 100) for x in h[:c]] or 'NONE',
                                                          c, ' <-- ROOM/UPGRADE' if better else ''))
        out[r['uid_hex']] = (lines, up)
    return out


# CROSS-PACKAGE RECONCILIATION 2026-09-02. keep_policy._stage_hold now EXCLUDES slot-exempt trophies
# (`if _truly_plain(r) and not _slot_exempt(r)`), matching stage_pool -- the engine fix this file's own
# advisory used to ask for. GATE was still built with drop_trophies=False, i.e. it modelled the OLD
# engine and judged every pile mon against a bar the engine no longer raises. Measured on the live
# pile: GATE printed "none of the tagged mons would improve" (PASS, and that string is full_audit's
# verdict needle) while the non-gating advisory below named 21 tagged mons that DO enter a later stage.
# An audit that under-reports relative to the engine is precisely the failure this file exists to
# prevent, so GATE now mirrors the engine exactly.
#   drop_piled stays False: _stage_hold is built from the whole plain pool, before any pile exists.
#   `_trophy` (iv in {0,45}) vs the engine's `_slot_exempt` (iv==45, or is_zero+pokemon_id while
#   rules.nundo is ON): 0 rows differ in the live bag (measured 2026-09-02), and the engine's own
#   `_evo_ok` gates candidates on the same iv-in-{0,45} test.
GATE_COMMIT = {}                                        # uid -> the stage(s) GATE commits each earmarked copy to
GATE = sweep(drop_trophies=True, drop_piled=False, commits=GATE_COMMIT)   # exactly keep_policy._stage_hold (trophy-exempt)
ADV = sweep(drop_trophies=True, drop_piled=True)        # + copies already in THIS pile stop occupying slots

print('EVO COMB-UP CHECK on the %d tagged mons   (evo graph: %s)' % (len(ps), _GRAPH_SRC))
print('(IV is preserved through evolution -- would evolving this beat your best of a later stage?)\n')
problems = []
fused_piled = []     # (2026-09-26) a fused component is HELD inside a Kyurem: kept as 'fused', never a Transfer candidate
for u in sorted(ps, key=lambda z: (-(iv(by[z]) if z in by else 0), z)):
    if u not in by:
        print('  *** tagged uid %s is NOT in the bag' % u)
        continue
    r = by[u]
    if keep_config.is_fused_component(r):
        fused_piled.append(r)
        print('  %-12s %3d%%  *** FUSED COMPONENT IN THE PILE (held inside a Kyurem fusion -- kept as \'fused\', '
              'never a Transfer candidate) ***' % (r['species_name'], round(iv(r) / 45 * 100)))
        continue
    if u not in GATE:
        why = ('shiny/shadow/cosmetic -- capped on its own axis, not by the line cap' if not _in_pool(r)
               else 'hundo/nundo trophy' if _trophy(r) else 'terminal/no evolution')
        print('  %-12s %3d%%  not a comb-up candidate under the law (%s)' % (
            r['species_name'], round(iv(r) / 45 * 100), why))
        continue
    lines, up = GATE[u]
    if not lines:
        print('  %-12s %3d%%  terminal/no evolution -- nothing to comb up' % (r['species_name'], round(iv(r) / 45 * 100)))
        continue
    # the engine never promotes a legendary/mythical/UB/paradox (keep_policy._evo_ok), so an improving
    # rare is a law statement, not an engine deviation -- reported, but not a gate failure.
    flag = ''
    if up:
        if r['pokemon_id'] in RARE_PIDS:
            flag = '  (INFO: the law never promotes a legendary/mythical/UB/paradox)'
        else:
            flag = '  *** UPGRADE MISSED ***'
            problems.append((r, lines))
    print('  %-12s %3d%%  -> %s%s' % (r['species_name'], round(iv(r) / 45 * 100), ', '.join(lines), flag))

# ---- ADVISORY: stages whose slots are propped up by trophies (or by copies about to be released) ----
_adv = [(by[u], GATE[u][1], ADV[u][1]) for u in GATE if set(ADV[u][1]) - set(GATE[u][1])]
print()
if _adv:
    print('-' * 78)
    print('ADVISORY (does NOT gate): %d tagged mon(s) would enter a later stage once the OTHER copies' % len(_adv))
    print('already in this pile stop counting as ordinary stage occupants.')
    print('The trophy half of this advisory is GONE as of 2026-09-02: keep_policy._stage_hold now honours')
    print('_slot_exempt, so a hundo/nundo no longer fills a comb-up slot, and GATE above models that.')
    print('What is left is a genuine law question, not an engine bug: the engine builds the stage bar')
    print('from the whole plain pool, so a mon can be judged against occupants that are themselves about')
    print('to be released. Reported for the user to decide, never gated.')
    for r, g, a in sorted(_adv, key=lambda x: (-iv(x[0]), x[0]['uid_hex'])):
        print('   %-12s %3d%%  would enter: %s' % (r['species_name'], round(iv(r) / 45 * 100),
                                                   ', '.join(sorted(set(a) - set(g)))))
    print('-' * 78)

# ADVICE LABELS ARE FOR KEPT MONS (2026-09-26): every evolve tag, 'Power Up to 1500/2500' and 'Unlock 2nd Move' each ask
# him to SPEND candy / dust / a TM on the copy -- one on a mon in this pile contradicts the release. And (2026-09-29, the
# fold) the count tags ('Evolve Once' / 'Twice' / 'Gated') are where he stops, so an earmarked copy wearing one must be the
# copy GATE commits to exactly the stage(s) its advice names -- a replay that credits it anywhere else judged this pile
# against a bar he will never build. The targets are read from evolve_advice.json (build_tagsets' record, trusted as
# promises.json is); the replay above derives its own.
import granular_tags
advice_piled, commit_off, _counted = [], [], set()
for _t in list(granular_tags.EVOLVE_TAGS) + [granular_tags.POWER_UP_GL, granular_tags.POWER_UP_UL, granular_tags.SECOND_MOVE]:
    _p = os.path.join('system', 'analysis', 'tagsets', granular_tags.filename(_t))
    _m = set(open(_p).read().split()) if os.path.exists(_p) else set()
    for u in sorted(_m & ps):
        advice_piled.append(u)
        print('  *** %s is in the pile AND wears %r -- advice to spend on a mon being released'
              % (by[u]['species_name'] if u in by else u, _t))
    if _t in (granular_tags.EVOLVE_ONCE, granular_tags.EVOLVE_TWICE, granular_tags.EVOLVE_GATED):
        _counted |= _m
try:
    _adv = {format(int(k, 16), '016x'): v for k, v in json.load(open(granular_tags.EVOLVE_ADVICE, encoding='utf-8')).items()}
except (OSError, ValueError) as _e:
    _adv = None
    print('  *** evolve_advice.json unreadable (%s) -- the replay cannot be checked against the advice' % _e)
for u in sorted(_counted & set(GATE_COMMIT)) if _adv is not None else []:
    if sorted(GATE_COMMIT[u]) != sorted((_adv.get(u) or {}).get('targets') or []):
        commit_off.append(u)
        print('  *** %s %d%% is advised to evolve to %s but the comb-up replay commits it to %s'
              % (by[u]['species_name'], round(iv(by[u]) / 45 * 100),
                 '/'.join((_adv.get(u) or {}).get('targets') or []) or 'nothing', '/'.join(GATE_COMMIT[u]) or 'no stage'))

if fused_piled:
    print('*** %d FUSED COMPONENT(S) IN THE PILE -- held inside a Kyurem fusion, these should NOT be transferred ***'
          % len(fused_piled))
if advice_piled:
    print('*** %d ADVICE LABEL(S) ON PILE MONS -- a mon told to evolve / power up / learn a move is being released ***'
          % len(advice_piled))
if commit_off:
    print('*** %d EVOLVE PROMISE(S) THE COMB-UP REPLAY COMMITS ELSEWHERE -- the pile was judged against the wrong stage ***'
          % len(commit_off))
_blocked = ((['%d fused component(s) in the pile' % len(fused_piled)] if fused_piled else [])
            + (['%d advice label(s) on pile mons' % len(advice_piled)] if advice_piled else [])
            + (['%d evolve promise(s) the replay commits elsewhere' % len(commit_off)] if commit_off else [])
            + (['evolve_advice.json unreadable'] if _adv is None else []))
if problems:
    print('*** %d TAGGED MON(S) WOULD UPGRADE A LATER STAGE -- these should NOT be transferred ***' % len(problems))
elif _blocked:
    print('VERDICT: BLOCKED -- %s (comb-up itself found no missed upgrade)' % '; '.join(_blocked))
else:
    print('VERDICT: none of the tagged mons would improve any later stage -- comb-up correctly applied.')
sys.exit(1 if (problems or _blocked) else 0)
