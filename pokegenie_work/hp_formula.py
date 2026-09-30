import json
BASE = r'C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance'
data = json.load(open(BASE + r'\pokegenie_work\extracted\scan_data.json'))

# Collect (a,d,s) -> hpType pairs from ground truth where hpType is non-empty.
pairs = []
for e in data:
    if e.get('quickMove') == 'Hidden Power' and e.get('hiddenPowerType'):
        a = e.get('avgAttackIV'); d = e.get('avgDefenseIV'); s = e.get('avgStaminaIV')
        if a is None: continue
        pairs.append((int(a), int(d), int(s), e['hiddenPowerType']))
print('non-empty HP pairs:', len(pairs))

# PoGo Hidden Power type order (index 0..15):
HP_TYPES = ['Fighting', 'Flying', 'Poison', 'Ground', 'Rock', 'Bug', 'Ghost', 'Steel',
            'Fire', 'Water', 'Grass', 'Electric', 'Psychic', 'Ice', 'Dragon', 'Dark']

# Standard Gen-3 main-series formula uses bit0 of each of 6 stats. PoGo only has 3 IVs (atk/def/sta)
# 0..15 each. The PoGo Hidden Power formula (from datamines):
#   type = floor( (15 * X) / 63 ) where X derives from IV bits? Let's brute force a formula:
# Candidate A: idx = (a%2 + 2*(d%2) + 4*(s%2))  -> only 0..7, can't reach 16. No.
# Candidate B (known PoGo): idx = floor( ((a & 1) + 2*(d & 1) + 4*(s & 1)) * 15 / 7 )? only 0/2/4/6/8/10/12/15
# Let's just test the documented PoGo formula:
#   hp = floor( ( (atkIV % 2) + 2*(defIV % 2) + 4*(staIV % 2) ) ... ) -- insufficient bits.
# Actually PoGo uses ALL bits: hp_index = floor(15 * (sum over the 3 IVs of (iv & 8)?)) ...
# Brute force: find integer linear combo mod-based mapping that fits ALL pairs.

def test_formula(fn, name):
    ok = 0; bad = []
    for a, d, s, t in pairs:
        if HP_TYPES[fn(a, d, s) % 16] == t: ok += 1
        else: bad.append((a, d, s, t, HP_TYPES[fn(a, d, s) % 16]))
    print('%-40s %d/%d' % (name, ok, len(pairs)), '' if not bad else ('e.g. ' + str(bad[:3])))
    return ok

# Known correct PoGo formula (from reverse engineering, e.g. GoStadium / PokeGenie):
# idx = floor( ((a % 2) + 2*(d % 2) + 4*(s % 2)) * 16 / 8 )? no.
# The REAL one many tools use:
#   idx = floor( ( (atk & 1) + 2*(def & 1) + 4*(sta & 1) ) ... ) — but that maxes at 7.
# Try: uses (iv % 4) maybe. Let me brute force over masks/multipliers.
import itertools
best = (0, None)
for ma, md, ms in itertools.product(range(1, 16), repeat=3):
    for div in range(2, 64):
        def fn(a, d, s, ma=ma, md=md, ms=ms, div=div):
            return ((a & ma) + (d & md) * 2 + (s & ms) * 4) * 15 // div
        ok = sum(1 for a, d, s, t in pairs if HP_TYPES[fn(a, d, s) % 16] == t)
        if ok > best[0]:
            best = (ok, ('mask', ma, md, ms, 'div', div))
print('brute best:', best, 'of', len(pairs))
