"""pogo_display.py -- how a pokemon.db row LOOKS and is NAMED in the game: its icon file, its display name, its look chips
and its location card. DISPLAY ONLY (2026-09-30): nothing here decides what is kept, tagged or released, and no stored
identifier (pvid, tag name, _pile_names, last_report.json) is ever derived from it.

ONE pure module, stdlib only, no side effects on import, no repo imports at import time (costume_forms is imported
lazily inside Names, so a CI checkout without game data still imports it). bag_art.py is the impure half (network,
cache, PNG codec, HTML); gen_bag_pulse.py reaches both through bag_art.

    IconIndex.load().resolve(row)   -> Match(fn, dropped): the pogo_assets icon file for the exact look, and which
                                       qualifiers (shiny / form / costume / gender) the mirror has NO art for
    Names.load().label(row)         -> "Galarian Farfetch'd", 'Wash Rotom', 'Castform (Rainy Form)': the game's own names
    Names.load().card_info(id)      -> CardInfo(name, kind, image_url) for a location card / special background
    look_chips(row, names)          -> [(text, css)]: shiny, shadow, costume, Dynamax / Gigantamax, XXL, lucky

Sources (both committed, both rebuilt by `python bag_art.py --refresh-index|--refresh-names`, never by hand):
  pogo_icon_index.txt      the file names of PokeMiners/pogo_assets 'Images/Pokemon - 256x256/Addressable Assets/' and
                           'Images/LocationCards/' at a named commit -- so a cull needs no listing API (api.github.com
                           answered 403 from a cloud session) and resolve() can only ever return a file of the SAME dex
  official_names_en.json   pokemon_name_%04d and form_* from the game's i18n_english.json
Never wire a stored identifier to these: species_name, form ids and costume ids stay the game's own numbers and strings.
"""
import collections
import json
import os
import re
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, 'pogo_icon_index.txt')
NAMES_PATH = os.path.join(HERE, 'official_names_en.json')
GM_PATH = os.path.join(HERE, 'gamemaster_pokeminers.json')       # the client game master (data store): card image + type
RAW = 'https://raw.githubusercontent.com/PokeMiners/pogo_assets/master/'
ICON_DIR = 'Images/Pokemon - 256x256/Addressable Assets/'         # a strict superset of 'Images/Pokemon/Addressable Assets/'
CARD_DIR = 'Images/LocationCards/'

# every name that reaches a URL or a cache path is validated first: no slash, no dot pair, no query characters
_ICON_RX = re.compile(r'^pm(\d+)((?:\.[a-z][A-Za-z0-9_]*)*)\.icon\.png$')     # build_art's pattern, verbatim
_SPRITE_OK = re.compile(r'^pm\d{1,5}(?:\.[A-Za-z0-9_]+)*\.icon\.png$')
_CARD_OK = re.compile(r'^[A-Za-z0-9_-]{1,120}$')
_COS_ALIAS = re.compile(r'^_(\d+)(Noevolve)?$')

# a name the walk stamps into ladder_history._pile_names / pokemon.db that the game spells differently (dex 29 / 32:
# 'Nidoran F' vs 'Nidoran♀'); Names.learn() adds any other mismatch it sees in the bag, this seed covers a bag with none
KNOWN_DB_NAMES = {'Nidoran F': 29, 'Nidoran M': 32}

_REGIONS = (('alolan', 'Alolan'), ('alola', 'Alolan'), ('galarian', 'Galarian'), ('galar', 'Galarian'),
            ('hisuian', 'Hisuian'), ('hisui', 'Hisuian'), ('paldean', 'Paldean'), ('paldea', 'Paldean'))   # costume_forms._REGION
