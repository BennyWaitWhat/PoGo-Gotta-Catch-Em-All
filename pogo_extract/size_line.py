"""SIZE UP THE EVOLUTION LINE (user 2026-09-19: "i want the largest pokemon period, even if it means evolving them").

What the game actually does, verified 2026-09-19:
  * PokemonProto stores heightM_ (float), weightKg_ (float) and size_ (the HoloPokemonSize badge) -- there is NO
    stored scale factor, so the evolved height/weight are computed server-side on evolution.
  * The badge follows a z-score against the species' own numbers, z = (height - pokedexHeightM) / heightStdDev.
    Measured over 5,632 in-bag mons: XXS <= -4, XS about -4..-2, normal -2..+2, XL +2..+4, XXL >= +4.
  * Showcases score entries with a three-part formula the SERVER sends per contest
    (ContestScoreComponentType Height=1 / Weight=2 / Iv=3, each with its own CoefficientValue). The game master's
    default is height 800, weight 150, iv 50 -- the 0.80/0.15/0.05 this project ranks XXL keepers by.

VERIFIED 2026-09-19 on 297 matched evolutions from the walk snapshots: the size BADGE always carries through
(132/132 XXL stayed XXL; no badge changed at all), and the evolved height matches base' * height/base within 1% in
87% of cases (90th percentile 5.3%, worst 25%). So `stays_xxl` is a fact about the badge, while `project` supplies the
height for scoring and carries that error.
"""
import json
import math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
XXL_Z = 4.0                      # measured lower edge of the XXL badge (p5 = +4.02 over 250 XXL)
_BASE = None                     # score / z baseline: a size-form family is measured against its centre form
_OWN = None                      # each form's OWN numbers: what an evolution scales between (Super -> Super)
_XUP = None                      # each form's sizeSettings.xxlUpperBound (metres), when the template carries one
_BANDS = None                    # each form's SIX size bounds (xxsLower, xsLower, mLower, mUpper, xlUpper, xxlUpper), metres
_BAND_KEYS = ('xxsLowerBound', 'xsLowerBound', 'mLowerBound', 'mUpperBound', 'xlUpperBound', 'xxlUpperBound')
_ENUM = None
_norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())
_LIVE = None                     # system/analysis/showcase_gm_live.json: the GAME's own numbers, read every recrawl (2026-09-24)
_LIVE_DIFF = {'xup': 0, 'base': 0, 'stages': 0}   # how often the live read disagreed with gamemaster_pokeminers.json (live wins)


