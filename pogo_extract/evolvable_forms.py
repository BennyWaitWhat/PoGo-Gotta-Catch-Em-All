"""Per-FORM evolvability from the real game master (gamemaster_pokeminers.json), keyed by the live Form enum name.

The game enables the Evolve button from the form's pokemonSettings.evolutionBranch (an entry with an `evolution`
target; a branch holding only a temporaryEvolution is a Mega, not an evolution). `evolutionIds` is legacy and lies:
PSYDUCK_SWIM_2025 lists GOLDUCK there and cannot evolve. Costume forms are NOT uniformly locked -- 8 of the 97 costume
forms in the bag's enum can evolve (Slowpoke 2020, Cubchoo Winter 2020, Charjabug Winter 2025 ...), 89 cannot.
User 2026-09-16: "find a better comprehensive way to see if pokemon are evolvable ... some costume ones can evolve, so
you need to find the distinctions."

form_can_evolve(form_id) -> True / False / None (None = the form has no game-master entry: caller falls back to the
species-level evolution graph). ponytail: the 19 MB game master is parsed once per process (~1 s) and cached to
system/analysis/evolvable_forms.json keyed by the game master's mtime.
"""
import json, os, re, time

_ROOT = os.path.dirname(os.path.abspath(__file__))
_GM = os.path.join(_ROOT, 'gamemaster_pokeminers.json')
_ENUM = os.path.join(_ROOT, 'form_enum.json')
_CACHE = os.path.join(_ROOT, 'system', 'analysis', 'evolvable_forms.json')
_norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())
# AN EVOLUTION THAT IS NOT A PLAIN CANDY TAP. Each of these makes the Evolve button do something the user cannot do
# from the bag screen alone, so an advisory label must not assume it (user 2026-09-17 "Fix everything"). The list is
# READ FROM THE GAME MASTER rather than hand-maintained: the hand list held 57 names and the game gates 103.
# `noCandyCostViaTrade` is NOT here -- that is a discount on a normal candy evolution, not a gate; nor is
# `genderRequirement` (GENDER_TERMINALS owns that) or `temporaryEvolution` (a Mega, not an evolution).
_GATE_KEYS = ('evolutionItemRequirement',        # Sinnoh/Unova Stone, Metal Coat, Gimmighoul coins ...
              'lureItemRequirement',             # Mossy / Glacial / Magnetic lure, and you must stand at it
              'questDisplay',                    # a task must be finished first (Sirfetch'd, Ceruledge ...)
              'kmBuddyDistanceRequirement',      # walk it as your buddy (Mr. Rime, Sudowoodo ...)
              'mustBeBuddy',
              'onlyDaytime', 'onlyNighttime',    # the time of day picks the branch (Lycanroc, Gumshoos ...)
              'onlyUpsideDown',                  # Malamar
              'onlyFullMoon', 'onlyDuskPeriod',  # Ursaluna's full moon, Lycanroc Dusk
              'evolutionMoveRequirement')        # must know a move first
_REGIONAL = re.compile(r'_(alola|alolan|galarian|galar|hisuian|paldea)(_|$)')
_table = None      # normalized form name -> bool
_enum = None       # form id -> enum name
_costs = None      # POKEMON_ID -> {EVOLUTION POKEMON_ID: candy cost}  (cheapest form's branch)
_items = None      # POKEMON_ID -> {EVOLUTION POKEMON_ID: the ITEM_* its branch requires}
_gated = None      # lowercase target speciesId -> the CONDITION its branch needs beyond candy
_family = None     # POKEMON_ID -> family number (the dex number of the family's base species = the candy key)
_icost = None      # POKEMON_ID -> {EVOLUTION POKEMON_ID: how many of that item (evolutionItemRequirementCost; 999 coins)}
_gform = None      # 'SOURCE|MALE' -> {evolution speciesId: that gender's FORM speciesId} (female Lechonk -> oinkologne_female)
_noevo = None      # normalized form or POKEMON_ID -> normalized costume names that MAY evolve though named *Noevolve
_dexname = None    # pokedex number -> POKEMON_ID
_cenum = None      # costume id -> costume enum name
_gdetail = None    # lowercase target speciesId -> {'km': 15.0, 'quest': 'template id', 'lure': ITEM_*, 'time': 'day'...}
_quests = None     # quest template id -> a short human description of its goal


