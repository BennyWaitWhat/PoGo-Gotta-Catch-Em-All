"""READ-ONLY: prove whether the plain_line cap change (3 -> 2) accounts for the pile size.

Replicates keep_policy's plain-floor selection (rule 1b) at cap=2 and cap=3 and reports how many
currently-piled mons would be rescued by cap=3. No writes, no config mutation.
"""
import sqlite3, json, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
con = sqlite3.connect('pokemon.db'); con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute('SELECT * FROM pokemon WHERE in_bag=1')]
ps = set(open('system/analysis/tagsets/Transfer.txt').read().split())
pol = json.load(open('system/analysis/policy_reasons.json'))
try:
    from costume_forms import is_costume_form
except Exception:
    is_costume_form = lambda f: False
import keep_config

GENDER_TERMINALS = {415, 757, 361, 281, 280, 412}
_nundo_on = keep_config.rule_enabled('nundo')

def deco(r):
    d = r.get('costume_decoration_id')
    return d if (d and str(d) != '0') else 0

def truly_plain(r):
    return (not (r.get('fresh_costume') or 0) and not (r.get('special_bg_id') or 0)
            and not (r.get('fresh_natural_art_bg') or 0) and not deco(r)
            and (r.get('fresh_bread_mode') or 0) not in (1, 2)
            and not is_costume_form(r.get('fresh_form') or 0))

def slot_exempt(r):
    if (r['iv_total'] or 0) == 45:
        return True
    return bool(_nundo_on and r.get('is_zero') and r['pokemon_id'])

# cf() replication
_bc = collections.defaultdict(collections.Counter)
for r in rows:
    f = r.get('form') or 0
    reg = ((r.get('form_region') or '')).strip().lower()
    if f and reg in ('', 'normal', 'kantonian', 'none', 'null'):
        _bc[r['pokemon_id']][f] += 1
base = {p: c.most_common(1)[0][0] for p, c in _bc.items() if len(c) == 1}
cf = lambda r: (base.get(r['pokemon_id'], r.get('form') or 0) if not (r.get('form') or 0) else r.get('form'))
gt = lambda r: (r.get('gender') if r['pokemon_id'] in GENDER_TERMINALS else 0)

# the plain pool exactly as the engine builds it (shiny/shadow are excluded upstream)
plain_pool = collections.defaultdict(list)
for r in rows:
    if r.get('fresh_shiny') or (r.get('fresh_alignment') or 0) == 1:
        continue
    if truly_plain(r) and not slot_exempt(r):
        plain_pool[(r['pokemon_id'], cf(r), gt(r))].append(r)

# specials that DISPLACE plain slots by IV (non-hundo shinies + non-hundo cosmetic variants)
spec = collections.defaultdict(list)
for r in rows:
    if (r['iv_total'] or 0) == 45:
        continue
    if r.get('fresh_shiny') or (not truly_plain(r) and (r.get('fresh_alignment') or 0) != 1):
        spec[(r['pokemon_id'], cf(r), gt(r))].append(((r['iv_total'] or 0), (r['cp'] or 0)))

def kept_at(cap):
    keep = set()
    for key, lst in plain_pool.items():
        sp = spec.get(key)
        eff = cap
        if sp:
            merged = sorted([(iv, cp, 0) for iv, cp in sp] + [((r['iv_total'] or 0), (r['cp'] or 0), 1) for r in lst],
                            key=lambda x: (-x[0], -x[1], x[2]))[:cap]
            eff = sum(1 for x in merged if x[2] == 1)
        for r in sorted(lst, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0), r['uid_hex']))[:eff]:
            keep.add(r['uid_hex'])
    return keep

k2, k3 = kept_at(2), kept_at(3)
gain = k3 - k2
piled_rescued = gain & ps
print('plain-floor slots filled  at cap=2: %d   at cap=3: %d   (delta %+d)' % (len(k2), len(k3), len(k3) - len(k2)))
print('currently PILED mons that cap=3 would rescue: %d  of %d piled (%.0f%%)' % (
    len(piled_rescued), len(ps), 100 * len(piled_rescued) / max(len(ps), 1)))
byname = {r['uid_hex']: r for r in rows}
rest = ps - piled_rescued
print('piled for OTHER reasons (cap-independent): %d' % len(rest))
cnt = collections.Counter(byname[u]['species_name'] for u in rest if u in byname)
print('   top:', dict(cnt.most_common(8)))
# sanity: engine's variant_floor count vs our cap=2 model
vf = {u for u, rs in pol.items() if 'variant_floor' in rs}
print()
print('engine variant_floor total (incl. cosmetic variants): %d' % len(vf))
print('our plain-only model at cap=2: %d  (cosmetic variants are the remainder)' % len(k2))
print('model plains ⊆ engine variant_floor? %s  (mismatch %d)' % (k2 <= vf, len(k2 - vf)))
