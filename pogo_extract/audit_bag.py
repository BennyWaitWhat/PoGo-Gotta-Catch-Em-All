"""audit_bag.py — independent triple-check of the entire bag.
Re-derives each tag from the raw DB (NOT via build_tagsets) and compares to the
actual DB tag membership; checks transfer-safety, keep-tag/transfer disjointness,
keep/transfer accounting vs policy_reasons, and basic sanity.
"""
import sqlite3, json, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from references import LEGENDARY_IDS, MYTHICAL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS
from pvp_iv_rule import qualifies
RARE = LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
gm = json.load(open(os.path.join(HERE, 'pvpoke_gamemaster.json'), encoding='utf-8'))
BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
c = sqlite3.connect(os.path.join(HERE, 'pokemon.db')); c.row_factory = sqlite3.Row
rows = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
N = len(rows)

actual = defaultdict(set)
for r in rows:
    for t in (r['auth_tag_names'] or '').split(';'):
        if t:
            actual[t].add(r['uid_hex'])

reasons = {}
pr = os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json')
if os.path.exists(pr):
    reasons = json.load(open(pr))

transfer = actual['Transfer']
P, F = [], []
def chk(name, ok, detail=''):
    (P if ok else F).append(f"{'✓' if ok else '✗ FAIL'}  {name}{(' — ' + detail) if detail else ''}")

# ---------- per-tag exact / validity ----------
# Hundo: member <=> iv_total==45
d_h = {r['uid_hex'] for r in rows if r['iv_total'] == 45}
chk('Hundo == iv_total45', d_h == actual['Hundo'], f"derived {len(d_h)} vs tag {len(actual['Hundo'])}")
# Nundo: is_zero & pid!=0
d_n = {r['uid_hex'] for r in rows if r['is_zero'] and r['pokemon_id']}
chk('Nundo == is_zero&pid', d_n == actual['Nundo'], f"derived {len(d_n)} vs tag {len(actual['Nundo'])}")
# Event: cosmetic union, MINUS transfer
d_e = {r['uid_hex'] for r in rows if (r['fresh_costume'] or r['special_bg_id'] or r['natural_art_background'] or r['fresh_has_location_card'] == 1)} - transfer
chk('Event == cosmetic-union∖T', d_e == actual['Event'], f"derived {len(d_e)} vs tag {len(actual['Event'])}")
# Best Buddy: was_best_buddy_badge, MINUS transfer
d_b = {r['uid_hex'] for r in rows if r['was_best_buddy_badge'] == 1} - transfer
chk('BestBuddy == badge∖T', d_b == actual['Best Buddy'], f"derived {len(d_b)} vs tag {len(actual['Best Buddy'])}")
# Traded by E+F
d_t = {r['uid_hex'] for r in rows if (r['is_traded'] or r['is_traded_flag_v2'] or r['is_lucky']) and (r['original_owner_name'] or '').strip().lower() in ('ethanmateovz', 'florandez')} - transfer
chk('TradedE+F == owner∖T', d_t == actual['Traded by E+F'], f"derived {len(d_t)} vs tag {len(actual['Traded by E+F'])}")
# GL IV / UL IV: every member passes the rule; no qualifier missing (∖T)
gl_q = {r['uid_hex'] for r in rows if qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['gl_stage'], r['gl_rank'], 1400, BS)} - transfer
ul_q = {r['uid_hex'] for r in rows if qualifies(r['species_name'], r['form'], r['iv_atk'], r['iv_def'], r['iv_sta'], r['ul_stage'], r['ul_rank'], 2400, BS)} - transfer
chk('GL IV == rule∖T', gl_q == actual['GL IV'], f"derived {len(gl_q)} vs tag {len(actual['GL IV'])}")
chk('UL IV == rule∖T', ul_q == actual['UL IV'], f"derived {len(ul_q)} vs tag {len(actual['UL IV'])}")
# XXL: every member is size==5
xxl_bad = [u for u in actual['XXL'] if (by := next((x for x in rows if x['uid_hex'] == u), None)) and (by['pokemon_size_category'] or 0) != 5]
chk('XXL all size==5', not xxl_bad, f"{len(xxl_bad)} non-XXL-size members")
# Legacy: every member in legacy_accurate
leg = set()
la = os.path.join(HERE, 'legacy_accurate.json')
if os.path.exists(la):
    leg = {e['uid_hex'] for e in json.load(open(la, encoding='utf-8'))}
leg_bad = [u for u in actual['Legacy Moves'] if u not in leg]
chk('Legacy ⊆ legacy_accurate', not leg_bad, f"{len(leg_bad)} members not in legacy_accurate")

# ---------- transfer safety ----------
sens = [(r['species_name'], r['iv_total']) for r in rows if r['uid_hex'] in transfer and (
        r['is_shiny'] or r['iv_total'] == 45 or r['pokemon_id'] in RARE or
        r['was_best_buddy_badge'] == 1 or (r['iv_atk'] == 0 and r['iv_def'] == 15 and r['iv_sta'] == 15))]
chk('Transfer has NO sensitive (shiny/hundo/rare/BB/0-15-15)', not sens, f"{len(sens)}: {sens[:6]}")

# ---------- keep-tags disjoint from Transfer ----------
KEEPTAGS = ['GL IV', 'UL IV', 'XXL', 'Hundo', 'Nundo', 'Event', 'Best Buddy', 'Traded by E+F', 'Legacy Moves']
for kt in KEEPTAGS:
    ov = actual[kt] & transfer
    chk(f'{kt} ∩ Transfer = ∅', not ov, f"{len(ov)} overlap")

# ---------- keep/transfer accounting vs policy_reasons ----------
if reasons:
    t_with_reason = [u for u in transfer if u in reasons]
    chk('Transfer mons have NO keep-reason', not t_with_reason, f"{len(t_with_reason)} transfer mons have a keep reason")
    kept = set(by_uid := {r['uid_hex'] for r in rows}) - transfer
    no_reason = [u for u in kept if u not in reasons]
    chk('Every kept mon has a reason', not no_reason, f"{len(no_reason)} kept mons with no reason")

# ---------- sanity ----------
pid0 = [r['uid_hex'] for r in rows if not r['pokemon_id']]
chk('No pid0 phantoms in_bag', not pid0, f"{len(pid0)} pid0")
unranked = [r['uid_hex'] for r in rows if r['gl_rank'] is None or r['ul_rank'] is None]
chk('All in_bag ranked', not unranked, f"{len(unranked)} unranked (new first-catches?)")

print(f"=== BAG AUDIT  (in_bag={N})  ===")
print(f"tags: " + " · ".join(f"{t} {len(actual[t])}" for t in ['Hundo','GL IV','UL IV','XXL','Event','Nundo','Best Buddy','Traded by E+F','Legacy Moves','Transfer']))
print()
for line in P: print(line)
for line in F: print(line)
print(f"\n=== {len(P)} PASS / {len(F)} FAIL ===" + ("  ✅ ALL CLEAN" if not F else "  ⚠ SEE FAILURES"))