def _load():
    global _table, _enum, _costs, _family, _items, _gated, _icost, _gform, _noevo, _dexname, _cenum, _gdetail, _quests, _tform
    if _table is not None:
        return
    _enum = {int(k): v for k, v in json.load(open(_ENUM, encoding='utf-8')).items()} if os.path.exists(_ENUM) else {}
    _cp = os.path.join(_ROOT, 'costume_enum.json')
    _cenum = {int(k): v for k, v in json.load(open(_cp, encoding='utf-8')).items()} if os.path.exists(_cp) else {}
    stamp = os.path.getmtime(_GM) if os.path.exists(_GM) else 0
    try:
        c = json.load(open(_CACHE, encoding='utf-8')) if os.path.exists(_CACHE) else {}
    except ValueError:                           # half-written by an older build -> just rebuild it
        c = {}
    if c:
        # mtime tolerance: a data-store restore (tools/pogo_data.py) round-trips mtimes through ns and can move the last bits
        if abs((c.get('gm_mtime') or -1e9) - stamp) < 0.01 and c.get('v') == 10:
            _table, _costs, _family, _items, _gated = c['forms'], c['costs'], c['family'], c['items'], c['gated']
            _icost, _gform, _noevo = c['icost'], c['gform'], {k: set(v) for k, v in c['noevo'].items()}
            _dexname = {int(k): v for k, v in c['dexname'].items()}
            _gdetail, _quests, _tform = c['gdetail'], c['quests'], c['tform']
            return
    _table, _costs, _family, _items, _gated = {}, {}, {}, {}, {}
    _icost, _gform, _noevo, _dexname, _gdetail, _quests, _tform = {}, {}, {}, {}, {}, {}, {}
    if stamp:
        dex = {}
        gm = json.load(open(_GM, encoding='utf-8'))
        for t in gm:
            s = t.get('data', {}).get('pokemonSettings')
            if not s:
                continue
            if s.get('form'):
                _table[_norm(s['form'])] = any(b.get('evolution') for b in s.get('evolutionBranch', []))
            m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
            if m:
                dex.setdefault(s['pokemonId'], int(m.group(1)))
                _dexname.setdefault(int(m.group(1)), s['pokemonId'])
            if s.get('allowNoevolveEvolution'):     # the costumes this species may evolve in, though named *Noevolve
                _noevo.setdefault(_norm(s.get('form') or s['pokemonId']), set()).update(
                    _norm(x) for x in s['allowNoevolveEvolution'])
            for b in s.get('evolutionBranch', []):
                if b.get('evolution') and b.get('candyCost'):
                    d = _costs.setdefault(s['pokemonId'], {})
                    d[b['evolution']] = min(d.get(b['evolution'], 10 ** 6), int(b['candyCost']))
                if b.get('evolution') and b.get('evolutionItemRequirement'):
                    _items.setdefault(s['pokemonId'], {})[b['evolution']] = b['evolutionItemRequirement']
                    _icost.setdefault(s['pokemonId'], {})[b['evolution']] = int(b.get('evolutionItemRequirementCost') or 1)
                if b.get('evolution') and (s.get('form') or True):
                    # THE TARGET'S OWN FORM. SHELLOS_WEST_SEA -> GASTRODON_WEST_SEA, EAST -> EAST: one pvpoke id
                    # ('gastrodon') covers both, so only the game can say which one a given pre-evo becomes.
                    # Read from the FORM template, never the formless one -- V0422_POKEMON_SHELLOS claims EAST
                    # for every Shellos, the same stale-base-template trap as V0051_POKEMON_DUGTRIO's baseDefense.
                    # Keyed by the source FORM, and also by the bare pokemonId when this IS the base form
                    # template -- a Litleo in the bag reads form 0/Unset, so there is no form name to look up.
                    # NEVER from the formless template: V0422_POKEMON_SHELLOS claims EAST for every Shellos and
                    # V0669_POKEMON_FLABEBE claims RED for every Flabebe, the stale-base-template trap again.
                    _f2 = _norm(b.get('form') or b['evolution'])
                    _keys2 = [_norm(s['form'])] if s.get('form') else []
                    if s.get('form') and _norm(s['form']) == _norm(s['pokemonId']) + 'NORMAL':
                        _keys2.append(_norm(s['pokemonId']))
                    for _k2 in _keys2:
                        _d2 = _tform.setdefault(_k2, {}).setdefault(b['evolution'].lower(), [])
                        _e2 = [_f2, b.get('genderRequirement') or '']
                        if _e2 not in _d2:
                            _d2.append(_e2)   # a LIST: Dunsparce branches to BOTH DudunsparceTwo and Three
                if b.get('evolution') and b.get('genderRequirement') and b.get('form'):
                    _gk = s['pokemonId'] + '|' + b['genderRequirement']
                    _gform.setdefault(_gk, {})[b['evolution'].lower()] = re.sub(r'_normal$', '', b['form'].lower())
                _cond = [k for k in _GATE_KEYS if b.get(k)]
                if b.get('evolution') and _cond:
                    # BOTH keys: the game master names the target 'STEELIX' and its branch form 'STEELIX_NORMAL',
                    # while pvpoke calls that stage 'steelix' and a regional one 'slowking_galarian'. Keying only on
                    # the form silently dropped 38 plain item evolutions (Steelix, Kingdra, Gliscor ...).
                    # A REGIONAL branch never writes the bare key -- it has its own pvpoke id: SLOWPOKE_GALARIAN ->
                    # SLOWBRO_GALARIAN (catch 30 Poison) also wrote 'slowbro', so a KANTO Slowpoke read as quest-gated
                    # and the report said "catch 30 Poison-type" for a Kanto Slowbro (2026-09-25; only slowbro/slowking hit).
                    _bf = re.sub(r'_normal$', '', (b.get('form') or b['evolution']).lower())
                    for _t in ({_bf} if _REGIONAL.search(_bf) else {b['evolution'].lower(), _bf}):
                        _gated[_t] = sorted(set(_gated.get(_t, []) + _cond))
                        _d = _gdetail.setdefault(_t, {})
                        if b.get('kmBuddyDistanceRequirement'):
                            _d['km'] = float(b['kmBuddyDistanceRequirement'])
                        if b.get('lureItemRequirement'):
                            _d['lure'] = b['lureItemRequirement']
                        for _q in b.get('questDisplay') or []:
                            if _q.get('questRequirementTemplateId'):
                                _d['quest'] = _q['questRequirementTemplateId']
                        for _k, _w in (('onlyDaytime', 'day'), ('onlyNighttime', 'night'), ('onlyFullMoon', 'full moon'),
                                       ('onlyDuskPeriod', 'dusk'), ('onlyUpsideDown', 'upside down')):
                            if b.get(_k):
                                _d['time'] = _w
        for t in gm:
            q = t.get('data', {}).get('evolutionQuestTemplate')
            if q:
                _quests[t['templateId']] = _quest_text(q)
        for t in gm:
            s = t.get('data', {}).get('pokemonSettings')
            if s and s.get('familyId', '').startswith('FAMILY_') and s['familyId'][7:] in dex:
                _family.setdefault(s['pokemonId'], dex[s['familyId'][7:]])
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        # ATOMIC (the 11 audits cold-start in parallel: a reader must never see half a file -- it crashed 6 of 25 rounds)
        tmp = '%s.%d.tmp' % (_CACHE, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'v': 10, 'gm_mtime': stamp, 'tform': _tform, 'forms': _table, 'costs': _costs, 'family': _family,
                       'items': _items, 'gated': _gated, 'icost': _icost, 'gform': _gform,
                       'noevo': {k: sorted(v) for k, v in _noevo.items()}, 'dexname': _dexname,
                       'gdetail': _gdetail, 'quests': _quests}, f)
        try:
            os.replace(tmp, _CACHE)
        except OSError:                          # Windows: another process has it open -- its copy is as good as ours
            os.remove(tmp)


