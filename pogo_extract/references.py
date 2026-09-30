"""
Pokemon GO untouchable categories for the cull-rules engine.

Pokemon IDs are integers matching the HoloPokemonId enum (= national dex 1-1025).
Move IDs are integers matching the HoloPokemonMove enum (PvPMoveId in pogoapi).

Be CONSERVATIVE: when in doubt, include in LEGENDARY_IDS.

Sources cross-referenced:
  - Bulbapedia (legendary/mythical/UB/paradox classifications)
  - Serebii.net Mega Evolution list
  - p337.info legacy + exclusive moves
  - pogoapi.net move ID mappings
"""

# ---------------------------------------------------------------------------
# LEGENDARY POKEMON
# Box-art and trio legendaries across all generations.
# Includes: birds, beasts, weather/dragon trios, lake guardians, swords of
# justice, kami trio, tapus, cosmog line, treasures of ruin, and Gen 9 box arts.
# Excludes: mythicals (separate set), Ultra Beasts (separate set),
#           paradox pokemon (separate set).
# ---------------------------------------------------------------------------
LEGENDARY_IDS = {
    # Gen 1
    144,  # Articuno
    145,  # Zapdos
    146,  # Moltres
    150,  # Mewtwo
    # Gen 2
    243,  # Raikou
    244,  # Entei
    245,  # Suicune
    249,  # Lugia
    250,  # Ho-Oh
    # Gen 3
    377,  # Regirock
    378,  # Regice
    379,  # Registeel
    380,  # Latias
    381,  # Latios
    382,  # Kyogre
    383,  # Groudon
    384,  # Rayquaza
    # Gen 4
    480,  # Uxie
    481,  # Mesprit
    482,  # Azelf
    483,  # Dialga
    484,  # Palkia
    485,  # Heatran
    486,  # Regigigas
    487,  # Giratina
    488,  # Cresselia
    # Gen 5
    638,  # Cobalion
    639,  # Terrakion
    640,  # Virizion
    641,  # Tornadus
    642,  # Thundurus
    643,  # Reshiram
    644,  # Zekrom
    645,  # Landorus
    646,  # Kyurem
    # Gen 6
    716,  # Xerneas
    717,  # Yveltal
    718,  # Zygarde
    # Gen 7
    772,  # Type: Null
    773,  # Silvally
    785,  # Tapu Koko
    786,  # Tapu Lele
    787,  # Tapu Bulu
    788,  # Tapu Fini
    789,  # Cosmog
    790,  # Cosmoem
    791,  # Solgaleo
    792,  # Lunala
    800,  # Necrozma
    # Gen 8
    888,  # Zacian
    889,  # Zamazenta
    890,  # Eternatus
    891,  # Kubfu
    892,  # Urshifu
    894,  # Regieleki
    895,  # Regidrago
    896,  # Glastrier
    897,  # Spectrier
    898,  # Calyrex
    905,  # Enamorus
    # Gen 9 (box-art / treasures of ruin)
    1001, # Wo-Chien
    1002, # Chien-Pao
    1003, # Ting-Lu
    1004, # Chi-Yu
    1007, # Koraidon
    1008, # Miraidon
    1014, # Okidogi
    1015, # Munkidori
    1016, # Fezandipiti
    1017, # Ogerpon
    1024, # Terapagos
}

# ---------------------------------------------------------------------------
# MYTHICAL POKEMON
# One-per-region event-distribution Pokemon. Always rare; mostly limited to
# special research / paid event tickets in PoGO.
# ---------------------------------------------------------------------------
MYTHICAL_IDS = {
    151,   # Mew
    251,   # Celebi
    385,   # Jirachi
    386,   # Deoxys
    489,   # Phione
    490,   # Manaphy
    491,   # Darkrai
    492,   # Shaymin
    493,   # Arceus
    494,   # Victini
    647,   # Keldeo
    648,   # Meloetta
    649,   # Genesect
    719,   # Diancie
    720,   # Hoopa
    721,   # Volcanion
    801,   # Magearna
    802,   # Marshadow
    807,   # Zeraora
    808,   # Meltan
    809,   # Melmetal
    893,   # Zarude
    1025,  # Pecharunt
}

