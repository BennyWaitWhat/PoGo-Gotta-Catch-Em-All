"""Print user's top ML candidates per PVPoke's open-Master rankings, with
the resource cost (XL candy + stardust + TMs) needed to max each one."""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')

MOVES = {int(k): v for k, v in json.load(open('move_id_to_name.json')).items()}


def pretty(m):
    if not m:
        return ''
    s = MOVES.get(m, f'?{m}').replace('_FAST', '').replace('_', ' ').title()
    return s.replace('Of', 'of').replace('The', 'the')


# Cumulative XL candy from level L (40.5..49.5) to 50
XL_BY_LEVEL = {
    50.0: 0, 49.5: 20, 49.0: 40, 48.5: 57, 48.0: 74, 47.5: 91, 47.0: 108,
    46.5: 123, 46.0: 138, 45.5: 153, 45.0: 168, 44.5: 181, 44.0: 194,
    43.5: 207, 43.0: 220, 42.5: 232, 42.0: 244, 41.5: 256, 41.0: 268,
    40.5: 279, 40.0: 290,
}


def xl_needed(lvl):
    if lvl >= 50.0:
        return 0
    if lvl < 40.0:
        return 296
    return XL_BY_LEVEL.get(lvl, 296)


def dust_needed(lvl):
    if lvl >= 50.0:
        return 0
    return int((50.0 - lvl) * 2 * 17000)  # rough 17k/half-level


ml = [
    (1,  'Zacian (Crowned Sword)',    "species_name='Zacian' AND form=2577 AND fresh_alignment IN (0,2)",       99.1,
        ('Metal Claw', 'Close Combat', 'Behemoth Blade'),
        'Behemoth Blade is the signature on Crowned form'),
    (2,  'Palkia (Origin)',           "species_name='Palkia' AND form=2830 AND fresh_alignment IN (0,2)",       98.8,
        ('Dragon Breath', 'Aqua Tail', 'Spacial Rend'),
        'Spacial Rend = Origin signature charged'),
    (3,  'Metagross',                 "species_name='Metagross' AND fresh_alignment IN (0,2)",                   96.6,
        ('Shadow Claw', 'Meteor Mash', 'Earthquake'),
        'Meteor Mash = legacy Elite Charged TM'),
    (4,  'Xerneas',                   "species_name='Xerneas' AND fresh_alignment IN (0,2)",                     95.2,
        ('Geomancy', 'Close Combat', 'Moonblast'),
        'Geomancy = signature fast (only from Xerneas raid days)'),
    (5,  'Zamazenta (Crowned Shield)', "species_name='Zamazenta' AND form=2579 AND fresh_alignment IN (0,2)",    94.8,
        ('Ice Fang', 'Close Combat', 'Behemoth Bash'),
        'Behemoth Bash is signature on Crowned form'),
    (6,  'Kyurem White',              "species_name='Kyurem' AND form=147 AND fresh_alignment IN (0,2)",         94.7,
        ('Dragon Breath', 'Fusion Flare', 'Ice Burn'), ''),
    (7,  'Dialga (Origin)',           "species_name='Dialga' AND form=2829 AND fresh_alignment IN (0,2)",        94.4,
        ('Dragon Breath', 'Roar of Time', 'Iron Head'),
        'Roar of Time = Origin signature'),
    (8,  'Lunala',                    "species_name='Lunala' AND fresh_alignment IN (0,2)",                      94.2,
        ('Shadow Claw', 'Shadow Ball', 'Moonblast'), ''),
    (9,  'Reshiram',                  "species_name='Reshiram' AND fresh_alignment IN (0,2)",                    94.1,
        ('Dragon Breath', 'Fusion Flare', 'Draco Meteor'), ''),
    (10, 'Kyurem Black',              "species_name='Kyurem' AND form=148 AND fresh_alignment IN (0,2)",         92.9,
        ('Dragon Tail', 'Freeze Shock', 'Fusion Bolt'), ''),
    (11, 'Zekrom',                    "species_name='Zekrom' AND fresh_alignment IN (0,2)",                      92.6,
        ('Dragon Breath', 'Outrage', 'Fusion Bolt'),
        'Outrage is the legacy CD move (Elite Charged TM)'),
    (12, 'Marshadow',                 "species_name='Marshadow' AND fresh_alignment IN (0,2)",                   92.0,
        ('Shadow Claw', 'Close Combat', 'Ice Punch'),
        'wants Shadow Claw over Sucker Punch'),
    (13, 'Kyogre',                    "species_name='Kyogre' AND fresh_alignment IN (0,2)",                      91.8,
        ('Waterfall', 'Avalanche', 'Origin Pulse'),
        'PVPoke prefers Avalanche over Thunder for ML coverage'),
    (15, 'Lugia',                     "species_name='Lugia' AND fresh_alignment IN (0,2)",                       90.7,
        ('Dragon Tail', 'Aeroblast', 'Fly'),
        'Aeroblast = legacy signature, Elite Charged TM'),
    (16, 'Eternatus',                 "species_name='Eternatus' AND fresh_alignment IN (0,2)",                   90.5,
        ('Dragon Tail', 'Dynamax Cannon', 'Flamethrower'),
        'Dragon Tail > Poison Jab'),
    (17, 'Lugia Shadow',              "species_name='Lugia' AND fresh_alignment=1",                       89.9,
        ('Dragon Tail', 'Aeroblast', 'Fly'),
        'Frustration → Elite Charged TM (or purify first if you have spare CTM)'),
    (18, 'Metagross Shadow',          "species_name='Metagross' AND fresh_alignment=1",                   89.7,
        ('Shadow Claw', 'Meteor Mash', 'Earthquake'),
        'needs Shadow Claw + Meteor Mash; current only L8'),
    (19, 'Necrozma (Dawn Wings)',     "species_name='Necrozma' AND form=2717 AND fresh_alignment IN (0,2)",      89.3,
        ('Shadow Claw', 'Dark Pulse', 'Moongeist Beam'),
        'Shadow Claw > Psycho Cut'),
    (20, 'Yveltal',                   "species_name='Yveltal' AND fresh_alignment IN (0,2)",                     89.0,
        ('Sucker Punch', 'Dark Pulse', 'Oblivion Wing'), ''),
    (21, 'Ho-Oh',                     "species_name='Ho-Oh' AND fresh_alignment IN (0,2)",                       88.5,
        ('Incinerate', 'Brave Bird', 'Sacred Fire'),
        'Sacred Fire = legacy event Elite Charged TM'),
    (23, 'Garchomp',                  "species_name='Garchomp' AND fresh_alignment IN (0,2)",                    87.9,
        ('Dragon Tail', 'Twister', 'Earth Power'),
        'Twister = legacy CD Elite Charged TM'),
    (24, 'Groudon',                   "species_name='Groudon' AND fresh_alignment IN (0,2)",                     87.8,
        ('Dragon Tail', 'Fire Punch', 'Precipice Blades'),
        'Precipice Blades = CD signature'),
    (25, 'Meloetta (Aria)',           "species_name='Meloetta' AND fresh_alignment IN (0,2)",                    87.7,
        ('Confusion', 'Psyshock', 'Dazzling Gleam'),
        'needs Confusion Fast TM + Psyshock/Dazzling Gleam Charged TMs'),
]

