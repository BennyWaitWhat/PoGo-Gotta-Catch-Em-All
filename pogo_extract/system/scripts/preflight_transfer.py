"""preflight_transfer.py -- comprehensive, reusable PRE-FLIGHT for the irreversible Transfer pile.

The Transfer set (system/analysis/tagsets/Transfer.txt) is the ONE irreversible bulk-release
output: the human reads it and mass-transfers those uids in-game. A single keeper that leaks in
gets a trophy destroyed (the Mareep / GL#1 failure mode). keep_policy.py builds the pile and has
its own tripwires, but this is an INDEPENDENT second set of eyes that re-derives EVERY keep axis
straight from pokemon.db (and reads DEPLOYMENT LIVE off the proto) and refuses to bless a pile that
contains a real keeper.

It NEVER mutates anything. It classifies each Transfer uid into one of:

  PLAIN          -- ordinary fodder. Expected. Safe.
  COSTUME_EXCESS -- a cosmetic (costume / art background / decoration / DYNAMAX / GIGANTAMAX) whose
                    variant group is over ITS cap and this one is past the top-cap by IV. Expected
                    (rule 1a caps, all read live from keep_config -- never hardcoded here).
  SHINY_EXCESS   -- a shiny whose (species,form) is over its PER-SPECIES shiny cap and this one is
                    past the top-cap by IV. Expected (rule 3, the gym-spam cap).
  XXL_EXCESS     -- a size-5 mon outside the per-(species, cf(form)) showcase top-N. Expected (rule 7).
  LEGACY_EXCESS  -- a legacy-move mon of a species with a per-species legacy cap, past that cap.
                    Expected (rule 6; keeps specials + best GL + best UL, then fills by IV).
  GYM_LOCKED     -- RETIRED 2026-09-24 (user: "3. sure"). It excused a KEEPER sitting in a gym: filed here
                    instead of REAL_KEEPER, it PASSED, got the Transfer tag, and became releasable the moment
                    it was knocked out. A keeper in a gym is now a REAL_KEEPER like any other, deployment is
                    no longer read, and this gate makes NO phone contact (the mid-pass re-walk is gone).
  REAL_KEEPER    -- earns a keep axis and is NOT cap-excess and NOT gym-locked. THE ALARM. Any of
                    these => exit(1).
  EGG            -- is_egg != 0, or an is_egg nobody wrote once the column has a live writer. A
                    fail-closed DATA bucket, not a keep axis: an egg is not a bag pokemon, earns no
                    axis at all, and would otherwise read as PLAIN fodder. => exit(1).
  FUSED          -- (2026-09-26) a Reshiram / Zekrom HELD inside a fused White / Black Kyurem
                    (keep_config.is_fused_component). The engine keeps it as 'fused' and it is never a pile
                    candidate: the game cannot release it while fused. A BLOCK, like EGG. => exit(1).
                    Fused components hold no ladder slot, so every re-derivation below runs WITHOUT them.

EVERY cap above is read from keep_config at run time, including the PER-SPECIES overrides. Hardcoding
one, or using the global cap where a per-species override exists, makes this report lie about the pile
immediately before an irreversible mass release -- that is the recurring bug class this file guards.

A REAL_KEEPER is any of (UNCONDITIONAL axes -- each re-derived here, independent of keep_policy):
  hundo (iv_total==45) / nundo (iv_total==0) /
  origin (E+F-only lucky/traded; non-E+F luckies/trades are NORMAL per user, transfer like plain) /
  legacy (legacy_accurate.json or Legacy_Moves.txt) / event (Event.txt) /
  mighty (fresh_is_strong) / adventure_effect (effects_left>0 OR the AE roster pid -- audit F2) /
  location_card (fresh_has_location_card -- the Event.txt route is vacuous for leaks; verifier 2026-06-09) /
  pvp_spread (configured trophy spreads) / dex_only_copy (sole copy of its SPECIES) /
  dex_only_form (sole copy of its species+normalized-form -- audit F8) / protected (keep-all pids) /
  rank<=READY_RANK for a CP-VIABLE evolved league form (GL or UL; OVER-PROTECTS if the
    gamemaster fails to load -- never silently passes a rank<=5) /
  pvp_chain -- ANY stage in the chain that is top-N AND cap-viable, not just the stage that won the
    rank contest (a pre-evo can win on itself while a later, viable stage is the real keeper) /
  pvp_unknown -- BOTH gl_rank and ul_rank are NULL, so no PvP check could run at all. Unknown data
    must read as PROTECTED, never as "no PvP value". /
  pvp_best_gl / pvp_best_ul / pvp_best_ml -- the best-GL / best-UL / best-ML NON-SHADOW copy of its PvP IDENTITY
    (species + battle form; LAW bucket 2b, 2026-09-23). GL / UL are USABLE ONLY: a copy competes with a stage it can
    reach AND enter (its CP there at its true level inside the cap), key (that stage reaches the cap first, its rank,
    uid_hex). A best-of-1 rule, not a top-N cap, so it IS re-derived here (_pvp_best_uids).
NOTE (deliberate trust boundary, 2026-06-08): the CAPPED axes -- shiny top-N, cosmetic/Dynamax/Gmax
  variant caps, XXL, rarity top-N, shadow -- are NOT re-derived here. keep_policy owns the cap maths
  (cf()-normalized); a cap-EXCESS copy in the pile is the user's deliberate trim and classifies as
  SHINY_EXCESS / COSTUME_EXCESS / XXL_EXCESS, never REAL_KEEPER. Legendaries do NOT alarm
  unconditionally anymore -- a piled legendary alarms only via another axis (hundo/AE/origin/...).

Run: python system/scripts/preflight_transfer.py   (--allow-no-live-deployment is accepted and ignored since 2026-09-24)
Exit 0 = pile is clean (only PLAIN / *_EXCESS).
Exit 1 = a REAL_KEEPER (deployed or not), OR an EGG (or unwritten is_egg) in the pile, OR a FUSED component in the
         pile, OR a uid missing from pokemon.db.

ARTIFACT (2026-09-07): a PASS now also writes system/analysis/preflight_stamp.json -- the producer
half of the preflight-stamp contract. Until today this gate's verdict existed ONLY as an exit code,
so nothing downstream could prove it had ever run, and system/scripts/prune_tags.py could push the
live Transfer tag with no evidence the pile had been inspected. The stamp is written ONLY on a full
PASS and DELETED on every other path; prune_tags refuses (exit 2) without a fresh matching one.
See the PREFLIGHT STAMP block below for the fields and the fail-closed reasoning.

(Frida is serial: this script reads deployment live, so run it ALONE -- never alongside another
Frida session. The verify phase runs it; do not run two at once.)
"""
# STDLIB, PART 1 -- os and sys ONLY, because every line below them runs BEFORE the stamp is
# destroyed. This is the ENTIRE pre-guard surface of the file and it is deliberately as close to
# zero as Python allows: two imports that cannot fail, two os.path calls, one join, one def.
# Everything that CAN fail -- json/hashlib/sqlite3/datetime, and the project imports far below --
# is imported AFTER the invalidation. (hoisted 2026-09-07: the FAIL CLOSED note below claimed
# every non-PASS path leaves no receipt BY CONSTRUCTION, but a SyntaxError or a stdlib import
# failure ABOVE the old guard killed the process before the delete and left a stale stamp that
# prune_tags would honour for a full 30 minutes -- Transfer.txt unchanged, so the hash matched.)
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # .../pogo_extract

# =================================================================================================
# PREFLIGHT STAMP -- producer half of the preflight-stamp contract (schema 1).
#
# The problem it fixes: this gate's verdict used to exist ONLY as an exit code. Nothing downstream
# could ask "was THIS pile actually inspected?", so system/scripts/prune_tags.py -- a live route to
# the phone Transfer tag -- had nothing to check. The gate was not so much bypassed as
# UNOBSERVABLE. So a full PASS now leaves a receipt, and prune_tags refuses (exit 2) to push the
# Transfer tag unless that receipt exists, matches, and is fresh.
#
#   pile_sha256    sha256 of the EXACT bytes of tagsets/Transfer.txt THIS run vetted, i.e.
#                  hashlib.sha256(open(TRANSFER_TXT, 'rb').read()).hexdigest() -- RAW bytes. The
#                  file is CRLF, so a text-mode re-read would hash different bytes; the consumer
#                  must open it 'rb' too. Read ONCE here and reused, because autocull_watch
#                  rewrites the pile on a 5-minute tick and hashing a second read could stamp
#                  bytes this run never looked at.
#   pile_uids      how many uids were vetted (cheap human-readable cross-check)
#   config_sha256  keep_config.fingerprint() -- the MERGED config, '_note' excluded, not file bytes
#   db_sha256      the 'db_content_sha256' value from system/analysis/pile_provenance.json
#   generated      UTC ISO-8601, '%Y-%m-%dT%H:%M:%SZ' (no microseconds, 'Z' not '+00:00')
#   schema         1
#
# FAIL CLOSED -- and the load-bearing half of that is the DELETE, not the write: a stamp left over
# from an EARLIER passing run must never authorise a LATER, different pile. Rather than enumerate
# every exit and hope none was missed, the invalidation is structural:
#
#     the stamp is destroyed as the FIRST executable statement of a real run -- above even the
#     project imports below, which can themselves raise -- and is (re)created in exactly ONE
#     place, _write_stamp(), on the final PASS line of main().
#
# So every other path leaves no stamp BY CONSTRUCTION: the missing-Transfer.txt sys.exit(1) in
# _load_transfer_uids, the empty-pile early return, the REAL_KEEPER / EGG / MISSING_FROM_DB /
# dead-Frida sys.exit(1)s, an ImportError at module load, any uncaught exception, and Ctrl-C.
# The __main__ guard at the bottom of the file re-invalidates on any non-zero exit or exception as
# belt-and-braces, so a future edit that adds code AFTER the write cannot leave one behind either.
# =================================================================================================
STAMP_PATH = os.path.join(ROOT, 'system', 'analysis', 'preflight_stamp.json')



def _ae_roster_union():
    """keep_config.adventure_effect_pids UNION the species derived from the game's live registry
    (system/analysis/ae_roster_derived.json, written by derive_ae_roster.py after each recrawl). Mirrors
    keep_policy._ae_ids_live so the GATE knows every Adventure-Effect species the ENGINE knows -- union
    only (adds protection, never removes), fail-soft to the hand list. (2026-09-08)"""
    ids = set(keep_config.ae_pids())
    try:
        import json as _j, time as _t
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analysis', 'ae_roster_derived.json')
        if os.path.exists(_p) and (_t.time() - os.path.getmtime(_p)) < 14 * 86400:
            ids |= {int(x) for x in _j.load(open(_p, encoding='utf-8')).get('species', [])}
    except Exception:
        pass
    return ids

def _ae_sids_union():
    """FORM-level Adventure-Effect roster (derive_ae_roster.py schema 2 'species_ids'), None when unavailable --
    mirrors keep_policy._ae_sids_live exactly. With it, a base-form Dialga in the pile is NOT an AE keeper
    (2026-09-09); without it the gate falls back to the species list (over-protects)."""
    try:
        import json as _j, time as _t
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analysis', 'ae_roster_derived.json')
        if os.path.exists(_p) and (_t.time() - os.path.getmtime(_p)) < 14 * 86400:
            sids = set((_j.load(open(_p, encoding='utf-8')).get('species_ids') or {}).keys())
            if sids:
                return sids
    except Exception:
        pass
    return None


def _ae_hit(r):
    # PER MON (2026-09-23): the specimen KNOWS an Adventure-Effect move (ae_moves, live registry) -- mirrors
    # keep_policy rule 8. Only an unreadable registry falls back to the form / species roster below.
    import ae_moves as _aem
    _ids = _aem.move_ids()
    if _ids is not None:
        return bool(_aem.known(r, _ids))
    sids = _ae_sids_union()
    if sids is not None:
        from pvp_iv_rule import pvid as _pv          # local: pvid is not a module-level import here
        return _pv(r['species_name'], r['form'] or 0) in sids   # r is a sqlite3.Row: index, never .get()
    return r['pokemon_id'] in _ae_roster_union()


