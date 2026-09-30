"""costume_forms.py -- which numeric `form` codes are COSTUMES, from the live game enum.

PoGo encodes a whole class of costumes directly in the PokemonDisplayProto.Form enum
(LaprasCostume2020, PikachuGofest2026CapBlue, CaterpieGofest2026, UmbreonGofest2024Mscarf ...)
-- SEPARATE from the `fresh_costume` field. Those specimens carry fresh_costume=0, so the
costume is invisible to any rule that only reads fresh_costume. This module reads the dumped
enum (form_enum.json, produced by system/scripts/game_read/classify_all_forms.py) and exposes
the set of costume form codes, so keep_policy (-> cosmetic top-4, NOT plain) and build_tagsets
(-> Event tag) treat a form-encoded costume as the cosmetic it is.

Classifier, on the enum NAME (ground truth):
  base     : '<Species>Normal'                              -> the plain form
  regional : contains Alola/Galar/Hisui/Paldea
  costume  : carries an event YEAR (19xx/20xx) OR a costume keyword
  form     : everything else (battle/natural/collectible -- Origin, Therian, Unown letters,
             Vivillon patterns, Flabebe colors ... none carry a year or costume keyword)

GAME-MASTER LAYER, ADD ONLY (2026-09-30, user: "do whats best and not lazy", shown five ways to decide it; LAW.md "WHAT COUNTS
AS A COSTUME"): the client game master (gamemaster_pokeminers.json) lists every form in formSettings.forms[] with its own
isCostume flag. A form is a costume if the NAME classifier above says so OR the game master flags it -- the flag can only ADD
protection, never take it away (the game leaves isCostume unset on event forms Niantic itself calls costumed: PsyduckSwim2025,
the four Copy2019 clones). On the 2026-09-30 enum (1,506 codes) and game master (1,449 forms) the flag adds MewtwoA,
GimmighoulCoinA1, PikachuKariyushi and PikachuDoctor (and Tshirt01-03, which TSHIRT also catches); 36 costumes only the name
rule knows stay costumes. 'FLYING' is a costume keyword for the Pikachu balloon outfits only: Arceus and Silvally use it as the
Flying TYPE (ArceusFlying, SilvallyFlying are plain forms). The game master lags the live enum, so a form the enum has and the
game master does not yet list can only be caught by name: 'TSHIRT' covers PikachuTshirt04-07.
COSTUME STATUS NEVER SILENTLY SHRINKS: with the game master file missing, unreadable or listing no forms, the LAST cached flags
(system/analysis/costume_gm_flags.json, whatever game master they were read from) stand in for it; only with neither does the
name rule work alone. GM_SOURCE / GM_NOTE / gm_layer_stamp() say which of the three happened (keep_policy stamps it into
pile_provenance.json, audit_gamemaster.py warns). Importing this module never raises and costs a few ms on a warm cache.

Re-dump the enum (run classify_all_forms.py) when new costumes ship; the set updates on import.
If form_enum.json is absent, COSTUME_FORMS is empty (safe fallback: old plain behavior).
(built 2026-06-04 -- after the LaprasCostume2020 / form-encoded-costume miss.
 last enum refresh 2026-09-03 -- 1498 entries, max known form id 3380.)
"""
import os
import json
import re
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
_ENUM = os.path.join(_ROOT, 'form_enum.json')
_GM = os.path.join(_ROOT, 'gamemaster_pokeminers.json')
_GM_CACHE = os.path.join(_ROOT, 'system', 'analysis', 'costume_gm_flags.json')   # formSettings flags, keyed by the game master's mtime
_norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())
_REGION = ('ALOLA', 'GALAR', 'HISUI', 'PALDEA')
_TYPE_FORM_SPECIES = ('ARCEUS', 'SILVALLY')   # every form of these is a TYPE form: 'ArceusFlying' = the Flying-type Arceus, not a balloon costume
# costume keywords for the (rare) costumes whose enum name carries no year
_KW = ('COSTUME', 'KURTA', 'JEJU', 'HORIZON', 'GOGGLE', 'MONOCLE', 'VISOR', 'FEDORA', 'BEANIE',
       'KIMONO', 'YUKATA', 'PONCHO', 'SOMBRERO', 'BANDANA', 'SANTA', 'WITCH', 'WEDDING', 'TUXEDO',
       'POPSTAR', 'ROCKSTAR', 'LIBRE', 'STARMOBILE', 'FOSSIL', 'FLOWERCROWN', 'STRAWHAT', 'SCARF',
       'ANNIV', 'FLYING', 'GLASSES', 'MASK', 'HOOD', 'EARMUFF', 'NIGHTCAP', 'BOWTIE', 'CROCHET',
       'TSHIRT')   # TSHIRT: Pikachu T-shirt outfits 01-07; the game master lists 01-03, 04-07 are in the enum but not (yet) in it
