"""studio_data.py -- READ-ONLY data layer for the Curation Studio.

Decodes internal code-words to human names, maps specimens to local sprite art, lists specimens per
special category with the engine's keep-reasons, and flags which are "over the cap line" (cull
candidates) at the current OR a proposed cap. NEVER writes the DB or pushes tags; opens sqlite ?mode=ro.
Mirrors keep_policy's bucketing (cf form-normalization + rarity variant key) so the Studio's counts
match the engine.
"""
import os
import re
import sys
import json
import sqlite3
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'system', 'scripts'))
import keep_config
import evolvable_forms   # BREAD_MODES / max_axis: the game's own Max-mode names
import costume_names   # field-costume id -> real event name (Halloween 2021, Nightcap, ...) from the dumped enum
from costume_forms import is_costume_form   # form-ENCODED costumes (LaprasCostume2020) carry fresh_costume=0 (audit F28)
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
from pvp_iv_rule import pvid
RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS

DB = os.path.join(HERE, 'pokemon.db')
POLICY = os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json')
SPRITE_DIR = os.path.join(os.path.dirname(HERE), 'pokegenie_work', 'extracted', 'Pokedex')

CATS = {
    'gigantamax': {'label': 'Gigantamax', 'cap': 'gigantamax', 'kind': 'bread', 'bread': 2},
    'dynamax':    {'label': 'Dynamax',    'cap': 'dynamax',    'kind': 'bread', 'bread': 1},
    'rarity':     {'label': 'Legendary & Rare', 'cap': 'rarity', 'kind': 'rarity'},
    'shiny':      {'label': 'Shiny',      'cap': 'shiny',      'kind': 'simple', 'col': 'fresh_shiny'},
    'xxl':        {'label': 'XXL',        'cap': 'xxl',        'kind': 'simple', 'col': 'size5'},
    'cosmetic':   {'label': 'Costumes & Backgrounds', 'cap': 'cosmetic', 'kind': 'cosmetic'},
}

_PROTECT_NOTE = {
    'shiny': 'Keeps the top-N HIGHEST-IV of EACH variant (every form / costume is its own card with its own keep line). Hundo and only-copy shinies are always kept (🔒); a richer shiny (bg/costume/Dmax/Gmax) outranks at the cap margin, but shinies are NEVER collapsed by richer copies — only the cap limits them. Nothing is released here — excess is tagged for transfer.',
    'gigantamax': 'Top-N highest-IV per species. Hundo / only-copy / location-card etc. are kept regardless (🔒). Excess is tagged for transfer, never released here.',
    'dynamax': 'Top-N highest-IV per species. Specials (hundo, only-copy, etc.) kept regardless (🔒). Excess is tagged for transfer, never released here.',
    'rarity': 'Top-N highest-IV per variant (form × shadow × Dynamax), PLUS your best Great-League and Ultra-League ranked one is always kept. Mewtwo is keep-all. Specials kept regardless (🔒). Excess is tagged for transfer, never released here.',
    'xxl': 'Top-N by showcase score (height-weighted) per variant. Shiny / hundo / etc. kept regardless (🔒). Excess is tagged for transfer, never released here.',
    'cosmetic': 'Top-N highest-IV of EACH distinct costume / background variant (own card, own keep line). Shiny / lucky / hundo kept regardless (🔒). Excess is tagged for transfer, never released here.',
}


def _ro():
    c = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def _j(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


_FORM = _j(os.path.join(HERE, 'form_enum.json'), {})
_LOC = _j(os.path.join(HERE, 'location_card_enum.json'), {})
_MOVE = _j(os.path.join(HERE, 'move_id_to_name.json'), {})
_LABELS = _j(os.path.join(HERE, 'curation_labels.json'), {})
_BGS = {'1': 'Special background', '65': 'Event background', '119': 'Event background',
        '256': 'Legendary event background', '65536': 'Legendary event background'}


def _camel(s):
    if not s:
        return ''
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)
    s = re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', s)
    s = re.sub(r'(?<=\d)(?=[A-Za-z])', ' ', s)
    return s.strip()


def decode_form(code):
    if not code:
        return ''
    o = _LABELS.get('form', {}).get(str(code))
    return o if o else _camel(_FORM.get(str(code), ''))


def decode_loc(enum):
    if not enum:
        return ''
    o = _LABELS.get('loc', {}).get(str(enum))
    if o:
        return o
    t = _LOC.get(str(enum), '')
    t = re.sub(r'^Lc', '', t)
    t = t.replace('Specialbackground', 'Special BG ')   # keep trailing digits so distinct enums stay distinct
    return _camel(t)


