"""ADVISORY ONLY -- NOT THE KEEP ENGINE. DO NOT DRIVE A TRANSFER PILE FROM THIS FILE.

==============================================================================================
READ THIS BEFORE RE-ARMING ANYTHING HERE (banner added 2026-09-02)
==============================================================================================
The ONE keep engine is system/scripts/keep_policy.py, whose every cap and roster lives in
keep_config.json. This file is a HISTORICAL second opinion: its only remaining job is the
advisory `cull_decision_v9` column, which pogo_pipeline.py fills in-process and keep_policy
reads solely to print a newly_trimmed / newly_kept diff line. Nothing releases from it and
nothing should tag from it.

ITS CAPS ARE FROZEN IN 2026 AND ARE NOT THE USER'S CURRENT POLICY. Measured 2026-09-02:
      here                     live keep_config.json
      SHINY_TOP_N   = 5        shiny            = 8
      PRE_EVO_TOP_N = 2        plain_line_preevo = 2
      FINAL_TOP_N   = 3        plain_line       = 3
      xxl  lst[:3]  = 3        xxl              = 2
and there is NO cosmetic, dynamax, gigantamax, rarity or shadow bucket here at all. `grep -c
keep_config` on this file returns 0. Wiring keep_config in would be WORSE, not better: it
would legitimize a second engine and guarantee future drift. Leave it frozen.

WHAT HAPPENED WHEN IT WAS DRIVEN LIVE: auto_tag.py used this column to rewrite auth_tag_names
and push the "Transfer" tag. Its TRANSFER set was 65 uids against keep_policy's 52, and all 44
extras were keepers -- 26 shiny, 13 variant_floor, 5 unconditionally-protected Pichu (pid 172),
2 of them PvP rank <= 5. auto_tag.py is retired; see its docstring.

If you want to change what gets kept, change keep_config.json. If you want a second opinion,
read the column. Do not tag, push, or release from it.
==============================================================================================

V9: V8 refactored to a single PROTECTION_RULES registry.

Each Rule = (name, reason_fn, sanity_sql).
- reason_fn(p, ctx) returns the reason string to append, or None.
- sanity_sql is the WHERE clause used by the sanity-check loop.
- Bucket-context (xxl_top3, shiny_top5, final_top3, etc.) is precomputed once
  into ctx; bucket rules read it as a simple uid_hex lookup.

The engine, sanity checker, and simulate_transfer all iterate the same registry,
so they cannot drift.

Output is bit-for-bit identical to cull_v8.py on the current DB state:
same decisions, same reason strings, same ';'.join(reasons[:8]) truncation.
"""
import sqlite3, json, time
from dataclasses import dataclass
from typing import Callable

_T0 = time.time()
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")
_tick("start")
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)
_tick("references imported")

PROTECTED_SHINY_PIDS = {
    129, 130, 133, 134, 135, 136, 196, 197, 470, 471, 700,
    172, 25, 26, 669, 670, 671, 384, 888,
    201,  # Unown: keep ALL shinies (user rule 2026-05-29); shinies excluded from the top-3/letter count
}
FULL_PROTECT_PIDS = {778, 242}
PER_FORM_TOP2_PIDS = {664, 924, 744}
SPECIAL_OWNERS = ('florandez', 'ethanmateovz')
PVP_RANK_KEEP = 15
SHINY_TOP_N = 5
PRE_EVO_TOP_N = 2
PRE_EVO_TOP2_N = 2
FINAL_TOP_N = 3
EXCLUDED_AUTO_TAGS = {'CLAUDE_TX', 'Traded', '6 Transfer', '6 Trade', 'Transfer'}  # transfer/trash tags must NOT self-protect
# user_tag sanity_sql derived from EXCLUDED_AUTO_TAGS so the two can never drift
_USER_TAG_EXCL_SQL = ', '.join("'%s'" % t for t in sorted(EXCLUDED_AUTO_TAGS | {''}))

def star(t): return 4 if t >= 45 else 3 if t >= 37 else 2 if t >= 30 else 1 if t >= 23 else 0


