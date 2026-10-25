"""TAG TRUTH -- every managed tag must be LITERALLY TRUE of EVERY member, checked per mon from its own live data.

User 2026-09-23: "I'm looking at the adventure effect tag and most of those pokemon dont have the adventure effect at
all. You need to stop generalizing and look at each pokemon that actually has it ... you did scans and still didnt
correct these kinda of details." The Adventure Effect tag had been built from the FORM (every Origin Dialga) and 19
of its 38 members did not know the move. No audit caught it because every audit re-derived the same form-level rule.
This one does not re-derive any rule: it takes each tag's CLAIM in plain words and tests it against the mon itself --
its IVs, size, moves, owner, CP at the stage the tag talks about. Where the claim covers every such mon in the bag
(Hundo, Adventure Effect ...) it also reports the ones that are missing the tag.

READ-ONLY. Exit 0 always; the verdict line is what full_audit reads.
"""
import collections
import json
import os
import sqlite3
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import keep_config
import ae_moves
from pvp_iv_rule import pvid, fits, chain_stage_ranks, maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN

TD = os.path.join('system', 'analysis', 'tagsets')
con = sqlite3.connect('file:pokemon.db?mode=ro', uri=True)
con.row_factory = sqlite3.Row
rows = {r['uid_hex']: keep_config.row_dict(r) for r in con.execute('SELECT * FROM pokemon WHERE in_bag=1')}
con.close()
gm = json.load(open('pvpoke_gamemaster.json', encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
GMP = {p['speciesId']: p for p in gm['pokemon']}
MOVES = json.load(open('move_id_to_name.json', encoding='utf-8'))
pile = set(open(os.path.join(TD, 'Transfer.txt')).read().split()) if os.path.exists(os.path.join(TD, 'Transfer.txt')) else set()


def tag(name):
    p = os.path.join(TD, name.replace(' ', '_') + '.txt')
    return {u for u in open(p).read().split() if u in rows} if os.path.exists(p) else None


def label(u):
    r = rows[u]
    return '%s %d%% %s/%s/%s CP%s' % (r['species_name'], round((r['iv_total'] or 0) * 100 / 45), r['iv_atk'], r['iv_def'],
                                      r['iv_sta'], r['cp'])


FAILS, WARNS = [], []


def check(name, claim, test, every=None, warn_only=False):
    """`test(r)` -> True when the claim holds for this mon. `every` (optional) -> True for EVERY in-bag mon the claim
    is true of, so the non-pile ones without the tag are reported as missing."""
    members = tag(name)
    if members is None:
        print('  %-18s (no tagset file -- skipped)' % name)
        return
    false_ = sorted(u for u in members if not test(rows[u]))
    # (2026-09-26) fused components hold no ladder slot: kept as 'fused' only (Legacy Moves is their one tag), so a
    # held Reshiram / Zekrom is never "missing" a tag
    missing = sorted(u for u, r in rows.items() if every and u not in members and u not in pile
                     and not keep_config.is_fused_component(r) and every(r)) if every else []
    bad = bool(false_ or missing)
    status = 'OK' if not bad else ('WARN' if warn_only else '*** FAIL ***')
    print('  %-18s members=%-5d untrue=%-4d missing=%-4d %s -- %s' % (name, len(members), len(false_), len(missing), status, claim))
    for u in false_[:12]:
        print('       UNTRUE : %s' % label(u))
    for u in missing[:12]:
        print('       MISSING: %s' % label(u))
    if bad:
        (WARNS if warn_only else FAILS).append(name)


# ---- per-mon facts ---------------------------------------------------------------------------------------------
own = lambda r: pvid(r['species_name'], r['form'] or 0)
ivs = lambda r: (r['iv_atk'], r['iv_def'], r['iv_sta'])
_AE = ae_moves.move_ids()


def move_names(r):
    out = []
    for k in ('move1', 'move2', 'move3'):
        n = MOVES.get(str(r[k])) if r[k] else None
        if n:
            out.append(n[:-5] if n.endswith('_FAST') else n)
    return out


norm = lambda m: m.replace('_', '').upper()


import re as _re
_ROLL = collections.defaultdict(set)      # dex -> move BASES any form rolls from a plain TM today (client game master)
for _t in json.load(open('gamemaster_pokeminers.json', encoding='utf-8')):
    _ps = (_t.get('data') or {}).get('pokemonSettings')
    _m = _re.match(r'V(\d{4})_POKEMON_', _t.get('templateId', ''))
    if not _ps or not _m:
        continue
    _nm = lambda x: MOVES.get(str(x)) if isinstance(x, int) else x
    _el = {_nm(x) for k in ('eliteQuickMove', 'eliteCinematicMove') for x in (_ps.get(k) or [])}
    for k in ('quickMoves', 'cinematicMoves'):
        for x in _ps.get(k) or []:
            n = _nm(x)
            if n and n not in _el:
                _ROLL[int(_m.group(1))].add(_re.sub(r'_FAST(_.*)?$', '', n))


def legacy_now(r):
    """The legacy move it is credited with is NOT one its species rolls from a plain TM today -- per the CLIENT game
    master, which outranks pvpoke. An UNKNOWN_* marker is the detector saying "cannot judge" = protected = true."""
    have = {_re.sub(r'_FAST(_.*)?$', '', MOVES.get(str(r[k]), '')) for k in ('move1', 'move2', 'move3') if r[k]}
    cred = LA.get(r['uid_hex'], [])
    if any(m.startswith('UNKNOWN') for m in cred):
        return ['UNKNOWN']
    return [m for m in cred if m in have and m not in _ROLL.get(r['pokemon_id'], set())]


LA = {e['uid_hex']: e.get('legacy_moves') or [] for e in json.load(open('legacy_accurate.json', encoding='utf-8'))}


def legacy_still_known(r):
    """The legacy move(s) legacy_accurate.json credits this mon with are still in its CURRENT moveset."""
    have = {norm(m) for m in move_names(r)}
    return any(norm(m) in have for m in LA.get(r['uid_hex'], []))


# shiny groups: (pid, canonical form) over the mons you are KEEPING (the pile is on its way out)
import granular_tags as _gt
_base = _gt._base_form_map(list(rows.values()))    # the project's own base-form election (regional + costume guards);
_cf = lambda r: r['form'] or _base.get(r['pokemon_id'], 0)   # a first-non-zero-form guess folded Unova Lilligant into Hisuian
_shg = collections.defaultdict(list)
for u, r in rows.items():
    if r['fresh_shiny'] and u not in pile and not keep_config.is_fused_component(r):   # (2026-09-26) fused components hold no ladder slot
        _shg[(r['pokemon_id'], _cf(r))].append(r)


def usable_rank(r, league, cap, own_only):
    """Best rank <= ready_rank at a stage this mon can ENTER now (own stage) / after evolving (later stage)."""
    rr = keep_config.pvp('ready_rank')
    for st, rk in chain_stage_ranks(r, league):
        if rk is None or rk > rr:
            continue
        if (st == own(r)) != own_only:
            continue
        if maxcp(st, BS) <= cap + VIABILITY_MARGIN:
            continue                                   # the stage cannot even reach the cap: no league rank claim
        if fits(r, st, cap, BS):
            return rk
    return None


UB = set(getattr(__import__('granular_tags'), 'ULTRA_BEAST_IDS', ()))
EF = keep_config.origin_owners()
PROT = set(keep_config.protected_pids())

print('TAG TRUTH -- each tag\'s claim tested on each member (and, where the claim covers every such mon, on the bag)')
check('Hundo', 'IVs are 15/15/15', lambda r: ivs(r) == (15, 15, 15), every=lambda r: ivs(r) == (15, 15, 15))
check('Nundo', 'IVs are 0/0/0', lambda r: ivs(r) == (0, 0, 0))
check('0-15-15', 'IVs are exactly 0/15/15', lambda r: ivs(r) == (0, 15, 15))
import size_line as _sl
_SC_MIN = keep_config.showcase_weights()['min_points']
_scg = collections.defaultdict(list)
for _u, _r in rows.items():
    if keep_config.is_fused_component(_r):
        continue                                   # (2026-09-26) fused components hold no ladder slot
    if (_r['pokemon_size_category'] or 0) == 5 and _r['height_m'] is not None and _r['weight_kg'] is not None \
            and (_sl.best_points(_r) is None or _sl.best_points(_r) >= _SC_MIN):   # evolution counts (2026-09-24)
        _scg[own(_r)].append(_r)
_SC_TOP = set(_sl.xxl_keepers([r for r in rows.values() if not keep_config.is_fused_component(r)]))   # ONE SELECTION (2026-09-29)
# EVO BEST GL / UL (rule 15e, 2026-09-24): evolving THIS copy would give a better GL / UL copy of that stage than any
# you own -- it can become the stage, still fits the league there, and its rank there beats yours (pvp_combup.pick).
import pvp_combup as _pcu
_CU = _pcu.pick_default([r for r in rows.values() if not keep_config.is_fused_component(r)])   # (2026-09-26) fused components hold no ladder slot
try:
    _CUL = json.load(open(os.path.join('system', 'analysis', 'pvp_combup_labels.json'), encoding='utf-8'))
except Exception:
    _CUL = None
_cus = lambda u: (_CUL.get(u) or {}).get('status') if _CUL is not None else 'now'
# THE FOLD (2026-09-29): 'Evo Best Gated' is retired -- a pick labelled 'now' OR 'gated' (never 'hold') wears Evolve for
# <league> ('Evo Best <league>' until 2026-09-30) BESIDE one of Evolve to Mid / to Final / Needs Item / Needs Task, whose own claim (where it ends,
# the gate) is checked further down.
import evolvable_forms as _ef
_EVC = set().union(*(tag(t) or set() for t in _gt.EVOLVE_COUNT_TAGS))
_cu_pick = lambda r, lg: r['uid_hex'] in _CU[lg] and _cus(r['uid_hex']) in ('now', 'gated')
check('Evolve for GL', 'THE copy to evolve for Great League (one per target), labelled now / gated: evolving it gives a better GL copy of its target stage than any you own (fits the league there), beside Evolve to Mid / to Final / Needs Item / Needs Task',
      lambda r: _cu_pick(r, 'gl') and r['uid_hex'] in _EVC, every=lambda r: _cu_pick(r, 'gl'))
check('Evolve for UL', 'THE copy to evolve for Ultra League (one per target), labelled now / gated: evolving it gives a better UL copy of its target stage than any you own (fits the league there), beside Evolve to Mid / to Final / Needs Item / Needs Task',
      lambda r: _cu_pick(r, 'ul') and r['uid_hex'] in _EVC, every=lambda r: _cu_pick(r, 'ul'))
check('XXL', 'XXL badge, showcase POINTS >= %d at its own stage or a stage it can evolve into, and one of the %d highest of its species+battle form (cosmetics fold)%s' % (_SC_MIN, keep_config.cap('xxl'), (' or of the %d highest that can enter a showcase of one of its types (XXL TRIM)' % keep_config.cap('xxl_per_type')) if keep_config.cap('xxl_per_type') else ''),
      lambda r: (r['pokemon_size_category'] or 0) == 5 and r['uid_hex'] in _SC_TOP, every=lambda r: r['uid_hex'] in _SC_TOP)
if _AE is not None:
    check('Adventure Effect', 'KNOWS an Adventure-Effect move right now', lambda r: bool(ae_moves.known(r, _AE)),
          every=lambda r: bool(ae_moves.known(r, _AE)))
else:
    WARNS.append('Adventure Effect (registry unreadable)')
    print('  Adventure Effect   registry unreadable -- UNVERIFIED')
check('Legacy Moves', 'still KNOWS the legacy move it is credited with', legacy_still_known)
check('Legacy Moves', 'that move is NOT one its species rolls from a plain TM today (client game master)',
      lambda r: bool(legacy_now(r)))
check('Ultra Beast', 'species is an Ultra Beast', lambda r: r['pokemon_id'] in UB)
check('Traded by E+F', 'traded/lucky AND original owner is E or F',
      lambda r: bool(r['is_traded'] or r['is_traded_flag_v2'] or r['is_lucky'])
      and (r['original_owner_name'] or '').strip().lower() in EF)
check('Never Cull', 'protected species or Mighty', lambda r: r['pokemon_id'] in PROT or r['fresh_is_strong'] == 1)
_shlook = lambda r: (r['pokemon_id'], _cf(r), r['fresh_costume'] or 0, _ef.gender_key(r['pokemon_id'], r['gender']))
_shl = collections.Counter(_shlook(r) for _l in _shg.values() for r in _l)     # per LOOK since 2026-09-30
check('Shiny - Only One', 'shiny, and the only shiny of its LOOK you are keeping (species + form + costume + gender where drawn differently)',
      lambda r: bool(r['fresh_shiny']) and not keep_config.is_fused_component(r)            # a fused component is never on the shiny ladder (2026-09-26)
      and _shl[_shlook(r)] == 1)
for lg, cap in (('GL', GL_CAP), ('UL', UL_CAP)):
    check('%s Rank 1-5' % lg, 'rank 1-5 AS IT IS NOW, and its CP lets it enter the league',
          lambda r, lg=lg, cap=cap: usable_rank(r, lg.lower(), cap, True) is not None)
    # THE SECOND FOLD (2026-09-30): no evolve word here -- the copy to evolve wears Evolve for <league> instead
    check('%s 1-5 No Evolve' % lg, 'a stage it can evolve into is rank 1-5 AND it would still fit the league there, and '
          'NO evolve tag is on it (not the copy to evolve)',
          lambda r, lg=lg, cap=cap: usable_rank(r, lg.lower(), cap, False) is not None and r['uid_hex'] not in _EVC)
# EVOLVE ONCE / TWICE / GATED -- THE FOLD (2026-09-29, user: "I either evolve once or evolve twice"). Every evolve advice
# is ONE table, evolve_advice.json (granular_tags.evolve_advice: promises, PvP comb-ups, shiny upgrades, showcase picks).
# Its TARGETS are the engine's record, trusted as promises.json / pvp_combup_labels.json always were; its steps / gated /
# tags are NOT -- the count and the gate are re-derived here, per copy, from the families and the client game master.
try:
    _ADV = {u.zfill(16): e for u, e in json.load(open(_gt.EVOLVE_ADVICE, encoding='utf-8')).items()}
except Exception as _ae:
    _ADV = {}
    print('  (evolve_advice.json unreadable -- %s: no evolve tag can be verified)' % _ae)


def _ends(t):
    """(2026-10-25) the CLIENT game master names no evolution out of stage t -- independent of the families granular_tags
    reads (is_final), so an 'Evolve to Final' on a stage the game evolves further is caught (it would be evolved past)."""
    _ef._load()
    return not (_ef._costs.get(_ef._gm_id(str(t))) or {})


def evo_way(r):
    """(2026-09-29) {(evolutions to it, gate keys on the way, ends its line)} over this copy's advised targets -- or None: no
    advice, a pile / fused copy,
    a form or costume that cannot evolve (row_can_evolve; an unknown form falls to the families), a target the families
    show no one- or two-step path to (steps_between), or one the game master shuts to its form / gender (can_reach).
    Gated = gate_reason on the target or, two steps away, on the stage it passes through (Happiny -> Chansey -> Blissey)."""
    ts = (_ADV.get(r['uid_hex']) or {}).get('targets') or []
    if not ts or r['uid_hex'] in pile or keep_config.is_fused_component(r) or _ef.row_can_evolve(r) is False:
        return None
    out = set()
    for t in ts:
        if len(ts) > 1 and _ef.can_reach(r['fresh_form'] or r['form'], t, own(r), r['gender']) is False:
            continue          # a gender/form split (oinkologne / oinkologne_female): this copy takes the OTHER branch
        n = _gt.steps_between(own(r), t)
        if n not in (1, 2) or _ef.can_reach(r['fresh_form'] or r['form'], t, own(r), r['gender']) is False:
            return None
        way = [t] + [m for m in _gt._evo_adj().get(own(r), ()) if n == 2 and _gt.steps_between(m, t) == 1]
        out.add((n, tuple(sorted({k for x in way for k in (_ef.gate_reason(x) or [])})), _ends(t)))
    return out or None


# WHERE IT ENDS (2026-10-25, user picked "A" + "D"): the tag names the stage the advice ends at, and a gate says what it needs.
_item = lambda ks: bool(ks) and all(k in _gt.ITEM_GATES for k in ks)
check('Evolve to Mid', 'kept to evolve to a stage that evolves again (stop there): it can evolve and the game gates nothing on the way',
      lambda r: bool(evo_way(r)) and all(not ks and not end for _n, ks, end in evo_way(r)))
check('Evolve to Final', 'kept to evolve to the end of its line: it can evolve, the game evolves its advised stage no further and gates nothing on the way',
      lambda r: bool(evo_way(r)) and all(not ks and end for _n, ks, end in evo_way(r)))
check('Evolve Needs Item', 'kept to evolve, and every gate on the way to its advised stage is an item or a lure',
      lambda r: bool(evo_way(r)) and any(ks for _n, ks, _e in evo_way(r)) and all(_item(ks) for _n, ks, _e in evo_way(r) if ks))
check('Evolve Needs Task', 'kept to evolve, and the game gates the way to its advised stage with a task, a buddy walk, a time or a move',
      lambda r: any(ks and not _item(ks) for _n, ks, _e in evo_way(r) or ()))
# RETIRED TAGS (2026-09-29: Evolve Next, every Stop tag, Evolve Shiny / Shiny Gated, Evolve for Size, Evo Best Gated ...):
# build_tagsets deletes a retired name's file, so every member a leftover file still holds is untrue.
_RET = sorted(t for t in _gt.RETIRED_TAGS if tag(t) is not None)
for _n in _RET:
    check(_n, 'RETIRED (%s) -- no mon may carry it' % _gt.RETIRED_TAGS[_n], lambda r: False)
print('  %-18s %d retired names, %d with a tagset file on disk' % ('(retired tags)', len(_gt.RETIRED_TAGS), len(_RET)))
# POWER UP TO 1500 / 2500 (2026-09-29, user: "I only want to power pokemon who are ranked in the top 100 of pvpoke"):
# rank 1-N (pvp.action_rank) at its OWN stage in that league, the own stage being its best stage there (usable_best), the
# stage reaches the cap, its species in pvpoke's top-M META for that league (pvp.power_up_meta_top, read here from the
# rankings files), CP inside the cap now and below the highest half-level (<= L50) that stays inside it; ONE copy per
# stage (the best rank, then the highest level, then uid), none when a copy already sits there; 'to 2500' never on a
# Great League keeper (it would burn it). Re-derived here from the rank chain.
from pvp_iv_rule import true_level, _cp_at_index, usable_best
from cpm_table import MAX_LEVEL_IDX
try:
    _RSN = json.load(open(os.path.join('system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))
except Exception:
    _RSN = {}
_own_rk = lambda r, lg: dict(chain_stage_ranks(r, lg)).get(own(r))
_AR, _PUN, _UMN = keep_config.pvp('action_rank'), keep_config.pvp('power_up_meta_top'), keep_config.pvp('unlock_meta_top')


def _lg_rank(r, lg, cap):
    """(2026-09-29) its OWN-stage rank in `lg` when the own stage is its best stage there (usable_best: a stage that
    reaches the cap first, then the lowest rank, own first on a tie), that stage reaches the cap and its CP is inside
    the cap now -- else None."""
    ub, o = usable_best(r, lg, cap, BS), own(r)
    if not ub or ub[2] != o or o not in BS or maxcp(o, BS) <= cap + VIABILITY_MARGIN or not fits(r, o, cap, BS):
        return None
    return ub[1]


_META = {}                                  # (2026-09-29) league -> pvpoke speciesIds by score (desc); None = unreadable
for _lg, _cap in (('gl', GL_CAP), ('ul', UL_CAP)):
    try:
        _ml = json.load(open(os.path.join('system', 'analysis', 'pvpoke_rankings', 'rankings-%d.json' % _cap), encoding='utf-8'))
        _META[_lg] = [x['speciesId'] for x in sorted(_ml, key=lambda x: -(x.get('score') or 0))]
    except Exception as _me:
        _META[_lg] = None
        if _PUN or _UMN:
            WARNS.append('%s meta list unreadable' % _lg.upper())
            print('  (pvpoke %s rankings unreadable -- %s: no meta gate, the top-N claim is UNVERIFIED)' % (_lg.upper(), _me))


def meta_in(r, lg, n):
    """(2026-09-29) its species is in pvpoke's top-n META for `lg` (a shadow as '<id>_shadow' or '<id>'); n = 0 or an
    unreadable list = no gate."""
    if not n or _META.get(lg) is None:
        return True
    top = set(_META[lg][:n])
    return own(r) in top or ((r['fresh_alignment'] or 0) == 1 and own(r) + '_shadow' in top)


_meta_txt = lambda lg, n: ("species in pvpoke's %s top %d" % (lg.upper(), n)) if n and _META.get(lg) is not None \
    else 'no meta gate'
_puc = collections.defaultdict(list)        # (league, stage) -> [(rank, true level, best level, uid)]
for _u, _r in rows.items():
    _b = BS.get(own(_r))
    if _u in pile or keep_config.is_fused_component(_r) or not _b or _r['iv_atk'] is None:
        continue
    for _lg, _cap in (('gl', GL_CAP), ('ul', UL_CAP)):
        _rk = _lg_rank(_r, _lg, _cap)
        if _rk is None or _rk > _AR or not meta_in(_r, _lg, _PUN):
            continue
        if _lg == 'ul' and ('pvp_best_gl' in (_RSN.get(_u) or ())
                            or ((_own_rk(_r, 'gl') or 9999) <= keep_config.pvp('ready_rank') and (_r['cp'] or 0) <= GL_CAP)):
            continue
        _lv = true_level(_r, BS)
        _top = max((i for i in range(MAX_LEVEL_IDX + 1) if _cp_at_index(_b, *ivs(_r), i) <= _cap), default=None)
        if _lv is not None and _top is not None:
            _puc[(_lg, own(_r))].append((_rk, _lv, 1 + _top / 2.0, _u))
def _evolve_labelled():
    """(2026-09-26) copies being told to evolve -- every evolve tag, granular_tags.EVOLVE_TAGS (2026-09-29: the Stop tags
    and Evolve for Size are folded into them; build_tagsets strips the advice by the same set): advice never sits beside one."""
    return set().union(*(tag(_t) or set() for _t in _gt.EVOLVE_TAGS))
_EVL = _evolve_labelled()
_PU = {'gl': set(), 'ul': set()}
for (_lg, _st), _l in _puc.items():
    if not any(lv >= bl for _k, lv, bl, _x in _l):
        _PU[_lg].add(min(_l, key=lambda x: (x[0], -x[1], x[3]))[3])
for _n, _lg, _nm in (('Power Up to 1500', 'gl', 'Great'), ('Power Up to 2500', 'ul', 'Ultra')):
    check(_n, 'rank 1-%d %s League spread at its OWN (= best) stage, %s, CP inside the cap now and below the best level '
              'that stays inside it (ONE per stage: the best rank, then the highest level; none when a copy is already '
              'there%s)' % (_AR, _nm, _meta_txt(_lg, _PUN), '; never a Great League keeper' if _lg == 'ul' else ''),
          lambda r, lg=_lg: r['uid_hex'] in _PU[lg], every=lambda r, lg=_lg: r['uid_hex'] in _PU[lg] and r['uid_hex'] not in _EVL)


def second_move(r):
    """(2026-09-29, user: "I only want Rank 1-5 PVP pokemon to have their 2nd moves unlocked") kept, not fused, NO second
    charged move, rank 1-N (pvp.action_rank) at its OWN (= best) stage in a league it can ENTER; with pvp.unlock_meta_top
    on, its species is in pvpoke's top-N too, judged in its best-ranked such league (Great first on a tie)."""
    if r['uid_hex'] in pile or keep_config.is_fused_component(r) or r['move3']:
        return False
    best = None
    for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
        rk = _lg_rank(r, lg, cap)
        if rk is not None and rk <= _AR and (best is None or rk < best[1]):
            best = (lg, rk)
    return best is not None and meta_in(r, best[0], _UMN)


# (2026-09-26) a league it can ENTER is part of the claim now (a CP 2494 Gardevoir was 'GL #1'); advice is never beside
# an evolve label (build_tagsets), so a copy being told to evolve is not 'missing' it.
check('Unlock 2nd Move', 'kept, NO second charged move, rank 1-%d at its OWN (= best) stage in a league it can still ENTER '
                         '(CP inside the cap)%s' % (_AR, (", species in that league's pvpoke top %d" % _UMN) if _UMN else ''),
      second_move, every=lambda r: second_move(r) and r['uid_hex'] not in _EVL)

print()
if FAILS:
    print('VERDICT: UNTRUE TAGS: %s%s' % (', '.join(FAILS), ('  (warnings: %s)' % ', '.join(WARNS)) if WARNS else ''))
else:
    print('VERDICT: EVERY TAG IS TRUE OF EVERY MEMBER%s' % (('  (warnings: %s)' % ', '.join(WARNS)) if WARNS else ''))