def decode_bg(bid):
    if not bid:
        return ''
    return _LABELS.get('bg', {}).get(str(bid)) or _BGS.get(str(bid)) or ('Background #' + str(bid))


def decode_move(mid):
    return (_MOVE.get(str(mid), '') or '').replace('_', ' ').title()


_REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')


def _build_cf(rows):
    bc = defaultdict(Counter)
    for r in rows:
        f = r['form'] or 0
        reg = (r['form_region'] or '').strip().lower()
        if f != 0 and reg in ('', 'normal', 'kantonian', 'none', 'null') and not any(x in pvid(r['species_name'], f) for x in _REGSUF):
            bc[r['pokemon_id']][f] += 1
    base = {pid: c.most_common(1)[0][0] for pid, c in bc.items() if len(c) == 1}

    def cf(r):
        f = r['form'] or 0
        return base.get(r['pokemon_id'], f) if f == 0 else f
    return cf


def sprite_rel(pid, form=0):
    """Return the local sprite FILENAME for (pid, form) if it exists, else None (client falls back to CDN)."""
    cands = []
    fn = decode_form(form) if form else ''
    for suf in ('Alola', 'Galarian', 'Hisuian', 'Paldean', 'Mega'):
        if fn and suf.lower() in fn.lower():
            cands.append('%d_%s.jpg' % (pid, suf))
    cands.append('%d.jpg' % pid)
    for c in cands:
        if os.path.isfile(os.path.join(SPRITE_DIR, c)):
            return c
    return None


def sprite_path(fname):
    p = os.path.join(SPRITE_DIR, os.path.basename(fname))
    return p if os.path.isfile(p) else None


def _ivkey(r):
    return (-(r['iv_total'] or 0), -(r['cp'] or 0))


def _badges(r):
    """EVERY distinguishing attribute of THIS mon -- so a card can never hide what a copy actually is.
    Cosmetics/backgrounds belong here (not only in the card title) because a coarse card (e.g. all shinies
    of a form, or all legendaries of a form) holds mons with DIFFERENT cosmetics."""
    b = []
    iv = r['iv_total'] or 0
    if r['fresh_shiny']:
        b.append('Shiny')
    if iv == 45:
        b.append('Hundo')
    elif iv == 0:
        b.append('Nundo')
    if r['fresh_alignment'] == 1:
        b.append('Shadow')
    elif r['fresh_alignment'] == 2:
        b.append('Purified')
    if r['is_lucky']:
        b.append('Lucky')
    elif r['is_traded']:
        b.append('Traded')
    _ax = evolvable_forms.max_axis(r['fresh_bread_mode'])
    if _ax == 'gigantamax':
        b.append('Gmax')
    elif _ax == 'dynamax':
        b.append('Dmax')
    sz = r['pokemon_size_category'] or 0
    if sz == 5:
        b.append('XXL')
    # XXS badge intentionally not surfaced (user: not interested in XXS) -- audit F13
    # --- cosmetics / collectibles: ALWAYS surfaced per-mon (was the gap that hid Zamazenta's location cards) ---
    if r['fresh_costume']:
        b.append('Costume: ' + (costume_names.costume_name(r['fresh_costume']) or ('#%s' % r['fresh_costume'])))
    elif is_costume_form(r['fresh_form']):   # form-ENCODED costume (fresh_costume=0) must still read as a Costume (audit F28)
        _cfn = decode_form(r['fresh_form']) or ''
        _sp = (r['species_name'] or '')
        if _cfn.lower().startswith(_sp.lower()):
            _cfn = _cfn[len(_sp):].strip()
        b.append('Costume: ' + (_cfn or ('form #%s' % r['fresh_form'])))
    if r['special_bg_id']:
        b.append('BG: ' + (decode_bg(r['special_bg_id']) or ('#%s' % r['special_bg_id'])))
    if (r['fresh_natural_art_bg'] or 0):   # fresh_ col -- non-fresh holds garbage (audit F1)
        b.append('Art BG')
    if r['fresh_has_location_card'] and r['fresh_loc_card_enum']:
        b.append('Location: ' + (decode_loc(r['fresh_loc_card_enum']) or ('#%s' % r['fresh_loc_card_enum'])))
    if _deco(r):
        b.append('Deco #%s' % _deco(r))
    if r['gl_rank'] is not None and r['gl_rank'] <= 50:
        b.append('GL #%d' % r['gl_rank'])
    if r['ul_rank'] is not None and r['ul_rank'] <= 50:
        b.append('UL #%d' % r['ul_rank'])
    return b


