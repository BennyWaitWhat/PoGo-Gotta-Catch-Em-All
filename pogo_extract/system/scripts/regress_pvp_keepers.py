"""regress_pvp_keepers.py -- PERMANENT regression fixtures for the 18 PvP keepers we LOST.

WHY THIS FILE EXISTS
====================
A forensic audit (2026-09-07) found 24 pokemon that a CORRECT engine would have KEPT and that a
past engine put in the irreversible Transfer pile. 18 of them are gone for good. Two causes:

  * 17 predate any PvP-RANK rule -- the pre-2026-06-05 IV-MAGNITUDE era, the same defect that
    killed a 0/13/11 Great League rank-1 Mareep (see feedback-pvp-rank-not-iv-threshold and the
    *** DO NOT REINTRODUCE AN IV GATE HERE *** banner in pvp_iv_rule.py). Under a league CP cap the
    stat-product rank ANTI-correlates with IV%: low attack wins. Every IV floor/threshold ever added
    to a PvP path has therefore rejected exactly the spreads that rank #1.
  * 1 was a Mudbray whose species_name parsed as the placeholder "pid749". With no FORM_OVERRIDES
    entry and no resolvable slug, pvid() produced a speciesId absent from the gamemaster, the ranker
    wrote NULL ranks, and the engine read "no rank" as "no PvP protection" instead of "unknown ->
    protect". Its true rank was GREAT LEAGUE #2 of 4096, 99.65%.

The patches for that are elsewhere (rule 15b pvp_rank, rule 15c rank_unknown, the maxcp UNKNOWN
sentinel, the rank_cache NULL-on-unmappable fix). THIS FILE IS THE GUARD: it encodes the 18 real
spreads as permanent fixtures, inserts them into a SANDBOX copy of the bag, runs the REAL current
keep_policy, and fails the audit gate if any of them comes out TRANSFER -- or comes out KEPT for an
incidental reason with its PvP protection silently gone. A rule can be deleted; a fixture that
proves the rule cannot be deleted quietly.

WHAT IS ASSERTED (all three are hard; any failure exits non-zero)
================================================================
  A. RANK MATH + FORM MAPPING. Each fixture's GL/UL rank, percent and best-chain STAGE are
     recomputed with the live ranker (system/scripts/rank_cache.py: to_pvpoke_id -> get_evolutions
     -> compute_rank_for_iv) and compared to the recorded audit values. This locks the stat-product
     formula AND the (species_name, form) -> pvpoke speciesId mapping for 15 distinct forms,
     including three regional ones (meowth_galarian, qwilfish_hisuian, grimer_alolan). A D2/D3-class
     mapping error on any of them changes the stage and fails here.
  B. THE ENGINE'S DECISION. Not "the rank is good" -- keep_policy.main() itself must put the uid in
     KEEP, and the reason set must contain a PvP-CLASS axis (pvp_rank / gl_iv / ul_iv / pvp_spread,
     or rank_unknown for the Mudbray). A fixture kept only by dex_only_copy or data_incomplete is a
     FAILURE: that is protection by accident, and it is how a silent regression hides.
  C. STANDING ANCHORS, verified twice against the user's own app and two in-game screenshots:
       Armored Mewtwo (182/278/214) ULTRA 12/15/13 -> #1108/4096, 96.88%;  12/13/14 -> #1151, 96.82%
       HP  13/15/15 @ L27.5 -> 160     15/15/13 @ L50 -> 190
     eff_atk=(base+iv)*cpm, eff_def=(base+iv)*cpm, eff_sta=FLOOR((base+iv)*cpm), sp=atk*def*sta.
     Stamina is floored, the other two are not.

THE AUDITOR'S CAVEAT -- READ THIS BEFORE "FIXING" A FAILURE
==========================================================
14 of the 18 are keepers under ANY viability margin. FOUR are not: the three Abra and the Wailmer
qualify ONLY because keep_config pvp.viability_margin is currently 0.
    Abra    13/15/15 -> GL #3, but abra's L50-hundo CP is 1517, i.e. cap+17
    Abra    13/15/15 -> GL #3   (second copy)
    Abra    14/15/13 -> GL #4,  same 1517
    Wailmer 10/15/15 -> UL #3 via wailord, L50-hundo CP 2577, i.e. cap+77
Rule 15b keeps a mon only if its ranked stage's L50-hundo CP EXCEEDS cap + viability_margin. Raise
the margin to 100 and all four stop qualifying -- not because the engine broke, but because the
policy changed. Those four carry margin_sensitive=True and this script says so IN THE FAILURE TEXT,
so a future margin change produces an explained failure instead of a mystery. The user rejected
margin=100 twice (2026-06-10, "its stupid" / "why not just 0"); if it is ever raised deliberately,
edit the caveat here, do not delete the fixtures.

HARD RULES THIS FILE OBEYS
==========================
  * SANDBOX ONLY. The live pokemon.db is opened read-only (file: URI, mode=ro) and snapshotted with
    sqlite's backup API. keep_policy's DB / TD / ROOT / __file__ are repointed INTO a temp tree, and
    every one of those paths is asserted to live under the sandbox before main() is called, so the
    live pile, policy_reasons.json, pile_provenance.json and fodder_oracle.json cannot be written.
    The live artifacts are hashed before and after as a belt-and-braces check.
  * NEVER releases, transfers, tags or touches the phone. No Frida, no ADB, no network. Read-only
    against the live tree, safe to run concurrently with the other audits.
  * Changes NO cap, roster or keep rule, and reads the LIVE keep_config.json -- so a config edit
    that would drop one of these mons shows up here as a failure rather than as a released keeper.

USAGE
=====
    python system/scripts/regress_pvp_keepers.py            # the gate (exit 0 = all 18 kept)
    python system/scripts/regress_pvp_keepers.py -v         # + per-fixture keep reasons / engine log
    python system/scripts/regress_pvp_keepers.py --keep-sandbox   # leave the temp tree for inspection
Wired into full_audit.py as a sixth gate; its pass line is 'ALL PVP KEEPER FIXTURES KEPT'.
"""
import contextlib, gc, hashlib, io, json, math, os, shutil, sqlite3, sys, tempfile, time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # <project>/
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rank_cache as rc                                 # THE live ranker (system/scripts/)
import pvp_iv_rule
# NOT keep_config directly: these are the values keep_policy itself imported BY VALUE at engine
# import time, so reporting them is reporting what actually judged the fixtures, not a second read
# of the config file that could disagree with it.
from pvp_iv_rule import GL_CAP, UL_CAP, READY_RANK, VIABILITY_MARGIN
from costume_forms import is_costume_form

