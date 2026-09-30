"""Field-costume id -> human name, from the live-dumped game Costume enum (costume_enum.json).

`fresh_costume` / `display_costume` hold a PokemonDisplayProto.Costume id (1,7,11,49...). The game
names them by the EVENT they shipped in (Halloween2021, Jan2020, Nightcap...). This is the platform's
single source for turning that id into a label -- import it ANYWHERE a costume is shown (Studio,
deep_read, audits, tag labels). Dump/refresh the enum with dump_costume_enum.py.

  costume_name(11)  -> 'Jan 2020'
  costume_name(67)  -> 'Nightcap'
  costume_name(61)  -> 'GO Tour 2023 Bandana'
  raw_name(11)      -> 'Jan2020Noevolve'   (exact enum token; 'Noevolve' = can't-evolve flag)
"""
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
try:
    _ENUM = json.load(open(os.path.join(_HERE, 'costume_enum.json'), encoding='utf-8'))
    if not isinstance(_ENUM, dict):
        _ENUM = {}
except Exception:
    _ENUM = {}   # enum not dumped yet -> graceful fallback to 'Costume #N'

# tokens the camel-splitter would otherwise mangle / abbreviate
_FIX = (('Gotour', 'GO Tour'), ('Gofest', 'GO Fest'), ('Tcg', 'TCG'))


def _humanize(s):
    if not s:
        return ''
    if s.endswith('Noevolve'):          # game flag, not part of the costume's identity
        s = s[:-8]
    s = s.replace('Noevolve', '')
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)     # camelCase  -> camel Case
    s = re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', s)     # word before year: Halloween2021 -> Halloween 2021
    s = re.sub(r'(?<=\d)(?=[A-Z])', ' ', s)        # year before word: 2023Bandana   -> 2023 Bandana
    s = s.strip()
    for a, b in _FIX:
        s = s.replace(a, b)
    return s


def raw_name(cid):
    """Exact enum token (e.g. 'Halloween2021Noevolve'); '' if unknown or Unset."""
    try:
        cid = int(cid or 0)
    except (TypeError, ValueError):
        return ''
    if not cid:
        return ''
    v = _ENUM.get(str(cid))
    return '' if (v is None or v == 'Unset') else v


def costume_name(cid):
    """Human label (e.g. 'Halloween 2021'); '' for none/Unset; 'Costume #N' if the id isn't in the enum."""
    try:
        cid = int(cid or 0)
    except (TypeError, ValueError):
        return ''
    if not cid:
        return ''
    v = _ENUM.get(str(cid))
    if v is None:
        return 'Costume #%d' % cid          # enum not dumped or id newer than the dump
    if v == 'Unset':
        return ''
    return _humanize(v) or ('Costume #%d' % cid)


def loaded():
    """True if the costume enum is present (87+ entries) -- lets callers warn if it needs a redump."""
    return len(_ENUM) > 3