def _variant_name(r):
    parts = []
    _ax = evolvable_forms.max_axis(r['fresh_bread_mode'])
    if _ax == 'gigantamax':
        parts.append('Gigantamax')
    elif _ax == 'dynamax':
        parts.append('Dynamax')
    # form-encoded costume (fresh_form is a real costume form, e.g. 'PikachuDiwali2024') -> use its NAME
    nm = (r['species_name'] or '')
    fn = decode_form(r['fresh_form'])
    if fn:
        if fn.lower().startswith(nm.lower()):
            fn = fn[len(nm):].strip()
        if fn and fn.lower() != 'normal':
            parts.append(fn)
    # field costume (fresh_costume id; fresh_form is just 'normal') -> real event name from the dumped Costume enum
    if r['fresh_costume']:
        parts.append(costume_names.costume_name(r['fresh_costume']))   # 'Halloween 2021', 'Nightcap', ... ('Costume #N' if id newer than the dump)
    if r['special_bg_id']:
        parts.append(decode_bg(r['special_bg_id']))
    if (r['fresh_natural_art_bg'] or 0):   # fresh_ col (audit F1)
        parts.append('Art bg #%s' % r['fresh_natural_art_bg'])
    if r['fresh_has_location_card'] and r['fresh_loc_card_enum']:
        parts.append(decode_loc(r['fresh_loc_card_enum']))
    return ' · '.join(dict.fromkeys(p for p in parts if p))


def _shared_variant(lst):
    """Variant label from ONLY the attributes EVERY mon in the bucket shares. A coarse bucket (all shinies
    of a form, all legendaries of a form) therefore NEVER inherits one mon's incidental costume / background /
    location card -- those live on each mon's own badges. A cosmetic bucket is keyed on the full cosmetic set,
    so it shares them all and they appear in the label as expected. lst is IV-sorted; lst[0] is the head."""
    def same(f):
        vals = {f(r) for r in lst}
        return next(iter(vals)) if len(vals) == 1 else None
    head = lst[0]
    parts = []
    _ax = same(lambda r: evolvable_forms.max_axis(r['fresh_bread_mode']))
    if _ax == 'gigantamax':
        parts.append('Gigantamax')
    elif _ax == 'dynamax':
        parts.append('Dynamax')
    al = same(lambda r: r['fresh_alignment'] or 0)
    if al == 1:
        parts.append('Shadow')
    elif al == 2:
        parts.append('Purified')
    fn = decode_form(head['fresh_form']) or decode_form(head['form']) or ''   # form is shared (cf is in every key)
    nm = head['species_name'] or ''
    if fn.lower().startswith(nm.lower()):
        fn = fn[len(nm):].strip()
    if fn and fn.lower() != 'normal':
        parts.append(fn)
    cv = same(lambda r: r['fresh_costume'] or 0)
    if cv:
        parts.append(costume_names.costume_name(cv) or ('Costume #%s' % cv))
    bgv = same(lambda r: r['special_bg_id'] or 0)
    if bgv:
        parts.append(decode_bg(bgv))
    if same(lambda r: r['fresh_natural_art_bg'] or 0):   # fresh_ col (audit F1)
        parts.append('Art BG')
    locv = same(lambda r: (r['fresh_loc_card_enum'] or 0) if r['fresh_has_location_card'] else 0)
    if locv:
        parts.append(decode_loc(locv))
    dv = same(lambda r: _deco(r))
    if dv:
        parts.append('Deco #%s' % dv)
    return ' · '.join(dict.fromkeys(p for p in parts if p))


_SELECT = ("SELECT uid_hex,pokemon_id,species_name,form,form_region,fresh_form,fresh_costume,"
           "special_bg_id,fresh_natural_art_bg,costume_decoration_id,fresh_has_location_card,"
           "fresh_loc_card_enum,fresh_shiny,fresh_alignment,fresh_bread_mode,is_lucky,is_traded,"
           "iv_total,iv_atk,iv_def,iv_sta,cp,gl_rank,ul_rank,pokemon_size_category,height_m,weight_kg "
           "FROM pokemon WHERE in_bag=1")   # fresh_natural_art_bg, NOT natural_art_background (audit F1); height/weight for XXL showcase score (F9)


