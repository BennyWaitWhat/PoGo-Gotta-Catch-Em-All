"""Dmax cull: top 3 IV per evolution chain. Keep shinies as special.

Chain root = lowest pokemon_id in the evolution chain.
"""
import sqlite3, json

# Evolution chain mapping: pokemon_id -> chain_root_id
# Built from PoGo's evolution data for the species in user's Dmax inventory
CHAIN = {}
def chain(*pids):
    """All pids in this list belong to same chain; root = first."""
    root = pids[0]
    for p in pids:
        CHAIN[p] = root

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
chain(133, 134, 135, 136, 196, 197, 470, 471, 700)  # Eevee + evos
chain(138, 139)             # Omanyte/Omastar
chain(140, 141)             # Kabuto/Kabutops
chain(213,)                 # Shuckle
chain(143, 446)             # Snorlax (if any)
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
chain(615,)                 # Cryogonal
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
chain(884,)                 # Duraludon
chain(892,)                 # Urshifu

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

rows = c.execute('''SELECT uid_hex, uid, pokemon_id, species_name, form, cp, iv_pct, level,
                           is_shiny, is_lucky, is_powered_up
                    FROM pokemon WHERE in_bag=1 AND fresh_bread_mode=1''').fetchall()

# Group by chain root + form (form distinguishes regional variants)
groups = {}
unmapped = []
for r in rows:
    pid = r[2]
    if pid not in CHAIN:
        unmapped.append(r)
        continue
    key = (CHAIN[pid], r[4])  # (chain_root, form)
    groups.setdefault(key, []).append(r)

# Within each chain, rank by IV desc, CP desc
keep_uids = set()
xfer_uids = set()
keep_reasons = {}

for key, lst in groups.items():
    lst.sort(key=lambda x: (-x[6], -x[5]))  # iv desc, cp desc
    # top 3 IV: keep
    for i, r in enumerate(lst):
        uid_hex = r[0]
        if i < 3:
            keep_uids.add(uid_hex)
            keep_reasons[uid_hex] = f'top3_chain_rank{i+1}'
        else:
            # Special: keep if shiny
            if r[8]:
                keep_uids.add(uid_hex)
                keep_reasons[uid_hex] = 'shiny'
            else:
                xfer_uids.add(uid_hex)

# Unmapped species: keep all, flag for user
for r in unmapped:
    keep_uids.add(r[0])
    keep_reasons[r[0]] = f'UNMAPPED_pid{r[2]}'

print(f'Total Dmax: {len(rows)}')
print(f'  KEEP: {len(keep_uids)}')
print(f'  TRANSFER: {len(xfer_uids)}')
print(f'  Unmapped (kept by default): {len(unmapped)}')

# Save list
xfer_list = []
for r in rows:
    if r[0] in xfer_uids:
        xfer_list.append({
            'uid_hex': r[0], 'uid': r[1], 'species': r[3], 'form': r[4],
            'cp': r[5], 'iv': r[6], 'level': r[7],
            'shiny': r[8], 'lucky': r[9], 'powered': r[10]
        })
with open('dmax_xfer_list.json','w') as f:
    json.dump(xfer_list, f, indent=2)

# Show by chain
print()
print('=== Per-chain breakdown (chains with transfers) ===')
shown_keys = set()
for r in rows:
    if r[0] in xfer_uids:
        pid = r[2]
        root = CHAIN.get(pid)
        if root is None: continue
        key = (root, r[4])
        if key in shown_keys: continue
        shown_keys.add(key)
        chain_rows = [x for x in rows if (CHAIN.get(x[2]) == root and x[4] == r[4])]
        chain_rows.sort(key=lambda x: (-x[6], -x[5]))
        species_in_chain = sorted(set(x[3] for x in chain_rows))
        chain_lbl = '/'.join(species_in_chain)[:40]
        print(f'\n  Chain root pid={root} form={r[4]} ({chain_lbl})')
        for i, cr in enumerate(chain_rows):
            decision = 'KEEP' if cr[0] in keep_uids else 'XFER'
            flags = []
            if cr[8]: flags.append('S')
            if cr[9]: flags.append('L')
            if cr[10]: flags.append('+')
            fl = ''.join(flags)
            mark = '*' if decision == 'XFER' else ' '
            print(f'    {mark} {decision} {cr[3]:14s} CP{cr[5]:5d} IV{cr[6]:5.1f}% L{cr[7]:4.1f} {fl}')

print(f'\n=== Transfer count: {len(xfer_uids)} ===')
print(f'\n*** Special preserved: shinies kept even outside top 3 ***')