# ---------------------------------------------------------------------------
# ULTRA BEASTS
# Gen 7 inter-dimensional pseudo-legendary Pokemon. PoGO treats them with
# legendary-tier candy/distance and limited availability.
# ---------------------------------------------------------------------------
ULTRA_BEAST_IDS = {
    793,  # Nihilego
    794,  # Buzzwole
    795,  # Pheromosa
    796,  # Xurkitree
    797,  # Celesteela
    798,  # Kartana
    799,  # Guzzlord
    803,  # Poipole
    804,  # Naganadel
    805,  # Stakataka
    806,  # Blacephalon
}

# ---------------------------------------------------------------------------
# PARADOX POKEMON
# Gen 9 Ancient (Scarlet) and Future (Violet) paradox forms. Treated as
# legendary-tier in PoGO when introduced.
# ---------------------------------------------------------------------------
PARADOX_IDS = {
    # Ancient (Scarlet)
    984,  # Great Tusk
    985,  # Scream Tail
    986,  # Brute Bonnet
    987,  # Flutter Mane
    988,  # Slither Wing
    989,  # Sandy Shocks
    1005, # Roaring Moon
    1009, # Walking Wake
    1020, # Gouging Fire
    1021, # Raging Bolt
    # Future (Violet)
    990,  # Iron Treads
    991,  # Iron Bundle
    992,  # Iron Hands
    993,  # Iron Jugulis
    994,  # Iron Moth
    995,  # Iron Thorns
    1006, # Iron Valiant
    1010, # Iron Leaves
    1022, # Iron Boulder
    1023, # Iron Crown
}

# ---------------------------------------------------------------------------
# MEGA EVOLUTION
# Pokemon that have a Mega form available in Pokemon GO as of 2026.
# Source: serebii.net/pokemongo/megaevolution.shtml
# Note: this is the BASE species ID. The mega itself is represented via the
# `form` field, not a different pokemon_id. A Pokemon that *can* mega-evolve
# is usually worth keeping.
# ---------------------------------------------------------------------------
MEGA_EVOLUTION_IDS = {
    3,    # Venusaur
    6,    # Charizard (X and Y)
    9,    # Blastoise
    15,   # Beedrill
    18,   # Pidgeot
    26,   # Raichu (X and Y)
    36,   # Clefable
    65,   # Alakazam
    71,   # Victreebel
    80,   # Slowbro
    94,   # Gengar
    115,  # Kangaskhan
    121,  # Starmie
    127,  # Pinsir
    130,  # Gyarados
    142,  # Aerodactyl
    149,  # Dragonite
    150,  # Mewtwo (X and Y)
    154,  # Meganium
    160,  # Feraligatr
    181,  # Ampharos
    208,  # Steelix
    212,  # Scizor
    214,  # Heracross
    227,  # Skarmory
    229,  # Houndoom
    248,  # Tyranitar
    254,  # Sceptile
    257,  # Blaziken
    260,  # Swampert
    282,  # Gardevoir
    302,  # Sableye
    303,  # Mawile
    306,  # Aggron
    308,  # Medicham
    310,  # Manectric
    319,  # Sharpedo
    323,  # Camerupt
    334,  # Altaria
    354,  # Banette
    358,  # Chimecho
    359,  # Absol
    362,  # Glalie
    373,  # Salamence
    376,  # Metagross
    380,  # Latias
    381,  # Latios
    384,  # Rayquaza
    398,  # Staraptor
    428,  # Lopunny
    445,  # Garchomp
    448,  # Lucario
    460,  # Abomasnow
    475,  # Gallade
    478,  # Froslass
    485,  # Heatran
    491,  # Darkrai
    500,  # Emboar
    530,  # Excadrill
    531,  # Audino
    545,  # Scolipede
    560,  # Scrafty
    604,  # Eelektross
    609,  # Chandelure
    623,  # Golurk
    652,  # Chesnaught
    655,  # Delphox
    658,  # Greninja
    668,  # Pyroar
    670,  # Floette
    678,  # Meowstic
    687,  # Malamar
    689,  # Barbaracle
    691,  # Dragalge
    701,  # Hawlucha
    718,  # Zygarde
    719,  # Diancie
    740,  # Crabominable
    768,  # Golisopod
    780,  # Drampa
    801,  # Magearna
    807,  # Zeraora
    870,  # Falinks
    952,  # Scovillain
    970,  # Glimmora
    978,  # Tatsugiri
    998,  # Baxcalibur
}