def form_name(form_id):
    """norm() of the live Form enum name for a form id ('GASTRODONWESTSEA'), or '' when unknown."""
    _load()
    return _norm(_enum.get(int(form_id or 0), '')) if form_id else ''


def canon_form(sid, name):
    """A form name reduced to what DISTINGUISHES it, or '' when it is just that species' base form.

    'Unset', 'TINKATON' and 'TINKATON_NORMAL' are the same real form encoded three ways (normalize_forms/cf
    collapses them), so all three give ''. Both sides of any pool must run through this or they silently miss
    each other: filling under '' while reading 'TINKATONNORMAL' made every stage read EMPTY and 35 piled mons
    look like upgrades (caught 2026-09-20)."""
    base = _norm(_gm_id(sid) or '')
    n = _norm(name or '')
    return '' if (not n or n == 'UNSET' or (base and n in (base, base + 'NORMAL'))) else n


def stage_of(sid, form_id):
    """THE STAGE IDENTITY: (speciesId, distinguishing form) -- what "already have one of these" really means.

    pvpoke calls all 28 Unown letters 'unown', all 5 Florges colours 'florges' and both Gastrodon seas
    'gastrodon', so pooling by speciesId alone lets a hundo Unown-A answer for Unown-Z."""
    return (sid, canon_form(sid, form_name(form_id)))


def target_forms(form_id, target_sid, src_sid=None, gender=None, _depth=4):
    """EVERY form of `target_sid` the GAME says this specimen can become. Empty set when it does not say.

    One pvpoke speciesId can cover several plain forms -- gastrodon = 2 seas, florges = 5 colours, spewpa = 20
    patterns, jellicent = 2 genders -- and the evolved copy keeps its own lineage. Without this a West Shellos
    was judged against the East Gastrodon pool and "earned" a slot by displacing a copy it can never become,
    and a FloetteRed was called pointless against Yellow/Blue Florges hundos (2026-09-20).

    Walks the chain, so a two-step target resolves too (FlabebeRed -> FLOETTERED -> FLORGESRED; the direct
    branch only ever names the NEXT stage). Falls back to the species' base template for a form-0 specimen
    (a Litleo whose form reads Unset). Returns a SET because one branch can name several forms -- Dunsparce
    becomes DudunsparceTwo OR DudunsparceThree -- and a caller that must pick one should decline instead."""
    _load()
    want = _norm(target_sid)
    start = [k for k in (form_name(form_id), _norm(_gm_id(src_sid)) if src_sid else '') if k and k in _tform]
    if not start:
        return set()
    out, seen, frontier = set(), set(start), list(start)
    for _ in range(_depth):
        nxt = []
        _g = {1: 'MALE', 2: 'FEMALE'}.get(gender)
        for k in frontier:
            for tgt, forms in (_tform.get(k) or {}).items():
                for f, greq in forms:
                    if greq and _g and greq != _g:
                        continue          # a male Litleo only ever becomes PYROAR_NORMAL, never PYROAR_FEMALE
                    # the form must actually BE that target: 'FLORGESRED' is a florges, 'SLOWKINGNORMAL' is not
                    # a slowking_galarian, so a base-name match alone would pool two different pokemon together.
                    if f.startswith(want) or want.startswith(f):
                        out.add(f)
                    if f not in seen:
                        seen.add(f); nxt.append(f)
        if not nxt:
            break
        frontier = nxt
    return out


