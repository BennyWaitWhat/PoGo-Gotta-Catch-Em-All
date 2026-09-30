"""Shared rule for the 1 GL IV / 1 UL IV tags (build_tagsets.py) AND the
keep_policy gl_iv/ul_iv keep-reasons -- SINGLE SOURCE OF TRUTH so the tag and the
keep reason cannot drift.

A specimen earns a league's IV tag iff its ranked form is CP-REACHABLE
(maxcp(stage) > cap + VIABILITY_MARGIN), AND EITHER:
  READY        : it is ALREADY its ranked form (pvid == stage), rank <= READY_RANK, and
                 under the league CP cap -> an evolved / use-as-itself mon you can run now.
  BUILD-TARGET : it is a PRE-EVO (pvid != stage) whose BEST evolved form ranks <= READY_RANK
                 -> worth evolving (a GL#1 0/13/11 Mareep -> Ampharos). RANK ONLY, no IV floor.

This CUTS by RANK, never by IV magnitude:
  - pre-evos whose best evolved form is "way off" (Wooloo -> GL#116 Dubwool): rank > 5.
  - under-cap hundo artifacts: a 15/15/15 Abra ranks #1 only because Abra maxes barely over
    the cap -> the VIABILITY_MARGIN gate (L50-hundo CP > cap+margin) can drop that degenerate band.
    USER CHOICE 2026-06-10: margin = 0 ("its stupid" / "why not just 0") -- any species that can
    CROSS the cap counts, band IV-dupes wearing the PvP label are ACCEPTED. Do NOT restore 100;
    the user explicitly rejected it twice. (Can't-reach-cap species like UL-Xatu are still excluded
    at margin 0 -- they never cross the cap at all.)
There is NO IV threshold of ANY kind anywhere -- not on atk, not on def, not on sta, not on the
total. The league RANK is the sole strength discriminator. (user 2026-06-05: "iv thresholds were
removed -- check every single iv rank for their league"; a BUILD_BULK def/sta>=14 gate had been
rejecting rank-#1 low-bulk spreads and a GL#1 0/13/11 Mareep got culled and released as a result.)

*** DO NOT REINTRODUCE AN IV GATE HERE. ***
This docstring used to claim qualification required `iv_atk <= 1`. It never did, and it must not:
an atk cap is the SAME class of gate as the BUILD_BULK def/sta>=14 floor that destroyed the Mareep.
A high-attack spread cannot rank top-N under a CP cap anyway, so the rank already encodes it. If
you find yourself adding `if iv_atk > N: return False`, stop -- that is the known failure mode.
"""
from form_overrides_complete import FORM_OVERRIDES
import keep_config   # dashboard-tunable READY_RANK / VIABILITY_MARGIN (single source of truth)

# CPM50 and the league caps come from cpm_table.py, the SINGLE SOURCE OF TRUTH, and are
# re-exported here because keep_policy.py and build_tagsets.py import GL_CAP/UL_CAP from
# this module. DEFECT D4 (fixed 2026-09-07): this file held one L50 literal while the
# ranker's table held a different one -- two values for one number, and neither was the
# value the game actually stores (float32(0.8403) = 0.8403000235557556, read off 66
# level-50 specimens). DO NOT re-hardcode a CP multiplier here; import it.
from cpm_table import CPM50, GL_CAP, UL_CAP, ML_CAP
READY_RANK = keep_config.pvp('ready_rank')     # top-N league IV-rank spreads of 4096 (keep_config.json) -- checked for EVERY mon, both leagues
BUILD_BULK = 14    # DEPRECATED 2026-06-05: the pre-evo def/sta>=14 gate is REMOVED from qualifies() (it rejected
#                    rank-#1 low-bulk spreads -> lost a GL#1 Mareep). Left defined so external imports don't break.
# (GL_CAP / UL_CAP imported above from cpm_table -- a READY mon already OVER its league cap can't enter it)
VIABILITY_MARGIN = keep_config.pvp('viability_margin')        # keep_config.json -- ranked form's L50-hundo CP must exceed the league cap by this, else its stat-product
#                               rank is DEGENERATE: an under/at-cap species pins every IV combo to L50, collapsing the
#                               rank to "highest raw IV wins" (the hundo ranks #1). The old floor (1400/2400) sat BELOW
#                               the cap and admitted that band (Abra L50hundo=1517 -> hundo #1). (user 2026-06-04)


