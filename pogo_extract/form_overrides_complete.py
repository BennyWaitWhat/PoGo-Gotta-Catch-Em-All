"""Comprehensive (species_name, form_code) -> PvPoke speciesId mapping.

Built from pokemon.db (in_bag=1) cross-checked against pvpoke_gamemaster.json.

Resolution rules used:
  1. Explicit (species_name, form_code) override below.
  2. form_code == 0 -> base PvPoke id (lowercased species_name with normalization).
  3. form_code != 0 but species has only one PvPoke variant -> base PvPoke id
     (PoGo uses unique form codes per species even when there is no real form variant).
  4. species_name starts with 'pid<dex>' -> resolve via PvPoke dex.

Every distinct (species_name, form) combo in the user's bag resolves cleanly, and the
resolution is PROVEN, not asserted: run `python form_overrides_complete.py` (or call
certify()) to re-derive the whole table from two independent ground truths -- the game's
own Form enum and the game's own stored CP+HP -- and fail loudly on any disagreement.
Costume codes do not change PvP stats, so the form_code lookup applies to them too; but a
COSTUMED code on a REGIONAL form still needs its own key (see D2, Corsola 3339).

Costume codes (non-zero fresh_costume) use the same PvPoke speciesId as the
matching (species_name, form_code) since costumes do not affect PvP stats.

To use:
    pvpoke_id = FORM_OVERRIDES.get((species_name, form_code))
    if pvpoke_id is None:
        pvpoke_id = species_name.lower().replace(' ', '_').replace("'", '') \
            .replace('.', '').replace('-', '_').replace('é', 'e')
"""