LIVE_DB = os.path.join(ROOT, 'pokemon.db')
GM_PATH = os.path.join(ROOT, 'pvpoke_gamemaster.json')
# The three data files keep_policy reads out of ROOT (besides the db). Copied into the sandbox so
# the engine's own input gates (which ABORT on a missing/empty one) see exactly the live inputs.
ROOT_INPUTS = ('pvpoke_gamemaster.json', 'legacy_accurate.json', 'pokedex_hundos_live.json')

# A keep reason that means "the PvP machinery actually protected this mon". Anything outside this
# set (dex_only_copy, variant_floor, data_incomplete, ...) is protection BY ACCIDENT and does not
# count -- the whole failure being regressed is a PvP keeper surviving on an unrelated axis one day
# and being released the next when that axis moves.
PVP_AXES = frozenset({'pvp_rank', 'gl_iv', 'ul_iv', 'pvp_spread'})
# pvp_best_gl / pvp_best_ul (rule 15d, 2026-09-23) are deliberately NOT here: they are bag-RELATIVE (the best copy
# you happen to own moves the moment a better one is caught), so for these absolute-spread fixtures they are
# protection by accident, like dex_only_copy -- they must never satisfy the rule-15b assertion.
# The Mudbray's axis. NOT a PvP rank axis -- the point of that fixture is that the ranks are NULL
# and rule 15c must read "unknown" as PROTECTED. Kept separate so the two behaviours can never be
# confused for one another in a pass.
UNKNOWN_AXIS = frozenset({'rank_unknown'})

MARGIN_NOTE = (' *** MARGIN-SENSITIVE FIXTURE: this one qualifies ONLY while keep_config '
               'pvp.viability_margin is 0. If the margin was just raised, this failure is a POLICY '
               "change, not an engine bug -- see the caveat in this file's docstring. ***")


# ---------------------------------------------------------------------------------------------
# THE FIXTURES -- 18 real spreads, every one of them culled by a past engine and unrecoverable.
# ---------------------------------------------------------------------------------------------
# form/form_region/pokemon_id are the values the LIVE bag uses for that species, so each fixture is
# judged exactly as its lost original was. gl/ul are the audit's recorded (rank, pct, chain) and are
# RE-DERIVED from the gamemaster on every run (assertion A) -- they are anchors, not inputs.
# `axis` is the reason set the engine MUST produce (assertion B).
def F(label, pid, species, form, region, ivs, gl, ul, axis, why, margin_sensitive=False):
    return dict(label=label, pid=pid, species=species, form=form, region=region, ivs=ivs,
                gl=gl, ul=ul, axis=axis, why=why, margin_sensitive=margin_sensitive)