_YEAR = re.compile(r'(?:19|20)\d\d')


def classify(name):
    """-> 'base' | 'regional' | 'costume' | 'form' (battle/natural/collectible)."""
    if not name:
        return 'base'
    u = name.upper()
    if u.endswith('NORMAL'):
        return 'base'
    if any(r in u for r in _REGION):
        return 'regional'
    if _YEAR.search(u) or any(k in u for k in _KW if not (k == 'FLYING' and u.startswith(_TYPE_FORM_SPECIES))):
        return 'costume'
    return 'form'


LOAD_ERROR = None   # str reason the enum could not be read, else None (see enum_ok())

# WHERE THIS PROCESS'S GAME-MASTER FLAGS CAME FROM (set by gm_costume_flags() at import; audit_gamemaster.py reads it):
#   'game_master' -- the game master file on disk, parsed now or through its mtime-keyed cache (the healthy state)
#   'stale_cache' -- the file is missing / unreadable / lists no forms: the LAST cached flags stand in (costume status does not shrink)
#   'none'        -- neither: the name classifier alone decides (the pre-2026-09-30 behaviour, and the only one that can shrink)
GM_SOURCE = 'none'
GM_NOTE = None        # str why GM_SOURCE is not 'game_master', else None
GM_COUNTS = (0, 0)    # (forms the flags list, forms flagged isCostume)


def _read_cache(path):
    """-> (flags, gm_mtime) of the cached game-master flags; (None, None) when absent, unreadable or not a usable table.
    gm_mtime is None when the cache does not hold a number there (the flags are still usable as a stale fallback)."""
    try:
        c = json.load(open(path, encoding='utf-8'))
        flags = c['flags']
        if c.get('v') == 1 and isinstance(flags, dict) and flags:
            stamp = c.get('gm_mtime')
            return flags, (stamp if isinstance(stamp, (int, float)) else None)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None, None


def _parse_gm(path):
    """{normalised form name: bool} from the game master's formSettings; {} when it cannot be read or lists no forms.
    A form printed as its enum NUMBER (0.381.2 / 0.395.1 print some: 3018 for GIMMIGHOUL_COIN_A1) is named through form_enum.json:
    keyed '3018' its flag would never meet the form's name, and a game-master-only costume would silently stop being one."""
    try:
        flags, enum = {}, None
        for t in json.load(open(path, encoding='utf-8')):
            for f in (((t.get('data') or {}).get('formSettings') or {}).get('forms') or []):
                nm = f.get('form')
                if isinstance(nm, int) and not isinstance(nm, bool):
                    if enum is None:
                        enum = {int(k): v for k, v in json.load(open(_ENUM, encoding='utf-8')).items()}
                    nm = enum.get(nm)
                if nm:
                    flags[_norm(nm)] = bool(f.get('isCostume'))
        return flags
    except Exception:
        return {}


