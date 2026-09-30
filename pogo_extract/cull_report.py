"""THE CULL REPORT, written by the cull itself (user 2026-09-24: "Why does it take you so long to make the report? it
shouldnt..." and "Where's my little thing about what got improved and why each thing got culled").

Compares this walk with the walk of the LAST REPORT (system/analysis/last_report.json: its snapshot stamp, pile,
keep reasons and evolve targets), so "just caught / just evolved" means "since you last read a report" even when a
pass in between was cut off. Everything comes from files the pass already wrote: pokemon.db, policy_reasons.json,
tagsets/Transfer.txt, .db_snapshots/*.before_sync.*.gz, evolve_targets -- and, for the closing Power Up block (2026-09-30, report only), the
Power Up tag files, the game master's Power Up tables and this walk's candy.json / inventory.json.

  python cull_report.py            # print the report and remember this walk as the last reported one
  python cull_report.py --dry-run  # print it, remember nothing
"""
import collections, glob, gzip, json, os, re, shutil, sqlite3, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
A = os.path.join(ROOT, 'system', 'analysis')
STATE = os.path.join(A, 'last_report.json')
# THE GAME'S OWN NAMES (2026-09-30, docs/memory/pogo-bag-pulse-sprites.md): DISPLAY ONLY. species_name, form ids and pvids stay the
# walk's own strings; only the words a person reads change ('Nidoran F' -> 'Nidoran♀', 'Mr Mime' -> 'Mr. Mime', 'Ho Oh' -> 'Ho-Oh').
# Every failure (no pogo_display, no names file, an id it cannot vouch for) prints what this report printed before.
try:
    import pogo_display as _pd
    _NM = _pd.Names.load()
except Exception:
    _NM = None


def species_label(r):
    """The species as the game spells it; the walk's own species_name when there is nothing better."""
    return _NM.species(r['pokemon_id'], r['species_name']) if _NM else r['species_name']


def stage_name(sid, dex=None):
    """A pvpoke speciesId for a person: 'mr_mime' -> 'Mr. Mime', 'raichu_alolan' -> 'Alolan Raichu'. Any id the names file cannot
    vouch for (a form, a shadow, a mega, no dex) keeps today's title-cased rendering."""
    return (_NM.stage(sid, dex) if _NM else None) or str(sid).replace('_', ' ').title()


LABEL = {'variant_floor': 'ladder slot', 'shiny': 'shiny slot', 'xxl': 'XXL showcase spot',
         'location_card': 'location-card slot', 'pvp_best_gl': 'Best GL', 'pvp_best_ul': 'Best UL',
         'pvp_best_ml': 'Best ML', 'shadow_best': 'best-shadow slot', 'legacy': 'legacy-move slot',
         'pvp_rank': 'GL/UL rank 1-5', 'rarity': 'legendary slot', 'nundo': 'nundo slot', 'cosmetic': 'costume slot',
         'pvp_combup_gl': 'GL comb-up', 'pvp_combup_ul': 'UL comb-up', 'evolve_1': 'Evolve Once', 'evolve_2': 'Evolve Twice',
         'shiny_ladder': 'Evolve (shiny)'}   # the fold (2026-09-29)
# THE GROUP A KEEP REASON IS SHARED WITHIN -- keep_policy's OWN key for each rule (H05-2, 2026-09-29: the report grouped
# XXL / rarity by species and location cards / best-shadow by stage, so "lost its X to Y" named copies the rule never
# compared): legacy per SPECIES (_legcap), XXL / Best GL-UL-ML / best shadow per PvP IDENTITY (size_line.xxl_keepers,
# rule 15d, rule 2), shiny per (species, form), location card per (species, form, CARD), rarity per (species, form,
# shadow, Max, shiny), nundo per look (trophy_pick.look), ladders per STAGE (+ gender where it is a look).
SPECIES_WIDE = {'legacy'}
IDENTITY_WIDE = {'pvp_best_gl', 'pvp_best_ul', 'pvp_best_ml', 'xxl', 'shadow_best'}
# NOT A SLOT: every copy that qualifies is kept (rule 15b keeps EVERY rank-1-5 spread), so no other copy can take it --
# a copy that lost it lost it to a data or rule change, never "to" an arrival.
NOT_A_SLOT = {'pvp_rank'}
# A higher-IV copy can push a copy out ONLY on an IV-ranked ladder (topn: IV, then CP). Best GL/UL/ML and best shadow go
# by PvP rank, XXL by showcase points, location cards / rarity / legacy / nundo by their own groups -- never "the
# just-caught 91%" because it has more IV.
IV_LADDER = {'variant_floor', 'shiny'}
# keep reasons that are not slots at all: losing one is a change of THAT fact, said as such ("no longer a favorite")
NO_LONGER = {'favorite': 'a favorite (starred)', 'protected': 'on the keep-every-copy list',
             'adventure_effect': 'an Adventure Effect keeper', 'mighty': 'kept for being Mighty', 'origin': 'counted as traded by E+F',
             'pvp_spread': 'a kept PvP spread (0-15-15)', 'gl_iv': 'a GL IV keeper', 'ul_iv': 'a UL IV keeper',
             'rank_unknown': 'missing its PvP ranks', 'fused': 'held inside a fused Kyurem',
             # R-B review: keep_policy.mark emits these too -- losing one was dropped without a word
             'dex_only_copy': 'kept as the only copy of its form', 'data_incomplete': 'held for incomplete data',
             'xxs': 'kept as an XXS'}

pct = lambda r: round((r['iv_total'] or 0) * 100 / 45)
norm = lambda u: format(int(u, 16), 'x')
sig = lambda r: (r['iv_atk'], r['iv_def'], r['iv_sta'], r['creation_date'])


