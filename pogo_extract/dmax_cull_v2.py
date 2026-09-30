"""Dmax cull v2: top 3 IV per evolution CHAIN (chain_root only, ignore form).

Form codes for Dmax pokemon are Dmax-specific identifiers, not regional variants.
So bucket purely by chain root.
"""
import sqlite3, json

CHAIN = {}
def chain(*pids):
    root = pids[0]
    for p in pids:
        CHAIN[p] = root

# Standard PoGo evolution chains touching user's Dmax inventory
chain(1, 2, 3)              # Bulbasaur line
chain(4, 5, 6)              # Charmander line
chain(7, 8, 9)              # Squirtle line
chain(10, 11, 12)           # Caterpie line
chain(172, 25, 26)          # Pichu/Pikachu/Raichu
chain(58, 59)               # Growlithe line
chain(63, 64, 65)           # Abra line
chain(66, 67, 68)           # Machop line
chain(92, 93, 94)           # Gastly line
chain(98, 99)               # Krabby line
chain(236, 106, 107, 237)   # Tyrogue/Hitmons
chain(440, 113, 242)        # Happiny/Chansey/Blissey
chain(133, 134, 135, 136, 196, 197, 470, 471, 700)  # Eevee chain
chain(138, 139)             # Omanyte/Omastar
chain(140, 141)             # Kabuto/Kabutops
chain(213,)                 # Shuckle (no evo)
chain(143, 446)             # Snorlax/Munchlax
chain(144,)                 # Articuno
chain(145,)                 # Zapdos
chain(146,)                 # Moltres
chain(243,)                 # Raikou
chain(244,)                 # Entei
chain(245,)                 # Suicune
chain(249,)                 # Lugia
chain(250,)                 # Ho-Oh
chain(280, 281, 282, 475)   # Ralts/Kirlia/Gardevoir/Gallade
chain(302,)                 # Sableye
chain(320, 321)             # Wailmer/Wailord
chain(328, 329, 330)        # Trapinch/Vibrava/Flygon
chain(363, 364, 365)        # Spheal/Sealeo/Walrein
chain(374, 375, 376)        # Beldum/Metang/Metagross
chain(378,)                 # Regice
chain(380,)                 # Latias
chain(381,)                 # Latios
chain(519, 520, 521)        # Pidove/Tranquill/Unfezant
chain(524, 525, 526)        # Roggenrola/Boldore/Gigalith
chain(527, 528)             # Woobat/Swoobat
chain(529, 530)             # Drilbur/Excadrill
chain(546, 547)             # Cottonee/Whimsicott
chain(554, 555)             # Darumaka/Darmanitan
chain(568, 569)             # Trubbish/Garbodor
chain(615,)                 # Cryogonal (no evo)
chain(686, 687)             # Inkay/Malamar
chain(761, 762, 763)        # Bounsweet/Steenee/Tsareena
chain(766,)                 # Passimian
chain(780,)                 # Drampa
chain(810, 811, 812)        # Grookey/Thwackey/Rillaboom
chain(813, 814, 815)        # Scorbunny/Raboot/Cinderace
chain(816, 817, 818)        # Sobble/Drizzile/Inteleon
chain(819, 820)             # Skwovet/Greedent
chain(821, 822, 823)        # Rookidee/Corvisquire/Corviknight
chain(831, 832)             # Wooloo/Dubwool
chain(848, 849)             # Toxel/Toxtricity
chain(856, 857, 858)        # Hatenna/Hattrem/Hatterene
chain(870,)                 # Falinks
chain(884,)                 # Duraludon (Archaludon=NEW pid TBD)
chain(892,)                 # Urshifu

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

rows = c.execute('''SELECT uid_hex, uid, pokemon_id, species_name, form, cp, iv_pct, level,
                           is_shiny, is_lucky, is_powered_up
                    FROM pokemon WHERE in_bag=1 AND fresh_bread_mode=1''').fetchall()
print(f'Total Dmax: {len(rows)}')

# Verify all pids are mapped
unmapped_pids = set()
for r in rows:
    if r[2] not in CHAIN:
        unmapped_pids.add((r[2], r[3]))
if unmapped_pids:
    print(f'\n*** UNMAPPED pids (will be kept by default until you confirm chain): {unmapped_pids}')
    print('*** These would be safer to keep until verified.')

# Bucket by chain ONLY (no form for Dmax)
groups = {}
for r in rows:
    pid = r[2]
    if pid not in CHAIN:
        groups.setdefault(('UNMAPPED', pid), []).append(r)
        continue
    key = CHAIN[pid]
    groups.setdefault(key, []).append(r)

keep_uids = set()
xfer_uids = set()

for key, lst in groups.items():
    lst.sort(key=lambda x: (-x[6], -x[5]))
    for i, r in enumerate(lst):
        uid_hex = r[0]
        if i < 3:
            keep_uids.add(uid_hex)
        elif r[8]:  # shiny exception
            keep_uids.add(uid_hex)
        else:
            xfer_uids.add(uid_hex)

# Show all chains with transfers
print()
print('=== Per-chain breakdown (only chains with transfers shown) ===')
shown_keys = set()
for key, lst in groups.items():
    if not any(r[0] in xfer_uids for r in lst): continue
    species_in_chain = sorted(set(x[3] for x in lst))
    chain_lbl = '/'.join(species_in_chain)[:50]
    print(f'\n  Chain root={key} ({chain_lbl}) - {len(lst)} pokemon')
    lst.sort(key=lambda x: (-x[6], -x[5]))
    for i, cr in enumerate(lst):
        decision = 'KEEP' if cr[0] in keep_uids else 'XFER'
        flags = []
        if cr[8]: flags.append('S')
        if cr[9]: flags.append('L')
        if cr[10]: flags.append('+')
        fl = ''.join(flags)
        mark = '*' if decision == 'XFER' else ' '
        rk = f'rank {i+1}'
        print(f'    {mark} {decision} {rk:8s} {cr[3]:14s} CP{cr[5]:5d} IV{cr[6]:5.1f}% L{cr[7]:4.1f} {fl}')

print(f'\n=== TOTAL: {len(rows)}  KEEP: {len(keep_uids)}  TRANSFER: {len(xfer_uids)} ===')

# Save list
xfer_list = []
for r in rows:
    if r[0] in xfer_uids:
        xfer_list.append({
            'uid_hex': r[0], 'uid': r[1], 'species': r[3], 'form': r[4],
            'cp': r[5], 'iv': r[6], 'level': r[7],
            'shiny': r[8], 'lucky': r[9], 'powered': r[10]
        })
with open('dmax_xfer_list_v2.json','w') as f:
    json.dump(xfer_list, f, indent=2)
print(f'Wrote dmax_xfer_list_v2.json')