def pvid(species_name, form):
    """The specimen's OWN pvpoke speciesId (to tell pre-evos from ready mons)."""
    if (species_name, form) in FORM_OVERRIDES:
        return FORM_OVERRIDES[(species_name, form)]
    return (species_name or '').lower().replace(' ', '_').replace("'", '') \
        .replace('.', '').replace('-', '_').replace('é', 'e')


# Sentinel returned when we CANNOT compute a species' L50-hundo CP (speciesId absent from the
# gamemaster, or the gamemaster failed to load at all). Every caller uses maxcp only in a
# `maxcp(stage, BS) > cap + margin` VIABILITY test, so a huge sentinel makes an unjudgeable stage
# read as VIABLE -> the mon keeps its PvP protection instead of silently losing it. Returning 0
# (the old behaviour) made missing data mean "not viable" = protection OFF, i.e. unknown data
# defaulted to UNPROTECTED -- the exact shape that lost the GL#1 Mareep. (lockdown 2026-09-02)
UNKNOWN_MAXCP = 10 ** 9


def maxcp(sid, BS):
    """L50-hundo CP for a gamemaster speciesId, or UNKNOWN_MAXCP when it cannot be computed.

    NOTE the sentinel is deliberately LARGE, not 0: unknown => PROTECTED. Callers that want to
    distinguish "unknown" from "genuinely huge" should compare against UNKNOWN_MAXCP explicitly.
    """
    b = BS.get(sid)
    if not b:
        return UNKNOWN_MAXCP
    return int(((b.get('atk', 0)+15)*(b.get('def', 0)+15)**0.5
                * (b.get('hp', 0)+15)**0.5*CPM50**2)/10)


CP_TOLERANCE = 1.03   # the CP formula reproduces 97.6% of the bag EXACTLY; legendaries whose pvpoke base stats are
#                       stale run ~2% high, so only call a specimen over the cap when it is over it by more than that.
#                       PREDICTED CPs only (a later stage): fits() judges a stored cp exactly (2026-09-23).


def cp_at(sid, iv_atk, iv_def, iv_sta, level, BS):
    """This specimen's CP as `sid`, at the level it is NOW -- None when the stage or the level is unknown.

    Evolving does not change the level, so this is exactly the CP it would have the moment it evolved."""
    b = BS.get(sid)
    if not b or level is None:
        return None
    from cpm_table import CPM, MAX_LEVEL_IDX
    m = CPM[min(max(int(round((level - 1) * 2)), 0), MAX_LEVEL_IDX)]
    return max(10, int(((b.get('atk', 0) + (iv_atk or 0)) * (b.get('def', 0) + (iv_def or 0)) ** 0.5
                       * (b.get('hp', 0) + (iv_sta or 0)) ** 0.5 * m * m) / 10))


def _col(r, k):
    """r[k] for a sqlite3.Row or a dict, None when the caller's projection does not carry the column."""
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def _cp_at_index(b, iv_atk, iv_def, iv_sta, i):
    """CP for base stats `b` at CPM table index i -- the SAME formula as cp_at(), without its level-50 clamp."""
    from cpm_table import CPM
    m = CPM[i]
    return max(10, int(((b.get('atk', 0) + iv_atk) * (b.get('def', 0) + iv_def) ** 0.5
                       * (b.get('hp', 0) + iv_sta) ** 0.5 * m * m) / 10))


def true_level(r, BS):
    """The half-level this specimen REALLY is, or None when it cannot be pinned down. ONE definition (2026-09-23).

    The `level` column is not always the truth: best buddies and half-level power-ups store a level the stored CP
    does not reproduce (Rampardos fd0146f38e1330df reads 27.0 at CP 2497, which only a L26.5 hundo Rampardos gives;
    130 in-bag rows on 2026-09-23 read exactly half a level high), and some rows carry a stale cp_multiplier while
    their level is right. So the level is PROVEN, not read: it is the half-level whose OWN-stage CP (the specimen's
    pvid base stats + IVs + cpm_table, the same formula as cp_at) reproduces the cp the game stored --
      1. the level column, if it reproduces the stored cp;
      2. else cp_multiplier + additional_cpm (the game's own float), if it lands on a table level that reproduces it;
      3. else every half-level L1..L51 is tried; the LOWEST that reproduces it wins (a tie is possible only at a
         very low CP, and the lowest level is the one that judges a later stage most leniently).
    None when nothing reproduces (stale base stats -- mostly legendaries; 6 rows on 2026-09-23, none of them able to
    evolve) or an input is missing. Callers read None as UNKNOWN, and unknown never strips protection: fits() treats
    it as fitting."""
    cp = _col(r, 'cp')
    ivs = (_col(r, 'iv_atk'), _col(r, 'iv_def'), _col(r, 'iv_sta'))
    if not cp or any(v is None for v in ivs):
        return None
    b = BS.get(pvid(_col(r, 'species_name'), _col(r, 'form') or 0))
    if not b:
        return None
    from cpm_table import CPM
    ok = lambda i: 0 <= i < len(CPM) and _cp_at_index(b, ivs[0], ivs[1], ivs[2], i) == cp
    lv = _col(r, 'level')
    if lv is not None:
        i = int(round((lv - 1) * 2))
        if abs((1 + i / 2.0) - lv) < 1e-6 and ok(i):
            return 1 + i / 2.0
    m = _col(r, 'cp_multiplier')
    if m is not None:
        m = m + (_col(r, 'additional_cpm') or 0)
        i = min(range(len(CPM)), key=lambda k: abs(CPM[k] - m))
        if abs(CPM[i] - m) < 1e-4 and ok(i):     # the game's float32 sum sits within ~5e-6 of the table entry
            return 1 + i / 2.0
    hits = [i for i in range(len(CPM)) if ok(i)]
    return 1 + hits[0] / 2.0 if hits else None