FORM_OVERRIDES = {
    # ---- Alolan forms (Gen 1 form codes) ----
    ('Rattata', 46): 'rattata_alolan',
    ('Raticate', 48): 'raticate_alolan',
    ('Raichu', 50): 'raichu_alolan',
    ('Sandshrew', 52): 'sandshrew_alolan',
    ('Sandslash', 54): 'sandslash_alolan',
    ('Vulpix', 56): 'vulpix_alolan',
    ('Ninetales', 58): 'ninetales_alolan',
    ('Diglett', 60): 'diglett_alolan',
    ('Dugtrio', 62): 'dugtrio_alolan',
    ('Meowth', 64): 'meowth_alolan',
    ('Persian', 66): 'persian_alolan',
    ('Geodude', 68): 'geodude_alolan',
    ('Graveler', 70): 'graveler_alolan',
    ('Golem', 72): 'golem_alolan',
    ('Grimer', 74): 'grimer_alolan',
    ('Muk', 76): 'muk_alolan',
    ('Exeggutor', 78): 'exeggutor_alolan',
    ('Marowak', 80): 'marowak_alolan',

    # ---- Galarian forms ----
    ('Weezing', 944): 'weezing_galarian',
    ('Zigzagoon', 946): 'zigzagoon_galarian',
    ('Linoone', 948): 'linoone_galarian',
    ('Meowth', 2335): 'meowth_galarian',
    ('Ponyta', 2336): 'ponyta_galarian',
    ('Rapidash', 2337): 'rapidash_galarian',
    ("Farfetch'd", 2338): 'farfetchd_galarian',
    ('Mr. Mime', 2339): 'mr_mime_galarian',
    ('Corsola', 2340): 'corsola_galarian',
    # AUDIT 2026-09-07 (D2) -- COSTUME-ON-A-REGIONAL-FORM TRAP. form_enum.json says
    # 3339='CorsolaSpring2026'; the name carries the costume, not the region, so the
    # key was missing entirely and the 3 rows fell through to Kantonian 'corsola'
    # (118/156/146). Their stored cp AND stamina reproduce ONLY under
    # 'corsola_galarian' (116/182/155) -- 3/3 vs 0/3. UNDER-KEEP direction: Galarian
    # is the bulkier line and the one that evolves to Cursola. A costumed form code is
    # NOT automatically the base region -- always CP-check it.
    ('Corsola', 3339): 'corsola_galarian',
    ('Darumaka', 2341): 'darumaka_galarian',
    ('Darmanitan', 2342): 'darmanitan_galarian_standard',
    ('Yamask', 2344): 'yamask_galarian',
    ('Stunfisk', 2345): 'stunfisk_galarian',
    ('Slowpoke', 2582): 'slowpoke_galarian',
    ('Slowbro', 2583): 'slowbro_galarian',
    ('Slowking', 2584): 'slowking_galarian',
    # AUDIT 2026-09-07 (D3) -- form_enum.json says 2734='Slowking2022', an event
    # re-release label that names no region. The 2026-09-03 audit left it on
    # slowking_galarian because no bag row carried form 2734 then. Rows exist now, and
    # their stored cp AND stamina reproduce ONLY under plain 'slowking' (177/180/216),
    # never under 'slowking_galarian' (190/180/216) -- 2/2 vs 0/2. Now settled.
    ('Slowking', 2734): 'slowking',
    ('Articuno', 2801): 'articuno_galarian',
    ('Zapdos', 2800): 'zapdos_galarian',
    ('Moltres', 2799): 'moltres_galarian',

    # ---- Hisuian forms ----
    ('Decidueye', 2785): 'decidueye_hisuian',
    ('Typhlosion', 2786): 'typhlosion_hisuian',
    ('Samurott', 2787): 'samurott_hisuian',
    ('Qwilfish', 2788): 'qwilfish_hisuian',
    ('Lilligant', 2789): 'lilligant_hisuian',
    ('Growlithe', 2792): 'growlithe_hisuian',
    ('Arcanine', 2793): 'arcanine_hisuian',
    ('Sneasel', 2794): 'sneasel_hisuian',
    ('Avalugg', 2795): 'avalugg_hisuian',
    ('Zorua', 2796): 'zorua_hisuian',
    ('Zoroark', 2797): 'zoroark_hisuian',
    ('Braviary', 2798): 'braviary_hisuian',
    ('Voltorb', 2728): 'voltorb_hisuian',
    ('Electrode', 2735): 'electrode_hisuian',
    ('Basculin', 2804): 'basculin',  # PvPoke has only one Basculin (white-striped collapsed)

    # ---- Paldean forms ----
    ('Wooper', 3009): 'wooper_paldean',
    # Tauros -- enum: 1086=TaurosNormal (the KANTONIAN bull, not Paldean!),
    # 3006=PaldeaCombat 3007=PaldeaBlaze 3008=PaldeaAqua. The old table mapped
    # 1086->tauros_combat (9 bag mons ranked as Paldean Combat 210/193/181 when CP proves
    # they are plain tauros 198/183/181), had NO entry for 3006 (1 mon fell through to
    # base 'tauros' when it is Paldean Combat), and mapped 3008->tauros_blaze. The three
    # Paldean breeds share one stat line, so 3008 is a labeling fix only.
    ('Tauros', 1086): 'tauros',
    ('Tauros', 3006): 'tauros_combat',
    ('Tauros', 3007): 'tauros_blaze',
    ('Tauros', 3008): 'tauros_aqua',

    # ---- Multi-form species (PvPoke has variants per form) ----
    # Burmy cloaks
    ('Burmy', 118): 'burmy_plant',
    ('Burmy', 119): 'burmy_sandy',
    ('Burmy', 120): 'burmy_trash',
    # Wormadam cloaks
    ('Wormadam', 87): 'wormadam_plant',
    ('Wormadam', 88): 'wormadam_sandy',
    ('Wormadam', 89): 'wormadam_trash',
    # Castform weather -- enum: 29=Normal 30=Sunny 31=Rainy 32=Snowy. The old table was
    # shifted one slot (29->sunny, 30->rainy, 31->snowy, no 32). All four Castform entries
    # share atk139/def139/hp172, so this is a pure labeling fix with no rank effect.
    ('Castform', 29): 'castform',
    ('Castform', 30): 'castform_sunny',
    ('Castform', 31): 'castform_rainy',
    ('Castform', 32): 'castform_snowy',
    # Cherrim
    ('Cherrim', 94): 'cherrim_overcast',
    ('Cherrim', 95): 'cherrim_sunny',
    # Deoxys
    ('Deoxys', 33): 'deoxys',
    ('Deoxys', 34): 'deoxys_attack',
    ('Deoxys', 35): 'deoxys_defense',
    ('Deoxys', 36): 'deoxys_speed',
    # Rotom -- form codes verified 2026-09-03 against the IL2CPP Form enum (form_enum.json)
    # AND stored CP: 81=Normal 82=Frost 83=Fan 84=Mow 85=Wash 86=Heat.
    # Was: 81->rotom_heat, 83->rotom_frost, and NO entry for 85=Wash (10 bag mons) which
    # fell through to base 'rotom'. Base rotom is atk185/def159/hp137 while every appliance
    # form is atk204/def219/hp137, so form 81 and the 10 Wash mons were ranked on the wrong
    # stat line. (The five appliance forms share one stat line, so 82/83/84/86 are labeling.)
    ('Rotom', 81): 'rotom',
    ('Rotom', 82): 'rotom_frost',
    ('Rotom', 83): 'rotom_fan',
    ('Rotom', 84): 'rotom_mow',
    ('Rotom', 85): 'rotom_wash',
    ('Rotom', 86): 'rotom_heat',
    # Giratina
    ('Giratina', 90): 'giratina_altered',
    ('Giratina', 91): 'giratina_origin',
    # Shaymin -- enum: 92=Sky, 93=Land (the old table had these SWAPPED). CP confirms the
    # single bag mon on form 92 is Sky (atk261/def166) not Land (atk210/def210).
    ('Shaymin', 92): 'shaymin_sky',
    ('Shaymin', 93): 'shaymin_land',
    # Genesect drives
    # enum: 593=Normal 594=Shock 595=Burn 596=Chill 597=Douse. The old table was rotated by
    # one drive. All five Genesect entries share atk252/def199/hp174, so labeling only.
    ('Genesect', 593): 'genesect',
    ('Genesect', 594): 'genesect_shock',
    ('Genesect', 595): 'genesect_burn',
    ('Genesect', 596): 'genesect_chill',
    ('Genesect', 597): 'genesect_douse',
    # Tornadus / Thundurus / Landorus / Enamorus
    ('Tornadus', 140): 'tornadus_incarnate',
    ('Tornadus', 141): 'tornadus_therian',
    ('Thundurus', 142): 'thundurus_incarnate',
    ('Thundurus', 143): 'thundurus_therian',
    ('Landorus', 144): 'landorus_incarnate',
    ('Landorus', 145): 'landorus_therian',
    ('Enamorus', 2802): 'enamorus_incarnate',
    ('Enamorus', 2803): 'enamorus_therian',
    # Kyurem
    # enum: 146=Normal 147=Black 148=White (the old table had 147/148 SWAPPED). Black and
    # White share atk310/def183/hp245 in the gamemaster, so labeling only, no rank effect.
    ('Kyurem', 146): 'kyurem',
    ('Kyurem', 147): 'kyurem_black',
    ('Kyurem', 148): 'kyurem_white',
    # Keldeo / Meloetta
    ('Keldeo', 149): 'keldeo_ordinary',
    ('Keldeo', 150): 'keldeo_resolute',
    ('Meloetta', 151): 'meloetta_aria',
    ('Meloetta', 152): 'meloetta_pirouette',
    # Pumpkaboo / Gourgeist sizes
    # enum: 2641=Small 2642=Average (the old table had these two SWAPPED; 2643=Large and
    # 2644=Super were already right). Every size has its own stat line, so the 8 bag mons
    # on 2641/2642 were mis-ranked. CP confirms the enum on each.
    ('Pumpkaboo', 2641): 'pumpkaboo_small',
    ('Pumpkaboo', 2642): 'pumpkaboo_average',
    ('Pumpkaboo', 2643): 'pumpkaboo_large',
    ('Pumpkaboo', 2644): 'pumpkaboo_super',
    # enum: 2645=Small 2646=Average (same SWAP as Pumpkaboo above; 2647/2648 were right).
    ('Gourgeist', 2645): 'gourgeist_small',
    ('Gourgeist', 2646): 'gourgeist_average',
    ('Gourgeist', 2647): 'gourgeist_large',
    ('Gourgeist', 2648): 'gourgeist_super',
    # Hoopa
    ('Hoopa', 2651): 'hoopa_confined',
    ('Hoopa', 2652): 'hoopa_unbound',
    # Necrozma / Mimikyu
    ('Necrozma', 2717): 'necrozma',
    ('Mimikyu', 2716): 'mimikyu',
    # Lycanroc
    # enum: 2684=Midday 2685=Midnight 2686=Dusk. The old table was rotated by one
    # (2684->midnight, 2685->dusk, 2686->midday). All three stat lines DIFFER
    # (midday 231/140/181, midnight 218/152/198, dusk 234/139/181), so the 6 bag mons
    # here were genuinely mis-ranked. CP on every one of them confirms the enum order.
    ('Lycanroc', 2684): 'lycanroc_midday',
    ('Lycanroc', 2685): 'lycanroc_midnight',
    ('Lycanroc', 2686): 'lycanroc_dusk',
    # Oricorio
    ('Oricorio', 2679): 'oricorio_baile',
    ('Oricorio', 2680): 'oricorio_pom_pom',
    ('Oricorio', 2681): 'oricorio_pau',
    ('Oricorio', 2683): 'oricorio_sensu',
    # Toxtricity
    # enum: 2463=LowKey 2464=Amped (the old table had these SWAPPED). Both share
    # atk224/def140/hp181, so labeling only, no rank effect.
    ('Toxtricity', 2463): 'toxtricity_low_key',
    ('Toxtricity', 2464): 'toxtricity_amped',
    # Indeedee / Morpeko
    ('Indeedee', 2542): 'indeedee_male',
    ('Indeedee', 2543): 'indeedee_female',
    ('Morpeko', 2544): 'morpeko_full_belly',
    ('Morpeko', 2545): 'morpeko_hangry',  # enum MorpekoHangry; not in bag today, but the
    # pair's other half was missing exactly the way Enamorus 2803 was. Same stat line.
    # Urshifu
    ('Urshifu', 2723): 'urshifu_single_strike',
    ('Urshifu', 2724): 'urshifu_rapid_strike',
    # Zacian / Zamazenta
    # enum: 2576=ZacianCrownedSword 2577=ZacianHero, 2578=ZamazentaCrownedShield
    # 2579=ZamazentaHero. The old table had BOTH pairs SWAPPED. This was the single
    # largest mis-ranking in the table: 32 bag mons (16 Zacian + 16 Zamazenta) were
    # ranked against the wrong stat line -- zacian_hero 254/236/192 vs
    # zacian_crowned_sword 332/240/192, zamazenta_hero 254/236/192 vs
    # zamazenta_crowned_shield 250/292/192. Stored CP confirms the enum on all 32.
    ('Zacian', 2576): 'zacian_crowned_sword',
    ('Zacian', 2577): 'zacian_hero',
    ('Zamazenta', 2578): 'zamazenta_crowned_shield',
    ('Zamazenta', 2579): 'zamazenta_hero',
    # Aegislash / Eternatus / Zygarde / Maushold
    ('Aegislash', 2639): 'aegislash_shield',
    ('Eternatus', 2581): 'eternatus',
    ('Zygarde', 2592): 'zygarde',
    ('Zygarde', 2591): 'zygarde_10',          # ZygardeTenPercent (2026-09-26: new account's 10% Forme read as 50%)
    ('Zygarde', 2593): 'zygarde_complete',    # ZygardeComplete
    ('Zygarde', 2823): 'zygarde_complete',    # ZygardeCompleteTenPercent -- Complete stats
    ('Zygarde', 2824): 'zygarde_complete',    # ZygardeCompleteFiftyPercent -- Complete stats
    ('Maushold', 2984): 'maushold',
    # Tatsugiri
    ('Tatsugiri', 2991): 'tatsugiri_curly',
    ('Tatsugiri', 2992): 'tatsugiri_droopy',
    ('Tatsugiri', 2993): 'tatsugiri_stretchy',
    # Oinkologne / Meowstic gender
    ('Oinkologne', 2981): 'oinkologne',
    ('Oinkologne', 2982): 'oinkologne_female',
    ('Meowstic', 2589): 'meowstic',
    ('Meowstic', 2590): 'meowstic_female',
    # Dialga / Palkia origin
    ('Dialga', 2829): 'dialga_origin',
    ('Palkia', 2830): 'palkia_origin',
    # Mewtwo Armored / Darmanitan Standard
    # AUDIT 2026-09-07 (D1) -- THESE TWO KEYS WERE BACKWARDS AND COST 160 ROWS THEIR
    # REAL PvP RANKS. form_enum.json: 133='MewtwoA' (Armored, 182/278/214),
    # 135='MewtwoNormal' (300/182/214). There was NO ('Mewtwo', 133) key at all, so
    # every real Armored Mewtwo fell through rule 2 to plain 'mewtwo', while the 46
    # plain Mewtwo were ranked on the Armored stat line. Settled by CP+HP
    # reconstruction against the live bag: all 114 rows on form 133 reproduce their
    # stored cp AND stamina ONLY under 'mewtwo_armored', all 46 rows on form 135 ONLY
    # under 'mewtwo'. Anchor: Armored 12/15/13 -> UL rank 1108/4096 (96.88%).
    ('Mewtwo', 133): 'mewtwo_armored',
    ('Mewtwo', 135): 'mewtwo',
    ('Darmanitan', 138): 'darmanitan_standard',

    # ---- Special name normalization (PvPoke uses _female / _male, DB uses 'F'/'M') ----
    ('Nidoran F', 0): 'nidoran_female',
    ('Nidoran F', 776): 'nidoran_female',
    ('Nidoran M', 0): 'nidoran_male',
    ('Nidoran M', 776): 'nidoran_male',
    # Flabébé (DB stores as Latin-1 bytes 0x46 0x6c 0x61 0x62 0xe9 0x62 0xe9)
    ('Flabébé', 0): 'flabebe',
    ('Flabébé', 2614): 'flabebe',
    ('Flabébé', 2615): 'flabebe',
    ('Flabébé', 2616): 'flabebe',
    ('Flabébé', 2617): 'flabebe',
    ('Flabébé', 2618): 'flabebe',

    # ---- Parser-garbage form codes (very large numbers from corrupted parses) ----
    # These rows have form > 1_000_000 with non-zero costume/current_temp_evolution.
    # The fresh_form column in the DB has the real form (or 0). Map to base species
    # since they cannot be reliably attributed to a specific form variant.
    ('Zacian', 6553715): 'zacian_crowned_sword',  # fresh_form=2577
    ('Camerupt', 1950495077): 'camerupt',
    ('Pidgeot', 7471201): 'pidgeot',
    ('Abra', 963335219): 'abra',
    ('Popplio', 961374028): 'popplio',
    ('Scyther', 1734620280): 'scyther',
    ('Clamperl', 1463104305): 'clamperl',

    # ---- Pokemon with parser-failed name resolution (species_name = 'pid<dex>') ----
    # The species_name was not resolved during parsing but pokemon_id encodes the dex.
    ('pid70', 667): 'weepinbell',
    ('pid857', 3191): 'hattrem',
}


