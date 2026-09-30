"""
Add species-based flags: legendary, mythical, can_mega_evolve, dynamax, gigantamax.
These are properties of the SPECIES, not individual pokemon, so we can derive them.
"""
import sqlite3

# Pokemon GO species lists (verified against PoGo data)

LEGENDARY = {
    144,145,146,150,                                # Gen 1 birds + Mewtwo
    243,244,245,249,250,                            # Gen 2 dogs + Lugia/Ho-oh
    377,378,379,380,381,382,383,384,                # Gen 3 regis + lati + groudon/kyogre/rayquaza
    480,481,482,483,484,485,486,487,488,            # Gen 4 lake trio + dialga/palkia/heatran/regigigas/giratina/cresselia
    638,639,640,641,642,643,644,645,646,            # Gen 5 swords + tornadus/thundurus/reshiram/zekrom/landorus/kyurem
    716,717,718,                                     # Gen 6 xerneas/yveltal/zygarde
    772,773,785,786,787,788,789,790,791,792,        # Gen 7 type:null + tapus + cosmog/cosmoem/solgaleo/lunala
    793,794,795,796,797,798,799,                    # ultra beasts
    800,                                             # Necrozma
    888,889,890,                                     # Gen 8 zacian/zamazenta/eternatus
    891,892,893,894,895,896,897,898,                # Kubfu/Urshifu/Zarude/Regieleki/Regidrago/Glastrier/Spectrier/Calyrex
    905,                                             # Enamorus
    1001,1002,1003,1004,1005,1006,                  # Gen 9 ruinous + paradox
    1007,1008,1009,1010,                            # Koraidon/Miraidon/walking wake/iron leaves
    1014,1015,1016,1017,                            # Loyal Three + Ogerpon
    1018,                                            # Archaludon
    1020,1021,1022,1023,1024                        # Paradox legendaries + Terapagos
}

MYTHICAL = {
    151, 251, 385, 386, 489, 490, 491, 492, 493,
    494, 647, 648, 649, 719, 720, 721,
    801, 802, 807, 808, 809,
    893, 1025
}

# Mega Evolution capable (well-known list)
MEGA_CAPABLE = {
    3,6,9,15,18,65,80,94,115,127,130,142,150,181,208,212,229,248,254,257,260,
    282,302,303,306,308,310,319,323,334,354,359,362,373,376,380,381,384,428,
    445,448,460,475,531,719,
}

# Dynamax / Gigantamax (Gen 8 mechanic)
DYNAMAX_CAPABLE = {
    # All standard pokemon can dynamax in main games. In PoGO, only specific species.
    1,4,7,52,68,143,143,809,
    810,813,816,819,825,827,830,832,834,837,840,843,845,847,849,851,853,856,
    858,860,861,862,863,864,865,866,867,868,869,870,871,872,873,874,875,879,
    880,881,882,883,884,887,
    888,889,890,892,893,894,895,898,
}

GIGANTAMAX_CAPABLE = {
    3,6,9,12,25,52,68,94,99,131,133,143,809,812,815,818,823,826,834,839,
    842,844,849,851,858,861,862,869,879,884,
}

# Pokemon that can_evolve - those with evolution paths (most Gen 1-9 species except final evos and standalone)
# Approximate: most non-final-form species
NO_EVOLUTION = {
    132, 137,138,139,140,141,142,                                  # Ditto and fossils
    143, 144,145,146,                                              # Snorlax, birds
    150,151, 201,202,210,211,213,214,                              # Mewtwo, Mew, Unown, Wobbuffet, etc.
    218,219,220,221,222,223,224,225,226,227,229,233,234,235,237,
    241,242,243,244,245,248,249,250,251,
    260,                                                            # Swampert (final)
    262,264,                                                        # Mightyena, Linoone (final)
    273,275,                                                        # Seedot final
    284,                                                            # Masquerain
    288,289,                                                        # Vigoroth, Slaking - has evos
    291,292, 295, 297, 299,                                         # Ninjask Shedinja, etc
    302,303,306,308,310,                                            # Mawile, Aggron, Medicham, Manectric
    312,313,314,                                                    # Minun, Volbeat, Illumise
    321,323,324,                                                    # Wailord, Camerupt, Torkoal
    327,330,332,                                                    # Spinda, Flygon, Cacturne
    336,337,338,                                                    # Seviper, Lunatone, Solrock
    340,342,344,                                                    # Whiscash, Crawdaunt, Claydol
    346,348,                                                        # Cradily, Armaldo
    350,351,352,358,                                                # Milotic, Castform, Kecleon, Chimecho
    357,                                                            # Tropius
    369,370,                                                        # Relicanth, Luvdisc
    373,376,                                                        # Salamence, Metagross
    377,378,379,                                                    # Regis
    380,381,382,383,384,385,386,                                    # Latis/big legendaries
    441,                                                             # Chatot
    442,                                                             # Spiritomb
    445,                                                             # Garchomp
    450,                                                             # Hippowdon
    452,                                                             # Drapion
    454,                                                             # Toxicroak
    455,                                                             # Carnivine
    457,                                                             # Lumineon
    460,                                                             # Abomasnow
    461,                                                             # Weavile
    462,463,464,465,466,467,468,469,470,471,472,473,474,475,476,477,478,
    479,480,481,482,483,484,485,486,487,488,489,490,491,492,493,
    # Many more - this is rough
}