def _load():
    global _BASE, _OWN, _XUP, _BANDS, _ENUM
    if _BASE is not None:
        return
    _BASE = {}
    _XUP = {}
    _BANDS = {}
    centre, sized = {}, {}
    _gm = json.load(open(os.path.join(HERE, 'gamemaster_pokeminers.json'), encoding='utf-8'))
    for t in _gm:
        s = (t.get('data') or {}).get('pokemonSettings')
        m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
        if not s or not m:
            continue
        rec = (s.get('pokedexHeightM'), s.get('pokedexWeightKg'), s.get('heightStdDev'), s.get('weightStdDev'))
        keys = ['DEX%d' % int(m.group(1)), _norm(s['pokemonId'])]
        if s.get('form'):
            # ONE FORM NAME, TWO SPECIES (2026-09-23): V0029 and V0032 are both NIDORAN_NORMAL, so the bare form
            # key is last-writer-wins and scored Nidoran F against Nidoran M. The dex-qualified key cannot collide.
            keys += [_norm(s['form']), '%s:%s' % (keys[0], _norm(s['form']))]
            _BASE[keys[2]] = _BASE[keys[3]] = rec
        _BASE.setdefault(keys[0], rec)
        _BASE.setdefault(keys[1], rec)
        ss = s.get('sizeSettings')
        if ss and ss.get('xxlUpperBound'):
            for k in keys:
                _XUP.setdefault(k, ss['xxlUpperBound'])
                _BANDS.setdefault(k, tuple(ss.get(b) for b in _BAND_KEYS))
        if ss:
            sized.setdefault(s['pokemonId'], set()).update(keys)
            if (ss.get('mUpperBound') or 0) > (ss.get('mLowerBound') or 0):
                centre[s['pokemonId']] = rec
    # SIZE-FORM FAMILIES (2026-09-23). Only Pumpkaboo and Gourgeist carry a sizeSettings block, and there the badge is
    # NOT a z-score against the form's own numbers: each form's heights sit in fixed metre bands (Pumpkaboo Small
    # 0.3-0.4 = XS, Average 0.4-0.5 = M, Large 0.5-0.6 = XL, Super 0.6-0.8 = XXL), and a Super's pokedexHeightM (0.8)
    # is the TOP of its band -- so every XXL Super scored below average. The one form whose M band is not empty
    # (Average) is the family's centre: scores and z are measured against it. INFERRED from the GM bands, not from a
    # real showcase score. The EVOLUTION projection keeps each form's own record (_OWN): the rule measured on 297
    # evolutions, and it maps a Super's band top onto the target Super's (0.8 -> 1.7 m). Scaling by the centre (x2.25)
    # would put every Super above 0.756 m past GOURGEIST_SUPER's 1.7 m xxlUpperBound, a height the game cannot give.
    # THE REAL SIZE BANDS (2026-09-23): every species/form has an EXTENDED_V####_POKEMON_<FORM> template whose
    # pokemonExtendedSettings.sizeSettings carries the metre bounds the client uses (Get_PokemonExtendedSettings).
    # The XXL upper bound is NOT a fixed multiple of the pokedex height: Bulbasaur 1.225 = 1.75x, Ninetales 2.2 = 2.0x
    # -- and the showcase points divide by exactly that ratio (two on-screen samples reproduce to the point only with
    # the per-species value). Form keys override; species keys fill in.
    for t in _gm:
        x = (t.get('data') or {}).get('pokemonExtendedSettings')
        m = re.match(r'EXTENDED_V(\d{4})_POKEMON_', t.get('templateId', ''))
        ss = (x or {}).get('sizeSettings') or {}
        if not x or not m or not ss.get('xxlUpperBound'):
            continue
        dex = int(m.group(1))
        keys = ['DEX%d' % dex, _norm(x.get('uniqueId') or '')]
        bands = tuple(ss.get(b) for b in _BAND_KEYS)
        if x.get('form'):
            keys += [_norm(x['form']), 'DEX%d:%s' % (dex, _norm(x['form']))]
            _XUP[keys[2]] = _XUP[keys[3]] = ss['xxlUpperBound']
            _BANDS[keys[2]] = _BANDS[keys[3]] = bands
        _XUP.setdefault(keys[0], ss['xxlUpperBound'])
        _XUP.setdefault(keys[1], ss['xxlUpperBound'])
        _BANDS.setdefault(keys[0], bands)
        _BANDS.setdefault(keys[1], bands)
    # THE GAME OUTRANKS THE MONTHLY DUMP (2026-09-24, user: "5 should be done everytime"): every recrawl reads the client's
    # CONTEST_SETTINGS coefficients and each bag stage's EXTENDED sizeSettings + pokedex height/weight straight from
    # GameMasterData (pogo_pipeline.step_read_showcase_gm -> showcase_gm_live.json), the very calls Pokemod's
    # showcaseScoreMath makes. Where the live read has a number it WINS over gamemaster_pokeminers.json; the
    # disagreements are counted for full_audit.showcase_formula_step. No live file -> the monthly dump, unchanged.
    global _LIVE
    _LIVE = _load_live()
    if _LIVE:
        _enum = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'form_enum.json'), encoding='utf-8')).items()}
        for _key, _st in (_LIVE.get('stages') or {}).items():
            _pid, _fid = (int(x) for x in _key.split(':'))
            _fname = _norm(_enum.get(_fid, '')) if _fid else ''
            _ks = ['DEX%d:%s' % (_pid, _fname), _fname] if _fname else ['DEX%d' % _pid]
            _ss = (_st.get('ext') or {}).get('sizeSettings') or {}
            _xup = _ss.get('XxlUpperBound')
            _touched = False
            if _xup:
                _bands = tuple(_ss.get(b) for b in ('XxsLowerBound', 'XsLowerBound', 'MLowerBound', 'MUpperBound', 'XlUpperBound', 'XxlUpperBound'))
                for _k in _ks:
                    if _k in _XUP and abs((_XUP[_k] or 0) - _xup) > 1e-4:
                        _LIVE_DIFF['xup'] += 1
                    _XUP[_k] = _xup
                    _BANDS[_k] = _bands
                _touched = True
            _b = _st.get('base') or {}
            if _b.get('pokedexHeightM') and _b.get('pokedexWeightKg'):
                _rec = (_b['pokedexHeightM'], _b['pokedexWeightKg'], _b.get('heightStdDev'), _b.get('weightStdDev'))
                for _k in _ks:
                    _old = _BASE.get(_k)
                    if _old and _old[0] and (abs(_old[0] - _rec[0]) > 1e-4 or abs((_old[1] or 0) - _rec[1]) > 1e-3):
                        _LIVE_DIFF['base'] += 1
                    _BASE[_k] = _rec
                _touched = True
            if _touched:
                _LIVE_DIFF['stages'] += 1
    _OWN = dict(_BASE)
    for pid, ks in sized.items():
        if pid in centre:
            for k in ks:
                _BASE[k] = centre[pid]
    _ENUM = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'form_enum.json'), encoding='utf-8')).items()}