def _invalidate_stamp(why=''):
    """Destroy any existing stamp. Idempotent, and NEVER raises -- an invalidation that blew up
    mid-teardown would be the one failure mode that leaves a stale receipt behind."""
    try:
        os.remove(STAMP_PATH)
    except FileNotFoundError:
        return False                      # nothing there: the normal, quiet case
    except OSError as e:
        # Cannot delete => a stale stamp may survive => the DANGEROUS direction. Never silent.
        sys.stderr.write("!! preflight: COULD NOT DELETE stale %s (%s) -- delete it BY HAND "
                         "before any prune_tags push.\n" % (STAMP_PATH, e))
        return False
    sys.stderr.write("preflight: invalidated previous %s%s\n"
                     % (os.path.basename(STAMP_PATH), (' -- %s' % why) if why else ''))
    return True


if __name__ == '__main__':
    # FIRST executable statement of a real run. Deliberately ABOVE the project imports below: if
    # cpm_table / keep_config / costume_forms fails to import, this process dies before main() and
    # a stamp from a previous run would otherwise survive to authorise a pile nobody vetted.
    # invalidation moved into main() (2026-09-12) so a stamp that is FRESH AND IDENTICAL (same pile bytes,
    # config fingerprint and DB content, < 120 s old) can be reused instead of a second live gym read: the
    # recrawl pipeline and the sync job both run this gate back-to-back on the same inputs. prune_tags still
    # re-checks all three hashes and the age, so a leftover stamp can only ever match its own inputs.
    pass


# STDLIB, PART 2 -- everything from here down is now UNREACHABLE before the invalidation above,
# which is the whole point of the split. Nothing here is optional to the run; it is ordered this
# way purely so that its failure cannot outlive the stamp.
import json
import hashlib
import sqlite3
import datetime as _dt
from collections import defaultdict

# project imports (costume_forms / keep_config / cpm_table) resolve against ROOT:
sys.path.insert(0, ROOT)

PROVENANCE = os.path.join(ROOT, 'system', 'analysis', 'pile_provenance.json')
STAMP_SCHEMA = 2        # 2 (H03, 2026-09-29): + walk_fp -- the walk the pile was judged on, and whether it was live


def _walk_fp():
    """The walk tripwires' record of the walk this pile was built from (the DB's MAX(last_scanned)), or None. The
    stamp carries it so prune_tags can refuse a pile judged on a walk nobody proved live: on 2026-09-29 the 05:06 /
    05:09 / 05:11 piles were built from a frozen graph and each got a valid PASS stamp -- pile, config and db hashes
    all matched, because the pile, the config and the (frozen) db agreed with one another."""
    import sqlite3
    try:
        import walk_tripwires
        c = sqlite3.connect('file:%s?mode=ro' % os.path.join(ROOT, 'pokemon.db').replace(os.sep, '/'), uri=True)
        walk = c.execute('SELECT MAX(last_scanned) FROM pokemon WHERE in_bag=1').fetchone()[0]
        c.close()
        fp = next((f for f in reversed(walk_tripwires.history()) if f.get('walk_iso') == walk), None)
    except Exception:
        return None
    if not fp:
        return None
    g, sv = fp.get('graph') or {}, (fp.get('services') or {}).get('svc') or {}
    return {'walk_iso': fp.get('walk_iso'), 'pid': fp.get('pid'), 'trainer': fp.get('trainer'),
            'graph_player': g.get('player'), 'graph_ts': g.get('ts'), 'phone_now_ms': fp.get('phone_now_ms'),
            'svc': sv.get('addr'), 'verdict': fp.get('verdict')}


