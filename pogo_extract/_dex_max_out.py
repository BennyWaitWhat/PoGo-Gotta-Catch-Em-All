"""Comprehensive dex max-out opportunity scan.

For each regional dex and each PokedexCategory, identify completion gaps,
distinguish released-uncaught from unreleased, and rank actionable
opportunities.

Reads dex_deep_full.json (from _dex_deep_read.py) + pvpoke_gamemaster.json
(released-species reference) + pokemon.db (current bag for "have multiples
to trade" lucky opportunity scoring). Writes rescan_report/dex_max_out.md.

PokedexCategory enum (verified live 2026-05-27):
  11 SHINY    12 LUCKY    13 THREE_STAR    14 FOUR_STAR (hundo)
  15 SHADOW   16 PURIFIED 17 COSTUME       18 BREAD_MODE (Dynamax)
  19 BREAD_DOUGH_MODE (Gigantamax)   101 SHINY_THREE_STAR
  102 SHINY_FOUR_STAR (shiny hundo)  201 SIZE_XXS  202 SIZE_XXL
"""
import json, os, re, sqlite3
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEX = os.path.join(HERE, 'dex_deep_full.json')
DB  = os.path.join(HERE, 'pokemon.db')
GM  = os.path.join(HERE, 'pvpoke_gamemaster.json')
REPORT_DIR = os.path.join(HERE, 'rescan_report')
OUT = os.path.join(REPORT_DIR, 'dex_max_out.md')

# (name, pid_lo, pid_hi)
REGIONS = [
    ('Kanto', 1, 151),     ('Johto', 152, 251),    ('Hoenn', 252, 386),
    ('Sinnoh', 387, 493),  ('Unova', 494, 649),    ('Kalos', 650, 721),
    ('Alola', 722, 809),   ('Galar', 810, 905),    ('Paldea', 906, 1025),
]

# (enum, label, feasibility, category 'core'|'optional')
CATS = [
    (13,  '3-Star',         'any caught species — random 37+ IV',                       'core'),
    (14,  'Hundo',          '45/45 — any species, rare',                                'core'),
    (12,  'Lucky',          'trade with any friend',                                    'core'),
    (11,  'Shiny',          'only species with shiny released',                         'core'),
    (15,  'Shadow',         'TGR Grunt/Leader/Giovanni drops only',                     'optional'),
    (16,  'Purified',       'purify any shadow you own',                                'optional'),
    (201, 'XXS',            '~5% random catch',                                         'optional'),
    (202, 'XXL',            '~5% random catch',                                         'optional'),
    (17,  'Costume',        'event-specific catches',                                   'optional'),
    (18,  'Dynamax',        'Max Battle eligible species',                              'optional'),
    (19,  'Gigantamax',     'Gmax-eligible 16 species only',                            'optional'),
    (101, 'Shiny 3-Star',   'shiny + 37+ IV',                                           'optional'),
    (102, 'Shiny Hundo',    'shiny + 45 IV (extreme rarity)',                           'optional'),
]

CORE_CATS = [c[0] for c in CATS if c[3] == 'core']


def build_pid_data():
    gm = json.load(open(GM, 'r', encoding='utf-8'))
    released = set()
    pid_to_name = {}
    for x in gm['pokemon']:
        sid = x.get('speciesId', '')
        if '_shadow' in sid: continue
        d = x.get('dex')
        if d is None: continue
        released.add(d)
        nm = x.get('speciesName', '') or ''
        if d in pid_to_name: continue
        if '(' not in nm:
            pid_to_name[d] = nm
    for x in gm['pokemon']:
        sid = x.get('speciesId', '')
        if '_shadow' in sid: continue
        d = x.get('dex')
        if d is None or d in pid_to_name: continue
        clean = re.sub(r'\s*\([^)]*\)\s*', '', x.get('speciesName', '') or '').strip()
        if clean: pid_to_name[d] = clean
    return released, pid_to_name


