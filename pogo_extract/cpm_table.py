"""cpm_table.py -- THE single source of truth for the CP multiplier table, the level
cap index, and the league CP caps.

*** DO NOT RE-HARDCODE ANY VALUE FROM THIS FILE ANYWHERE ELSE. IMPORT IT. ***

WHY THIS FILE EXISTS (defect D4, 2026-09-07)
--------------------------------------------
There used to be two different values for one number -- the level-50 CP multiplier:

    system/scripts/rank_cache.py:99      CPM[98] = 0.84029995     <- the ranker
    compute_all_ranks.py:33              CPM[98] = 0.84029995     <- the fallback ranker
    pvp_iv_rule.py:34                    CPM50   = 0.84029999     <- the viability gate

and five more copies in build_tagsets / preflight_transfer / audit_cull / granular_tags
(the last two SCRAPED the literal back out of compute_all_ranks.py's source text with a
regex, which is duplication with extra steps). Two literals that merely happen to match
are not a single source of truth: the next person to "correct" one of them silently
re-splits the brain, and the ranks that decide PvP protection move underneath the
irreversible Transfer pile. A shared constant beats two matching literals.

GROUND TRUTH FOR THE L50 VALUE
------------------------------
Neither old literal was right. The arbiter is the game itself: pokemon.db stores the raw
`cp_multiplier` + `additional_cpm` floats read straight out of PoGo's own memory, and on
66 level-50 specimens their sum is exactly

    0.8403000235557556  ==  float32(0.8403)      <- the value the game multiplies by

Both old literals (0.84029995 and 0.84029999) are float64 decimals that round to the
float32 *below* the game's value (0.8402999639511108) -- i.e. they were both failed
transcriptions of the same real constant, off by one ULP in the same direction.

CP+HP reconstruction could NOT tell the three apart (all reproduce every stored CP and HP
in the bag identically), so the raw stored float is the stronger arbiter and is what this
table now uses. Measured impact of adopting it, on the live 5,727-mon bag (sandboxed):

    Transfer pile ............. 26 uids, MEMBERSHIP IDENTICAL
    all 48 tagsets ............ MEMBERSHIP IDENTICAL
    rank<=5 protection boundary crossings ...... 0
    mons whose rank column shifts at all ....... 181  (cosmetic, see below)

WHY 181 RANKS SHIFT, AND WHY IT IS NOT SIGNAL
---------------------------------------------
For a species weak enough to sit at L50 under its league cap (magikarp/feebas/weedle in
Little League, many pre-evos in GL/UL) EVERY one of the 4096 spreads is evaluated at the
same level, so the CPM is a uniform scale factor and cannot reorder anything. It was
verified directly on magikarp: no floor((base_sta+iv)*cpm) value changes, and the
exact-integer ordering surrogate (atk+ia)*(def+id)*floor(...) is IDENTICAL under both
constants. What changes is only how float64 rounding merges or splits EXACT TIES
(3123 vs 2971 distinct stat-product values out of 4096), and rank is the leftmost index
of the tied value.

    *** KNOWN LATENT HAZARD -- NOT FIXED HERE, NEEDS A DECISION ***
    That means the published rank is decided by float rounding wherever spreads tie, and
    it can move by up to ~11 positions for a purely cosmetic constant edit. Today no mon
    crosses the rank<=5 gate that grants PvP protection (measured: 0 of 5,727), but the
    gate IS exposed to tie noise on a future bag. The durable fix is to rank on the exact
    integer surrogate instead of the float product. That changes the ranking metric, so it
    is deliberately NOT done here.

The rest of the table is left byte-identical to what the ranker has always used. The
entries are decimal roundings of the game's float32 values (deltas ~1e-9); replacing the
whole table with exact float32 was measured too -- pile and all 48 tagsets still
identical, 0 boundary crossings, but 416 rank columns churn for no decision benefit, so
it is NOT done without a deliberate call.
"""

