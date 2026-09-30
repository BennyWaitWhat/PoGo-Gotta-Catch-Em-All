"""Shiny cull: top 8 per (species, form) bucket, except fully-protected chains.

Protected chains (keep ALL shinies):
  - Magikarp/Gyarados (129, 130)
  - Eevee + all evolutions (133, 134, 135, 136, 196, 197, 470, 471, 700)
  - Pichu/Pikachu/Raichu (172, 25, 26)
  - Flabebe/Floette/Florges (669, 670, 671)
"""
import sqlite3, json

PROTECTED_PIDS = {
    # Magikarp/Gyarados
    129, 130,
    # Eevee chain
    133, 134, 135, 136, 196, 197, 470, 471, 700,
    # Pikachu chain
    172, 25, 26,
    # Flabebe chain
    669, 670, 671,
    # Rayquaza
    384,
    # Zacian
    888,
}
TOP_N = 6

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

rows = c.execute('''SELECT uid_hex, uid, pokemon_id, species_name, form, fresh_costume,
                           cp, iv_pct, level, is_lucky, is_powered_up, is_traded_flag_v2
                    FROM pokemon WHERE in_bag=1 AND fresh_shiny=1''').fetchall()
print(f'Total shinies: {len(rows)}')

# Bucket by (species, form) - costume IGNORED for shiny rule
buckets = {}
for r in rows:
    pid = r[2]
    if pid in PROTECTED_PIDS:
        continue  # all kept regardless
    key = (pid, r[4] or 0)
    buckets.setdefault(key, []).append(r)

# Within each bucket rank by IV%, CP. Below rank 8 = transferable
xfer = []
for key, lst in buckets.items():
    lst.sort(key=lambda x: (-(x[7] or 0), -(x[6] or 0)))
    for i, r in enumerate(lst):
        if i >= TOP_N:
            xfer.append(r)

protected = sum(1 for r in rows if r[2] in PROTECTED_PIDS)
print(f'  Protected chains (keep all): {protected}')
print(f'  Other shinies (top {TOP_N}/bucket): {len(rows) - protected}')
print(f'  Below-rank-{TOP_N} in non-protected = TRANSFER candidates: {len(xfer)}')

if xfer:
    print()
    print('=== Transfer candidates ===')
    for r in xfer:
        flags = []
        if r[9]: flags.append('LUCKY')
        if r[10]: flags.append('POWERED')
        if r[11]: flags.append('TRADED')
        print(f'  {r[3]:14s} f={r[4]:>4} CP{r[6]:5d} IV{r[7]:5.1f}% L{r[8]:.1f} {" ".join(flags)}')

# Save list
out = []
for r in xfer:
    out.append({'uid_hex': r[0], 'uid': r[1], 'species': r[3],
                'form': r[4], 'cp': r[6], 'iv': r[7]})
with open('shiny_xfer_list.json','w') as f:
    json.dump(out, f, indent=2)
print(f'\nWrote shiny_xfer_list.json ({len(out)} entries)')