c = sqlite3.connect('pokemon.db')
print(f'{"#":<3}{"Sc":>5}  {"Pokemon":<26}  {"Lv":>4}  {"IVs":<8}  XL→50  Dust→50    Action')
print('-' * 160)
for rank, label, where, score, ideal, note in ml:
    q = (f"SELECT cp, iv_total, iv_atk, iv_def, iv_sta, level, move1, move2, move3 "
         f"FROM pokemon WHERE in_bag=1 AND ({where}) "
         f"ORDER BY iv_total DESC, cp DESC LIMIT 1")
    # Also pull alignment + uid for display clarity
    q2 = q.replace(
        "SELECT cp, iv_total, iv_atk, iv_def, iv_sta, level, move1, move2, move3",
        "SELECT cp, iv_total, iv_atk, iv_def, iv_sta, level, move1, move2, move3, fresh_alignment, uid_hex")
    r = c.execute(q2).fetchone()
    if not r:
        print(f'{rank:<3}{score:>5}    {label:<26}    --   none in your bag')
        continue
    cp, ivt, a, d, s, lvl, m1, m2, m3, fa, uid = r
    if fa == 2:
        label = label + ' (Purified)'
    elif fa == 1:
        label = label + ' (Shadow)'
    cur = {pretty(m) for m in (m1, m2, m3) if m}
    miss = [m for m in ideal if m not in cur]
    ivs = f'{a}/{d}/{s}'
    flag = '★' if ivt == 45 else '+' if ivt >= 42 else ' '
    xl = xl_needed(lvl)
    dust = dust_needed(lvl)
    actions = []
    if lvl < 50.0:
        actions.append(f'PWR L{lvl}→50')
    if miss:
        actions.append('TM: ' + ', '.join(miss))
    if not actions:
        actions = ['MAXED & moveset perfect — ready']
    action_str = '; '.join(actions)
    extra = f'  -- {note}' if note else ''
    print(f'{rank:<3}{score:>5}  {flag} {label:<24}  {lvl:>4}  {ivs:<8}  {xl:>5}  {dust:>7,}    {action_str}{extra}')

c.close()