# ---- Audit 2026-09-03 ----
# The whole table was re-audited against TWO independent ground truths instead of the
# form-code guesswork the notes below used to rely on:
#   (1) form_enum.json -- the game's own IL2CPP Form enum, so the authority on what a
#       form code MEANS. Anchor-checked (46=RattataAlola ... 80=MarowakAlola) before use.
#   (2) stored CP. CP is a pure function of base stats + IVs + CPM, so recomputing it per
#       candidate speciesId and comparing to the DB's cp column identifies which stat line
#       a mon actually has. This is what settles a pair the enum alone could not.
# Both agreed everywhere they overlapped. Results:
#   - Every one of the 168 mapped speciesIds exists in pvpoke_gamemaster.json.
#   - Every distinct (species_name, form) combo in the live bag now resolves.
#   - 9 groups were wrong and are corrected in place above, each with its own comment:
#       Enamorus 2803 (was missing entirely -- the reported bug), Zacian 2576/2577 and
#       Zamazenta 2578/2579 (both pairs swapped, 32 mons), Lycanroc 2684/2685/2686
#       (rotated, 6 mons), Pumpkaboo 2641/2642 and Gourgeist 2645/2646 (swapped, 15 mons),
#       Rotom 81 + missing 85=Wash (11 mons), Tauros 1086 + missing 3006 (10 mons),
#       Shaymin 92/93 (swapped, 1 mon). Castform, Genesect, Kyurem and Toxtricity were
#       also mislabeled but their variants share a stat line, so those cost no ranks.
#
# Resolved by the audit (these were open questions in the old notes; all now CONFIRMED
# CORRECT as they stand, do not "fix" them):
#   - ('Avalugg', 2812): enum says AvaluggNormal -- the fallthrough to base 'avalugg' is
#       right. It is not a stray or Hisuian code.
#   - ('Decidueye', 2809): enum says DecidueyeNormal -- fallthrough to 'decidueye' is right.
#   - ('Indeedee', 2542/2543), ('Oinkologne', 2981/2982), ('Meowstic', 2589/2590): the
#       male-first assumption was correct; enum confirms.
#   - ('Cherrim', 94/95), ('Burmy', 118/119/120), ('Wormadam', 87/88/89), ('Deoxys',
#       33-36), ('Oricorio', 2679-2683), ('Tatsugiri', 2991-2993), ('Urshifu',
#       2723/2724), ('Hoopa', 2651/2652), ('Keldeo', 149/150), ('Meloetta', 151/152),
#       ('Pumpkaboo'/'Gourgeist' Large+Super): all confirmed correct.
#
# Still open -- do NOT guess these:
#   - ('Slowking', 2734): CLOSED 2026-09-07, see D3 above. Bag rows on this form now
#       exist and CP+HP reconstruction settles it as plain 'slowking'.
#   - The 7 parser-garbage keys (form > 1_000_000: Zacian 6553715, Camerupt, Pidgeot,
#       Abra, Popplio, Scyther, Clamperl) and ('pid70', 667) / ('pid857', 3191): no bag row
#       uses any of them, so they are inert. Note that Zacian 6553715's comment says
#       fresh_form=2577, which under the corrected mapping now means HERO, not Crowned
#       Sword -- its value is left as-is because the row is a corrupted parse that cannot
#       be CP-verified. If such a row ever reappears, re-derive it, do not trust the entry.


