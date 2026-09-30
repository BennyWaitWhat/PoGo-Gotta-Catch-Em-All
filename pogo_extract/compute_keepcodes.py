"""Compute per-mon SUFFIXED nickname = "<species> <code>" (12-char cap), mirroring keep_policy:
  VF1/VF2/VF3 = variant_floor positions 1-3 (plain pool: non-shadow non-shiny), iv desc.
  GL / UL     = best gl_rank / best ul_rank per (pid,form) among NON-shiny rares.
  XXL         = xxl keepers (size==5): top-2 height + top-1 weight per (pid,form), non-shiny.
  O / F       = traded/lucky from ethanmateovz (O) / florandez (F).  [additive to any code]
  SHINIES     = suffixed by IV rank within their species (1..x), iv desc; + O/F if traded.
Every OTHER mon that currently has a non-species nickname -> CLEAR ("").  Mons with no code
and no old nickname -> left alone.  Name+code is compacted/truncated to fit 12 chars.
Writes keepcode_targets.json = [[uid_hex, nickname], ...]; prints the breakdown.
"""
import sqlite3, json, os, sys
from collections import defaultdict, Counter
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
RARE_PIDS = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
DB = os.path.join(HERE, 'pokemon.db')


def build_nick(species, code):
    code = code.strip()
    if not code:
        return ''
    s = f"{species} {code}"
    if len(s) <= 12: return s
    c2 = code.replace(' ', '')
    s = f"{species} {c2}"
    if len(s) <= 12: return s
    s = f"{species}{c2}"
    if len(s) <= 12: return s
    keep = max(1, 12 - len(c2))
    return f"{species[:keep]}{c2}"


c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
rows = c.execute("""SELECT uid_hex,pokemon_id,species_name,form,fresh_alignment,fresh_shiny,
  fresh_costume,special_bg_id,natural_art_background,costume_decoration_id,fresh_bread_mode,
  iv_total,cp,gl_rank,ul_rank,pokemon_size_category,height_m,weight_kg,
  nickname,is_traded,is_traded_flag_v2,is_lucky,original_owner_name
  FROM pokemon WHERE in_bag=1""").fetchall()

# --- variant_floor positions (plain pool) ---
vg = defaultdict(list)
for r in rows:
    if r['fresh_alignment'] == 1 or r['fresh_shiny']:
        continue
    key = (r['pokemon_id'], r['form'] or 0, r['fresh_costume'] or 0, r['special_bg_id'] or 0,
           r['natural_art_background'] or 0, r['costume_decoration_id'] or 0, r['fresh_bread_mode'] or 0)
    vg[key].append(r)
vf_rank = {}
for key, lst in vg.items():
    _, _, _co, _bg, _ar, _de, _br = key
    _ds = bool(_de) and str(_de) != '0'
    cap = 8 if _br == 2 else (4 if (_br == 1 or _co or _bg or _ar or _ds) else 3)  # plain -> top-3 (2026-06-01)
    kept = sorted(lst, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0)))[:cap]
    vfn = 0
    for r in kept:
        if (r['iv_total'] or 0) == 45:
            continue          # hundo -> labeled "100"; excluded from VF rank so the
                              # best NON-hundo becomes VF1 (no gap).
        vfn += 1
        if vfn <= 3:
            vf_rank[r['uid_hex']] = vfn

# --- best GL / best UL per (pid,form) among non-shiny rares ---
rg = defaultdict(list)
for r in rows:
    if (not r['fresh_shiny']) and r['pokemon_id'] in RARE_PIDS:
        rg[(r['pokemon_id'], r['form'] or 0)].append(r)
gl_set, ul_set = set(), set()
for lst in rg.values():
    glc = [r for r in lst if r['gl_rank'] is not None]
    ulc = [r for r in lst if r['ul_rank'] is not None]
    if glc: gl_set.add(min(glc, key=lambda r: r['gl_rank'])['uid_hex'])
    if ulc: ul_set.add(min(ulc, key=lambda r: r['ul_rank'])['uid_hex'])

# --- XXL keepers (non-shiny) ---
xg = defaultdict(list)
for r in rows:
    if (not r['fresh_shiny']) and (r['pokemon_size_category'] or 0) == 5:
        xg[(r['pokemon_id'], r['form'] or 0)].append(r)
xxl_set = set()
for lst in xg.values():
    for metric, n in (('height_m', 2), ('weight_kg', 1)):
        for r in sorted(lst, key=lambda x: -(x[metric] or 0))[:n]:
            xxl_set.add(r['uid_hex'])

# --- shiny IV rank within species ---
sh = defaultdict(list)
for r in rows:
    if r['fresh_shiny']:
        sh[r['species_name']].append(r)
shiny_rank = {}
for sp, lst in sh.items():
    for i, r in enumerate(sorted(lst, key=lambda x: (-(x['iv_total'] or 0), -(x['cp'] or 0))), 1):
        shiny_rank[r['uid_hex']] = i


def traded_code(r):
    if r['is_traded'] or r['is_traded_flag_v2'] or r['is_lucky']:
        o = (r['original_owner_name'] or '').strip().lower()
        if o == 'ethanmateovz': return 'O'
        if o == 'florandez': return 'F'
    return ''


targets, cnt = [], Counter()
nuke = 0
for r in rows:
    u = r['uid_hex']; sp = r['species_name']
    tc = traded_code(r)
    is_hundo = (r['iv_total'] or 0) == 45     # 15/15/15 -> label "100", not VF1/shiny-rank
    if r['fresh_shiny']:
        parts = ['100' if is_hundo else str(shiny_rank[u])]
        cnt['100' if is_hundo else 'shiny'] += 1
        if tc: parts.append(tc); cnt[tc] += 1
    else:
        parts = []
        if is_hundo:
            parts.append('100'); cnt['100'] += 1
        elif u in vf_rank:
            parts.append(f"VF{vf_rank[u]}"); cnt[f"VF{vf_rank[u]}"] += 1
        if u in gl_set:  parts.append("GL");  cnt['GL'] += 1
        if u in ul_set:  parts.append("UL");  cnt['UL'] += 1
        if u in xxl_set: parts.append("XXL"); cnt['XXL'] += 1
        if tc: parts.append(tc); cnt[tc] += 1
    if parts:
        targets.append([u, build_nick(sp, " ".join(parts))])
    else:
        has_old = bool((r['nickname'] or '').strip()) and r['nickname'] != sp
        if has_old:
            targets.append([u, ""]); nuke += 1

json.dump(targets, open(os.path.join(HERE, 'keepcode_targets.json'), 'w'), indent=0)
sets = sum(1 for _, n in targets if n)
print(f"TOTAL writes: {len(targets)}   (code-sets={sets}, nukes={nuke})")
print("per-code:", dict(sorted(cnt.items())))
nm = {r['uid_hex']: (r['species_name'], r['fresh_shiny']) for r in rows}
print("\nsamples (coded):")
shown = 0
for u, n in targets:
    if n and shown < 16:
        tag = 'shiny' if nm[u][1] else ''
        print(f"  {nm[u][0]:<13} -> {n!r}  {tag}"); shown += 1
print("sample nukes:", [nm[u][0] for u, n in targets if not n][:6])
