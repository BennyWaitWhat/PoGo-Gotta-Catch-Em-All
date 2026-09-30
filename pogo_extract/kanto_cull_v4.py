"""Kanto cull v4: full rules with shadow/purified + XXL top-3-heaviest.

FULL PROTECTIONS (always keep):
  - Hundo / Nundo
  - Shadow / Purified (alignment != 0)
  - Gmax / Dmax (fresh_bread_mode != 0)
  - Shiny / Lucky / Traded
  - Legendary (Articuno/Zapdos/Moltres/Mewtwo/Mew)
  - User-tagged (any auth tag != CLAUDE_TX)
  - Location card / special background

BUCKET RULES (top 3 per (species, form, costume) bucket):
  - XXL pokemon: top 3 BY WEIGHT (heaviest)
  - Non-XXL: top 3 BY IV%
"""
import sqlite3, json

LEGENDARY_KANTO = {144, 145, 146, 150, 151}

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
rows = c.execute('''SELECT uid_hex, uid, pokemon_id, species_name, form,
                           fresh_shiny, fresh_bread_mode, fresh_has_location_card,
                           fresh_costume, cp, iv_pct, level,
                           is_lucky, is_traded_flag_v2, is_powered_up,
                           auth_tag_names, fresh_alignment, pokemon_size_category,
                           weight_kg
                    FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN 1 AND 151''').fetchall()
print(f'Total Kanto: {len(rows)}')

protected = []
xfer = []
xxl_buckets = {}
norm_buckets = {}

for r in rows:
    (uid_hex,_u,pid,sp,form,shiny,bread,loc,cost,cp,iv,lvl,
     lucky,traded,powered,auth,align,size_cat,weight) = r

    if pid in LEGENDARY_KANTO: protected.append((r,'legendary')); continue
    if (iv or 0) >= 100: protected.append((r,'hundo')); continue
    if (iv or 0) == 0: protected.append((r,'nundo')); continue
    if (align or 0) == 1: protected.append((r,'shadow')); continue
    if (align or 0) == 2: protected.append((r,'purified')); continue
    if bread: protected.append((r,'gmax' if bread==2 else 'dmax')); continue
    if shiny: protected.append((r,'shiny')); continue
    if lucky: protected.append((r,'lucky')); continue
    if traded: protected.append((r,'traded')); continue
    if loc: protected.append((r,'location_card')); continue
    user_tags = [t for t in (auth or '').split(';') if t and t != 'CLAUDE_TX']
    if user_tags: protected.append((r,f'user_tag_{user_tags[0]}')); continue

    key = (pid, form or 0, cost or 0)
    if size_cat == 5:
        xxl_buckets.setdefault(key, []).append(r)
    else:
        norm_buckets.setdefault(key, []).append(r)

# XXL bucket: top 3 by weight (heaviest)
for key, lst in xxl_buckets.items():
    lst.sort(key=lambda x: -(x[18] or 0))  # weight_kg desc
    for i, r in enumerate(lst):
        if i < 3: protected.append((r, f'xxl_top3_heaviest_rank{i+1}'))
        else: xfer.append(r)

# Non-XXL bucket: top 3 by IV
for key, lst in norm_buckets.items():
    lst.sort(key=lambda x: (-(x[10] or 0), -(x[9] or 0)))  # iv desc, cp desc
    for i, r in enumerate(lst):
        if i < 3: protected.append((r, f'bucket_iv_rank{i+1}'))
        else: xfer.append(r)

full_set = {"legendary","hundo","nundo","shadow","purified","gmax","dmax","shiny","lucky","traded","location_card"}
print(f'  Full-protected (status): {sum(1 for _,reason in protected if reason in full_set or reason.startswith("user_tag"))}')
print(f'  XXL top-3-heaviest: {sum(1 for _,reason in protected if reason.startswith("xxl_"))}')
print(f'  Non-XXL bucket-top-3: {sum(1 for _,reason in protected if reason.startswith("bucket_iv_"))}')
print(f'  XXL buckets: {len(xxl_buckets)}, Non-XXL buckets: {len(norm_buckets)}')
print(f'  TRANSFER: {len(xfer)}')

# Sanity check
print()
print('=== Sanity: any concerning flags in transfer (should be 0) ===')
for r in xfer:
    flags = []
    if r[5]: flags.append('SHINY')
    if r[6]: flags.append('BREAD')
    if r[7]: flags.append('LOCCARD')
    if r[12]: flags.append('LUCKY')
    if r[13]: flags.append('TRADED')
    if r[10] >= 100: flags.append('HUNDO')
    if r[10] == 0: flags.append('NUNDO')
    if r[16] in (1,2): flags.append(f'ALIGN{r[16]}')
    ut = [t for t in (r[15] or '').split(';') if t and t != 'CLAUDE_TX']
    if ut: flags.append(f'USER_TAG({ut})')
    if flags:
        print(f'  WARN {r[3]} f={r[4]} CP{r[9]} IV{r[10]:.1f}: {flags}')

# Group transfers
print()
print('=== Transfers grouped by species ===')
xfer_by_sp = {}
for r in xfer:
    xfer_by_sp.setdefault(r[3], []).append(r)
for sp, lst in sorted(xfer_by_sp.items(), key=lambda x: -len(x[1])):
    print(f'  {sp}: {len(lst)}')

out = []
for r in xfer:
    out.append({'uid_hex': r[0], 'uid': r[1], 'species': r[3], 'form': r[4],
                'cp': r[9], 'iv': r[10]})
with open('kanto_xfer_v4.json','w') as f:
    json.dump(out, f, indent=2)
print(f'\nWrote kanto_xfer_v4.json ({len(out)} entries)')