# ==================================================================================================
# SELF-CHECK GUARD -- `python form_overrides_complete.py`  /  certify()
# ==================================================================================================
# WHY THIS EXISTS. A wrong entry in the table above is SILENT. It does not raise, it does not
# produce an unknown species, it does not show up in any tally: it just feeds the ranker a
# DIFFERENT pokemon's base stats, and every PvP rank computed from that point on is confidently
# wrong. That is how 114 Armored Mewtwo were ranked as plain Mewtwo and 46 plain Mewtwo were
# ranked as Armored for as long as the ('Mewtwo', 135) key existed (D1, 2026-09-07), and how a
# Mudbray whose species failed to parse produced NULL ranks that were read as "no PvP protection"
# instead of "unknown -> protect" -- its true rank was GREAT LEAGUE #2 of 4096 and it is gone.
#
# The table therefore may not be trusted because a human wrote a plausible-looking line in it. It
# has to be RE-DERIVED from ground truth on demand, which is what certify() does:
#
#   GT1  pvpoke_gamemaster.json -- every speciesId this table maps TO must exist there. A typo
#        maps a mon to nothing; the ranker then NULLs its ranks (safe) but the mapping is still
#        a lie and the next reader "fixes" it by guessing.
#   GT2  form_enum.json -- the game's own Form enum, so the authority on what a form code MEANS.
#        Used for the two structural checks a human is most likely to get backwards:
#          * a code whose enum name ends in 'Normal' must NOT map to a variant speciesId
#            (this is exactly D1: 135='MewtwoNormal' was mapped to 'mewtwo_armored'), and
#          * a code whose enum name carries a region token must map to that region, and vice
#            versa. ADVISORY ONLY in the second direction, because a costume label replaces the
#            region in the enum name -- 3339='CorsolaSpring2026' IS Galarian (that is D2, the
#            costume-on-a-regional-form trap). Never "fix" a mapping on the enum name alone.
#   GT3  the bag's own stored cp AND stamina -- the decisive test. CP and HP are pure functions
#        of base stats + IVs + CPM, so recomputing them per candidate speciesId identifies which
#        stat line a mon ACTUALLY has. This is what settles a pair the enum cannot.
#
# GT3 is deliberately LEVEL-FREE: it asks whether SOME level reproduces the stored cp and the
# stored stamina together, not whether the level column does. Several bag rows carry a stale
# cp_multiplier / stamina relative to cp (the mon was powered up between proto reads), and a few
# carry the best-buddy CP boost or a mega form's CP; pinning the level from a column turns all of
# those into false failures. A row that cannot be reconstructed at ANY level, while some OTHER
# stat line reconstructs it, is a mapping error -- that is the finding this guard is for.
#
# CPM: borrowed from the LIVE ranker (system/scripts/rank_cache.py), never redefined here.
# Certifying against the ranker's OWN ladder means this checks the mapping as the pipeline will
# actually consume it, not as a private reimplementation imagines it. Since defect D4 that ladder
# is itself a copy of cpm_table.py's -- the SINGLE source of truth every ranker now imports, which
# settled the old 0.84029995-vs-0.84029999 L50 split at the game's own float32(0.8403) -- so
# cpm_table is the ONLY sanctioned fallback. compute_all_ranks is NOT one: see _live_cpm().
#
# Exit code 0 = certified, 1 = a FAIL finding, 2 = the check could not run (missing input). A
# check that cannot run is NOT a pass -- treat 2 like 1.
# ==================================================================================================

