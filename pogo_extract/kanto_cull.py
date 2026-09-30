"""Kanto cull: top 3 per (species, form, shiny, bread_mode, location_card, costume) bucket.

Each unique combination of these dimensions is its own bucket.
Bucketing ensures shinies/Gmax/Dmax/backgrounds/costumes don't compete with normal ones.

Persistent protections from earlier user decisions:
  - Shiny chain protection: ALL shinies of Magikarp/Gyarados, Eevee+evos,
    Pichu/Pikachu/Raichu, Flabebe+evos kept regardless of bucket rank
  - Legendaries (Articuno/Zapdos/Moltres/Mewtwo/Mew) kept

Otherwise: rank by IV% desc, CP desc; rank 4+ = TRANSFER.
"""
import sqlite3, json

PROTECTED_SHINY_PIDS = {
    129, 130,                                     # Magikarp/Gyarados
    133, 134, 135, 136, 196, 197, 470, 471, 700,  # Eevee chain
    172, 25, 26,                                  # Pikachu chain
    669, 670, 671,                                # Flabebe chain
}
LEGENDARY_KANTO = {144, 145, 146, 150, 151}  # Articuno/Zapdos/Moltres/Mewtwo/Mew

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

rows = c.execute('''SELECT uid_hex, uid, pokemon_id, species_name, form,
                           fresh_shiny, fresh_bread_mode, fresh_has_location_card,
                           fresh_costume, cp, iv_pct, level,
                           is_lucky, is_traded_flag_v2, is_powered_up
                    FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN 1 AND 151''').fetchall()
print(f'Total Kanto pokemon: {len(rows)}')

buckets = {}
xfer = []
auto_keep = []

for r in rows:
    uid, _uid, pid, sp, form, shiny, bread, loc, costume, cp, iv, lvl, lucky, traded, powered = r

    # Persistent protections
    if pid in LEGENDARY_KANTO:
        auto_keep.append((r, 'legendary'))
        continue
    if shiny and pid in PROTECTED_SHINY_PIDS:
        auto_keep.append((r, 'protected_shiny_chain'))
        continue

    # Bucket on all 6 dimensions
    key = (pid, form or 0, shiny or 0, bread or 0, loc or 0, costume or 0)
    buckets.setdefault(key, []).append(r)

# Rank within bucket
keep_in_bucket = []
for key, lst in buckets.items():
    lst.sort(key=lambda x: (-(x[10] or 0), -(x[9] or 0)))
    for i, r in enumerate(lst):
        if i < 3:
            keep_in_bucket.append((r, f'bucket_rank{i+1}'))
        else:
            xfer.append(r)

print(f'  Auto-protected (legendary/protected-shiny): {len(auto_keep)}')
print(f'  Distinct buckets: {len(buckets)}')
print(f'  Bucket-rank-3-keepers: {len(keep_in_bucket)}')
print(f'  TRANSFER: {len(xfer)}')

# Show all transfers grouped by bucket
print()
print('=== Transfers by species/bucket ===')
xfer_by_species = {}
for r in xfer:
    xfer_by_species.setdefault(r[3], []).append(r)
for sp, lst in sorted(xfer_by_species.items(), key=lambda x: -len(x[1])):
    print(f'\n  {sp}: {len(lst)} to transfer')
    for r in sorted(lst, key=lambda x: (x[4], -(x[10] or 0))):
        flags = []
        if r[5]: flags.append('S')
        if r[6]==1: flags.append('Dmax')
        if r[6]==2: flags.append('Gmax')
        if r[7]: flags.append('LocCard')
        if r[8]: flags.append(f'Cost{r[8]}')
        if r[12]: flags.append('L')
        if r[13]: flags.append('T')
        if r[14]: flags.append('+')
        fl = ' '.join(flags)
        print(f'    f={r[4]:>4} CP{r[9]:5d} IV{r[10]:5.1f}% L{r[11]:.1f}  {fl}')

# Save
out = []
for r in xfer:
    out.append({'uid_hex': r[0], 'uid': r[1], 'species': r[3], 'form': r[4],
                'cp': r[9], 'iv': r[10]})
with open('kanto_xfer_list.json','w') as f:
    json.dump(out, f, indent=2)
print(f'\nWrote kanto_xfer_list.json ({len(out)} entries)')
