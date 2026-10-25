"""keep_config.py -- single source of truth for every tunable cap/roster the keep engine uses.

Loaded by keep_policy / build_tagsets / preflight_transfer / pvp_iv_rule so the caps can NEVER
drift between them (the recurring "3-mirror" bug, e.g. the XXL showcase cap 2026-06-08) and can be
edited from the dashboard. EVERY value falls back to its hardcoded DEFAULT below if keep_config.json
is missing the key (or the file is absent / corrupt), so a partial or hand-edited file can never
break the engine -- worst case it silently uses the shipped defaults.

Game constants (league CP caps 1500/2500, CPM) are NOT tunable here -- they are fixed game rules and
live in pvp_iv_rule.py.

API:
    cap('plain_line'|'cosmetic'|'dynamax'|'gigantamax'|'shiny'|'rarity'|'xxl') -> int
    pvp('ready_rank'|'viability_margin'|'gl_floor'|'ul_floor')                 -> int
    legacy_caps()           -> {pid:int}        per-species legacy caps (else keep-all)
    rarity_keep_all()       -> set[pid]         legendaries exempt from the rarity cap (Mewtwo)
    protected_pids()        -> set[pid]         keep EVERY copy (Pichu)
    ae_pids()               -> set[pid]         adventure-effect roster
    origin_owners()         -> set[str]         lowercased trade-origin owners (E+F)
    pattern_line_pools()    -> [{name,pids}]    lines pooled per pattern across the whole evo line (pattern_pools.py)
    raw()                   -> dict             merged config (defaults <- file) for display
    write(new_cfg)          -> None             validate + atomically save keep_config.json
"""
import os
import json
import copy

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, 'keep_config.json')