__all__ = ['FORM_OVERRIDES', 'certify']

_HERE = __import__('os').path.dirname(__import__('os').path.abspath(__file__))


def _base_id(species_name):
    """Rule 2/3 fallback -- the SAME normalization every consumer applies when there is no key."""
    return (species_name.lower().replace(' ', '_').replace("'", '')
            .replace('.', '').replace('-', '_').replace(u'\xe9', 'e'))


def _live_cpm():
    """The live ranker's CPM ladder. Returns None if it cannot be sourced (-> check cannot run).

    *** NEVER fall back to `from compute_all_ranks import CPM`. *** compute_all_ranks.py is a
    SCRIPT, not a module: its body opens pokemon.db relative to the current working directory,
    ALTERs the table, re-ranks every in_bag=1 row and COMMITS. It carried no `__main__` guard
    until 2026-09-07, so merely IMPORTING it did all of that -- inside certify(), whose own
    docstring promises "Read-only ... writes nothing anywhere". Measured in a sandbox that day,
    against the unguarded file: a bare `import compute_all_ranks` overwrote every gl/ul/ll rank
    column and changed the database file's sha256. It now refuses the import itself (its line-1
    `if __name__ != "__main__": raise ImportError`); dropping this fallback is the other half of
    that fix, so a single edit to either file can never again put a live-DB rewrite inside a
    read-only check. The fallback is pointless anyway: since defect D4 BOTH rankers take their
    ladder from cpm_table.py, so cpm_table is the same numbers with no side effects.
    check_constant_drift.py refuses this import for the same reason. (defect D1D3-tc, 2026-09-07)
    """
    import os, sys
    for p in (os.path.join(_HERE, 'system', 'scripts'), _HERE):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from rank_cache import CPM            # the ladder the pipeline actually ranks with
        return list(CPM)
    except Exception:
        pass
    try:
        from cpm_table import CPM             # the SAME ladder at its single source of truth
        return list(CPM)                      # (rank_cache.CPM *is* cpm_table.cpm_list())
    except Exception:
        return None                           # a check that cannot run is not a pass -- GT3 FAILs