# ---------------------------------------------------------------------------
# PRIMAL REVERSION
# Kyogre and Groudon have Primal forms. Distinct mechanic from Mega Evolution.
# In PoGO these are exclusive raid forms.
# ---------------------------------------------------------------------------
PRIMAL_FORMS = {
    382,  # Primal Kyogre
    383,  # Primal Groudon
}

# ---------------------------------------------------------------------------
# GIGANTAMAX / DYNAMAX
# Pokemon GO introduced Dynamax/Gigantamax via Max Battles (Gen 8 mechanic).
# As of 2026 the rotating Gmax raid roster includes the Galar starters,
# Toxtricity, and several legendaries. A Pokemon with a Gmax form should
# never be transferred.
# ---------------------------------------------------------------------------
GIGANTAMAX_FORMS = {
    3,    # Venusaur (Gmax)
    6,    # Charizard (Gmax)
    9,    # Blastoise (Gmax)
    12,   # Butterfree (Gmax)
    25,   # Pikachu (Gmax)
    52,   # Meowth (Gmax)
    68,   # Machamp (Gmax)
    94,   # Gengar (Gmax)
    99,   # Kingler (Gmax)
    131,  # Lapras (Gmax)
    133,  # Eevee (Gmax)
    143,  # Snorlax (Gmax)
    569,  # Garbodor (Gmax)
    812,  # Rillaboom (Gmax)
    815,  # Cinderace (Gmax)
    818,  # Inteleon (Gmax)
    823,  # Corviknight (Gmax)
    826,  # Orbeetle (Gmax)
    834,  # Drednaw (Gmax)
    839,  # Coalossal (Gmax)
    841,  # Flapple (Gmax)
    842,  # Appletun (Gmax)
    844,  # Sandaconda (Gmax)
    849,  # Toxtricity (Gmax)
    851,  # Centiskorch (Gmax)
    858,  # Hatterene (Gmax)
    861,  # Grimmsnarl (Gmax)
    869,  # Alcremie (Gmax)
    879,  # Copperajah (Gmax)
    884,  # Duraludon (Gmax)
    892,  # Urshifu (Gmax)
}

# ---------------------------------------------------------------------------
# ADVENTURE EFFECT
# Species whose signature move has the Adventure-Effect mechanic — chargeable
# out-of-battle use of the move for a stardust+candy cost. The mechanic is
# gated by FORM, not species; species IDs here are the Dex parent of any form
# that carries an Adventure Effect. (We key by species so the cull engine can
# protect the whole line; a per-form lookup would be more precise but the
# species-level guard is conservative.)
#
# Authoritative roster verified 2026-05-27. The 9 forms across 7 species are:
#   483 Dialga (Origin) — Roar of Time
#   484 Palkia (Origin) — Spacial Rend
#   646 Kyurem (Black, White) — Freeze Shock / Ice Burn
#   800 Necrozma (Dusk Mane, Dawn Wings) — Sunsteel Strike / Moongeist Beam
#   888 Zacian (Crowned Sword) — Behemoth Blade
#   889 Zamazenta (Crowned Shield) — Behemoth Bash
#   890 Eternatus — Dynamax Cannon (the only AE that stacks rather than replaces)
#
# Removed from earlier list (do NOT have Adventure Effects; remain protected via
# LEGENDARY_IDS): 480 Uxie, 481 Mesprit, 482 Azelf, 641/642/645 Therian trio,
# 898 Calyrex, 905 Enamorus, 1007 Koraidon, 1008 Miraidon.
# ---------------------------------------------------------------------------
ADVENTURE_EFFECT_IDS = {
    483,  # Dialga (Origin form)
    484,  # Palkia (Origin form)
    646,  # Kyurem (Black + White forms)
    800,  # Necrozma (Dusk Mane + Dawn Wings forms)
    888,  # Zacian (Crowned Sword form)
    889,  # Zamazenta (Crowned Shield form)
    890,  # Eternatus (Dynamax Cannon)
}

# ---------------------------------------------------------------------------
# LEGACY / EXCLUSIVE MOVES (move IDs)
# Moves that can NO LONGER be obtained on a current catch through normal
# moveset rolls. Available only via Elite TM, Community Day window, or events.
# A Pokemon possessing one of these in move1/move2/move3 is a collector item.
#
# Move IDs come from PoGOAPI pvp_fast_moves / pvp_charged_moves endpoints.
# ---------------------------------------------------------------------------