def _load_live():
    """showcase_gm_live.json when it exists and carries stages, else None (never raises)."""
    try:
        d = json.load(open(os.path.join(HERE, 'system', 'analysis', 'showcase_gm_live.json'), encoding='utf-8'))
        return d if d.get('stages') else None
    except Exception:
        return None


def live_coefficients():
    """The game's own CONTEST_SETTINGS coefficient row (heightCoefficient/weightCoefficient/ivCoefficient/
    xxlAdjustmentFactor) from the last live read, or None. _points scores by these when present."""
    _load()
    rows = ((_LIVE or {}).get('contest') or {}).get('coefficients') or []
    for c in rows:
        if all(isinstance(c.get(k), (int, float)) and c.get(k) > 0 for k in ('heightCoefficient', 'weightCoefficient', 'ivCoefficient')):
            return c
    return None


def live_status():
    """For full_audit: when the live read was made, what it covered, and how often it overrode the monthly file."""
    _load()
    d = _LIVE or {}
    return {'generated': d.get('generated'), 'pairs': d.get('pairs'), 'with_size_settings': d.get('with_size_settings'),
            'with_base': d.get('with_base'), 'coefficients': live_coefficients(), 'diff': dict(_LIVE_DIFF),
            'diff_total': _LIVE_DIFF['xup'] + _LIVE_DIFF['base'], 'errors': d.get('errors'), 'methods': d.get('methods')}


def _g(r, k):
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def _rec_for_row(r, own=False):
    """The row's base numbers. own=True: the form's OWN record even in a size-form family (evolution scaling)."""
    _load()
    tab = _OWN if own else _BASE
    for f in (_g(r, 'fresh_form'), _g(r, 'form')):
        name = _norm(_ENUM.get(int(f or 0), ''))
        rec = tab.get('DEX%d:%s' % (_g(r, 'pokemon_id') or 0, name)) or tab.get(name)
        if rec and rec[0]:
            return rec
    return tab.get('DEX%d' % (_g(r, 'pokemon_id') or 0))


def _xup_for_row(r):
    """The form's XxlUpperBound in metres when its template carries sizeSettings (Pumpkaboo / Gourgeist), else None."""
    _load()
    for f in (_g(r, 'fresh_form'), _g(r, 'form')):
        name = _norm(_ENUM.get(int(f or 0), ''))
        v = _XUP.get('DEX%d:%s' % (_g(r, 'pokemon_id') or 0, name)) or _XUP.get(name)
        if v:
            return v
    return _XUP.get('DEX%d' % (_g(r, 'pokemon_id') or 0))


def size_bands(r):
    """(xxsLower, xsLower, mLower, mUpper, xlUpper, xxlUpper) in metres for this mon's species/form, from the client's
    EXTENDED_ size settings; None when unknown. The badge bands: XXS [0], XS [1], M [2]..[3], XL ..[4], XXL ..[5]."""
    _load()
    for f in (_g(r, 'fresh_form'), _g(r, 'form')):
        name = _norm(_ENUM.get(int(f or 0), ''))
        v = _BANDS.get('DEX%d:%s' % (_g(r, 'pokemon_id') or 0, name)) or _BANDS.get(name)
        if v:
            return v
    return _BANDS.get('DEX%d' % (_g(r, 'pokemon_id') or 0))