_REGION_RX = re.compile('|'.join(k for k, _ in _REGIONS), re.I)
_REGION_ADJ = dict(_REGIONS)
# the game keys a form's i18n text under the family's showcase species: Scatterbug and Spewpa wear Vivillon's patterns
# ('Marine Pattern'), Wormadam wears Burmy's cloaks ('Plant Cloak'). dex -> the dex whose form_<species>_<form> keys apply.
FORM_FAMILY = {664: 666, 665: 666, 413: 412}

Match = collections.namedtuple('Match', 'fn dropped')                # fn None = no icon at all; dropped = wanted, absent
Match.approx = property(lambda self: bool(self.dropped))
CardInfo = collections.namedtuple('CardInfo', 'id name kind image_url')


def norm(s):
    """Lowercase a-z0-9 only, accents folded ('Flabébé' == 'Flabebe'), punctuation dropped ("Mr. Mime" == 'MrMime').
    build_art compared RAW text here and lost 8 Galarian Farfetch'd / Mr. Mime and 15 Flabébé colours to it."""
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', s.lower())


def humanize(s):
    """'IcySnow' -> 'Icy Snow', 'Fall2019' -> 'Fall 2019', 'Flying5ThAnniv' -> 'Flying 5th Anniv' (CamelCase and digit runs
    split; an ordinal stays whole)."""
    t = re.sub(r'(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z])', ' ', str(s or '')).strip()
    return re.sub(r'(\d) (St|Nd|Rd|Th)\b', lambda m: m.group(1) + m.group(2).lower(), t)


def _g(r, k):
    """row[k] for a dict or a sqlite3.Row; None when the column is absent."""
    try:
        return r[k]
    except (KeyError, IndexError, TypeError):
        return None


def _load_enum(path):
    """{int id: name} from one of the small committed enum files; {} when unreadable (callers degrade, never raise)."""
    try:
        return {int(k): v for k, v in json.load(open(path, encoding='utf-8')).items()}
    except Exception:
        return {}


def card_id(row):
    """The row's location card id, 0 when it has none. THE keep engine's own test (keep_policy / trophy_pick): the walk's
    fresh_has_location_card == 1 AND a non-zero fresh_loc_card_enum. Not loc_LocationCard (203 rows carry the fresh id but
    NULL there), not the retired special_bg_id, not fresh_natural_art_bg (0 on every row)."""
    return (_g(row, 'fresh_loc_card_enum') or 0) if _g(row, 'fresh_has_location_card') == 1 else 0


def sprite_path(fn):
    """Repo-relative asset path of an icon file name, or None when the name is not a plain pm<dex>...icon.png."""
    return ICON_DIR + fn if isinstance(fn, str) and _SPRITE_OK.match(fn) else None


def card_path(stem):
    return CARD_DIR + stem + '.png' if isinstance(stem, str) and _CARD_OK.match(stem) else None


def raw_url(path):
    return RAW + urllib.parse.quote(path)


# --------------------------------------------------------------------------------------------------- the icon index file
def read_index(path=INDEX_PATH):
    """-> (icon names, card stems, meta dict, error or None). The file is `# header` lines, `[icons]`, `[cards]` sections."""
    icons, cards, meta, sec = [], [], {}, None
    try:
        for raw in open(path, encoding='utf-8'):
            line = raw.strip()
            if not line:
                continue
            if line.startswith('#'):
                for k in ('commit', 'committed', 'listed'):
                    m = re.search(r'\b%s (\S+)' % k, line)
                    if m:
                        meta[k] = m.group(1)
                continue
            if line in ('[icons]', '[cards]'):
                sec = line
                continue
            (icons if sec == '[icons]' else cards if sec == '[cards]' else []).append(line)
    except Exception as e:
        return [], [], {}, '%s: %s' % (type(e).__name__, e)
    return icons, cards, meta, (None if icons else 'icon index holds no icons')