def _write_cache(path, stamp, flags):
    """Atomic (tmp + os.replace). A read-only checkout or a missing directory just skips the cache: callers re-parse."""
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'v': 1, 'gm_mtime': stamp, 'flags': flags}, fh)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _gm_layer(gm_path, cache_path):
    """-> (flags, source, note): the ladder documented on gm_costume_flags(). Pure of module state (the self-test drives it)."""
    try:
        stamp = os.path.getmtime(gm_path)
    except OSError:
        stamp = None
    cached, cached_stamp = _read_cache(cache_path)
    if stamp is not None:
        if cached is not None and cached_stamp is not None and abs(cached_stamp - stamp) < 0.01:   # tolerance as in evolvable_forms: a data-store restore moves the last bits
            return cached, 'game_master', None
        flags = _parse_gm(gm_path)
        if flags:
            _write_cache(cache_path, stamp, flags)
            return flags, 'game_master', None
        why = 'the game master (%s) is unreadable or lists no forms' % os.path.basename(gm_path)
    else:
        why = 'the game master (%s) is missing' % os.path.basename(gm_path)
    if cached is not None:
        try:
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(cached_stamp)) if cached_stamp is not None else 'an unknown date'
        except (ValueError, OverflowError, OSError):
            when = 'an unknown date'
        return cached, 'stale_cache', '%s -- the flags cached from the game master of %s stand in' % (why, when)
    return {}, 'none', '%s and there are no cached flags -- the name rule alone decides' % why


def gm_costume_flags():
    """{normalised form name: bool} -- the client game master's OWN isCostume verdict for every form it lists in
    formSettings (a form it does not list is simply absent). COSTUME STATUS NEVER SILENTLY SHRINKS (2026-09-30), so the
    source is a ladder: (1) the game master itself -- the 19 MB file is parsed once and the flags cached next to the other
    analysis files, keyed by its mtime (evolvable_forms keeps its own table the same way; a read-only checkout just
    re-parses); (2) when it is missing, unreadable or lists no forms: the LAST cached flags, whatever game master they
    came from; (3) only with neither: {} (the name classifier alone). GM_SOURCE / GM_NOTE / GM_COUNTS record which rung
    answered, for audit_gamemaster.py and the pile provenance. Never raises (this module is imported by ~20 tools)."""
    global GM_SOURCE, GM_NOTE, GM_COUNTS
    try:
        flags, GM_SOURCE, GM_NOTE = _gm_layer(_GM, _GM_CACHE)
    except Exception as e:
        flags, GM_SOURCE, GM_NOTE = {}, 'none', 'unexpected %s: %s -- the name rule alone decides' % (type(e).__name__, e)
    GM_COUNTS = (len(flags), sum(1 for v in flags.values() if v))
    return flags


def gm_layer_stamp():
    """-> {'source', 'forms', 'costumes', 'note'}: which rung of the ladder above this process used (pile_provenance.json)."""
    return {'source': GM_SOURCE, 'forms': GM_COUNTS[0], 'costumes': GM_COUNTS[1], 'note': GM_NOTE}


def _costume_set(fmap, gm):
    """The costume form codes of an enum {code: name} given the game's flags. ADD ONLY: the name says costume OR the game
    says costume -- the game's "not a costume" never removes a form."""
    return {f for f, nm in fmap.items() if classify(nm) == 'costume' or gm.get(_norm(nm))}


def _load():
    global LOAD_ERROR
    try:
        fmap = {int(k): v for k, v in json.load(open(_ENUM, encoding='utf-8')).items()}
    except Exception as e:
        LOAD_ERROR = '%s: %s' % (type(e).__name__, e)
        return set(), {}
    if not fmap:
        LOAD_ERROR = 'form_enum.json parsed but is EMPTY'
        return set(), {}
    return _costume_set(fmap, gm_costume_flags()), fmap


COSTUME_FORMS, FORM_ENUM = _load()


# Highest form id the dumped enum knows about. Anything ABOVE this shipped AFTER the dump, so the
# classifier has no name for it and cannot judge it.
_MAX_KNOWN_FORM = max(FORM_ENUM) if FORM_ENUM else 0