# Community-Day / event signature charged moves (universally legacy)
LEGACY_MOVE_IDS = {
    # Starter ultimate moves (CD-exclusive)
    296,  # FRENZY_PLANT
    298,  # BLAST_BURN
    299,  # HYDRO_CANNON
    # Pseudo-legendary signatures
    301,  # METEOR_MASH (Metagross CD)
    285,  # DRACO_METEOR (Dragonite, Salamence, etc. - CD/legacy)
    330,  # SACRED_SWORD (Cobalion CD)
    304,  # EARTH_POWER (Garchomp CD, Flygon CD)
    297,  # SMACK_DOWN (Tyranitar CD)
    # Box-legendary signatures
    335,  # AEROBLAST (Lugia)
    109,  # PSYSTRIKE (Mewtwo)
    289,  # ORIGIN_PULSE (Kyogre)
    290,  # PRECIPICE_BLADES (Groudon)
    394,  # ROAR_OF_TIME (Origin Dialga)
    388,  # SPACIAL_REND (Origin Palkia)
    371,  # SHADOW_FORCE (Giratina)
    366,  # MIST_BALL (Latias)
    365,  # LUSTER_PURGE (Latios)
    386,  # MAGMA_STORM (Heatran)
    378,  # GLACIATE (Kyurem)
    389,  # OBLIVION_WING (Yveltal)
    387,  # GEOMANCY (Xerneas)
    374,  # FUSION_BOLT (Zekrom)
    375,  # FUSION_FLARE (Reshiram)
    358,  # SACRED_FIRE (Ho-Oh)
    # Therian-Forme storms
    395,  # BLEAKWIND_STORM (Tornadus Therian)
    397,  # WILDBOLT_STORM (Thundurus Therian)
    396,  # SANDSEAR_STORM (Landorus Therian)
    # Tapu signature
    390,  # NATURES_MADNESS (Tapus)
    # Other notable legacy
    315,  # SHADOW_BONE (Alolan Marowak CD)
    381,  # DOUBLE_IRON_BASH (Melmetal CD)
    370,  # OBSTRUCT (Obstagoon CD)
    464,  # RAGE_FIST (Annihilape CD)
    379,  # BREAKING_SWIPE (Haxorus, Rayquaza CD)
    376,  # POLTERGEIST (Chandelure CD)
    367,  # BRUTAL_SWING (Hydreigon CD, Absol CD)
    # Frequently-rotated CD legacy moves
    300,  # LAST_RESORT (Eeveelutions CD)
    272,  # GRASS_KNOT (Pikachu CD, Cresselia)
    283,  # WATERFALL (legacy on multiple)
    287,  # YAWN (Snorlax CD)
    277,  # OUTRAGE (Salamence CD)
    284,  # SURF (Pikachu CD, Slowbro)
    273,  # ENERGY_BALL (Accelgor CD)
    275,  # FUTURE_SIGHT
    324,  # SYNCHRONOISE (Gardevoir/Gallade)
    332,  # AURA_SPHERE (Togekiss CD)
    334,  # ROCK_WRECKER (Rhyperior CD)
    353,  # PSYCHIC_FANGS (Luxray CD)
    372,  # METEOR_BEAM (Gigalith CD)
    377,  # HIGH_HORSEPOWER (Ursaluna CD)
    380,  # BOOMBURST (Noivern CD)
    408,  # HIGH_JUMP_KICK (Tsareena CD, Mienshao)
    359,  # ICICLE_SPEAR (Walrein CD)
    314,  # DRAIN_PUNCH (Bewear CD)
    310,  # SUPER_POWER (Flareon CD, Bidoof)
    318,  # RAZOR_SHELL (Escavalier CD, Samurott)
    321,  # GIGA_IMPACT
    346,  # INCINERATE (Talonflame CD)
    357,  # MAGICAL_LEAF (Celebi, Victreebel CD)
    364,  # ACROBATICS (Jumpluff CD)
}

