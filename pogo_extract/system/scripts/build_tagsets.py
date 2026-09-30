"""build_tagsets.py -- deterministically compute EVERY tag's membership from the
freshly-crawled DB, write uid-list files, print an auditable summary.

Tag set (2026-05-30, de-numbered + E/F merged + Costume widened to Event):
  GL IV   = pvp_iv_rule.qualifies for the GL stage. That rule is RANK-DRIVEN: rank <= ready_rank
            AND the ranked form's L50-hundo CP > 1500 + viability_margin. It is NOT the old
            ">= 1400 floor" this docstring used to claim -- GL_FLOOR/UL_FLOOR are vestigial
            (every call site passes a non-None cap, so `floor` is never consulted). 2026-09-02
  UL IV   = same rule against the UL stage (cap 2500 + viability_margin).
  XXL     = top-N by SHOWCASE SCORE per (pid, cf(form)), size_category=5. cf() is keep_policy's
            form-0 collapse -- grouping by RAW form silently split a species into two groups and
            handed out an extra cap slot (a Voltorb, 2026-09-02).
  Hundo / Nundo / Best Buddy = SQL rules
  Event   = any cosmetic variant: costume OR special/event background OR art
            background OR location card (the 370 union -- preserves every visible
            event variant; PoGo's in-game "event" is a catch-time computation we
            can't reproduce exactly, so we capture all visible variants instead)
  Traded by E+F = traded/lucky from ethanmateovz OR florandez (merged 2026-05-30)
  Legacy Moves = ALL legacy-move mons (legacy_accurate INTERSECT in_bag), MINUS Transfer (keep-all 2026-06-05)
  Transfer = keep_policy.py TRANSFER pile (run keep_policy FIRST; it writes
             6_Transfer.txt, which we read here and re-emit as Transfer.txt)

INVARIANT: every KEEP tag = (its rule) MINUS Transfer (subtracted at the end),
so no keep tag can hold a transfer-fodder mon.
"""
import sqlite3, json, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from pvp_iv_rule import qualifies as pvp_iv_qualifies, pvid, GL_CAP, UL_CAP
from costume_forms import COSTUME_FORMS, _MAX_KNOWN_FORM
from costume_forms import is_costume_form as _icf
import keep_config
import granular_tags   # single source of truth for caps (PVP rank/floor, XXL)

# _MAX_KNOWN_FORM is interpolated straight into SQL below. If costume_forms ever falls back to a
# None/str sentinel (a reasonable fix on that side) the f-string would emit `form > None` and the
# UNKNOWN-FORM GUARD would silently stop protecting brand-new costume forms. Fail loudly instead.
if not isinstance(_MAX_KNOWN_FORM, int) or isinstance(_MAX_KNOWN_FORM, bool) or _MAX_KNOWN_FORM <= 0:
    raise SystemExit("build_tagsets: costume_forms._MAX_KNOWN_FORM is %r, not a positive int -- the "
                     "Event unknown-form guard cannot be built. Fix costume_forms.py (a stale/absent "
                     "form_enum.json makes brand-new costume forms judge as PLAIN)." % (_MAX_KNOWN_FORM,))
DB = os.path.join(ROOT, 'pokemon.db')
OUTDIR = os.path.join(ROOT, 'system', 'analysis', 'tagsets')
os.makedirs(OUTDIR, exist_ok=True)

PVP_RANK = keep_config.pvp('ready_rank')
GL_FLOOR, UL_FLOOR = keep_config.pvp('gl_floor'), keep_config.pvp('ul_floor')
# L50 CP multiplier: imported, never re-hardcoded (defect D4 -- this file held a third
# copy of a number that already existed in two other places, with two different values).
from cpm_table import CPM50