# 2026-09-08: four anchors re-derived after the ranker became VIABILITY-AWARE (see Dottler fixture). The old values
# named a stage that never reaches its cap (abra UL, meowth_galarian GL) -- the bug itself, frozen into the test.
FIXTURES = [
    F('Ralts 0/15/15', 280, 'Ralts', 292, 'kantonian', (0, 15, 15),
      (1, 100.00, 'ralts->gallade'), (2, 99.87, 'ralts->gallade'),
      PVP_AXES, 'GL#1 100% -- gallade line'),
    F('Eevee 0/15/14', 133, 'Eevee', 1092, 'kantonian', (0, 15, 14),
      (1, 100.00, 'eevee->umbreon'), (5, 99.64, 'eevee->leafeon'),
      PVP_AXES, 'GL#1 100% -- umbreon/leafeon'),
    F('Popplio 0/14/14', 728, 'Popplio', 3081, None, (0, 14, 14),
      (2, 99.52, 'popplio->primarina'), (82, 98.67, 'popplio->primarina'),
      PVP_AXES, 'GL#2 -- primarina'),
    F('Krabby 0/15/13', 98, 'Krabby', 870, 'kantonian', (0, 15, 13),
      (65, 98.48, 'krabby->krabby'), (2, 99.94, 'krabby->kingler'),
      PVP_AXES, 'UL#2 99.94% -- kingler'),
    F('Meowth-Galarian 2/15/15', 52, 'Meowth', 2335, 'galarian', (2, 15, 15),
      (676, 96.75, 'meowth_galarian->perrserker'), (3, 99.75, 'meowth_galarian->perrserker'),
      PVP_AXES, 'UL#3 -- perrserker (its GL stage is not even cap-viable)'),
    F('Qwilfish-Hisuian 1/15/12', 211, 'Qwilfish', 2788, 'hisuian', (1, 15, 12),
      (14, 98.83, 'qwilfish_hisuian->overqwil'), (3, 99.73, 'qwilfish_hisuian->overqwil'),
      PVP_AXES, 'UL#3 -- overqwil'),
    F('Wailmer 10/15/15', 320, 'Wailmer', 1511, 'kantonian', (10, 15, 15),
      (479, 96.16, 'wailmer->wailmer'), (3, 99.62, 'wailmer->wailord'),
      PVP_AXES, 'UL#3 -- wailord; wailord L50-hundo CP is 2577 = cap+77', True),
    F('Golduck 2/13/15', 55, 'Golduck', 289, 'kantonian', (2, 13, 15),
      (4, 99.86, 'golduck->golduck'), (73, 99.24, 'golduck->golduck'),
      PVP_AXES, 'GL#4 -- ready as itself'),
    F('Bellsprout 2/15/14', 69, 'Bellsprout', 664, 'kantonian', (2, 15, 14),
      (4, 99.71, 'bellsprout->victreebel'), (41, 99.16, 'bellsprout->victreebel'),
      PVP_AXES, 'GL#4 -- victreebel'),
    F('Gastly 0/15/15', 92, 'Gastly', 1038, 'kantonian', (0, 15, 15),
      (5, 99.55, 'gastly->haunter'), (7, 99.23, 'gastly->gengar'),
      PVP_AXES, 'GL#5 -- haunter'),
    F('Grimer-Alolan 0/14/12', 88, 'Grimer', 74, 'alolan', (0, 14, 12),
      (73, 98.80, 'grimer_alolan->muk_alolan'), (5, 99.67, 'grimer_alolan->muk_alolan'),
      PVP_AXES, 'UL#5 -- muk_alolan'),
    F('Growlithe 1/11/15', 58, 'Growlithe', 280, 'kantonian', (1, 11, 15),
      (47, 98.77, 'growlithe->arcanine'), (5, 99.62, 'growlithe->arcanine'),
      PVP_AXES, 'UL#5 -- arcanine; 11 def would have failed any def/sta bulk floor'),
    F('Krabby 2/13/15', 98, 'Krabby', 870, 'kantonian', (2, 13, 15),
      (129, 98.29, 'krabby->kingler'), (5, 99.80, 'krabby->kingler'),
      PVP_AXES, 'UL#5 -- kingler'),
    F('Sprigatito 0/12/15', 906, 'Sprigatito', 3222, 'kantonian', (0, 12, 15),
      (6, 99.29, 'sprigatito->floragato'), (5, 99.61, 'sprigatito->meowscarada'),
      PVP_AXES, 'UL#5 -- meowscarada'),
    F('Abra 13/15/15 (a)', 63, 'Abra', 304, 'kantonian', (13, 15, 15),
      (3, 99.64, 'abra->abra'), (1994, 95.91, 'abra->alakazam'),
      PVP_AXES, 'GL#3; abra L50-hundo CP is 1517 = cap+17', True),
    F('Abra 13/15/15 (b)', 63, 'Abra', 304, 'kantonian', (13, 15, 15),
      (3, 99.64, 'abra->abra'), (1994, 95.91, 'abra->alakazam'),
      PVP_AXES, 'GL#3, second copy', True),
    F('Abra 14/15/13', 63, 'Abra', 304, 'kantonian', (14, 15, 13),
      (4, 99.60, 'abra->abra'), (2566, 95.41, 'abra->alakazam'),
      PVP_AXES, 'GL#4; same cap+17 band', True),
    # THE IMPORTANT ONE. species_name is DELIBERATELY the unresolvable placeholder the crawl actually
    # produced. pvid('pid749', 3098) has no FORM_OVERRIDES entry and slugs to 'pid749', which is not a
    # gamemaster speciesId -> the ranker writes NULL ranks -> rules 15/15b all begin `rank is not None`
    # and protect nothing. The ONLY thing between this mon and the pile is rule 15c reading NULL as
    # UNKNOWN-therefore-PROTECTED. Its true spread is Mudbray 0/11/13 = GREAT LEAGUE #2 of 4096,
    # 99.65% (re-run this file with species='Mudbray' to see it). Never "fix" this fixture by giving
    # it a resolvable name -- the broken name IS the test.
    F('Mudbray 0/11/13 as "pid749"', 749, 'pid749', 3098, 'kantonian', (0, 11, 13), None, None,
      UNKNOWN_AXIS, 'UNRESOLVABLE SPECIES -> NULL ranks -> must be kept as rank_unknown; '
                    'true rank GL#2 of 4096, 99.65%, viable via mudsdale'),
    # 2026-09-08 -- the VIABLE-STAGE guard. Not a lost mon (it is a hundo, kept by other axes) but the exact
    # shape of a bug found in the live ranker: the chain's "best" rank was chosen viability-blind, so the
    # raw-IV #1 of a stage that never reaches the cap (dottler, max CP 1,164) MASKED the legitimate Orbeetle
    # UL #3 (max CP 2,513) and every consumer saw a non-viable stage -> no PvP protection. Assertion A pins
    # the stage to orbeetle; assertion B demands a PvP axis. 2,232 of 5,738 rows changed when this was fixed.
    F('Dottler 15/15/15 (viable-stage guard)', 825, 'Dottler', 3164, None, (15, 15, 15),
      (1505, 95.14, 'dottler->orbeetle'), (3, 99.99, 'dottler->orbeetle'),
      PVP_AXES, 'UL#3 99.99% -- orbeetle; guards the viability-blind best-stage bug'),
]
# True base stats for the deliberately-unresolvable fixture. The specimen IS a Mudbray -- only the
# engine's NAME lookup is broken -- so its CP is reconstructed from mudbray's line, as the real one's
# was in game.
TRUE_SID = {'Mudbray 0/11/13 as "pid749"': 'mudbray'}


