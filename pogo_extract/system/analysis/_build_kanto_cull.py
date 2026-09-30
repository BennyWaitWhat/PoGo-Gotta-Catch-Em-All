import sqlite3, json, sys, os
sys.path.insert(0, os.path.abspath('.'))  # project root holds costume_forms.py
import costume_forms as CF  # authoritative is_costume_form(form_code)

DB = 'pokemon.db'
SRC = 'system/analysis/_kanto_line_analyses.json'
OUT = 'system/analysis/kanto_cull_plan.json'

lines = json.load(open(SRC, encoding='utf-8'))

# Flatten cull entries (dedupe by uid prefix)
raw = []
seen = set()
for ln in lines:
    for c in ln.get('cull', []):
        u = c['uid']
        if u in seen:
            continue
        seen.add(u)
        raw.append({'uid': u, 'species': c['species'], 'family': ln['family'], 'base': ln['base']})

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

def fetch(uid_prefix):
    # uids in analyses are sometimes 8-char prefixes; match uid_hex LIKE prefix%
    cur.execute("SELECT * FROM pokemon WHERE uid_hex = ?", (uid_prefix,))
    rows = cur.fetchall()
    if rows:
        return rows, 'exact'
    cur.execute("SELECT * FROM pokemon WHERE uid_hex LIKE ?", (uid_prefix + '%',))
    rows = cur.fetchall()
    return rows, 'prefix'

STAR_BADGE_CODES = {11, 14}  # PokedexCategory ThreeStar(11)/FourStar(14) badges, NOT wardrobe costumes

def _i(v):
    """Coerce DB cell (may be None / '' / '0' TEXT / int) to int; non-numeric -> 0."""
    if v is None:
        return 0
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0

def special_axes(r):
    """HARD keep axes only (irreversible-cull blockers). best_buddy + traded handled separately."""
    flags = []
    ivt = _i(r['iv_total'])
    # shiny
    if _i(r['is_shiny']) or _i(r['fresh_shiny']):
        flags.append('shiny')
    # hundo
    if _i(r['is_hundo']) or ivt == 45:
        flags.append('hundo')
    # nundo
    if _i(r['is_zero']) or ivt == 0:
        flags.append('nundo')
    # lucky
    if _i(r['is_lucky']):
        flags.append('lucky')
    # shadow / purified (alignment or fresh_alignment nonzero)
    al = _i(r['alignment'])
    fal = _i(r['fresh_alignment'])
    if al != 0 or fal != 0:
        flags.append('shadow/purified(align=%s/%s)' % (al, fal))
    # COSTUME — authoritative, two-path:
    #  (1) FORM-encoded costume: is_costume_form(fresh_form|form) per costume_forms module.
    #  (2) FIELD-encoded costume: fresh_costume/costume/costume_decoration_id nonzero AND
    #      the code is NOT a PokedexCategory star-badge (11=ThreeStar, 14=FourStar).
    #      Any other nonzero field code = genuine wardrobe costume (e.g. 57/58/71/74/83).
    ff = _i(r['fresh_form']); fm = _i(r['form'])
    form_costume = False
    for code in (ff, fm):
        try:
            if code and CF.is_costume_form(code):
                form_costume = True
        except Exception:
            pass
    fc = _i(r['fresh_costume']); cc = _i(r['costume']); cdid = _i(r['costume_decoration_id'])
    field_codes = {x for x in (fc, cc, cdid) if x}
    real_field_costume = any(code not in STAR_BADGE_CODES for code in field_codes)
    if form_costume or real_field_costume:
        flags.append('costume(form?%s field=%s)' % (form_costume, sorted(field_codes)))
    # XXL (size cat 5 or size_enum 5)
    sc = _i(r['pokemon_size_category'])
    se = _i(r['size_enum'])
    if sc == 5 or se == 5:
        flags.append('XXL')
    # location card -> ANY real signal is conservative-exclude (irreversible; data-completeness rule).
    # has_location_card / loc_LocationCard are authoritative; fresh_has_location_card alone is the
    # unreliable fresh-flag but we STILL exclude on it (cost of wrong cull >> keeping a dupe).
    if _i(r['has_location_card']) or _i(r['fresh_has_location_card']) or _i(r['loc_LocationCard']):
        flags.append('location_card(hlc=%s,fhlc=%s,loc=%s)' % (r['has_location_card'], r['fresh_has_location_card'], r['loc_LocationCard']))
    # auth tags that imply specials (Legacy etc.)
    atn = (r['auth_tag_names'] or '')
    for t in ['Legacy', 'Hundo', 'Nundo', 'XXL', 'Lucky', 'Shadow', 'Shiny']:
        if t.lower() in atn.lower():
            flags.append('tag:%s' % t)
    return flags

def soft_axes(r):
    """best_buddy / traded: keep axes per user memory, but analysts deliberately culled some.
    Surface as a review bucket; EXCLUDE from the irreversible cull to be rule-safe."""
    s = []
    if _i(r['is_best_buddy']):
        s.append('best_buddy')
    if _i(r['is_traded']) or _i(r['is_traded_flag_v2']):
        s.append('traded')
    return s