# ---------------------------------------------------------------------------
# Species-specific legacy moves
# Maps pokemon_id -> set of move IDs that are legacy ONLY on this species.
# A move can be legacy on one species (e.g. Earth Power on Garchomp) yet
# legitimate on another (e.g. Earth Power on Flygon current). Use this dict
# when LEGACY_MOVE_IDS would have too many false positives.
#
# Format: { species_id: { move_id, move_id, ... } }
# ---------------------------------------------------------------------------
LEGACY_MOVES_BY_SPECIES = {
    # Gen 1
    25:  {272, 291, 284, 78, 387},                # Pikachu: Grass Knot, Present, Surf, Thunder, Volt Tackle
    26:  {78},                                    # Raichu: Thunder
    28:  {63},                                    # Sandshrew: Rock Tomb
    29:  {51},                                    # Sandslash: Night Slash
    34:  {200},                                   # Nidoking: Fury Cutter
    36:  {222},                                   # Clefable: Pound
    38:  {209, 103, 24},                          # Ninetales: Ember, Fire Blast, Flamethrower
    39:  {88, 131},                               # Jigglypuff: Play Rough, Body Slam
    52:  {131},                                   # Meowth: Body Slam
    53:  {51},                                    # Persian: Night Slash
    57:  {208, 28, 464},                          # Primeape: Karate Chop, Cross Chop, Rage Fist
    59:  {202, 95},                               # Arcanine: Bite, Bulldoze
    61:  {106},                                   # Poliwhirl: Scald
    62:  {243, 54},                               # Poliwrath: Counter, Submission
    65:  {243, 86, 108},                          # Alakazam: Counter, Dazzling Gleam, Psychic
    66:  {207},                                   # Machop: Low Kick
    67:  {28},                                    # Machoke: Cross Chop
    68:  {208, 32, 54, 333},                      # Machamp: Karate Chop, Stone Edge, Submission, Payback
    71:  {357},                                   # Victreebel: Magical Leaf
    78:  {209, 92},                               # Rapidash: Ember, Wild Charge
    80:  {284},                                   # Slowbro: Surf
    91:  {40},                                    # Cloyster: Blizzard
    94:  {212, 91, 16, 108, 67},                  # Gengar: Lick, Sludge Wave, Dark Pulse, Psychic, Shadow Punch
    97:  {60},                                    # Hypno: Psyshock
    99:  {216},                                   # Kingler: Mud Shot
    103: {234},                                   # Exeggutor: Zen Headbutt
    105: {315},                                   # Marowak (Alolan): Shadow Bone
    106: {127, 123},                              # Hitmonlee: Stomp, Brick Break
    107: {241, 123},                              # Hitmonchan: Rock Smash, Brick Break
    112: {22},                                    # Rhydon: Megahorn
    113: {30},                                    # Chansey: Psybeam
    114: {118},                                   # Tangela: Power Whip
    115: {123, 127},                              # Kangaskhan: Brick Break, Stomp
    117: {40},                                    # Seadra: Blizzard
    119: {89, 111, 46},                           # Seaking: Cross Poison, Icy Wind, Drill Run
    120: {219},                                   # Staryu: Quick Attack (legacy)
    121: {221, 219},                              # Starmie: Tackle, Quick Attack (legacy)
    123: {239, 49},                               # Scyther: Steel Wing, Bug Buzz
    124: {222, 33},                               # Jynx: Pound, Ice Punch
    127: {54},                                    # Pinsir: Submission
    130: {253, 82, 58},                           # Gyarados: Dragon Tail, Dragon Pulse, Aqua Tail
    131: {217, 82, 39},                           # Lapras: Ice Shard, Dragon Pulse, Ice Beam
    133: {300, 131},                              # Eevee: Last Resort, Body Slam
    134: {300, 106},                              # Vaporeon: Last Resort, Scald
    135: {300, 252},                              # Jolteon: Last Resort, Zap Cannon
    136: {300, 42, 310},                          # Flareon: Last Resort, Heat Wave, Super Power
    137: {221, 234, 99, 30, 35, 219},             # Porygon: Tackle, Zen Headbutt, Signal Beam, Psybeam, Discharge, Quick Attack
    138: {63, 104},                               # Omanyte: Rock Tomb, Brine
    139: {64},                                    # Omastar: Rock Slide
    141: {200},                                   # Kabutops: Fury Cutter
    143: {287},                                   # Snorlax: Yawn
    144: {122},                                   # Articuno: Hurricane
    145: {205},                                   # Zapdos: Thunder Shock
    146: {257},                                   # Moltres: Sky Attack
    149: {285, 82},                               # Dragonite: Draco Meteor, Dragon Pulse
    150: {109, 70, 14},                           # Mewtwo: Psystrike, Shadow Ball, Hyper Beam
    # Gen 2
    154: {296},                                   # Meganium: Frenzy Plant
    157: {298},                                   # Typhlosion: Blast Burn
    160: {230, 299},                              # Feraligatr: Water Gun, Hydro Cannon
    172: {219},                                   # Pichu: Quick Attack (legacy)
    173: {108, 131},                              # Cleffa: Psychic, Body Slam
    174: {131},                                   # Igglybuff: Body Slam
    175: {234},                                   # Togepi: Zen Headbutt
    176: {239, 234},                              # Togetic: Steel Wing, Zen Headbutt
    181: {82},                                    # Ampharos: Dragon Pulse
    186: {31, 39},                                # Politoed: Earthquake, Ice Beam
    189: {364},                                   # Jumpluff: Acrobatics
    195: {58},                                    # Quagsire: Aqua Tail
    196: {300, 70},                               # Espeon: Last Resort, Shadow Ball
    197: {300, 108},                              # Umbreon: Last Resort, Psychic
    199: {284},                                   # Slowking: Surf
    230: {230},                                   # Kingdra: Water Gun
    238: {218},                                   # Smoochum: Frost Breath
    239: {79},                                    # Elekid: Thunderbolt
    240: {24},                                    # Magby: Flamethrower
    242: {92},                                    # Blissey: Wild Charge
    245: {281},                                   # Suicune: Hidden Power (legacy)
    248: {297},                                   # Tyranitar: Smack Down
    249: {335},                                   # Lugia: Aeroblast
    250: {31, 358},                               # Ho-Oh: Earthquake, Sacred Fire
    251: {357},                                   # Celebi: Magical Leaf
    # Gen 3
    254: {296},                                   # Sceptile: Frenzy Plant
    257: {298, 32},                               # Blaziken: Blast Burn, Stone Edge
    260: {299},                                   # Swampert: Hydro Cannon
    275: {271},                                   # Shiftry: Bullet Seed
    282: {324},                                   # Gardevoir: Synchronoise
    286: {272},                                   # Breloom: Grass Knot
    289: {131},                                   # Slaking: Body Slam
    292: {202},                                   # Shedinja: Bite (legacy)
    330: {304},                                   # Flygon: Earth Power
    334: {87},                                    # Altaria: Moonblast
    359: {367},                                   # Absol: Brutal Swing
    365: {59, 359},                               # Walrein: Powder Snow, Icicle Spear (Powder Snow id approx)
    373: {277},                                   # Salamence: Outrage
    376: {301},                                   # Metagross: Meteor Mash
    377: {31},                                    # Regirock: Earthquake
    378: {78},                                    # Regice: Thunder
    379: {252},                                   # Registeel: Zap Cannon
    380: {366},                                   # Latias: Mist Ball
    381: {365},                                   # Latios: Luster Purge
    382: {289},                                   # Kyogre: Origin Pulse
    383: {115, 290},                              # Groudon: Fire Punch, Precipice Blades
    384: {122, 379},                              # Rayquaza: Hurricane, Breaking Swipe
    # Gen 4
    389: {296},                                   # Torterra: Frenzy Plant
    392: {298},                                   # Infernape: Blast Burn
    395: {299},                                   # Empoleon: Hydro Cannon
    398: {345},                                   # Staraptor: Gust
    400: {70, 79, 39, 310},                       # Bidoof: Shadow Ball, Thunderbolt, Ice Beam, Super Power
    405: {353},                                   # Luxray: Psychic Fangs
    407: {271, 292},                              # Roserade: Bullet Seed, Weather Ball Fire
    445: {304},                                   # Garchomp: Earth Power
    448: {462},                                   # Lucario: Force Palm
    463: {131},                                   # Lickilicky: Body Slam
    464: {334},                                   # Rhyperior: Rock Wrecker
    466: {24},                                    # Electivire: Flamethrower
    467: {79},                                    # Magmortar: Thunderbolt
    468: {332},                                   # Togekiss: Aura Sphere
    470: {271, 300},                              # Leafeon: Bullet Seed, Last Resort
    471: {300, 105},                              # Glaceon: Last Resort, Water Pulse
    473: {62},                                    # Mamoswine: Ancient Power
    474: {344},                                   # Porygon-Z: Tri Attack
    475: {324},                                   # Gallade: Synchronoise
    477: {70},                                    # Dusknoir: Shadow Ball
    485: {386},                                   # Heatran: Magma Storm
    487: {371},                                   # Giratina: Shadow Force
    488: {272},                                   # Cresselia: Grass Knot
    491: {90},                                    # Darkrai: Sludge Bomb
    # Gen 5
    497: {296},                                   # Serperior: Frenzy Plant
    500: {298},                                   # Emboar: Blast Burn
    503: {299},                                   # Samurott: Hydro Cannon
    526: {372},                                   # Gigalith: Meteor Beam
    534: {367},                                   # Conkeldurr: Brutal Swing
    542: {213},                                   # Leavanny: Shadow Claw
    584: {254},                                   # Vanilluxe: Avalanche
    589: {318},                                   # Escavalier: Razor Shell
    604: {250},                                   # Eelektross: Volt Switch
    609: {376},                                   # Chandelure: Poltergeist
    612: {379},                                   # Haxorus: Breaking Swipe
    617: {273},                                   # Accelgor: Energy Ball
    619: {408},                                   # Mienfoo: High Jump Kick
    635: {367},                                   # Hydreigon: Brutal Swing
    638: {330},                                   # Cobalion: Sacred Sword
    639: {330},                                   # Terrakion: Sacred Sword
    640: {330},                                   # Virizion: Sacred Sword
    641: {395},                                   # Tornadus: Bleakwind Storm
    642: {397},                                   # Thundurus: Wildbolt Storm
    643: {375},                                   # Reshiram: Fusion Flare
    644: {374},                                   # Zekrom: Fusion Bolt
    645: {396},                                   # Landorus: Sandsear Storm
    646: {378},                                   # Kyurem: Glaciate
    # Gen 6
    652: {296},                                   # Chesnaught: Frenzy Plant
    655: {298},                                   # Delphox: Blast Burn
    658: {299},                                   # Greninja: Hydro Cannon
    663: {346},                                   # Talonflame: Incinerate
    700: {300, 60},                               # Sylveon: Last Resort, Psyshock
    706: {77},                                    # Goodra: Thunder Punch
    715: {380},                                   # Noivern: Boomburst
    716: {387},                                   # Xerneas: Geomancy
    717: {389},                                   # Yveltal: Oblivion Wing
    # Gen 7
    724: {296},                                   # Decidueye: Frenzy Plant
    727: {298},                                   # Incineroar: Blast Burn
    730: {299},                                   # Primarina: Hydro Cannon
    737: {250},                                   # Charjabug: Volt Switch
    738: {250},                                   # Vikavolt: Volt Switch
    760: {314},                                   # Bewear: Drain Punch
    763: {408},                                   # Tsareena: High Jump Kick
    785: {390},                                   # Tapu Koko: Nature's Madness
    786: {390},                                   # Tapu Lele: Nature's Madness
    787: {390},                                   # Tapu Bulu: Nature's Madness
    788: {390},                                   # Tapu Fini: Nature's Madness
    809: {381},                                   # Melmetal: Double Iron Bash
    # Gen 8
    823: {74},                                    # Corviknight: Iron Head
    862: {370},                                   # Obstagoon: Obstruct
    901: {377},                                   # Ursaluna: High Horsepower
    # Gen 9
    908: {296},                                   # Meowscarada: Frenzy Plant
    911: {298},                                   # Skeledirge: Blast Burn
    916: {233},                                   # Oinkologne: Mud-Slap (CD 2026-05-09; fast move)
    923: {123},                                   # Pawmot: Brick Break
    959: {494},                                   # Tinkaton: Gigaton Hammer (CD 2026-04-11)
    979: {464},                                   # Annihilape: Rage Fist
    980: {22},                                    # Clodsire: Megahorn
}


# Convenience union: any pokemon belonging to any "untouchable" category.
# Use as the primary cull-rules veto: if pokemon_id in UNTOUCHABLE_IDS -> skip.
UNTOUCHABLE_IDS = (
    LEGENDARY_IDS
    | MYTHICAL_IDS
    | ULTRA_BEAST_IDS
    | PARADOX_IDS
    | MEGA_EVOLUTION_IDS
    | PRIMAL_FORMS
    | GIGANTAMAX_FORMS
    | ADVENTURE_EFFECT_IDS
)


def has_legacy_move(pokemon_id: int, moves: list[int]) -> bool:
    """Return True if any of the moves are legacy on this species."""
    if not moves:
        return False
    move_set = {m for m in moves if m is not None}
    # Universal legacy / community-day exclusive
    if move_set & LEGACY_MOVE_IDS:
        return True
    # Species-specific legacy
    species_legacy = LEGACY_MOVES_BY_SPECIES.get(pokemon_id, set())
    if move_set & species_legacy:
        return True
    return False