# ---------------------------------------------------------------------------------------------
# rank derivation -- the live ranker, not a reimplementation
# ---------------------------------------------------------------------------------------------
def _rank_cache(gm_bytes, pokemon_db, pkl_dir):
    """A RankTableCache pinned to a SANDBOX pickle path.

    rank_cache's own pickle (system/scripts/rank_tables.pkl) is ~280MB of shared cache the live
    pipeline owns; this test must never rewrite it. The 4096-combo tables for ~20 species rebuild in
    well under a second, so the sandbox cache is simply thrown away with the rest of the tree.
    """
    return rc.RankTableCache(pokemon_db, rc._content_hash(gm_bytes),
                             pkl_path=os.path.join(pkl_dir, 'regress_rank_tables.pkl'))


def _best_rank(cache, pokemon_db, sid, ivs, cap):
    """Best (lowest) rank across the evolution chain -- the same walk compute_ranks() does per row."""
    if sid not in pokemon_db:
        return None
    # 2026-09-08: mirrors rank_cache's VIABILITY-AWARE selection -- a stage that can reach the cap beats one
    # that cannot; among equals the lowest rank wins; fall back to the overall lowest if none is viable.
    # (Dottler 15/15/15: stage dottler ranks #1 by raw IV but maxes at 1,164 CP; orbeetle UL #3 is the real one.)
    best = None
    for stage in rc.get_evolutions(pokemon_db, sid):
        r = rc.compute_rank_for_iv(cache, stage, ivs[0], ivs[1], ivs[2], cap, False)
        if not r:
            continue
        cand = dict(r, stage=stage, viable=rc._stage_viable(cache, stage, cap, False))
        if best is None or (cand['viable'] and not best['viable']) or (cand['viable'] == best['viable'] and cand['rank'] < best['rank']):
            best = cand
    return best


def derive_ranks(cache, pokemon_db, fx):
    """(sid, gl, ul) for a fixture, via the live to_pvpoke_id + chain walk."""
    sid = rc.to_pvpoke_id(fx['species'], fx['form'], 0)
    return (sid,
            _best_rank(cache, pokemon_db, sid, fx['ivs'], GL_CAP),
            _best_rank(cache, pokemon_db, sid, fx['ivs'], UL_CAP))


def fixture_cp(pokemon_db, fx, sid):
    """CP of the specimen BUILT FOR THE LEAGUE THAT PROTECTS IT -- highest level under that cap.

    CP is not what saves any of these mons (rule 15b never looks at it), but rule 15's READY branch
    refuses a mon already OVER its league cap, and CP is a topn() tiebreak. Deriving it from the real
    compute_cp at the real cap is the honest reconstruction; inventing a round number is not.
    """
    b = (pokemon_db.get(sid) or pokemon_db[TRUE_SID[fx['label']]])['baseStats']
    cap = GL_CAP if (fx['gl'] and fx['gl'][0] <= READY_RANK) else UL_CAP
    a, d, s = fx['ivs']
    idx = rc.find_max_idx(b['atk'], b['def'], b['hp'], a, d, s, cap, False)
    idx = min(max(idx, 0), rc.MAX_LEVEL_IDX)
    return rc.compute_cp(b['atk'], b['def'], b['hp'], a, d, s, rc.CPM[idx], False), idx


# ---------------------------------------------------------------------------------------------
# sandbox
# ---------------------------------------------------------------------------------------------
def build_sandbox(sandbox):
    """A throwaway project tree: a CONSISTENT snapshot of the bag + the files keep_policy reads.

    The db is copied with sqlite's backup API through a mode=ro URI rather than shutil.copy: the
    dashboard and autocull_watch are live processes writing this database in WAL mode, and a byte
    copy taken mid-transaction is a torn read. Read-only is enforced by the URI, not by intent.
    """
    os.makedirs(os.path.join(sandbox, 'system', 'analysis', 'tagsets'), exist_ok=True)
    os.makedirs(os.path.join(sandbox, 'system', 'scripts'), exist_ok=True)
    sb_db = os.path.join(sandbox, 'pokemon.db')
    src = sqlite3.connect('file:%s?mode=ro' % LIVE_DB.replace('\\', '/'), uri=True)
    try:
        dst = sqlite3.connect(sb_db)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    for fn in ROOT_INPUTS:
        shutil.copyfile(os.path.join(ROOT, fn), os.path.join(sandbox, fn))
    return sb_db