def enum_ok():
    """True iff form_enum.json actually loaded. FAIL-LOUD HOOK (2026-09-02).

    is_costume_form()'s unknown-form guard answers True for any id above the dump's max. That is the
    right answer for a HANDFUL of ids that shipped after the dump, but when the dump is MISSING
    entirely _MAX_KNOWN_FORM collapses to 0 and the guard silently reclassifies EVERY non-zero form
    as a costume -- which empties the plain pool, disables the whole plain-line cap and the evolve
    comb-up, and (measured 2026-09-02 on the live bag) moves 62 mons INTO the irreversible Transfer
    pile and 22 out of it. A total load failure is not a data point to guess from, it is a reason to
    stop: callers that produce irreversible output (keep_policy) MUST check this and abort.
    Deliberately advisory, not an import-time raise -- costume_forms is imported by ~20 read-only
    tools that must keep working without the dump.
    """
    return bool(FORM_ENUM) and LOAD_ERROR is None


def enum_stamp():
    """(path, mtime, entry-count, max-known-id) -- for provenance/staleness reporting by callers."""
    try:
        mt = os.path.getmtime(_ENUM)
    except OSError:
        mt = None
    return {'path': _ENUM, 'mtime': mt, 'entries': len(FORM_ENUM),
            'max_known_form': _MAX_KNOWN_FORM, 'error': LOAD_ERROR, 'gm_layer': gm_layer_stamp()}


def is_unknown_form(form_code):
    """True iff this form id has NO NAME in the enum dump -- we have no verdict for it.

    MEMBERSHIP, not "above the max" (2026-09-23): a new form can be added below the old max id (an event reusing a
    gap), and the max test waved it through as plain. The walk now refreshes form_enum.json every scan, so an
    unnamed id means the refresh itself failed -- still protected."""
    f = form_code or 0
    return bool(FORM_ENUM) and f != 0 and f not in FORM_ENUM


def is_costume_form(form_code):
    """True iff this numeric form code is a form-encoded COSTUME (per the live enum).

    UNKNOWN-FORM GUARD (2026-09-02): a form id NEWER than the enum dump returns True -- protected, not
    plain. An unrecognised form is missing data, and the standing rule is that missing data means
    PROTECTED. The fallback over-protects (a genuine new battle/regional form is merely kept, which is
    recoverable) rather than under-protects (a new costume gets released, which is not).
    Re-dump the enum with system/scripts/game_read/classify_all_forms.py to clear the guard.

    HISTORY -- the guard was added because form_enum.json had been dumped 2026-06-04 (max id 3348) while
    the live bag held ids 3351/3352/3353. Unnamed, those were classified 'not a costume', judged as PLAIN
    Pikachu, given the pre-evo plain cap of 2 instead of the cosmetic cap, and SEVEN landed in the
    irreversible Transfer pile.
    VINDICATED 2026-09-03: the enum was re-dumped from the live game (1479 -> 1498 entries, max 3348 ->
    3380) and all three resolved to real costumes -- GimmighoulCoinA22026, PikachuPxp2026, PikachuWcs2026
    -- so the guard's protective verdict was exactly right and the pile did not move (80 uids, membership
    unchanged). Those ids are now classified by NAME; the guard remains for whatever ships above 3380.
    """
    f = form_code or 0
    return f in COSTUME_FORMS or is_unknown_form(f)


def _col(r, k):
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def card_folds_into_costume(r):
    """True for a NON-shiny, NON-shadow COSTUME copy (costume, costume form, decoration or art background).

    COSTUME + BACKGROUND = ONE LADDER (user 2026-09-24: "if a costume and the SAME costume with a back ground, dont
    count them seperate"). Such a copy competes only in its costume's top-N (keep_policy _vkey ignores the card),
    where backgrounds_first() puts it AHEAD of the costume-only copies; the per-card ladder no longer holds it.
    Plain, Max-only, shiny and shadow copies keep their card ladder. ONE definition: engine, audit_cull, preflight."""
    if _col(r, 'fresh_shiny') or _col(r, 'fresh_alignment') == 1:
        return False
    deco = _col(r, 'costume_decoration_id')
    return bool((_col(r, 'fresh_costume') or 0) or (_col(r, 'fresh_natural_art_bg') or 0)
                or (deco and str(deco) != '0')
                or is_costume_form(_col(r, 'fresh_form')) or is_costume_form(_col(r, 'form')))