_REGION_TOKENS = [('galar', 'galarian'), ('alola', 'alolan'), ('hisui', 'hisuian'),
                  ('paldea', 'paldean')]


def certify(db_path=None, gm_path=None, enum_path=None, verbose=True):
    """Re-derive this table from ground truth. Returns (ok, findings).

    findings entries are dicts: {'level': 'FAIL'|'WARN'|'INFO', 'check': str, 'detail': str}.
    ok is False iff any FAIL was raised. Read-only: opens pokemon.db in URI ro mode and writes
    nothing anywhere.
    """
    import os, json, math, sqlite3, collections
    out = []

    def say(lvl, chk, det):
        out.append({'level': lvl, 'check': chk, 'detail': det})
        if verbose:
            print('[%s] %-14s %s' % (lvl, chk, det))

    gm_path = gm_path or os.path.join(_HERE, 'pvpoke_gamemaster.json')
    enum_path = enum_path or os.path.join(_HERE, 'form_enum.json')
    db_path = db_path or os.path.join(_HERE, 'pokemon.db')

    try:
        gm = json.load(open(gm_path, encoding='utf-8'))
        pdb = {p['speciesId']: p for p in gm['pokemon']}
    except Exception as e:
        say('FAIL', 'inputs', 'cannot read %s (%s) -- CHECK DID NOT RUN' % (gm_path, e))
        return False, out
    try:
        fenum = {int(k): v for k, v in json.load(open(enum_path, encoding='utf-8')).items()}
    except Exception as e:
        fenum = {}
        say('WARN', 'inputs', 'no form_enum.json (%s) -- GT2 enum checks skipped' % e)

    # ---- GT1: every mapped speciesId exists in the gamemaster ------------------------------------
    missing = sorted({v for v in FORM_OVERRIDES.values() if v not in pdb})
    if missing:
        say('FAIL', 'gm-exists', 'mapped speciesId(s) absent from pvpoke_gamemaster.json: %s' % missing)
    else:
        say('INFO', 'gm-exists', '%d entries -> %d distinct speciesIds, all present'
            % (len(FORM_OVERRIDES), len(set(FORM_OVERRIDES.values()))))

    # ---- GT2: form-enum structural checks --------------------------------------------------------
    # Both checks are gated on "the id this SHOULD be actually exists in the gamemaster", so a
    # naming convention PvPoke simply does not follow can never raise a FAIL. Two real examples
    # that would otherwise be false alarms: PvPoke has no 'nidoran_f' (the DB's "Nidoran F" is a
    # name-normalization case, not a form variant), and no 'tauros_paldean' (the Paldean breeds
    # are 'tauros_combat'/'_blaze'/'_aqua'). A guard that cries wolf gets muted, and a muted
    # guard is how D1 survived; so FAIL only on a contradiction the gamemaster itself can prove.
    for (sp, form), sid in sorted(FORM_OVERRIDES.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        nm = fenum.get(form)
        if not nm:
            continue
        low = nm.lower()
        b = _base_id(sp)
        if low.endswith('normal') and sid != b and b in pdb:
            say('FAIL', 'enum-normal',
                "(%r, %d) enum=%s says NORMAL but maps to the variant %r -- expected %r. "
                "(This is the D1 shape: 135='MewtwoNormal' mapped to 'mewtwo_armored'.)"
                % (sp, form, nm, sid, b))
        for tok, suffix in _REGION_TOKENS:
            if tok in low and suffix not in sid and (b + '_' + suffix) in pdb:
                say('FAIL', 'enum-region',
                    "(%r, %d) enum=%s is %s but maps to %r -- expected %r"
                    % (sp, form, nm, suffix, sid, b + '_' + suffix))
            elif suffix in sid and tok not in low:
                say('WARN', 'enum-region',
                    "(%r, %d) maps to %r but enum=%s names no region -- a costume label replaces "
                    "the region in the enum name, so this is EXPECTED for a costumed regional "
                    "form (D2). Settled by the CP+HP check below, never by the name."
                    % (sp, form, sid, nm))

    # ---- GT3: CP+HP reconstruction against the live bag ------------------------------------------
    CPM = _live_cpm()
    if CPM is None:
        say('FAIL', 'cpm', 'could not import the live ranker CPM ladder -- GT3 DID NOT RUN')
        return False, out
    if not os.path.exists(db_path):
        say('FAIL', 'bag', 'no %s -- GT3 DID NOT RUN (a check that cannot run is not a pass)' % db_path)
        return False, out

    conn = sqlite3.connect('file:' + db_path.replace('\\', '/') + '?mode=ro', uri=True)
    try:
        rows = conn.execute(
            "SELECT species_name, pokemon_id, form, cp, "
            "COALESCE(max_stamina, stamina_max), iv_atk, iv_def, iv_sta "
            "FROM pokemon WHERE in_bag=1").fetchall()
    finally:
        conn.close()

    def cp_at(ba, bd, bs, ia, idf, ista, m):
        return max(10, int((ba + ia) * m * math.sqrt((bd + idf) * m) * math.sqrt((bs + ista) * m) / 10))

    _cpc, _hpc = {}, {}

    def cp_levels(st, ia, idf, ista, cp):
        k = (st['atk'], st['def'], st['hp'], ia, idf, ista, cp)
        v = _cpc.get(k)
        if v is None:
            v = frozenset(i for i, m in enumerate(CPM)
                          if cp_at(st['atk'], st['def'], st['hp'], ia, idf, ista, m) == cp)
            _cpc[k] = v
        return v

    def hp_levels(st, ista, hp):
        if hp is None:
            return frozenset(range(len(CPM)))
        k = (st['hp'], ista, hp)
        v = _hpc.get(k)
        if v is None:
            v = frozenset(i for i, m in enumerate(CPM)
                          if max(10, int(math.floor((st['hp'] + ista) * m))) == hp)
            _hpc[k] = v
        return v

    def fits(sid, r):
        """True iff SOME level reproduces this row's stored cp AND stamina under sid's stat line."""
        st = pdb[sid]['baseStats']
        _, _, _, cp, hp, ia, idf, ista = r
        cl = cp_levels(st, ia, idf, ista, cp)
        hl = hp_levels(st, ista, hp)
        if cl & hl:
            return True
        if cl:                     # stale cp_multiplier/stamina, or a mega/best-buddy CP
            return bool(hl)
        for c in pdb:              # the mon's own mega/primal line carries a different CP
            if c.startswith(sid + '_') and c.rsplit('_', 1)[-1] in ('mega', 'x', 'y', 'primal'):
                if cp_levels(pdb[c]['baseStats'], ia, idf, ista, cp):
                    return bool(hl)
        return False

    by_dex = collections.defaultdict(set)
    for sid, p in pdb.items():
        by_dex[p.get('dex')].add(sid)
    pairs = collections.defaultdict(list)
    for r in rows:
        if r[3] is None or r[5] is None:
            continue
        pairs[(r[0], r[2] or 0)].append(r)

    n_fail = n_soft = 0
    for (sp, form), prows in sorted(pairs.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        sid = FORM_OVERRIDES.get((sp, form), _base_id(sp))
        if sid not in pdb:
            say('FAIL', 'bag-map', "(%r, %d): %d row(s) map to %r which is not in the gamemaster"
                % (sp, form, len(prows), sid))
            n_fail += 1
            continue
        ok_n = sum(1 for r in prows if fits(sid, r))
        if ok_n == len(prows):
            continue
        cands = set(by_dex.get(prows[0][1], set()))
        b = _base_id(sp)
        cands |= {k for k in pdb if k == b or k.startswith(b + '_')}
        cands.discard(sid)
        scored = {c: sum(1 for r in prows if fits(c, r)) for c in cands}
        best = max(scored.values()) if scored else 0
        if best > ok_n:
            n_fail += 1
            say('FAIL', 'cp-recon',
                "(%r, %d) enum=%s mapped=%r reproduces stored cp+HP for only %d/%d row(s); "
                "%r reproduces %d/%d -- THE MAPPING IS WRONG"
                % (sp, form, fenum.get(form, '?'), sid, ok_n, len(prows),
                   sorted(c for c, v in scored.items() if v == best), best, len(prows)))
        else:
            n_soft += 1
            say('WARN', 'cp-recon',
                "(%r, %d) enum=%s mapped=%r: %d/%d row(s) reconstruct; no other stat line does "
                "better, so this is per-row data noise (stale cp_multiplier/stamina after a "
                "power-up, a best-buddy CP boost, or a CP sitting on an int-truncation edge), "
                "not a mapping error"
                % (sp, form, fenum.get(form, '?'), sid, ok_n, len(prows)))

    say('INFO', 'cp-recon', '%d bag rows over %d (species_name, form) pairs checked; %d mapping '
        'FAIL(s), %d data-noise WARN(s)' % (sum(len(v) for v in pairs.values()), len(pairs),
                                            n_fail, n_soft))
    ok = not any(f['level'] == 'FAIL' for f in out)
    if verbose:
        print()
        print('CERTIFIED -- the table reproduces the game\'s own CP and HP for every bag row.'
              if ok else 'NOT CERTIFIED -- see the FAIL line(s) above. Do NOT cull on this table.')
    return ok, out


if __name__ == '__main__':
    import sys as _sys
    try:
        _ok, _f = certify()
    except Exception as _e:                     # a guard that dies silently is worse than none
        print('[FAIL] certify() raised: %r -- CHECK DID NOT RUN' % (_e,))
        raise SystemExit(2)
    raise SystemExit(0 if _ok else 1)