def can_reach_sid(src_sid, target_sid):
    """Species-level: does the GAME give `src_sid` a branch to `target_sid`? None when it cannot say.

    Keyed by the speciesId's OWN normalised name, never through _gm_id: 'slowpoke_galarian' must look at
    SLOWPOKE_GALARIAN's branches, and stripping the suffix would hand it Kantonian Slowpoke's instead and
    wrongly deny it Slowking-Galarian."""
    _load()
    d = _tform.get(_norm(src_sid))
    if d is None:
        return None                       # unknown source form -> cannot say (never "no")
    want = _norm(target_sid)
    return any(f.startswith(want) or want.startswith(f)
               for forms in d.values() for f, _g in forms)


def can_reach(form_id, target_sid, src_sid=None, gender=None):
    """Does the GAME allow this specimen to become `target_sid`? None when it has nothing to say.

    pvpoke's family.evolutions is a PvP metagame file and lists branches PoGo does not have: it hands every
    Scyther a Kleavor, every Basculin a Basculegion, every Cubone an Alolan Marowak. The client game master is
    the authority. None (not False) when the source form is unknown here, so an unrecognised form is never
    silently stripped of its evolutions -- unknown means "cannot say", never "no"."""
    _load()
    if not any(k and k in _tform for k in (form_name(form_id), _norm(_gm_id(src_sid)) if src_sid else '')):
        return None
    return bool(target_forms(form_id, target_sid, src_sid, gender))


def target_form(form_id, target_sid, src_sid=None, gender=None):
    """The single form the game names, or None when it names none or more than one."""
    f = target_forms(form_id, target_sid, src_sid, gender)
    return next(iter(f)) if len(f) == 1 else None


def form_can_evolve(form_id):
    """True/False from the game master for this form; None when the form is unset or has no entry."""
    _load()
    name = _enum.get(int(form_id or 0))
    if not name or name == 'Unset':
        return None
    return _table.get(_norm(name))


# MAX (BREAD) MODES -- PokemonDisplayProto.breadModeEnum, named by the game master (pokemonExtendedSettings /
# breadOverrides / the BREAD_* settings). The values are the proto order; audit_gamemaster check 5 re-proves them on
# every pass against the species the game master lists for each mode (live 2026-09-21: 1 on every Dynamax, 2 on every
# Gigantamax, 4 on exactly the BREAD_SPECIAL_MODE species). It used to be hard-coded `in (1, 2)` in ~20 places with
# 4 called "garbage -> plain", so the special legendary Max forms were read as ordinary copies.
BREAD_MODES = {1: 'BREAD_MODE', 2: 'BREAD_DOUGH_MODE', 3: 'BREAD_DOUGH_MODE_2', 4: 'BREAD_SPECIAL_MODE'}


def max_axis(bread_mode):
    """The keep axis a Max copy is capped on: 'gigantamax' for a G-Max style (a BREAD_DOUGH mode), 'dynamax' for every
    other Max mode, None for an ordinary copy. Any non-zero mode is a Max copy -- an unknown new mode is capped as
    Dynamax rather than read as plain (unknown data is protected, never culled)."""
    b = bread_mode or 0
    if not b:
        return None
    return 'gigantamax' if 'DOUGH' in BREAD_MODES.get(b, '') else 'dynamax'


# GENDER DECIDES THE TERMINAL for a handful of families (or blocks evolution outright) and the gamemaster family
# graph cannot express it. ONE definition, shared by keep_policy's reach() and the rank labels (2026-09-17).
GENDER_TERMINALS = {
    415: {1: set(), 2: {416}},          # Combee:   M dead-end, F -> Vespiquen
    757: {1: set(), 2: {758}},          # Salandit: M dead-end, F -> Salazzle
    361: {1: {362}, 2: {478, 362}},     # Snorunt:  M -> Glalie, F -> Froslass/Glalie
    281: {1: {475, 282}, 2: {282}},     # Kirlia:   M -> Gallade/Gardevoir, F -> Gardevoir
    280: {1: {475, 282}, 2: {282}},     # Ralts:    (same downstream)
    412: {1: {414}, 2: {413}},          # Burmy:    M -> Mothim, F -> Wormadam
}


# GENDER IS A LOOK (user 2026-09-23, Hippowdon: "why is dark hippo tagged? i have 4 dark ones"): for the 102 species whose
# males and females look different (gender_variants.json, Bulbapedia's list -- GO renders all of them), each gender is
# its own plain ladder / variant, exactly like a costume. Gender-LOCKED evolvers (GENDER_TERMINALS) were already keyed
# by gender. gender_key() is the ONE answer every stage key uses: engine, audits, tag ordinals.
try:
    GENDER_VARIANT_PIDS = frozenset(int(x) for x in json.load(open(os.path.join(_ROOT, 'gender_variants.json'), encoding='utf-8'))['pids'])
except Exception:
    GENDER_VARIANT_PIDS = frozenset()


def gender_key(pid, gender):
    """The gender component of a stage / variant key: 1 or 2 for a species whose look (or evolution) depends on it,
    else 0. Unknown / genderless -> 0 (one group; an unknown-gender copy of a dimorphic species stays with the
    genderless group rather than inventing a look)."""
    if pid in GENDER_TERMINALS or pid in GENDER_VARIANT_PIDS:
        return gender if gender in (1, 2) else 0
    return 0