@dataclass
class Rule:
    name: str
    reason_fn: Callable  # (p, ctx) -> Optional[str]
    sanity_sql: str      # WHERE clause; sanity skipped if blank


def _owner_special(p, prefix):
    owner = (p['original_owner_name'] or '').lower()
    if owner in SPECIAL_OWNERS or not owner:
        return f'{prefix}_from_{owner or "unknown"}'
    return None


def _user_tag(p, _):
    tags = [t for t in (p['auth_tag_names'] or '').split(';') if t and t not in EXCLUDED_AUTO_TAGS]
    return f"user_tag_{tags[0]}" if tags else None


def _pid_in(ids, label):
    return lambda p, _: label if p['pokemon_id'] in ids else None


def _flag_eq(col, val, label):
    return lambda p, _: label if (p[col] or 0) == val else None


def _flag_nonzero(col, prefix):
    return lambda p, _: f"{prefix}_{p[col]}" if (p[col] or 0) != 0 else None


def _rank(col):
    return lambda p, _: (f"{col[:2]}_top{p[col]}"
                         if p[col] and p[col] <= PVP_RANK_KEEP else None)


_PROT_SHINY_SQL = ','.join(str(i) for i in sorted(PROTECTED_SHINY_PIDS))


# Rules listed in v8's exact append order. Bit-for-bit identity depends on
# this order because reason strings are truncated to [:8] before storage.
PROTECTION_RULES = [
    Rule('hundo',          lambda p, _: 'hundo' if p['is_hundo'] else None, 'is_hundo=1'),
    Rule('nundo',          lambda p, _: 'nundo' if (p['is_zero'] and p['pokemon_id']) else None,  'is_zero=1 AND pokemon_id!=0'),
    Rule('lucky_special',  lambda p, _: _owner_special(p, 'lucky')   if p['is_lucky'] else None,
         "is_lucky=1 AND lower(original_owner_name) IN ('florandez','ethanmateovz')"),
    Rule('best_buddy',     lambda p, _: 'best_buddy' if p['is_best_buddy'] else None, 'is_best_buddy=1'),
    Rule('deployed',       lambda p, _: 'deployed_in_gym' if p['is_deployed'] else None, 'is_deployed=1'),
    Rule('shadow_purified', lambda p, _: {1:'shadow',2:'purified'}.get(p['fresh_alignment'] or 0),
         'fresh_alignment IN (1,2)'),
    Rule('traded_special', lambda p, _: _owner_special(p, 'traded') if (p['is_traded_flag_v2'] or 0) == 1 else None,
         "is_traded_flag_v2=1 AND lower(original_owner_name) IN ('florandez','ethanmateovz')"),
    Rule('user_tag',       _user_tag,
         f"auth_tag_names IS NOT NULL AND auth_tag_names NOT IN ({_USER_TAG_EXCL_SQL})"),
    Rule('bread_mode',     _flag_nonzero('fresh_bread_mode', 'bread'),    'fresh_bread_mode != 0'),
    Rule('location_card',  _flag_eq('fresh_has_location_card', 1, 'location_card'), 'fresh_has_location_card=1'),
    Rule('costume',        _flag_nonzero('fresh_costume', 'costume'),     'fresh_costume != 0'),
    Rule('strong',         _flag_eq('fresh_is_strong', 1, 'is_strong'),   'fresh_is_strong=1'),
    # fresh_pokemon_badge is the per-Pokémon decorative badge enum (Best Buddy /
    # Lucky / Hundo variants — NOT the Adventure Effect marker; column-bug verified
    # 2026-05-27 against zero overlap with adventure_effects_left>0). Reason
    # encodes the badge value to make audits readable.
    Rule('badge',          lambda p, _: f'has_badge_{p["fresh_pokemon_badge"]}' if (p['fresh_pokemon_badge'] or 0) != 0 else None,
         'fresh_pokemon_badge != 0'),
    # The actual Adventure-Effect uses-remaining protection. Functionally
    # redundant with the legendary rule (all AE species are in LEGENDARY_IDS),
    # but kept as a distinct dimension so the sanity loop catches drift on the
    # AE column specifically.
    Rule('adventure_effect_uses', lambda p, _: f'adventure_effect_uses_{p["adventure_effects_left"]}' if (p['adventure_effects_left'] or 0) > 0 else None,
         'adventure_effects_left > 0'),
    Rule('current_mega',   lambda p, _: 'current_mega_evolved' if (p['fresh_current_temp_evolution'] or 0) != 0 else None,
         'fresh_current_temp_evolution != 0'),
    Rule('has_mega_level', _flag_eq('fresh_has_mega_level', 1, 'has_mega_level'), 'fresh_has_mega_level=1'),
    # GL/UL: new rule - rank<=10 AND ranked-stage form max-CP gate (GL>=1425, UL>2425),
    # top 2 per species. Computed into ctx; rule is a uid lookup. (LL still rank<=15.)
    Rule('gl_pvp',         lambda p, c: 'gl_top2_pvp' if p['uid_hex'] in c['gl_qualify_uids'] else None, ''),
    Rule('ul_pvp',         lambda p, c: 'ul_top2_pvp' if p['uid_hex'] in c['ul_qualify_uids'] else None, ''),
    Rule('ll_rank',        _rank('ll_rank'), f'll_rank<={PVP_RANK_KEEP}'),
    Rule('xxl_top3',       lambda p, c: 'xxl_top3_heaviest' if p['uid_hex'] in c['xxl_top3_uids'] else None,
         ''),  # bucket rule; sanity from ctx checked at runtime
    Rule('full_protect_species', _pid_in(FULL_PROTECT_PIDS, 'full_protect_species'), 'pokemon_id IN (778,242)'),
    Rule('legendary',      _pid_in(LEGENDARY_IDS,        'legendary'),
         f"pokemon_id IN ({','.join(str(i) for i in sorted(LEGENDARY_IDS))})"),
    Rule('mythical',       _pid_in(MYTHICAL_IDS,         'mythical'),
         f"pokemon_id IN ({','.join(str(i) for i in sorted(MYTHICAL_IDS))})"),
    Rule('ultra_beast',    _pid_in(ULTRA_BEAST_IDS,      'ultra_beast'),
         f"pokemon_id IN ({','.join(str(i) for i in sorted(ULTRA_BEAST_IDS))})"),
    Rule('paradox',        _pid_in(PARADOX_IDS,          'paradox'),
         f"pokemon_id IN ({','.join(str(i) for i in sorted(PARADOX_IDS))})"),
    Rule('adventure_effect_sp', _pid_in(ADVENTURE_EFFECT_IDS, 'adventure_effect_species'),
         f"pokemon_id IN ({','.join(str(i) for i in sorted(ADVENTURE_EFFECT_IDS))})"),
    Rule('legacy_move',    lambda p, c: 'legacy_move' if p['uid_hex'] in c['legacy_uids'] else None,
         ''),  # accurate set from detect_legacy.py (legacy_accurate.json); not has_legacy_move
    # Late-pass rules (v8 appends these AFTER the base loop):
    Rule('shiny_protected_chain',
         lambda p, _: 'shiny_protected_chain' if p['fresh_shiny'] and p['pokemon_id'] in PROTECTED_SHINY_PIDS else None,
         f"fresh_shiny=1 AND pokemon_id IN ({_PROT_SHINY_SQL})"),
    Rule('shiny_bucket',
         lambda p, c: c['shiny_bucket_reason'].get(p['uid_hex']),
         ''),
    Rule('species_form_bucket',
         lambda p, c: c['species_form_bucket_reason'].get(p['uid_hex']),
         ''),
    Rule('dex_gap_evolution',
         lambda p, c: 'dex_gap_evolution' if p['uid_hex'] in c.get('dex_gap_uids', set()) else None,
         ''),
]