def band_resolution(r):
    """'form' when the mon's own form template supplied its bounds, 'species' when only the species default did,
    None when nothing did -- for the coverage proof."""
    _load()
    dex = _g(r, 'pokemon_id') or 0
    for f in (_g(r, 'fresh_form'), _g(r, 'form')):
        name = _norm(_ENUM.get(int(f or 0), ''))
        if name and (_BANDS.get('DEX%d:%s' % (dex, name)) or _BANDS.get(name)):
            return 'form'
    return 'species' if _BANDS.get('DEX%d' % dex) else None


def showcase_points_range(r):
    """(min, max) exactly as Pokemod prints them: height and weight are shown rounded to 0.01, so the true values sit
    within +/-0.005 -- and the height range is CLAMPED to the mon's size band (an XXL cannot be below its XL upper
    bound). Pumpkaboo / Gourgeist take their badge from the form. None when the template is unknown."""
    rec = _rec_for_row(r, own=True)
    h, w = _g(r, 'height_m'), _g(r, 'weight_kg')
    if not rec or not rec[0] or not rec[1] or h is None or w is None:
        return None
    size = _g(r, 'pokemon_size_category') or 0
    name = _norm(_ENUM.get(int(_g(r, 'fresh_form') or _g(r, 'form') or 0), ''))
    for tag_, sz in (('SMALL', 2), ('AVERAGE', 3), ('LARGE', 4), ('SUPER', 5)):
        if name in ('PUMPKABOO' + tag_, 'GOURGEIST' + tag_):
            size = sz
    lo, hi = h - 0.005, h + 0.005
    b = size_bands(r)
    if b and all(v is not None for v in b):
        lo_b, hi_b = {1: (b[0], b[1]), 2: (b[1], b[2]), 3: (b[2], b[3]), 4: (b[3], b[4]), 5: (b[4], b[5])}.get(size, (None, None))
        if lo_b is not None:
            lo, hi = max(lo, lo_b), min(hi, hi_b)
    xup = _xup_for_row(r)
    a = _points(rec, xup, lo, w - 0.005, _g(r, 'iv_total'), size == 5)
    z = _points(rec, xup, hi, w + 0.005, _g(r, 'iv_total'), size == 5)
    if a is None or z is None:
        return None
    return (min(a, z), max(a, z))


def _points(rec, xup, h, w, iv, xxl):
    if not rec or not rec[0] or not rec[1] or h is None or w is None:
        return None
    import keep_config
    cfg = keep_config.showcase_weights()
    _lc = live_coefficients()                # the GAME's 800/150/50 when the recrawl read them (2026-09-24); keep_config otherwise
    hw, ww, iw = ((_lc['heightCoefficient'] / 1000.0, _lc['weightCoefficient'] / 1000.0, _lc['ivCoefficient'] / 1000.0) if _lc
                  else (cfg['height'], cfg['weight'], cfg['iv']))
    n = (xup / rec[0]) if xup else cfg['xxl_upper_factor']
    c = (h / rec[0]) / n
    u = (w / rec[1]) / (0.5 + n)
    d = (iv or 0) / 45.0
    return math.trunc(1000 * (hw * c + ww * u + iw * d) + (cfg['xxl_bonus'] if xxl else 0))


def showcase_points(r, h=None, w=None):
    """THE GAME'S SHOWCASE POINTS for a real specimen -- what Pokemod prints as "SHOWCASE: N PTS" (2026-09-23).

    Pokemod's showcaseScoreMath, reproduced on the user's screen to the point (Alolan Ninetales XXL 1.893 m /
    34.65 kg / 32 IV -> 1004-1008; the range is the +/-0.005 display rounding of height and weight):
        n = XxlUpperBound / pokedexHeightM   (the species/form's EXTENDED_ sizeSettings: 1.75x, 1.55x, 2.0x ... -- never a constant)
        points = trunc(800 * (h/pokedexHeightM)/n + 150 * (w/pokedexWeightKg)/(0.5+n) + 50 * IV/45 + 178 if XXL)
    Measured against the FORM's OWN template (a Gourgeist Super against GOURGEIST_SUPER's 1.7 m, n = 1), exactly as
    the overlay does. Verified on two screens (Ninetales 1004-1008, Arboliva 1039-1042). None when the template is
    unknown; keep_config xxl_upper_factor is the fallback only for a species with no EXTENDED template (0 today).
    Pass h / w to score a hypothetical size."""
    rec = _rec_for_row(r, own=True)
    return _points(rec, _xup_for_row(r), _g(r, 'height_m') if h is None else h, _g(r, 'weight_kg') if w is None else w,
                   _g(r, 'iv_total'), (_g(r, 'pokemon_size_category') or 0) == 5)