def insert_fixtures(sb_db, pokemon_db, derived):
    """Insert the fixtures as synthetic in_bag rows, ranks written the way the ranker writes them.

    EVERY protection column keep_policy's data-completeness gate reads is set EXPLICITLY to 0. A NULL
    there would mark the row 'data_incomplete' and keep it unconditionally -- a fixture that passes
    because the engine could not judge it is a fixture that proves nothing. Same reasoning for the
    cosmetic/shiny/shadow/legendary/size columns: these mons must live or die on PvP alone.
    """
    con = sqlite3.connect(sb_db)
    cols = {r[1] for r in con.execute('PRAGMA table_info(pokemon)')}
    rows = []
    for i, fx in enumerate(FIXTURES):
        sid, gl, ul = derived[i]
        cp, lvl_idx = fixture_cp(pokemon_db, fx, sid)
        a, d, s = fx['ivs']
        r = {
            'uid_hex': 'REGRESSFIXTURE%03d' % i, 'in_bag': 1,
            'pokemon_id': fx['pid'], 'species_name': fx['species'], 'form': fx['form'],
            'form_region': fx['region'], 'gender': 1, 'nickname': None,
            'iv_atk': a, 'iv_def': d, 'iv_sta': s, 'iv_total': a + d + s,
            'iv_pct': round((a + d + s) / 45.0 * 100, 2), 'is_hundo': 0, 'is_zero': 0, 'is_component': 0, 'is_fusion': 0,
            'cp': cp, 'level': 1 + lvl_idx / 2.0, 'cp_multiplier': rc.CPM[lvl_idx],
            'num_additional_cpm': 0, 'height_m': 0.0, 'weight_kg': 0.0,
            'costume': 0, 'is_shiny': 0, 'alignment': 0, 'is_lucky': 0, 'is_traded': 0,
            'is_traded_flag_v2': 0, 'original_owner': None, 'original_owner_name': '',
            'is_favorite_v2': 0, 'is_deployed': 0, 'deployed_fort_id': '',
            'adventure_effects_left': 0, 'is_legendary': 0, 'is_mythical': 0,
            'is_ultra_beast': 0, 'is_paradox': 0, 'pokemon_size_category': 3,
            'costume_decoration_id': 0,
            # the data-completeness gate's columns, all explicitly present and unremarkable
            'fresh_shiny': 0, 'fresh_alignment': 0, 'fresh_costume': 0, 'fresh_form': fx['form'],
            'fresh_bread_mode': 0, 'fresh_natural_art_bg': 0, 'fresh_has_location_card': 0,
            'fresh_loc_card_enum': 0, 'fresh_is_strong': 0,
            # ranks exactly as rank_cache.compute_ranks would write them (NULL when unmappable)
            'gl_rank': gl['rank'] if gl else None, 'gl_pct': gl['pct'] if gl else None,
            'gl_stage': gl['stage'] if gl else None,
            'ul_rank': ul['rank'] if ul else None, 'ul_pct': ul['pct'] if ul else None,
            'ul_stage': ul['stage'] if ul else None,
        }
        missing = [k for k in r if k not in cols]
        if missing:
            con.close()
            raise SystemExit('FAIL setup: pokemon.db schema has no column(s) %s -- the fixture row '
                             'cannot be built. Re-run the crawl/migration.' % missing)
        rows.append(r)
    keys = sorted(rows[0])
    con.executemany('INSERT INTO pokemon (%s) VALUES (%s)'
                    % (','.join(keys), ','.join('?' * len(keys))),
                    [tuple(r[k] for k in keys) for r in rows])
    con.commit()
    con.close()
    return [r['uid_hex'] for r in rows]


def run_engine(sandbox, sb_db):
    """keep_policy.main(), UNMODIFIED, with every output path repointed into the sandbox.

    keep_policy resolves five paths: DB, TD (tagsets), ROOT (gamemaster / legacy / dex /
    policy_reasons.json / pile_provenance.json) and -- for the fodder_oracle export only -- its own
    __file__. All four patch targets are asserted to be inside the sandbox before main() is called,
    because the live pile is the one irreversible output in this system and a test that can write it
    is a hazard, not a test.
    """
    import keep_policy
    sb_td = os.path.join(sandbox, 'system', 'analysis', 'tagsets')
    patched = dict(DB=sb_db, TD=sb_td, ROOT=sandbox,
                   __file__=os.path.join(sandbox, 'system', 'scripts', 'keep_policy.py'))
    sbx = os.path.abspath(sandbox)
    for k, v in patched.items():
        p = os.path.abspath(v)
        if not (p == sbx or p.startswith(sbx + os.sep)):
            raise SystemExit('FAIL setup: refusing to run -- keep_policy.%s would resolve to %s, '
                             'which is OUTSIDE the sandbox %s' % (k, v, sandbox))
    saved = {k: getattr(keep_policy, k) for k in patched}
    buf = io.StringIO()
    err = None
    try:
        for k, v in patched.items():
            setattr(keep_policy, k, v)
        with contextlib.redirect_stdout(buf):
            keep_policy.main()
    except SystemExit as e:            # the engine's own ABORT tripwires are a RESULT, not a crash
        err = str(e)
    finally:
        for k, v in saved.items():
            setattr(keep_policy, k, v)
    pile, reasons = set(), {}
    pfile = os.path.join(sb_td, '6_Transfer.txt')
    rfile = os.path.join(sandbox, 'system', 'analysis', 'policy_reasons.json')
    if os.path.exists(pfile):
        pile = set(open(pfile, encoding='utf-8').read().split())
    if os.path.exists(rfile):
        reasons = json.load(open(rfile, encoding='utf-8'))
    return pile, reasons, buf.getvalue(), err