def build_ctx(rows, gm):
    """Precompute bucket sets/maps that bucket-based rules read from."""
    ctx = {}
    ctx['final_form_pids'] = {p.get('dex', 0) for p in gm['pokemon']
                              if not p.get('family', {}).get('evolutions')}

    # xxl top-3-heaviest per (pid, form, costume)
    xxl_groups = {}
    for p in rows:
        if (p['pokemon_size_category'] or 0) == 5:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            xxl_groups.setdefault(key, []).append(p)
    xxl_top3 = set()
    for lst in xxl_groups.values():
        lst.sort(key=lambda x: -(x['weight_kg'] or 0))
        for p in lst[:3]: xxl_top3.add(p['uid_hex'])
    ctx['xxl_top3_uids'] = xxl_top3

    # shiny buckets (excluding protected chain)
    shiny_buckets = {}
    for p in rows:
        if p['fresh_shiny'] and p['pokemon_id'] not in PROTECTED_SHINY_PIDS:
            key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
            shiny_buckets.setdefault(key, []).append(p)
    shiny_reason = {}
    for lst in shiny_buckets.values():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst):
            if i < SHINY_TOP_N:
                shiny_reason[p['uid_hex']] = f'shiny_top{SHINY_TOP_N}_rank{i+1}'
            elif star(p['iv_total'] or 0) >= 3:
                shiny_reason[p['uid_hex']] = f'shiny_3star+_rank{i+1}'
    ctx['shiny_bucket_reason'] = shiny_reason

    # species/form top-N (excluding shinies and costumes)
    sf_buckets = {}
    for p in rows:
        if p['fresh_shiny'] or (p['fresh_costume'] or 0) != 0: continue
        sf_buckets.setdefault((p['pokemon_id'], p['form'] or 0), []).append(p)
    sf_reason = {}
    for (pid, _form), lst in sf_buckets.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))   # IV is the metric everywhere (incl. Unown)
        if pid in ctx['final_form_pids']: keep_n, label = FINAL_TOP_N, 'final_top'
        elif pid in PER_FORM_TOP2_PIDS:   keep_n, label = PRE_EVO_TOP2_N, 'preevo2_top'
        else:                             keep_n, label = PRE_EVO_TOP_N, 'preevo_top'
        for i, p in enumerate(lst[:keep_n]):
            sf_reason[p['uid_hex']] = f'{label}{keep_n}_rank{i+1}'
    ctx['species_form_bucket_reason'] = sf_reason

    # GL/UL qualify sets: rank<=10 AND ranked-stage (gl_stage/ul_stage) form max CP
    # (L50, perfect IV, NO Mega) clears gate (GL>=1425, UL>2425); keep top 2 per species.
    by_sid = {p['speciesId']: p for p in gm['pokemon']}
    # L50 CP multiplier: imported, never re-hardcoded. This file is advisory, but it is
    # imported and RUN in-process by pogo_pipeline.py, so a stale copy here is a live
    # second opinion computed from a different number (defect D4).
    from cpm_table import CPM50 as CPM_L50
    _cp = {}
    def stage_maxcp(sid):
        if sid in _cp: return _cp[sid]
        pp = by_sid.get(sid); v = None
        if pp:
            bs = pp.get('baseStats', {})
            v = max(10, int(((bs.get('atk',0)+15)*(bs.get('def',0)+15)**0.5*(bs.get('hp',0)+15)**0.5*CPM_L50**2)/10))
        _cp[sid] = v; return v
    def qualify(rank_col, stage_col, pct_col, cpmin, strict):
        groups = {}
        for p in rows:
            r = p[rank_col]
            if r is None or r > 10: continue
            stage = p[stage_col]
            if not stage: continue
            cp = stage_maxcp(stage)
            if cp is None: continue
            if (cp > cpmin) if strict else (cp >= cpmin):
                groups.setdefault(p['pokemon_id'], []).append(p)
        out = set()
        for lst in groups.values():
            lst.sort(key=lambda x: (x[rank_col], -(x[pct_col] or 0)))
            for p in lst[:2]: out.add(p['uid_hex'])
        return out
    ctx['gl_qualify_uids'] = qualify('gl_rank', 'gl_stage', 'gl_pct', 1425, False)
    ctx['ul_qualify_uids'] = qualify('ul_rank', 'ul_stage', 'ul_pct', 2425, True)

    # accurate legacy set (regenerated by detect_legacy.py -> legacy_accurate.json each pipeline run)
    try:
        with open('legacy_accurate.json') as f:
            ctx['legacy_uids'] = {e['uid_hex'] for e in json.load(f)}
    except FileNotFoundError:
        ctx['legacy_uids'] = set()

    # evolution dex-gap (FORM-AWARE): keep the BEST pre-evo of any evolution target whose
    # dex entry is incomplete - either the species was never caught, OR a tracked FORM is
    # missing (e.g. Maushold Family-of-Three vs Four share dex 925). Never transfer the only
    # path to a missing dex form. Uses dex_caught_forms.json {pid:[forms]} + form_to_dex.json
    # ({form_id: dex} -> dex's full required-form set). Inert if those files are absent.
    dex_gap = set()
    caught_forms = None
    try:
        with open('dex_caught_forms.json') as f:
            caught_forms = {int(k): set(v) for k, v in json.load(f).items()}
    except FileNotFoundError:
        # back-compat: species-level only
        try:
            with open('dex_caught.json') as f:
                caught_forms = {pid: None for pid in json.load(f)}  # None = species caught, forms unknown
        except FileNotFoundError:
            caught_forms = None
    if caught_forms is not None:
        try:
            with open('form_to_dex.json') as f:
                f2d = {int(k): v for k, v in json.load(f).items()}
        except FileNotFoundError:
            f2d = {}
        # Only forms that are CATCHABLE/EVOLVABLE count as dex gaps. Exclude transient
        # battle-stance forms and event costumes (can't be caught or evolved-to), which
        # otherwise spuriously flag evolvers (Darmanitan Zen, Aegislash Blade, Pikachu costumes).
        try:
            form_names = {int(k): v for k, v in json.load(open('form_enum.json')).items()}
        except FileNotFoundError:
            form_names = {}
        try:
            form_cat = json.load(open('form_category.json'))
        except FileNotFoundError:
            form_cat = {}
        BATTLE_KW = ('ZEN', 'BLADE', 'SHIELD', 'CROWNED', 'HANGRY', 'GULPING', 'GORGING',
                     'HERO', 'ASH', 'ETERNAMAX', 'SCHOOL', 'METEOR', 'BUSTED')
        def catchable_form(fid, dexnum):
            nm = (form_names.get(fid) or '').upper()
            if any(k in nm for k in BATTLE_KW): return False
            cat = form_cat.get(f'{dexnum}_{fid}', {}).get('category')
            if cat == 'event': return False
            return True
        dex_required_forms = {}
        for fid, d in f2d.items():
            if catchable_form(fid, d):
                dex_required_forms.setdefault(d, set()).add(fid)
        sid_dex = {p['speciesId']: p.get('dex') for p in gm['pokemon']}
        dex_sid = {}
        for p in gm['pokemon']:
            d = p.get('dex')
            if d and '_shadow' not in p['speciesId'] and d not in dex_sid:
                dex_sid[d] = p['speciesId']
        reach_cache = {}
        def reach(sid):
            if sid in reach_cache: return reach_cache[sid]
            out = set(); reach_cache[sid] = out
            pp = by_sid.get(sid)
            if pp:
                for ev in pp.get('family', {}).get('evolutions', []) or []:
                    d = sid_dex.get(ev)
                    if d: out.add(d)
                    out |= reach(ev)
            return out
        def is_incomplete(tgt_dex):
            if tgt_dex not in caught_forms: return True       # species never caught
            req = dex_required_forms.get(tgt_dex)
            cap = caught_forms[tgt_dex]
            if not req or cap is None: return False            # no form data -> species-level caught
            return bool(req - cap)                             # any required form missing
        best = {}  # target_dex -> (iv, cp, uid_hex)
        for p in rows:
            sid = dex_sid.get(p['pokemon_id'])
            if not sid: continue
            for tgt in reach(sid):
                if not is_incomplete(tgt): continue
                cand = (p['iv_total'] or 0, p['cp'] or 0, p['uid_hex'])
                cur = best.get(tgt)
                if cur is None or cand[:2] > cur[:2]:
                    best[tgt] = cand
        dex_gap = {v[2] for v in best.values()}
    ctx['dex_gap_uids'] = dex_gap

    return ctx