# Index i corresponds to level 1 + i/2  (i=0 -> L1.0, i=98 -> L50.0, i=100 -> L51.0).
# Immutable on purpose: consumers that need to mutate take a copy via cpm_list().
CPM = (
    0.094, 0.135137432, 0.16639787, 0.192650919, 0.21573247, 0.236572661,  # L1.0-L3.5
    0.25572005, 0.273530381, 0.29024988, 0.306057377, 0.3210876, 0.335445036,  # L4.0-L6.5
    0.34921268, 0.362457751, 0.37523559, 0.387592406, 0.39956728, 0.411193551,  # L7.0-L9.5
    0.42250001, 0.432926419, 0.44310755, 0.4530599578, 0.46279839, 0.472336083,  # L10.0-L12.5
    0.48168495, 0.4908558, 0.49985844, 0.508701765, 0.51739395, 0.525942511,  # L13.0-L15.5
    0.53435433, 0.542635767, 0.55079269, 0.558830576, 0.56675452, 0.574569153,  # L16.0-L18.5
    0.58227891, 0.589887907, 0.59740001, 0.604818814, 0.61215729, 0.619399365,  # L19.0-L21.5
    0.62656713, 0.633644533, 0.64065295, 0.647576426, 0.65443563, 0.661214806,  # L22.0-L24.5
    0.667934, 0.674577537, 0.68116492, 0.687680648, 0.69414365, 0.700538673,  # L25.0-L27.5
    0.7068842, 0.713164996, 0.71939909, 0.725571552, 0.7317, 0.734741009,  # L28.0-L30.5
    0.73776948, 0.740785574, 0.74378943, 0.746781211, 0.74976104, 0.752729087,  # L31.0-L33.5
    0.7556855, 0.758630378, 0.76156384, 0.764486065, 0.76739717, 0.770297266,  # L34.0-L36.5
    0.7731865, 0.776064962, 0.77893275, 0.781790055, 0.78463697, 0.787473578,  # L37.0-L39.5
    0.79030001, 0.792803968, 0.79530001, 0.797800015, 0.8003, 0.802799995,  # L40.0-L42.5
    0.8053, 0.807800014, 0.81029999, 0.812799985, 0.81529999, 0.81779999,  # L43.0-L45.5
    0.82029998, 0.82279998, 0.82529997, 0.82779996, 0.83029996, 0.83279996,  # L46.0-L48.5
    0.83529995, 0.83779995, 0.8403000235557556, 0.84279995, 0.84529994,  # L49.0-L51.0
)

MAX_LEVEL_IDX = 98          # level 50.0 -- the highest level the ranker will evaluate (matches Pokemod)
LEVEL_50_IDX  = 98          # level 50.0
LEVEL_51_IDX  = 100         # level 51.0 -- present in the table, above the ranker's cap

#: The level-50 CP multiplier, DERIVED from the table so the scalar and the table entry
#: are the same object-value by construction and cannot drift (this was defect D4).
CPM50 = CPM[LEVEL_50_IDX]

# League CP caps. Game constants, NOT policy knobs -- keep_config.py says so explicitly
# ("Game constants (league CP caps 1500/2500, CPM) are NOT tunable here"), so they live
# here next to the CPM rather than in keep_config.json.
LL_CAP = 500                # Little League
GL_CAP = 1500               # Great League
UL_CAP = 2500               # Ultra League
ML_CAP = 10 ** 9            # Master League: NO cap -- every spread is ranked at the level ceiling (2026-09-23)
LEAGUE_CAPS = (LL_CAP, GL_CAP, UL_CAP)


def cpm_list():
    """A fresh MUTABLE copy of the table, for consumers that index/patch it locally.

    Handing out a copy (rather than the tuple itself) means a caller that temporarily
    patches its own CPM -- e.g. regress_pvp_keepers.py's D4 guard, which assigns
    rank_cache.CPM[MAX_LEVEL_IDX] and restores it -- cannot corrupt the canonical table
    for every other importer in the same process.
    """
    return list(CPM)


def level_for_index(i):
    """Level (float, half-steps) for a table index."""
    return 1.0 + i / 2.0


# ---- import-time self-checks: fail LOUD, never silently serve a broken table ----------
assert len(CPM) == 101, 'CPM table must hold L1.0..L51.0 in half-steps (101 entries), got %d' % len(CPM)
assert all(CPM[i] < CPM[i + 1] for i in range(len(CPM) - 1)), \
    'CPM table must be strictly increasing -- find_max_idx binary-searches on that assumption'
assert CPM50 == CPM[MAX_LEVEL_IDX], 'CPM50 must BE the table entry, not a second literal (defect D4)'
assert level_for_index(MAX_LEVEL_IDX) == 50.0, 'MAX_LEVEL_IDX must point at level 50.0'
assert CPM50 == 0.8403000235557556, (
    'CPM50 is no longer the value the game itself stores (float32(0.8403), verified against '
    '66 level-50 specimens\' cp_multiplier+additional_cpm in pokemon.db). If you are changing '
    'this deliberately, re-run the sandboxed pile/tagset impact measurement first -- this '
    'constant feeds the PvP ranks that decide the irreversible Transfer pile.')
assert LL_CAP < GL_CAP < UL_CAP