def split_listing(paths):
    """A repo-relative path listing -> (icon file names, card stems): only real pm<dex>...icon.png files directly in ICON_DIR,
    only .png files directly in CARD_DIR (the 96 *.portrait.png next to the icons are not sprites). A name that would not
    pass sprite_path / card_path validation never enters the index, so no later fetch can be handed an unsafe one."""
    icons = [p[len(ICON_DIR):] for p in paths if p.startswith(ICON_DIR) and '/' not in p[len(ICON_DIR):]]
    cards = [p[len(CARD_DIR):-4] for p in paths if p.startswith(CARD_DIR) and p.endswith('.png') and '/' not in p[len(CARD_DIR):]]
    return [n for n in icons if _ICON_RX.match(n) and _SPRITE_OK.match(n)], [c for c in cards if _CARD_OK.match(c)]


def format_index(icons, cards, commit, committed, listed):
    """The committed text form of the index (bag_art --refresh-index writes it; read_index reads it back)."""
    return ('# pogo_icon_index v1 -- PokeMiners/pogo_assets  commit %s  committed %s  listed %s\n'
            '# icons = file names in %r ; cards = stems in %r (every .png there)\n'
            '# Rebuilt by `python bag_art.py --refresh-index --tree FILE | --clone DIR`; never edit by hand.\n'
            '[icons]\n%s\n[cards]\n%s\n' % (commit, committed, listed, ICON_DIR, CARD_DIR,
                                            '\n'.join(sorted(icons)), '\n'.join(sorted(cards))))


