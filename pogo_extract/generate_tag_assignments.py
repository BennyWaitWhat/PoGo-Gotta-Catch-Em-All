"""Generate the tag-assignment plan for the user's pokemon.

Output: desired_tags.csv with one row per pokemon listing every tag that should
be applied. Format makes it easy to feed into whatever apply mechanism we end up
using (iPogo runtime API, Frida script via pokemod-injector, or even iPogo UI
batch-input).

New tags created (added to user's existing 15):
  TX        - transferable per cull plan (858 pokemon)
  TOP3      - top 3 per (species, form) bucket (3,245)
  JUMBO     - size category XL or XXL (130)
  TINY      - size category XXS (30)
  LEGACY    - has legacy/event-exclusive move (784 pokemon-move matches)
  POSTCARD  - has assigned postcard / location background (92)
  BUDDY     - is or was best buddy (332)
  POWERED   - has stardust invested past catch level (609)
  ADVENTURE - has adventure-effect uses remaining (21)

The user's pre-existing tags (TeamEevee, Hundos, Nundos, etc.) remain - we don't
duplicate. Where our new tag overlaps existing one (Hundos already exists, Nundos
already exists, Trade/Traded already exist, Mega already exists), we use the
existing tag name not a new one.
"""
import sqlite3, csv
from references import (
    LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    ADVENTURE_EFFECT_IDS, has_legacy_move,
)

DB = 'pokemon.db'

# Mapping new tag -> rule
# Existing user tags reused: Hundos, Nundos, Trade (or Traded), Mega, MegaHundos, Shinyyy
NEW_TAGS = {
    'TX': 'transferable per cull plan',
    'TOP3': 'top 3 by IV in (species, form) bucket',
    'JUMBO': 'size XL or XXL',
    'TINY': 'size XXS',
    'LEGACY': 'has legacy/event-exclusive move',
    'POSTCARD': 'has assigned postcard or location background',
    'BUDDY': 'is or was best buddy',
    'POWERED': 'stardust invested past catch level',
    'ADVENTURE': 'adventure-effect uses remaining',
    'LEGENDARY': 'legendary species',
    'MYTHICAL': 'mythical species',
    'UB': 'ultra-beast species',
    'PARADOX': 'paradox species',
}

def tags_for(p):
    tags = []
    pid = p['pokemon_id']

    # Reuse existing user tags where applicable
    if p['is_hundo']: tags.append('Hundos')
    if p['is_zero']:  tags.append('Nundos')

    # Trade-related: user has both 'Trade' and 'Traded' as separate tags
    # Keep them simple: any traded pokemon gets 'Traded' (their existing tag)
    if (p['is_traded_flag_v2'] or 0) == 1 or (p['is_traded'] or 0) == 1:
        tags.append('Traded')

    # New tags
    if p['cull_decision'] == 'TRANSFER':
        tags.append('TX')

    sc = p['pokemon_size_category'] or 0
    if sc == 1:
        tags.append('TINY')
    elif sc == 5:
        tags.append('JUMBO')

    if (p['is_mega_evolved'] or 0) == 1:
        tags.append('Mega')  # use existing user tag

    if (p['adventure_effects_left'] or 0) > 0:
        tags.append('ADVENTURE')

    # POSTCARD = the server 'Background' tag. Use the same column the pipeline
    # populates (fresh_has_location_card) — the *_bg_id columns gave only ~10%
    # overlap with the live Background server-tag set (audit 2026-05-27).
    if (p['fresh_has_location_card'] or 0) == 1:
        tags.append('POSTCARD')

    if p['is_best_buddy']:
        tags.append('BUDDY')

    if (p['is_powered_up'] or 0) == 1:
        tags.append('POWERED')

    if has_legacy_move(pid, [p['move1'], p['move2'], p['move3']]):
        tags.append('LEGACY')

    if pid in LEGENDARY_IDS:    tags.append('LEGENDARY')
    if pid in MYTHICAL_IDS:     tags.append('MYTHICAL')
    if pid in ULTRA_BEAST_IDS:  tags.append('UB')
    if pid in PARADOX_IDS:      tags.append('PARADOX')

    # Top 3 per (species, form) - need bucket context, set by caller
    # We'll add it after sorting

    # Hundo + Mega → MegaHundos
    if 'Hundos' in tags and 'Mega' in tags:
        tags.append('MegaHundos')

    return tags

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    rows = [dict(r) for r in c.execute("SELECT * FROM pokemon").fetchall()]
    print(f"Loaded {len(rows)} pokemon")

    # First pass: assign all non-bucket-rank tags
    tag_map = {}  # uid_hex -> set of tag names
    for p in rows:
        ts = tags_for(p)
        tag_map[p['uid_hex']] = set(ts)

    # Second pass: add TOP3 tag based on (species, form) ranking
    by_bucket = {}
    for p in rows:
        key = (p['pokemon_id'], p['form'] or 0)
        by_bucket.setdefault(key, []).append(p)
    top3_count = 0
    for key, lst in by_bucket.items():
        lst.sort(key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))
        for i, p in enumerate(lst[:3]):
            tag_map[p['uid_hex']].add('TOP3')
            top3_count += 1
    print(f"  TOP3 marked: {top3_count}")

    # Stats
    print("\n=== Tag distribution ===")
    tag_counts = {}
    for ts in tag_map.values():
        for t in ts:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    for t, n in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:15s} {n}")

    # Write desired_tags.csv
    print("\nWriting desired_tags.csv...")
    with open('desired_tags.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['uid_hex','uid_signed','pokemon_id','species_name','form','cp','iv_pct','tags_pipe_separated'])
        for p in rows:
            ts = sorted(tag_map[p['uid_hex']])
            w.writerow([p['uid_hex'], p['uid'], p['pokemon_id'], p['species_name'],
                        p['form'], p['cp'], p['iv_pct'], '|'.join(ts)])
    print("  desired_tags.csv written")

    # Also write a markdown summary of new tags
    print("\nWriting tag_scheme.md...")
    with open('tag_scheme.md', 'w', encoding='utf-8') as f:
        f.write("# Tag scheme\n\n")
        f.write("## New tags created\n\n")
        for t, desc in NEW_TAGS.items():
            n = tag_counts.get(t, 0)
            f.write(f"- **{t}** ({n}) - {desc}\n")
        f.write("\n## Existing user tags reused\n\n")
        f.write("- **Hundos** - 100% IV\n")
        f.write("- **Nundos** - 0% IV\n")
        f.write("- **Traded** - obtained via trade\n")
        f.write("- **Mega** - currently mega evolved\n")
        f.write("- **MegaHundos** - hundo + mega evolved\n")
        f.write("\n## Tag application order\n\n")
        f.write("Per pokemon, all matching tags are assigned. Up to 14 tags per pokemon "
                "(Niantic's max). The desired_tags.csv has the full assignment.\n")
    print("  tag_scheme.md written")

    conn.close()

if __name__ == '__main__':
    main()