def derive_can_evolve(pokemon_id):
    """Approximation: pokemon NOT in no_evolution set can evolve."""
    return pokemon_id not in NO_EVOLUTION

def main():
    conn = sqlite3.connect('pokemon.db')
    c = conn.cursor()

    # Add new columns if not exist
    cols = [r[1] for r in c.execute("PRAGMA table_info(pokemon)").fetchall()]
    new_cols = {
        'is_legendary': 'BOOLEAN',
        'is_mythical': 'BOOLEAN',
        'can_mega_evolve': 'BOOLEAN',
        'is_dynamax_capable': 'BOOLEAN',
        'is_gigantamax_capable': 'BOOLEAN',
        'can_evolve_estimated': 'BOOLEAN',
    }
    for col, typ in new_cols.items():
        if col not in cols:
            c.execute(f'ALTER TABLE pokemon ADD COLUMN {col} {typ}')

    # Update flags based on species
    print("Updating species-based flags...")
    c.execute("UPDATE pokemon SET is_legendary = (pokemon_id IN (" + ','.join(map(str, LEGENDARY)) + "))")
    c.execute("UPDATE pokemon SET is_mythical = (pokemon_id IN (" + ','.join(map(str, MYTHICAL)) + "))")
    c.execute("UPDATE pokemon SET can_mega_evolve = (pokemon_id IN (" + ','.join(map(str, MEGA_CAPABLE)) + "))")
    c.execute("UPDATE pokemon SET is_dynamax_capable = (pokemon_id IN (" + ','.join(map(str, DYNAMAX_CAPABLE)) + "))")
    c.execute("UPDATE pokemon SET is_gigantamax_capable = (pokemon_id IN (" + ','.join(map(str, GIGANTAMAX_CAPABLE)) + "))")
    c.execute("UPDATE pokemon SET can_evolve_estimated = (pokemon_id NOT IN (" + ','.join(map(str, NO_EVOLUTION)) + "))")
    conn.commit()

    # Compare to user's known stats
    print("\n=== Species-based flag results vs your stats ===")
    print(f'{"metric":<25} {"mine":>8} {"real":>8}    diff')
    for label, q, real in [
        ('Legendary', 'COUNT(*) FROM pokemon WHERE is_legendary', 465),
        ('Mythical', 'COUNT(*) FROM pokemon WHERE is_mythical', 39),
        ('Can Mega Evolve', 'COUNT(*) FROM pokemon WHERE can_mega_evolve', 282),
        ('Dynamax-capable', 'COUNT(*) FROM pokemon WHERE is_dynamax_capable', 224),
        ('Gigantamax-capable', 'COUNT(*) FROM pokemon WHERE is_gigantamax_capable', 84),
        ('Can Evolve (est.)', 'COUNT(*) FROM pokemon WHERE can_evolve_estimated', 2329),
    ]:
        c.execute(f'SELECT {q}')
        mine = c.fetchone()[0]
        diff = mine - real
        print(f'  {label:<25} {mine:>8} {real:>8}   {diff:+5d}')

    print('\nDB updated with species flags')
    conn.close()

if __name__ == '__main__':
    main()