class IconIndex:
    """(dex, form, costume, gender, shiny) -> icon file, and row -> icon: pokegenie_work/build_art.py's matcher, extracted
    (its copy is nested inside main(), so it cannot be imported) with three measured fixes:
      1. the species prefix is stripped from the form name after norm(), so Farfetch'd / Mr. Mime / Flabébé strip
      2. enum costume '_2' / '_2Noevolve' -> the upstream token COSTUME_2 / COSTUME_2_NOEVOLVE (Raichu costume 28)
      3. 'gender' counts as a dropped qualifier only for a species that HAS a female (.g2) icon
    A ladder that never leaves the dex keeps the guarantee build_art documents: a mon is never given another
    species' picture. Whole bag 2026-09-30: 5,733 rows, 0 without an icon, 99.0% with the exact look."""

    def __init__(self, icon_names=(), card_stems=(), form_enum=None, costume_enum=None, meta=None):
        self.icons = {}                                        # (dex, form token, costume token, gender token, shiny) -> file
        self.form_tok = collections.defaultdict(dict)          # dex -> norm(token) -> token
        self.cos_tok = collections.defaultdict(dict)
        self.g2 = set()                                        # dex that HAVE a female (.g2) icon
        self.dexes = set()
        self.form_enum, self.costume_enum = form_enum or {}, costume_enum or {}
        self.meta, self.error = dict(meta or {}), None
        for n in sorted(icon_names):                           # sorted: last wins for a duplicate key, as in build_art
            m = _ICON_RX.match(n)
            if not m:
                continue
            dex, f, c, g, s = int(m.group(1)), '', '', '', False
            parts = [x for x in m.group(2).split('.') if x]
            if any(len(x) == 1 and x in 'fcg' for x in parts):
                continue        # upstream's bare 'pm479.f.icon.png' (Rotom) would overwrite the plain key with an empty token
            for part in parts:
                if part == 's':
                    s = True
                elif part[0] == 'f':
                    f = part[1:]
                elif part[0] == 'c':
                    c = part[1:]
                elif part[0] == 'g':
                    g = part[1:]
            self.icons[(dex, f, c, g, s)] = n
            self.dexes.add(dex)
            if f:
                self.form_tok[dex].setdefault(norm(f), f)
            if c:
                self.cos_tok[dex].setdefault(norm(c), c)
            if g == '2':
                self.g2.add(dex)
        self.cards = set(card_stems)
        self._cards_ci = {c.lower(): c for c in sorted(self.cards)}

    @classmethod
    def load(cls, path=INDEX_PATH, root=HERE):
        """Never raises: an unreadable index is an empty one (every resolve() says 'species'), `.error` says why."""
        icons, cards, meta, err = read_index(path)
        fe, ce = _load_enum(os.path.join(root, 'form_enum.json')), _load_enum(os.path.join(root, 'costume_enum.json'))
        ix = cls(icons, cards, fe, ce, meta)
        ix.error = err or (None if fe and ce else 'form_enum.json / costume_enum.json unreadable')
        return ix

    def _form_token(self, dex, name, species):
        if not name or name.lower() in ('unset', 'normal'):
            return ''
        vocab = self.form_tok.get(dex)
        if not vocab:
            return ''
        n, sp = norm(name), norm(species)
        for cand in (n, n[len(sp):] if sp and n.startswith(sp) else ''):   # the token may or may not repeat the species
            if cand and cand in vocab:                                    # 'pm19.fALOLA' but 'pm201.fUNOWN_A'
                return vocab[cand]
        return ''

    def _cos_token(self, dex, name):
        if not name or name.lower() == 'unset':
            return ''
        m = _COS_ALIAS.match(name)
        if m:                                                             # enum '_2' -> upstream COSTUME_2 (FIX 2)
            name = 'COSTUME_%s%s' % (m.group(1), '_NOEVOLVE' if m.group(2) else '')
        return self.cos_tok.get(dex, {}).get(norm(name), '')

    def _pick(self, dex, f, c, g, shiny):
        """Most specific existing icon, shiny-first: shiny accuracy is preferred over qualifier depth (build_art.pick)."""
        ladder = ((f, c, g), (f, c, ''), (f, '', g), ('', c, g), (f, '', ''), ('', c, ''), ('', '', g), ('', '', ''))
        for want in ((True, False) if shiny else (False,)):
            for ff, cc, gg in ladder:
                n = self.icons.get((dex, ff, cc, gg, want))
                if n:
                    return n, (ff, cc, gg, want)
        return None, None

    def resolve(self, row):
        """-> Match(fn, dropped). Inputs are pokemon.db's fresh_* columns first (as build_art and the keep engine do)."""
        dex = _g(row, 'pokemon_id') or 0
        fid = _g(row, 'fresh_form')
        fid = _g(row, 'form') if fid is None else fid
        fname = self.form_enum.get(fid or 0, '')
        # a form id the enum has never heard of is NOT known to be plain: flag the sprite instead of silently claiming it
        want_form = (bool(fname) and fname.lower() not in ('unset', 'normal') and not fname.upper().endswith('NORMAL')) \
            or (bool(fid) and bool(self.form_enum) and fid not in self.form_enum)
        f = self._form_token(dex, fname, _g(row, 'species_name'))
        cid = _g(row, 'fresh_costume') or 0
        cname = self.costume_enum.get(cid, '')
        want_cos = bool(cid) and cname.lower() != 'unset'
        c = self._cos_token(dex, cname)
        g = '2' if _g(row, 'gender') == 2 else ''
        shiny = bool(_g(row, 'fresh_shiny'))
        fn, used = self._pick(dex, f, c, g, shiny)
        if fn is None:
            return Match(None, ('species',))
        ff, cc, gg, ws = used
        dropped = []
        if shiny and not ws:
            dropped.append('shiny')
        if want_form and not ff:
            dropped.append('form')
        if want_cos and not cc:
            dropped.append('costume')
        if g and not gg and dex in self.g2:       # FIX 3: a female Lechonk legitimately wears the plain icon
            dropped.append('gender')
        return Match(fn, tuple(dropped))

    def card_stem(self, image_url):
        """A game-master imageUrl -> the stem of its PNG in CARD_DIR: exact, else case-insensitive (9 of 246 differ only in
        case), else the imageUrl as given (an index older than the card: the fetch's 404 is negative-cached); None when
        the name is not a plain identifier."""
        if not isinstance(image_url, str) or not _CARD_OK.match(image_url):
            return None
        if image_url in self.cards:
            return image_url
        return self._cards_ci.get(image_url.lower()) or image_url