def showcase_points_at(sid, h, w, iv, xxl):
    """The points a specimen with these numbers would have AS `sid` (an evolution projection)."""
    _load()
    key = _norm(sid)
    xup = _XUP.get(key) or _XUP.get(_norm(str(sid).split('_')[0]))
    return _points(_rec_for_sid(sid, own=True), xup, h, w, iv, xxl)


def _rec_for_sid(sid, own=False):
    """speciesId -> that stage's base numbers ('slowbro_galarian' -> SLOWBRO_GALARIAN, else the plain species)."""
    _load()
    tab = _OWN if own else _BASE
    key = _norm(sid)
    return tab.get(key) or tab.get(_norm(str(sid).split('_')[0]))


def scale(r, own=False):
    """This specimen's height as a fraction of its species' base height, or None when the base is unknown."""
    rec = _rec_for_row(r, own)
    if not rec or not rec[0] or not r['height_m']:
        return None
    return (r['height_m'] or 0) / rec[0]


def z_now(r):
    rec = _rec_for_row(r)
    if not rec or not rec[0] or not rec[2]:
        return None
    return ((r['height_m'] or 0) - rec[0]) / rec[2]


def project(r, target_sid):
    """The evolved copy's (height, weight, z) at `target_sid` if the scale carries over. None when unknown."""
    sc = scale(r, own=True)
    tgt = _rec_for_sid(target_sid, own=True)
    src = _rec_for_row(r, own=True)
    ctr = _rec_for_sid(target_sid)                   # z is read against the score baseline (the family centre)
    if sc is None or not tgt or not tgt[0] or not ctr or not ctr[0] or not ctr[2] or not src or not src[1]:
        return None
    h = tgt[0] * sc
    w = tgt[1] * ((r['weight_kg'] or 0) / src[1]) if (tgt[1] and src[1]) else None
    return (h, w, (h - ctr[0]) / ctr[2])


def stays_xxl(r, target_sid=None):
    """MEASURED, not assumed (2026-09-19): across 297 matched evolutions in the walk history the size badge carried
    through EVERY time -- 132 of 132 XXL stayed XXL, and no badge of any kind changed. So an XXL pre-evo is an XXL at
    the next stage whatever the projected z says; the projection is only used for the SCORE, where it lands within 1%
    of the real height 87% of the time (worst case seen: 25%)."""
    return (r['pokemon_size_category'] or 0) == 5


def showcase_score(h, w, iv, gmaxh, gmaxw, weights):
    """The project's showcase score, on projected numbers -- same shape keep_policy ranks real XXL with."""
    return (weights['height'] * ((h or 0) / (gmaxh or 1)) + weights['weight'] * ((w or 0) / (gmaxw or 1))
            + weights['iv'] * ((iv or 0) / 45))


# EVOLUTION COUNTS EVERYWHERE (user 2026-09-24: "evolution should be considered everywhere and evrything"): the XXL keep
# scores a copy by the best points it has at its own stage OR at any later stage it can become. ONE implementation for
# keep_policy rule 7 and every mirror (build_tagsets, preflight_transfer, audit_cull, audit_tags_membership,
# audit_tag_truth, _spotdata, cull_cost_table).
_REACH = []


