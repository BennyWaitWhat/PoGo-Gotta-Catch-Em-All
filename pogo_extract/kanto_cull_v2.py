"""Kanto cull v2: clean rules.

FULL PROTECTIONS (always keep):
  - Hundo (iv_pct >= 100)
  - Gmax (fresh_bread_mode=2)
  - Dmax (fresh_bread_mode=1)
  - Shiny (fresh_shiny=1)
  - Lucky (is_lucky=1)
  - Traded (is_traded_flag_v2=1)
  - Legendary (Articuno/Zapdos/Moltres/Mewtwo/Mew)

BUCKET DIMENSIONS:
  - Costume = own bucket per (species, form, costume)

BUCKET RULE: top 3 by IV per (species, form, costume) bucket.
Applied to all non-protected pokemon (powered-up included).
"""
import sqlite3, json

LEGENDARY_KANTO = {144, 145, 146, 150, 151}

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
rows = c.execute('''SELECT uid_hex, uid, pokemon_id, species_name, form,
                           fresh_shiny, fresh_bread_mode, fresh_has_location_card,
                           fresh_costume, cp, iv_pct, level,
                           is_lucky, is_traded_flag_v2, is_powered_up
                    FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN 1 AND 151''').fetchall()
print(f'Total Kanto: {len(rows)}')

protected = []
xfer = []
buckets = {}

for r in rows:
    uid, _u, pid, sp, form, shiny, bread, loc, cost, cp, iv, lvl, lucky, traded, powered = r
    # FULL PROTECTIONS
    if pid in LEGENDARY_KANTO:
        protected.append((r, 'legendary')); continue
    if (iv or 0) >= 100:
        protected.append((r, 'hundo')); continue
    if (iv or 0) == 0:
        protected.append((r, 'nundo')); continue
    if bread:
        protected.append((r, 'gmax' if bread==2 else 'dmax')); continue
    if shiny:
        protected.append((r, 'shiny')); continue
    if lucky:
        protected.append((r, 'lucky')); continue
    if traded:
        protected.append((r, 'traded')); continue
    # Bucket
    key = (pid, form or 0, cost or 0)
    buckets.setdefault(key, []).append(r)

for key, lst in buckets.items():
    lst.sort(key=lambda x: (-(x[10] or 0), -(x[9] or 0)))
    for i, r in enumerate(lst):
        if i < 3:
            protected.append((r, f'bucket_rank{i+1}'))
        else:
            xfer.append(r)

full_set = {"legendary","hundo","nundo","gmax","dmax","shiny","lucky","traded"}
print(f'  Full-protected: {sum(1 for _,reason in protected if reason in full_set)}')
print(f'  Bucket-rank-3-keepers: {sum(1 for _,reason in protected if reason.startswith("bucket_"))}')
print(f'  Distinct buckets: {len(buckets)}')
print(f'  TRANSFER: {len(xfer)}')

# Group transfers
print()
print('=== Transfers grouped by species ===')
xfer_by_sp = {}
for r in xfer:
    xfer_by_sp.setdefault(r[3], []).append(r)
for sp, lst in sorted(xfer_by_sp.items(), key=lambda x: -len(x[1])):
    print(f'\n  {sp}: {len(lst)} to transfer')
    for r in sorted(lst, key=lambda x: (x[4], -(x[10] or 0))):
        flags = []
        if r[8]: flags.append(f'Cost{r[8]}')
        if r[14]: flags.append('Powered')
        if r[7]: flags.append('LocCard')
        fl = ' '.join(flags) if flags else ''
        print(f'    f={r[4]:>5} CP{r[9]:5d} IV{r[10]:5.1f}% L{r[11]:.1f}  {fl}')

# Save
out = []
for r in xfer:
    out.append({'uid_hex': r[0], 'uid': r[1], 'species': r[3], 'form': r[4],
                'cp': r[9], 'iv': r[10]})
with open('kanto_xfer_v2.json','w') as f:
    json.dump(out, f, indent=2)
print(f'\nWrote kanto_xfer_v2.json ({len(out)} entries)')
