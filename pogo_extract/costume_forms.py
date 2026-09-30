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

Re-dump the enum (run classify_all_forms.py) when new costumes ship; the set updates on import.
If form_enum.json is absent, COSTUME_FORMS is empty (safe fallback: old plain behavior).
(built 2026-06-04 -- after the LaprasCostume2020 / form-encoded-costume miss.
 last enum refresh 2026-09-03 -- 1498 entries, max known form id 3380.)
"""
import os
import json
import re

_ROOT = os.path.dirname(os.path.abspath(__file__))
_ENUM = os.path.join(_ROOT, 'form_enum.json')
_REGION = ('ALOLA', 'GALAR', 'HISUI', 'PALDEA')
# costume keywords for the (rare) costumes whose enum name carries no year
_KW = ('COSTUME', 'KURTA', 'JEJU', 'HORIZON', 'GOGGLE', 'MONOCLE', 'VISOR', 'FEDORA', 'BEANIE',
       'KIMONO', 'YUKATA', 'PONCHO', 'SOMBRERO', 'BANDANA', 'SANTA', 'WITCH', 'WEDDING', 'TUXEDO',
       'POPSTAR', 'ROCKSTAR', 'LIBRE', 'STARMOBILE', 'FOSSIL', 'FLOWERCROWN', 'STRAWHAT', 'SCARF',
       'ANNIV', 'FLYING', 'GLASSES', 'MASK', 'HOOD', 'EARMUFF', 'NIGHTCAP', 'BOWTIE', 'CROCHET')
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
    if _YEAR.search(u) or any(k in u for k in _KW):
        return 'costume'
    return 'form'


LOAD_ERROR = None   # str reason the enum could not be read, else None (see enum_ok())


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
    return {f for f, nm in fmap.items() if classify(nm) == 'costume'}, fmap


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
            'max_known_form': _MAX_KNOWN_FORM, 'error': LOAD_ERROR}


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