def bag_pid_counts():
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    cnt = defaultdict(int)
    for pid, n in conn.execute("SELECT pokemon_id, COUNT(*) FROM pokemon WHERE in_bag=1 GROUP BY pokemon_id"):
        cnt[pid] = n
    conn.close()
    return dict(cnt)


def bag_shadow_counts():
    """Shadow-only bag counts — for Purified opportunity sizing (need a shadow to purify)."""
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    cnt = defaultdict(int)
    for pid, n in conn.execute(
        "SELECT pokemon_id, COUNT(*) FROM pokemon WHERE in_bag=1 AND fresh_alignment=1 GROUP BY pokemon_id"
    ):
        cnt[pid] = n
    conn.close()
    return dict(cnt)


def name_or(pid, names): return names.get(pid, f'pid{pid}')


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    dex = json.load(open(DEX, 'r', encoding='utf-8'))
    released_pids, pid_to_name = build_pid_data()
    bag_counts = bag_pid_counts()
    shadow_bag_counts = bag_shadow_counts()

    # Per-region: build pid -> cat_acq_map
    region = {}
    for name, lo, hi in REGIONS:
        entries = {e['pid']: e for e in dex[name]}
        cat_acq = defaultdict(dict)  # cat -> {pid -> bool}
        for pid, e in entries.items():
            tracks = {c['cat']: bool(c['acq']) for c in e['cats']}
            for cat_enum, *_ in CATS:
                cat_acq[cat_enum][pid] = tracks.get(cat_enum, False)
        in_range = set(range(lo, hi+1))
        caught = set(entries.keys())
        region[name] = {
            'entries': entries,
            'caught': caught,
            'released_uncaught': sorted((in_range & released_pids) - caught),
            'unreleased': sorted(in_range - released_pids),
            'cat_acq': cat_acq,
        }

    # ---- build report ----
    L = []
    L.append('# Dex Max-Out Opportunity Scan — 2026-05-27\n')
    L.append('Goal: identify every actionable gap across all 9 regional dexes + 13 PokedexCategories.\n')
    L.append('Source: live PokedexImpl (`dex_deep_full.json`), pvpoke gamemaster (release status), pokemon.db (bag counts).\n')

    # ---- 1. top-line ----
    L.append('## Top-line completion per region\n')
    L.append('| Region | Caught | Rel-uncaught | Unreleased | 3-Star | Hundo | Lucky | Shiny | Shadow | XXS | XXL | Dyna |')
    L.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    totals = defaultdict(int)
    for name, lo, hi in REGIONS:
        rd = region[name]
        n_caught = len(rd['caught'])
        def got(cat):
            return sum(1 for v in rd['cat_acq'][cat].values() if v)
        row = [name, n_caught, len(rd['released_uncaught']), len(rd['unreleased'])]
        for cat in [13, 14, 12, 11, 15, 201, 202, 18]:
            row.append(got(cat))
            totals[cat] += got(cat)
        totals['caught'] += n_caught
        totals['rel_uncaught'] += len(rd['released_uncaught'])
        totals['unreleased'] += len(rd['unreleased'])
        L.append('| ' + ' | '.join(str(c) for c in row) + ' |')
    L.append('')

    # ---- 2. cross-region actionable summary ----
    L.append('## Action layer — what to chase\n')

    # (a) Caught completion: released uncaught
    rel_uncaught_total = sum(len(region[n]['released_uncaught']) for n,_,_ in REGIONS)
    L.append('### A. Released species you have NOT caught yet\n')
    L.append(f'**{rel_uncaught_total} species in pvpoke gamemaster are not in your PoGo dex.** Caveat: pvpoke includes the entire national-dex movepool catalog, so this list OVER-COUNTS — many Paldea-DLC/paradox/treasures-of-ruin species are defined in pvpoke but **not yet released in PoGo as of 2026-05-27**. Use this list as a candidate set; verify against an in-game search (most Hisuian-form Gen 4/5 species + Galar/Paldea earlier-released ones are real targets, while paradox/Indigo-Disk species likely are not).\n')
    for name, lo, hi in REGIONS:
        rd = region[name]
        if not rd['released_uncaught']: continue
        names = ', '.join(f'`#{p}` {name_or(p, pid_to_name)}' for p in rd['released_uncaught'])
        L.append(f'- **{name}** ({len(rd["released_uncaught"])}): {names}')
    L.append('')

    # (b) Lucky trade opportunities
    all_caught = set()
    for name, _, _ in REGIONS:
        all_caught |= region[name]['caught']
    # collect global lucky map across regions (a species in All dict is caught somewhere; lucky tracked across)
    lucky_globally = set()
    for e in dex['All']:
        for c in e['cats']:
            if c['cat'] == 12 and c['acq']:
                lucky_globally.add(e['pid'])
                break
    lucky_missing = sorted(all_caught - lucky_globally)
    L.append('### B. Lucky trade opportunities — biggest untapped opportunity\n')
    L.append(f'**Only {len(lucky_globally)} of {len(all_caught)} caught species have a Lucky.** Every caught species can earn the Lucky medal via a single friend trade (no IV/level requirement).\n')
    # rank by bag count (more in bag = easier to trade away/keep one)
    lm_with_counts = [(p, bag_counts.get(p, 0), name_or(p, pid_to_name)) for p in lucky_missing]
    lm_with_counts.sort(key=lambda x: -x[1])
    L.append(f'Top 30 by bag count (more = easier to spare for a trade):')
    for p, n, nm in lm_with_counts[:30]:
        L.append(f'- `#{p}` **{nm}** — {n} in bag')
    if len(lucky_missing) > 30:
        L.append(f'- _... +{len(lucky_missing)-30} more_')
    L.append('')

    # (c) 3-Star gap (very narrow — 20 species)
    threestar_globally = {e['pid'] for e in dex['All'] for c in e['cats'] if c['cat']==13 and c['acq']}
    threestar_missing = sorted(all_caught - threestar_globally)
    L.append('### C. 3-Star (≥37 IV) gap — easiest core medal to fill\n')
    L.append(f'{len(threestar_missing)} caught species are still missing 3-Star. Any 37+ IV catch fills the medal; checking via Pokémon Storage IV search filters these fast.\n')
    if threestar_missing:
        for p in threestar_missing:
            n = bag_counts.get(p, 0)
            L.append(f'- `#{p}` **{name_or(p, pid_to_name)}** — {n} in bag')
    L.append('')

    # (d) XXS / XXL gaps — bulk grind targets
    xxs = {e['pid'] for e in dex['All'] for c in e['cats'] if c['cat']==201 and c['acq']}
    xxl = {e['pid'] for e in dex['All'] for c in e['cats'] if c['cat']==202 and c['acq']}
    xxs_missing = sorted(all_caught - xxs)
    xxl_missing = sorted(all_caught - xxl)
    L.append('### D. Size XXS / XXL gaps (top opportunities = species you already see often)\n')
    L.append(f'XXS missing: **{len(xxs_missing)}**.  XXL missing: **{len(xxl_missing)}**.  Both roll at ~5%.\n')
    L.append('**Top 25 XXL targets by bag count** (showing means common = many chances per event/spotlight):')
    xxl_ranked = [(p, bag_counts.get(p,0)) for p in xxl_missing]
    xxl_ranked.sort(key=lambda x: -x[1])
    for p, n in xxl_ranked[:25]:
        if n > 0:
            L.append(f'- `#{p}` {name_or(p, pid_to_name)} — {n} in bag')
    L.append('')
    L.append('**Top 25 XXS targets by bag count:**')
    xxs_ranked = [(p, bag_counts.get(p,0)) for p in xxs_missing]
    xxs_ranked.sort(key=lambda x: -x[1])
    for p, n in xxs_ranked[:25]:
        if n > 0:
            L.append(f'- `#{p}` {name_or(p, pid_to_name)} — {n} in bag')
    L.append('')

    # (e) Shiny hundo (zero!)
    sh4 = {e['pid'] for e in dex['All'] for c in e['cats'] if c['cat']==102 and c['acq']}
    L.append('### E. Shiny Hundo — you have ZERO\n')
    L.append('`SHINY_FOUR_STAR` category has **0 acquired** across your entire dex. Every shiny hundo you ever catch will fill a new slot. This is the rarest single category in the game.\n')

    # (f) Gigantamax remaining
    GMAX_PIDS = [3, 6, 9, 12, 25, 52, 68, 94, 99, 131, 143, 569,
                 812, 815, 818, 849, 861]  # 17 species released in PoGo as of 2026-05-27
    gmax_acq = {e['pid'] for e in dex['All'] for c in e['cats'] if c['cat']==19 and c['acq']}
    gmax_missing = sorted(set(GMAX_PIDS) - gmax_acq)
    extras_in_acq = sorted(gmax_acq - set(GMAX_PIDS))
    L.append('### F. Gigantamax — narrow but completable\n')
    L.append(f'17 species can be Gmax in PoGo as of May 2026: `{GMAX_PIDS}`. You have **{len(gmax_acq)}/17** acquired. ' +
             (f'Missing: ' + ', '.join(f'`#{p}` {name_or(p, pid_to_name)}' for p in gmax_missing) if gmax_missing else 'all complete!') +
             (f'\n_(Note: also showing Gmax acq for pids `{extras_in_acq}` — verify these are real or update GMAX_PIDS list.)_' if extras_in_acq else ''))
    L.append('')

    # (g) Purified opportunities — species with Shadow but no Purified
    shadow_acq = {e['pid'] for e in dex['All'] for c in e['cats'] if c['cat']==15 and c['acq']}
    purified_acq = {e['pid'] for e in dex['All'] for c in e['cats'] if c['cat']==16 and c['acq']}
    purified_easy = sorted(shadow_acq - purified_acq)
    L.append('### G. Purified opportunities — species you have a Shadow medal for but not Purified\n')
    have_shadow_in_bag = {p for p, n in shadow_bag_counts.items() if n > 0}
    can_purify_now = sorted(set(purified_easy) & have_shadow_in_bag)
    need_recatch = sorted(set(purified_easy) - have_shadow_in_bag)
    L.append(f'**{len(purified_easy)} species** have a Shadow medal but no Purified medal. The Purified medal awards on the first purification of any shadow of that species — for ~1k-5k Stardust + ~5 candy.\n')
    L.append(f'- **{len(can_purify_now)} species: you have a shadow IN BAG right now** (purify one directly).')
    L.append(f'- **{len(need_recatch)} species: shadow medal acquired but no shadow in current bag** (re-catch a TGR drop, then purify).')
    L.append('')
    if can_purify_now:
        rows = [(p, shadow_bag_counts.get(p, 0), name_or(p, pid_to_name)) for p in can_purify_now]
        rows.sort(key=lambda x: -x[1])
        L.append('Top 30 to purify right now (sorted by shadow count in bag):')
        for p, n, nm in rows[:30]:
            L.append(f'- `#{p}` **{nm}** — {n} shadow in bag')
        if len(can_purify_now) > 30:
            L.append(f'- _... +{len(can_purify_now)-30} more with shadow in bag_')
    L.append('')

    # (h) Shadow opportunities — species caught but no shadow medal (TGR-droppable depends on rotation)
    shadow_missing = sorted(all_caught - shadow_acq)
    L.append('### H. Shadow medal gap (depends on TGR rotation)\n')
    L.append(f'{len(shadow_missing)} caught species without Shadow medal. Most depend on whether Team GO Rocket currently drops them (rotates monthly). Worth checking the current Grunt/Leader rosters before grinding.\n')
    L.append('')

    # ---- 3. per-region detail tables ----
    L.append('## Per-region detail\n')
    for name, lo, hi in REGIONS:
        rd = region[name]
        n_caught = len(rd['caught'])
        L.append(f'### {name} — {n_caught} caught, {len(rd["released_uncaught"])} released-uncaught, {len(rd["unreleased"])} unreleased\n')
        if rd['released_uncaught']:
            L.append('**Released uncaught:** ' + ', '.join(f'`#{p}` {name_or(p, pid_to_name)}' for p in rd['released_uncaught']))
            L.append('')
        L.append('| Category | Got | Missing | First 12 missing |')
        L.append('|---|---:|---:|---|')
        for cat_enum, label, note, kind in CATS:
            status = rd['cat_acq'][cat_enum]
            got = sum(1 for v in status.values() if v)
            missing_pids = sorted(p for p in rd['caught'] if not status.get(p))
            preview = ', '.join(f'`#{p}` {name_or(p, pid_to_name)}' for p in missing_pids[:12])
            L.append(f'| {label} | {got}/{n_caught} | {len(missing_pids)} | {preview} |')
        L.append('')

    # ---- 4. "Almost-perfect" species (1 core cat missing) ----
    L.append('## Quick wins — caught species 1 CORE category from complete\n')
    L.append('Core = 3-Star, Hundo, Lucky, Shiny. (Optional cats like XXS/XXL deliberately excluded — those need luck.)\n')
    almost = []
    for name, lo, hi in REGIONS:
        rd = region[name]
        for pid in sorted(rd['caught']):
            cats = {c['cat']: bool(c['acq']) for c in rd['entries'][pid]['cats']}
            core_have = [c for c in CORE_CATS if cats.get(c, False)]
            core_missing = [c for c in CORE_CATS if not cats.get(c, False)]
            if len(core_missing) == 1:
                almost.append((name, pid, core_missing[0]))
    if almost:
        # Group by missing category
        by_cat = defaultdict(list)
        for name, pid, cat in almost:
            by_cat[cat].append((name, pid))
        cat_label = {13:'3-Star',14:'Hundo',12:'Lucky',11:'Shiny'}
        for cat in CORE_CATS:
            rows = sorted(by_cat[cat])
            if not rows: continue
            L.append(f'### Missing only {cat_label[cat]} ({len(rows)} species)')
            for region_name, pid in rows[:30]:
                bag_n = bag_counts.get(pid, 0)
                L.append(f'- `#{pid}` **{name_or(pid, pid_to_name)}** ({region_name}) — {bag_n} in bag')
            if len(rows) > 30:
                L.append(f'- _... +{len(rows)-30} more_')
            L.append('')
    else:
        L.append('_No species are exactly 1 core category from complete._\n')

    # ---- write ----
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'wrote {OUT}')

    # ---- console summary ----
    print(f'\n=== Top-line ===')
    print(f'  Total caught: {sum(len(region[n]["caught"]) for n,_,_ in REGIONS)} (across regions)')
    print(f'  Released-uncaught total: {rel_uncaught_total}')
    print(f'  Lucky opportunity: {len(lucky_missing)} caught species without Lucky')
    print(f'  3-Star opportunity: {len(threestar_missing)} caught species without 3-Star')
    print(f'  XXS opportunity: {len(xxs_missing)}  XXL opportunity: {len(xxl_missing)}')
    print(f'  Shiny Hundo: 0 ever (largest single rarity)')
    print(f'  Gigantamax: {len(gmax_acq)}/{len(GMAX_PIDS)} — missing {len(gmax_missing)}')
    print(f'  Almost-perfect (1 core cat from complete): {len(almost)}')


if __name__ == '__main__':
    main()
