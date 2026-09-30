"""Kanto cull v3: full rules.

FULL PROTECTIONS (always keep):
  - Hundo (iv_pct >= 100)
  - Nundo (iv_pct == 0)
  - Gmax / Dmax (fresh_bread_mode != 0)
  - Shiny (fresh_shiny=1)
  - Lucky (is_lucky=1)
  - Traded (is_traded_flag_v2=1)
  - Legendary (Articuno/Zapdos/Moltres/Mewtwo/Mew)
  - User-tagged (auth_tag_names contains anything != CLAUDE_TX)
  - Location card / special background (fresh_has_location_card=1)

BUCKET DIMENSIONS: costume
BUCKET RULE: top 3 by IV per (species, form, costume) bucket.
"""
import sqlite3, json

LEGENDARY_KANTO = {144, 145, 146, 150, 151}

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
rows = c.execute('''SELECT uid_hex, uid, pokemon_id, species_name, form,
                           fresh_shiny, fresh_bread_mode, fresh_has_location_card,
                           fresh_costume, cp, iv_pct, level,
                           is_lucky, is_traded_flag_v2, is_powered_up,
                           auth_tag_names
                    FROM pokemon WHERE in_bag=1 AND pokemon_id BETWEEN 1 AND 151''').fetchall()
print(f'Total Kanto: {len(rows)}')

protected = []
xfer = []
buckets = {}

for r in rows:
    uid_hex,_u,pid,sp,form,shiny,bread,loc,cost,cp,iv,lvl,lucky,traded,powered,auth = r
    if pid in LEGENDARY_KANTO: protected.append((r,'legendary')); continue
    if (iv or 0) >= 100: protected.append((r,'hundo')); continue
    if (iv or 0) == 0: protected.append((r,'nundo')); continue
    if bread: protected.append((r,'gmax' if bread==2 else 'dmax')); continue
    if shiny: protected.append((r,'shiny')); continue
    if lucky: protected.append((r,'lucky')); continue
    if traded: protected.append((r,'traded')); continue
    if loc: protected.append((r,'location_card')); continue
    user_tags = [t for t in (auth or '').split(';') if t and t != 'CLAUDE_TX']
    if user_tags: protected.append((r,f'user_tag_{user_tags[0]}')); continue
    key = (pid, form or 0, cost or 0)
    buckets.setdefault(key, []).append(r)

for key, lst in buckets.items():
    lst.sort(key=lambda x: (-(x[10] or 0), -(x[9] or 0)))
    for i, r in enumerate(lst):
        if i < 3: protected.append((r, f'bucket_rank{i+1}'))
        else: xfer.append(r)

full_set = {"legendary","hundo","nundo","gmax","dmax","shiny","lucky","traded","location_card"}
print(f'  Full-protected: {sum(1 for _,reason in protected if reason in full_set or reason.startswith("user_tag"))}')
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
    if len(lst) <= 1: continue
    print(f'  {sp}: {len(lst)}')

print(f'\nSingletons: {sum(1 for lst in xfer_by_sp.values() if len(lst)==1)}')

out = []
for r in xfer:
    out.append({'uid_hex': r[0], 'uid': r[1], 'species': r[3], 'form': r[4],
                'cp': r[9], 'iv': r[10]})
with open('kanto_xfer_v3.json','w') as f:
    json.dump(out, f, indent=2)
print(f'\nWrote kanto_xfer_v3.json ({len(out)} entries)')

# Sanity: show any with concerning flags (should be empty)
print()
print('=== Sanity: any concerning flags in transfer list (should be 0) ===')
for sp, lst in sorted(xfer_by_sp.items()):
    for r in lst:
        flags = []
        if r[5]: flags.append('SHINY')
        if r[6]: flags.append('BREAD')
        if r[7]: flags.append('LOCCARD')
        if r[12]: flags.append('LUCKY')
        if r[13]: flags.append('TRADED')
        if r[10] >= 100: flags.append('HUNDO')
        if r[10] == 0: flags.append('NUNDO')
        ut = [t for t in (r[15] or '').split(';') if t and t != 'CLAUDE_TX']
        if ut: flags.append(f'USER_TAG({ut})')
        if flags:
            print(f'  WARN {sp} f={r[4]} CP{r[9]} IV{r[10]:.1f}: {flags}')