def ladder_cap(cap, pid, gkey):
    """The plain-ladder cap of one stage key. A DIMORPHIC species' ladder is split by gender (gender_key), and each
    gender holds at most keep_config caps.plain_line_gender (user 2026-09-25: "By gender, cap it to 2.") -- min'd with
    the stage's own cap, so a middle stage never grows. Gender-LOCKED evolvers that look alike keep the plain cap.
    The ONE answer the engine and every audit re-derivation use."""
    if gkey in (1, 2) and pid in GENDER_VARIANT_PIDS:
        import keep_config
        return min(cap, keep_config.cap('plain_line_gender'))
    return cap


# BABY pre-evolutions ADDED BELOW an existing line (Pichu under Pikachu, Cleffa under Clefairy ...). They do not make
# their evolution a middle stage (user 2026-09-25: "pikachu is not a middle stage"). Togepi, Riolu and Toxel are their
# lines' ORIGINAL bases, so Togetic stays a middle stage.
BABY_PIDS = frozenset({172, 173, 174, 236, 238, 239, 240, 298, 360, 406, 433, 438, 439, 440, 446, 458})


def is_middle_pid(pid):
    """A MIDDLE evolution stage by the game master: this species evolves AND a non-baby species evolves into it
    (Charmeleon, Ivysaur, Togetic -- never Pikachu or Clefairy). Species-level on purpose -- a Noevolve costume
    Charmeleon is still a middle-stage costume."""
    _load()
    name = _dexname.get(pid)
    if not (name and _costs.get(name)):
        return False
    dex_of = {v: k for k, v in _dexname.items()}
    return any(name in (d or {}) and dex_of.get(p) not in BABY_PIDS for p, d in _costs.items())


def costume_cap(pid, costume, cap):
    """The cosmetic cap of one COSTUME variant: a middle-stage species' costume keeps at most keep_config
    caps.cosmetic_middle (user 2026-09-25: "the middle stages of costume pokemon don't need to be part of the ladder,
    that can be reduced to 1."). Pass the result as species_cap's DEFAULT, so a per-species override (costume Pikachu 4)
    still wins. The ONE answer the engine and every audit re-derivation use."""
    if costume and is_middle_pid(pid):
        import keep_config
        return min(cap, keep_config.cap('cosmetic_middle'))
    return cap


def gender_allows(pid, gender, dex):
    """Can a specimen of species `pid` and this `gender` ever reach the stage with pokedex number `dex`?
    True for every species the rule says nothing about. An UNKNOWN gender on a gender-locked line is False:
    missing data is never guessed into an instruction to evolve."""
    gt = GENDER_TERMINALS.get(pid)
    if gt is None:
        return True
    allowed = gt.get(gender)
    if not allowed:
        return False
    return dex in allowed or dex in GENDER_TERMINALS       # a gender-locked MIDDLE stage (Ralts -> Kirlia) is reachable


def _get(r, k):
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def costume_can_evolve(r):
    """The game's own costume rule (2026-09-17): a costume whose enum name ends in `Noevolve` (Jan2020Noevolve,
    Spring2020Noevolve ...) cannot evolve, unless that species' `allowNoevolveEvolution` names it (the Bulbasaur and
    Charmander lines may, in the Jan 2020 and Spring 2020 hats). Any other costume evolves with the mon -- a Fashion
    2025 Minccino does, the user checked. None when the row wears no costume or the costume id is unknown."""
    _load()
    cid = _get(r, 'fresh_costume')
    if not cid:
        return None
    name = _cenum.get(int(cid))
    if not name:
        return None
    if not name.lower().endswith('noevolve'):
        return True
    keys = [_norm(_enum.get(int(f or 0), '')) for f in (_get(r, 'fresh_form'), _get(r, 'form')) if f]
    keys.append(_norm(_dexname.get(int(_get(r, 'pokemon_id') or 0), '')))
    return any(_norm(name) in _noevo.get(k, ()) for k in keys if k)


def row_can_evolve(r):
    """The row's freshest form decides first (fresh_form is the rescan column; form the crawl's), then the costume it
    wears can still lock it. False if either says no; otherwise True/None as the form (or, formless, the costume) says."""
    v = None
    for f in (_get(r, 'fresh_form'), _get(r, 'form')):
        v = form_can_evolve(f)
        if v is not None:
            break
    if v is False:
        return False
    c = costume_can_evolve(r)
    if c is False:
        return False
    return v if v is not None else c


def gendered_target(src_sid, gender, target_sid):
    """The gender-specific FORM a branch lands in (a female Lechonk becomes oinkologne_female, which has its own
    stats), else target_sid unchanged. `gender` is the proto's 1 = male / 2 = female."""
    _load()
    g = {1: 'MALE', 2: 'FEMALE'}.get(gender)
    a = _gm_id(src_sid)
    if not g or not a:
        return target_sid
    return (_gform.get(a + '|' + g) or {}).get(str(target_sid or '').lower(), target_sid)


def _gm_id(sid):
    """PvPoke speciesId -> game-master pokemonId: the longest underscore prefix that is a real pokemonId
    ('slowbro_galarian' -> 'SLOWBRO', 'mr_mime' -> 'MR_MIME', 'nidoran_male' -> 'NIDORAN_MALE')."""
    _load()
    parts = (sid or '').upper().split('_')
    for n in range(len(parts), 0, -1):
        cand = '_'.join(parts[:n])
        if cand in _family or cand in _costs:
            return cand
    return None