def stage_cp(r, stage, BS):
    """This specimen's CP as `stage` RIGHT NOW, or None when it cannot be known.

    Its own stage: the cp the game stored. A later stage: cp_at() at its TRUE level (true_level above) -- evolving
    keeps the level, so that is exactly the CP it would have the moment it evolved."""
    if pvid(_col(r, 'species_name'), _col(r, 'form') or 0) == stage:
        return _col(r, 'cp') or None
    lv = true_level(r, BS)
    if lv is None:
        return None
    return cp_at(stage, _col(r, 'iv_atk'), _col(r, 'iv_def'), _col(r, 'iv_sta'), lv, BS)


def fits(r, stage, cap, BS):
    """Can this SPECIMEN ever enter `cap`'s league as `stage`?  (user 2026-09-19: "some even over the cap".)

    CP only goes UP -- powering up raises it, evolving keeps the level -- so a mon already past the cap at the stage
    that ranks it can never play there, and a rank keep on it is a keep for a game it cannot enter. The clearest
    case: a cp1914 Magmar the game itself ranks GL#5. It is a genuine top-5 Great League SPREAD and it will never
    stand in Great League, because 1914 > 1500 and there is no way back down.

    Its own stage is judged on its REAL cp, exactly: the stored cp is the game's own number, so 1501 cannot enter Great
    League (2026-09-23 -- this used to allow cap x CP_TOLERANCE here too, which named a CP 1529 Golduck its species'
    Best GL; audit_rank_tags already judged own-stage tags strictly). A later stage is judged on its PREDICTED cp
    there at its TRUE level (stage_cp / true_level -- the level column is wrong on best buddies), with CP_TOLERANCE,
    because a prediction carries the stale-base-stat error that tolerance exists for. THE one usability test:
    keep_policy's Best GL/UL (rule 15d, shadow rule 2), the Rank labels and every audit mirror ask this function.
    UNKNOWN DATA => FITS: a missing base-stat row must never silently strip PvP protection (the Mareep shape)."""
    if not stage or cap is None:
        return True
    cp = stage_cp(r, stage, BS)
    if not cp:
        return True
    if pvid(_col(r, 'species_name'), _col(r, 'form') or 0) == stage:
        return cp <= cap                     # the STORED cp -- exact
    return cp <= cap * CP_TOLERANCE          # a PREDICTED cp -- stale base stats run ~2% high


def chain_stage_ranks(r, league):
    """[(stage speciesId, rank)] from <league>_chain_ranks ('raboot:7(99.82%);cinderace:1(100.00%)'), in the
    ranker's order: the specimen's OWN stage first, then every later stage rank_cache judged reachable. A malformed
    fragment is skipped, never guessed at."""
    out = []
    for part in str(_col(r, league + '_chain_ranks') or '').split(';'):
        if ':' not in part:
            continue
        sid, rest = part.split(':', 1)
        try:
            out.append((sid.strip(), int(rest.split('(')[0])))
        except ValueError:
            continue
    return out