def main():
    gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
    BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}

    def maxcp(sid):
        bs = BS.get(sid)
        if not bs: return 0
        return int(((bs.get('atk', 0) + 15) * (bs.get('def', 0) + 15) ** 0.5
                    * (bs.get('hp', 0) + 15) ** 0.5 * CPM50 ** 2) / 10)

    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    # SELECT * (2026-09-24): the XXL block now scores a copy at every stage it can evolve into (size_line.best_points ->
    # keep_policy.pvp_later_stages), which reads gender / fresh_form / costume -- a narrowed projection crashed it. The
    # engine ranks full rows; this mirror must see the same columns or its points can differ from the engine's.
    rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()

    # ---- cf(): keep_policy's FORM-0 COLLAPSE. VERBATIM MIRROR of keep_policy.py (base_form/cf,
    # incl. the _is_regional_code guard). Any (pid,form)-keyed CAP must use it or the same species
    # splits into a form-0 group and an explicit-base-form group and quietly gets DOUBLE the cap
    # slots. That is exactly what happened to XXL: this file grouped by raw `form` and emitted 207
    # members while keep_policy kept 206 -- the tag advertised a keeper the engine does not keep.
    # (lockdown 2026-09-02. TODO: collapse this + preflight_transfer's copy into one form_norm.py;
    # four hand-copies of this helper exist tree-wide.)
    _REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')
    def _is_regional_code(nm, f):
        return any(x in pvid(nm, f) for x in _REGSUF)
    from collections import Counter as _Counter
    _basecnt = defaultdict(_Counter)
    for r in rows:
        _f = r['form'] or 0
        _reg = (r['form_region'] or '').strip().lower()
        if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null') \
                and not _is_regional_code(r['species_name'], _f) and not _icf(_f):   # no costume base (2026-09-23)
            _basecnt[r['pokemon_id']][_f] += 1
    _base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}
    def cf(r):
        _f = r['form'] or 0
        return _base_form.get(r['pokemon_id'], _f) if _f == 0 else _f

    sets = {}   # tagname -> list of (uid, label)

    # 'GL IV' / 'UL IV' RETIRED 2026-09-09 (granular_tags.RETIRED_TAGS): the keep decision (pvp_iv_rule.qualifies)
    # is unchanged; the label is now the GL/UL Rank + Evo Rank tags, and audit_tags_membership proves every
    # qualifies() keeper carries one.

    # --- XXL : top-2 by SHOWCASE SCORE per (pid,form), size=5 (user 2026-06-08 "top 2 for showcase scores") ---
    # score = height*0.80 + weight*0.15 + IV*0.05 (Niantic's formula), normalized by group max (monotonic).
    # XXL (2026-09-23): per PvP identity (species + battle form; cosmetics fold), XXL badge only -- keep_policy rule 7.
    from pvp_iv_rule import pvid as _sc_pvid
    import size_line as _slx
    # ONE SELECTION (2026-09-29): size_line.xxl_keepers, exactly what keep_policy rule 7 marks (per species, and per type
    # only during an XXL TRIM). Fused components hold no ladder slot (2026-09-26).
    _xrows = [r for r in rows if not keep_config.is_fused_component(r)]
    _xby = {r['uid_hex']: r for r in _xrows}
    xxl = {u: f"{_xby[u]['species_name']} w{_xby[u]['weight_kg']:.1f}/h{_xby[u]['height_m']:.2f}" for u in _slx.xxl_keepers(_xrows)}
    sets['XXL'] = sorted(xxl.items(), key=lambda x: x[1])   # the 2 highest showcase points per species, XXL only

    # --- Transfer = keep_policy's pile (keep_policy writes 6_Transfer.txt FIRST) ---
    _tf = os.path.join(OUTDIR, '6_Transfer.txt')
    if not os.path.exists(_tf):
        # Falling back to an empty set silently wrote an EMPTY Transfer.txt AND disabled the
        # "no keep-tag may contain a Transfer mon" filter at the bottom of this file. Every tag
        # here is pushed to the phone by prune_tags, so a silent empty pile is a silent policy
        # change. keep_policy.py MUST run first. (lockdown 2026-09-02)
        raise SystemExit("build_tagsets: %s is missing -- run keep_policy.py FIRST. Refusing to "
                         "write tagsets from an empty Transfer pile." % _tf)
    TRANSFER = set(open(_tf).read().split())
    _nm = {r['uid_hex']: r['species_name'] for r in rows}
    sets['Transfer'] = sorted([(u, _nm.get(u, '?')) for u in TRANSFER], key=lambda x: (x[1], x[0]))   # uid_hex TIEBREAK, same reasoning as XXL above (2026-09-07): TRANSFER is a set, so a name-only key let same-species members (13 Pikachu today) fall to set-iteration order, which str-hash randomisation reshuffles EVERY process. preflight_stamp.pile_sha256 hashes these exact bytes, so a mere regeneration of an IDENTICAL pile changed the hash and prune_tags.py:357 announced 'PILE CHANGED SINCE PRE-FLIGHT ... NOT the same set of pokemon' -- false, on the one gate guarding the irreversible output. Name-then-uid keeps the human-readable species grouping AND makes the bytes a function of the pile alone.

    # --- rule-based SQL tags ---
    _cf_csv = ','.join(str(f) for f in sorted(COSTUME_FORMS)) or '-1'   # form-ENCODED costumes (fresh_costume=0) from the live enum -- costume_forms.py
    _oo_sql = ','.join("'" + o.replace("'", "''") + "'" for o in sorted(keep_config.origin_owners())) or "''"   # origin owners from keep_config (was hardcoded E+F) so the tag matches the keep decision
    SQL_TAGS = [
        ('Hundo', 'iv_total=45'),
        ('Nundo', 'is_zero=1 AND pokemon_id!=0'),
        # 'Event' RETIRED 2026-09-09: the native Event chip plus the two Background chips list every cosmetic.
        # 'Best Buddy' tag RETIRED 2026-06-07 (user: "nuke best buddy ... they're goats anyway") -- 0 sole-BB mons.
        ('Traded by E+F', "(is_traded=1 OR is_traded_flag_v2=1 OR is_lucky=1) "
                          "AND lower(original_owner_name) IN (" + _oo_sql + ")"),
    ]
    for tag, sql in SQL_TAGS:
        sets[tag] = sorted([(r['uid_hex'], r['species_name']) for r in
                            c.execute(f"SELECT uid_hex,species_name FROM pokemon WHERE in_bag=1 AND ({sql})")],
                           key=lambda x: x[1])

    # --- Evolve = keep_policy's 'evolve' reason: best pre-evos that claim a line cap slot
    # (evolve them up to fill the final-form caps; IV is preserved on evolution) ---
    # NOT a silent `except FileNotFoundError: pass`. Evolve_1/Evolve_2 are in prune_tags.PLAN, so
    # skipping them here leaves the PREVIOUS run's Evolve_1.txt / Evolve_2.txt on disk and prune
    # pushes those stale files to the phone as if they were current. Missing input = hard stop.
    # (lockdown 2026-09-02)
    _prpath = os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json')
    if not os.path.exists(_prpath):
        raise SystemExit("build_tagsets: %s is missing -- run keep_policy.py FIRST. Refusing to "
                         "leave stale Evolve_1/Evolve_2 tagsets on disk for prune_tags to push."
                         % _prpath)
    _reasons = json.load(open(_prpath, encoding='utf-8'))
    # 'Evolve 1' / 'Evolve 2' RETIRED 2026-09-09: identical sets to the granular 'Evolve Next' / 'Evolve Twice'.

    # --- GRANULAR COVERAGE TAGS (user 2026-09-02: "your labels dont make sense", then "im sure you can
    # label 1st 2nd 3rd, best ul, best gl, actually ranked ul and gl"). One tag used to cover 1,939 mons
    # ('Variant Floor') and another hid which of the three shadow slots was earned. granular_tags.build()
    # spreads every reason into a specific, self-explaining tag; it reads policy_reasons and NEVER changes
    # a keep/transfer decision (the Transfer hash assertion below proves that).
    import granular_tags
    for _tag, _uids in granular_tags.build(rows, TRANSFER, _reasons).items():
        sets[_tag] = sorted([(u, _nm.get(u, '?')) for u in _uids], key=lambda x: x[1])
    # Evolve Shiny / Evolve for Size: folded into the advice table (granular_tags.evolve_advice, 2026-09-29) --
    # granular_tags.build() ran it above; the table is written out for the report and the audits.
    _adv = granular_tags.LAST_ADVICE
    with open(granular_tags.EVOLVE_ADVICE + '.tmp', 'w', encoding='utf-8') as _f:
        json.dump(_adv, _f, indent=0, sort_keys=True)
    os.replace(granular_tags.EVOLVE_ADVICE + '.tmp', granular_tags.EVOLVE_ADVICE)
    print('=== evolve advice: %d copies (%s) ===' % (len(_adv), ', '.join('%s %d' % (t, len(us)) for t, us in sorted(
        granular_tags.evolve_tags(_adv).items()))))

    # POLICY CONSISTENCY: no keep-tag may contain a TRANSFER mon. (Restored 2026-09-02 -- the
    # granular-tag edit accidentally replaced this pass along with the block above it, which let 27
    # pile members stay in Event.txt and failed both the cull audit and the membership audit.)
    # MUST run after EVERY tag is built and BEFORE the coverage assertion, so coverage is measured
    # on the stripped sets that actually get pushed.
    for _t in list(sets):
        if _t != 'Transfer':
            sets[_t] = [(u, l) for (u, l) in sets[_t] if u not in TRANSFER]

    # ADVICE NEVER BESIDE AN EVOLVE LABEL (2026-09-26, audit_labels' rule): Power Up / Unlock 2nd Move come off any copy
    # that is being told to evolve -- powering up the stage it is leaving.
    _ev = {u for t in granular_tags.EVOLVE_TAGS for u, _ in sets.get(t, [])}
    for _t in (granular_tags.POWER_UP_GL, granular_tags.POWER_UP_UL, granular_tags.SECOND_MOVE):
        if _t in sets:
            sets[_t] = [(u, l) for (u, l) in sets[_t] if u not in _ev]

    # COVERAGE ASSERTION -- the whole point of the block above. Every in-bag mon must end up either in the
    # Transfer pile or carrying >=1 keep tag. A silent gap here is exactly the 56.9% hole this replaced.
    _pile_uids = set(TRANSFER)
    _tagged = set()
    for _t, _members in sets.items():
        if _t == 'Transfer':
            continue
        _tagged.update(u for u, _ in _members)
    # NATIVE-CHIP COVERAGE (2026-09-09): a kept mon whose every reason the game already shows with a filter chip
    # (rarity -> Legendary/Mythical, shiny -> Shiny, location_card -> Background, adventure_effect -> Adventure
    # Effect) is explained in-game without a tag of ours. Everything else must still carry >=1 tag.
    _nat = granular_tags.NATIVE_COVERED_REASONS
    # 'Last Copy' chip retired 2026-09-23 (user). dex_only_copy is never a mon's ONLY reason (measured: 0), so the
    # mon's other reason carries the label. If it ever is the only one, the set below is empty and the mon still
    # fails coverage -- the safe direction.
    _META = {'dex_only_copy'}
    # 2026-09-24: dex_only_copy CAN now be a mon's only reason (the shadow rank floor left a lone shadow Vibrava kept
    # as the last copy of its form) -- it is in NATIVE_COVERED_REASONS, so a mon whose reasons are all native/meta is
    # covered; a mon with NO reason at all still fails.
    # A PvP comb-up HELD for candy / a missing item carries no evolve tag on purpose (user 2026-09-24: split like the
    # regular comb-ups -- "kept, labelled once he can"); if that is its only reason it is covered by that decision.
    try:
        _held = {u for u, v in json.load(open(os.path.join(os.path.dirname(OUTDIR), 'pvp_combup_labels.json'),
                                             encoding='utf-8')).items() if v.get('status') == 'hold'}
    except (OSError, ValueError):
        _held = set()
    _CU_R = {'pvp_combup_gl', 'pvp_combup_ul'}
    _uncovered = {r['uid_hex'] for r in rows
                  if r['uid_hex'] not in _tagged and r['uid_hex'] not in _pile_uids
                  and not (set(_reasons.get(r['uid_hex']) or [])
                           and set(_reasons.get(r['uid_hex']) or []) <= (_nat | _META | (_CU_R if r['uid_hex'] in _held else set())))}
    if _uncovered:
        _ex = sorted(_uncovered)[:5]
        raise SystemExit('build_tagsets: %d kept mon(s) carry NO tag -- coverage is not 100%%. '
                         'A keep reason exists with no tag mapped to it. Examples: %s'
                         % (len(_uncovered), _ex))
    print('=== coverage: every one of the %d kept mons carries >=1 tag ==='
          % (len(rows) - len(_pile_uids)))



    for tag, members in sets.items():
        fn = os.path.join(OUTDIR, granular_tags.filename(tag))
        with open(fn, 'w', encoding='utf-8') as f:
            f.write('\n'.join(u for u, _ in members))
        print(f"=== {tag}: {len(members)} ===")

    # EMPTY-SET CONTRACT (2026-09-09). A registered tag build() did NOT emit this cycle gets an EMPTY file, so
    # prune pushes want=<empty> and strips its stale members. 'Safety Hold' sat on an Enamorus for 5 days because
    # nothing ever rewrote its 2026-09-03 file: build() stopped emitting it, the old file stayed, prune pushed it
    # as-is every cycle (user: "Why is it tagged in safety hold and never resolved?"). The distinction prune keeps:
    # a file that is MISSING still means "the producer did not run -> do not touch" (D5); PRESENT-and-EMPTY means
    # "the engine says nobody qualifies". prune never CREATES a device tag for an empty want.
    # RETIRED tags (granular_tags.RETIRED_TAGS) get their stale file DELETED: prune strips them on the device from
    # that list, and a leftover file would be an orphan audit_registry refuses.
    _written = set(sets)
    for _tag, (_fn, _col) in granular_tags.registry().items():
        if _tag in _written or _tag == 'Transfer':
            continue
        open(os.path.join(OUTDIR, _fn), 'w', encoding='utf-8').close()
        print(f"=== {_tag}: 0 (nobody qualifies this cycle -- empty file, pushed as empty) ===")
    for _tag in granular_tags.RETIRED_TAGS:
        _p = os.path.join(OUTDIR, granular_tags.filename(_tag))
        if os.path.exists(_p):
            os.remove(_p)
            print(f"=== {_tag}: RETIRED -- stale tagset file removed ===")
    c.close()


if __name__ == '__main__':
    main()