def _showcase_score(r, gmaxh, gmaxw):
    """Mirror keep_policy rule 7's XXL ordering (height-weighted Niantic showcase score) so the Studio's
    XXL cap line targets the SAME specimens the engine keeps -- ranking by IV picked the wrong mons
    (Gourgeist 0.792 over 0.983). Normalized by the bucket max h/w (monotonic -> exact top-N). Audit F9."""
    # THE GAME'S POINTS (2026-09-23): size_line.showcase_points -- Pokemod's formula, verified on screen. The old
    # group-max ordering stays only for a template size_line does not know.
    import size_line as _sl
    _p = _sl.showcase_points(r)
    if _p is not None:
        return _p
    w = keep_config.showcase_weights()
    return (w['height'] * ((r['height_m'] or 0) / (gmaxh or 1))
            + w['weight'] * ((r['weight_kg'] or 0) / (gmaxw or 1))
            + w['iv'] * ((r['iv_total'] or 0) / 45))


def _deco(r):
    d = r['costume_decoration_id']
    return d if (d and str(d) != '0') else 0   # costume_decoration_id is a STRING '0' for most -> not a real decoration


def _bucket_key(cat, r, cf):
    k = CATS[cat]['kind']
    if cat == 'xxl':      # Showcase (2026-09-23): per PvP identity -- species + battle form; costumes and cosmetics fold
        from pvp_iv_rule import pvid as _pv
        return ('showcase', _pv(r['species_name'], r['form'] or 0))
    if k == 'bread' or k == 'simple':
        return (r['pokemon_id'], cf(r))
    if k == 'rarity':
        return (r['pokemon_id'], cf(r), 1 if r['fresh_alignment'] == 1 else 0, r['fresh_bread_mode'] or 0)
    if k == 'cosmetic':
        loc = (r['fresh_loc_card_enum'] or 0) if r['fresh_has_location_card'] else 0
        return (r['pokemon_id'], cf(r), r['fresh_costume'] or 0, r['special_bg_id'] or 0,
                r['fresh_natural_art_bg'] or 0, _deco(r), loc)   # loc card was MISSING -> distinct cards collapsed into one; fresh_ art col (audit F1)
    return (r['pokemon_id'], cf(r))


def _in_category(cat, r):
    c = CATS[cat]
    k = c['kind']
    if k == 'bread':
        return evolvable_forms.max_axis(r['fresh_bread_mode']) == c['cap']   # every Max mode, by the game's own names
    if k == 'rarity':
        return (r['pokemon_id'] in RARE_PIDS) and not r['fresh_shiny']
    if k == 'cosmetic':
        return bool((r['fresh_costume'] or 0) or (r['special_bg_id'] or 0) or (r['fresh_natural_art_bg'] or 0)
                    or _deco(r) or (r['fresh_has_location_card'] or 0)) and not evolvable_forms.max_axis(r['fresh_bread_mode'])
    if c.get('col') == 'fresh_shiny':
        return bool(r['fresh_shiny'])
    if c.get('col') == 'size5':
        return (r['pokemon_size_category'] or 0) == 5
    return False