def usable_best(r, league, cap, BS, later=None):
    """The copy's USABLE rank in `league` (user 2026-09-23: "Best GL/UL must be able to enter the league").

    Returns (viable_first_key, rank, stage) for the best stage this specimen can both REACH and ENTER, or None when it
    has none. A stage counts iff
      * it is its own stage, or a later stage in `later` -- the set of later speciesIds this specimen can actually
        become (the caller's evolution graph: form, costume and gender gates; item / candy cost never blocks). None
        means "trust the ranker's chain as it stands" (rank_cache already applied the form/costume/gender gates);
      * fits(): its CP there, at its TRUE level, is inside the cap (own stage: the stored cp).
    Best = a stage that can reach the cap first (viable_first_key 0, else 1), then the lowest rank, then the ranker's
    chain order (own stage first on a full tie -- no evolution for nothing). The ranks are the per-stage ranks
    rank_cache already stores; nothing is re-ranked here. A row with no chain but a stored rank falls back to that
    single (stage, rank)."""
    ch = chain_stage_ranks(r, league)
    if not ch and _col(r, league + '_rank') is not None:
        ch = [(_col(r, league + '_stage'), _col(r, league + '_rank'))]
    own = pvid(_col(r, 'species_name'), _col(r, 'form') or 0)
    # EVOLUTION COUNTS EVERYWHERE (user 2026-09-24): the rank is the best at ANY reachable stage, CP-blind per stage;
    # the copy only has to be able to ENTER the league at SOME reachable stage (else None -- 2026-09-23 stands).
    reach = [(pos, st, rk) for pos, (st, rk) in enumerate(ch) if st and (st == own or later is None or st in later)]
    if not any(fits(r, st, cap, BS) for _p, st, _k in reach):
        return None
    best = None
    for pos, st, rk in reach:
        key = (0 if maxcp(st, BS) > cap + VIABILITY_MARGIN else 1, rk, pos)
        if best is None or key < best[0]:
            best = (key, st)
    return None if best is None else (best[0][0], best[0][1], best[1])


def qualifies(species_name, form, iv_atk, iv_def, iv_sta, stage, rank, floor, BS, cp=None, cap=None):
    """True iff this specimen earns the league IV tag for ranked form `stage`.

    RANK-DRIVEN -- NO IV-magnitude threshold. (user 2026-06-05, after a GL#1 0/13/11 Mareep
    was put in Transfer and released: "i thought iv thresholds were removed -- you are to
    check every single iv rank for their league".) A BUILD_BULK def>=14 & sta>=14 gate had
    been silently rejecting rank-#1 LOW-BULK pre-evos and dumping them in the cull. That gate
    is GONE. A specimen is kept iff:
      VIABLE : its best-ranked chain form `stage` reaches the cap WITH HEADROOM
               (L50-hundo CP > cap + VIABILITY_MARGIN (keep_config pvp.viability_margin, currently 0)) -- CP-REACHABILITY only, not an IV gate -- so the
               stat-product rank is meaningful (not the under-cap-hundo degeneracy), AND
      RANKED : that form's league IV-rank <= READY_RANK (top-5 of 4096 spreads), AND
      a READY mon (already the ranked form) must be UNDER the league CP cap to enter.
    A PRE-EVO that is top-5 for its viable evolved form is kept OUTRIGHT -- the rank already
    proves the spread; there is no def/sta IV floor. The rank itself enforces low-attack
    (a high-atk spread can't rank top-5 under a CP cap), so iv_atk needs no separate gate.
    """
    gate = (cap + VIABILITY_MARGIN) if cap is not None else floor   # league-competitive = reaches the cap WITH HEADROOM
    if not stage or maxcp(stage, BS) <= gate:    # CP-REACHABILITY only (not an IV gate): the ranked form's L50-hundo CP
        return False                             # must exceed cap + VIABILITY_MARGIN (keep_config pvp.viability_margin, currently 0) or the rank is degenerate (Abra/Machop hundo = #1).
    if rank is None or rank > READY_RANK:        # THE league IV-RANK check -- top-5 of 4096 spreads for the best chain form
        return False                             # (a pre-evo whose best form is only GL#116, e.g. Wooloo->Dubwool, is "way off")
    if pvid(species_name, form or 0) == stage:                 # READY (evolved / as-itself)
        return cap is None or (cp or 0) <= cap   # ...but a READY mon ALREADY over the league CP cap can't enter it
    # PRE-EVO top-5 build-target for a viable evolved form -> KEEP. Deliberately NOT gated on whether THIS copy can
    # still get under the cap after evolving: that gate was tried 2026-09-19 and the lost-keeper fixtures rejected
    # it, 9 real spreads to the irreversible pile. `fits()` answers that question for LABELS only.
    return True                                  # The def/sta>=14
    #                                              BUILD_BULK floor that lost the 0/13/11 GL#1 Mareep is REMOVED (rank is the rule).