# --- DEFAULTS: the exact values hardcoded in the engine as of 2026-06-08 ---
DEFAULTS = {
    "caps": {
        "plain_line": 3,      # rule 1b -- top-N plain per (species, form, gender) by IV -- FINAL stages
        "plain_line_preevo": 2,  # rule 1b -- tighter cap for MIDDLE stages only (user 2026-09-13); was every evolvable stage (a pre-evo is a
        #                          stepping stone, a final form is the keeper). user 2026-07-26.
        "plain_line_gender": 3,  # rule 1b -- cap PER GENDER for the dimorphic species (gender_variants.json), min'd with the
        #                          stage's own cap (user 2026-09-25: "By gender, cap it to 2."); 3 = no extra cut
        "cosmetic_middle": 3,  # rule 1a -- a MIDDLE-stage species' costume keeps at most this many (user 2026-09-25: "the
        #                        middle stages of costume pokemon ... can be reduced to 1"); per-species overrides still win
        "cosmetic": 4,      # rule 1a -- top-4 per cosmetic variant (costume/bg/art/decoration)
        "dynamax": 3,         # rule 1a -- top-3 Dynamax (bread=1) per (species,cf)
        "gigantamax": 6,      # rule 1a -- top-6 Gigantamax (bread=2) per (species,cf)
        "shiny": 20,          # rule 3  -- top-20 by IV per (species, form)
        "shiny_plain": 4,     # rule 3  -- of those, at most 4 PLAIN (no bg/card/costume/Max/shadow) (user 2026-09-23)
        "rarity": 12,         # rule 5  -- top-12 legendary/myth/UB/paradox per variant
        "rarity_shadow": 12,  # rule 5  -- ...and a SHADOW legendary variant keeps at most this many (user 2026-09-29: "i didnt
        #                        [want] shadow legendaries kept 6 too, keep it at 3" -> 3 in keep_config.json); min'd with rarity
        "xxl": 2,             # rule 7  -- top-2 by the game's showcase points per species+battle form (cosmetics fold), XXL only (2026-09-23)
        "xxl_per_type": 0,    # rule 7  -- ALSO keep the top-N XXLs per TYPE (own stage or one it can evolve into); 0 = OFF, the
        #                        everyday value. The XXL TRIM (user 2026-09-29: "2, but 1,000" / "a one time thing, that will
        #                        be done sometimes when i say, not every time") = xxl 1 + xxl_per_type 5 for ONE cull:
        #                        `full_audit.py --xxl-trim` sets both for that run and restores the file afterwards.
        "xxs": 2,             # rule 7b -- top-2 smallest per (species,form), size=1 (active only when rules.xxs is on)
        "shadow": 1,
        "nundo": 1,           # rule 8  -- nundos kept per look, most exotic catch place first (user 2026-09-17)
        "location_card": 3,          # rule 13 -- top-N per (species, form, card) by IV (user 2026-09-24: 5 -> 3; 6 -> 5 on 09-23)
    },
    "pvp": {
        "ready_rank": 5,      # gl/ul_rank <= this is a keeper (top-5 of 4096 spreads)
        "viability_margin": 100,  # ranked form's L50-hundo CP must exceed the league cap by this
        "best_rank_floor": 4096,    # rule 15d -- Best GL/UL/ML (non-shadow) kept only while that rank is <= this (150, user 2026-09-25 "Let's make it 150 rank."; 250, 500, 614 = top 15% and 819 = top 20% before); 4096 = off
        "shadow_rank_floor": 4096,  # rule 7 -- a shadow is kept as best ML/GL/UL only if that rank is <= this (150 with best_rank_floor, user 2026-09-25; 250, 500, 614 "15 for shadows too", 1024 = top quarter before); 4096 = off
        "gl_floor": 1400,     # vestigial CP floor (the viability gate supersedes it)
        "ul_floor": 2400,
        "action_rank": 5,     # dust advice (Power Up to 1500/2500, Unlock 2nd Move) only on an own-stage rank <= this (user 2026-09-29: "only Rank 1-5")
        "power_up_meta_top": 100,   # ...and Power Up only when the species is in pvpoke's top-N META ranking for that league (user 2026-09-29: "top 100 of pvpoke"); 0 = no meta gate
        "unlock_meta_top": 0,       # the same META gate for Unlock 2nd Move; 0 = off. LIVE VALUES are in keep_config.json (200 / 200 since 2026-09-29 02:10: "top 200")
    },
    "legacy_species_caps": {},                  # Absol -> 10; every other legacy species = legacy_default_cap (below)
    "legacy_default_cap": None,                          # rule 6 -- cap for legacy species NOT individually listed above; None = keep-all
    "rarity_keep_all_pids": [150],                       # Mewtwo -> keep ALL non-shiny (no rarity cap)
    "rarity_ladders": {},                                # {dex: {ml, ul, gl, keep_iv_over}} league ladders instead of the top-N (rarity_ladder_keep)
    "shadow_best_leagues": ["gl", "ul"],                 # rule 7 -- leagues whose best shadow is kept beside the best-ML one (shadow_leagues)
    "rarity_floor_iv": 46,                               # rule 5 -- 3-star floor OFF (user 2026-09-23: "Remove the 3 star thing"); 37 = the in-game 3-star line
    "collection_floor_iv": 0,                            # EVERY capped collection ladder (plain / costume / Max / legendary / legacy / cards): a copy below this
    #                                                      IV total takes no slot unless it is the ladder's best (0 = off; 12 = under 25%, user 2026-09-24)
    "shiny_floor_iv": 0,                                 # rule 3 -- a PLAIN shiny below this IV total takes no plain-shiny slot unless it is its form's best
    "shiny_floor_keep": 2,                               # ... the floor never takes a species+form below its best N shinies (user 2026-10-25:
    #                                                      "i want to at least keep 2 of a shiny, geez, this is going forward"; 1 before)
    #                                                      shiny (0 = off; 18 = under 40%, user 2026-09-24: "only the absolute shitty ones")
    #                                                      (37/45 = the in-game 3-star line) is kept regardless of the cap. user 2026-09-13.
    "protected_keep_all_pids": [172],                    # Pichu -> keep EVERY copy
    "adventure_effect_pids": [483, 484, 646, 800, 888, 889, 890],  # Dialga/Palkia/Kyurem/Necrozma/Zacian/Zamazenta/Eternatus
    "origin_owners": ["ethanmateovz", "florandez"],      # traded/lucky from these = keep
    "showcase_weights": {"height": 0.80, "weight": 0.15, "iv": 0.05,   # rule 7 -- the game's 800/150/50, /1000
                         "xxl_bonus": 178, "xxl_upper_factor": 2.0,
                         "min_points": 1000},   # rule 7 -- only a showcase WINNER is kept: points >= this (user 2026-09-23: 1000, 945, 955; 2026-09-24: 999, then 1050, then "Make the cut off exactly 1000." at 13:47)  # flat XXL bonus; upper-bound FALLBACK only -- the real per-species bound comes from the EXTENDED_ templates (2026-09-23)
    "pvp_spread_keep": [[0, 15, 15]],                    # rule 15 -- IV spreads always kept as PvP trophies (extend the list to keep others)
    "rules": {                    # keep-all axes you can switch OFF (default all ON = current behavior)
        "nundo": True,            # rule 8  -- keep every 0/0/0
        "adventure_effect": True, # rule 8  -- keep every copy of a FORM that has an Adventure Effect (derive_ae_roster species_ids; the pid list below is the fallback)
        "mighty": True,           # rule 11 -- keep every Mighty (fresh_is_strong)
        "location_card": True,    # rule 13 -- keep every location-card mon
        "dex_only": True,         # rule 14 -- keep the sole copy of a (species,form)
        "xxs": False,             # rule 7b -- XXS smallest-trophy axis (2026 size badges); OFF = no behavior change
    },
    "per_species_caps": {},       # Curation Studio per-species overrides {category:{pid:cap}}; empty = use the global cap (behavior-neutral)
    # PATTERN-POOLED LINES (user 2026-09-08 "top 3 of each region type only for its whole evo line"): lines whose
    # form is a collectible that SURVIVES evolution get ONE caps.plain_line pool per pattern across the whole
    # line instead of the per-(species, form) cap. See pattern_pools.py. Scatterbug/Spewpa/Vivillon by default.
    "pattern_line_pools": [{"name": "vivillon", "pids": [664, 665, 666]}],
    # EVERY line shares ONE plain pool of caps.plain_line (user 2026-09-26 on florandez: "2 plain per evolution line (the
    # whole line shares 2)" -> "this on"). Branches split (each eeveelution its own line). pattern_pools.pool_key.
    "line_pool_all": False,
}


