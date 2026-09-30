#!/usr/bin/env python
"""DEEP audit -- goes beyond the 12-tag invariant check.

1. FORM CENSUS: every distinct (species, form) code in the bag resolved against the live
   PokemonDisplayProto.Form enum (form_enum.json) and classed base/regional/costume/form.
2. FALSE-NEGATIVE costume hunt: any 'form'-class code whose enum NAME contains a costume word
   (a costume costume_forms.py might have missed -> would sit untagged in the plain cull).
3. FALSE-POSITIVE hunt: any 'costume'-class code whose name contains a battle-form word.
4. REGIONAL-LEAK hunt: regional-named forms carrying a base-region tag (Raichu-class).
5. The full 12-tag invariant triple-check + completeness + transfer-safety + disjointness +
   accounting + enum-completeness + nonzero-merged + mis-fold.
"""
import sqlite3, json, sys, os
from collections import defaultdict, Counter
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8')
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
from pvp_iv_rule import pvid, maxcp, GL_CAP, UL_CAP, VIABILITY_MARGIN
from costume_forms import is_costume_form, FORM_ENUM, classify
import keep_policy as kp

DB = os.path.join(ROOT, 'pokemon.db')
legacy = set(e['uid_hex'] for e in json.load(open(os.path.join(ROOT, 'legacy_accurate.json'), encoding='utf-8')))
gm = json.load(open(os.path.join(ROOT, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
seen = set(e['pid'] for e in json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json')))['entries'])
is_pre, term, dist, _ = kp.build_evo_graph(gm, seen)
GT = {415: {1: set(), 2: {416}}, 757: {1: set(), 2: {758}}, 361: {1: {362}, 2: {478, 362}},
      281: {1: {475, 282}, 2: {282}}, 280: {1: {475, 282}, 2: {282}}, 412: {1: {414}, 2: {413}}}


def reach(r):
    gt = GT.get(r['pokemon_id'])
    if gt is not None:
        return gt.get(r['gender'], set())
    sid = pvid(r['species_name'], r['form'] or 0)
    return term.get(sid, set()) if is_pre.get(sid) else set()


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
    pr = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'policy_reasons.json'), encoding='utf-8'))
    RM = pr['reasons'] if (isinstance(pr, dict) and isinstance(pr.get('reasons'), dict)) else pr
    keptu = set(r['uid_hex'] for r in rows if isinstance(RM.get(r['uid_hex']), list) and RM.get(r['uid_hex']))
    allu = set(r['uid_hex'] for r in rows); xferu = allu - keptu

    def T(r):
        return set(t for t in (r['auth_tag_names'] or '').split(';') if t)

    # ===== 1. FORM CENSUS =====
    formrec = defaultdict(lambda: [0, 0, 0, 0])   # (pid,ff) -> [tot,kept,event,xfer]
    for r in rows:
        ff = r['fresh_form'] or 0; k = (r['pokemon_id'], ff); formrec[k][0] += 1
        if r['uid_hex'] in keptu: formrec[k][1] += 1
        if 'Event' in T(r): formrec[k][2] += 1
        if r['uid_hex'] in xferu: formrec[k][3] += 1
    byclass = Counter()
    for (pid, ff), v in formrec.items():
        byclass[(classify(FORM_ENUM.get(ff)) if ff else 'base')] += v[0]
    print("FORM-CLASS CENSUS (specimens):", dict(byclass), "| distinct codes:", len(formrec))

    # FULL-ENUM verification: classify EVERY game form (not just in-bag) so a year-less costume the
    # classifier would miss is caught BEFORE the user ever catches one.
    ACC_FULL = ('HAT', 'HOOD', 'MASK', 'GLASSES', 'SCARF', 'HELMET', 'WIG', 'OUTFIT', 'DRESS', 'TUXEDO',
                'KIMONO', 'YUKATA', 'PONCHO', 'SOMBRERO', 'BANDANA', 'VISOR', 'MONOCLE', 'GOGGLE', 'BEANIE',
                'FEDORA', 'FLOWERCROWN', 'STRAWHAT', 'EARMUFF', 'BOWTIE', 'CROCHET', 'FLYING', 'ANNIV',
                'PARTY', 'WITCH', 'SANTA', 'HALLOWEEN', 'HOLIDAY', 'DIWALI', 'GOFEST', 'GOTOUR', 'WCS',
                'JEJU', 'KURTA', 'HORIZON', 'POPSTAR', 'ROCKSTAR', 'LIBRE', 'STARMOBILE', 'FOSSIL')
    fullmiss = [n for f, n in FORM_ENUM.items() if classify(n) == 'form' and n and any(w in n.upper() for w in ACC_FULL) and 'CROWNED' not in n.upper()]
    print(f"FULL-ENUM costume misses (game-wide form-class w/ costume word): {fullmiss or 'none'}")

    BROAD = ('HAT', 'CAP', 'HOOD', 'MASK', 'GLASSES', 'SCARF', 'HELMET', 'WIG', 'COSTUME', 'OUTFIT',
             'DRESS', 'TUXEDO', 'KIMONO', 'YUKATA', 'PONCHO', 'SOMBRERO', 'BANDANA', 'VISOR', 'MONOCLE',
             'GOGGLE', 'BEANIE', 'FEDORA', 'HOLIDAY', 'PARTY', 'WITCH', 'SANTA', 'WEDDING', 'KURTA',
             'JEJU', 'HORIZON', 'FOSSIL', 'STARMOBILE', 'POPSTAR', 'ROCKSTAR', 'LIBRE', 'FLOWERCROWN',
             'EARS', 'HORNS', 'CROWN', 'SWIM', 'DIWALI', 'GOFEST', 'GOTOUR', 'WCS', 'ANNIV')
    # NB: bare SPRING/SUMMER/WINTER/FALL are NATURAL seasonal forms (Deerling/Sawsbuck), NOT
    # costumes -- excluded from the hunt; season COSTUMES carry a year and are caught already.
    BATTLE = ('ORIGIN', 'THERIAN', 'CROWNED', 'ATTACK', 'DEFENSE', 'SPEED', 'BLADE', 'SHIELD', 'ZEN',
              'HERO', 'STRIKE', 'AMPED', 'LOWKEY', 'INCARNATE', 'ALTERED', 'PRIMAL', 'MEGA', 'GMAX',
              'DYNAMAX', 'SUNSHINE', 'RAINY', 'SNOWY', 'SUNNY')
    fn = []; fp = []; leak = set()
    for (pid, ff), v in formrec.items():
        if not ff:
            continue
        nm = FORM_ENUM.get(ff); cls = classify(nm); u = (nm or '').upper()
        if cls == 'form' and nm and any(w in u for w in BROAD) and 'CROWNED' not in u:
            fn.append((nm, v[0], v[2]))
        if cls == 'costume' and nm and any(w in u for w in BATTLE):
            fp.append((nm, v[0]))
    for r in rows:
        ff = r['fresh_form'] or 0
        if ff and classify(FORM_ENUM.get(ff)) == 'regional' and (r['form_region'] or '').strip().lower() in ('', 'normal', 'kantonian', 'none', 'null'):
            leak.add((r['species_name'], FORM_ENUM.get(ff)))
    print("FALSE-NEG costume candidates ('form'-class w/ costume word):", fn or "none")
    print("FALSE-POS ('costume'-class w/ battle word):", fp or "none")
    print(f"REGIONAL-LEAK (regional name, base-region tag): {len(leak)} {sorted(leak)[:8]}")

    # ===== 2. 12-TAG TRIPLE-CHECK =====
    viol = defaultdict(list); count = defaultdict(int); misfold = 0; merged = 0; enum_missing = set()
    KEEP = {'GL IV', 'UL IV', 'XXL', 'Hundo', 'Nundo', 'Event', 'Best Buddy', 'Traded by E+F', 'Legacy Moves', 'Evolve 1', 'Evolve 2'}
    EF = lambda r: (r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1 or r['is_lucky'] == 1) and (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez')
    for r in rows:
        tg = T(r); iv = r['iv_total'] or 0; nm = r['species_name']; u = r['uid_hex']; ff = r['fresh_form'] or 0
        for t in tg:
            count[t] += 1
        if ff and ff not in FORM_ENUM: enum_missing.add(ff)
        if is_costume_form(r['form']) and not is_costume_form(ff): misfold += 1
        if ff and (r['form'] or 0) != ff: merged += 1
        if 'Hundo' in tg and iv != 45: viol['Hundo'].append(nm)
        if 'Nundo' in tg and not (r['iv_atk'] == 0 and r['iv_def'] == 0 and r['iv_sta'] == 0): viol['Nundo'].append(nm)
        if 'XXL' in tg and (r['pokemon_size_category'] or 0) != 5: viol['XXL'].append(nm)
        if 'Event' in tg and not (r['fresh_costume'] or r['special_bg_id'] or r['natural_art_background'] or r['fresh_has_location_card'] or is_costume_form(ff)): viol['Event'].append(nm)
        if 'Best Buddy' in tg and r['was_best_buddy_badge'] != 1: viol['Best Buddy'].append(nm)
        if 'Legacy Moves' in tg and u not in legacy: viol['Legacy Moves'].append(nm)
        for lab, sc, rc, cap in [('GL IV', 'gl_stage', 'gl_rank', GL_CAP), ('UL IV', 'ul_stage', 'ul_rank', UL_CAP)]:
            if lab in tg:
                stg = r[sc]; rk = r[rc]
                if not stg or maxcp(stg, BS) <= cap + VIABILITY_MARGIN: viol[lab].append(nm + 'UC')
                elif rk is None or rk > 5: viol[lab].append(f"{nm}rk{rk}")
                elif iv == 45: viol[lab].append(nm + 'H')
                elif pvid(nm, r['form'] or 0) == stg and (r['cp'] or 0) > cap: viol[lab].append(nm + 'OC')
        for ev, want in (('Evolve 1', 1), ('Evolve 2', 2)):
            if ev in tg:
                if not reach(r): viol[ev].append(nm)
                elif iv in (0, 45): viol[ev].append(f"{nm}iv{iv}")
                elif r['pokemon_id'] in RARE: viol[ev].append(nm + 'R')
                elif r['pokemon_id'] not in GT and dist.get(pvid(nm, r['form'] or 0), 0) != want: viol[ev].append(nm)
        if 'Transfer' in tg:
            bad = [x for x, cond in [('SH', r['fresh_shiny']), ('H', iv == 45), ('N', r['iv_atk'] == 0 and r['iv_def'] == 0 and r['iv_sta'] == 0), ('BB', r['was_best_buddy_badge'] == 1), ('CO', is_costume_form(ff)), ('OR', EF(r))] if cond]
            if bad: viol['Transfer-SAFETY'].append(f"{nm}:{'+'.join(bad)}")
            if tg & KEEP: viol['Transfer-DISJOINT'].append(nm)

    def comp(lab, tag, pred):
        q = [r for r in rows if pred(r)]; miss = [r for r in q if tag not in T(r)]
        return f"{lab} {count[tag]}/{len(q)}" + (" MISS!" + ",".join(m['species_name'] for m in miss[:4]) if miss else " ok")
    print("completeness:", comp('Hundo', 'Hundo', lambda r: (r['iv_total'] or 0) == 45), "|",
          comp('Nundo', 'Nundo', lambda r: r['iv_atk'] == 0 and r['iv_def'] == 0 and r['iv_sta'] == 0 and r['pokemon_id']), "|",
          comp('BB', 'Best Buddy', lambda r: r['was_best_buddy_badge'] == 1), "|",
          comp('Traded', 'Traded by E+F', EF))
    print(f"nonzero-merged {merged} | misfold {misfold} | forms-missing-from-enum {len(enum_missing)}")
    print(f"accounting: in_bag={len(allu)} kept={len(keptu)} xfer={len(xferu)} sum={len(keptu)+len(xferu)} overlap={len(keptu&xferu)}")
    anyv = False
    for t in ['Hundo', 'Nundo', 'XXL', 'Event', 'Best Buddy', 'Legacy Moves', 'GL IV', 'UL IV', 'Evolve 1', 'Evolve 2', 'Transfer-SAFETY', 'Transfer-DISJOINT']:
        if viol.get(t):
            anyv = True; print(f"  VIOL {t}: {len(viol[t])} " + "; ".join(viol[t][:8]))
    ok = not (anyv or merged or misfold or enum_missing or fn or fp or fullmiss or len(keptu & xferu))
    print("*** " + ("ISSUES ABOVE" if not ok else "ALL CLEAN (deep)") + " ***")


if __name__ == '__main__':
    main()