def later_stages(r, later_fn=None):
    """Every later stage (speciesId) THIS specimen can become: keep_policy.pvp_later_stages over the ONE evolution
    graph (form, costume and gender gates -- the reach Best GL/UL uses), minus any branch the client game master
    denies (evolvable_forms.can_reach False: pvpoke's Scyther -> Kleavor). `later_fn` lets keep_policy pass its own
    graph (built from the same two files). Empty when no graph can be built: the own stage alone decides (the rule
    before 2026-09-24), said once on stdout."""
    if later_fn is None:
        if not _REACH:
            try:
                _scr = os.path.join(HERE, 'system', 'scripts')
                if _scr not in sys.path:
                    sys.path.insert(0, _scr)
                import keep_policy as _kp
                _gr = _kp.build_evo_graph(json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8')),
                                          {e['pid'] for e in json.load(open(os.path.join(HERE, 'pokedex_hundos_live.json')))['entries']},
                                          with_all=True)
                _REACH.append(lambda x: _kp.pvp_later_stages(x, _gr))
            except Exception as _e:
                print('  (size_line: evolution graph unavailable -- %s; XXL judged at its own stage only)' % _e)
                _REACH.append(None)
        later_fn = _REACH[0]
    if not later_fn:
        return set()
    import evolvable_forms as _ef
    from pvp_iv_rule import pvid as _pv
    own = _pv(_g(r, 'species_name'), _g(r, 'form') or 0)
    return {t for t in later_fn(r)
            if _ef.can_reach(_g(r, 'fresh_form') or _g(r, 'form'), t, own, _g(r, 'gender')) is not False}


def projected_points(r, target_sid):
    """The showcase points r would have evolved into `target_sid`: its size scale carries over (project) and so does
    the XXL badge (stays_xxl, 132/132 measured). The same projection as showcase_plan.projected_score. None when a
    template is unknown."""
    p = project(r, target_sid)
    rec = _rec_for_sid(target_sid)
    if not p or not rec or not rec[0] or not rec[1] or p[1] is None:
        return None
    return showcase_points_at(target_sid, p[0], p[1], _g(r, 'iv_total') or 0, stays_xxl(r, target_sid))


_TYPES = None                    # each form's (type, type2) from the game master -- for TYPE showcases (2026-09-29)


def _load_types():
    """speciesId/form keys -> ('POKEMON_TYPE_X', ...) from gamemaster_pokeminers.json (the client's own templates),
    keyed exactly like _BASE so a stage id resolves the same way its points do."""
    global _TYPES
    if _TYPES is not None:
        return _TYPES
    _TYPES = {}
    for t in json.load(open(os.path.join(HERE, 'gamemaster_pokeminers.json'), encoding='utf-8')):
        s = (t.get('data') or {}).get('pokemonSettings')
        m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
        if not s or not m:
            continue
        tp = tuple(x for x in (s.get('type'), s.get('type2')) if x)
        keys = ['DEX%d' % int(m.group(1)), _norm(s['pokemonId'])]
        if s.get('form'):
            keys += [_norm(s['form']), '%s:%s' % (keys[0], _norm(s['form']))]
            _TYPES[keys[2]] = _TYPES[keys[3]] = tp
        _TYPES.setdefault(keys[0], tp)
        _TYPES.setdefault(keys[1], tp)
    return _TYPES


def _gm_form_of_sid(sid):
    """pvpoke speciesId -> the game master's own form name for the REGIONAL ids whose spelling differs (H09-3, 2026-09-29):
    'ninetales_alolan' -> NINETALES_ALOLA, 'wooper_paldean' -> WOOPER_PALDEA, 'tauros_blaze' -> TAUROS_PALDEA_BLAZE.
    Galarian / Hisuian ids already match the game master's spelling."""
    s = str(sid).lower()
    m = re.match(r'^tauros_(blaze|aqua|combat)$', s)
    if m:
        return 'tauros_paldea_' + m.group(1)
    return re.sub(r'_(alola|paldea)n(?=_|$)', r'_\1', s)


def types_for_sid(sid):
    """The types a stage (pvpoke speciesId, e.g. 'charizard', 'slowbro_galarian') has in the game master; () when unknown.
    A REGIONAL id resolves to its own form first (H09-3): the bare-species fallback gave an Alolan Ninetales Fire."""
    T = _load_types()
    return (T.get(_norm(_gm_form_of_sid(sid))) or T.get(_norm(sid)) or T.get(_norm(str(sid).split('_')[0])) or ())