# ------------------------------------------------------------------------------------------------------------ names
class Names:
    """The game's own display names (i18n_english.json, distilled into official_names_en.json) with today's names as the
    fallback for everything: an empty Names (BAG_ART=0, a missing or corrupt file) returns the fallback from every call."""

    def __init__(self, species=None, forms=None, form_enum=None, costume_enum=None, card_enum=None, gm=None, gm_path=GM_PATH):
        self.species_map = dict(species or {})               # dex -> 'Mr. Mime'
        self.forms = dict(forms or {})                       # norm(i18n key minus 'form_') -> 'Plant Cloak'
        self.form_enum, self.costume_enum, self.card_enum = form_enum or {}, costume_enum or {}, card_enum or {}
        self.on = bool(self.species_map)
        self.error = None
        self._species_norm = {norm(v) for v in self.species_map.values()}
        self._db_names = dict(KNOWN_DB_NAMES)                # DB spelling -> dex, for fix_stamped
        self._gm, self._gm_path = gm, gm_path                # None = read the game master on the first card lookup
        self._classify = None

    @classmethod
    def empty(cls):
        return cls()

    @classmethod
    def load(cls, root=HERE, path=None, gm_path=None):
        """Never raises. Missing / corrupt official_names_en.json -> an empty Names (`.error` says why)."""
        species, forms, err = {}, {}, None
        try:
            d = json.load(open(path or os.path.join(root, 'official_names_en.json'), encoding='utf-8'))
            species = {int(k): str(v) for k, v in d['species'].items() if str(v).strip()}
            forms = {str(k): str(v) for k, v in d['forms'].items() if str(v).strip()}
        except Exception as e:
            species, forms, err = {}, {}, '%s: %s' % (type(e).__name__, e)
        n = cls(species, forms, _load_enum(os.path.join(root, 'form_enum.json')), _load_enum(os.path.join(root, 'costume_enum.json')),
                _load_enum(os.path.join(root, 'location_card_enum.json')), gm_path=gm_path or os.path.join(root, 'gamemaster_pokeminers.json'))
        n.error = err
        return n

    def species(self, dex, fallback=''):
        return (self.species_map.get(dex) if self.on else None) or fallback

    def learn(self, rows):
        """Remember every DB spelling the game spells differently, so fix_stamped can map old stamped text."""
        if self.on:
            for r in rows:
                db, dex = _g(r, 'species_name'), _g(r, 'pokemon_id')
                if db and dex and self.species(dex, db) != db:
                    self._db_names.setdefault(db, dex)

    def fix_stamped(self, text):
        """'Nidoran F 71%' (ladder_report stamps '<DB name> <iv>%' and keeps doing so) -> 'Nidoran♀ 71%'. Unknown text
        passes through unchanged."""
        if self.on and text:
            for db in sorted(self._db_names, key=len, reverse=True):
                if text.startswith(db + ' '):
                    return self.species(self._db_names[db], db) + text[len(db):]
        return text

    def stage(self, sid, dex):
        """A pvpoke speciesId as the game spells it -- 'mr_mime' -> 'Mr. Mime', 'raichu_alolan' -> 'Alolan Raichu',
        'farfetchd_galarian' -> "Galarian Farfetch'd", 'nidoran_female' -> 'Nidoran♀' -- or None. `dex` is the pvpoke entry's own
        number. Only an id that is exactly '<species>' or '<species>_<region>' is respelled: a form (giratina_altered), a shadow
        or a mega gets None and the caller keeps its own rendering."""
        base = self.species(dex, '')
        if not base or not sid:
            return None
        parts = str(sid).split('_')
        adj = _REGION_ADJ.get(parts[-1]) if len(parts) > 1 else None
        stem = norm('_'.join(parts[:-1]) if adj else sid)
        if stem == norm(base) or (dex in (29, 32) and stem in ('nidoranfemale', 'nidoranmale')):   # pvpoke: 'Nidoran Female' / 'Male'
            return (adj + ' ' if adj else '') + base
        return None

    # -- forms
    def _words(self, text):
        return {norm(w) for w in re.findall(r'[^\W_]+', text)}

    def _text_ok(self, text, own):
        """A species-LESS i18n key ('form_white' = 'White Kyurem') may only name the row's own species: the typo'd key
        form_squakabilly_white would otherwise hand a white Squawkabilly the text 'White Kyurem'. Word based, not a
        substring test ('Overcast Form' contains 'castform')."""
        return not any(w in self._species_norm and w != own for w in self._words(text))

    def _costume_class(self, name):
        if self._classify is None:
            try:
                import costume_forms
                self._classify = costume_forms.classify
            except Exception:
                self._classify = lambda _n: 'form'          # no classifier: the form stays in the name, never lost
        return self._classify(name)

    def _form_parts(self, row):
        """-> (label, costume chip text). The chip text is a form-encoded costume kept OUT of the name (PikachuWinter2020)."""
        dex, db = _g(row, 'pokemon_id') or 0, _g(row, 'species_name') or ''
        if not self.on:
            return db, ''
        sp = self.species(dex, db)
        fid = _g(row, 'fresh_form')
        fid = _g(row, 'form') if fid is None else fid
        fname = self.form_enum.get(fid or 0, '')
        if not fname or fname.lower() == 'unset' or fname.upper().endswith('NORMAL'):
            return sp, ''
        tail = _strip_species(fname, db)
        if tail == fname and sp != db:
            tail = _strip_species(fname, sp)
        adj, rest = '', tail
        m = _REGION_RX.search(tail)
        if m:                                             # the game builds 'Alolan Raichu' the same way
            adj, rest = _REGION_ADJ[m.group(0).lower()], tail[:m.start()] + tail[m.end():]
        pre = adj + ' ' if adj else ''
        n, own = norm(fname), norm(sp)
        pref = next((p for p in (norm(db), own) if p and n.startswith(p)), '')
        rem_n = n[len(pref):] if pref else n                             # species out, region token kept: 'paldeaaqua'
        rem = norm(rest)                                                 # region token out too: 'aqua'
        fam = norm(self.species(FORM_FAMILY.get(dex), ''))
        off = None
        for key, generic in ((n, False), (own + rem if rem else '', False), (fam + rem if fam and rem else '', False),
                             (rem_n, True), (rem, True)):
            t = self.forms.get(key) if key else None
            if t and (not generic or self._text_ok(t, own)):
                off = t
                break
        if off:                                                          # 'Wash Rotom' already names the species: use it alone
            return pre + (off if own in self._words(off) else '%s (%s)' % (sp, off)), ''
        if self._costume_class(fname) == 'costume':
            return pre + sp, humanize(rest or tail)
        if not rest:
            return pre + sp, ''
        return pre + '%s (%s)' % (sp, humanize(rest)), ''

    def label(self, row):
        """Galarian Farfetch'd, Castform (Rainy Form), Unown (A): regional adjective + species + form, all from the game's
        own strings, the DB species_name when there is nothing better. Copies are not named by sex."""
        return self._form_parts(row)[0]

    def costume_bits(self, row):
        """Chip texts for a costume: the fresh_costume enum name and/or a form-encoded costume (both can apply)."""
        out = []
        cid = _g(row, 'fresh_costume') or 0
        if cid:
            nm = self.costume_enum.get(cid, '')
            out.append(_costume_text(nm) if nm and nm.lower() != 'unset' else 'costume')
        if self.on:
            t = self._form_parts(row)[1]
            if t:
                out.append(t)
        return out

    # -- location cards
    def _gm_cards(self):
        """{norm(locationCard): its locationCardSettings} from the client game master's templates (a list, as in
        gamemaster_pokeminers.json), read on the FIRST card lookup only: 0.2 s and ~60 MB that a pile with no card never pays."""
        if not isinstance(self._gm, dict):
            cards = {}
            try:
                gm = self._gm if isinstance(self._gm, list) else json.load(open(self._gm_path, encoding='utf-8'))
                for t in gm:
                    s = ((t or {}).get('data') or {}).get('locationCardSettings')
                    if s and s.get('locationCard'):
                        cards[norm(s['locationCard'])] = s
            except Exception:
                cards = {}                                   # no game master here: every card shows as text
            self._gm = cards
        return self._gm

    def card_info(self, card_id):
        """A row's location card / special background -> CardInfo(id, name, kind, image_url). kind is the game's own
        label ('Special Background' / 'Location Background'): the game master's cardType when it has one (69 of 246), else
        the enum name ('specialbackground' in it). image_url is None when the game master has no entry (a card newer than
        the client game master copy): the row then shows kind + name as text."""
        raw = self.card_enum.get(card_id)
        if not raw:
            return CardInfo(card_id, 'Card #%s' % card_id, 'Background', None)
        ent = self._gm_cards().get(norm(raw))
        ctype = (ent or {}).get('cardType')
        special = (ctype == 'SPECIAL_BACKGROUND') if ctype in ('SPECIAL_BACKGROUND', 'LOCATION_CARD') else 'specialbackground' in norm(raw)
        human = re.sub(r'^Lc', '', raw)
        human = re.sub(r'^Specialbackground', '', human)
        human = humanize(re.sub(r'001$', '', human) or human)
        url = (ent or {}).get('imageUrl')
        return CardInfo(card_id, human or raw, 'Special Background' if special else 'Location Background',
                        url if isinstance(url, str) and _CARD_OK.match(url) else None)