resolved = []
problems = []
for item in raw:
    rows, how = fetch(item['uid'])
    if len(rows) == 0:
        problems.append((item['uid'], item['species'], 'NOT_FOUND'))
        continue
    if len(rows) > 1:
        problems.append((item['uid'], item['species'], 'AMBIGUOUS x%d' % len(rows)))
        # still inspect all matches; if any is special, flag
    r = rows[0]
    flags = special_axes(r)
    soft = soft_axes(r)
    in_bag = r['in_bag']
    item2 = {
        'uid': r['uid_hex'],
        'uid_input': item['uid'],
        'species': item['species'],
        'family': item['family'],
        'iv': '%s/%s/%s' % (r['iv_atk'], r['iv_def'], r['iv_sta']),
        'iv_total': r['iv_total'],
        'in_bag': in_bag,
        'match': how,
        'special_flags': flags,
        'soft_flags': soft,
        'auth_tags': r['auth_tag_names'],
    }
    resolved.append(item2)

hard_leaks = [x for x in resolved if x['special_flags']]
bb_leaks = [x for x in resolved if (not x['special_flags']) and x['soft_flags']]

reason_map = {}
for ln in lines:
    for c in ln.get('cull', []):
        reason_map[c['uid']] = 'Redundant non-special duplicate per line analysis (%s); off-spread/non-competitive, no keep axis.' % ln['base']

def is_costume_only(flags):
    """A flag set whose ONLY special axis is a costume (no loc-card/shiny/hundo/lucky/shadow/legacy/XXL/nundo)."""
    return len(flags) >= 1 and all(f.startswith('costume(') for f in flags)

plan = []
excl_hard = []        # genuine non-costume specials OR costume+other-special -> hard exclude
excl_soft = []        # best_buddy / traded -> user-veto bucket, excluded
excl_bag = []
costume_overflow = [] # costume-ONLY: cap-overflow per documented top-4 rule -> INCLUDED w/ flagged reason
for x in resolved:
    if x['special_flags']:
        if is_costume_only(x['special_flags']):
            costume_overflow.append(x)
            plan.append({'uid': x['uid'], 'species': x['species'],
                         'reason': 'COSTUME OVERFLOW past top-4 cosmetic cap (%s) — sanctioned by keep_policy (excess costumes -> Transfer is expected). No other special axis. VETO if you want this cosmetic copy.' % x['family']})
            continue
        excl_hard.append(x)
        continue
    if x['soft_flags']:
        excl_soft.append(x)
        continue
    if x['in_bag'] != 1:
        excl_bag.append(x)
        continue
    plan.append({'uid': x['uid'], 'species': x['species'], 'reason': reason_map.get(x['uid_input'], 'Redundant non-special duplicate per line analysis.')})

json.dump(plan, open(OUT, 'w', encoding='utf-8'), indent=2)

print('=== SUMMARY ===')
print('raw cull entries (deduped)   :', len(raw))
print('resolved in DB               :', len(resolved))
print('problems (notfound/ambig)    :', len(problems))
print('HARD specials EXCLUDED       :', len(excl_hard))
print('best_buddy/traded EXCLUDED   :', len(excl_soft))
print('not in_bag EXCLUDED          :', len(excl_bag))
print('costume-overflow INCLUDED    :', len(costume_overflow))
print('FINAL written cull plan      :', len(plan))
print()
if problems:
    print('--- PROBLEMS ---');  [print(' ', p) for p in problems];  print()
print('--- HARD specials EXCLUDED (true specials kept safe; analyst mislabels caught) ---')
for x in excl_hard:
    print('  %s %-16s %-8s %s tags=%s' % (x['uid'], x['species'], x['iv'], x['special_flags'], x['auth_tags']))
print()
print('--- best_buddy/traded EXCLUDED (rule-safe; user-veto bucket) ---')
for x in excl_soft:
    print('  %s %-16s %-8s %s' % (x['uid'], x['species'], x['iv'], x['soft_flags']))
print()
print('--- COSTUME-OVERFLOW INCLUDED (past top-4 cap; cap-sanctioned cull) ---')
for x in costume_overflow:
    print('  %s %-16s %-8s %s tags=%s' % (x['uid'], x['species'], x['iv'], x['special_flags'], x['auth_tags']))
print()
# FINAL HARD-GATE: written plan must contain ZERO non-costume specials and ZERO best_buddy/traded.
final = json.load(open(OUT, encoding='utf-8'))
viol = []
for p in final:
    cur.execute('SELECT * FROM pokemon WHERE uid_hex=?', (p['uid'],))
    rr = cur.fetchone()
    hard = special_axes(rr)
    soft = soft_axes(rr)
    noncostume_hard = [f for f in hard if not f.startswith('costume(')]
    if noncostume_hard or soft:
        viol.append((p['uid'], p['species'], noncostume_hard + soft))
print('=== FINAL HARD-GATE on written plan ===')
print('entries:', len(final))
print('non-costume-special / best_buddy / traded violations:', len(viol))
if viol:
    for v in viol: print('  !!! VIOLATION', v)
    sys.exit(1)
else:
    print('CLEAN: 0 shiny/hundo/nundo/lucky/shadow/legacy/location_card/XXL/best_buddy/traded in the cull plan.')
    print('       (the only special axis present is sanctioned costume-overflow x%d, each flagged for user veto.)' % len(costume_overflow))

# species tally
from collections import Counter
print()
print('--- cull-by-species tally (written plan) ---')
for sp, n in sorted(Counter(p['species'] for p in plan).items(), key=lambda kv: (-kv[1], kv[0])):
    print('  %-18s %d' % (sp, n))
print()
print('TOTAL cull entries written:', len(plan))