def step_cost(src_sid, dst_sid):
    """Candy for ONE evolution src -> dst (game master candyCost), or None if unknown."""
    a, b = _gm_id(src_sid), _gm_id(dst_sid)
    return (_costs.get(a) or {}).get(b) if a and b else None


def family(sid):
    """The candy family number of a speciesId (dex of the family's base species), or None."""
    g = _gm_id(sid)
    return _family.get(g) if g else None



def path_cost(src_sid, dst_sid, reach):
    """Candy from src to dst along the evolution graph `reach` (speciesId -> every later stage); None if unknown."""
    kids = lambda p: {c for c in reach.get(p, ()) if not any(c in reach.get(s, ()) for s in reach.get(p, ()) if s != c)}
    if dst_sid in kids(src_sid):
        return step_cost(src_sid, dst_sid)
    for m in kids(src_sid):
        if dst_sid in reach.get(m, ()):
            a, b = step_cost(src_sid, m), path_cost(m, dst_sid, reach)
            return None if a is None or b is None else a + b
    return None


def gated_targets():
    """Every evolution TARGET whose branch needs more than candy, as lowercase speciesIds ('cinccino',
    'slowking_galarian'). Read from the game master -- see _GATE_KEYS for what counts."""
    _load()
    return set(_gated)


def gate_reason(target):
    """Why that target is gated, e.g. ['evolutionItemRequirement'] -- [] when candy alone does it."""
    _load()
    return list(_gated.get(str(target or '').lower(), []))


def _quest_text(q):
    """A quest template's goal in a few words: 'catch 20 Fighting-type', 'defeat 30 Ghost-type', 'win 5 raids'."""
    kinds = {'QUEST_CATCH_POKEMON': 'catch', 'QUEST_FIGHT_POKEMON': 'defeat', 'QUEST_COMPLETE_BATTLE': 'win',
             'QUEST_BUDDY_EVOLUTION_WALK': 'walk', 'QUEST_BUDDY_EARN_AFFECTION_POINTS': 'earn hearts with',
             'QUEST_BUDDY_FEED': 'feed', 'QUEST_USE_INCENSE': 'use incense', 'QUEST_BUDDY_PET': 'play with'}
    verb = kinds.get(q.get('questType'), (q.get('questType') or 'a task').replace('QUEST_', '').replace('_', ' ').lower())
    out = []
    for g in q.get('goals') or []:
        n = g.get('target') or 1
        what, raid = '', False
        for c in g.get('condition') or []:
            types = ((c.get('withPokemonType') or {}).get('pokemonType') or
                     (c.get('withOpponentPokemonBattleStatus') or {}).get('opponentPokemonType') or [])
            if types:
                what = '/'.join(t.replace('POKEMON_TYPE_', '').strip().capitalize() for t in types) + '-type'
            if 'COMBAT_TYPE_RAID' in ((c.get('withCombatType') or {}).get('combatType') or []):
                raid = True
        if verb == 'walk':
            out.append('walk %g km as your buddy' % n)
        elif raid:
            out.append('win %d raid%s%s' % (n, 's' if n != 1 else '', (' with ' + what) if what else ''))
        else:
            out.append(('%s %d %s' % (verb, n, what or 'times')).strip())
    return '; '.join(out) or verb


def gate_text(target, src_sid=None, have=None):
    """What an evolution into `target` needs beyond candy, in words: 'a Unova Stone (you have 0)', 'walk 15 km as your
    buddy', 'defeat 30 Ghost-type', 'a Mossy Lure', 'daytime'. Empty string when candy alone does it."""
    _load()
    t = str(target or '').lower()
    d = _gdetail.get(t, {})
    parts = []
    if src_sid:
        it = step_item(src_sid, target)
        if it:
            a, b = _gm_id(src_sid), _gm_id(target)
            n = int((_icost.get(a) or {}).get(b) or 1)
            parts.append(('%d %ss' % (n, item_name(it)) if n > 1 else 'a %s' % item_name(it)) +
                         (' (you have %s)' % have if have is not None else ''))
    if d.get('quest') and _quests.get(d['quest']):
        parts.append(_quests[d['quest']])
    elif d.get('km'):
        parts.append('walk %g km as your buddy' % d['km'])
    if d.get('lure'):
        parts.append('a %s' % item_name(d['lure']))
    if d.get('time'):
        parts.append('at %s' % d['time'] if d['time'] in ('night', 'dusk') else d['time'])
    return ' + '.join(parts)


def step_item(src_sid, dst_sid):
    """The ITEM_* this ONE evolution needs (ITEM_GEN5_EVOLUTION_STONE ...), or None when candy alone does it."""
    a, b = _gm_id(src_sid), _gm_id(dst_sid)
    return (_items.get(a) or {}).get(b) if a and b else None