def category_view(cat, proposed_global=None, proposed_species=None):
    """Return the category's specimens grouped by species, with per-mon over-cap flag at the effective cap,
    plus summary counts. proposed_global / proposed_species[pid] override the saved cap for the preview."""
    if cat not in CATS:
        return {'error': 'unknown category'}
    con = _ro()
    rows = con.execute(_SELECT).fetchall()
    con.close()
    cf = _build_cf(rows)
    pol = _j(POLICY, {})
    cap_name = CATS[cat]['cap']
    _axis = {'gigantamax': 'variant_floor', 'dynamax': 'variant_floor', 'cosmetic': 'variant_floor',
             'rarity': 'rarity', 'shiny': 'shiny', 'xxl': 'xxl'}.get(cat, 'variant_floor')   # the keep-reason THIS category caps
    base_global = keep_config.cap(cap_name)
    gcap = proposed_global if proposed_global is not None else base_global
    pspec = dict(keep_config.raw().get('per_species_caps', {}).get(cap_name, {}))
    if proposed_species:
        pspec.update({str(k): v for k, v in proposed_species.items()})

    members = [r for r in rows if _in_category(cat, r)]
    buckets = defaultdict(list)
    for r in members:
        buckets[_bucket_key(cat, r, cf)].append(r)

    # releasable comes from ENGINE TRUTH (policy_reasons.json: no reasons = keep_policy put it in Transfer),
    # NOT from the studio's own cap re-ranking -- the re-ranking ignored the dominance collapse, rarity
    # keep-all, and showcase ordering, painting keepers red (27 kept Mewtwo) and released mons green (a
    # collapsed shiny Gmax Lapras). Audit F3. The cap heuristic survives ONLY for what-if cap previews.
    proposal_active = (proposed_global is not None) or bool(proposed_species)
    pol_ok = bool(pol)

    groups = []   # ONE per variant bucket (matches keep_policy's per-(species,form/variant) cap exactly)
    total = 0
    for key, lst in buckets.items():
        pid = key[0]
        cap = int(pspec.get(str(pid), gcap))
        if cat == 'xxl':   # rank by the engine's showcase score, not IV, so over_cap targets match rule 7 (F9)
            _gmh = max((r['height_m'] or 0) for r in lst) or 1
            _gmw = max((r['weight_kg'] or 0) for r in lst) or 1
            ranked = sorted(lst, key=lambda r: (-_showcase_score(r, _gmh, _gmw), r['uid_hex']))
        else:
            ranked = sorted(lst, key=_ivkey)
        head = ranked[0]
        variant = _shared_variant(ranked)   # label from ONLY what the whole bucket shares -- never the head's incidentals
        g = {'pid': pid, 'name': head['species_name'], 'variant': variant,
             'sprite': sprite_rel(pid, head['form'] or 0), 'cap': cap, 'mons': []}
        for i, r in enumerate(ranked):
            reasons = sorted(pol.get(r['uid_hex'], []))
            other = [x for x in reasons if x != _axis]   # protected by ANY OTHER axis (shiny/rarity/xxl/hundo/legacy/...) -> NOT releasable. (BUG was excluding all 4 caps, so e.g. a shiny over the Dynamax cap falsely showed red 'release'.)
            is_over = i >= cap
            in_transfer = pol_ok and (r['uid_hex'] not in pol)   # engine truth: no keep reason = Transfer
            if proposal_active:
                rel = is_over and not other        # what-if estimate at the PROPOSED cap (engine hasn't run it)
            elif pol_ok:
                rel = in_transfer                  # saved-cap view: red EXACTLY when the engine releases (F3)
            else:
                rel = is_over and not other        # policy_reasons.json missing -> old heuristic fallback
            g['mons'].append({
                'uid': r['uid_hex'], 'iv': r['iv_total'], 'atk': r['iv_atk'], 'def': r['iv_def'],
                'sta': r['iv_sta'], 'cp': r['cp'], 'shiny': bool(r['fresh_shiny']),
                'badges': _badges(r), 'form': r['form'] or 0, 'reasons': reasons,
                'protected_by': other, 'over_cap': is_over, 'releasable': rel,
                'in_transfer': in_transfer,
            })
            total += 1
        g['count'] = len(g['mons'])
        groups.append(g)
    groups.sort(key=lambda g: (-g['count'], g['name'] or '', g['variant']))
    # GUARANTEE distinct labels per species: if two buckets still share a name, suffix them (safety: the
    # user must never see two indistinguishable cards -- Pikachu costumes were the trap)
    _vc = Counter((g['pid'], g['variant']) for g in groups)
    _seen = defaultdict(int)
    for g in groups:
        k = (g['pid'], g['variant'])
        if _vc[k] > 1:
            _seen[k] += 1
            g['variant'] = (g['variant'] + ' ' if g['variant'] else '') + '(#%d)' % _seen[k]
    over = sum(1 for g in groups for m in g['mons'] if m['over_cap'])
    releasable = sum(1 for g in groups for m in g['mons'] if m['releasable'])
    note = _PROTECT_NOTE.get(cat, '')
    if cat == 'rarity':   # dynamic keep-all roster instead of a hardcoded 'Mewtwo' that goes stale (F10c)
        try:
            _ka = keep_config.rarity_keep_all()
        except Exception:
            _ka = []
        note = note.replace('Mewtwo is keep-all.', 'Keep-all dex #s: %s.' % (', '.join('#%d' % p for p in _ka) or 'none'))
    return {
        'category': cat, 'label': CATS[cat]['label'], 'cap_name': cap_name,
        'global_cap': gcap, 'saved_global_cap': base_global, 'per_species': pspec,
        'protected_note': note,
        'total': total, 'over_cap': over, 'releasable': releasable,
        'species_count': len(groups), 'species': groups,
    }


def categories():
    con = _ro()
    rows = con.execute(_SELECT).fetchall()
    con.close()
    out = []
    for cat, meta in CATS.items():
        n = sum(1 for r in rows if _in_category(cat, r))
        out.append({'key': cat, 'label': meta['label'], 'count': n, 'cap': keep_config.cap(meta['cap'])})
    return out