def _write_stamp(pile_sha256, pile_uids):
    """Write the PASS receipt ATOMICALLY. Called from exactly ONE place: the final PASS of main().

    Never raises, and never changes the verdict: a stamp that cannot be written is not a pile
    problem, and flipping a correct PASS into a FAIL would be exactly the "changed the verdict"
    regression this change is forbidden to make. The ABSENCE of a stamp is already the safe state
    (prune_tags refuses without one), so on any error we shout, guarantee nothing partial or stale
    survives, and leave the exit code alone.
    """
    tmp = None
    try:
        with open(PROVENANCE, encoding='utf-8') as f:
            prov = json.load(f)
        db_sha = prov.get('db_content_sha256')
        if not db_sha:
            raise ValueError('pile_provenance.json carries no db_content_sha256')
        stamp = {
            'pile_sha256': pile_sha256,
            'pile_uids': int(pile_uids),
            'config_sha256': keep_config.fingerprint(),
            'db_sha256': db_sha,
            'generated': _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'schema': STAMP_SCHEMA,
            'gate_sha256': _gate_sha256(),                     # which gate code judged this pile (H08, reuse check)
            'walk_fp': _walk_fp(),     # H03: None is written as-is -- prune_tags refuses it, the verdict here is unchanged
        }
        tmp = '%s.tmp.%d' % (STAMP_PATH, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(stamp, f, indent=1, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STAMP_PATH)       # atomic swap: a half-written stamp is never visible
        tmp = None
        print("STAMP: wrote %s  (pile_sha256=%s pile_uids=%d config=%s db=%s generated=%s)"
              % (os.path.relpath(STAMP_PATH, ROOT), stamp['pile_sha256'][:16], stamp['pile_uids'],
                 stamp['config_sha256'][:16], stamp['db_sha256'][:16], stamp['generated']))
        return True
    except Exception as e:
        _invalidate_stamp('stamp write failed')
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        print("!! STAMP NOT WRITTEN (%s) -- the pile verdict above still stands, but prune_tags"
              " will REFUSE to push Transfer without a stamp. Fix the cause and re-run." % e)
        return False


from costume_forms import is_costume_form
import evolvable_forms   # BREAD_MODES / max_axis: the game's own Max-mode names
import keep_config   # single source of truth for caps (cosmetic/dmax/gmax/shiny/xxl)

try:
    from pvp_iv_rule import pvid as _PVID   # regional-form-code detection for the cf() mirror
except Exception:                           # pragma: no cover -- defensive
    _PVID = None


def _g(r, col, default=None):
    """Safe sqlite3.Row column access -- returns default if the column is absent."""
    return r[col] if col in r.keys() else default

# ---- caps (source of truth = keep_policy.py; mirrored here for the independent re-derivation) ----
COSMETIC_CAP = int(os.environ.get('COSMETIC_CAP') or keep_config.cap('cosmetic'))   # keep_config.json (env still overrides)
DMAX_CAP = keep_config.cap('dynamax')                    # Dynamax(bread=1) cap (keep_config.json)
GMAX_CAP = keep_config.cap('gigantamax')                 # Gigantamax(bread=2) cap (keep_config.json)
SHINY_CAP = keep_config.cap('shiny')                     # GLOBAL default only -- see _shiny_cap()
XXL_CAP = keep_config.cap('xxl')                         # GLOBAL default only -- see _xxl_cap()


# keep_config carries PER-SPECIES cap overrides (per_species_caps) and keep_policy honours them.
# Using the GLOBAL cap here made the report lie: pid 130 (Gyarados) has a shiny cap of 20 and 21
# shinies in the bag, so the engine keeps 20 -- but this gate believed 10 and would have labelled
# ten IN-CAP shinies "past the top-10 cap". A human reads that label immediately before an
# irreversible mass release. (lockdown 2026-09-02)
def _shiny_cap(pid):
    return keep_config.species_cap('shiny', pid, SHINY_CAP)


def _shiny_plain_cap(pid):
    """At most cap('shiny_plain') PLAIN shinies inside the shiny cap (user 2026-09-23); a species with its own
    per_species_caps.shiny exception keeps that whole exception for plains too (keep_policy rule 3)."""
    if keep_config.species_cap('shiny', pid, None) is not None:
        return _shiny_cap(pid)
    return min(_shiny_cap(pid), keep_config.cap('shiny_plain'))


def _shiny_is_special(r):
    """keep_policy._scollect non-empty: a background, location card, costume / costume form, Max mode or shadow."""
    return bool((r['fresh_natural_art_bg'] or 0)
                or (r['fresh_has_location_card'] and (r['fresh_loc_card_enum'] or 0))
                or (r['fresh_costume'] or 0)
                or is_costume_form(r['fresh_form']) or is_costume_form(r['form'])
                or evolvable_forms.max_axis(r['fresh_bread_mode'])
                or r['fresh_alignment'] == 1)


def _xxl_cap(pid):
    return keep_config.species_cap('xxl', pid, XXL_CAP)

# Explicit opt-in to accept a DB-only verdict when the LIVE gym read is unavailable. Without it a
# failed deployment read is a FAIL, so the gate can never report a check it did not run. 2026-09-02
_ALLOW_NO_LIVE_DEPLOYMENT = ('--allow-no-live-deployment' in sys.argv
                             or os.environ.get('PREFLIGHT_ALLOW_NO_LIVE_DEPLOYMENT') == '1')

DB = os.path.join(ROOT, 'pokemon.db')
TRANSFER_TXT = os.path.join(ROOT, 'system', 'analysis', 'tagsets', 'Transfer.txt')
GAMEMASTER = os.path.join(ROOT, 'pvpoke_gamemaster.json')
LEGACY_JSON = os.path.join(ROOT, 'legacy_accurate.json')

# E+F roster -- the origins keep_policy protects on traded/lucky (rule 8). A traded/lucky mon from
# one of these owners is the user's "keep" origin; we ALSO alarm on ANY lucky/traded below (broader
# than keep_policy on purpose -- a pre-flight should over-protect, never under-protect, the one
# irreversible pile). This set is only used to label WHY in the report.
EF_OWNERS = keep_config.origin_owners()   # config-driven (dashboard-editable) -- the gate MUST track the same owners keep_policy uses, else it under-protects a newly-added origin owner


# Game constants (L50 CPM + league CP caps) come from cpm_table.py, the single source of
# truth. Imported OUTSIDE the try/except below on purpose: that fallback exists for a
# pvp_iv_rule import failure, and cpm_table has no dependencies of its own. If IT cannot
# load, this pre-flight must abort loudly rather than substitute a stale literal for the
# constant that decides the irreversible pile.
from cpm_table import CPM50 as _CANON_CPM50, GL_CAP as _CANON_GL_CAP, UL_CAP as _CANON_UL_CAP

# ---- PvP viability (top-5 rank only counts if the evolved form can actually reach the league cap) ----
# Prefer the project's single source of truth; fall back to a clearly-labelled local re-impl if absent.
try:
    from pvp_iv_rule import maxcp as _pvp_maxcp, READY_RANK, GL_CAP, UL_CAP, VIABILITY_MARGIN
    from pvp_iv_rule import plays as _plays      # rule 15b's "this copy can PLAY it" test (2026-09-30)
    _HAVE_VIABILITY = True
    _VIABILITY_NOTE = "pvp_iv_rule (maxcp/READY_RANK/GL_CAP/UL_CAP/VIABILITY_MARGIN)"
except Exception as _e:                                   # pragma: no cover -- defensive
    # Read the tunables from keep_config, NOT hardcoded literals: a hardcoded READY_RANK=5 would
    # silently ignore a dashboard change to ready_rank and judge the pile against the wrong rule.
    # (The old literals also disagreed with the note printed in the report header, which claimed
    # "margin 100" while the code set 0.) keep_config is already imported above. 2026-09-02
    READY_RANK = keep_config.pvp('ready_rank')
    VIABILITY_MARGIN = keep_config.pvp('viability_margin')
    GL_CAP, UL_CAP = _CANON_GL_CAP, _CANON_UL_CAP   # league CP caps -- game constants, not policy knobs
    _CPM50 = _CANON_CPM50
    _UNKNOWN_MAXCP = 10 ** 9           # mirrors pvp_iv_rule.UNKNOWN_MAXCP: unknown => VIABLE => protected

    def _pvp_maxcp(sid, BS):
        b = BS.get(sid)
        # NOT 0 on a miss. Returning 0 made an unjudgeable stage read as "not viable", i.e. PvP
        # protection OFF for missing data -- unknown must default to PROTECTED.
        return (int(((b.get('atk', 0) + 15) * (b.get('def', 0) + 15) ** 0.5
                     * (b.get('hp', 0) + 15) ** 0.5 * _CPM50 ** 2) / 10) if b else _UNKNOWN_MAXCP)
    _HAVE_VIABILITY = False
    _plays = None                      # no shared rule -> the rank alarm below over-protects (CP-blind, as before)
    _VIABILITY_NOTE = ("LOCAL FALLBACK (pvp_iv_rule import FAILED: %s) -- READY_RANK=%d, caps "
                       "%d/%d, margin %d (all from keep_config)"
                       % (_e, READY_RANK, GL_CAP, UL_CAP, VIABILITY_MARGIN))


def _viable(stage, cap, BS):
    """A ranked stage is league-VIABLE iff its L50-hundo CP clears the cap WITH headroom; otherwise
    the stat-product rank is degenerate (an under-cap species pins every IV to L50 so the hundo ranks
    #1) -- e.g. Ivysaur 'ranks' UL but maxes ~1921 < 2600 => NOT a real UL keeper."""
    return bool(stage) and _pvp_maxcp(stage, BS) > cap + VIABILITY_MARGIN


# ---- helpers ----
def _load_transfer_uids():
    """Return (uids, pile_sha256) from ONE read of Transfer.txt.

    The bytes are read once and both the uid list and the stamp hash are derived from that single
    snapshot. Re-opening the file to hash it would be a race, not a convenience: autocull_watch
    rewrites the pile on a 5-minute tick, so a second read can return different bytes and the stamp
    would then vouch for a pile this run never inspected -- the precise failure the stamp exists to
    prevent. The hash is over the RAW bytes (the file is CRLF); the consumer must open 'rb' too.
    """
    if not os.path.exists(TRANSFER_TXT):   # missing pile must REFUSE the sync, not silently open the gate (ultrareview 2026-06-08)
        print("Transfer.txt not found at %s -- run keep_policy + build_tagsets first; refusing to sync." % TRANSFER_TXT)
        sys.exit(1)
    with open(TRANSFER_TXT, 'rb') as f:
        raw = f.read()
    # decoded exactly as the old text-mode read did (utf-8, and .strip() was already line-ending agnostic)
    uids = [ln.strip() for ln in raw.decode('utf-8').splitlines() if ln.strip()]
    return uids, hashlib.sha256(raw).hexdigest()


def _tagset(auth_tag_names):
    """auth_tag_names is a comma/semicolon-joined list of human tag names ('Hundo', 'Event', ...)."""
    if not auth_tag_names:
        return set()
    return {t.strip() for t in str(auth_tag_names).replace(';', ',').split(',') if t.strip()}


def _is_cosmetic(r):
    """A mon is COSMETIC if ANY cosmetic axis is set (mirrors the project KEY).

    Dynamax / Gigantamax (fresh_bread_mode 1/2) ARE cosmetic-cap axes here: _cosmetic_variant_key
    carries the bread bundle and the classifier picks DMAX_CAP/GMAX_CAP off key[-1]. Omitting them
    from this predicate meant cos_groups never contained a bread mon, so those two branches were
    UNREACHABLE and DMAX_CAP/GMAX_CAP were dead constants -- a piled Gigantamax printed in the
    PLAIN bucket, i.e. the human read "ordinary fodder" about a Gmax. 276 bread mons in the bag
    classified as non-cosmetic before this fix. (lockdown 2026-09-02)
    """
    return bool(
        (r['fresh_costume'] or 0)
        or is_costume_form(r['form'])
        or is_costume_form(r['fresh_form'])
        or (r['fresh_natural_art_bg'] or 0)   # fresh_ col -- non-fresh holds garbage on 7 real rows (audit F1)
        or (_deco(r) != 0)
        or bool(evolvable_forms.max_axis(r['fresh_bread_mode']))   # any Max mode (evolvable_forms.BREAD_MODES)
    )


def _deco(r):
    """costume_decoration_id normalized to an int. The column is TEXT on every row, so the bare
    `or 0` used by _cosmetic_variant_key left '0' truthy while _is_cosmetic's `not in (0,'0',None)`
    treated it as unset -- two different answers for the same field. 0 rows split today; normalize
    both so they cannot diverge later. (lockdown 2026-09-02)"""
    v = r['costume_decoration_id']
    if v in (None, '', 0, '0'):
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return v   # unparseable -> keep it truthy: unknown cosmetic data must not read as "plain"


def _cosmetic_variant_key(r):
    """The per-variant cap key (mirror of keep_policy rule 1a vg key, minus the form-collapse which
    is irrelevant for cosmetics): species x every cosmetic axis x bread-mode bundle."""
    return (
        r['pokemon_id'],
        r['form'] or 0,
        r['fresh_costume'] or 0,
        0,   # special_bg_id retired -- garbage column
        r['fresh_natural_art_bg'] or 0,   # fresh_ col (audit F1)
        _deco(r),                          # normalized: TEXT '0' must not split a group off (2026-09-02)
        r['fresh_bread_mode'] or 0,   # every Max mode is its own bundle
    )


def _ivkey(r):
    """Sort key matching keep_policy.topn: highest iv_total, then highest cp, then uid_hex.

    The uid_hex tiebreak is NOT decorative -- keep_policy.topn added it (audit F25) because
    stat-identical dupes otherwise fall to SQLite rowid order, which a recrawl can reshuffle.
    Without it this gate's cap replica could disagree with the engine purely by row order.
    (lockdown 2026-09-02)"""
    return (-(r['iv_total'] or 0), -(r['cp'] or 0), r['uid_hex'])


def _capnote(within_cap):
    """Annotation for an EXCESS label when THIS gate's cap replica disagrees with keep_policy.

    The three *_within_cap flags used to be computed and thrown away (`_ = (a, b, c)`). They are
    not alarms -- keep_policy owns the cap maths and a cap-excess release is the user's deliberate
    trim -- but when this replica says a piled mon is INSIDE its cap, the flat "past the cap" claim
    in the label is not true, and a human reads that label immediately before an irreversible
    release. Report the disagreement instead of discarding it. Informational only: it can never
    turn a PLAIN into a FAIL. (2026-09-02)"""
    return ('' if not within_cap else
            "  [NOTE: this gate's cap replica puts it INSIDE the cap -- keep_policy trimmed it on"
            " another axis (dominance collapse / stage cap). Not an alarm; verify if unexpected.]")


def _is_xxl(r):
    """XXL by keep_policy's canonical column (pokemon_size_category==5, rule 7), OR the parallel
    size_enum column so a NULL/short-read category cannot hide one.

    (The old docstring also claimed an 'XXL auth tag' fallback -- the body never implemented one,
    and must not: auth_tag_names lags until set_db runs, so it is not a valid protection input
    inside the pipeline. Corrected 2026-09-02.)"""
    return (r['pokemon_size_category'] or 0) == 5 or (r['size_enum'] or 0) == 5   # fresh DB size cols only (auth_tag lags)


def _showcase_score(r, gmaxh, gmaxw):
    """Niantic showcase score = height*0.80 + weight*0.15 + IV*0.05, normalized by the group max
    (monotonic -> top-2 exact). Mirrors keep_policy rule 7 (user 2026-06-08)."""
    # THE GAME'S POINTS (2026-09-23): size_line.showcase_points -- Pokemod's formula, verified on screen. The old
    # group-max ordering stays only for a template size_line does not know.
    import size_line as _sl
    _p = _sl.best_points(r)   # evolution counts (2026-09-24)
    if _p is not None:
        return _p
    _w = keep_config.showcase_weights()
    return (_w['height'] * ((r['height_m'] or 0) / gmaxh) + _w['weight'] * ((r['weight_kg'] or 0) / gmaxw)
            + _w['iv'] * ((r['iv_total'] or 0) / 45))


def _xxl_kept_uids(bag, cf_norm):
    """Mirror keep_policy rule 7: per (species, cf(form)) keep the TOP-N by SHOWCASE SCORE.

    THREE bugs fixed here 2026-09-02 -- this replica disagreed with the engine three ways:
      1. `key=lambda x: -_showcase_score(r, ...)` scored the ENCLOSING loop variable `r`, not the
         item `x`. That makes the sort key a CONSTANT, so `sorted` was a no-op and the "top-N"
         was just the first N rows in DB order. The identical typo was already fixed in
         keep_policy.py:565 and build_tagsets.py:78 -- this third mirror was missed. Fixing it
         alone moves 2 uids in the current bag.
      2. it used the GLOBAL cap('xxl') instead of keep_config.species_cap, so a per-species XXL
         override was ignored.
      3. it grouped by RAW `form`, while keep_policy groups by cf(form) (the form-0 collapse).
         Raw-form grouping split one species into two groups and handed out an extra cap slot.
    With all three fixed this replica reproduces keep_policy's xxl set exactly.
    """
    # XXL (2026-09-23): per PvP identity (species + battle form), XXL badge only, by the game's points -- rule 7.
    from pvp_iv_rule import pvid as _sc_pvid
    import size_line as _slx
    _SC_MIN = keep_config.showcase_weights()['min_points']
    def _sc_ok(r):
        """A showcase WINNER (user 2026-09-23: "keep pokemon that score over 1000"): points >= min_points. An unknown
        template scores None -> protected (unknown data is never fodder)."""
        _p = _slx.best_points(r)   # evolution counts (2026-09-24)
        return _p is None or _p >= _SC_MIN
    groups = defaultdict(list)
    for r in bag:
        if _is_xxl(r) and r['height_m'] is not None and r['weight_kg'] is not None and _sc_ok(r):
            groups[_sc_pvid(r['species_name'], r['form'] or 0)].append(r)
    # ONE SELECTION (2026-09-29): exactly keep_policy rule 7 (+ per type during an XXL trim) -- and, as before, an XXL
    # badge that only the parallel size_enum column shows (NULL/short-read category) stays protected.
    kept = set(_slx.xxl_keepers(bag)) | {r['uid_hex'] for r in bag if _is_xxl(r) and (r['pokemon_size_category'] or 0) != 5}
    return kept, groups


# ---- LIVE deployment read (VALIDATED 2026-06-06 -- finds both deployed shiny Gyarados) ----
# DB is_deployed / deployed_fort_id / deployed_gym_lat|lng are parsed from a STALE snapshot and are
# unreliable; deployment MUST be read live off the proto gym-coord doubles at proto+0x140 (lat) /
# proto+0x148 (lng). Non-zero (either) = currently deployed.
_JS = '''rpc.exports.readgym = function (ptrs) {
  var out = [];
  for (var i = 0; i < ptrs.length; i++) { try { var p = ptr(ptrs[i]);
    var lat = p.add(0x140).readDouble(); var lng = p.add(0x148).readDouble();
    if (lat !== 0.0 || lng !== 0.0) out.push([ptrs[i], lat, lng]); } catch (e) {} }
  return out; };'''


def live_deployed_uids():
    """Return the set of uid_hex (16-char, zero-padded) currently deployed in a gym, read LIVE.
    On any Frida failure, RAISE -- a pre-flight that silently treats 'no live read' as 'nothing
    deployed' would misclassify a real keeper as a non-gym-locked alarm (over-cautious, acceptable)
    OR worse hide that we never checked; we let the caller decide via the exception."""
    import pogo_il2cpp as pg
    # ATTACH-SAFETY FIRST (2026-09-09): this read attached straight into a game the user was restarting and hung
    # ~160 s while the game stalled on its loading screen ("The game froze and i restarted it, now its frozen
    # again"). The recrawl already waits for a >=45 s-old, pool-floyd-free process; the gate must too.
    pg.wait_ready_to_attach(timeout_s=240)
    sess, _pid = pg.get_session()
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        bag_map = pg.walk_bag_protos(sess, bag)            # {uid_dec: proto_ptr}
        ptr2uid = {str(pp): format(int(d), 'x').zfill(16) for d, pp in bag_map.items()}
        scr = pg.get_script_with_helpers(sess, _JS)
        try:
            res = scr.exports_sync.readgym([str(pp) for pp in bag_map.values()])
        finally:
            scr.unload()
        return {ptr2uid[str(p)] for p, lat, lng in res if str(p) in ptr2uid}
    finally:
        sess.detach()


# ---- keeper derivation (per-mon, independent of keep_policy) ----
def _chain_stages(chain_str):
    """Parse a gl_chain_ranks / ul_chain_ranks blob ('stage:rank(pct%);stage:rank(pct%)') into
    [(stage, rank)]. Malformed fragments are skipped, never guessed at."""
    out = []
    for part in (chain_str or '').split(';'):
        part = part.strip()
        if not part or ':' not in part:
            continue
        stage, _, rest = part.partition(':')
        num = rest.split('(')[0].strip()
        try:
            out.append((stage.strip(), int(num)))
        except ValueError:
            continue
    return out


def _legacy_kept_uids(bag, legacy):
    """Mirror keep_policy rule 6's PER-SPECIES legacy cap. Returns (kept_uids, capped_pids).

    keep_policy keeps ALL legacy-move mons EXCEPT for species listed in keep_config
    legacy_species_caps (today: Absol/359 -> 10), where it keeps specials (shiny/shadow/costume/
    hundo) + best GL + best UL, then fills to the cap by IV. This gate modelled legacy as an
    UNCONDITIONAL keep-all, so the first over-cap copy the engine legitimately trims would have
    been reported as a REAL_KEEPER and exit(1) -- a hard deadlock with no way to proceed. Absol
    is at 8 of 10 right now, i.e. ~2 catches away. (lockdown 2026-09-02)

    Direction of any residual disagreement is safe: if this replica thinks a mon is KEPT and the
    engine trimmed it, we alarm (over-protect). Only a mon this replica agrees is over-cap is
    downgraded from REAL_KEEPER to the expected LEGACY_EXCESS bucket.
    """
    caps = keep_config.legacy_caps()
    default = keep_config.legacy_default_cap()

    def _legcap(pid):
        return caps.get(pid, default)

    kept = set()
    capped = defaultdict(list)
    for r in bag:
        if r['uid_hex'] not in legacy:
            continue
        if _legcap(r['pokemon_id']) is None:
            kept.add(r['uid_hex'])          # uncapped species: keep EVERY legacy specimen
        else:
            capped[r['pokemon_id']].append(r)

    def _best_by(lst, key):
        cand = [x for x in lst if x[key] is not None]
        return min(cand, key=lambda x: x[key]) if cand else None

    for pid, lst in capped.items():
        ks = set()
        for r in lst:                        # specials are NEVER cut
            if (r['fresh_shiny'] or r['fresh_alignment'] == 1 or (r['fresh_costume'] or 0)
                    or is_costume_form(r['fresh_form']) or (r['iv_total'] or 0) == 45):
                ks.add(r['uid_hex'])
        for key in ('gl_rank', 'ul_rank'):   # + best GL-rank and best UL-rank specimen
            b = _best_by(lst, key)
            if b:
                ks.add(b['uid_hex'])
        rest = keep_config.floor_top(sorted([x for x in lst if x['uid_hex'] not in ks], key=_ivkey))   # collection floor (2026-09-24)
        for r in rest[:max(0, _legcap(pid) - len(ks))]:   # fill to cap with highest-IV plain
            ks.add(r['uid_hex'])
        kept |= ks
    return kept, set(pid for pid in capped)


_LOC_CARD_KEPT = set()   # populated in main() before any _keeper_reasons call
_COMBUP_KEPT = set()     # rule 15e (2026-09-24): pvp_combup.pick on this bag, populated in main() like _LOC_CARD_KEPT
_LAW_KEEPERS = {}        # uid -> [reasons] from independent_law.py (H08, 2026-09-29), populated in main()


def _loc_card_kept_uids(bag, cf_norm):
    """Independently re-derive the location-card keepers: top-N per (pid, cf, card enum), trophies
    exempt from consuming a slot, unknown-enum holders never capped. Mirrors keep_policy rule 13b."""
    import collections as _c
    g = _c.defaultdict(list)
    keep = set()
    for r in bag:
        if _g(r, 'fresh_has_location_card') != 1:
            continue
        e = _g(r, 'fresh_loc_card_enum') or 0
        if not e:
            keep.add(r['uid_hex'])
            continue
        if __import__('costume_forms').card_folds_into_costume(r):
            continue      # costume + background = ONE ladder (user 2026-09-24): the cosmetic cap re-derivation holds it
        g[(r['pokemon_id'], cf_norm(r), e)].append(r)
    for (_pid, _f, _e), lst in g.items():
        n = keep_config.species_cap('location_card', _pid, keep_config.cap('location_card'))
        rank = [r for r in lst if (_g(r, 'iv_total') or 0) not in (0, 45)]
        for r in keep_config.floor_top(sorted(rank, key=lambda x: (-(_g(x, 'iv_total') or 0), -(_g(x, 'cp') or 0), x['uid_hex'])),
                                       look=keep_config.card_look)[:n]:   # collection floor; each look's best stays (2026-10-25)
            keep.add(r['uid_hex'])
        for r in lst:
            if (_g(r, 'iv_total') or 0) in (0, 45):
                keep.add(r['uid_hex'])
    return keep


def _pvp_best_uids(bag, cf_norm, BS, gm_ok):
    """Independently re-derive keep_policy rule 15d (LAW bucket 2b, user 2026-09-23): the best GL copy and the best
    UL copy of every PvP IDENTITY (species + battle form) among NON-shadow copies (fresh_alignment != 1).
    USABLE ONLY (user 2026-09-23): a copy competes in GL / UL only with a stage it can REACH (its own, or a later stage
    its form / costume / gender can become -- keep_policy.pvp_later_stages, the ONE evolution graph; if that import
    fails, the ranker's chain as it stands, which is looser and can only ALARM) and ENTER (pvp_iv_rule.fits -- its CP
    there at its TRUE level inside the cap; the ONE shared CP/level helper). Key (usable stage reaches the cap first,
    usable rank, uid_hex); a copy with no usable stage never wins. ML: unchanged (viable ml_stage, ml_rank, uid_hex).
    {uid: {'GL','UL','ML'}}. If the gamemaster did not load, viability cannot be judged and rank alone decides (a
    different winner in the pile then ALARMS -- the over-protect direction; the engine keeps its own winner and trips
    its own 15d tripwire if it does not)."""
    import collections as _c
    from pvp_iv_rule import pvid as _pv, fits as _fits
    from cpm_table import ML_CAP as _MLC
    try:
        import keep_policy as _kp
        _seen = {e['pid'] for e in json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json')))['entries']}
        _graph = _kp.build_evo_graph(json.load(open(GAMEMASTER, encoding='utf-8')), _seen, with_all=True)
        _later = lambda r: _kp.pvp_later_stages(r, _graph)
    except Exception as _e:                                   # looser reach -> more candidates -> can only alarm
        print('  WARN: evolution graph unavailable (%s) -- Best GL/UL judged on the ranker\'s chain as it stands' % _e)
        _later = lambda r: None

    def _usable(r, lg, cap):
        """(reaches-the-cap-first key, rank) of the best stage this copy can reach AND enter, or None."""
        own = _pv(r['species_name'], _g(r, 'form') or 0)
        later = _later(r)
        best = None
        reach = [(stage, rank) for stage, rank in (_chain_stages(_g(r, lg + '_chain_ranks'))
                                                  or ([(_g(r, lg + '_stage'), _g(r, lg + '_rank'))] if _g(r, lg + '_rank') is not None else []))
                 if stage and (stage == own or later is None or stage in later)]
        if gm_ok and not any(_fits(r, stage, cap, BS) for stage, _k in reach):   # cannot ENTER at any reachable stage
            return None                                   # (no gamemaster -> CP unjudgeable -> every copy counts)
        for stage, rank in reach:                         # evolution counts everywhere (2026-09-24): CP-blind per stage
            k = (0 if (gm_ok and _viable(stage, cap, BS)) else 1, rank)
            best = k if best is None or k < best else best
        return best

    g = _c.defaultdict(list)
    for r in bag:
        if _g(r, 'fresh_alignment') == 1:
            continue
        g[_pv(r['species_name'], _g(r, 'form') or 0)].append(r)   # PvP identity (2026-09-23): cosmetics fold in
    won = {}
    _BRF = keep_config.pvp('best_rank_floor')             # rule 15d best rank floor (2026-09-24): top 20% only
    from references import LEGENDARY_IDS as _LI, MYTHICAL_IDS as _MI, ULTRA_BEAST_IDS as _UI, PARADOX_IDS as _PI
    _RARE = _LI | _MI | _UI | _PI                          # legendaries: no rank floor (user 2026-09-24)
    for lst in g.values():
        for lg, cap in (('gl', GL_CAP), ('ul', UL_CAP)):
            cand = [(k, r) for r in lst for k in (_usable(r, lg, cap),) if k is not None]
            if cand:
                bk, b = min(cand, key=lambda x: (x[0][0], x[0][1], x[1]['uid_hex']))
                if bk[1] <= _BRF or _g(b, 'pokemon_id') in _RARE:
                    won.setdefault(b['uid_hex'], set()).add(lg.upper())
        cand = [r for r in lst if _g(r, 'ml_rank') is not None and (_g(r, 'ml_rank') <= _BRF or _g(r, 'pokemon_id') in _RARE)]
        if cand:
            b = min(cand, key=lambda r: (0 if (gm_ok and _viable(r['ml_stage'], _MLC, BS)) else 1, r['ml_rank'], r['uid_hex']))
            won.setdefault(b['uid_hex'], set()).add('ML')
    return won


_POOL_COUNTS = {}


def _line_pool(r):
    """The every-line pool key (keep_config.line_pool_all) or None -- pattern_pools.pool_key, the engine's own."""
    if not keep_config.line_pool_all():
        return None
    import pattern_pools
    return pattern_pools.pool_key(r['pokemon_id'], r['species_name'], r['form'] or 0, _g(r, 'gender'))


def _keeper_reasons(r, BS, legacy_set, gm_ok, dex_counts, event_txt, legacy_txt,
                    dex_form_counts=None, cf_norm=None,
                    legacy_kept=None, legacy_capped_pids=frozenset(), pvp_best=None):
    """Every UNCONDITIONAL keep axis this mon earns, as a list of human reasons. EXCLUDES the three
    CAPPED axes -- shiny (top-20), costume (top-4), XXL (top-2 height + top-1 weight) -- which the
    classifier handles cap-aware so a cap-EXCESS copy reads as expected, not as a real keeper. A
    non-empty list here = an UNCONDITIONAL keeper (alarm unless gym-locked)."""
    why = []
    iv = r['iv_total'] or 0
    # (the old `tags = _tagset(r['auth_tag_names'])` line was removed 2026-09-02: it was assigned
    #  and never read. auth_tag_names lags until set_db runs, so it is deliberately NOT a
    #  protection input here -- event/legacy read the FRESH Event.txt / Legacy_Moves.txt instead.)
    owner = (r['original_owner_name'] or '').strip().lower()

    if iv == 45:
        why.append('hundo(iv45)')
    if (iv == 0 or r['is_zero']) and r['uid_hex'] in _nundo_keepers():
        why.append('nundo(iv0)')     # the chosen nundo of its look; a duplicate of the same look is fodder (2026-09-17)
    # legendary/mythical is NO LONGER an unconditional alarm (user 2026-06-08: "what's the point of the knobs
    # if it won't let me clean up"). keep_policy rule 5 already keeps your best rares (top-N by IV + best GL/UL
    # per variant), so only genuine over-cap dupes reach the pile. A piled legendary STILL alarms if it earns
    # ANY other axis below -- hundo, nundo, top-rank PvP, legacy, event, mighty, adventure-effect, pvp_spread,
    # dex-only-copy, protected, origin, or a within-cap shiny/costume/XXL -- so a special legendary is still
    # protected; only a low-IV dupe you deliberately capped is allowed to trim.
    # best_buddy keep-axis RETIRED 2026-06-07 (user nuked it; 0 sole-BB mons -- all kept by another axis)
    # lucky/traded keep ONLY for E+F origin (keep_policy rule 'origin'); luckies/trades from anyone else are
    # NORMAL (user "treat luckies as normal") and transfer like a plain. The old broad alarm false-failed
    # the shiny-displaced lucky Vanillite (owner VamsiVee) + traded Igglybuff (vgroover), neither E+F. 2026-06-07
    if (r['is_lucky'] == 1 or r['is_traded'] == 1 or r['is_traded_flag_v2'] == 1) and owner in EF_OWNERS:
        why.append('origin(E+F)')
    # legacy: keep-all EXCEPT the per-species caps keep_policy applies (rule 6). An over-cap copy
    # of a CAPPED species is the user's deliberate trim, so it is classified LEGACY_EXCESS by the
    # caller instead of alarming. Species with no cap are unchanged keep-all. (lockdown 2026-09-02)
    if r['uid_hex'] in legacy_set or r['uid_hex'] in legacy_txt:
        if (legacy_kept is None or r['pokemon_id'] not in legacy_capped_pids
                or r['uid_hex'] in legacy_kept):
            why.append('legacy')
    if r['uid_hex'] in event_txt:           # current Event.txt -- NOT stale auth_tag_names (lags until set_db)
        why.append('event')
    # additional UNCONDITIONAL keep-all axes (added 2026-06-06 -- the guard must be a SUPERSET):
    if _g(r, 'fresh_is_strong') == 1:
        why.append('mighty')
    # AE roster clause mirrors keep_policy (effects_left>0 OR pid in the AE roster). Deliberately
    # UNCONDITIONAL here (ignores the rules.adventure_effect toggle): the gate over-protects, so a
    # 0-effects-left roster legendary can never slip through it silently (audit F2).
    # adventure_effects_left alone is NOT a keeper (2026-09-24: 19 bag rows carry it, 18 of them know no AE move -- a
    # shiny Rapidash 27% blocked the whole pile); it backs the roster up only while the live registry is unreadable.
    if _ae_hit(r) or (__import__('ae_moves').move_ids() is None and (_g(r, 'adventure_effects_left') or 0) > 0):
        why.append('adventure_effect')
    # location_card UNCONDITIONAL (workflow verifier 2026-06-09): the Event.txt route is VACUOUS for
    # leaks -- build_tagsets strips Transfer uids from Event.txt before this gate reads it, so a leaked
    # loc-card mon is already gone from the tagset. 78/126 loc-card keepers have no other axis; check
    # the column directly (ignores the rules.location_card toggle -- over-protect like mighty/AE).
    # CAPPED 2026-09-02 (top-N per (pid,cf,card enum), user "top 6 per species per card"). Was
    # unconditional keep-all; after the engine capped it this gate reported 17 phantom REAL_KEEPERs and
    # blocked a correct pile -- the 9th instance of a capped axis modelled as keep-all. A holder whose
    # card enum is still UNKNOWN stays unconditional (unknown data is protected, never fodder).
    if _g(r, 'fresh_has_location_card') == 1:
        if not (_g(r, 'fresh_loc_card_enum') or 0) or r['uid_hex'] in _LOC_CARD_KEPT:
            why.append('location_card')
    if (r['iv_atk'], r['iv_def'], r['iv_sta']) in keep_config.pvp_spread_keep():
        why.append('pvp_spread')
    _lpk = _line_pool(r)
    if _lpk is not None:
        # EVERY-LINE POOLS (florandez 2026-09-26): the last copy that matters is the last copy of the POOL (the only
        # Ivysaur may go while the line keeps its 2 best; the Pokedex is lifetime).
        if _POOL_COUNTS.get(_lpk, 99) <= 1:
            why.append('dex_only_copy')
    else:
        if dex_counts.get(r['pokemon_id'], 99) <= 1:        # per-SPECIES: never release the last copy of a dex entry
            why.append('dex_only_copy')
        if dex_form_counts is not None and cf_norm is not None \
                and dex_form_counts.get((r['pokemon_id'], cf_norm(r)), 99) <= 1:
            why.append('dex_only_form')   # per-(species,FORM) like keep_policy's dex_only_copy axis (audit F8)
    if r['pokemon_id'] in keep_config.protected_pids():  # "leave them alone" keep-all species (Pichu) -- keep_policy reason 'protected'; gate had no protected axis (ultrareview 2026-06-08)
        why.append('protected')
    if (r['is_favorite_v2'] or 0) == 1:     # user 2026-09-17: favorites are never culled (keep_policy reason 'favorite')
        why.append('favorite')
    if r['uid_hex'] in _evolve_shiny_targets():   # a shiny held to evolve into a shiny spot (keep_policy 'shiny_ladder', 2026-09-17)
        why.append('shiny_ladder')
    if r['uid_hex'] in _COMBUP_KEPT:               # PvP comb-up copy (rule 15e, 2026-09-24)
        why.append('pvp_combup')
    if pvp_best is not None:                       # Best GL / UL / ML copy of its PvP identity (rule 15d, usable-only GL/UL)
        why.extend('pvp_best_%s' % lg.lower() for lg in sorted(pvp_best.get(r['uid_hex'], ())))

    # PvP rank<=READY_RANK for a CP-VIABLE evolved league form (GL or UL). A degenerate rank<=5 on a
    # stage that can't reach the cap (e.g. Ivysaur for UL) is NOT a keeper -> the _viable() gate.
    # FAIL-SAFE: if the gamemaster did NOT load (gm_ok False) we cannot judge viability, so OVER-PROTECT
    # -- flag ANY rank<=READY_RANK as a keeper rather than silently passing it through.
    # ONLY A COPY THAT CAN PLAY (user 2026-09-30: "Why would I keep any GL and UL pokemon that cant participate?"):
    # with the gamemaster loaded, the alarm fires only when pvp_iv_rule.plays() -- the engine's own rule 15b -- finds a
    # top-READY_RANK stage in the chain that reaches the cap AND that this copy fits under (unknown => fits). Without
    # it, the old CP-blind check still over-protects.
    _play = gm_ok and _plays is not None
    if _play:
        _gl_ok = _plays(r, 'gl', GL_CAP, BS) is not None
        _ul_ok = _plays(r, 'ul', UL_CAP, BS) is not None
    else:
        _gl_ok = (r['gl_rank'] is not None and r['gl_rank'] <= READY_RANK
                  and (not gm_ok or _viable(r['gl_stage'], GL_CAP, BS)))
        _ul_ok = (r['ul_rank'] is not None and r['ul_rank'] <= READY_RANK
                  and (not gm_ok or _viable(r['ul_stage'], UL_CAP, BS)))
    if _gl_ok:
        why.append('gl_rank<=%d%s' % (READY_RANK, '' if gm_ok else ' (gm-fail/over-protect)'))
    if _ul_ok:
        why.append('ul_rank<=%d%s' % (READY_RANK, '' if gm_ok else ' (gm-fail/over-protect)'))

    # STAGE-COUPLED VIABILITY GAP (the Mareep shape, again). gl_rank/gl_stage record the ONE stage
    # that won the rank contest; viability is then judged on THAT stage. A pre-evo can win the
    # contest on itself (which is not cap-viable) while a LATER stage in the same chain is both
    # top-N and viable -- and the mon then earns no PvP axis at all. Live example: a Dottler whose
    # ul_stage='dottler' ranks #1 but is not cap-viable, while 'orbeetle' ranks #3 and IS viable.
    # The chain ranks are already in the DB, so sweep EVERY stage. Only checked when neither
    # headline axis fired, so it adds no duplicate reasons. (lockdown 2026-09-02; 0 new alarms
    # against the current pile.)
    if not (_gl_ok or _ul_ok) and not _play:     # plays() already swept every chain stage
        for _col, _lcap in (('gl_chain_ranks', GL_CAP), ('ul_chain_ranks', UL_CAP)):
            for _stage, _rk in _chain_stages(_g(r, _col)):
                if _rk <= READY_RANK and (not gm_ok or _viable(_stage, _lcap, BS)):
                    why.append('pvp_chain(%s r%d%s)'
                               % (_stage, _rk, '' if gm_ok else ' gm-fail/over-protect'))
                    break
            else:
                continue
            break

    # PvP UNKNOWN. Every rule above is `is not None`-gated, so a mon with NO ranks at all sails
    # through every PvP check green -- missing data reading as "no PvP value" instead of "not
    # judged". compute_all_ranks NULLs all 12 rank columns for a (species,form) it cannot map to
    # a gamemaster speciesId, so this is exactly where that lands. Unknown => PROTECTED.
    # (lockdown 2026-09-02; 0 pile members have both ranks NULL today, so this costs nothing now.)
    if r['gl_rank'] is None and r['ul_rank'] is None:
        why.append('pvp_unknown(no gl/ul rank -- unrankable species/form, cannot judge)')
    return why


# =================================================================================================
# EGG GUARD -- a fail-closed DATA bucket, NOT a keep axis.
#
# An egg is not a bag pokemon. It has no species, no IVs, no ranks and no cosmetics, so every keep
# axis above reads it as nothing at all: _keeper_reasons() returns [], the three cap tests are all
# False, and it lands in PLAIN -- the "ordinary fodder, safe to release" bucket -- and is blessed
# into an irreversible hand-release list. Nothing in the keep chain read is_egg at all before
# 2026-09-07 (grep over keep_policy.py / build_tagsets.py / this file: zero hits), so the pile gate
# had no way to refuse a non-pokemon.
#
# NOT a keep axis, deliberately. A keep axis says "this mon is worth keeping" and can be capped,
# toggled, or traded off against another axis. This says "this row is not a pokemon, so no verdict
# about it is valid" -- the same category as MISSING_FROM_DB, and it takes the same exit(1) /
# no-stamp path.
#
# INERT TODAY, ON PURPOSE. pogo_pipeline.py skips eggs before the insert (_rec_is_egg ->
# skipped_eggs) so no row has ever carried is_egg=1: measured 2026-09-07, the whole column is 3697
# zeros + 2031 NULLs, 0 ones, and 0 of the 26 pile uids is touched by anything below. The guard has
# to exist BEFORE the data does -- a gate written after the first egg reaches the pile is a gate
# that was missing exactly when it mattered -- and until then it costs one comparison per pile uid.
#
# THE NULL SUB-CLAUSE, and why it is armed by the DATA rather than by a constant:
#   A NULL is_egg means "nobody wrote this field" = unknown, and unknown protection data must read
#   as BLOCKED (project law: never act destructively on incomplete data). But today every recent
#   row is NULL, because the only writer the column has ever had is a one-off backfill
#   (_enrich_proto_fields.py; the newest row it stamped was created 2026-06-02) -- so blocking every
#   NULL right now would block 24 of the 26 pile uids and simply break the gate. MEASURED, not
#   assumed. So the sub-clause self-arms off two facts read live out of the DB:
#     live    at least one row anywhere carries is_egg != 0 -> an egg has actually been ingested,
#             so the column has a current writer. 0 such rows today -> DORMANT.
#     epoch   MAX(creation_time_ms) over rows that DO carry a value: a provable LOWER BOUND on when
#             the column was last populated. A NULL on a row NEWER than that was created after the
#             last write and should have been stamped -> unknown -> blocked. Older NULLs are the
#             grandfathered pre-backfill population and stay quiet.
#
#   WHAT THIS SUB-CLAUSE CANNOT DO, stated plainly rather than papered over. It cannot notice a
#   writer that stamps is_egg=0 on every mon and never ingests an egg: no row would ever carry
#   is_egg != 0, `live` would stay False, and a stray NULL on a fresh row would pass. I tried to
#   close that with a second signal -- "some row carrying a value is NEWER than the newest row
#   carrying none" -- and it is VACUOUS: that condition holds only when every NULL row is older
#   than `epoch`, i.e. exactly when no NULL row can satisfy `ctm > epoch`. It would arm a clause
#   that can never fire, which is worse than not having it. Closing the gap honestly needs
#   per-row write provenance (a last_seen / row_updated column), which this schema does not have
#   -- there is no per-row timestamp here except creation_time_ms, the in-game catch time. The
#   exposure is bounded: this is only the sub-clause. The is_egg != 0 test below is unconditional,
#   needs no arming, and is the guard that actually stops an egg. (measured + proved 2026-09-07)
#   The direction of error is chosen: UNDER-arming this sub-clause is safe, because the is_egg != 0
#   test above is unconditional and is the real guard; OVER-arming it would block a correct pile.
#
# The `eggs` TABLE is deliberately NOT used as a second oracle. It is stale: uid 8de05237b3bcdabd
# sits in `eggs` with is_hatched=0 while `pokemon` says it is a hatched Pichu (hatched_from_egg=1,
# is_egg=0). Cross-checking it would have flagged a real pokemon as an egg. (checked 2026-09-07)
# =================================================================================================
def _egg_context(conn):
    """(has_col, live, epoch_ms) for the EGG bucket -- every input read from the DB itself.

    NEVER raises. An unreadable context degrades to "column not usable", which is exactly the state
    this file was in before the guard existed: a new guard must not be able to turn a good pile into
    a crash. It is announced either way (see _egg_ctx_note) -- a gate whose arming state is
    invisible is the unobservable-gate bug this project has already been bitten by.
    """
    try:
        cols = {row[1] for row in conn.execute('PRAGMA table_info(pokemon)')}
        if 'is_egg' not in cols:
            return (False, False, None)
        live = conn.execute('SELECT COUNT(*) FROM pokemon '
                            'WHERE is_egg IS NOT NULL AND is_egg <> 0').fetchone()[0] > 0
        epoch = conn.execute('SELECT MAX(creation_time_ms) FROM pokemon '
                             'WHERE is_egg IS NOT NULL').fetchone()[0]
        return (True, bool(live), epoch)
    except Exception as e:                                    # pragma: no cover -- defensive
        print("WARN: is_egg context unreadable (%s) -- the EGG bucket cannot arm this run." % e)
        return (False, False, None)


def _egg_ctx_note(egg_ctx):
    """One line saying exactly which half of the EGG guard is live this run."""
    has_col, live, epoch_ms = egg_ctx
    if not has_col:
        return 'DISABLED -- no usable is_egg column in this schema (nothing to check)'
    return ('is_egg != 0 blocks when the row ALSO has no CP/IVs (egg shape; a bare bit on a CP-bearing row is a recent hatch, allowed); NULL sub-clause %s'
            % (('ARMED (a live is_egg writer exists -- a NULL on a row created after %r blocks too)'
                % (epoch_ms,)) if live else
               'DORMANT (no row carries is_egg != 0 yet, so NULL is the historical all-NULL state)'))


def _egg_block_reason(r, egg_ctx):
    """Why this pile row must BLOCK as non-pokemon data, or None. See the block comment above."""
    has_col, live, epoch_ms = egg_ctx
    if not has_col:
        return None
    v = _g(r, 'is_egg', None)
    if v is not None and v != 0:
        # 2026-09-08 LIVE MEASUREMENT: the game leaves PokemonProto.isEgg_=1 on a freshly HATCHED
        # pokemon for a day or two (Sobble hatched 04:20Z read 1 at ~20h; a Scorbunny hatched the day
        # before had cleared to 0; three control mons read 0). A hatched mon has CP, IVs and a level;
        # a real egg has NONE of them. So the bit alone is not an egg -- the egg SHAPE is. Blocking on
        # the bit alone false-blocked the whole pile on a legitimate 10/14/13 Scorbunny.
        cp = _g(r, 'cp', None); ivt = _g(r, 'iv_total', None)
        if cp is None or cp <= 0 or ivt is None:
            # Any non-zero value, not just ==1: a garbage read is still not a "this IS a pokemon" answer.
            return ('is_egg=%r with no CP/IVs -- an EGG, not a bag pokemon; it must never be blessed'
                    ' into a hand-release list' % (v,))
        print('  note: %s has is_egg=%r but CP %s and IVs -- a recent HATCH whose flag has not cleared,'
              ' not an egg (bit clears within ~1-2 days); allowed' % (_g(r, 'uid_hex', '?'), v, cp))
        return None
    if v is not None:
        return None                       # 0 -- positively read as "not an egg"
    if not live:
        return None                       # no live writer yet: NULL is the historical state, not a
                                          # missing write. (Dormant by measurement -- see above.)
    ctm = _g(r, 'creation_time_ms', None)
    if epoch_ms is None or ctm is None or ctm > epoch_ms:
        return ('is_egg is NULL on a row the live is_egg writer should have stamped'
                ' (creation_time_ms=%r, last is_egg write >= %r) -- unknown, and unknown data is'
                ' BLOCKED, never released' % (ctm, epoch_ms))
    return None


STAMP_REUSE_S = 120


def _gate_sha256():
    """sha256 of the gate's own code and the selection modules it judges with -- a stamp is reused only by THIS gate."""
    h = hashlib.sha256()
    # + every module and read-only input the verdict is computed with that the pile / config / DB digests do not already
    # pin (R-A review): the CP / rank helpers, the form + costume tables, the legendary roster, the base-form map pick()
    # uses, the legacy list and the game master / dex the evolution graph is built from.
    for rel in ('system/scripts/preflight_transfer.py', 'independent_law.py', 'trophy_pick.py', 'pvp_combup.py',
                'system/scripts/refresh_evolve_shiny.py', 'size_line.py', 'keep_config.py', 'system/scripts/keep_policy.py',
                'pvp_iv_rule.py', 'cpm_table.py', 'evolvable_forms.py', 'costume_forms.py', 'references.py', 'granular_tags.py',
                'form_overrides_complete.py', 'legacy_accurate.json', 'pvpoke_gamemaster.json', 'pokedex_hundos_live.json'):
        try:
            h.update(open(os.path.join(ROOT, rel), 'rb').read())
        except OSError:
            h.update(b'<missing %s>' % rel.encode())
    return h.hexdigest()


def _fresh_identical_stamp(pile_sha256):
    """The existing stamp, if it vouches for EXACTLY these inputs and is younger than STAMP_REUSE_S; else None."""
    try:
        st = json.load(open(STAMP_PATH, encoding='utf-8'))
        prov = json.load(open(PROVENANCE, encoding='utf-8'))
        gen = _dt.datetime.strptime(st['generated'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=_dt.timezone.utc)
        age = (_dt.datetime.now(_dt.timezone.utc) - gen).total_seconds()
        if (st.get('schema') == STAMP_SCHEMA and 0 <= age <= STAMP_REUSE_S
                and st.get('pile_sha256') == pile_sha256
                and st.get('config_sha256') == keep_config.fingerprint()
                and st.get('db_sha256') == prov.get('db_content_sha256')
                and st.get('gate_sha256') == _gate_sha256()):      # the same GATE judged it (H08)
            return age
    except Exception:
        pass
    return None


_EVS = None
_NDK = None


def _nundo_keepers():
    """trophy_pick.pick_nundos over the whole bag -- the same one-per-look choice the engine makes."""
    global _NDK
    if _NDK is None:
        import trophy_pick
        _c = sqlite3.connect(DB); _c.row_factory = sqlite3.Row
        # (2026-09-26) fused components hold no ladder slot: keep_policy picks the nundos over rows without them
        _NDK = trophy_pick.pick_nundos([r for r in _c.execute('SELECT * FROM pokemon WHERE in_bag=1').fetchall()
                                        if not keep_config.is_fused_component(r)])
        _c.close()
    return _NDK


def _evolve_shiny_targets():
    """The Evolve Shiny list, computed by the same rule the engine and build_tagsets use. No fallback: if it cannot
    be computed the gate must not pass a shiny it cannot judge."""
    global _EVS
    if _EVS is None:
        from refresh_evolve_shiny import compute_target
        _EVS = set(compute_target())
    return _EVS


def pile_members_sha256(uids):
    """The pile's MEMBERSHIP fingerprint (X3, 2026-09-24): sha256 of its sorted, normalised uids -- order- and
    padding-proof, so full_audit and the pre-flight gate compute the same value for the same set."""
    return hashlib.sha256('\n'.join(sorted(format(int(u, 16), 'x') for u in uids)).encode()).hexdigest()


def _expected_members():
    """--expect-pile-members <sha256> (X3): the fingerprint full_audit took when the 11 audits judged the pile."""
    if '--expect-pile-members' in sys.argv:
        i = sys.argv.index('--expect-pile-members')
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else ''
    return None


def main():
    transfer_uids, pile_sha256 = _load_transfer_uids()
    # X3 (2026-09-24): the pile this gate vets must be the pile the 11 audits judged. Checked FIRST -- before any stamp
    # reuse or write -- so a pile the sync's recompute changed after the audits can never be stamped for the push.
    _exp = _expected_members()
    if _exp is not None and _exp != pile_members_sha256(transfer_uids):
        _invalidate_stamp('pile differs from the one the audits judged')
        print('RESULT: FAIL -- the pile to push (%d uids) is NOT the pile the 11 audits judged this pass (its membership '
              'changed after them: a config edit or a re-derived input mid-pass). Nothing is stamped; the next cull '
              'audits the new pile.' % len(transfer_uids))
        sys.exit(1)
    _age = _fresh_identical_stamp(pile_sha256) if transfer_uids else None
    if _age is not None:
        print('TRANSFER PRE-FLIGHT: reusing the stamp written %.0f s ago -- same pile bytes, config and DB content; '
              'no second live read (2026-09-12). PASS' % _age)
        return
    _invalidate_stamp('new pre-flight run started')
    if not transfer_uids:
        # EMPTY PILE (2026-09-12): the user released everything and keep_policy found nothing new. That is a
        # legitimate verdict, not a partial run -- the EMPTY set is what the phone must show, and without a
        # stamp prune_tags refused the Transfer target, which aborted the WHOLE sync (rc 2). Vetting an empty
        # set is trivially complete, so stamp it: prune then pushes want=<empty> (a leftover tagged mon is
        # stripped; nothing can be released from an empty tag).
        print("Transfer.txt is EMPTY -- nothing to pre-flight; stamping the empty pile so the sync proceeds.")
        _write_stamp(pile_sha256, 0)
        return

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    ph = ','.join('?' * len(transfer_uids))
    rows = c.execute(f"SELECT * FROM pokemon WHERE uid_hex IN ({ph})", transfer_uids).fetchall()
    rowmap = {r['uid_hex']: r for r in rows}

    missing = [u for u in transfer_uids if u not in rowmap]      # uid in the file but not in the DB

    # full-bag pools for the cap-context (a cap is judged against EVERY copy in the bag, not just the
    # Transfer subset). in_bag=1 mirrors keep_policy's universe.
    bag = c.execute("SELECT * FROM pokemon WHERE in_bag=1").fetchall()
    # (2026-09-26) fused components hold no ladder slot: a Reshiram / Zekrom held inside a fused Kyurem is not in
    # keep_policy's `rows`, so EVERY re-derivation below (dex counts, the base-form election, every cap / ladder /
    # Best GL/UL/ML / comb-up / legacy / card pool) runs without it, exactly as the engine does. `bag` feeds ONLY those
    # competitions here; pile membership is read from rowmap above, and a fused component IN the pile is the FUSED block.
    _fused_bag = [r for r in bag if keep_config.is_fused_component(r)]
    bag = [r for r in bag if not keep_config.is_fused_component(r)]
    if _fused_bag:
        print('  fused components: %d held inside a fused Kyurem -- out of every ladder re-derived here (%s)'
              % (len(_fused_bag), ', '.join(sorted(r['species_name'] for r in _fused_bag))))
    dex_counts = defaultdict(int)                 # pid -> count in bag, for the dex_only_copy axis (per-species)
    for _r in bag:
        dex_counts[_r['pokemon_id']] += 1
    _POOL_COUNTS.clear()                          # every-line pools: copies per POOL in the bag (2026-09-26)
    for _r in bag:
        _k = _line_pool(_r)
        if _k is not None:
            _POOL_COUNTS[_k] = _POOL_COUNTS.get(_k, 0) + 1
    # per-(species, normalized form) counts so the gate can independently re-flag a sole-FORM copy the way
    # keep_policy's dex_only_copy does (audit F8). Form-0 rows fold into the species base form when the bag
    # has exactly ONE unambiguous non-regional form (same inference as keep_policy cf(); ambiguous -> raw form,
    # which over-counts singletons = over-protects, the right direction for a gate).
    from collections import Counter as _Counter
    # REGIONAL-CODE GUARD -- keep_policy._is_regional_code, which this copy was missing. A regional
    # form code (Alolan Raichu, ...) can carry a NULL/blank form_region and masquerade as
    # base-region; without the guard it can become the species' "base form" and the Kantonian
    # copies collapse onto it. Recomputed both ways over the live bag: 702 vs 701 base-form
    # entries, diverging on pid 199 (Slowking); 0 rows normalize differently TODAY, so this is a
    # latent-divergence fix, not a behaviour change. (lockdown 2026-09-02)
    _REGSUF = ('_alolan', '_galarian', '_hisuian', '_paldean')

    def _is_regional_code(nm, f):
        if _PVID is None:
            # Cannot tell. Excluding the form from base-form candidacy leaves form-0 rows on raw
            # form 0 -> MORE distinct (pid,form) groups -> more singletons -> more dex_only_form
            # protection. That is the over-protective direction, which is what a gate wants.
            return True
        return any(x in _PVID(nm, f) for x in _REGSUF)

    _basecnt = defaultdict(_Counter)
    for _r in bag:
        _f = _r['form'] or 0
        _reg = ((_g(_r, 'form_region') or '')).strip().lower()
        if _f != 0 and _reg in ('', 'normal', 'kantonian', 'none', 'null') \
                and not _is_regional_code(_r['species_name'], _f) and not is_costume_form(_f):   # 2026-09-23
            _basecnt[_r['pokemon_id']][_f] += 1
    _base_form = {pid: cnt.most_common(1)[0][0] for pid, cnt in _basecnt.items() if len(cnt) == 1}
    def _cf_norm(rr):
        _f = rr['form'] or 0
        return _base_form.get(rr['pokemon_id'], _f) if _f == 0 else _f
    # Use the same canonical form pool as the engine and the other independent cap checks.
    global _LOC_CARD_KEPT, _COMBUP_KEPT
    _LOC_CARD_KEPT = _loc_card_kept_uids(bag, _cf_norm)
    _cu = __import__('pvp_combup').pick_default(bag)
    _COMBUP_KEPT = set(_cu['gl']) | set(_cu['ul'])
    print('  PvP comb-up: %d copies would make a better GL / UL copy of a stage after evolving' % len(_COMBUP_KEPT))
    print('  location-card cap: %d of %d holders are within the top-%d of their (species, form, card)'
          % (len(_LOC_CARD_KEPT), sum(1 for _r in bag if (_r['fresh_has_location_card'] == 1)),
             keep_config.cap('location_card')))
    dex_form_counts = defaultdict(int)
    for _r in bag:
        dex_form_counts[(_r['pokemon_id'], _cf_norm(_r))] += 1
    # current keep-tagset membership (FRESH keep_policy output -- auth_tag_names lags until set_db runs)
    def _load_ts(fn):
        try:
            with open(os.path.join(ROOT, 'system', 'analysis', 'tagsets', fn), encoding='utf-8') as _f:
                return {ln.strip() for ln in _f if ln.strip()}
        except FileNotFoundError:
            return set()
    event_txt = _load_ts('Event.txt')
    legacy_txt = _load_ts('Legacy_Moves.txt')

    BS = {}
    gm_ok = False
    try:
        gm = json.load(open(GAMEMASTER, encoding='utf-8'))
        BS = {p['speciesId']: p.get('baseStats', {}) for p in gm['pokemon']}
        gm_ok = True
    except Exception as e:
        print("WARN: gamemaster load failed (%s) -- PvP-rank axis now OVER-PROTECTS"
              " (any rank<=%d flags as a keeper; never silently passes)." % (e, READY_RANK))
    pvp_best_kept = _pvp_best_uids(bag, _cf_norm, BS, gm_ok)
    print('  best GL/UL/ML (rule 15d, usable-only GL/UL): %d best non-shadow copies across PvP identities; %d of them in the pile'
          % (len(pvp_best_kept), len(set(pvp_best_kept) & set(transfer_uids))))

    legacy_set = set()
    try:
        legacy_set = {e['uid_hex'] for e in json.load(open(LEGACY_JSON, encoding='utf-8'))}
    except Exception as e:
        print("WARN: legacy_accurate.json load failed (%s) -- falling back to the 'Legacy Moves' tag only." % e)

    # ---- legacy cap context: keep_policy rule 6's per-species caps, replicated (2026-09-02) ----
    legacy_kept, legacy_capped_pids = _legacy_kept_uids(bag, legacy_set)

    # ---- INDEPENDENT LAW RE-DERIVATIONS (H08, 2026-09-29) ----
    # The nundo, comb-up and shiny-ladder axes above come from trophy_pick.pick_nundos, pvp_combup.pick_default and
    # refresh_evolve_shiny.compute_target -- the functions keep_policy marks them from -- so a bug there was blessed here
    # as well, and the dashboard's Sync button runs THIS gate without the 11 audits. independent_law.py re-derives the
    # three from LAW.md without those functions; a pile member it flags is a REAL_KEEPER. Cannot run -> every pile
    # member alarms (a gate that cannot judge does not pass).
    global _LAW_KEEPERS
    _LAW_KEEPERS = {}
    _pile_set = set(transfer_uids)
    try:
        import independent_law as _il
        import keep_policy as _kpl
        from pvp_iv_rule import pvid as _pvl, fits as _fitl
        from references import LEGENDARY_IDS as _L1, MYTHICAL_IDS as _L2, ULTRA_BEAST_IDS as _L3, PARADOX_IDS as _L4
        _gml = json.load(open(GAMEMASTER, encoding='utf-8'))
        _BSl = {p['speciesId']: p.get('baseStats', {}) for p in _gml['pokemon']}
        _dexl = {p['speciesId']: p.get('dex') for p in _gml['pokemon']}
        _grl = _kpl.build_evo_graph(_gml, {e['pid'] for e in json.load(open(os.path.join(ROOT, 'pokedex_hundos_live.json')))['entries']},
                                    with_all=True)
        _later_l = lambda r: _kpl.pvp_later_stages(r, _grl)
        _own_l = lambda r: _pvl(r['species_name'], r['form'] or 0)

        def _next_l(r):
            _l = set(_later_l(r) or ())
            return {t for t in _l if not any(t in _grl[4].get(x, ()) for x in _l if x != t)}
        try:
            _labels_l = json.load(open(os.path.join(ROOT, 'system', 'analysis', 'pvp_combup_labels.json'), encoding='utf-8'))
        except (OSError, ValueError):
            _labels_l = {}
        _found = []
        for _u, _why in (_il.nundo_violations(bag, _pile_set, keep_config.cap('nundo'), _cf_norm, is_costume_form)
                         if keep_config.rule_enabled('nundo') else []):
            _found.append((_u, 'nundo_look(law: %s)' % _why))
        for _u, _lg, _st, _rk, _why in _il.combup_uncovered(
                bag, _pile_set, _labels_l, own_of=_own_l, later_fn=_later_l,
                fits_fn=lambda r, st, cap: _fitl(r, st, cap, _BSl), reaches_fn=lambda st, cap: _viable(st, cap, _BSl),
                caps={'gl': GL_CAP, 'ul': UL_CAP}, floor=keep_config.pvp('best_rank_floor'), rare_pids=_L1 | _L2 | _L3 | _L4,
                legacy_uids=legacy_set, protected_pids=keep_config.protected_pids(), cf=_cf_norm):
            _found.append((_u, 'pvp_combup(law: %s)' % _why))
        for _u, _why in _il.shiny_ladder_violations(
                bag, _pile_set, own_of=_own_l, next_of=_next_l, can_evolve=lambda r: bool(_later_l(r)),
                cap_of=lambda t: _shiny_cap(_dexl.get(t)), plain_cap_of=lambda t: _shiny_plain_cap(_dexl.get(t)),
                floor_iv=keep_config.shiny_floor_iv(), is_collectible=lambda r: _shiny_is_special(r) and r['fresh_alignment'] != 1,
                protected_pids=keep_config.protected_pids()):
            _found.append((_u, 'shiny_ladder(law: %s)' % _why))
        for _u, _why in _found:
            _LAW_KEEPERS.setdefault(_u, []).append(_why)
        print('  independent law re-derivations (nundo one per look, PvP comb-up, shiny ladder): %d pile member(s) flagged'
              % len(_LAW_KEEPERS))
    except Exception as _le:
        print('  *** independent law re-derivations could NOT run (%s) -- every pile member alarms' % _le)
        _LAW_KEEPERS = {u: ['independent law re-derivation unavailable (%s)' % _le] for u in _pile_set}

    # ---- shiny cap context: top-N by IV per (species, form) over the WHOLE bag ----
    # The cap is PER-SPECIES (keep_config per_species_caps.shiny), not the global cap.
    shiny_groups = defaultdict(list)
    for r in bag:
        if r['fresh_shiny']:
            shiny_groups[(r['pokemon_id'], r['form'] or 0)].append(r)
    shiny_kept = set()              # uids inside the per-species cap (within cap)
    for key, lst in shiny_groups.items():
        _rk = sorted(lst, key=_ivkey)
        _sfl = keep_config.shiny_floor_iv(); _first = _rk[0]['uid_hex'] if _rk else None      # shiny floor, best of the form stays (2026-09-24)
        _plsh = [x for x in _rk if not _shiny_is_special(x)]; _first_pl = _plsh[0]['uid_hex'] if _plsh else None   # ...and the best PLAIN one
        _lk = {}                              # every look first, comb up, cap stays (user 2026-09-30, LAW bucket 4)
        for x in _rk:
            _lk.setdefault(((x['fresh_costume'] or 0), evolvable_forms.gender_key(x['pokemon_id'], x['gender'])), x['uid_hex'])
        _lt = set(_lk.values())
        _pok = {x['uid_hex'] for x in ([x for x in _plsh if x['uid_hex'] in _lt]
                                       + [x for x in _plsh if x['uid_hex'] not in _lt
                                          and ((x['iv_total'] or 0) >= _sfl or x['uid_hex'] in (_first, _first_pl))])[:_shiny_plain_cap(key[0])]}
        _el = [x for x in _rk if _shiny_is_special(x) or x['uid_hex'] in _pok]
        for r in ([x for x in _el if x['uid_hex'] in _lt] + [x for x in _el if x['uid_hex'] not in _lt])[:_shiny_cap(key[0])]:
            shiny_kept.add(r['uid_hex'])

    # ---- cosmetic cap context: COSMETIC_CAP / DMAX_CAP / GMAX_CAP per variant over the bag (all from keep_config) ----
    cos_groups = defaultdict(list)
    for r in bag:
        if _is_cosmetic(r):
            cos_groups[_cosmetic_variant_key(r)].append(r)
    cosmetic_kept = set()           # uids inside the per-variant cap (within cap)
    cos_group_cap = {}              # variant key -> the cap that applies to it (for the EXCESS label)
    for key, lst in cos_groups.items():
        # PER-SPECIES override honoured (2026-09-02): the user set cosmetic cap 6 for Pikachu only.
        # keep_policy/audit_cull/_lawcheck already route these through keep_config.species_cap(); this
        # gate read the flat global, so it would have reported 5 phantom REAL_KEEPERs and blocked a
        # correct pile -- the same capped-axis-disagreement class that has now recurred ten times.
        _ax = evolvable_forms.max_axis(key[-1])
        _base = DMAX_CAP if _ax == 'dynamax' else GMAX_CAP if _ax == 'gigantamax' else COSMETIC_CAP
        _cat = 'dynamax' if _ax == 'dynamax' else 'gigantamax' if _ax == 'gigantamax' else 'cosmetic'
        if _cat == 'cosmetic':
            _base = evolvable_forms.costume_cap(key[0], key[2], _base)   # middle-stage costumes keep 1 (2026-09-25)
        cap = keep_config.species_cap(_cat, key[0], _base)
        cos_group_cap[key] = cap
        for r in keep_config.floor_top(__import__('costume_forms').backgrounds_first(sorted(lst, key=_ivkey)))[:cap]:   # collection floor + backgrounds first (2026-09-24)
            cosmetic_kept.add(r['uid_hex'])

    # ---- XXL cap context: top-N by showcase score per (species, cf(form)) over the bag (rule 7) ----
    xxl_kept, xxl_groups = _xxl_kept_uids(bag, _cf_norm)   # uids inside the showcase cap (within cap)

    # ---- NO GYM EXCUSE (user 2026-09-24, "3. sure") ----
    # The live deployment read could only ever EXCUSE a keeper (GYM_LOCKED instead of REAL_KEEPER), and an excused
    # keeper got the Transfer tag and became releasable once knocked out of its gym. Stricter AND cheaper: deployment
    # is not read, every keeper alarms, and this gate never attaches to the phone (it re-walked the bag mid-pass only
    # for this). Non-keepers in gyms are classified as they would be anyway; the game itself refuses to release a
    # deployed mon. live_deployed_uids() stays for verify_kanto_cull.py; nothing in the cull calls it.
    deployed = set()
    deploy_err = None

    # ---- EGG guard context (fail-closed DATA bucket -- see the block above _egg_context) ----
    egg_ctx = _egg_context(c)
    print('  egg guard: %s' % _egg_ctx_note(egg_ctx))

    # ---- classify every Transfer uid ----
    buckets = defaultdict(list)     # class -> [(uid, label)]
    real_keepers = []               # [(uid, species, [reasons], gym_locked_bool)]

    for u in transfer_uids:
        r = rowmap.get(u)
        if r is None:
            buckets['MISSING_FROM_DB'].append((u, 'uid not found in pokemon.db'))
            continue

        # EGG -- checked BEFORE every keep axis, so an egg can neither be classified as fodder nor
        # excused as a keeper: it is not a pokemon, so no verdict about it is meaningful. Same
        # exit(1) / stamp-deleted path as MISSING_FROM_DB.
        _egg_why = _egg_block_reason(r, egg_ctx)
        if _egg_why:
            buckets['EGG'].append((u, _egg_why))
            continue

        # FUSED (2026-09-26) -- fused components hold no ladder slot and are NEVER pile candidates: keep_policy keeps
        # them as 'fused' and the game cannot release one while it is held inside its Kyurem. One in the pile means a
        # kept mon leaked through -- BLOCK (exit 1, no stamp), checked before any keep axis so nothing can excuse it.
        if keep_config.is_fused_component(r):
            buckets['FUSED'].append((u, '%s iv=%s -- held inside a fused Kyurem (kept as fused, never releasable)'
                                     % (r['species_name'], r['iv_total'])))
            continue

        sp = r['species_name']
        gym_locked = u in deployed
        unconditional = _keeper_reasons(r, BS, legacy_set, gm_ok, dex_counts, event_txt, legacy_txt,
                                        dex_form_counts, _cf_norm,
                                        legacy_kept, legacy_capped_pids,
                                        pvp_best=pvp_best_kept)   # all keep axes
        is_shiny = bool(r['fresh_shiny'])
        is_cosmetic = _is_cosmetic(r)
        is_xxl = _is_xxl(r)
        shiny_within_cap = is_shiny and (u in shiny_kept)
        cos_within_cap = is_cosmetic and (u in cosmetic_kept)
        xxl_within_cap = is_xxl and (u in xxl_kept)

        # assemble the full keeper-reason list (cap-aware shiny/costume/XXL folded in)
        reasons = list(unconditional) + list(_LAW_KEEPERS.get(u, ()))   # + the independent LAW re-derivations (H08)
        # CAP axes (shiny top-N / costume top-N / XXL showcase) are NO LONGER re-derived as keepers here:
        # keep_policy owns the cap with cf form-normalization the gate can't perfectly replicate, so the old
        # raw-form re-derivation FALSE-ALARMED in-cap mons and blocked legit culls (user 2026-06-08: lowered
        # shiny cap to 6 -> 11 Eeveelutions wrongly flagged "within top-6"). A cap-EXCESS release is your
        # deliberate trim, not an irreversible mistake. A piled shiny/costume/XXL STILL alarms if it earns an
        # UNCONDITIONAL axis above (hundo, nundo, only-copy, lucky-E+F, legacy, event, mighty, top-PvP, etc.),
        # so every special one is still protected; only plain cap-excess dupes are released.
        #
        # The three *_within_cap flags are NOT alarms (see above) but they are no longer discarded
        # either: they annotate the EXCESS label. If this gate's cap replica says a piled mon is
        # INSIDE its cap, keep_policy trimmed it on some other axis (dominance collapse, a stage
        # cap, ...) and the human deserves to see that rather than a flat "past the cap" claim that
        # may not be true. Informational only -- it can never turn a PLAIN into a FAIL. 2026-09-02

        if reasons:
            # earns a keep axis -> REAL KEEPER (alarm) UNLESS gym-locked (can't be transferred anyway)
            if gym_locked:
                buckets['GYM_LOCKED'].append((u, '%s [%s] (deployed -> SAFE, game blocks transfer)'
                                              % (sp, ', '.join(reasons))))
            else:
                buckets['REAL_KEEPER'].append((u, '%s -- %s' % (sp, ', '.join(reasons))))
                real_keepers.append((u, sp, reasons, gym_locked))
            continue

        # no keep axis earned. cap-excess shiny/costume are EXPECTED transfers.
        if gym_locked:
            # deployed but otherwise plain fodder -- still can't be transferred; report it.
            desc = 'shiny' if is_shiny else ('cosmetic' if is_cosmetic else ('xxl' if is_xxl else 'plain'))
            buckets['GYM_LOCKED'].append((u, '%s [%s] (deployed -> SAFE, game blocks transfer)' % (sp, desc)))
        elif is_shiny:      # shiny but not within cap => cap-excess
            grp = shiny_groups.get((r['pokemon_id'], r['form'] or 0), [])
            _sc = _shiny_cap(r['pokemon_id'])            # PER-SPECIES cap, not the global one
            buckets['SHINY_EXCESS'].append(
                (u, '%s shiny iv=%s (#%d+ of %d -> past top-%d cap)%s'
                 % (sp, r['iv_total'], _sc + 1, len(grp), _sc, _capnote(shiny_within_cap))))
        elif is_cosmetic:   # cosmetic but not within cap => cap-excess
            _ck = _cosmetic_variant_key(r)
            grp = cos_groups.get(_ck, [])
            _cc = cos_group_cap.get(_ck, COSMETIC_CAP)   # Dmax/Gmax variants use their OWN cap
            _kind = {1: 'Dynamax', 2: 'Gigantamax'}.get(_ck[-1], 'cosmetic')
            buckets['COSTUME_EXCESS'].append(
                (u, '%s %s iv=%s (variant has %d -> past top-%d cap)%s'
                 % (sp, _kind, r['iv_total'], len(grp), _cc, _capnote(cos_within_cap))))
        elif is_xxl:        # XXL but not in the showcase set => cap-excess (rule 7 keeps top-N by showcase score)
            grp = xxl_groups.get(__import__('pvp_iv_rule').pvid(r['species_name'], r['form'] or 0), [])
            buckets['XXL_EXCESS'].append(
                (u, '%s XXL h=%.2f w=%.2f (%d XXL of this form -> not in the showcase top-%d)%s'
                 % (sp, r['height_m'] or 0, r['weight_kg'] or 0, len(grp),
                    _xxl_cap(r['pokemon_id']), _capnote(xxl_within_cap))))
        elif (r['uid_hex'] in legacy_set or r['uid_hex'] in legacy_txt)                 and r['pokemon_id'] in legacy_capped_pids:
            # legacy mon of a CAPPED species, past the cap -> the user's deliberate trim (rule 6),
            # exactly like the other cap-excess buckets. Reported separately so an over-cap legacy
            # release is visible rather than hiding in PLAIN. (lockdown 2026-09-02)
            _lcount = sum(1 for x in bag if x['pokemon_id'] == r['pokemon_id'] and x['uid_hex'] in legacy_set)
            buckets['LEGACY_EXCESS'].append(
                (u, '%s legacy iv=%s (%d legacy of this species -> past the per-species cap of %d)'
                 % (sp, r['iv_total'], _lcount,
                    keep_config.legacy_caps().get(r['pokemon_id'], keep_config.legacy_default_cap()))))
        else:
            buckets['PLAIN'].append((u, '%s iv=%s' % (sp, r['iv_total'])))

    # ---- report ----
    print("=" * 78)
    print("TRANSFER PRE-FLIGHT  --  %d uids in %s" % (len(transfer_uids), os.path.relpath(TRANSFER_TXT, ROOT)))
    print("PvP viability source: %s" % _VIABILITY_NOTE)
    if deploy_err is not None:
        print("!! LIVE DEPLOYMENT READ FAILED: %s" % deploy_err)
        print("!! deployment is UNKNOWN -> any keeper below is treated as a NON-gym-locked ALARM"
              " (no mon can be cleared as gym-locked). Re-run with Frida available.")
    else:
        print("Gym excuse OFF (2026-09-24): deployment not read -- a keeper in a gym alarms like any other.")
    if missing:
        print("!! %d uid(s) in Transfer.txt are NOT in pokemon.db: %s" % (len(missing), missing[:10]))
    print("-" * 78)

    order = ['PLAIN', 'COSTUME_EXCESS', 'SHINY_EXCESS', 'XXL_EXCESS', 'LEGACY_EXCESS',
             'GYM_LOCKED', 'REAL_KEEPER', 'FUSED', 'EGG', 'MISSING_FROM_DB']
    total = 0
    for cls in order:
        n = len(buckets.get(cls, []))
        total += n
        print("  %-16s %4d" % (cls, n))
    print("  %-16s %4d" % ('TOTAL', total))
    print("-" * 78)

    # always show the gym-locked detail (informational: these are safe but won't actually transfer)
    if buckets.get('GYM_LOCKED'):
        print("GYM-LOCKED (deployed -> cannot be transferred in-game; SAFE in the pile):")
        for u, lbl in buckets['GYM_LOCKED']:
            print("    %s  %s" % (u, lbl))
        print("-" * 78)

    # the alarm list
    alarms = buckets.get('REAL_KEEPER', [])
    if alarms:
        print("!! REAL KEEPER(S) IN TRANSFER -- %d (NOT gym-locked) !!" % len(alarms))
        for u, lbl in alarms:
            print("    ALARM  %s  %s" % (u, lbl))
        print("=" * 78)
        print("RESULT: FAIL -- the irreversible Transfer pile contains %d real keeper(s). DO NOT"
              " transfer. Investigate keep_policy / the tagset before releasing." % len(alarms))
        sys.exit(1)

    # FUSED (2026-09-26): a component held inside a fused Kyurem is kept by law and cannot be released -- BLOCK.
    if buckets.get('FUSED'):
        print("=" * 78)
        print("!! FUSED COMPONENT(S) IN TRANSFER -- %d !!" % len(buckets['FUSED']))
        for u, lbl in buckets['FUSED']:
            print("    BLOCK  %s  %s" % (u, lbl))
        print("RESULT: FAIL -- %d Transfer uid(s) are Reshiram / Zekrom held inside a fused Kyurem. keep_policy keeps"
              " them as 'fused' (no ladder slot, never a pile candidate). Fix keep_policy / the tagset before"
              " releasing." % len(buckets['FUSED']))
        sys.exit(1)

    # EGG is a DATA failure of the same kind as MISSING_FROM_DB, not a keeper alarm: an egg is
    # not a bag pokemon, so "is it safe to release?" has no valid answer for it.
    if buckets.get('EGG'):
        print("=" * 78)
        print("!! EGG(S) / UNREADABLE is_egg IN TRANSFER -- %d !!" % len(buckets['EGG']))
        for u, lbl in buckets['EGG']:
            print("    EGG    %s  %s" % (u, lbl))
        print("RESULT: FAIL -- %d Transfer uid(s) are eggs, or carry an is_egg nobody wrote. An egg"
              " is not a bag pokemon and must never be blessed into a hand-release list. Fix the"
              " tagset (or the pipeline that let one in) before releasing." % len(buckets['EGG']))
        sys.exit(1)

    # missing-from-DB is also a hard fail: we cannot vouch for a uid we can't read.
    if buckets.get('MISSING_FROM_DB'):
        print("=" * 78)
        print("RESULT: FAIL -- %d Transfer uid(s) are not present in pokemon.db; cannot verify they"
              " are safe to release." % len(buckets['MISSING_FROM_DB']))
        sys.exit(1)

    # A FAILED live deployment read must NOT print PASS. deploy_err was set, printed, and then
    # dropped -- so with Frida down this gate advertised "reads DEPLOYMENT LIVE off the proto" in
    # its own header, skipped that read entirely, and still exited 0. The keeper verdict itself is
    # conservative when deployment is unknown (nothing can be cleared as gym-locked, so every
    # keeper alarms), but a gate that reports a check it did not perform is not a gate. Callers
    # that genuinely cannot reach Frida can opt in explicitly. (lockdown 2026-09-02)
    if deploy_err is not None and not _ALLOW_NO_LIVE_DEPLOYMENT:
        print("=" * 78)
        print("RESULT: FAIL -- no real keeper was found, BUT the LIVE deployment read failed (%s),"
              " so this run did not perform the gym check it reports. Re-run with Frida available,"
              " or pass --allow-no-live-deployment to accept a DB-only verdict." % deploy_err)
        sys.exit(1)

    print("RESULT: PASS -- every Transfer uid is PLAIN fodder, expected cap-excess"
          " (cosmetic>top-%d / shiny>top-%d(+per-species) / XXL>top-%d / legacy>per-species cap)."
          " No real keeper in the pile."
          % (COSMETIC_CAP, SHINY_CAP, XXL_CAP)
          + ("" if deploy_err is None else
             "  [live deployment read FAILED and --allow-no-live-deployment was given:"
             " the gym check was NOT performed this run.]"))

    # THE ONLY place a stamp is ever created. Reached only after every FAIL path above has been
    # cleared, so it describes a pile that really was vetted against every keep axis.
    #
    # A PASS under --allow-no-live-deployment DOES stamp, deliberately: the live gym read can only
    # ever DOWNGRADE an alarm (a deployed keeper is game-blocked from transfer, so it is filed
    # GYM_LOCKED instead of REAL_KEEPER). With deployment unknown nothing can be downgraded, so
    # every keeper alarms and this PASS means "not one keep axis anywhere in the pile" -- a
    # STRICTER verdict than a Frida-backed PASS, not a weaker one. The caveat is printed above.
    if deploy_err is not None:
        print("STAMP: note -- this PASS was reached WITHOUT the live gym read (the keeper verdict"
              " was strictly stricter for it: nothing could be excused as gym-locked).")
    _write_stamp(pile_sha256, len(transfer_uids))


if __name__ == '__main__':
    # Belt-and-braces. main() only writes on its final PASS line and the stamp was already
    # destroyed at start-up -- but if a future edit ever adds code AFTER that write, a failure
    # there must not leave a receipt for a run that did not finish.
    try:
        main()
    except SystemExit as _e:
        if (_e.code or 0) != 0:            # any non-zero exit is a FAIL / partial run
            _invalidate_stamp('run exited %r' % (_e.code,))
        raise
    except BaseException:                  # exceptions AND KeyboardInterrupt
        _invalidate_stamp('run raised before finishing')
        raise