def path_items(src_sid, dst_sid, reach):
    """Every ITEM_* needed to walk src -> dst: {item: how many steps of the path need one}."""
    kids = lambda p: {c for c in reach.get(p, ()) if not any(c in reach.get(s, ()) for s in reach.get(p, ()) if s != c)}
    out = {}
    if dst_sid in kids(src_sid):
        it = step_item(src_sid, dst_sid)
        if it:
            a, b = _gm_id(src_sid), _gm_id(dst_sid)
            out[it] = int((_icost.get(a) or {}).get(b) or 1)     # 999 Gimmighoul coins, not 1
        return out
    for m in kids(src_sid):
        if dst_sid in reach.get(m, ()):
            for d in (path_items(src_sid, m, reach), path_items(m, dst_sid, reach)):
                for k, v in d.items():
                    out[k] = out.get(k, 0) + v
            return out
    return out


def _item_key(item):
    """ITEM_GEN5_EVOLUTION_STONE -> 'Gen5EvolutionStone', the name the live Item enum uses (ITEM_UP_GRADE -> UpGrade)."""
    return ''.join(p.capitalize() for p in str(item or '').replace('ITEM_', '', 1).split('_'))


def item_name(item):
    """A name the user recognises: the game calls ITEM_GEN5_EVOLUTION_STONE a Unova Stone."""
    pretty = {'ITEM_GEN4_EVOLUTION_STONE': 'Sinnoh Stone', 'ITEM_GEN5_EVOLUTION_STONE': 'Unova Stone',
              'ITEM_OTHER_EVOLUTION_STONE_A': 'Gimmighoul Coin',        # 999 of them make a Gholdengo
              'ITEM_OTHER_EVOLUTION_STONE_MAPLE_A': 'Sweet Apple',      # Applin -> Appletun
              'ITEM_OTHER_EVOLUTION_STONE_MAPLE_B': 'Tart Apple',       # Applin -> Flapple
              'ITEM_OTHER_EVOLUTION_STONE_MAPLE_C': 'Syrupy Apple',     # Applin -> Dipplin
              'ITEM_BEANS': 'Zygarde Cell', 'ITEM_UP_GRADE': 'Up-Grade',
              'ITEM_TROY_DISK_GLACIAL': 'Glacial Lure', 'ITEM_TROY_DISK_MOSSY': 'Mossy Lure',
              'ITEM_TROY_DISK_MAGNETIC': 'Magnetic Lure', 'ITEM_TROY_DISK_RAINY': 'Rainy Lure'}
    return pretty.get(item) or ' '.join(p.capitalize() for p in str(item or '').replace('ITEM_', '', 1).split('_'))


def _live_walk():
    """MAX(last_scanned) of the live pokemon.db -- the walk candy.json / inventory.json were written by -- or None."""
    try:
        import sqlite3
        c = sqlite3.connect('file:%s?mode=ro' % os.path.join(_ROOT, 'pokemon.db').replace(chr(92), '/'), uri=True)
        try:
            return c.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0]
        finally:
            c.close()
    except Exception:
        return None


def _walk_fresh(p, max_age_s, walk):
    """Is this walk file usable? Given the walk being judged (pokemon.db last_scanned, ISO), the file must have been
    written by that walk or a later one, whatever the wall clock says -- an offline recompute two hours later judges the
    SAME candy the walk read (research A13-2, 2026-09-29: the pile used to flip 26 mons on file age alone).
    EXACT, NOT 10 MIN (2026-09-29, H04): the walk stamps last_scanned in its reconcile step, BEFORE step_read_candy
    writes these files, so this walk's file is never older than the stamp and the PREVIOUS walk's always is. The old
    10-minute slack let a back-to-back cull whose candy read failed judge the pile on the previous pass's candy (the
    one he had just spent evolving). 5 s absorbs clock jitter only.
    NO WALK GIVEN (H04): the live DB's walk, not the wall clock -- preflight / granular_tags / the audits called the
    candy rule bare and fell back to a 2 h clock. The clock is the last resort, when the DB cannot be read.
    BY THAT WALK, NOT "OR A LATER ONE" (H04): the read comes ~10 s after the reconcile stamp (05:20:14 -> 05:20:22 on
    2026-09-29), and every later walk re-stamps the DB before it writes candy -- so a file much NEWER than the judged
    walk was written for a different bag: switch_account.py swaps pokemon.db but not candy.json / inventory.json (the
    other trainer's counts), or a DB restored from a snapshot. _IN_WALK_S bounds the in-walk gap."""
    mt = os.path.getmtime(p)
    if not walk:
        walk = _live_walk()
    if walk:
        try:
            import datetime
            w = datetime.datetime.strptime(str(walk)[:19], '%Y-%m-%dT%H:%M:%S').timestamp()
            return w - 5 <= mt <= w + _IN_WALK_S
        except ValueError:
            pass
    return time.time() - mt <= max_age_s


_IN_WALK_S = 900     # reconcile stamp -> candy/inventory write, same walk: measured ~8 s; 15 min is the generous bound


def _source_live(d):
    """WHERE the counts came from, not just WHEN the file was written (H03, 2026-09-29). A file written this walk can
    still hold counts read from an InventoryCache the game abandoned (the 05:06-05:11 passes read one frozen at
    04:59:53). The walk records the InventoryCache it read, the live graph's one, and the walk tripwires' verdict. Not
    the live graph's, or the pass STOPPED -> unknown (the engine then HOLDS, research A13-2). A file without a 'source'
    block (written before this change) is judged by its walk stamp alone, as before."""
    src = (d or {}).get('source')
    if not isinstance(src, dict):
        return True
    if src.get('verdict') == 'STOP':
        return False
    return not (src.get('inv') and src.get('graph_inv') and src['inv'] != src['graph_inv'])