def backgrounds_first(rows_sorted):
    """BACKGROUNDS FIRST (user 2026-09-24: "the ones where a costume with a background/card CAN take the slot of one
    thats just a costume" -> "Backgrounds first"): stable partition of an IV-sorted costume ladder -- every costume
    copy that carries a background card ahead of the costume-only copies, each side in the caller's own order. Rows
    that are not folded costume copies (a Max-only variant, anything shiny or shadow) keep their place in the tail."""
    bg = lambda r: card_folds_into_costume(r) and _col(r, 'fresh_has_location_card') == 1
    return [r for r in rows_sorted if bg(r)] + [r for r in rows_sorted if not bg(r)]


def form_name(form_code):
    return FORM_ENUM.get(form_code or 0)


def _selftest():
    """python costume_forms.py --selftest -- offline and self-contained: golden names for the rules, and synthetic game masters
    in a temp dir for every rung of the fail-safe ladder (2026-09-30). Needs neither the real game master nor the DB."""
    import shutil
    import tempfile
    global _GM, _GM_CACHE, _gm_layer
    n = 0
    for nm, want in (('ArceusFlying', 'form'), ('SilvallyFlying', 'form'), ('PikachuFlying03', 'costume'),   # Flying TYPE forms are plain
                     ('PikachuFlying5ThAnniv', 'costume'), ('PikachuTshirt07', 'costume'), ('PsyduckSwim2025', 'costume'),
                     ('MewtwoA', 'form'), ('GimmighoulCoinA1', 'form'), ('PikachuNormal', 'base'), ('YamaskNormal', 'base'),
                     ('RaichuAlolan', 'regional'), ('UnownA', 'form'), ('', 'base'), (None, 'base')):
        assert classify(nm) == want, (nm, classify(nm), want)
        n += 1
    enum = {1: 'FooBar2019', 2: 'FooPlain', 3: 'FooSkin', 4: 'ArceusFlying'}
    assert _costume_set(enum, {}) == {1}
    assert _costume_set(enum, {_norm('FOO_SKIN'): True}) == {1, 3}                                  # the game adds ...
    assert _costume_set(enum, {_norm('FOO_BAR_2019'): False, _norm('ARCEUS_FLYING'): False}) == {1}   # ... and never removes
    assert {f for f, nm in FORM_ENUM.items() if classify(nm) == 'costume'} <= COSTUME_FORMS            # add only, on the live enum too
    assert set(gm_layer_stamp()) == {'source', 'forms', 'costumes', 'note'} and enum_stamp()['gm_layer'] == gm_layer_stamp()
    n += 5
    forms = lambda *fl: [{'templateId': 'FORMS_POKEMON_X', 'data': {'formSettings': {'pokemon': 'X', 'forms': list(fl)}}},
                         {'templateId': 'V0001_POKEMON_BULBASAUR', 'data': {'pokemonSettings': {}}}]
    d = tempfile.mkdtemp()
    save = (_GM, _GM_CACHE, _gm_layer)
    try:
        gm, cache = os.path.join(d, 'gm.json'), os.path.join(d, 'cache.json')

        def put(path, obj, mtime=None):
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(obj if isinstance(obj, str) else json.dumps(obj))
            if mtime:
                os.utime(path, (mtime, mtime))
        skin = {'FOOSKIN': True, 'FOOPLAIN': False}
        put(gm, forms({'form': 'FOO_SKIN', 'isCostume': True}, {'form': 'FOO_PLAIN'}), 1.0e9)
        assert _gm_layer(gm, cache) == (skin, 'game_master', None)                 # no cache: parsed, then cached
        assert json.load(open(cache))['v'] == 1 and abs(json.load(open(cache))['gm_mtime'] - 1.0e9) < 0.01
        assert _gm_layer(gm, cache) == (skin, 'game_master', None)                 # warm cache
        put(gm, forms({'form': 'FOO_SKIN', 'isCostume': True}, {'form': 'FOO_PLAIN', 'isCostume': True}), 1.0e9 + 100)
        both = {'FOOSKIN': True, 'FOOPLAIN': True}
        assert _gm_layer(gm, cache) == (both, 'game_master', None)                 # a newer game master is re-read, not served from the old cache
        os.remove(gm)
        f, src, note = _gm_layer(gm, cache)                                        # MISSING -> the last cached flags stand in
        assert (f, src) == (both, 'stale_cache') and 'is missing' in note and '2001-09' in note, (f, src, note)
        for junk in ('{not json', '[]', '[{"templateId": "X"}]', '{"a": 1}', '5', 'null', '[5, "x"]'):
            put(gm, junk)                                                          # unreadable / lists no forms / not a template list
            f, src, note = _gm_layer(gm, cache)
            assert (f, src) == (both, 'stale_cache') and 'unreadable or lists no forms' in note, (junk, f, src)
        os.remove(cache)
        f, src, note = _gm_layer(gm, cache)                                        # neither: the name rule alone, and it says so
        assert (f, src) == ({}, 'none') and 'no cached flags' in note, (f, src, note)
        os.remove(gm)
        f, src, note = _gm_layer(gm, cache)
        assert (f, src) == ({}, 'none') and 'is missing' in note and 'no cached flags' in note, (f, src, note)
        put(gm, forms({'form': 'FOO_SKIN', 'isCostume': True}), 1.0e9 + 200)
        for junk in ('garbage', '[]', '5', 'null', '{"v": 1, "flags": 5}', '{"v": 1, "flags": {}}', '{"v": 2, "flags": {"X": true}}',
                     '{"v": 1, "gm_mtime": "x", "flags": {"X": true}}', '{"v": 1, "gm_mtime": null, "flags": {"X": true}}'):
            put(cache, junk)                                                       # an unusable cache is ignored, never an exception
            assert _gm_layer(gm, cache) == ({'FOOSKIN': True}, 'game_master', None), junk
        assert _gm_layer(gm, os.path.join(d, 'no', 'such', 'dir', 'cache.json'))[1:] == ('game_master', None)   # cache dir missing: still answers
        n += 13
        _GM, _GM_CACHE = gm, cache                                                 # the public wrapper records the rung it used
        put(cache, {'v': 1, 'gm_mtime': 5.0, 'flags': {'OLD': True, 'OLD2': False}})
        os.remove(gm)
        assert gm_costume_flags() == {'OLD': True, 'OLD2': False} and GM_SOURCE == 'stale_cache' and GM_COUNTS == (2, 1) and GM_NOTE
        assert gm_layer_stamp()['source'] == 'stale_cache' and gm_layer_stamp()['costumes'] == 1
        put(gm, forms({'form': 'FOO_SKIN', 'isCostume': True}), 1.0e9 + 300)
        assert gm_costume_flags() == {'FOOSKIN': True} and GM_SOURCE == 'game_master' and GM_NOTE is None and GM_COUNTS == (1, 1)

        def _boom(*_a):
            raise RuntimeError('boom')
        _gm_layer = _boom                                                          # a bug inside the ladder degrades, never raises at import
        assert gm_costume_flags() == {} and GM_SOURCE == 'none' and 'RuntimeError' in GM_NOTE
        n += 4
    finally:
        _GM, _GM_CACHE, _gm_layer = save
        shutil.rmtree(d, ignore_errors=True)
        gm_costume_flags()                                                         # put the module's own state back
    print('costume_forms selftest: %d checks OK (layer now: %s)' % (n, GM_SOURCE))


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--selftest']:
        _selftest()
    else:
        print('usage: python costume_forms.py --selftest   (a library: importing it is all anything else needs)')
        sys.exit(2)