# ---------------------------------------------------------------------------------------------
# standing anchors (assertion C) -- pure math, no db, no engine
# ---------------------------------------------------------------------------------------------
def check_anchors(cache):
    """The numbers verified against the user's own app and two in-game screenshots."""
    out = []
    for ivs, want_rank, want_pct in (((12, 15, 13), 1108, 96.88), ((12, 13, 14), 1151, 96.82)):
        r = rc.compute_rank_for_iv(cache, 'mewtwo_armored', ivs[0], ivs[1], ivs[2], UL_CAP, False)
        got = (r['rank'], round(r['pct'], 2)) if r else (None, None)
        out.append(('Armored Mewtwo UL %d/%d/%d' % ivs, got == (want_rank, want_pct),
                    '#%s %s%%' % got, '#%d %.2f%%' % (want_rank, want_pct)))
    # HP = floor((base_sta + iv_sta) * cpm);  CPM index = (level - 1) * 2.  Armored Mewtwo base_sta=214.
    for lvl, iv_sta, want in ((27.5, 15, 160), (50.0, 13, 190)):
        got = math.floor((214 + iv_sta) * rc.CPM[int((lvl - 1) * 2)])
        out.append(('Armored Mewtwo HP iv_sta=%d @L%s' % (iv_sta, lvl), got == want, str(got), str(want)))
    return out


def check_cpm_split_brain(pokemon_db, derived):
    """D4: rank_cache.CPM[98]=0.84029995 vs pvp_iv_rule.CPM50=0.84029999 -- two values for one number.

    (compute_all_ranks.py carries the rank_cache value; those two must agree with each other or the
    primary and fallback rankers disagree outright. pvp_iv_rule uses its own copy for the maxcp
    viability test only.)

    Neither file is this test's to fix (a sibling owns them), so this does NOT fail on the mere
    disagreement, and it does not fail on cosmetic drift either. Every fixture rank is recomputed
    with the L50 constant swapped for the other file's value, and the failure condition is
    DECISION-RELEVANT drift only:
      * a rank crossing the READY_RANK boundary (<=N vs >N) -- that flips rules 15/15b, or
      * a different best-chain STAGE -- that flips the maxcp viability test.
    A one-place reshuffle deep in the pack (float noise between two values that differ at the 8th
    decimal) changes no keep decision, and a gate that goes red for it is a gate people learn to wave
    through -- which on an IRREVERSIBLE output is worse than no gate at all. The measured drift is
    reported either way, so the day it reaches the top of a league this fails instead of whispering.
    """
    live = rc.CPM[rc.MAX_LEVEL_IDX]
    if live == pvp_iv_rule.CPM50:
        return True, 'CPM L50 constants AGREE (%r) -- defect D4 resolved' % pvp_iv_rule.CPM50
    drift, decisive = [], []
    tmpdir = tempfile.mkdtemp(prefix='pogo_regress_cpm_')
    try:
        rc.CPM[rc.MAX_LEVEL_IDX] = pvp_iv_rule.CPM50
        alt = _rank_cache(open(GM_PATH, 'rb').read(), pokemon_db, tmpdir)
        for i, fx in enumerate(FIXTURES):
            sid, gl, ul = derived[i]
            for lab, cap, base in (('GL', GL_CAP, gl), ('UL', UL_CAP, ul)):
                b = _best_rank(alt, pokemon_db, sid, fx['ivs'], cap)
                r0, r1 = (base or {}).get('rank'), (b or {}).get('rank')
                s0, s1 = (base or {}).get('stage'), (b or {}).get('stage')
                if r0 == r1 and s0 == s1:
                    continue
                what = '%s %s: #%s via %s -> #%s via %s' % (fx['label'], lab, r0, s0, r1, s1)
                drift.append(what)
                ready = lambda r: (r is not None and r <= READY_RANK)
                if s0 != s1 or ready(r0) != ready(r1):
                    decisive.append(what)
    finally:
        rc.CPM[rc.MAX_LEVEL_IDX] = live
        shutil.rmtree(tmpdir, ignore_errors=True)
    if decisive:
        return False, ('CPM L50 split-brain (rank_cache %r vs pvp_iv_rule %r, defect D4) now changes a '
                       'KEEP-RELEVANT answer -- it crosses the ready_rank<=%d boundary or picks a '
                       'different chain stage: %s' % (live, pvp_iv_rule.CPM50, READY_RANK,
                                                      '; '.join(decisive[:6])))
    return True, ('CPM L50 split-brain still present (rank_cache %r vs pvp_iv_rule %r, defect D4). '
                  'MEASURED, not assumed: %d of %d fixture ranks shift under the other value%s -- none '
                  'crosses the ready_rank<=%d boundary and no chain stage changes, so no keep decision '
                  'moves. Still worth collapsing to one constant.'
                  % (live, pvp_iv_rule.CPM50, len(drift), 2 * len(FIXTURES),
                     (' (' + '; '.join(drift[:4]) + ')') if drift else '', READY_RANK))