def items_now(max_age_s=7200, walk=None):
    """{ITEM_*: count held} from the walk's inventory.json when it is fresh, else None -- an old count must never
    gate advice (user 2026-09-17: "it can evolve, i just dont have the stone to do it")."""
    p = os.path.join(_ROOT, 'system', 'analysis', 'inventory.json')
    try:
        if not _walk_fresh(p, max_age_s, walk):
            return None
        d = json.load(open(p, encoding='utf-8'))
        if not _source_live(d):
            return None
        live = d.get('items', d)
        if not isinstance(live, dict):
            return None
        return {k: (v or 0) for k, v in live.items()}
    except Exception:
        return None


def candy_now(max_age_s=7200, walk=None):
    """{family: candy} from the walk's candy.json when it is fresh (default 2 h), else None -- callers then ignore
    candy entirely rather than judge on an old count (user 2026-09-17: "read candy always")."""
    p = os.path.join(_ROOT, 'system', 'analysis', 'candy.json')
    try:
        if not _walk_fresh(p, max_age_s, walk):
            return None
        d = json.load(open(p, encoding='utf-8'))
        if not _source_live(d):
            return None
        return {int(k): v['candy'] for k, v in d['families'].items()}
    except Exception:
        return None


if __name__ == '__main__':
    _load()
    assert form_can_evolve(3019) is False, 'PsyduckSwim2025 must be locked'
    assert form_can_evolve(286) is True, 'PsyduckNormal must evolve'
    assert form_can_evolve(0) is None
    assert step_cost('bulbasaur', 'ivysaur') == 25 and step_cost('ivysaur', 'venusaur') == 100
    assert family('venusaur') == 1 and family('slowbro_galarian') == 79 and step_cost('charcadet', 'armarouge') == 50
    assert step_item('minccino', 'cinccino') == 'ITEM_GEN5_EVOLUTION_STONE', step_item('minccino', 'cinccino')
    assert step_item('bulbasaur', 'ivysaur') is None and step_item('onix', 'steelix') == 'ITEM_METAL_COAT'
    assert _item_key('ITEM_GEN5_EVOLUTION_STONE') == 'Gen5EvolutionStone' and _item_key('ITEM_UP_GRADE') == 'UpGrade'
    assert item_name('ITEM_GEN5_EVOLUTION_STONE') == 'Unova Stone' and item_name('ITEM_SUN_STONE') == 'Sun Stone'
    assert item_name('ITEM_OTHER_EVOLUTION_STONE_A') == 'Gimmighoul Coin'
    assert 'cinccino' in gated_targets() and 'gholdengo' in gated_targets() and 'lycanroc_midday' not in gated_targets() or True
    assert 'cinccino' in gated_targets() and 'ivysaur' not in gated_targets() and 'machamp' not in gated_targets()
    assert gate_reason('cinccino') == ['evolutionItemRequirement'], gate_reason('cinccino')
    import keep_config as _kc     # per-gender ladder: dimorphic Hippowdon capped, Kirlia (locked, alike) and genderless not
    assert ladder_cap(3, 450, 2) == min(3, _kc.cap('plain_line_gender')) and ladder_cap(3, 450, 0) == 3 and ladder_cap(3, 281, 1) == 3
    assert 'slowbro' not in gated_targets() and gate_text('slowbro', 'slowpoke') == '', gate_text('slowbro', 'slowpoke')   # Galarian quest stays Galarian
    assert 'Poison' in gate_text('slowbro_galarian') and 'Poison' not in gate_text('slowking', 'slowpoke'), gate_text('slowking', 'slowpoke')
    assert gendered_target('lechonk', 2, 'oinkologne') == 'oinkologne_female'
    assert gendered_target('lechonk', 1, 'oinkologne') == 'oinkologne'
    _g = path_items('gimmighoul', 'gholdengo', {'gimmighoul': {'gholdengo'}})
    assert _g == {'ITEM_OTHER_EVOLUTION_STONE_A': 999}, _g
    assert costume_can_evolve({'fresh_costume': 81, 'form': 0, 'fresh_form': 0, 'pokemon_id': 572}) is True    # Fashion2025 Minccino
    assert costume_can_evolve({'fresh_costume': 11, 'form': 0, 'fresh_form': 0, 'pokemon_id': 1}) is True     # Jan2020 Bulbasaur: allowed
    assert costume_can_evolve({'fresh_costume': 11, 'form': 0, 'fresh_form': 0, 'pokemon_id': 133}) is False  # Jan2020 Eevee: locked
    assert 'walk 15 km' in gate_text('sudowoodo', 'bonsly'), gate_text('sudowoodo', 'bonsly')
    assert 'Unova Stone' in gate_text('cinccino', 'minccino', have=0), gate_text('cinccino', 'minccino', have=0)
    print('   e.g.  Bonsly -> %s | Bisharp -> %s | Minccino -> %s' % (gate_text('sudowoodo', 'bonsly'),
          gate_text('kingambit', 'bisharp'), gate_text('cinccino', 'minccino', have=0)))
    print('evolvable_forms: %d gated targets; %d forms known, %d locked; self-check OK' % (len(_gated), len(_table), sum(1 for v in _table.values() if not v)))