def is_protected(p, ctx):
    """Run every rule against p; return ordered list of reasons (possibly empty)."""
    out = []
    for r in PROTECTION_RULES:
        rs = r.reason_fn(p, ctx)
        if rs is not None: out.append(rs)
    return out


def _load_rows_and_ctx(c):
    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()]
    with open('pvpoke_gamemaster.json') as f:
        gm = json.load(f)
    return rows, build_ctx(rows, gm)


def simulate_transfer(uid_hex):
    """Return the protection-reason list for `uid_hex`, or [] if none would have kept it.

    Useful for answering "why was X transferred?". Reads from pokemon.db live;
    returns None if the uid_hex is not in the bag.
    """
    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows, ctx = _load_rows_and_ctx(c)
    p = next((r for r in rows if r['uid_hex'] == uid_hex), None)
    return None if p is None else is_protected(p, ctx)


def main():
    conn = sqlite3.connect('pokemon.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
    if 'cull_decision_v9' not in cols: c.execute('ALTER TABLE pokemon ADD COLUMN cull_decision_v9 TEXT')
    if 'cull_reason_v9' not in cols:   c.execute('ALTER TABLE pokemon ADD COLUMN cull_reason_v9 TEXT')
    conn.commit()
    _tick("schema ensured")

    _q = time.time()
    rows, ctx = _load_rows_and_ctx(c)
    _tick(f"rows + ctx built ({len(rows)} rows in {time.time()-_q:.2f}s)")

    _p = time.time()
    keep = xfer = 0
    for p in rows:
        reasons = is_protected(p, ctx)
        if reasons:
            decision, reason_str = 'KEEP', ';'.join(reasons[:8]); keep += 1
        else:
            decision, reason_str = 'TRANSFER', 'no_keep_rule';   xfer += 1
        c.execute('UPDATE pokemon SET cull_decision_v9=?, cull_reason_v9=? WHERE uid_hex=?',
                  (decision, reason_str, p['uid_hex']))
    _tick(f"per-uid UPDATE loop done ({len(rows)} rows in {time.time()-_p:.2f}s)")
    conn.commit()
    _tick("commit done")
    print(f'\nKEEP: {keep}  TRANSFER: {xfer}')

    print('\n=== Sanity (all should be 0) ===')
    for r in PROTECTION_RULES:
        if not r.sanity_sql: continue  # bucket rules / UDF-only rules
        n = c.execute(
            f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND cull_decision_v9='TRANSFER' AND {r.sanity_sql}"
        ).fetchone()[0]
        marker = '!' if n > 0 else ' '
        print(f'  {marker} {r.name:30s}: {n}')

    # xxl_top3 sanity: check no uid in ctx['xxl_top3_uids'] is a TRANSFER
    xfer_uids = {r[0] for r in c.execute(
        "SELECT uid_hex FROM pokemon WHERE in_bag=1 AND cull_decision_v9='TRANSFER'")}
    n_xxl = len(ctx['xxl_top3_uids'] & xfer_uids)
    print(f'  {"!" if n_xxl else " "} {"xxl_top3":30s}: {n_xxl}')
    for key, label in [('gl_qualify_uids','gl_pvp'), ('ul_qualify_uids','ul_pvp'),
                       ('legacy_uids','legacy_move'), ('dex_gap_uids','dex_gap_evolution')]:
        n = len(ctx.get(key, set()) & xfer_uids)
        print(f'  {"!" if n else " "} {label:30s}: {n}')

    print('\n=== Top transfer species ===')
    for r in c.execute("""SELECT species_name, COUNT(*) as n FROM pokemon
                          WHERE cull_decision_v9='TRANSFER' AND in_bag=1
                          GROUP BY species_name ORDER BY n DESC LIMIT 25"""):
        print(f'  {r[0]:25s} {r[1]}')


if __name__ == '__main__':
    main()
    _tick("done")