def xxl_keepers(rows, later_fn=None):
    """THE XXL SHOWCASE KEEP -- ONE selection for keep_policy rule 7 and its mirrors (build_tagsets, preflight_transfer,
    audit_tags_membership, audit_tag_truth, _spotdata). audit_cull re-derives it on its own. Returns {uid_hex: why}.

    Candidates: XXL badge, height + weight known, best_points >= showcase_weights.min_points (None = unknown template:
    still a candidate -- unknown data is never fodder).
      (a) per PvP identity (species + battle form; cosmetics fold): the top species_cap('xxl') by best_points; a copy
          with an unknown template sorts by the old group-max score (below any known points). Tie: uid_hex.
      (b) caps.xxl_per_type > 0 (the XXL TRIM, user 2026-09-29, only when he says): also the top-N per TYPE -- the XXLs
          that can enter that type's showcase as themselves or as a later stage they can become, scored at that stage,
          that stage's points >= min_points. The game's own showcase data: 5 entries at once (ContestSettingsProto
          PlayerContestMaxEntries), one Pokemon per showcase, 2026 Showcase Tuesdays feature types + Good/Great Buddy.
    """
    import keep_config
    from collections import defaultdict
    from pvp_iv_rule import pvid
    w = keep_config.showcase_weights()
    mn = w['min_points']
    cand = []
    for r in rows:
        if (_g(r, 'pokemon_size_category') or 0) != 5 or _g(r, 'height_m') is None or _g(r, 'weight_kg') is None:
            continue
        p = best_points(r, later_fn)
        if p is None or p >= mn:
            cand.append((r, p))
    out = {}
    groups = defaultdict(list)
    for r, p in cand:
        groups[pvid(_g(r, 'species_name'), _g(r, 'form') or 0)].append((r, p))
    for lst in groups.values():
        gh = max((_g(r, 'height_m') or 0) for r, _ in lst) or 1
        gw = max((_g(r, 'weight_kg') or 0) for r, _ in lst) or 1
        def _score(rp):
            r, p = rp
            if p is not None:
                return p
            return w['height'] * ((_g(r, 'height_m') or 0) / gh) + w['weight'] * ((_g(r, 'weight_kg') or 0) / gw) \
                + w['iv'] * ((_g(r, 'iv_total') or 0) / 45)
        n = keep_config.species_cap('xxl', _g(lst[0][0], 'pokemon_id'), keep_config.cap('xxl'))
        for r, _ in sorted(lst, key=lambda rp: (-_score(rp), _g(rp[0], 'uid_hex')))[:n]:
            out[_g(r, 'uid_hex')] = 'species'
    per_type = keep_config.cap('xxl_per_type')
    if per_type:
        bytype = defaultdict(dict)
        for r, p in cand:
            if p is None:
                continue
            u = _g(r, 'uid_hex')
            stages = [(pvid(_g(r, 'species_name'), _g(r, 'form') or 0), showcase_points(r))]
            stages += [(t, projected_points(r, t)) for t in later_stages(r, later_fn)]
            for sid, pts in stages:
                if pts is None or pts < mn:
                    continue
                for ty in types_for_sid(sid):
                    if pts > bytype[ty].get(u, -1):
                        bytype[ty][u] = pts
        for ty, d in bytype.items():
            for u, _ in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:per_type]:
                out[u] = (out[u] + '+' if u in out else '') + 'type:' + ty.replace('POKEMON_TYPE_', '').lower()
    return out


def best_points(r, later_fn=None):
    """THE XXL KEEP'S POINTS (2026-09-24): the best of this copy's own showcase points and its projected points at
    every later stage it can become -- an XXL Rhydon at 1005 that would score 1104 as Rhyperior is a 1104. None when
    its OWN template is unknown: unknown data stays protected, exactly as before."""
    own = showcase_points(r)
    if own is None:
        return None
    best = own
    for t in later_stages(r, later_fn):
        p = projected_points(r, t)
        if p is not None and p > best:
            best = p
    return best


if __name__ == '__main__':
    import sqlite3, collections
    c = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'pokemon.db').replace('\\', '/'), uri=True)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1 AND height_m IS NOT NULL')]
    c.close()
    bad = [r for r in rows if z_now(r) is None]
    print('rows whose base numbers are unknown: %d of %d' % (len(bad), len(rows)))
    cat = collections.defaultdict(list)
    for r in rows:
        z = z_now(r)
        if z is not None:
            cat[r['pokemon_size_category'] or 0].append(z)
    for k in sorted(cat):
        v = sorted(cat[k])
        print('  badge %s: n=%-5d z from %+.2f to %+.2f' % (k, len(v), v[0], v[-1]))
    mis = sum(1 for r in rows if (r['pokemon_size_category'] or 0) == 5 and (z_now(r) or 0) < XXL_Z)
    print('XXL badges below the z>=%.1f line (form-mapping misses): %d' % (XXL_Z, mis))