SANDBOX_PREFIX = 'pogo_regress_pvp_'


def rmtree_hard(path, tries=4):
    """rmtree that actually works on Windows -- and SAYS SO when it does not.

    keep_policy.main() never closes its sqlite connection, and its many nested closures
    (cf/_vkey/_eff_cap/...) capture the enclosing frame, so the connection object sits in a reference
    CYCLE and refcounting alone never frees it. On Windows an open sqlite handle blocks deletion, so
    plain shutil.rmtree(ignore_errors=True) silently left a 19MB sandbox pokemon.db behind on EVERY
    run -- measured: 7 orphans, 133MB, after a single afternoon of testing. This gate runs on every
    full_audit, so a silent per-run leak is a disk filling up on its own. gc.collect() breaks the
    cycles first; the retry loop covers an indexer/AV racing us; and the return value is a REPORT,
    never a swallowed error.
    """
    gc.collect()
    for _ in range(tries):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return ''
        time.sleep(0.25)
        gc.collect()
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.exists(path):
        return ''
    left = [os.path.join(r, f) for r, _d, fs in os.walk(path) for f in fs]
    return ('sandbox %s could NOT be removed (%d file(s) still locked%s) -- delete it by hand; a '
            'later run of this test will sweep it.'
            % (path, len(left), (', e.g. ' + os.path.basename(left[0])) if left else ''))


def sweep_stale_sandboxes(max_age_s=3600):
    """Delete sandboxes an earlier crash (or the pre-2026-09-07 leak) left behind.

    Only directories with this script's own prefix, only in the system temp dir, only when untouched
    for an hour -- a live run finishes in seconds, so this can never remove a concurrent instance's
    tree. Best-effort and silent on error: cleanup must never be the reason a keeper gate fails.
    """
    swept = 0
    base = tempfile.gettempdir()
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for d in names:
        if not d.startswith(SANDBOX_PREFIX):
            continue
        p = os.path.join(base, d)
        try:
            if os.path.isdir(p) and (time.time() - os.stat(p).st_mtime) > max_age_s:
                shutil.rmtree(p, ignore_errors=True)
                swept += not os.path.exists(p)
        except OSError:
            pass
    return swept


# ---------------------------------------------------------------------------------------------
def live_artifact_hashes():
    """Fingerprint the live outputs this test must never write (belt-and-braces around the sandbox)."""
    out = {}
    for rel in ('system/analysis/tagsets/6_Transfer.txt', 'system/analysis/policy_reasons.json',
                'system/analysis/pile_provenance.json', 'system/analysis/fodder_oracle.json'):
        p = os.path.join(ROOT, rel)
        try:
            out[rel] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
        except OSError:
            out[rel] = None
    return out