def _strip_species(fname, species):
    """The raw remainder of a form enum name after its species prefix, ignoring punctuation and accents in the species:
    'FarfetchdGalarian' / "Farfetch'd" -> 'Galarian'; a name that does not start with the species comes back whole."""
    sp = norm(species)
    i = j = 0
    while i < len(fname) and j < len(sp):
        c = norm(fname[i])
        if c == '':
            i += 1
        elif c == sp[j]:
            i += 1
            j += 1
        else:
            return fname
    return fname[i:] if j == len(sp) else fname


def _costume_text(name):
    """'Holiday2016' -> 'Holiday 2016', '_2Noevolve' -> 'Costume 2' (the Noevolve suffix is the game's evolve lock)."""
    n = re.sub(r'Noevolve$', '', name)
    m = re.match(r'^_(\d+)$', n)
    return 'Costume %s' % m.group(1) if m else humanize(n)


def look_chips(row, names=None, max_axis=None):
    """[(text, css class)] for what makes THIS copy look different: shiny, shadow, costume, Max, XXL, lucky. `max_axis` is
    evolvable_forms.max_axis (injected: this module imports nothing from the repo)."""
    out = []
    if _g(row, 'fresh_shiny'):
        out.append(('shiny', 'sh'))
    if _g(row, 'fresh_alignment') == 1:
        out.append(('shadow', 'sd'))
    for t in (names.costume_bits(row) if names else ([] if not _g(row, 'fresh_costume') else ['costume'])):
        out.append((t, 'co'))
    b = _g(row, 'fresh_bread_mode') or 0
    if b:
        ax = max_axis(b) if max_axis else ('gigantamax' if b == 2 else 'dynamax')
        out.append(('Gigantamax' if ax == 'gigantamax' else 'Dynamax', 'mx'))
    if (_g(row, 'pokemon_size_category') or 0) == 5:
        out.append(('XXL', ''))
    if _g(row, 'is_lucky'):
        out.append(('lucky', 'lk'))
    return out