def _deep_merge(base, over):
    """Return base deep-merged with over (over wins); only dict branches recurse."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


LOAD_ERROR = None   # str reason keep_config.json could not be used, else None (see file_loaded())


def _load():
    global LOAD_ERROR
    LOAD_ERROR = None
    try:
        with open(PATH, encoding='utf-8') as f:
            user = json.load(f)
        if not isinstance(user, dict):
            LOAD_ERROR = 'keep_config.json is not a JSON object (got %s) -- SHIPPED DEFAULTS IN USE' % type(user).__name__
            user = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        LOAD_ERROR = '%s: %s -- SHIPPED DEFAULTS IN USE' % (type(e).__name__, e)
        user = {}
    return _deep_merge(DEFAULTS, user)


CFG = _load()


def reload():
    """Re-read keep_config.json (for a long-lived process like the dashboard)."""
    global CFG
    CFG = _load()
    return CFG


def file_loaded():
    """True iff keep_config.json was actually read. FAIL-LOUD HOOK (2026-09-02).

    The module docstring promises that a missing/corrupt file "silently uses the shipped defaults".
    Silently is the defect: DEFAULTS and the live keep_config.json are NOT the same policy (today
    cosmetic 4 vs 3, gigantamax 6 vs 8, shiny 20 vs 10, rarity 12 vs 8, shadow 1 vs 2,
    viability_margin 100 vs 0, and per_species_caps empty vs three shiny overrides), so a config
    read failure produces a DIFFERENT irreversible Transfer pile with no warning anywhere -- measured
    2026-09-02 on the live bag: 3 mons in, 4 out. Falling back to defaults is the right behaviour for
    a READ-ONLY consumer (a dashboard panel, an audit); a producer of irreversible output
    (keep_policy) must check this and refuse instead. See LOAD_ERROR for the reason.
    """
    return LOAD_ERROR is None


def fingerprint():
    """Stable sha256 of the merged config actually in effect.

    THE one definition, so the pile's producer (keep_policy, which stamps it) and its consumers
    (preflight_transfer, full_audit, the audits, the dashboard's staleness badge) can never compute
    it two different ways. Excludes '_note' -- free-text, not policy.
    """
    import hashlib
    body = {k: v for k, v in CFG.items() if k != '_note'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def _int(v, default):
    """Coerce to int, falling back to default on ANY bad value -- so a hand-edited keep_config.json
    can never crash the engine at import (the docstring's promise). (ultrareview 2026-06-08)"""
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def cap(name):
    d = DEFAULTS["caps"][name]
    return _int(CFG.get("caps", {}).get(name, d), d)


def pvp(name):
    d = DEFAULTS["pvp"][name]
    return _int(CFG.get("pvp", {}).get(name, d), d)


def legacy_caps():
    src = CFG.get("legacy_species_caps")
    if not isinstance(src, dict):
        src = DEFAULTS["legacy_species_caps"]
    out = {}
    for k, v in src.items():
        try:
            out[int(k)] = int(v)
        except (TypeError, ValueError):
            continue   # skip a bad entry rather than crash (empty dict = no per-species caps, valid)
    return out


def _pid_set(key):
    src = CFG.get(key)
    if not isinstance(src, list):
        src = DEFAULTS[key]
    out = set()
    for x in src:
        try:
            if not isinstance(x, bool):
                out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def rarity_keep_all():
    return _pid_set("rarity_keep_all_pids")


def collection_floor_iv():
    """IV total BELOW which a copy takes no slot in ANY capped collection ladder unless it is that ladder's best copy.
    0 = off. user 2026-09-24 ("thats the floor now" -- 25%)."""
    d = DEFAULTS["collection_floor_iv"]
    return _int(CFG.get("collection_floor_iv", d), d)


_ROWKEYS_OK = {}


def is_fused_component(r):
    """A Reshiram/Zekrom HELD inside a fused White/Black Kyurem (PokemonProto.isComponent_, read live every walk).
    User 2026-09-26: "i think 2 are currently fused. So don't count those in the ladder." It takes NO slot on any
    ladder (plain, legacy, rarity, card, Best GL/UL/ML, ...) and is kept as 'fused' -- the game hides it and cannot
    release it while fused. Unfused, it is an ordinary bag mon again at the next walk. ONE definition for the engine
    and every mirror."""
    try:
        return bool(r['is_component'])
    except (KeyError, IndexError):
        return False


def row_dict(r):
    """dict(r) for a sqlite3.Row, built by POSITION (speed study 2026-09-24, user: "fix it. think carefully.").

    dict(sqlite3.Row) looks every key up by NAME, and a Row finds a name with a case-insensitive linear scan of its
    columns: O(columns^2) per row -- ~1 s per whole-bag load of the 212-column pokemon table, ~19 loads per pass.
    zip(keys, values) builds the IDENTICAL dict whenever the names are case-insensitively unique (always, for
    SELECT * FROM one table: SQLite refuses two columns that differ only by case). When they are not (a join that
    repeats a name) this falls back to dict(r), whose first-match semantics then decide -- so it can never return
    different data. Anything that is not a sqlite3.Row (already a dict) goes through dict() as before."""
    import sqlite3
    if not isinstance(r, sqlite3.Row):
        return dict(r)
    k = tuple(r.keys())
    ok = _ROWKEYS_OK.get(k)
    if ok is None:
        ok = _ROWKEYS_OK[k] = len({c.lower() for c in k}) == len(k)
    return dict(zip(k, r)) if ok else dict(r)


def floor_top(rows_sorted, look=None):
    """THE collection floor, applied to a ladder already sorted best-first (IV desc, CP desc, uid): the first copy always
    stays, every later copy must reach collection_floor_iv. Rows may be dicts or sqlite3.Rows. Used by keep_policy.topn
    AND every mirror (audit_cull, _lawcheck, preflight_transfer) so the floor cannot drift between them.
    look (2026-10-25): a ladder that holds several LOOKS -- one card's plain, shiny, shadow and Max copies (card_look) --
    keeps the best copy of EACH look the way it keeps its best: the floor never removes the last copy of a picture. At the
    50% floor a 53% shiny card Popplio was its card ladder's best, and both 47% normal copies of that card went to the pile."""
    fl = collection_floor_iv()
    if fl <= 0:
        return list(rows_sorted)
    if look is None:
        return [r for i, r in enumerate(rows_sorted) if i == 0 or (r["iv_total"] or 0) >= fl]
    seen, out = set(), []
    for i, r in enumerate(rows_sorted):
        lk = look(r)
        if i == 0 or (r["iv_total"] or 0) >= fl or lk not in seen:
            out.append(r)
        seen.add(lk)
    return out


def card_look(r):
    """What a location-card copy shows besides its card: shiny, shadow, Max mode, background, costume, decoration (the
    variant axes of audit_cull's layer 5 that can differ inside one card ladder). The look key for floor_top(look=)."""
    def g(k):
        try:
            return r[k]
        except (KeyError, IndexError):
            return None
    d = g("costume_decoration_id")
    return (bool(g("fresh_shiny")), g("fresh_alignment") == 1, g("fresh_bread_mode") or 0,
            g("fresh_natural_art_bg") or 0, g("fresh_costume") or 0, d if (d and str(d) != "0") else 0)


def shadow_leagues():
    """The leagues whose best shadow is kept beside the best-ML (= top-IV) shadow. ('ul',) since 2026-09-26 (user:
    "remove the gl shadows, we only collect ul and ml and best iv now"); ('gl', 'ul') before."""
    v = CFG.get("shadow_best_leagues", DEFAULTS.get("shadow_best_leagues"))
    return tuple(x for x in (v if isinstance(v, (list, tuple)) else ("gl", "ul")) if x in ("gl", "ul"))


def rarity_ladder(pid):
    """{'ml': n, 'ul': n, 'gl': n, 'keep_iv_over': t} when legendary `pid` is sorted by LEAGUE ladders instead of the
    plain top-N (Mewtwo, user 2026-09-26: "top 9 for ML, UL, GL ... no one that is special or above 90 iv can go ...
    legacy move makes this special"), else None."""
    d = CFG.get("rarity_ladders")
    v = d.get(str(pid)) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else None


def rarity_ladder_pids():
    d = CFG.get("rarity_ladders")
    return {int(k) for k in d} if isinstance(d, dict) else set()


def rarity_ladder_keep(rows, legacy_uids, spec):
    """uids to keep from ONE rarity group (species, form, shadow, Max mode) of a laddered legendary. Kept outright:
    everything SPECIAL (shiny, shadow, purified, lucky, card, background, costume, decoration, Max, hundo, legacy move)
    and every copy with IV total over spec['keep_iv_over']. The rest compete: the top spec['ml'] / ['ul'] / ['gl'] by
    that league's rank, identical IV spreads counted ONCE (the higher-CP twin holds the place). Rows may be dicts or
    sqlite3.Rows. THE one implementation: keep_policy and audit_cull both call it."""
    def g(r, k):
        try:
            return r[k]
        except (KeyError, IndexError):
            return None
    def special_look(r):
        deco = g(r, "costume_decoration_id")
        return bool(g(r, "fresh_shiny") or g(r, "fresh_alignment") in (1, 2) or g(r, "is_lucky")
                    or g(r, "fresh_loc_card_enum") or g(r, "fresh_has_location_card") or g(r, "fresh_natural_art_bg")
                    or g(r, "fresh_costume") or (deco and str(deco) != "0") or (g(r, "fresh_bread_mode") or 0)
                    or (g(r, "iv_total") or 0) == 45)
    over = _int(spec.get("keep_iv_over"), 45)
    # spec['legacy_is_special']: a legacy copy is kept outright (it still RANKS either way). OFF for Mewtwo since
    # 2026-09-26 ("legeccy move doesnt make them special anymore") -- the general legacy rule (best N per species) still
    # keeps its own legacy copies.
    _leg = legacy_uids if spec.get("legacy_is_special") else ()
    keep = {g(r, "uid_hex") for r in rows
            if special_look(r) or g(r, "uid_hex") in _leg or (g(r, "iv_total") or 0) > over}
    twins = {}
    for r in rows:
        if special_look(r):
            continue
        k = (g(r, "iv_atk"), g(r, "iv_def"), g(r, "iv_sta"))
        if k not in twins or ((g(r, "cp") or 0), g(r, "uid_hex")) > ((g(twins[k], "cp") or 0), g(twins[k], "uid_hex")):
            twins[k] = r
    pool = list(twins.values())
    for lg in ("ml", "ul", "gl"):
        n = _int(spec.get(lg), 0)
        ranked = sorted(pool, key=lambda r: (g(r, lg + "_rank") or 10 ** 6, -(g(r, "iv_total") or 0), -(g(r, "cp") or 0), g(r, "uid_hex")))
        keep |= {g(r, "uid_hex") for r in ranked[:n]}
    return keep


def shiny_floor_keep():
    """The shiny floor never takes a species+form below this many shinies: its N best stay, floor or not (2 since
    2026-10-25, user: "i want to at least keep 2 of a shiny"). The best PLAIN shiny stays as well."""
    d = DEFAULTS["shiny_floor_keep"]
    return max(1, _int(CFG.get("shiny_floor_keep", d), d))


def shiny_floor_iv():
    """IV total BELOW which a PLAIN shiny (no bg / card / costume / Max / shadow) is not eligible for a plain-shiny
    slot -- unless it is the best shiny of its species+form, which always stays. 0 = off. user 2026-09-24."""
    d = DEFAULTS["shiny_floor_iv"]
    return _int(CFG.get("shiny_floor_iv", d), d)


def rarity_floor_iv():
    """IV total at/above which a roster legendary/mythical/UB/paradox is kept regardless of the rarity cap
    (37 = the in-game 3-star line; 46 switches the floor off). user 2026-09-13."""
    d = DEFAULTS["rarity_floor_iv"]
    return _int(CFG.get("rarity_floor_iv", d), d)


def protected_pids():
    return _pid_set("protected_keep_all_pids")


def ae_pids():
    return _pid_set("adventure_effect_pids")


def origin_owners():
    src = CFG.get("origin_owners")
    if not isinstance(src, list):
        src = DEFAULTS["origin_owners"]
    return set(str(x).strip().lower() for x in src if isinstance(x, str) and x.strip())


def showcase_weights():
    w = CFG.get("showcase_weights")
    if not isinstance(w, dict):
        w = DEFAULTS["showcase_weights"]
    out = {}
    for k in ("height", "weight", "iv", "xxl_bonus", "xxl_upper_factor", "min_points"):
        try:
            out[k] = float(w.get(k, DEFAULTS["showcase_weights"][k]))
        except (TypeError, ValueError):
            out[k] = DEFAULTS["showcase_weights"][k]
    return out


def pvp_spread_keep():
    src = CFG.get("pvp_spread_keep")
    if not isinstance(src, list):
        src = DEFAULTS["pvp_spread_keep"]
    out = set()
    for x in src:
        try:
            if isinstance(x, (list, tuple)) and len(x) == 3:
                out.add((int(x[0]), int(x[1]), int(x[2])))
        except (TypeError, ValueError):
            continue
    return out


def legacy_default_cap():
    """Global cap for legacy species NOT individually listed in legacy_species_caps. None = keep-all (current)."""
    v = CFG.get("legacy_default_cap", None)
    if v is None or isinstance(v, bool):
        return None
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return None


def rule_enabled(name):
    """Is a switchable keep-all axis ON? Missing/bad -> the shipped default (True for all)."""
    src = CFG.get("rules")
    if not isinstance(src, dict):
        src = {}
    v = src.get(name, DEFAULTS["rules"].get(name, True))
    return v if isinstance(v, bool) else DEFAULTS["rules"].get(name, True)


def species_cap(category, pid, default):
    """Per-species cap override for a category (Curation Studio), else `default`.
    Missing/bad/empty -> default, so an empty per_species_caps is byte-identical to today."""
    src = CFG.get("per_species_caps")
    if not isinstance(src, dict):
        return default
    cat = src.get(category)
    if not isinstance(cat, dict):
        return default
    v = cat.get(str(pid))
    return _int(v, default) if v is not None else default


def line_pool_all():
    """True -> every evolution line shares one plain pool (pattern_pools.pool_key); False -> per-stage ladders."""
    return CFG.get("line_pool_all", DEFAULTS["line_pool_all"]) is True


def pattern_line_pools():
    """[{name, pids}] -- lines pooled per pattern across the whole evolution line (pattern_pools.py).
    Malformed entries are DROPPED (never crash the engine); a missing key -> the shipped default."""
    src = CFG.get("pattern_line_pools", DEFAULTS["pattern_line_pools"])
    if not isinstance(src, list):
        return copy.deepcopy(DEFAULTS["pattern_line_pools"])
    out = []
    for ent in src:
        if not isinstance(ent, dict) or not isinstance(ent.get("name"), str) or not ent["name"].strip():
            continue
        pids = ent.get("pids")
        if not isinstance(pids, list):
            continue
        ok = [int(x) for x in pids if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 1025]
        if ok:
            out.append({"name": ent["name"].strip(), "pids": ok})
    return out


def raw():
    return copy.deepcopy(CFG)


# --- validation + atomic save (used by the dashboard) ---
_CAP_BOUNDS = {  # (min, max) sanity bounds the dashboard enforces -- a fat-finger guard, not policy
    "plain_line": (0, 50), "plain_line_preevo": (0, 50), "plain_line_gender": (1, 50), "cosmetic_middle": (1, 50), "cosmetic": (0, 50), "dynamax": (0, 50), "gigantamax": (0, 50),
    "shiny": (0, 200), "shiny_plain": (0, 200), "rarity": (0, 200), "rarity_shadow": (0, 200), "xxl": (0, 50), "xxl_per_type": (0, 50), "xxs": (0, 50), "shadow": (0, 50), "nundo": (1, 50),
}   # xxs entry REQUIRED: every merged config carries caps.xxs, so a missing bound KeyError'd validate() and killed all dashboard saves (workflow verifier 2026-06-09)
_PVP_BOUNDS = {"ready_rank": (1, 100), "viability_margin": (-500, 1000), "action_rank": (1, 100), "power_up_meta_top": (0, 5000), "unlock_meta_top": (0, 5000), "shadow_rank_floor": (1, 4096), "best_rank_floor": (1, 4096),
               "gl_floor": (0, 5000), "ul_floor": (0, 5000)}


def validate(cfg):
    """Return list of human-readable problems with a proposed config (empty list = OK)."""
    probs = []
    caps = cfg.get("caps", {})
    for k, v in caps.items():
        if k not in DEFAULTS["caps"]:
            probs.append(f"unknown cap '{k}'")
            continue
        if not isinstance(v, int) or isinstance(v, bool):
            probs.append(f"cap '{k}' must be an integer (got {v!r})")
            continue
        bounds = _CAP_BOUNDS.get(k)
        if bounds is None:
            continue   # known cap without an explicit bound: accept any int (a DEFAULTS/bounds skew must NEVER KeyError and kill every config save -- audit F01)
        lo, hi = bounds
        if not (lo <= v <= hi):
            probs.append(f"cap '{k}'={v} out of range [{lo},{hi}]")
    pv = cfg.get("pvp", {})
    for k, v in pv.items():
        if k not in DEFAULTS["pvp"]:
            probs.append(f"unknown pvp key '{k}'")
            continue
        if not isinstance(v, int) or isinstance(v, bool):
            probs.append(f"pvp '{k}' must be an integer (got {v!r})")
            continue
        bounds = _PVP_BOUNDS.get(k)
        if bounds is None:
            continue   # known pvp key without an explicit bound: accept any int. Same F01 guard the caps
            #            loop already has -- a DEFAULTS/_PVP_BOUNDS skew (adding a pvp default without a
            #            bound) would otherwise KeyError here and kill EVERY dashboard config save.
        lo, hi = bounds
        if not (lo <= v <= hi):
            probs.append(f"pvp '{k}'={v} out of range [{lo},{hi}]")
    for k in ("rarity_keep_all_pids", "protected_keep_all_pids", "adventure_effect_pids"):
        if k in cfg and not (isinstance(cfg[k], list) and all(isinstance(x, int) and not isinstance(x, bool) for x in cfg[k])):
            probs.append(f"'{k}' must be a list of integer pids")
    if "legacy_species_caps" in cfg:
        lsc = cfg["legacy_species_caps"]
        if not isinstance(lsc, dict) or not all(str(k).isdigit() and isinstance(v, int) for k, v in lsc.items()):
            probs.append("'legacy_species_caps' must be {pid: int}")
    if "origin_owners" in cfg and not (isinstance(cfg["origin_owners"], list) and all(isinstance(x, str) for x in cfg["origin_owners"])):
        probs.append("'origin_owners' must be a list of strings")
    # value bounds for rosters + unknown-key rejection (ultrareview 2026-06-08)
    lsc = cfg.get("legacy_species_caps", {})
    if isinstance(lsc, dict):
        for k, v in lsc.items():
            if isinstance(v, int) and not isinstance(v, bool) and not (0 <= v <= 500):
                probs.append("legacy cap for pid %s=%s out of range [0,500]" % (k, v))
    for key in ("rarity_keep_all_pids", "protected_keep_all_pids", "adventure_effect_pids"):
        for x in (cfg.get(key) or []):
            if isinstance(x, int) and not isinstance(x, bool) and not (1 <= x <= 1025):
                probs.append("%s: pid %s out of range [1,1025]" % (key, x))
    sw = cfg.get("showcase_weights")
    if sw is not None:
        if not isinstance(sw, dict):
            probs.append("'showcase_weights' must be an object {height,weight,iv}")
        else:
            for k in ("height", "weight", "iv"):
                v = sw.get(k)
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 1):
                    probs.append("showcase_weights.%s must be a number 0..1" % k)
    ps = cfg.get("pvp_spread_keep")
    if ps is not None:
        if not isinstance(ps, list):
            probs.append("'pvp_spread_keep' must be a list of [atk,def,sta]")
        else:
            for x in ps:
                if not (isinstance(x, (list, tuple)) and len(x) == 3 and all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 15 for n in x)):
                    probs.append("pvp_spread_keep entry %r must be [atk,def,sta] each 0..15" % (x,))
    rf = cfg.get("rarity_floor_iv", DEFAULTS["rarity_floor_iv"])
    if isinstance(rf, bool) or not isinstance(rf, int) or not (0 <= rf <= 46):
        probs.append("'rarity_floor_iv' must be an integer 0..46 (46 = floor off)")
    cfl = cfg.get("collection_floor_iv", DEFAULTS["collection_floor_iv"])
    if isinstance(cfl, bool) or not isinstance(cfl, int) or not (0 <= cfl <= 45):
        probs.append("'collection_floor_iv' must be an integer 0..45 (0 = floor off)")
    sf = cfg.get("shiny_floor_iv", DEFAULTS["shiny_floor_iv"])
    if isinstance(sf, bool) or not isinstance(sf, int) or not (0 <= sf <= 45):
        probs.append("'shiny_floor_iv' must be an integer 0..45 (0 = floor off)")
    sk = cfg.get("shiny_floor_keep", DEFAULTS["shiny_floor_keep"])
    if isinstance(sk, bool) or not isinstance(sk, int) or not (1 <= sk <= 20):
        probs.append("'shiny_floor_keep' must be an integer 1..20")
    ldc = cfg.get("legacy_default_cap", None)
    if ldc is not None and not (isinstance(ldc, int) and not isinstance(ldc, bool) and 0 <= ldc <= 500):
        probs.append("'legacy_default_cap' must be null or an integer 0..500")
    rl = cfg.get("rules")
    if rl is not None:
        if not isinstance(rl, dict):
            probs.append("'rules' must be an object of {axis: true/false}")
        else:
            for k, v in rl.items():
                if k not in DEFAULTS["rules"]:
                    probs.append("unknown rule toggle '%s'" % k)
                elif not isinstance(v, bool):
                    probs.append("rule toggle '%s' must be true/false" % k)
    psc = cfg.get("per_species_caps")
    if psc is not None:
        _psc_cats = {"gigantamax", "dynamax", "cosmetic", "shiny", "rarity", "rarity_shadow", "xxl", "xxs", "location_card"}   # xxs: rule 7b consults species_cap('xxs', ...)
        if not isinstance(psc, dict):
            probs.append("'per_species_caps' must be {category: {pid: int}}")
        else:
            for _cat, _m in psc.items():
                if _cat not in _psc_cats:
                    probs.append("per_species_caps: unknown category '%s'" % _cat)
                elif not isinstance(_m, dict):
                    probs.append("per_species_caps['%s'] must be {pid: int}" % _cat)
                else:
                    for _k, _v in _m.items():
                        if not (str(_k).isdigit() and isinstance(_v, int) and not isinstance(_v, bool) and 0 <= _v <= 500):
                            probs.append("per_species_caps['%s']: pid %s cap %r must be int 0..500" % (_cat, _k, _v))
    plp = cfg.get("pattern_line_pools")
    if plp is not None:
        if not isinstance(plp, list):
            probs.append("'pattern_line_pools' must be a list of {name, pids}")
        else:
            _seen_pids = set()
            for ent in plp:
                if not isinstance(ent, dict) or not isinstance(ent.get("name"), str) or not ent["name"].strip():
                    probs.append("pattern_line_pools entry %r needs a non-empty string 'name'" % (ent,))
                    continue
                pids = ent.get("pids")
                if not (isinstance(pids, list) and pids and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 1025 for x in pids)):
                    probs.append("pattern_line_pools['%s'].pids must be a non-empty list of dex ids 1..1025" % ent["name"])
                    continue
                dup = _seen_pids & set(pids)
                if dup:
                    probs.append("pattern_line_pools: pid(s) %s listed in more than one line" % sorted(dup))
                _seen_pids |= set(pids)
    _allowed = {"line_pool_all", "caps", "pvp", "legacy_species_caps", "legacy_default_cap", "rarity_keep_all_pids", "rarity_ladders", "shadow_best_leagues", "rarity_floor_iv", "shiny_floor_iv", "shiny_floor_keep", "collection_floor_iv",
                "protected_keep_all_pids", "adventure_effect_pids", "origin_owners",
                "showcase_weights", "pvp_spread_keep", "rules", "per_species_caps", "pattern_line_pools", "_note"}
    for k in cfg:
        if k not in _allowed:
            probs.append("unknown top-level key '%s'" % k)
    return probs


def write(new_cfg):
    """Validate (raise ValueError on problems) then atomically write keep_config.json + reload."""
    merged = _deep_merge(DEFAULTS, new_cfg)
    probs = validate(merged)
    if probs:
        raise ValueError("invalid config: " + "; ".join(probs))
    merged["_note"] = DEFAULTS.get("_note", CFG.get("_note", "edited via dashboard"))
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    os.replace(tmp, PATH)
    reload()
    return merged