def _rows(path):
    c = sqlite3.connect(path); c.row_factory = sqlite3.Row
    out = {r['uid_hex']: dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1')}
    c.close()
    return out


def _snapshots():
    """{stamp: path}, oldest first."""
    out = {}
    for p in glob.glob(os.path.join(ROOT, '.db_snapshots', 'pokemon.db.*.before_sync.*.gz')):
        m = re.search(r'pokemon\.db\.(\d{4}-\d\d-\d\d_\d{6})\.before_sync', os.path.basename(p))
        if m:
            out[m.group(1)] = p
    return dict(sorted(out.items()))


def _open_snapshot(path):
    tmp = os.path.join(tempfile.gettempdir(), 'cull_report_' + os.path.basename(path)[:-3])
    if not os.path.exists(tmp):
        with gzip.open(path, 'rb') as f, open(tmp, 'wb') as g:
            shutil.copyfileobj(f, g)
    return _rows(tmp)


# last pass's keep reasons, read back from the TAGS the walk saw, for when last_report.json has none (first run)
TAG_REASON = {'Best GL': 'pvp_best_gl', 'Best UL': 'pvp_best_ul', 'Best ML': 'pvp_best_ml', 'XXL': 'xxl',
              'Legacy Moves': 'legacy', 'Shiny - Only One': 'shiny', 'Shiny #4+': 'shiny', 'Nundo': 'nundo',
              'GL Rank 1-5': 'pvp_rank', 'UL Rank 1-5': 'pvp_rank'}


def _from_tags(r):
    tags = (r or {}).get('auth_tag_names') or ''
    out = {TAG_REASON[t] for t in tags.split(';') if t in TAG_REASON}
    if any(t.startswith('Variant #') for t in tags.split(';')):
        out.add('variant_floor')
    return sorted(out)


def _line_pool_of(r):
    """The every-line pool key (keep_config.line_pool_all) or None."""
    import keep_config, pattern_pools
    if not keep_config.line_pool_all():
        return None
    return pattern_pools.pool_key(r['pokemon_id'], r['species_name'], r.get('form') or 0, r.get('gender'))


def main():
    import evolvable_forms as ef
    import granular_tags
    from pvp_iv_rule import pvid
    import pvp_iv_rule as pv, keep_config
    _gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    BS = {q['speciesId']: q.get('baseStats', {}) for q in _gm['pokemon']}
    _dex_of = {q['speciesId']: q.get('dex') for q in _gm['pokemon']}
    stg = lambda s: stage_name(s, _dex_of.get(s))            # a pvpoke speciesId as the game spells it (display only)
    snaps = _snapshots()
    if not snaps:
        print('(no walk snapshot yet)'); return 0
    _first = len(snaps) < 2       # a NEW account's first cull (2026-09-26): compare the walk with itself -- nothing
    #                               "improved" yet, but the pile and the evolve advice still need explaining
    cur_stamp = list(snaps)[-1]
    saved = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    C = _rows(os.path.join(ROOT, 'pokemon.db'))
    # WHICH WALK IS THIS (H05-10): the rows' own re-read time (last_scanned) against the newest before_sync snapshot. A
    # walk newer than that snapshot never reached a sync -- the audit gate stopped it, or a recrawl ran alone -- so it is
    # NOT the cur_stamp walk: compare it with the last report's walk itself and remember nothing.
    import datetime as _dt
    _walk_t = max((x.get('last_scanned') or '') for x in C.values()) if C else ''
    try:                                             # an unreadable time proves nothing either way: treat as synced
        _dt.datetime.strptime(_walk_t[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
    except ValueError:
        _walk_t = ''
    unsynced = bool(_walk_t) and (_dt.datetime.strptime(_walk_t[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                                  > _dt.datetime.strptime(cur_stamp, '%Y-%m-%d_%H%M%S') + _dt.timedelta(seconds=60))
    # the SAME walk asked again (he wants it re-printed): compare against what that report compared against, so the
    # re-print is identical instead of "since itself"
    state = saved.get('prev') or {} if saved.get('walk') == cur_stamp and not unsynced else saved
    prev_stamp = (cur_stamp if _first else
                  state.get('walk') if state.get('walk') in snaps and (state.get('walk') != cur_stamp or unsynced)
                  else list(snaps)[-2])
    P = _open_snapshot(snaps[prev_stamp])
    why = json.load(open(os.path.join(A, 'policy_reasons.json'), encoding='utf-8'))
    try:
        prom_now = json.load(open(os.path.join(A, 'promises.json'), encoding='utf-8'))
    except Exception:
        prom_now = {}
    prev_why = state.get('reasons') or {}
    prev_pile = {norm(u) for u in state.get('pile') or []}
    prev_targets = {norm(u): v for u, v in (state.get('targets') or {}).items()}
    _by = {norm(u): u for u in C}
    pile = [_by[norm(u)] for u in open(os.path.join(A, 'tagsets', 'Transfer.txt')).read().split() if norm(u) in _by]
    pile_set = set(pile)

    # ---- arrivals: caught vs evolved (IVs + creation date survive an evolution; the uid does not) ----
    gone = {sig(P[u]): P[u] for u in sorted(set(P) - set(C))}
    origin = {}                                          # new uid -> source row (evolved) or None (caught)
    for u in sorted(set(C) - set(P)):                    # sorted (R-B review): hash order made the same walk print in random order
        origin[u] = gone.get(sig(C[u]))
    evolved_src = {id(v) for v in origin.values() if v is not None}
    released = [r for r in gone.values() if id(r) not in evolved_src]

    def arrived(r):
        """HOW a new copy came (H05-5): the walk's own proto fields, not a guess -- hatchedFromEgg_ (pogo_pipeline
        parse_pokemon @0xe1 -> hatched_from_egg / is_hatched_from_egg) and tradedTimeMs_ (@0x108 -> traded_time_ms).
        'caught' is what is left: wild, raid, research, rocket, gift ... the game has no single 'caught' flag."""
        if (r.get('traded_time_ms') or 0) > 0 or r.get('is_traded') == 1:
            return 'traded to you'                       # checked first: a traded mon keeps its first owner's hatch flag
        if r.get('hatched_from_egg') or r.get('is_hatched_from_egg'):
            return 'hatched'
        return 'caught'

    sid = lambda r: pvid(r['species_name'], r['form'] or 0)
    stage = lambda r: (ef.stage_of(sid(r), r['fresh_form'] or r['form'] or 0),
                       ef.gender_key(r['pokemon_id'], r['gender']))
    stage_ng = lambda r: ef.stage_of(sid(r), r['fresh_form'] or r['form'] or 0)      # the shiny cap pools genders
    import trophy_pick
    from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
    ROSTER = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS   # their Best is kept at ANY rank (LAW 2b, rule 15d)

    def group(r, reason):
        """keep_policy's OWN group for `reason` -- see SPECIES_WIDE / IDENTITY_WIDE at the top (H05-2)."""
        if reason in SPECIES_WIDE:
            return r['pokemon_id']
        if reason in IDENTITY_WIDE:
            return sid(r)
        if reason == 'shiny':
            return stage_ng(r)
        if reason == 'location_card':                    # keep_policy 13b: top-N per (species, form, CARD TYPE)
            return (stage_ng(r), r['fresh_loc_card_enum'] or 0)
        if reason == 'rarity':                           # keep_policy rarity: (species, form, shadow, Max), shinies apart
            return (stage_ng(r), r['fresh_alignment'] == 1, r['fresh_bread_mode'] or 0, bool(r['fresh_shiny']))
        if reason == 'nundo':                            # one nundo per LOOK (trophy_pick.pick_nundos)
            return trophy_pick.look(r)
        return stage(r)

    def ladder_mate(x, r, reason):
        """Can x hold a place in the IV ladder r lost (keep_policy 1a / 1b, rule 3)? A shiny slot goes to ANY shiny of the
        same species+form: rule 3 ranks hundo and shadow shinies inside the cap too (keep_policy's _ranked exempts
        neither). A plain / variant ladder: a hundo never takes a slot (rule 4 keeps it outside the cap), a NON-shiny
        shadow is its own axis, a plain ladder is shared with every non-hundo special of its stage (1b: shinies -- shadow
        shinies included, _special_iv_grp -- and cosmetic variants displace plains), a costume / background / Max ladder
        only with its own variant (1a)."""
        if reason == 'shiny':
            return bool(x['fresh_shiny']) and stage_ng(x) == stage_ng(r)
        if ((x['iv_total'] or 0) == 45 or r['fresh_alignment'] == 1
                or (x['fresh_alignment'] == 1 and not x['fresh_shiny'])):
            return False
        if reason != 'variant_floor' or stage(x) != stage(r):
            return False
        _v = lambda y: (y['fresh_costume'] or 0, y['fresh_natural_art_bg'] or 0, y['fresh_bread_mode'] or 0)
        return _v(r) == (0, 0, 0) or _v(x) == _v(r)

    def outranks(x, r):
        """topn's own order (IV, then CP): x can have taken r's place only if it sorts at or above r (R-B review: "98%
        Ekans: lost its ladder slot to the just-caught 40% costume Ekans" printed with no such check)."""
        return ((x['iv_total'] or 0), (x['cp'] or 0)) >= ((r['iv_total'] or 0), (r['cp'] or 0))
    sym = {1: ' ♂', 2: ' ♀'}

    def desc(r, with_origin=True):
        bits = []
        if r['fresh_shiny']: bits.append('shiny')
        if (r['fresh_bread_mode'] or 0) == 1: bits.append('Dynamax')
        if (r['fresh_bread_mode'] or 0) == 2: bits.append('Gigantamax')
        if r['fresh_costume']: bits.append('costume')
        if r['fresh_alignment'] == 1: bits.append('shadow')
        g = sym.get(r['gender'], '') if ef.gender_key(r['pokemon_id'], r['gender']) else ''
        reg = {'alolan': 'Alolan ', 'galarian': 'Galarian ', 'hisuian': 'Hisuian ', 'paldean': 'Paldean '}.get(sid(r).split('_')[-1], '')
        s = '%d%% %s%s%s%s' % (pct(r), ' '.join(bits) + ' ' if bits else '', reg, species_label(r), g)
        if not with_origin:
            return s
        if r['uid_hex'] in origin:
            return ('the just-evolved ' if origin[r['uid_hex']] else 'the just-%s ' % arrived(r).replace(' to you', '')) + s
        return 'your ' + s

    def keepers(r, reason):
        """Kept copies sharing r's group for `reason`, best first."""
        g = group(r, reason)
        return sorted((x for u, x in C.items() if u != r['uid_hex'] and reason in (why.get(u) or ())
                       and group(x, reason) == g), key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))

    def kind_of(r):
        """'Alolan Raichu' -- the PvP identity by name (the group an XXL spot or a Best is decided in)."""
        return {'alolan': 'Alolan ', 'galarian': 'Galarian ', 'hisuian': 'Hisuian ', 'paldean': 'Paldean '}.get(
            sid(r).split('_')[-1], '') + species_label(r)

    def xxl_why(r):
        """Why an XXL copy holds no XXL spot -- size_line.xxl_keepers' own tests, in its order (H05-1): no height /
        weight = never a candidate; best_points under showcase_weights.min_points; else outside the top
        species_cap('xxl') of its PvP IDENTITY by points (+ outside the trim's per-type top-N while caps.xxl_per_type is
        on). Never an IV comparison: an XXL spot is not an IV ladder."""
        import size_line as _sl
        _mn, _trim = keep_config.showcase_weights()['min_points'], keep_config.cap('xxl_per_type')
        if r['height_m'] is None or r['weight_kg'] is None:
            return 'no height / weight was read, so the showcase rule cannot score it'
        _p = _sl.best_points(r)
        if _p is not None and _p < _mn:
            return '%d points, under the %d-point cut-off%s' % (_p, _mn, ' (XXL trim)' if _trim else '')
        # an unknown template stays a candidate that sorts below every known score (xxl_keepers), never "None points"
        _pt = lambda x: ('%d' % _sl.best_points(x)) if _sl.best_points(x) is not None else 'unknown'
        _me = ('%d points' % _p) if _p is not None else 'showcase points unknown (no size template for it)'
        _ks = sorted(keepers(r, 'xxl'), key=lambda x: -(_sl.best_points(x) or -1))
        if _ks:
            return '%s, below the XXL %s you keep (%s points)%s' % (
                _me, kind_of(r), ', '.join(_pt(x) for x in _ks[:3]),
                ' and not in the top %d of its types (XXL trim)' % _trim if _trim else '')
        return ('%s, yet no XXL %s is kept -- ***CHECK: the XXL rule should keep it; nothing here explains why '
                'it is in the pile***' % (_me, kind_of(r)))

    def ladder(r):
        """The copies holding r's ladder: its plain (or shiny) keepers, plus same-stage copies held to EVOLVE -- they
        occupy a place too (a just-caught Rattata tagged Evolve Next sits in the female ladder)."""
        ks = keepers(r, 'shiny' if r['fresh_shiny'] else 'variant_floor')
        # the SAME ladder only: a costume, card, background or Max copy has its own (a costume Cottonee is not in the
        # plain Cottonee ladder, 2026-09-24)
        look = lambda x: (bool(x['fresh_costume']), bool(x['fresh_has_location_card']), bool(x['fresh_natural_art_bg']),
                          x['fresh_bread_mode'] or 0)
        ks = [x for x in ks if look(x) == look(r)] or ks
        if not r['fresh_shiny']:
            ev = [x for x in C.values() if x['uid_hex'] != r['uid_hex'] and stage(x) == stage(r) and x not in ks
                  and any(k.startswith('evolve_') for k in (why.get(x['uid_hex']) or ()))]
            ks = sorted(ks + ev, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        tag = lambda x: ' (to evolve)' if any(k.startswith('evolve_') for k in (why.get(x['uid_hex']) or ())) else ''
        txt = ', '.join('%d%%%s' % (pct(x), tag(x)) for x in ks[:5])
        if any(pct(x) == pct(r) for x in ks[:5]):
            txt += ' -- it ties your %d%%, and the one you keep has more CP' % pct(r)
        return txt

    def shiny_why(r):
        """Why a shiny holds no shiny slot -- rule 3's own two tests (H05-11): a PLAIN shiny (no background, card, costume,
        costume form, Max or shadow -- keep_policy _scollect) under keep_config.shiny_floor_iv takes no plain slot; else the
        cap of its species + form is full. "outside your top 1 shinies" for a 24% under the floor named the wrong rule."""
        from costume_forms import is_costume_form
        _sfl = keep_config.shiny_floor_iv()
        _plain = not ((r['fresh_natural_art_bg'] or 0) or (r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0))
                      or (r['fresh_costume'] or 0) or is_costume_form(r['fresh_form'] or r['form'] or 0)
                      or ef.max_axis(r['fresh_bread_mode']) or r['fresh_alignment'] == 1)
        if _sfl and _plain and (r['iv_total'] or 0) < _sfl:
            return 'a plain shiny under your %d/45 shiny floor (you keep %s)' % (_sfl, ladder(r) or 'no other shiny of it')
        return 'outside your top %d shinies (%s)' % (len(keepers(r, 'shiny')), ladder(r))

    def why_out(r):
        """The verdict for a copy that is in the pile, by the rule that put it there: an XXL by the showcase rule, a shiny
        by the shiny rule, everything else by its ladder (H05-1 / H05-11)."""
        _own = shiny_why(r) if r['fresh_shiny'] else 'you keep %s' % (ladder(r) or 'better copies')
        if (r['pokemon_size_category'] or 0) == 5 and 'xxl' not in (why.get(r['uid_hex']) or ()):
            return 'XXL -- %s; %s' % (xxl_why(r), _own)       # both reasons, never one hiding the other (R-B review)
        return _own

    lines, still, from_pile = [], [], []
    grouped = collections.OrderedDict()                  # same kind + same verdict -> one line (32 Rattatas, 2026-09-24)
    replaced = collections.defaultdict(list)             # new copy's uid -> the pile mons it pushed out
    for u in sorted(pile, key=lambda u: (C[u]['species_name'], -pct(C[u]))):
        r = C[u]
        if keep_config.is_fused_component(r):
            continue                                     # (2026-09-26) never a pile mon: the CHECK line at the top names it
        src = origin.get(u, 'old')
        if norm(u) in prev_pile:
            still.append(desc(r, False)); continue
        if src not in ('old', None) and norm(src['uid_hex']) in prev_pile:
            from_pile.append('**%s** (was %s): an extra at its new stage too; %s.' % (desc(r, False), desc(src, False), why_out(r)))
            continue
        # EVERY-LINE POOLS (florandez 2026-09-26): a plain copy competes for its LINE's 2 slots, not its stage's -- say
        # which copies of the line hold them ("84% Charizard: kept 69%, 69%" read as a bug; the 69% are specials).
        _lp = _line_pool_of(r)
        # an old copy that lost an XXL spot goes to the XXL attribution below, never to the line text (R-B review: on a
        # line_pool_all account the XXL reason was never printed)
        _xxl_lost = src == 'old' and 'xxl' in (prev_why.get(u) or _from_tags(P.get(u)))
        if (_lp is not None and not _xxl_lost and not r['fresh_shiny'] and not (r.get('fresh_costume') or 0)
                and r.get('fresh_alignment') != 1):
            _mates = sorted((x for x in C.values() if x['uid_hex'] not in pile and _line_pool_of(x) == _lp
                             and 'variant_floor' in (why.get(x['uid_hex']) or ())),
                            key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
            if _mates:
                import evolve_targets as _et
                _how = '' if src == 'old' else (' (just evolved from %s)' % desc(src, False) if src else ' (just %s)' % arrived(r))
                _xt = ('; XXL -- %s' % xxl_why(r)) if ((r['pokemon_size_category'] or 0) == 5
                                                        and 'xxl' not in (why.get(u) or ())) else ''
                lines.append('**%s**%s: the %s line keeps %s%s.' % (desc(r, False), _how, _et._nice(_lp[0][1][len('line:'):]),
                                                                    ', '.join(desc(x, False) for x in _mates[:3]), _xt))
                continue
        if src == 'old':
            _was = prev_why.get(u) or _from_tags(P.get(u))
            lost = [x for x in _was if x in LABEL and x != 'dex_only_copy']
            # a keep reason that is not a slot (a favorite star, the keep-all list, Adventure Effect ...): losing it is
            # its own fact -- say it, never dress it up as "outranked" (H05-3)
            parts = ['no longer %s' % NO_LONGER[x] for x in _was if x in NO_LONGER]
            if 'hundo' in _was and (r['iv_total'] or 0) != 45:
                # a hundo cannot stop being one: one of the two walks misread its IVs (R-B review)
                parts.append('***CHECK: kept as a hundo last time, but this walk reads %s/%s/%s -- an IV misread in one of '
                             'the two walks; do not release it until a re-read agrees***' % (r['iv_atk'], r['iv_def'], r['iv_sta']))
            to, _iv_to = collections.OrderedDict(), set()       # one clause per copy that took something
            for reason in lost:
                if reason.startswith('evolve_'):
                    # an EVOLVE promise is a slot at the TARGET stage: name the new copy now promised it (the 87% Pawmo
                    # whose Pawmot slot went to a just-caught 91% Pawmi, 2026-09-24)
                    old_t = set(prev_targets.get(norm(u)) or [])
                    took = sorted((x for x in C.values() if x['uid_hex'] in origin and old_t & set(prom_now.get(x['uid_hex']) or [])),
                                  key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
                    if took:
                        _lbl = '%s slot' % ' / '.join(sorted(stg(t) for t in old_t))
                        to.setdefault(desc(took[0]), []).append(_lbl)
                        if desc(r, False) not in replaced[took[0]['uid_hex']]:
                            replaced[took[0]['uid_hex']].append(desc(r, False))
                        continue
                    # NO FALL-THROUGH (R-B review): no arrival is promised r's target, and the generic path below named any
                    # same-stage arrival holding an Evolve label ("lost its Evolve Once to the just-caught 89% Charcadet")
                    _tg = ' / '.join(sorted(stg(t) for t in old_t))
                    parts.append('lost its %s%s -- no just-arrived copy is promised %s' % (
                        LABEL[reason], (' (%s)' % _tg) if _tg else '', 'that target' if _tg else 'its target'))
                    continue
                if reason in NOT_A_SLOT:
                    # rule 15b keeps EVERY rank-1-5 spread at a stage that reaches its league: no copy takes that from another,
                    # so it was lost to a rank / reach change -- say what the ranks are now (H05-2)
                    _now = []
                    for _l, _cp in (('gl', pv.GL_CAP), ('ul', pv.UL_CAP)):
                        _rk, _st = r[_l + '_rank'], r[_l + '_stage']
                        if _rk is None:
                            _now.append('%s unranked' % _l.upper())
                            continue
                        _reach = bool(_st) and pv.maxcp(_st, BS) > _cp + pv.VIABILITY_MARGIN
                        _now.append('%s #%d as %s%s' % (_l.upper(), _rk, stg(_st or '?'),
                                                         '' if _reach else ', a stage that cannot reach the league'))
                    # "its ranks changed" only when they DID (R-B review): the same ranks with the spread dropped means the
                    # rank rule (keep_config READY_RANK / viability margin) or the stage's reach changed
                    _pr = P.get(u) or {}
                    _same = bool(_pr) and all(_pr.get(k) == r.get(k) for k in (
                        'gl_rank', 'gl_stage', 'ul_rank', 'ul_stage', 'gl_chain_ranks', 'ul_chain_ranks'))   # rule 15b reads the CHAIN
                    parts.append('no longer a GL/UL rank 1-%d spread -- no copy took it; %s (now %s)'
                                 % (pv.READY_RANK, 'its ranks read the same as last walk, so the rank rule or the league '
                                    'reach changed' if _same else 'its ranks changed', '; '.join(_now)))
                    continue
                ks = keepers(r, reason)
                new = [x for x in ks if x['uid_hex'] in origin]
                if reason == 'xxl':
                    # AN XXL SPOT IS NOT AN IV LADDER (2026-09-29: "69% Nidorino lost its XXL showcase spot to the just-evolved
                    # 87% Nidorino" -- a normal-size copy): only a new XXL of the SAME PvP identity with MORE points can have
                    # taken it, and never one that fell under the cut-off on its own. Otherwise say the points and the rule.
                    import size_line as _sl
                    _rp, _mn = _sl.best_points(r), keep_config.showcase_weights()['min_points']
                    _nx = sorted((x for x in new if _rp is not None and _rp >= _mn and (_sl.best_points(x) or -1) > _rp),
                                 key=lambda x: -(_sl.best_points(x) or -1))
                    if _nx:
                        to.setdefault('%s (%s points vs its %s)' % (desc(_nx[0]), _sl.best_points(_nx[0]), _rp), []).append(LABEL[reason])
                        if desc(r, False) not in replaced[_nx[0]['uid_hex']]:
                            replaced[_nx[0]['uid_hex']].append(desc(r, False))
                    else:
                        parts.append('lost its XXL showcase spot: %s' % xxl_why(r))
                    continue
                # A CUT-OFF MOVED (2026-09-29, 150 -> 100): a Best / best-shadow copy nobody replaced lost its slot to the
                # rule itself -- say the rank and the line it fell past, not "outside your top copies".
                _lg = {'pvp_best_gl': ('gl', 'Great League'), 'pvp_best_ul': ('ul', 'Ultra League'),
                       'pvp_best_ml': ('ml', 'Master League')}.get(reason)      # rule 15d floors Best ML too
                if reason == 'shadow_best':                  # best ML (top IV) or best UL shadow: name the rank nearest the line
                    _lg = min((('ml', 'Master League'), ('ul', 'Ultra League')), key=lambda t: r[t[0] + '_rank'] or 9999)
                _fl = keep_config.pvp('best_rank_floor' if reason != 'shadow_best' else 'shadow_rank_floor')
                # keep_policy 15d keeps a legendary / mythical / UB / paradox Best at ANY rank, so the cut-off never takes it
                # (R-B review: "87% Tornadus: lost its Best ML: Master League #59 is past the #55 cut-off"); shadows are floored
                if (not new and _lg and (r[_lg[0] + '_rank'] or 0) > _fl
                        and (reason == 'shadow_best' or r['pokemon_id'] not in ROSTER)):
                    parts.append('lost its %s: %s #%d is past the #%d cut-off' % (LABEL[reason], _lg[1], r[_lg[0] + '_rank'], _fl))
                    continue
                if reason in IV_LADDER:
                    # only a copy that can SIT in r's ladder (same species+form, same look, not a hundo) AND sorts at or
                    # above r there can push it out
                    new = [x for x in new if ladder_mate(x, r, reason) and outranks(x, r)]
                if new:
                    to.setdefault(desc(new[0]), []).append(LABEL[reason])
                    if reason in IV_LADDER:
                        _iv_to.add(desc(new[0]))
                    if desc(r, False) not in replaced[new[0]['uid_hex']]:
                        replaced[new[0]['uid_hex']].append(desc(r, False))
                elif reason in IV_LADDER:
                    # the slot went to a new copy kept for ANOTHER reason (a just-caught Shellos tagged Evolve Next still
                    # takes a ladder place): the best new, KEPT copy that can sit in the same ladder and outranks r by
                    # topn's own order (IV, then CP) took it. (2026-09-26) fused components hold no ladder slot.
                    took = sorted((x for x in C.values() if x['uid_hex'] in origin and x['uid_hex'] not in pile_set
                                   and why.get(x['uid_hex']) and not keep_config.is_fused_component(x)
                                   and ladder_mate(x, r, reason)
                                   and ((x['iv_total'] or 0), (x['cp'] or 0)) > ((r['iv_total'] or 0), (r['cp'] or 0))),
                                  key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
                    if took:
                        to.setdefault(desc(took[0]), []).append(LABEL[reason])
                        _iv_to.add(desc(took[0]))
                        if desc(r, False) not in replaced[took[0]['uid_hex']]:
                            replaced[took[0]['uid_hex']].append(desc(r, False))
                    elif reason == 'shiny':
                        parts.append('lost its shiny slot: %s' % shiny_why(r))
                    elif ks:
                        parts.append('lost its %s (kept: %s)' % (LABEL[reason], ', '.join('%d%%' % pct(x) for x in ks[:4])))
                else:
                    # a slot decided by PvP rank, points or its own group (Best GL/UL/ML, best shadow, location card, legacy,
                    # legendary, nundo, comb-up): no new copy of THAT group holds it, so no arrival took it -- name who does
                    parts.append('lost its %s (%s)' % (LABEL[reason], ('now kept for that: ' + ', '.join(desc(x, False) for x in ks[:3]))
                                                       if ks else 'no copy is kept for that now'))
            parts = ['lost its %s to %s' % (' and '.join(v), k) for k, v in to.items()] + parts
            if any(('%d%% ' % pct(r)) in k for k in _iv_to):
                parts.append('same IV -- the one you keep has more CP')          # an IV tie goes to the stronger copy
            if not [p for p in parts if not p.startswith('no longer ')]:     # no slot explained yet: where it stands now
                _lr = 'shiny' if r['fresh_shiny'] else 'variant_floor'
                better = sorted((x for x in C.values() if x['uid_hex'] in origin and x['uid_hex'] not in pile_set
                                 and why.get(x['uid_hex'])               # KEPT: a copy in the pile outranks nothing (H05-3)
                                 and not keep_config.is_fused_component(x)      # (2026-09-26) fused components hold no ladder slot
                                 and ladder_mate(x, r, _lr)              # the same ladder: a plain never outranks a shiny
                                 and (x['iv_total'] or 0) > (r['iv_total'] or 0)),
                                key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
                if better:
                    parts.append('outranked by %s' % desc(better[0]))
                    replaced[better[0]['uid_hex']].append(desc(r, False))
                elif r['fresh_shiny']:
                    parts.append(shiny_why(r))
                else:
                    # an empty ladder printed "()" (a 58% Drapion beside a kept 100% and a 98% shadow, 2026-09-25): name
                    # the copies of the species that DO stay instead
                    # (2026-09-26) fused components hold no ladder slot: not one of "your top copies"
                    _kin = sorted((x for x in C.values() if x['uid_hex'] not in pile and x['pokemon_id'] == r['pokemon_id']
                                   and not keep_config.is_fused_component(x)),
                                  key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
                    parts.append('outside your top copies (%s)' % (ladder(r) or (
                        'you keep %s' % ', '.join(desc(x, False) for x in _kin[:3]) if _kin else 'none of this kind is kept')))
            lines.append('**%s**: %s.' % (desc(r, False), '; '.join(parts)))
        else:
            how = ('just evolved from %s' % desc(src, False)) if src else 'just %s' % arrived(r)
            meant = prev_targets.get(norm(src['uid_hex'])) if src else None
            miss = ''
            if meant and not any(sid(r).startswith(t.split('_')[0]) for t in meant):
                _m = ' or '.join(stg(t) for t in meant)
                # went PAST the promised stage (a Dratini tagged Evolve Next for a Dragonair slot, evolved twice)
                past = any(ef.can_reach_sid(t, sid(r)) for t in meant)
                miss = (' It was tagged to stop at %s (that is where the open slot was); evolving it again made it an extra.' % _m
                        if past else ' It was meant to become %s.' % _m)
            # THE XXL BADGE IS pokemon_size_category (H05-1): the column size_line.is_xxl / xxl_keepers / keep_policy read.
            # size_enum is a stale proto read (33 of the 234 in-bag XXLs carry it), so the 20% XXL Shieldon of 2026-09-29
            # 05:20 was printed as plain fodder "below what you keep: 98%" instead of "948 points, under the cut-off".
            what = why_out(r)
            grouped.setdefault((re.sub(r'^\d+% ', '', desc(r, False)), how, what, miss), []).append(pct(r))

    fodder = []                                          # just caught, below what he keeps: [(kind, [IV%], keep text)] -> a table
    for (kind, how, what, miss), ivs in grouped.items():
        if how == 'just caught' and not miss and what.startswith('you keep '):   # "below what you keep" must be TRUE of
            #                                                                          every row: an XXL cut gets its own line
            _k = what[len('you keep '):] if what.startswith('you keep ') else what
            fodder.append((kind, sorted(ivs, reverse=True), _k))
        elif len(ivs) == 1:
            lines.append('**%d%% %s** (%s): %s.%s' % (ivs[0], kind, how, what, miss))
        else:
            lines.append('**%d %s %s** (%s): %s.%s' % (len(ivs), {'just caught': 'just-caught', 'just hatched': 'just-hatched',
                                                                   'just traded to you': 'traded-in'}.get(how, how), kind,
                         ', '.join('%d%%' % v for v in sorted(ivs, reverse=True)), what, miss))
    # ---- what improved ----
    arr = [C[u] for u in origin]
    ev, ca = [r for r in arr if origin[r['uid_hex']]], [r for r in arr if not origin[r['uid_hex']]]
    best_prev = collections.defaultdict(int)
    hundo_prev = set()
    for x in P.values():
        k = stage_ng(x)
        if not keep_config.is_fused_component(x):       # (2026-09-26) fused components hold no ladder slot
            best_prev[k] = max(best_prev[k], x['iv_total'] or 0)
        if (x['iv_total'] or 0) == 45:
            hundo_prev.add(k)
    # "YOUR FIRST" = the GAME'S record (user 2026-09-29: "that wasnt my first hundo panpour, ive had one before. i evolved
    # it."): the Pokedex FOUR_STAR category as it stood at the LAST REPORT's walk -- the same moment "since the last
    # report" counts from. H05-6: pokedex_hundos_live.prev.json is rotated by EVERY walk (pogo_pipeline.step_read_dex) and is
    # not parked by switch_account.py, so after an unreported walk it is too new (a real first goes unsaid) and after an
    # account switch it is the OTHER trainer's Pokedex (a false "your first"). So: the set this report saved with the last
    # one (last_report.json is parked per account); else the .prev file only when it lists every species of the last
    # report's bag (a Pokedex always does -- a foreign or partial one does not). An unreadable record claims nothing.
    def _dex_hundo_set(path, bag):
        try:
            _ents = json.load(open(path, encoding='utf-8'))['entries']
            _pids = {e['pid'] for e in _ents}
            _hun = {e['pid'] for e in _ents if e.get('hundo')}
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not {x['pokemon_id'] for x in bag.values() if x['pokemon_id']} <= _pids:
            return None                                  # not this trainer's Pokedex as of that bag
        # ...and every species that bag holds a hundo of must be FOUR_STAR in it (R-B review): the subset test alone takes
        # the main account's LARGER Pokedex as the alt's. The account's own dex passes (525 of 525 on 2026-09-29).
        if not {x['pokemon_id'] for x in bag.values() if x['pokemon_id'] and (x['iv_total'] or 0) == 45} <= _hun:
            return None
        return _hun
    _dexh = (set(state['dex_hundos']) if isinstance(state.get('dex_hundos'), list)
             else _dex_hundo_set('pokedex_hundos_live.prev.json', P))
    def _dex_is_this_walks(p):
        try:
            return bool(ef._walk_fresh(p, 7200, _walk_t))
        except OSError:
            return False
    _dexh_now = (_dex_hundo_set('pokedex_hundos_live.json', C)           # saved below: the next report's "before" --
                 if _dex_is_this_walks('pokedex_hundos_live.json') else None)   # -- only if this walk's read wrote it (R-B review)
    first_hundo = lambda x: stage_ng(x) not in hundo_prev and _dexh is not None and x['pokemon_id'] not in _dexh
    # (R-B review) the unused hundos / bests / gl1 / ul1 / xxl lists are gone: `bests` read best_prev[stage] on the
    # defaultdict BEFORE testing `in`, which inserted every arrival's stage -- so the `stage_ng(x) in best_prev` guard in
    # What improved was always true and the FIRST copy of a stage was called "new best at its stage"

    # ---- PvP SAFETY, independent of keep_policy (user 2026-09-24: "Careful with the PVP stuff. Don't be lazy.") ----
    # For every pile mon, every league and every stage it can become: (1) a top-5 spread at a stage that reaches the
    # league cap (the rank rule); (2) is it BETTER than every copy you keep that can reach that stage and still enter
    # the league (same shadow/non-shadow class)? (2) is lawful only below the Best-of-kind floor (keep_config
    # pvp.best_rank_floor) -- anything else is printed as a CHECK line, never smoothed over.
    CAPS = {'gl': pv.GL_CAP, 'ul': pv.UL_CAP, 'ml': None}
    NAMES = {'gl': 'Great League', 'ul': 'Ultra League', 'ml': 'Master League'}
    floor = keep_config.pvp('best_rank_floor')
    sfloor = keep_config.pvp('shadow_rank_floor')        # rule 7's cut-off: a SHADOW's, legendaries included (H09-4)
    cls = lambda r: 'shadow' if r['fresh_alignment'] == 1 else 'plain'
    chain = lambda r, lg: pv.chain_stage_ranks(r, lg) or ([(r[lg + '_stage'], r[lg + '_rank'])] if r[lg + '_rank'] else [])
    pset = set(pile)
    best_kept = {}
    for x in C.values():
        if x['uid_hex'] in pset or keep_config.is_fused_component(x):   # (2026-09-26) fused components hold no ladder slot
            continue
        for lg in CAPS:
            for st, rk in chain(x, lg):
                if st and (CAPS[lg] is None or pv.fits(x, st, CAPS[lg], BS)):
                    k = (lg, st, cls(x))
                    if k not in best_kept or rk < best_kept[k][0]:
                        best_kept[k] = (rk, x)
    close, checks, floor_notes, close_calls, species_notes, uncollected = None, [], [], [], [], []
    over_cap = []                                        # top-N spreads this copy can never play (2026-09-30)
    unc_best = set()                                     # leagues whose uncollected shadows a close call says nothing kept beats
    _ubc = {}
    def _ub(x, lg):
        if (x['uid_hex'], lg) not in _ubc:
            _ubc[(x['uid_hex'], lg)] = pv.usable_best(x, lg, CAPS[lg], BS)
        return _ubc[(x['uid_hex'], lg)]
    def _species_best_beats(m, lg):
        """(name, rank, stage) of the KEPT Best GL/UL copy of m's own species (same PvP identity, non-shadow) when its
        usable rank -- viable stage first, then rank, the key keep_policy picks the Best by -- is at least as good as m's."""
        # Master League has no cap: keep_policy picks its Best by ml_rank (the chain's best stage), not the usable key
        mine = (m['ml_rank'], m['ml_stage']) if lg == 'ml' else _ub(m, lg)
        if not mine or mine[0] is None:
            return None
        ident = pv.pvid(m['species_name'], m['form'] or 0)
        for x in C.values():
            if (x['uid_hex'] in pset or cls(x) != 'plain' or ('pvp_best_' + lg) not in (why.get(x['uid_hex']) or ())
                    or pv.pvid(x['species_name'], x['form'] or 0) != ident):
                continue
            if lg == 'ml':
                if x['ml_rank'] is not None and x['ml_rank'] <= mine[0]:
                    return (desc(x, False), x['ml_rank'], x['ml_stage'] or ident)
                continue
            ub = _ub(x, lg)
            if ub and (ub[0], ub[1]) <= (mine[0], mine[1]):
                return (desc(x, False), ub[1], ub[2])
        return None
    CLOSE_CALL = 100                                     # top ~2.5% of 4,096 spreads: worth a line even when lawful
    for u in pile:
        m = C[u]
        for lg in CAPS:
            for st, rk in chain(m, lg):
                if not st:
                    continue
                capreach = CAPS[lg] is not None and pv.maxcp(st, BS) > CAPS[lg] + pv.VIABILITY_MARGIN
                if capreach and (close is None or rk < close[0]):
                    close = (rk, m, NAMES[lg], st, CAPS[lg] is None or pv.fits(m, st, CAPS[lg], BS))
                if capreach and rk <= pv.READY_RANK and (CAPS[lg] is None or pv.fits(m, st, CAPS[lg], BS)):
                    checks.append('%s is %s #%d as %s (a top-%d spread)' % (desc(m, False), NAMES[lg], rk, st, pv.READY_RANK))
                elif capreach and rk <= pv.READY_RANK:
                    # user 2026-09-30: "Why would I keep any GL and UL pokemon that cant participate?" -- lawful, but say so
                    over_cap.append('%s is %s #%d as %s, but its CP is already over that league cap there, so it can never '
                                    'play it' % (desc(m, False), NAMES[lg], rk, st.replace('_', ' ').title()))
                elif capreach and rk <= CLOSE_CALL and (CAPS[lg] is None or pv.fits(m, st, CAPS[lg], BS)):
                    # a strong spread that is only second-best (a 1/15/14 Raticate GL #21 behind a #20, 2026-09-24):
                    # lawful to release, but he decides -- a Favorite keeps it
                    bk = best_kept.get((lg, st, cls(m)))
                    _txt = '%s (%d/%d/%d) is %s #%d as %s' % (desc(m, False), m['iv_atk'], m['iv_def'], m['iv_sta'], NAMES[lg],
                                                             rk, stg(st))
                    if bk and bk[0] <= rk:
                        close_calls.append(_txt + ' -- your best kept there is #%d, so the better one stays and this one goes.' % bk[0])
                    else:
                        # IT IS THE BETTER ONE (H05-4: "#58 ... your best kept there is #216, so the better one stays and this
                        # one goes" sent the better copy): say the rule that still lets it go, the same order as the notes below
                        if cls(m) == 'shadow' and lg != 'ml' and lg not in keep_config.shadow_leagues():
                            _rule = 'you no longer keep %s shadows' % NAMES[lg]
                            unc_best.add(NAMES[lg])      # the summary below must not say "none beats every copy you keep" over this
                        elif rk > (sfloor if cls(m) == 'shadow' else floor) and (cls(m) == 'shadow' or m['pokemon_id'] not in ROSTER):
                            _rule = '#%d is past your #%d %scut-off' % (rk, sfloor if cls(m) == 'shadow' else floor,
                                                                      'shadow ' if cls(m) == 'shadow' else '')
                        elif cls(m) == 'plain' and _species_best_beats(m, lg):
                            _rule = 'your Best %s %s wins at another stage (one per species)' % (NAMES[lg], species_label(m))
                        else:
                            _rule = 'of nothing -- ***CHECK: no rule lets it go***'
                        close_calls.append(_txt + ' -- nothing you keep there is better (%s), so it goes only because %s.'
                                           % (('next best kept #%d' % bk[0]) if bk else 'none kept there', _rule))
                if CAPS[lg] is not None and not pv.fits(m, st, CAPS[lg], BS):
                    continue
                if cls(m) == 'shadow' and lg != 'ml' and lg not in keep_config.shadow_leagues():
                    # a league whose shadows he no longer collects (GL since 2026-09-26: "remove the gl shadows") -- a note,
                    # not a CHECK: nothing of that kind is kept by law
                    if rk <= floor:
                        uncollected.append('%s is %s #%d as %s -- you no longer keep %s shadows'
                                           % (desc(m, False), NAMES[lg], rk, stg(st), NAMES[lg]))
                    continue
                bk = best_kept.get((lg, st, cls(m)))
                if bk is None or rk < bk[0]:
                    note = '%s is your best %s %s (#%d%s)' % (desc(m, False), NAMES[lg], stg(st), rk,
                                                               ', next best kept #%d' % bk[0] if bk else '')
                    # A SHADOW is kept by rule 7 only inside pvp.shadow_rank_floor -- legendaries too: the roster's "Best at
                    # any rank" (LAW 2b) is the NON-shadow Best (H09-4, 2026-09-29: caps.rarity_shadow piled shadow Dialgas
                    # at UL #1053 / #1257 and this printed two false ***CHECK*** lines).
                    _sh = cls(m) == 'shadow'
                    if rk > (sfloor if _sh else floor) and (_sh or m['pokemon_id'] not in ROSTER):
                        # ONE LINE PER MON (2026-09-26): the #150 cut turned this into ~110 near-identical lines
                        floor_notes.append((m['uid_hex'], desc(m, False), '%s %s #%d%s%s' % (
                            NAMES[lg], stg(st), rk, ' (next best kept #%d)' % bk[0] if bk else '',
                            (' -- the shadow cut-off is #%d' % sfloor) if _sh and sfloor != floor else '')))
                    elif cls(m) == 'plain' and _species_best_beats(m, lg):
                        # ONE BEST PER SPECIES (LAW 2b), counted at every stage it can reach: a copy that is the best
                        # AS this stage can still lose to the species' Best, which wins as another stage (a 67% Murkrow
                        # GL #272 as Murkrow vs the kept 58% Murkrow, GL #162 as Honchkrow, 2026-09-25). Lawful -- a
                        # note, not a CHECK; a CHECK stays for a copy nothing of its species beats.
                        _sb = _species_best_beats(m, lg)          # cached via _ub: the repeat call is free
                        species_notes.append(note + ' -- but your Best %s %s is the %s (#%d as %s), one per species'
                                             % (NAMES[lg], species_label(m), _sb[0], _sb[1], stg(_sb[2])))
                    else:
                        checks.append(note)

    out = []
    # ---- WHAT THIS REPORT STANDS ON (H05-7 / H05-8 / H05-10) ----
    # this walk's own time: every row the walk re-read carries it (pogo_pipeline reconcile_db, last_scanned)
    def _iso(s):
        try:
            return _dt.datetime.strptime(s[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S') if s else None
        except ValueError:
            return None
    _stamp_t = lambda st: _dt.datetime.strptime(st, '%Y-%m-%d_%H%M%S')
    walk_t = _iso(_walk_t)
    # the GAME'S storage numbers, read by THIS walk only when bag_count.json was written within 2 min of it
    try:
        _bc = json.load(open(os.path.join(A, 'bag_count.json'), encoding='utf-8'))
        if not isinstance(_bc, dict):
            _bc = {}
    except Exception:
        _bc = {}
    _bc_t = _iso(_bc.get('ts'))
    # ONE-SIDED (R-B review): the walk writes bag_count.json AFTER it stamps last_scanned (pogo_pipeline reconcile_db), so a
    # file from before the stamp is an earlier walk's; and every number printed as "the game's own count" must have been read
    _bc_ok = bool(_bc_t and walk_t and -5 <= (_bc_t - walk_t).total_seconds() <= 120
                  and all(isinstance(_bc.get(k), int) for k in ('game_count', 'pokemon_only', 'eggs_incubated')))
    try:
        cap = json.load(open(os.path.join(ROOT, 'player_state.json'), encoding='utf-8')).get('max_pokemon_storage')
    except Exception:
        cap = None
    # THIS WALK'S CAP, OR SAY WHOSE (R-B review: H06-6 flagged a stale cap in full_audit's line only -- this block is the
    # one relayed): the walk's cap read is fail-soft and keeps the previous player_state.json, which has no read time
    _cap_note = ''
    if cap:
        try:
            if _walk_t and not ef._walk_fresh(os.path.join(ROOT, 'player_state.json'), 7200, _walk_t):
                _cap_note = ' [storage cap NOT read by this walk -- player_state.json is from %s]' % _dt.datetime.fromtimestamp(
                    os.path.getmtime(os.path.join(ROOT, 'player_state.json'))).strftime('%m-%d %H:%M')
        except Exception as _ce:
            _cap_note = ' [storage cap: age unknown (%s)]' % _ce
    _pushed, _pushed_sha = None, None                # the prune step's own read-back of the Transfer tag after the write
    try:
        _sl_txt = open(os.path.join(A, 'last_job_api_sync.log'), encoding='utf-8', errors='replace').read()
        if ('.%s.before_sync' % cur_stamp) in _sl_txt and _sl_txt.startswith('rc=0') and 'ALL TARGETS EXACTLY SYNCED' in _sl_txt:
            _m = re.search(r'^\s*Transfer\s+server=(\d+) want=(\d+)\s+\[OK\]', _sl_txt, re.M)
            _pushed = int(_m.group(1)) if _m and _m.group(1) == _m.group(2) else None
            # WHICH bytes were pushed: prune logs the preflight stamp's pile_sha256 prefix of Transfer.txt
            _h = re.search(r'^\s*pile\s+\S*Transfer\.txt\s+([0-9a-f]{16})\.\.\.', _sl_txt, re.M)
            _pushed_sha = _h.group(1) if _h else None
    except OSError:
        pass
    try:
        import hashlib
        _file_sha = hashlib.sha256(open(os.path.join(A, 'tagsets', 'Transfer.txt'), 'rb').read()).hexdigest()[:16]
    except OSError:
        _file_sha = None
    # WHAT THE WALK SAW (H05-7), decided BEFORE the lead line (R-B review: the frozen banner printed several lines below
    # "**Release the N in the Transfer tag.**"). Each walk is named by its OWN re-read time (the rows' last_scanned), the
    # snapshot stamp only when the rows carry none.
    _day = (walk_t or _stamp_t(cur_stamp)).date()
    _fmt = lambda t: t.strftime('%H:%M') if t.date() == _day else t.strftime('%m-%d %H:%M')
    _prev_t = _iso(max((x.get('last_scanned') or '') for x in P.values())) if P else None
    _hm = lambda st: _fmt(_prev_t if (st == prev_stamp and _prev_t) else _stamp_t(st))
    _cur_hm = _fmt(walk_t) if walk_t else _hm(cur_stamp)
    # not `prev_stamp != cur_stamp` (R-B review): that guard could only ever be False on an UNSYNCED walk, and hid the
    # frozen banner exactly there
    _same_bag = not _first and set(P) == set(C) and all(P[u]['cp'] == C[u]['cp'] for u in C)
    _no_new_walk = _same_bag and _prev_t is not None and _prev_t == walk_t   # a sync without a new walk (--skip-crawl)
    _frozen = _same_bag and not _no_new_walk
    # "RELEASE" ONLY FOR THE PILE THAT WAS PUSHED AND READ BACK (R-B review): the same bytes (prune's pile hash), the same
    # count, and a verify that did not fail afterwards (full_audit passes CULL_VERIFY=FAILED to this report)
    _stop = None
    if pile and _pushed is not None:
        _at = _stamp_t(cur_stamp).strftime('%H:%M')
        if _bc_ok and _bc.get('account_verified') is False:
            # pogo_pipeline writes account_verified=False when account_guard could not read / match the trainer: the guard only
            # WARNS then (H06-5), so this pile may have been built from another account's bag (R-B review)
            _stop = 'the account guard could not match the phone\'s trainer to this data set on this walk'
        elif os.environ.get('CULL_VERIFY') == 'FAILED':
            _stop = 'the verify after the %s sync FAILED' % _at
        elif not _pushed_sha:
            _stop = 'the %s sync log does not say which pile file it pushed' % _at
        elif _pushed_sha != _file_sha:
            _stop = ('Transfer.txt is not the file the %s sync pushed (pushed %s..., the file now %s...) -- it was rewritten '
                     'after the push' % (_at, _pushed_sha, _file_sha or '?'))
        elif _pushed != len(pile):
            _stop = 'the game read back %d in the tag, but %d of the pile file are in this walk' % (_pushed, len(pile))
    if unsynced:
        out.append('**%d in the pile file -- NOT pushed to the phone**: this walk (%s) never reached a sync, so the '
                   'Transfer tag still holds the last synced pile. Do not release from the tag until a cull pushes this one.'
                   % (len(pile), walk_t.strftime('%H:%M')))
    elif pile and _pushed is None:
        # NOT CONFIRMED IS NOT "RELEASE" (H10-3, 2026-09-29): the release line is the one he acts on, irreversibly. Without
        # the game's own read-back of the Transfer tag for THIS walk (a failed / refused push, or a verify that did not
        # pass), the tag on the phone may hold another pile than the vetted file -- so the first line says stop.
        out.append('**Do not release yet -- the Transfer tag was not confirmed for this walk.** %d in the pile file, but '
                   'the sync log has no read-back of the Transfer tag for this walk (the push failed, was refused, or its '
                   'verify did not pass). Re-run the cull.' % len(pile))
    elif pile and _stop:
        out.append('**Do not release yet -- %s.** %d in the pile file; the explanations below are for that file, not '
                   'necessarily for what the tag holds. Re-run the cull.' % (_stop, len(pile)))
    elif pile and _frozen:
        out.append('**Do not release yet if you caught, hatched, evolved, released or powered up anything since %s** -- '
                   'this walk (%s) saw nothing change at all, so it may have read a frozen copy of the game: re-cull first. '
                   'If you did nothing in between, the %d below are the ones in the Transfer tag (the game read back %d '
                   'in the sync that started at %s).' % (_hm(prev_stamp), _cur_hm, len(pile), _pushed, _stamp_t(cur_stamp).strftime('%H:%M')))
    elif pile:
        # (the snapshot is taken when the sync STARTS, ~20-40 s before prune pushes: "after the 17:20 push" was a minute off)
        out.append('**Release the %d in the Transfer tag.** (the game read back %d in the tag in the sync that started at %s)'
                   % (len(pile), _pushed, _stamp_t(cur_stamp).strftime('%H:%M')))
    else:
        out.append('**Nothing to release** -- the pile is empty.')
    if _bc_ok:
        _used, _eg = _bc['game_count'], _bc.get('eggs_incubated') or 0
        out.append('Bag %d%s%s -- the game\'s own count: %s Pokemon + %d egg%s in incubators%s' % (
            _used, ('/%d' % cap) if cap else '', (' (%d free)' % (cap - _used)) if cap else '',
            _bc.get('pokemon_only'), _eg, '' if _eg == 1 else 's', _cap_note))
        if _bc.get('pokemon_only') is not None and _bc['pokemon_only'] != len(C):
            out.append('***CHECK: the game counts %s Pokemon but this walk left %d in the bag -- the walk is incomplete, so '
                       'the counts and the pile below are not the whole bag***' % (_bc['pokemon_only'], len(C)))
    else:
        out.append('Bag %d%s%s -- Pokemon only, from this walk\'s rows (the game\'s own storage count was not read with '
                   'this walk, so eggs in incubators are not counted)%s' % (len(C), ('/%d' % cap) if cap else '',
                                                                            (' (%d free at most)' % (cap - len(C))) if cap else '',
                                                                            _cap_note))
    # (2026-09-26) a fused component is kept as 'fused' and can never be released while held inside its Kyurem
    _fz = [C[u] for u in pile if keep_config.is_fused_component(C[u])]
    if _fz:
        out.append('***CHECK: %d in the pile %s held inside a fused Kyurem (%s) -- kept as fused, never releasable; '
                   'it must not be in the pile***' % (len(_fz), 'is' if len(_fz) == 1 else 'are',
                                                      ', '.join(desc(x, False) for x in _fz)))
    out.append('')
    # THE COUNTS SAY WHAT THEY ARE (H05-7): a diff of two walks -- name both, name the kinds of arrival the walk can prove
    # (H05-5), and say it outright when nothing at all changed: three frozen walks (2026-09-29 05:06 / 05:09 / 05:11 read
    # the stale 04:59 graph) printed "evolved 0, caught 0, released 0" while he caught, hatched and released 46.
    # (each walk's name -- _hm / _cur_hm -- and the frozen verdict are computed above, before the lead line)
    _kinds = collections.Counter(arrived(x) for x in arr if not origin[x['uid_hex']])
    _counts = 'evolved %d, caught %d%s, released or traded away %d' % (
        len(ev), _kinds['caught'], ''.join(', %s %d' % (k, _kinds[k]) for k in ('hatched', 'traded to you') if _kinds[k]),
        len(released))
    if _first:
        _basis = 'first report for this account -- nothing to compare yet'
    elif state.get('walk') == prev_stamp:
        _basis = 'since the last report, walk %s -> %s: %s' % (_hm(prev_stamp), _cur_hm, _counts)
    else:
        _basis = 'since the %s walk (%s) -> %s: %s' % (
            _hm(prev_stamp), ("the last report's walk %s has no snapshot left" % state['walk']) if state.get('walk')
            else 'no earlier report on record', _cur_hm, _counts)
    # A WALK PROVEN FROZEN SAYS SO (H03, 2026-09-29). The identical-bag banner below catches a walk that saw NOTHING new;
    # the snapshot proof also catches a walk that saw SOME catches but missed others made before it walked (2026-09-24
    # 17:33:25 saw 2 new mons and missed Houndour 17:25, Munna, Litten, Yanma 17:31) -- and names the passes whose
    # "tagged / in sync / verified" lines were about stale objects. Plus this walk's own tripwire verdict when not OK.
    try:
        import walk_tripwires as _wt
        _fz = {s: m for s, _w, m in _wt.retro_frozen(last_n=12)}
        if prev_stamp in _fz:
            out.append('***CHECK: the %s walk this report compares against read a FROZEN bag -- it missed %s, made before it '
                       'walked -- so the counts below are measured from stale data, and whatever that pass reported as '
                       'tagged never reached the game***' % (_hm(prev_stamp), ', '.join(nm for _c, nm, _s in _fz[prev_stamp][:5])))
        _fp = next((f for f in reversed(_wt.history()) if f.get('walk_iso') == _walk_t), None)
        if _fp and _fp.get('verdict') not in (None, 'OK'):
            out.append('***CHECK: the freshness verdict of this walk is %s: %s***' % (_fp.get('verdict'), '; '.join(
                '%s %s' % (c, m) for lv, c, m in (_fp.get('findings') or []) if lv != 'INFO')[:300]))
    except Exception as _e:
        out.append('(walk freshness: not checked -- %s)' % _e)
    out.append('**What improved** (%s)' % _basis)
    if _same_bag:
        if _no_new_walk:                                 # a sync without a new walk (--skip-crawl): the same rows, not a freeze
            out.append('(no new walk since the last report -- the bag was not re-read, so there is nothing new to count)')
        else:
            out.append('***Nothing in the bag changed between the %s and the %s walk -- not one catch, hatch, evolution, '
                       'release or power-up. If you did any of those in between, this walk read a frozen copy of the game: '
                       'do not act on this report.***' % (_hm(prev_stamp), _cur_hm))
    # ONE LINE PER NEW KEEPER: what it is now, what it holds, and which pile mon it replaced -- the other half of
    # "why each one is in the pile" (user 2026-09-24: "like what improved and why each one was culled....")
    SHOW = dict(LABEL, hundo='hundo', pvp_spread='0-15-15 spread', origin='traded by E+F', favorite='favorite',
                adventure_effect='Adventure Effect', mighty='Mighty', location_card='location card',
                # H05-13: a keeper held ONLY by one of these was skipped as if it "went straight to the pile" -- a new form
                # (dex_only_copy), a Pichu (protected), a GL/UL IV keeper -- and "no new keepers this time" could print
                dex_only_copy=('your only copy of its line' if keep_config.line_pool_all() else 'your only copy of its form'),
                protected='keep-every-copy list', gl_iv='GL IV keeper', ul_iv='UL IV keeper',
                # 'not read yet' was false: the ranks are computed and can stay missing for good (keep_policy 1467-1470)
                rank_unknown='missing its PvP ranks', data_incomplete='held for incomplete data',
                fused='held in a fused Kyurem', xxs='XXS')
    _ab = {}                                             # the best NEW copy per stage, ANY kind: only it can be "the new best"
    for x in arr:                                        # (R-B review: a new hundo or shiny at the stage outranks the rest)
        if keep_config.is_fused_component(x):
            continue
        _k = stage_ng(x)
        if _k not in _ab or ((x['iv_total'] or 0), (x['cp'] or 0)) > ((_ab[_k]['iv_total'] or 0), (_ab[_k]['cp'] or 0)):
            _ab[_k] = x
    imp, undecided = [], []
    for x in arr:
        if x['uid_hex'] in pile_set:
            continue                                     # went straight to the pile: it is in the next section
        rs = [SHOW.get(k, k.replace('_', ' ')) for k in (why.get(x['uid_hex']) or ())]   # EVERY reason it is kept for
        if not rs:
            # neither kept nor piled: the keep reasons are not from this walk (a manual run after an unsynced walk) --
            # never "no new keepers" over it (R-B review)
            undecided.append(desc(x, False))
            continue
        tag = []
        if (x['iv_total'] or 0) == 45:
            # an EVOLVED hundo is the same hundo at a new stage, not a new one -- only the Pokedex "first" is news
            if not origin[x['uid_hex']]:
                tag.append('new hundo' + (', your first' if first_hundo(x) else ''))
            elif first_hundo(x):
                tag.append('your first hundo %s' % species_label(x))
        elif (not x['fresh_shiny'] and _ab.get(stage_ng(x)) is x and stage_ng(x) in best_prev
              and (x['iv_total'] or 0) > best_prev[stage_ng(x)]):
            tag.append('new best at its stage')
        for _lg, _cap in (('gl', pv.GL_CAP), ('ul', pv.UL_CAP)):
            # gl_rank / ul_rank is the CHAIN's best (gl_stage may be a later stage): judge that stage's reach, and name it
            _st = x[_lg + '_stage'] or sid(x)
            if x[_lg + '_rank'] == 1 and pv.maxcp(_st, BS) > _cap + pv.VIABILITY_MARGIN:
                tag.append(_lg.upper() + ' #1' + ('' if _st == sid(x) else ' as ' + stg(_st)))
        src = origin[x['uid_hex']]
        line = '**%s** (%s)%s: %s' % (desc(x, False), ('just evolved from %s' % species_label(src)) if src else 'just %s' % arrived(x),
                                      (' **%s**' % ', '.join(tag)) if tag else '', ', '.join(rs))
        if replaced.get(x['uid_hex']):
            line += ' -- replaces your %s' % ' and '.join(replaced[x['uid_hex']])
        rank = (0 if replaced.get(x['uid_hex']) else 1, 0 if tag else 1, -(x['iv_total'] or 0))
        imp.append((rank, line))
    imp.sort(key=lambda t: t[0])
    out.extend('- ' + l for _r, l in imp)       # EVERY one, never '+N more' (user 2026-09-26: "dont do this. always print it all out.")
    if undecided:
        out.append('- ***CHECK: %d new arrival%s with no keep decision -- not in policy_reasons.json and not in the pile '
                   '(%s): the keep reasons are not from this walk, so do not act on this report***'
                   % (len(undecided), '' if len(undecided) == 1 else 's', ', '.join(undecided)))
    elif not imp:
        out.append('- no new keepers this time')
    out.append('')
    if pile:
        out.append('**Why each one is in the pile**')
        if still:
            out.extend(still_lines(still))
        if from_pile:
            out.append('You evolved %d from the last pile instead of releasing them:' % len(from_pile))
            out.extend('%d. %s' % (i + 1, l) for i, l in enumerate(from_pile))
        n0 = len(from_pile)
        if lines:
            if still or from_pile:
                out.append('New this pass:')
            out.extend('%d. %s' % (n0 + i + 1, l) for i, l in enumerate(lines))
        if fodder:                                       # every mon still named -- as a table (2026-09-29: "Fix your formatting")
            if not lines and (still or from_pile):
                out.append('New this pass:')
            out.extend(fodder_lines(fodder))
        out.append('')
        out.append('**PvP safety check** (all %d, every league and every stage they can evolve into):' % len(pile))
        if checks:
            out.extend('- ***CHECK: %s***' % c for c in checks)
        else:
            out.append('- none is a top-%d spread%s%s' % (pv.READY_RANK, ' it can still play' if over_cap else '', (' -- closest: %s at %s #%d as %s%s'
                        % (desc(close[1], False), close[2], close[0], stg(close[3]),
                           '' if close[4] else ' (its CP is already over that league cap, so it can never play there)')) if close else ''))
            # a floor note IS a copy that beats every copy kept at that stage (bk is None or rk < bk[0]) -- the summary must
            # not say "none" above lines that say it is your best (H05-4)
            _exc = (["stage bests that lose to their species' Best at another stage"] if species_notes else []) + \
                   (['stage bests past your cut-off'] if floor_notes else []) + \
                   (['shadow stage bests in a league you no longer collect (%s)' % ', '.join(sorted(unc_best))] if unc_best else [])
            out.append('- none beats every copy you keep at any stage it could still play' + (
                ', except the %s (below)' % ' and the '.join(_exc) if _exc else ''))
        for n in species_notes + uncollected:
            out.append('- %s' % n)
        _fn = collections.OrderedDict()
        for u, who, what in floor_notes:
            _fn.setdefault((u, who), []).append(what)
        for (u, who), whats in _fn.items():
            out.append('- %s is your best %s -- outside your #%d cut-off, so no Best is kept there' % (who, '; '.join(whats), floor))
        for n in over_cap:
            out.append('- %s' % n)
        for n in close_calls:
            # user 2026-09-24: "I want whichever is best. Spares are not ok." -- say which one wins, never offer to keep both
            out.append('- close call: %s' % n)
    try:
        import evolve_targets
        ww = evolve_targets.lines()
        if ww:
            out.append('')
            out.append('**Which way to evolve**')
            # STANDING LINES ONCE (2026-09-29, pick 5): a line identical to last report's is a mon he has already been told
            # about (the gated Charcadets sat there for a week) -- name it, do not repeat the instruction.
            _prev_ww = set(state.get('which_way') or [])
            _new = [l for l in ww if l not in _prev_ww]
            _stand = [l for l in ww if l in _prev_ww]
            out.extend('- ' + l for l in _new)
            if _stand:
                out.append('- standing, unchanged (%d): %s' % (len(_stand), ', '.join(l.split(' (')[0] for l in _stand)))
        targets = {u: (e['fixed'] or list(e['split'] or [])) for u, e in evolve_targets._targets().items()}
    except Exception as e:
        out.append('(which way: not computed -- %s)' % e)
        targets = prev_targets
    # POWER UP COSTS (2026-09-30, Benny: "yes" to the game master's exact prices). REPORT ONLY: it reads the tag files and the walk's
    # balances and writes nothing -- no keep reason, no tag and no pile decision depends on it. Never fails the report.
    try:
        _pu = power_up_block(C, pile_set, why, lambda u: desc(C[u], False))
        if _pu:
            out.append('')
            out.extend(_pu)
    except Exception as e:
        out.append('(power up costs: not computed -- %s)' % e)
    print('\n'.join(l for l in out if l is not None))
    if unsynced:
        # an unsynced walk has no before_sync snapshot: remembering it under cur_stamp would pair THIS pile and these
        # reasons with ANOTHER walk's rows, and the next report would count from the wrong bag (H05-10)
        print('(this walk never reached a sync -- nothing remembered; the next report still counts from the %s walk)'
              % _hm(prev_stamp))
    elif '--dry-run' not in sys.argv:
        # 'which_way' and 'dex_hundos' ride along in 'prev' too: a RE-PRINT of this walk compares against what this report
        # compared against, and it said "standing, unchanged" from which_way (H05-9: the re-print re-announced them all)
        json.dump({'walk': cur_stamp, 'pile': pile, 'reasons': why, 'targets': {norm(u): v for u, v in targets.items()},
                   'which_way': (ww if 'ww' in dir() else []),
                   'dex_hundos': sorted(_dexh_now) if _dexh_now is not None else None,
                   'prev': {k: state.get(k) for k in ('walk', 'pile', 'reasons', 'targets', 'which_way', 'dex_hundos')}},
                  open(STATE, 'w', encoding='utf-8'))
    return 0


def still_lines(still):
    """The mons still in the pile from the last report: one table row per kind with its IVs, never a comma wall (2026-09-29)."""
    g = collections.OrderedDict()
    for d in still:
        m = re.match(r'^(\d+)% (.+)$', d)
        g.setdefault(m.group(2) if m else d, []).extend([int(m.group(1))] if m else [])
    # "same reasons as before" was never checked -- a rule change (the XXL trim, a new cut-off) can keep a mon in the pile
    # for a DIFFERENT reason (H05-11): say only what is known, that it was in the last pile and is still in the bag
    out = ['Still here from last time: %d mon%s, in the last pile too and not released yet.' % (len(still), '' if len(still) == 1 else 's'), '',
           '| In the pile | IVs |', '|---|---|']
    out += ['| %s | %s |' % (k, ', '.join('%d%%' % v for v in sorted(ivs, reverse=True)) or '-') for k, ivs in g.items()]
    return out + ['']                   # a table swallows the next line unless a blank line ends it


def fodder_lines(fodder):
    """The just-caught fodder block: a count of MONS, then one table row per kind -- never a run-on line (2026-09-29)."""
    n = sum(len(ivs) for _, ivs, _ in fodder)
    who = lambda kind, ivs: ('%d%% %s' % (ivs[0], kind)) if len(ivs) == 1 else '%s x%d (%s)' % (kind, len(ivs), ', '.join('%d%%' % v for v in ivs))
    if len(fodder) == 1:
        kind, ivs, k = fodder[0]
        return ['', 'Just-caught fodder (%d), below what you keep: **%s** -- you keep %s.' % (n, who(kind, ivs), k)]
    out = ['', 'Just-caught fodder: %d mon%s, each below what you keep.' % (n, '' if n == 1 else 's'), '', '| In the pile | You keep instead |', '|---|---|']
    out += ['| %s | %s |' % (who(kind, ivs), k.replace('|', '/')) for kind, ivs, k in fodder]
    return out


POWER_UP_LINES = 12          # mons that get a full line; any beyond are still NAMED, in one short line (never a "+N more")


def _power_up_verdict(e, brief=False):
    """'doable now' / 'doable after exchanging N candy for M XL (if the game allows the exchange)' / 'short X' ... (status: see
    game_opportunities.power_up_plan). brief = the short form for the one-line list of the mons past POWER_UP_LINES."""
    f = lambda v: '{:,}'.format(v)
    need, sh, st = e.get('need'), e.get('short') or {}, e['status']
    if not need:
        return 'no price' if brief else 'no price for it (the game master tables, its candy family or its levels are unknown)'
    if st == 'now':
        return 'doable now'
    if st == 'exchange':
        return ('doable after exchanging %s candy' % f(e['swap'])) if brief else (
            'doable after exchanging %s candy for %s XL (if the game allows the exchange)' % (f(e['swap']), f(sh['xl'])))
    if st == 'short':
        v = 'short ' + ' + '.join(p for p in ('%s dust' % f(sh['dust']) if sh.get('dust') else '', '%s candy' % f(sh['candy']) if sh.get('candy') else '',
                                              '%s XL' % f(sh['xl']) if sh.get('xl') else '') if p)
        if not brief and sh.get('xl') and e.get('swap') and not sh.get('dust') and not sh.get('candy'):
            v += ' (swapping candy for it would take %s; %s to spare)' % (f(e['swap']), f(max(e['spare'] or 0, 0)))
        return v
    if st == 'level':
        return ('above your trainer-level cap (L%g)' % e['cap']) if not brief else 'above your trainer-level cap'
    return 'a balance it needs was not read this walk' if not brief else 'balance not read'


def _power_up_line(e, name):
    """One mon of the Power Up block: what it costs, what the family holds of it, and the verdict."""
    f = lambda v: '{:,}'.format(v)
    lvl = lambda v: ('L%g' % v) if isinstance(v, (int, float)) else 'L?'
    need, have = e.get('need'), e.get('have') or {}
    head = '%s: %s -> %s' % (name(e['uid']), lvl(e.get('lv')), lvl(e.get('target')))
    if not need:
        return '%s: %s' % (head, _power_up_verdict(e))
    price = ' + '.join(p for p in ('%s dust' % f(need['dust']), '%s candy' % f(need['candy']) if need['candy'] else '',
                                   '%s XL' % f(need['xl']) if need['xl'] else '') if p)
    hold = ' + '.join(p for p in ('%s candy' % f(have['candy']) if need['candy'] and have.get('candy') is not None else '',
                                  '%s XL' % f(have['xl']) if need['xl'] and have.get('xl') is not None else '') if p)
    return '%s: %s%s -- %s' % (head, price, (' (you hold %s)' % hold) if hold else '', _power_up_verdict(e))


def power_up_lines(plan, name, tags):
    """The Power Up block (2026-09-30, Benny: "yes" to the game master's exact prices): one line per mon a Power Up tag holds, best
    news first -- what it costs, what its family holds, 'doable now' / 'doable after exchanging N candy' / 'short X' -- and a total.
    REPORT ONLY: nothing here is a keep reason, a tag or a pile decision. `plan` = game_opportunities.power_up_plan's list, `name(uid)`
    a mon as this report names it, `tags` = {'gl': tag name, 'ul': tag name}. The first POWER_UP_LINES get a full line; any beyond
    that are still ALL named, with a short verdict, in one line -- Benny's rule is that no list in this report ends in "+N more"
    (2026-09-26: "dont do this. always print it all out."). [] when the tags hold no one."""
    if not plan:
        return []
    f = lambda v: '{:,}'.format(v)
    out, shown, rest = [], plan[:POWER_UP_LINES], plan[POWER_UP_LINES:]
    for lg in ('gl', 'ul'):
        mine = [e for e in shown if e['league'] == lg]
        if mine:
            out.append('**%s**%s' % (tags[lg], '' if out else " (report only -- nothing here changes what you keep; the game master's prices "
                                                                "against this walk's balances)"))
            out.extend('- ' + _power_up_line(e, name) for e in mine)
    if rest:
        out.append('- and the other %d, in short: %s' % (len(rest), '; '.join('%s -- %s' % (name(e['uid']), _power_up_verdict(e, brief=True)) for e in rest)))
    priced = [e for e in plan if e.get('need')]
    tot = {k: sum(e['need'][k] for e in priced) for k in ('dust', 'candy', 'xl')}
    held = next((e['have']['dust'] for e in plan if e.get('have') and e['have'].get('dust') is not None), None)
    cnt = collections.Counter(e['status'] for e in plan)
    said = ', '.join(t for t in ('%d doable now' % cnt['now'] if cnt['now'] else '',
                                 '%d after exchanging candy' % cnt['exchange'] if cnt['exchange'] else '',
                                 '%d short' % cnt['short'] if cnt['short'] else '', '%d above your trainer-level cap' % cnt['level'] if cnt['level'] else '',
                                 '%d not read this walk' % cnt['unread'] if cnt['unread'] else '', '%d without a price' % cnt['unknown'] if cnt['unknown'] else '') if t)
    # every line is judged on its own: two doable mons of ONE family draw on the same candy and XL candy, so say so
    byfam = collections.defaultdict(list)
    for e in plan:
        if e.get('need') and e.get('family') is not None and e['status'] in ('now', 'exchange'):
            byfam[e['family']].append(name(e['uid']))
    clash = [n for v in byfam.values() if len(v) > 1 for n in v]
    out.append('Total for all %d: %s dust (%s), %s candy, %s XL -- %s%s' % (
        len(plan), f(tot['dust']), ('you hold %s' % f(held)) if held is not None else 'stardust not read this walk', f(tot['candy']), f(tot['xl']), said,
        ('; %s come from one family and share its candy, so they are not all doable together' % ', '.join(clash)) if clash else ''))
    return out


def power_up_block(C, pile_set, why, name):
    """The report's Power Up block for this walk: the members of the Power Up tags (the tag FILES -- what the game shows), each with
    granular_tags.power_ups' own (level now, best level), priced by game_opportunities against this walk's balances. [] when both
    tags are empty. C = {uid: bag row}, pile_set = the Transfer uids, why = policy_reasons.json, name(uid) = how the report names a mon."""
    import granular_tags, game_opportunities
    by = {norm(u): u for u in C}
    tags = {'gl': granular_tags.POWER_UP_GL, 'ul': granular_tags.POWER_UP_UL}
    mem = {}
    for lg, tag in tags.items():
        try:
            mem[lg] = [by[norm(u)] for u in open(os.path.join(A, 'tagsets', granular_tags.filename(tag)), encoding='utf-8').read().split()
                       if norm(u) in by]
        except OSError:
            mem[lg] = []
    if not any(mem.values()):
        return []
    _sets, detail = granular_tags.power_ups([r for u, r in C.items() if u not in pile_set], why)
    items = [(u, lg, *(detail.get((u, lg)) or (None, None))) for lg in ('gl', 'ul') for u in mem[lg]]
    return power_up_lines(game_opportunities.power_up_plan(items, C), name, tags)


def _selftest():
    rows = [('Bulbasaur', [91], '98%'), ('Cyndaquil', [71, 64], '96%, 91%, 89%'), ('Fletchling', [67, 67, 51], '84%')]
    got = fodder_lines(rows)
    assert got[0] == '' and got[1] == 'Just-caught fodder: 6 mons, each below what you keep.', got[:2]   # mons, not the 3 kinds; blank line first so the table never glues to a list item
    assert got[3:5] == ['| In the pile | You keep instead |', '|---|---|'] and len(got) == 5 + 3, got
    assert got[5] == '| 91% Bulbasaur | 98% |' and got[6] == '| Cyndaquil x2 (71%, 64%) | 96%, 91%, 89% |', got
    assert fodder_lines([('Alolan Graveler', [36], '91%')]) == ['', 'Just-caught fodder (1), below what you keep: **36% Alolan Graveler** -- you keep 91%.']
    st = still_lines(['91% Bulbasaur', '71% Cyndaquil', '64% Cyndaquil', '62% shadow Dialga'])
    assert st[0] == 'Still here from last time: 4 mons, in the last pile too and not released yet.' and st[2:4] == ['| In the pile | IVs |', '|---|---|'], st
    assert st[4:7] == ['| Bulbasaur | 91% |', '| Cyndaquil | 71%, 64% |', '| shadow Dialga | 62% |'] and st[7:] == [''], st
    # official names (2026-09-30): display only, and every doubt falls back to today's rendering
    global _NM
    assert _NM is not None and _NM.on, 'official_names_en.json did not load: %s' % (_pd.Names.load().error,)
    for sid, dex, want in (('mr_mime', 122, 'Mr. Mime'), ('ho_oh', 250, 'Ho-Oh'), ('nidoran_female', 29, 'Nidoran\u2640'),
                           ('raichu_alolan', 26, 'Alolan Raichu'), ('farfetchd_galarian', 83, "Galarian Farfetch'd"), ('flabebe', 669, 'Flab\u00e9b\u00e9'),
                           ('porygon_z', 474, 'Porygon-Z'), ('giratina_altered', 487, 'Giratina Altered'), ('machamp_shadow', 68, 'Machamp Shadow'),
                           ('unknown_thing', None, 'Unknown Thing'), ('?', None, '?')):
        assert stage_name(sid, dex) == want, (sid, stage_name(sid, dex), want)
    assert species_label({'pokemon_id': 29, 'species_name': 'Nidoran F'}) == 'Nidoran\u2640', 'Nidoran F'
    assert species_label({'pokemon_id': 1012, 'species_name': 'Poltchageist'}) == 'Poltchageist', 'a dex the game i18n lacks keeps the walk name'
    _saved, _NM = _NM, None
    try:
        assert stage_name('mr_mime', 122) == 'Mr Mime' and species_label({'pokemon_id': 29, 'species_name': 'Nidoran F'}) == 'Nidoran F', 'no names: today'
    finally:
        _NM = _saved
    # Power Up block (2026-09-30): the lines are pure text over game_opportunities.power_up_plan's dicts (the prices are tested there)
    nm = {'m': '100% Mandibuzz', 'd': '100% Dusknoir', 'l': '93% Lickilicky', 'x': '91% Mimikyu', 'u': '90% Seaking', 'n': '80% Nobody'}
    nd = lambda d, c, x: {'dust': d, 'candy': c, 'xl': x, 'steps': 0}
    hv = lambda c, x, d=2462829: {'dust': d, 'candy': c, 'xl': x}
    z = {'dust': 0, 'candy': 0, 'xl': 0}

    def pe(uid, lg, lv, tg, need, have, short, status, swap=0, spare=None, **kw):
        return dict({'uid': uid, 'league': lg, 'lv': lv, 'target': tg, 'need': need, 'have': have, 'short': short, 'status': status,
                     'swap': swap, 'spare': spare}, **kw)
    plan = [pe('m', 'ul', 16.0, 50.0, nd(492600, 264, 296), hv(4556, 601), z, 'now'),
            pe('d', 'ul', 49.5, 50.0, nd(15000, 0, 20), hv(6488, 18), dict(z, xl=2), 'exchange', 200, 6488),
            pe('l', 'ul', 43.0, 48.5, nd(142000, 0, 172), hv(982, 14), dict(z, xl=158), 'short', 15800, 982),
            pe('x', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(4, 4, 100000), dict(z, dust=150000, xl=292), 'short', 29200, 4),
            pe('u', 'ul', 40.0, 50.0, nd(250000, 0, 296), {'dust': None, 'candy': 1, 'xl': 1}, {}, 'unread'),
            pe('n', 'ul', 40.0, 52.0, None, None, {}, 'unknown')]
    tg = {'gl': 'Power Up to 1500', 'ul': 'Power Up to 2500'}
    got = power_up_lines(plan, nm.get, tg)
    want = ["**Power Up to 2500** (report only -- nothing here changes what you keep; the game master's prices against this walk's balances)",
            '- 100% Mandibuzz: L16 -> L50: 492,600 dust + 264 candy + 296 XL (you hold 4,556 candy + 601 XL) -- doable now',
            '- 100% Dusknoir: L49.5 -> L50: 15,000 dust + 20 XL (you hold 18 XL) -- doable after exchanging 200 candy for 2 XL (if the game allows the exchange)',
            '- 93% Lickilicky: L43 -> L48.5: 142,000 dust + 172 XL (you hold 14 XL) -- short 158 XL (swapping candy for it would take 15,800; 982 to spare)',
            '- 91% Mimikyu: L40 -> L50: 250,000 dust + 296 XL (you hold 4 XL) -- short 150,000 dust + 292 XL',
            '- 90% Seaking: L40 -> L50: 250,000 dust + 296 XL (you hold 1 XL) -- a balance it needs was not read this walk',
            '- 80% Nobody: L40 -> L52: no price for it (the game master tables, its candy family or its levels are unknown)',
            'Total for all 6: 1,149,600 dust (you hold 2,462,829), 264 candy, 1,080 XL -- 1 doable now, 1 after exchanging candy, 2 short, '
            '1 not read this walk, 1 without a price']
    assert got == want, '\n'.join(got)
    assert power_up_lines([], nm.get, tg) == [] and power_up_lines(None, nm.get, tg) == []
    # past 12 lines no mon is dropped (Benny 2026-09-26: no list ends in "+N more"): the rest are all NAMED in one short line, and the total counts all
    many = [pe('m', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(0, 400), z, 'now') for _ in range(14)] + [plan[2]]
    got = power_up_lines(many, nm.get, tg)
    assert len(got) == 1 + 12 + 1 + 1, got
    assert got[-2] == '- and the other 3, in short: 100% Mandibuzz -- doable now; 100% Mandibuzz -- doable now; 93% Lickilicky -- short 158 XL', got[-2]
    assert got[-1] == 'Total for all 15: 3,642,000 dust (you hold 2,462,829), 0 candy, 4,316 XL -- 14 doable now, 1 short', got[-1]
    got = power_up_lines([plan[0]] * 12 + [plan[1], plan[3], plan[4], plan[5], pe('m', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(0, 400), {}, 'level', cap=40.0)], nm.get, tg)
    assert got[-2] == ('- and the other 5, in short: 100% Dusknoir -- doable after exchanging 200 candy; 91% Mimikyu -- short 150,000 dust + 292 XL; '
                       '90% Seaking -- balance not read; 80% Nobody -- no price; 100% Mandibuzz -- above your trainer-level cap'), got[-2]
    both = power_up_lines([pe('m', 'gl', 30.0, 40.0, nd(10000, 15, 0), hv(20, 0), z, 'now'), pe('d', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(0, 400), z, 'now')],
                          nm.get, tg)
    assert both[0].startswith('**Power Up to 1500** (report only') and both[2] == '**Power Up to 2500**' and both[-1].startswith('Total for all 2:'), both
    fam = power_up_lines([pe('m', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(0, 400), z, 'now', family=355), pe('d', 'ul', 49.5, 50.0, nd(15000, 0, 20), hv(6488, 18), dict(z, xl=2), 'exchange', 200, 6488, family=355),
                          pe('l', 'ul', 43.0, 48.5, nd(142000, 0, 172), hv(982, 14), dict(z, xl=158), 'short', 15800, 982, family=355)], nm.get, tg)
    assert fam[-1].endswith('; 100% Mandibuzz, 100% Dusknoir come from one family and share its candy, so they are not all doable together'), fam[-1]
    two = power_up_lines([pe('m', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(0, 400), z, 'now', family=355), pe('d', 'ul', 49.5, 50.0, nd(15000, 0, 20), hv(6488, 18), dict(z, xl=2), 'exchange', 200, 6488, family=108)],
                         nm.get, tg)
    assert 'share its candy' not in two[-1] and 'share its candy' not in power_up_lines(plan, nm.get, tg)[-1], 'distinct families carry no note'
    nodust = power_up_lines([pe('m', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(0, 400, None), z, 'unread')], nm.get, tg)
    assert '(stardust not read this walk)' in nodust[-1], nodust
    lv = power_up_lines([pe('m', 'ul', 40.0, 50.0, nd(250000, 0, 296), hv(0, 400), {}, 'level', cap=40.0)], nm.get, tg)
    assert lv[1].endswith('-- above your trainer-level cap (L40)'), lv
    print('cull_report selftest (fodder tables, official names, Power Up block): ok')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        _selftest(); sys.exit(0)
    sys.exit(main())