def main():
    argv = sys.argv[1:]
    verbose = '-v' in argv or '--verbose' in argv
    keep_sandbox = '--keep-sandbox' in argv
    t0 = time.time()
    print('regress_pvp_keepers -- %d fixtures | ready_rank=%d viability_margin=%d gl_cap=%d ul_cap=%d'
          % (len(FIXTURES), READY_RANK, VIABILITY_MARGIN, GL_CAP, UL_CAP))

    gm_bytes = open(GM_PATH, 'rb').read()
    pokemon_db = {p['speciesId']: p for p in json.loads(gm_bytes.decode('utf-8'))['pokemon']}
    before = live_artifact_hashes()
    swept = sweep_stale_sandboxes()
    sandbox = os.environ.get('REGRESS_SANDBOX_DIR') or tempfile.mkdtemp(prefix=SANDBOX_PREFIX)
    fails, notes = [], []
    try:
        cache = _rank_cache(gm_bytes, pokemon_db, sandbox)

        # ---- setup sanity ------------------------------------------------------------------------
        # A fixture form that is (or becomes) a COSTUME routes to the cosmetic cap instead of the
        # plain pool and stops modelling the plain specimen that was actually lost.
        for fx in FIXTURES:
            if is_costume_form(fx['form']):
                fails.append('FAIL setup %s: form %d now classifies as a COSTUME, so the fixture no '
                             'longer models a plain specimen -- pick the plain form id for this species.'
                             % (fx['label'], fx['form']))

        # ---- A. rank math + form mapping ---------------------------------------------------------
        derived = [derive_ranks(cache, pokemon_db, fx) for fx in FIXTURES]
        for i, fx in enumerate(FIXTURES):
            sid, gl, ul = derived[i]
            for lab, got, want in (('GL', gl, fx['gl']), ('UL', ul, fx['ul'])):
                if want is None:
                    if got is not None:
                        fails.append('FAIL rank %s %s: expected NO rank (deliberately unresolvable '
                                     'species %r) but got #%d via %s -- the placeholder now resolves, so '
                                     'this fixture no longer tests the NULL-rank path.'
                                     % (fx['label'], lab, sid, got['rank'], got['stage']))
                    continue
                w_rank, w_pct, w_chain = want
                w_stage = w_chain.split('->')[-1]
                if got is None:
                    fails.append('FAIL rank %s %s: expected #%d via %s but the chain produced NO rank at '
                                 'all -- speciesId %r missing from the gamemaster, or the (species,form) '
                                 'mapping broke.' % (fx['label'], lab, w_rank, w_stage, sid))
                elif (got['rank'], round(got['pct'], 2), got['stage']) != (w_rank, w_pct, w_stage):
                    fails.append('FAIL rank %s %s: engine says #%d %.2f%% via %s, the audit recorded '
                                 '#%d %.2f%% via %s -- the stat-product math or the (species,form)->'
                                 'speciesId mapping changed.'
                                 % (fx['label'], lab, got['rank'], got['pct'], got['stage'],
                                    w_rank, w_pct, w_stage))

        # ---- C. standing anchors -----------------------------------------------------------------
        for name, ok, got, want in check_anchors(cache):
            if not ok:
                fails.append("FAIL anchor %s: got %s, expected %s -- this number was verified against "
                             "the user's own app and in-game screenshots; a change that breaks it is "
                             "wrong." % (name, got, want))
        ok, msg = check_cpm_split_brain(pokemon_db, derived)
        (notes if ok else fails).append(msg if ok else 'FAIL cpm: ' + msg)

        # ---- B. the engine's decision -------------------------------------------------------------
        sb_db = build_sandbox(sandbox)
        uids = insert_fixtures(sb_db, pokemon_db, derived)
        pile, reasons, log, engine_err = run_engine(sandbox, sb_db)
        if engine_err:
            # keep_policy's own tripwires ABORT rather than emit a bad pile, so a leak may surface as
            # an abort instead of a pile membership. Either way the run produced no usable answer.
            fails.append('FAIL engine: keep_policy ABORTED -- %s'
                         % engine_err.strip().replace('\n', ' ')[:400])
        elif not reasons:
            fails.append('FAIL engine: keep_policy produced no policy_reasons.json in the sandbox')

        print('%-31s %-8s %s' % ('FIXTURE', 'VERDICT', 'KEEP REASONS'))
        for i, fx in enumerate(FIXTURES):
            uid = uids[i]
            why = sorted(reasons.get(uid, []))
            saved_by = sorted(set(why) & fx['axis'])
            note = MARGIN_NOTE if fx['margin_sensitive'] else ''
            if uid in pile or not why:
                verdict = 'TRANSFER'
                fails.append('FAIL %s: the CURRENT engine puts this spread in the IRREVERSIBLE '
                             'Transfer pile. %s%s' % (fx['label'], fx['why'], note))
            elif not saved_by:
                verdict = 'WEAK'
                fails.append('FAIL %s: KEPT, but ONLY by %s -- no PvP axis fired (wanted one of %s). '
                             'That is protection by accident: the day that axis moves, this mon is '
                             'released. %s%s'
                             % (fx['label'], why, sorted(fx['axis']), fx['why'], note))
            else:
                verdict = 'KEEP'
            print('%-31s %-8s %-40s %s'
                  % (fx['label'][:31], verdict, ','.join(why) or '-',
                     ('saved by ' + ','.join(saved_by)) if saved_by else ''))
        if verbose:
            print('\n--- sandbox keep_policy log ---')
            for l in log.splitlines():
                print('   ' + l[:160])
    finally:
        if keep_sandbox:
            print('sandbox kept at %s' % sandbox)
        else:
            stuck = rmtree_hard(sandbox)
            if stuck:
                notes.append(stuck)
    if swept:
        notes.append('swept %d stale sandbox(es) left by an earlier run' % swept)

    moved = [k for k, v in live_artifact_hashes().items() if before.get(k) != v]
    if moved:
        # NOT a failure: autocull_watch.py and dashboard.py are live and legitimately rewrite these.
        # Every path this test writes was asserted to be inside the sandbox before the engine ran.
        notes.append('live artifact(s) changed DURING this run: %s -- expected when autocull/dashboard '
                     'are running (check system/analysis/autocull_watch.log and dashboard_run.log); '
                     'this test writes only inside its sandbox.' % ', '.join(moved))
    for n in notes:
        print('note: %s' % n)
    n_ms = sum(1 for f in FIXTURES if f['margin_sensitive'])
    print('caveat: %d of %d fixtures are keepers under ANY viability margin; the other %d (three Abra '
          '+ the Wailmer) qualify ONLY at viability_margin=0 (currently %d).'
          % (len(FIXTURES) - n_ms, len(FIXTURES), n_ms, VIABILITY_MARGIN))
    if fails:
        print('\n----- failures -----')
        for f in fails:
            print('  ' + f)
        print('VERDICT: *** %d PVP KEEPER FIXTURE CHECK(S) FAILED *** -- these are real spreads a '
              'correct engine keeps; do NOT sync a pile until this passes. (%.1fs)'
              % (len(fails), time.time() - t0))
        return 1
    print('VERDICT: ALL PVP KEEPER FIXTURES KEPT -- %d/%d lost-keeper spreads survive the current '
          'engine; ranks, form mappings and standing anchors all reproduce. (%.1fs)'
          % (len(FIXTURES), len(FIXTURES), time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
