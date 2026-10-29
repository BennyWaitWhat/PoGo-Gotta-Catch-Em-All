"""prune_tags.py -- make each named server tag EXACTLY equal its tagset file.

Bidirectional, single-attach, fresh-everything (the only thing that persists):
  * removal  = server_uids - want   -> untag_one() w/ fresh create_tag tagproto
  * addition = want - server_uids    -> apply_members() w/ same fresh tagproto
Then RE-ENUMERATE and verify SET EQUALITY (not just counts -- counts can match
while membership differs, which is exactly the leading-zero bug this fixes).

uid normalization: EVERYTHING is compared as unpadded lowercase hex
(format(int(x,16),'x')). DB uid_hex is zero-padded to 16 chars, the bag-walk
yields decimals; normalizing both via int() is the only safe comparison. The
earlier version compared padded file strings to unpadded bag hex, so the 296
leading-zero uids never matched -> false drift + wrongly-stripped members.

THIS SCRIPT NEVER TOUCHES pokemon.db. It reads the tagset FILES and writes the phone; the DB mirror
(auth_tag_names) is set_db_tags_from_files.py's job, and reconcile_tags.py compares the two. So a
STANDALONE prune_tags run leaves auth_tag_names describing the PREVIOUS push, and the next reconcile
reports drift that is not real. Run set_db_tags_from_files.py AFTER this (that is the order the
dashboard's /api/sync uses -- mirror last, so the DB only ever records a push that verified).

EXIT CODE: 0 only if every targeted tag verified as an exact set match AND every add/remove applied.
Non-zero means the push did not fully land -- do not mirror it, do not call the sync done.

WHICH TAGS: PLAN comes from granular_tags.registry() -- the legacy table plus the whole tag
VOCABULARY, so a tag stays managed even in a cycle where nothing qualifies for it. A tagset file
with no plan entry and no entry in granular_tags.EXEMPT_TAGSETS aborts the run (D5). A planned tag
with no file is SKIPPED, never pushed as an empty set. `python granular_tags.py --audit` prints the
whole registry offline -- no DB, no device.

PRE-FLIGHT STAMP GATE: any push that includes the 'Transfer' tag -- and the DEFAULT no-args
push does, because targets falls back to list(PLAN) -- REFUSES with exit 2 unless
system/analysis/preflight_stamp.json proves preflight_transfer.py PASSED, within the last 30
minutes, over this exact Transfer.txt, this keep_config fingerprint and this db. Missing,
unreadable, malformed, mismatched or stale all refuse. --force does NOT bypass it (--force
bypasses ready_gate only). Non-Transfer tags are unaffected. See require_preflight_stamp().

Usage:
  python prune_tags.py [--dry-run] [--atomic] [--force] ["Legacy Moves" "GL IV" ...]   (default: all)
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
os.chdir(ROOT)
import time
import re
import json
import hashlib
from datetime import datetime, timezone
import pogo_il2cpp as pg
import tag_ops
from reconcile_tags import ENUM_MEMBERS_JS, stale_members

TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets')

# THE PUSH PLAN lives in granular_tags.registry() -- the historical LEGACY_TAGS table (11 original
# tags whose filenames and colours must never move, or their on-device members are orphaned) plus
# granular_tags.all_tags(), the full VOCABULARY of labels build() can emit. Deriving it there rather
# than restating it here is what stops build_tagsets and prune disagreeing about a filename -- they
# did once ('Variant Floor' -> Top_Of_Kind.txt vs Variant_Floor.txt) and the push silently sent a
# frozen file for hours while the newest catches went untagged.
#
# D5 (2026-09-07) -- WHY IT IS THE VOCABULARY AND NOT build()'s RETURN VALUE.
# This function used to derive the plan by CALLING granular_tags.build() and taking the keys, i.e.
# the tags that happened to have >=1 member at that moment. A tag whose membership fell to zero
# therefore vanished from PLAN -- while build_tagsets left its last tagset file on disk, and
# set_db_tags_from_files (which consumes EVERY .txt, plan or not) kept mirroring that frozen file
# into auth_tag_names. The tag stayed live on the phone and in the DB and became invisible to the
# only script that could ever correct it.
#   Proven case: 'Safety Hold' (rank_unknown / data_incomplete). Emitted 2026-09-03 for one
#   Enamorus, pushed; the mon's reasons then changed to dex_only_copy/rarity/variant_floor, build()
#   stopped emitting it, Safety_Hold.txt froze at 1 uid, and on 2026-09-07 the tag was nearly
#   deleted as stale legacy cruft. Only a file-existence check caught it.
# The registry is data-independent, so a zero-member tag KEEPS its plan entry and stays managed.
# It also makes the plan derivable with no DB at all -- reconcile_tags imports PLAN purely for its
# allowlist and no longer drags a SELECT * over 5,700 rows to get it.
_LEGACY_PLAN = None       # set below from granular_tags.LEGACY_TAGS; kept as a name for old callers


def _build_plan():
    global _LEGACY_PLAN
    try:
        import granular_tags
    except Exception as e:                      # fail LOUD: a silently short PLAN pushes stale tags
        raise SystemExit('prune_tags: could not import granular_tags to derive the tag registry '
                         '(%s). PLAN is the ONLY thing that decides which tags get pushed -- a '
                         'short one leaves live tags unmanaged. Fix the import; do not push.' % e)
    _LEGACY_PLAN = granular_tags.LEGACY_TAGS
    plan = granular_tags.registry()
    # FATAL on a tagset file with no plan entry and no explicit exemption -- that is the D5 state.
    granular_tags.audit_registry(plan, td=TD)
    return plan


PLAN = _build_plan()

# Tags that are LIVE on the device but deliberately NOT pushed here, each with its owning script --
# see granular_tags.EXEMPT_TAGSETS for the reason per file. Re-exported so reconcile_tags can use
# (PLAN | EXEMPT_TAGS) as its managed-set allowlist instead of hardcoding 'Evolve Shiny' and
# reporting the two Armored snapshots as untracked drift forever.
import granular_tags as _gt          # noqa: E402  (PLAN above already imported it successfully)
EXEMPT_TAGS = _gt.EXEMPT_TAGS



def norm(x):
    """Canonical uid: unpadded lowercase hex, from hex string OR decimal int."""
    return format(int(x, 16), 'x')


def file_uids(fn):
    return {norm(u) for u in open(os.path.join(TD, fn)).read().split() if u.strip()}


def enum_by_name(sess, svc):
    en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
    try:
        return {t['name']: t for t in en.exports_sync.enumerate_all_tag_members(svc)}
    finally:
        en.unload()


def live_hex_fn(hex_to_proto):
    """dec uid (a binding's memberUids entry) -> this script's unpadded hex key, or None when the mon is not in the walk."""
    return lambda d: (lambda h: h if h in hex_to_proto else None)(format(int(d), 'x'))


def server_uids_of(info, proto_to_hex, stale=None):
    """-> (members, unmapped, confirmed). `members` also holds STALE-BOUND live mons (the binding kept an older proto
    object -- reconcile_tags.stale_members, 2026-09-26): enough to call a mon an EXTRA, since that only ever leads to a
    removal. `confirmed` holds them only when the mon's live pokemonTagIds_ lists the tag -- use it for ADD / SHORT, so
    a write the game dropped is still re-added and still fails the verify. `unmapped` = entries whose own uid is not in
    the bag either (transferred / unreadable)."""
    s, unmapped = set(), 0
    _mu = info.get('memberUids') or []
    _live = None
    for j, pp in enumerate(info['members']):
        uh = proto_to_hex.get(pp)
        if uh:
            s.add(uh)
            continue
        if j < len(_mu) and _mu[j]:
            if _live is None:
                _live = set(proto_to_hex.values())
            if format(int(_mu[j]), 'x') in _live:
                continue                    # stale-bound live mon: counted through `stale` below
        unmapped += 1
    st, conf = (stale or {}).get(info.get('idx', info.get('name')), (set(), set()))
    return s | st, unmapped, s | conf


# ==============================================================================================
# THE PRE-FLIGHT STAMP GATE -- the one thing between this script and an irreversible pile.
# ==============================================================================================
# WHY IT EXISTS (2026-09-07). This file was a LIVE, UNGATED route to the phone's Transfer tag.
# The word "preflight" did not appear in it once. 'Transfer' sits in PLAN with no exclusion, and
# main() computes
#       targets = [...] or list(PLAN)
# so a BARE `python prune_tags.py` pushed all 46 tags INCLUDING Transfer, live, by default. The
# only check in the whole file was ready_gate -- a battery/foreground WRITE-RELIABILITY check that
# says nothing whatsoever about whether a keeper is in the pile -- and --force skipped even that.
# It calls the tag_ops PRIMITIVES directly (create_tag / apply_members / untag_one / apply_changes
# / ensure_ready), every one of which is GATED=False, so hardening the tag_ops CLI closed a side
# door and left this one open. RUNBOOK.md:72 and HANDOFF_KEEP_LAW.md:19 both tell a HUMAN to run
# this script by hand.
#
# ROOT CAUSE: preflight_transfer.py's verdict existed ONLY as an exit code. Nothing downstream
# could confirm it had ever run, so the keeper gate was not so much bypassed as UNOBSERVABLE. The
# fix is an ARTIFACT: preflight writes system/analysis/preflight_stamp.json on a FULL PASS only,
# and this script refuses to push the pile without one that still describes the world it vetted.
#
# WHY A STAMP AND NOT A SUBPROCESS: Frida is SINGLE-CLIENT, and the dashboard already runs
# preflight_transfer.py as its own gate step immediately before this one (dashboard.py:199, then
# :221). Shelling out to preflight from inside prune would be a SECOND attach to a device that
# permits exactly one.
#
# THE CONTRACT (shared verbatim with the producer, preflight_transfer.py):
#   pile_sha256    sha256 of the EXACT bytes of system/analysis/tagsets/Transfer.txt it vetted
#   pile_uids      count of uids vetted (a cheap human-readable cross-check)
#   config_sha256  keep_config.fingerprint() -- the MERGED config, _note excluded, NOT file bytes
#   db_sha256      the db_content_sha256 value from system/analysis/pile_provenance.json
#   generated      UTC ISO-8601 timestamp
#   schema         1
# REFUSE (sys.exit(2)) unless ALL of these hold: the stamp exists, parses and is complete;
# pile_sha256 equals a FRESH hash of the CURRENT Transfer.txt; config_sha256 equals the live
# keep_config.fingerprint(); db_sha256 equals the live provenance value; generated is younger
# than 30 minutes.
#
# FAIL CLOSED: missing, unreadable, malformed, mismatched or stale ALL refuse. Never push what was
# not inspected.
#
# WHY THE *FILE* AND NOT THE DB MIRROR: the pile file and auth_tag_names drift by design -- right
# now the file holds 26 uids and the mirror 25, because the 01:52 and 01:53 syncs both failed and
# the mirror never recorded the new Scorbunny (set_db_tags_from_files runs LAST, only after a
# VERIFIED push). That lag is benign and self-healing; keying the gate off it would wedge the
# pipeline for a reason that has nothing to do with keeper safety. The stamp binds the FILE, which
# is the exact thing prune pushes.
#
# --force DOES NOT BYPASS THIS. --force bypasses ready_gate and NOTHING else. That is enforced by
# construction, not by discipline: `force` is never passed to require_preflight_stamp() and the
# function takes no such parameter, so there is no argument for a future caller to thread through.
# In main(), `force` is read exactly twice -- the ready_gate notice and the ready_gate branch. A
# battery override must never double as a keeper override.
STAMP_PATH          = os.path.join(ROOT, 'system', 'analysis', 'preflight_stamp.json')
PROV_PATH           = os.path.join(ROOT, 'system', 'analysis', 'pile_provenance.json')
PILE_TAG            = 'Transfer'        # the ONE irreversible tag
PILE_FILE           = 'Transfer.txt'    # the exact bytes preflight vets and stamps
STAMP_MAX_AGE_S     = 30 * 60           # contract: younger than 30 minutes
STAMP_FUTURE_SKEW_S = 120               # a far-FUTURE stamp would never expire -> treat as bogus
STAMP_SCHEMA        = 2           # 2 (H03, 2026-09-29): + walk_fp, see check 9
_STAMP_FIELDS       = ('schema', 'pile_sha256', 'pile_uids', 'config_sha256', 'db_sha256',
                       'generated', 'walk_fp')
WALK_AGE_WARN_MS    = 5 * 60 * 1000   # walk_tripwires.AGE_STOP_MS -- the push-time twin of GRAPH_STALE (a WARN)
_RUN_PREFLIGHT      = ('run  python system/scripts/preflight_transfer.py  and let it PASS (rc 0), '
                       'or drive the whole cycle from the dashboard, which runs preflight as its '
                       'gate step immediately before this script.')


def _norm_tag(s):
    """Canonical form of a tag TOKEN, purely for the question 'is this the Transfer pile?'.

    Accepts every spelling that has ever reached this script's argv or its PLAN:
        'Transfer', 'transfer', 'TRANSFER', '6 Transfer', '6_Transfer', 'Transfer.txt',
        'system/analysis/tagsets/6_Transfer.txt'   ->   'transfer'
    It deliberately OVER-matches. '6_Transfer' is the raw pile file (EXEMPT_TAGSETS -- there is no
    6_Transfer tag on the device, so the main loop would only ever 'skip unknown' it), but a run
    that NAMES the pile still has to prove preflight passed. Refusing a target that would have been
    skipped costs one re-run; missing a spelling costs the collection.
    """
    t = os.path.basename(str(s).strip().strip('\'"'))
    if t.lower().endswith('.txt'):
        t = t[:-4]
    t = ' '.join(re.sub(r'[^a-z0-9]+', ' ', t.lower()).split())
    return re.sub(r'^\d+\s+', '', t)            # drop the '6 ' ordinal prefix of 6_Transfer


def _is_pile_target(name):
    return _norm_tag(name) == _norm_tag(PILE_TAG)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


def _stamp_refuse(cond, detail, fix):
    """Print WHICH condition failed and HOW to clear it, then exit 2. Never returns."""
    bar = '=' * 92
    print('\n' + bar)
    print('REFUSING TO PUSH THE TRANSFER PILE -- %s' % cond)
    print(bar)
    for ln in detail.splitlines():
        print('  ' + ln)
    print('  FIX: ' + fix)
    print('  Nothing was written and no session was opened -- this check runs BEFORE the Frida')
    print('  attach. Non-Transfer tags are unaffected: name them explicitly, e.g.')
    print('      python system/scripts/prune_tags.py --atomic "Shiny #1" "Legacy Moves"')
    print('  --force does NOT bypass this gate. --force bypasses ready_gate (battery/foreground')
    print('  write-reliability) and nothing else; it is not a keeper override.')
    print(bar)
    sys.exit(2)


def _stamp_parse_generated(raw):
    """UTC-aware datetime from the stamp's 'generated', or None if it is not a timestamp.

    Tolerant on FORM (trailing Z, +00:00, a space instead of 'T', with or without microseconds)
    and strict on MEANING: a naive timestamp is read as UTC, because the contract says UTC.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip().replace('Z', '+00:00').replace('z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def require_preflight_stamp(targets):
    """REFUSE (exit 2) unless preflight_transfer.py vetted exactly this pile, just now.

    Called from main() AFTER `targets` is final and BEFORE pg.get_session(), so a refusal costs
    zero device contact. Returns False when this push does not include the pile (the routine
    tag-sync path, whose behaviour is completely unchanged), True when the stamp verified.

    Takes NO force parameter -- see the block comment above.
    """
    hits = sorted({t for t in targets if _is_pile_target(t)})
    if not hits:
        return False                     # routine tag sync: not our business, carry on unchanged
    print('\n[preflight-stamp] this push includes the TRANSFER pile (target%s %s) -- the one '
          'irreversible output. Verifying %s'
          % ('' if len(hits) == 1 else 's', ', '.join(repr(h) for h in hits),
             os.path.join('system', 'analysis', 'preflight_stamp.json')))

    # -- 0. the stamp describes Transfer.txt; if PLAN pushes some OTHER file under that tag, the
    #       stamp would be vouching for bytes we are not sending. Contract drift -> refuse.
    _planned = PLAN.get(PILE_TAG)
    if _planned and _planned[0] != PILE_FILE:
        _stamp_refuse('CONTRACT DRIFT: the %r tag no longer pushes %s' % (PILE_TAG, PILE_FILE),
                      'PLAN[%r] pushes %r, but the stamp contract vouches for %r.\n'
                      'A stamp over one file cannot authorise pushing a different one.'
                      % (PILE_TAG, _planned[0], PILE_FILE),
                      'restore the historical filename in granular_tags.LEGACY_TAGS, or update '
                      'BOTH halves of the stamp contract (preflight_transfer.py and this file) '
                      'together.')

    # -- 1. the pile file itself must be readable: it is what we hash and what we would push.
    pile_path = os.path.join(TD, PILE_FILE)
    try:
        live_pile_sha = _sha256_file(pile_path)
        live_pile_n = len(file_uids(PILE_FILE))
    except OSError as e:
        _stamp_refuse('PILE FILE UNREADABLE',
                      'could not read %s\n  %s' % (pile_path, e),
                      'regenerate it with keep_policy.py -> build_tagsets.py, then '
                      + _RUN_PREFLIGHT)

    # -- 2. EXISTS -----------------------------------------------------------------------------
    if not os.path.exists(STAMP_PATH):
        _stamp_refuse('NO PRE-FLIGHT STAMP',
                      'there is no %s, so nothing can confirm preflight_transfer.py ever ran\n'
                      'against this pile. Its verdict used to live only in an exit code; the\n'
                      'stamp is that verdict made observable. No stamp = not inspected.'
                      % STAMP_PATH,
                      _RUN_PREFLIGHT)

    # -- 3. READABLE and PARSES ----------------------------------------------------------------
    try:
        raw = open(STAMP_PATH, 'rb').read()
    except OSError as e:
        _stamp_refuse('STAMP UNREADABLE', 'open(%s) failed: %s' % (STAMP_PATH, e),
                      'fix the permissions, delete the file, and ' + _RUN_PREFLIGHT)
    try:
        stamp = json.loads(raw.decode('utf-8'))
    except Exception as e:
        _stamp_refuse('STAMP MALFORMED (not valid JSON)',
                      '%s did not parse: %s\n  first 200 bytes: %r'
                      % (STAMP_PATH, e, raw[:200]),
                      'delete the corrupt stamp and ' + _RUN_PREFLIGHT)
    if not isinstance(stamp, dict):
        _stamp_refuse('STAMP MALFORMED (not a JSON object)',
                      'expected an object with %s; got %s'
                      % (', '.join(_STAMP_FIELDS), type(stamp).__name__),
                      'delete the bad stamp and ' + _RUN_PREFLIGHT)

    # -- 4. COMPLETE ---------------------------------------------------------------------------
    missing = [k for k in _STAMP_FIELDS if k not in stamp or stamp[k] in (None, '')]
    if missing:
        _stamp_refuse('STAMP MALFORMED (incomplete)',
                      'missing or empty field(s): %s\n  present: %s'
                      % (', '.join(missing), ', '.join(sorted(stamp)) or '(none)'),
                      'a partial stamp means a partial run -- ' + _RUN_PREFLIGHT)
    if stamp.get('schema') != STAMP_SCHEMA:
        _stamp_refuse('STAMP SCHEMA MISMATCH',
                      'stamp schema=%r, this consumer understands schema=%d.\n'
                      'A schema this consumer does not understand may not mean what it looks like.'
                      % (stamp.get('schema'), STAMP_SCHEMA),
                      'upgrade both halves of the contract together, then ' + _RUN_PREFLIGHT)
    if not isinstance(stamp['pile_uids'], int) or isinstance(stamp['pile_uids'], bool):
        _stamp_refuse('STAMP MALFORMED (pile_uids is not an integer)',
                      'pile_uids=%r (%s)'
                      % (stamp['pile_uids'], type(stamp['pile_uids']).__name__),
                      'delete the bad stamp and ' + _RUN_PREFLIGHT)

    # -- 5. THE PILE IS THE ONE THAT WAS VETTED ------------------------------------------------
    #    This is the load-bearing check: it binds the verdict to the EXACT BYTES. build_tagsets
    #    rewrites Transfer.txt on every engine run, so any recrawl between preflight and here
    #    invalidates the stamp -- which is exactly right. It is also why the tripwire is a hash of
    #    the CURRENT file rather than a remembered one: only a fresh read can catch a rewrite.
    if stamp['pile_sha256'] != live_pile_sha:
        _stamp_refuse('PILE CHANGED SINCE PRE-FLIGHT (pile_sha256 mismatch)',
                      'stamp vouches for : %s\n  %s is now: %s\n'
                      'The pile was regenerated (a recrawl / keep_policy / build_tagsets run)\n'
                      'after preflight inspected it, so the vetted pile and the pile about to be\n'
                      'pushed are NOT the same set of pokemon.'
                      % (stamp['pile_sha256'], PILE_FILE, live_pile_sha),
                      'do not push a pile nobody inspected -- ' + _RUN_PREFLIGHT)
    if stamp['pile_uids'] != live_pile_n:
        _stamp_refuse('STAMP INTERNALLY INCONSISTENT (pile_uids mismatch)',
                      'stamp says it vetted %d uid(s); %s holds %d.\n'
                      'The BYTES matched, so this is a producer-side counting bug, not a changed\n'
                      'pile -- but a stamp that miscounts what it inspected is not evidence.'
                      % (stamp['pile_uids'], PILE_FILE, live_pile_n),
                      'fix the count preflight_transfer.py writes, then ' + _RUN_PREFLIGHT)

    # -- 6. SAME POLICY ------------------------------------------------------------------------
    #    keep_config.fingerprint() is THE definition (merged config, '_note' excluded), so the
    #    producer and every consumer compute it one way. A cap edited between preflight and now
    #    would silently mean a different pile.
    try:
        import keep_config
        live_cfg = keep_config.fingerprint()
    except Exception as e:
        _stamp_refuse('CANNOT VERIFY CONFIG FINGERPRINT',
                      'keep_config.fingerprint() raised: %r\n'
                      'Unable to prove the policy is the one preflight vetted.' % (e,),
                      'repair keep_config.py / keep_config.json, then ' + _RUN_PREFLIGHT)
    if stamp['config_sha256'] != live_cfg:
        _stamp_refuse('KEEP POLICY CHANGED SINCE PRE-FLIGHT (config_sha256 mismatch)',
                      'stamp vetted config: %s\n  live config now   : %s\n'
                      'A cap, roster or rule moved after preflight ran. The pile on disk was\n'
                      'produced under one policy and vetted under another.'
                      % (stamp['config_sha256'], live_cfg),
                      're-run the engine (keep_policy.py -> build_tagsets.py), then '
                      + _RUN_PREFLIGHT)

    # -- 7. SAME DATABASE ----------------------------------------------------------------------
    #    autocull_watch.py recrawls on a timer and rewrites pokemon.db underneath us; the
    #    provenance file is the pile producer's record of WHICH db content it read.
    try:
        prov = json.loads(open(PROV_PATH, 'rb').read().decode('utf-8'))
        live_db = prov['db_content_sha256']
    except Exception as e:
        _stamp_refuse('CANNOT VERIFY DB PROVENANCE',
                      'could not read db_content_sha256 from %s: %r' % (PROV_PATH, e),
                      're-run keep_policy.py (it writes pile_provenance.json), then '
                      + _RUN_PREFLIGHT)
    if stamp['db_sha256'] != live_db:
        _stamp_refuse('DATABASE CHANGED SINCE PRE-FLIGHT (db_sha256 mismatch)',
                      'stamp vetted db: %s\n  live provenance: %s\n'
                      'A recrawl replaced the bag snapshot the pile was derived from\n'
                      # NOTE: the watcher is named in the '# -- 7.' comment above, NOT in
                      # this string. audit_invariants._invokes() reads .py filenames out
                      # of string CONSTANTS, so spelling it here fabricates a
                      # prune -> autocull_watch edge and grows I6's entry-point closure
                      # over a script this file does not run. The FIX text below still
                      # names the scripts the operator must actually RUN.
                      '(the autocull recrawl watcher runs on a timer and does this).'
                      % (stamp['db_sha256'], live_db),
                      're-run the engine against the current db, then ' + _RUN_PREFLIGHT)

    # -- 8. STILL FRESH ------------------------------------------------------------------------
    gen = _stamp_parse_generated(stamp['generated'])
    if gen is None:
        _stamp_refuse('STAMP MALFORMED (unparseable timestamp)',
                      'generated=%r is not a UTC ISO-8601 timestamp, so freshness cannot be\n'
                      'established -- and an unaged stamp never expires.' % (stamp['generated'],),
                      'delete the bad stamp and ' + _RUN_PREFLIGHT)
    age = (datetime.now(timezone.utc) - gen).total_seconds()
    if age < -STAMP_FUTURE_SKEW_S:
        _stamp_refuse('STAMP TIMESTAMP IS IN THE FUTURE',
                      'generated=%s is %.1f min ahead of now. A future stamp would never go\n'
                      'stale, which turns the freshness rule off entirely.'
                      % (stamp['generated'], -age / 60.0),
                      'fix the clock (or the producer), then ' + _RUN_PREFLIGHT)
    if age > STAMP_MAX_AGE_S:
        _stamp_refuse('STALE PRE-FLIGHT STAMP (older than %d minutes)' % (STAMP_MAX_AGE_S // 60),
                      'generated=%s\n  age=%.1f min, limit=%d min.\n'
                      'The bag moves constantly -- catches, evolutions, trades, and the\n'
                      'autocull_watch recrawl. An old PASS is not evidence about the pile now.'
                      % (stamp['generated'], age / 60.0, STAMP_MAX_AGE_S // 60),
                      _RUN_PREFLIGHT)

    # -- 9. THE WALK WAS LIVE (H03, 2026-09-29) --------------------------------------------------
    #    Checks 5-8 bind the pile to its config and its db -- and a pile built from a FROZEN walk agrees with its own
    #    frozen db perfectly (the 05:06 / 05:09 / 05:11 piles all stamped PASS). walk_fp is the walk tripwires' verdict
    #    on the walk the pile came from; only OK or WARN (e.g. PoGo backgrounded) may authorise the pile.
    wfp = stamp.get('walk_fp')
    if not isinstance(wfp, dict) or wfp.get('verdict') not in ('OK', 'WARN'):
        _stamp_refuse('THE PILE WAS JUDGED ON A WALK NOBODY PROVED LIVE (walk_fp %s)'
                      % ('missing' if not isinstance(wfp, dict) else 'verdict=%r' % wfp.get('verdict')),
                      'walk_fp=%r\n'
                      'The walk tripwires either did not run for the walk this pile was built from, or stopped it.'
                      % (wfp,),
                      're-run the recrawl (python full_audit.py), then ' + _RUN_PREFLIGHT)
    # -- 10. THE WALK'S ACCOUNT WAS READ (H10-5, 2026-09-29) ----------------------------------------
    #    account_guard only WARNS when it cannot read the trainer name (the walk goes on), so a pile could be built from
    #    a bag nobody identified -- another trainer's, after a login switch -- and reach that phone's Transfer tag. The
    #    purge already needs a positive match (pogo_pipeline, H07); the irreversible pile needs at least a name.
    if not str(wfp.get('trainer') or '').strip():
        _stamp_refuse('THE PILE WAS JUDGED ON A WALK WHOSE ACCOUNT WAS NOT READ (trainer name unreadable)',
                      'walk_fp=%r\n'
                      'account_guard could not read the trainer name on that walk, so nobody proved whose bag it was.'
                      % (wfp,),
                      're-run the recrawl (python full_audit.py) once the game shows the map, then ' + _RUN_PREFLIGHT)

    print('[preflight-stamp] OK -- preflight PASSED %.1f min ago over this exact pile:'
          % (age / 60.0))
    print('    pile   %s  %s...  (%d uids)' % (PILE_FILE, live_pile_sha[:16], live_pile_n))
    print('    config %s...   db %s...' % (live_cfg[:16], live_db[:16]))
    print('    (TAGGING IS NOT RELEASING: this authorises the TAG only. The user releases by hand.)')
    return True


def _refuse_unproven_graph(sess, pid, targets):
    """THE PUSH-TIME TRIPWIRE (H03, 2026-09-29). The 05:00 push wrote 41 Transfer tags into a TaggingRpcService the
    game had abandoned -- "41 tagged", "All tags in sync", "VERIFY OK", Transfer 0 in the game. Two checks on the graph
    this session is about to write through (pg.live_graph, already resolved by the bag/svc picks above):
      a. its InventoryCache was updated recently by the PHONE's clock (a graph frozen minutes ago is not live);
      b. for a Transfer push, it is the graph the pile was judged on (same pid -> same PlayerService): a rebuild between
         the walk and this push means the pile describes objects the game no longer shows.
    Exit 2 on either, before any write."""
    g = getattr(sess, '_pogo_graph', None) or {}
    ts, now = g.get('ts'), g.get('now')
    try:
        ts, now = int(ts), int(now)
    except (TypeError, ValueError):
        ts = now = None
    if not ts or not now:
        print('!! REFUSED: the service graph this push would write through has no readable inventory timestamp / phone '
              'clock (%s / %s) -- its liveness cannot be proven. Nothing was written.' % (ts, now))
        sys.exit(2)
    if now - ts > WALK_AGE_WARN_MS:          # age alone is a quiet game as often as a frozen one: say it, do not refuse
        print('  [WARN] the inventory of the graph this push writes through was last updated %.1f min ago (a quiet game, '
              'or a frozen graph -- the walk tripwires judged the walk)' % ((now - ts) / 60000.0))
    try:
        wfp = json.load(open(STAMP_PATH, encoding='utf-8')).get('walk_fp') or {}
    except Exception:
        wfp = {}
    if wfp.get('pid') == pid and wfp.get('graph_ts') and ts < int(wfp['graph_ts']) - 1000:
        print('!! REFUSED: the graph this push would write through was last updated %s ms, BEFORE the walk this pile was '
              'judged on saw %s ms -- an older (abandoned) graph. Re-cull; nothing was written.' % (ts, wfp['graph_ts']))
        sys.exit(2)
    if any(_is_pile_target(t) for t in targets):
        if wfp.get('pid') == pid and wfp.get('graph_player') and g.get('player') != wfp['graph_player']:
            print('!! REFUSED: the game rebuilt its service graph since the walk this pile was judged on (PlayerService '
                  '%s then, %s now, same process %s). Re-cull; nothing was written.' % (wfp['graph_player'], g.get('player'), pid))
            sys.exit(2)
        # R6 (Gym Battle review, 2026-09-29): the account the phone is on NOW must be the one whose walk judged the pile
        # (a login switch between the walk and this push -- a new process skips the same-pid graph test above).
        try:
            import account_guard as _ag
            _tr = (_ag.trainer_name(sess) or '').strip()
        except Exception as _te:
            _tr = ''
            print('  [WARN] the trainer name could not be read at push time (%s)' % _te)
        if _tr and wfp.get('trainer') and _tr.lower() != str(wfp['trainer']).strip().lower():
            print('!! REFUSED: the phone is logged in as %r but this pile was judged on %r\'s walk. Nothing was written.'
                  % (_tr, wfp['trainer']))
            sys.exit(2)


def main():
    argv = sys.argv[1:]
    dry = '--dry-run' in argv
    atomic = '--atomic' in argv            # collapse ALL tags' adds+removes into 1-3 SetPokemonTags RPCs
    force = '--force' in argv              # user override: skip the ready_gate (battery/fg) and write anyway
    targets = [a for a in argv if a not in ('--dry-run', '--atomic', '--force')] or list(PLAN)

    # ---- NO FILE => SKIP, never "push an empty set" (D5, 2026-09-07) --------------------------
    # PLAN is now the whole tag VOCABULARY, so it legitimately contains tags with zero members
    # today ('Paradox', 'Rare Other'), and build_tagsets only writes a file for a tag that HAS
    # members. Treating a missing file as want=<empty> would make prune strip every member of that
    # tag off the device -- a membership change nobody asked for, from a file that simply is not
    # there. Skip them loudly instead. (This also stops file_uids() raising FileNotFoundError
    # halfway through a push, after some tags had already been written.)
    _nofile = [n for n in targets if n in PLAN and not os.path.exists(os.path.join(TD, PLAN[n][0]))]
    if _nofile:
        targets = [n for n in targets if n not in set(_nofile)]
        print('  [registry] %d planned tag(s) have no tagset file -> SKIPPED (registered, but zero '
              'members this cycle; NOT pushed as empty): %s' % (len(_nofile), sorted(_nofile)))

    # ---- STALE FILE => WARN, still push ------------------------------------------------------
    # prune's contract is "make the device equal the file"; it cannot regenerate someone else's
    # file. But a file the last build_tagsets run did NOT rewrite is a frozen producer, and pushing
    # one quietly is exactly how a 2-day-old Evolve_Shiny.txt got staged as current (2026-09-02).
    # Same threshold and same warn-don't-block stance as set_db_tags_from_files._warn_stale.
    _STALE_S = 3600
    _mt = {}
    for n in targets:
        if n not in PLAN:          # a typo'd CLI name: the main loop reports it as 'skip unknown'
            continue
        try:
            _mt[n] = os.path.getmtime(os.path.join(TD, PLAN[n][0]))
        except OSError:
            pass
    _stale = sorted(n for n, m in _mt.items() if _mt and m < max(_mt.values()) - _STALE_S)
    if _stale:
        _newest = max(_mt.values())
        print('  [STALE] %d tagset file(s) were NOT rewritten by the last build_tagsets run and are '
              'being pushed as-is -- their producer did not run this cycle:' % len(_stale))
        for n in _stale:
            print('      %-20s %s  (%.1f h behind the freshest tagset)'
                  % (n, PLAN[n][0], (_newest - _mt[n]) / 3600.0))
        print('      Re-run keep_policy.py + build_tagsets.py if that is not deliberate.')

    # ---- PRE-FLIGHT STAMP GATE (2026-09-07) --------------------------------------------------
    # THE LAST THING BEFORE ANY DEVICE CONTACT. `targets` is final here (the --dry-run/--atomic/
    # --force flags are stripped, missing-file tags are dropped), and pg.get_session() is the next
    # statement, so a refusal costs zero Frida attaches. It fires whenever ANY target normalises to
    # the Transfer tag -- including the DEFAULT `or list(PLAN)` path above, which is the actual
    # danger: a bare `python prune_tags.py` silently included the pile.
    #
    # WHY AFTER THE _nofile SKIP AND NOT BEFORE IT: if Transfer.txt is absent, the D5 rule
    # above has already dropped 'Transfer' from targets, so this run cannot push the pile at
    # all -- the tag is skipped and its on-device membership is left exactly as it is.
    # Deleting the pile file therefore removes the PUSH, not the CHECK; it is not a bypass.
    # Gating before the skip would instead refuse every routine tag sync whenever the pile
    # file was legitimately absent, buying no safety and wedging the pipeline. Verified.
    #
    # `force` is deliberately NOT passed. --force bypasses ready_gate (battery/foreground write
    # RELIABILITY) and NOTHING else; require_preflight_stamp() has no parameter it could be
    # threaded into. A --dry-run does not bypass it either -- a dry-run still attaches, and the
    # point of refusing HERE is that an un-vetted pile never reaches the device at all.
    require_preflight_stamp(targets)

    sess, pid = pg.get_session()
    print(f'attached pid {pid}   {"[DRY-RUN]" if dry else "[LIVE]"}')
    _gate_svc = ''
    if force:
        print('[ready_gate] --force: BYPASSED by user -- writing regardless of battery/foreground (may no-op at very low battery)')
    elif not dry:                          # 2026-05-29: tag WRITES silently no-op unless foregrounded
        try:
            from ready_gate import ensure_ready_for_writes, NotReadyForWrites
            _gate_svc = getattr(ensure_ready_for_writes(sess, pid), 'svc_addr', '') or ''
        except NotReadyForWrites:
            raise                          # device genuinely not write-ready -> abort cleanly
        except Exception as _e:
            print(f'[ready_gate] skipped (gate error, proceeding): {_e}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        # the write gate just picked AND probed TaggingRpcService in THIS session (Stage 2, 2026-09-24): reuse it; with
        # --force / --dry-run / a gate error there is none and it is picked exactly as before
        svc = _gate_svc or pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        _refuse_unproven_graph(sess, pid, targets)              # H03: never write through a graph nobody proved live
        bag_map = pg.walk_bag_protos(sess, bag)                 # {uid_dec: proto_ptr}
        hex_to_proto = {format(int(d), 'x'): pp for d, pp in bag_map.items()}
        proto_to_hex = {pp: uh for uh, pp in hex_to_proto.items()}
        print(f'bag-walk: {len(hex_to_proto)} live protos')

        srv = enum_by_name(sess, svc)
        _stale = stale_members(sess, list(srv.values()), live_hex_fn(hex_to_proto), hex_to_proto)   # 2026-09-26
        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            _ix = tag_ops.tag_index(bt, svc)    # every existing tag from ONE RPC (2026-10-29: was 2 per tag, ~4 s)
            write_failed = False   # any add/remove that did not fully apply -> non-zero exit at the end
            change_map = {}        # atomic mode: uid_hex -> {'add': {tagproto..}, 'remove': {tagproto..}}
            def _chg(uh, kind, tp):
                change_map.setdefault(uh, {'add': set(), 'remove': set()})[kind].add(tp)
            for name in targets:
                if name not in PLAN:
                    print(f'  skip unknown {name!r}'); continue
                fn, color = PLAN[name]
                info = srv.get(name)
                if not info and not file_uids(fn):
                    # EMPTY-SET CONTRACT (2026-09-09): a registered tag with an EMPTY file and no device tag is
                    # "nobody qualifies" -- creating an empty tag on the phone would be one more useless chip.
                    print(f'  {name}: registered, zero members, not on the device -> nothing to do'); continue
                if not info:
                    # NEW-ACCOUNT PATH (2026-07-25): the tag does not exist server-side yet. Previously we
                    # `continue`d, so on a fresh account NOTHING was ever created and every sync reported
                    # "MISSING from server" forever. Treat it as an empty tag -- create_tag below makes it,
                    # and want-minus-empty adds every member. No effect on an established account.
                    print(f'  {name}: NOT on server -> creating it')
                    su, unmapped, su_conf = set(), 0, set()
                else:
                    su, unmapped, su_conf = server_uids_of(info, proto_to_hex, _stale)
                want = file_uids(fn)
                removal = su - want                 # stale-bound members count: an extra is removed either way
                addition = want - su_conf           # ...but only a CONFIRMED stale member counts as already tagged
                _sm = len(su - su_conf)
                print(f'  {name}: server={len(su)} (+{unmapped} unmapped' + (f', {_sm} stale-bound unconfirmed' if _sm else '')
                      + f') want={len(want)} -> remove {len(removal)}, add {len(addition)}')
                if dry:
                    if removal:  print(f'      would remove: {sorted(removal)[:12]}')
                    if addition: print(f'      would add:    {sorted(addition)[:12]}')
                    continue
                try:
                    tagproto = tag_ops.create_tag(bt, svc, name, color, index=_ix)   # FRESH (needed for untag persistence)
                except tag_ops.DuplicateTagName as exc:           # (2026-09-30) never write into an ambiguous tag
                    print(f'  !! {name}: SKIPPED this pass -- {exc}')
                    write_failed = True
                    continue
                if atomic:
                    # accumulate this tag's deltas; one apply_changes after the loop
                    for uh in addition: _chg(uh, 'add', tagproto)
                    for uh in removal:  _chg(uh, 'remove', tagproto)
                    continue
                # ---- legacy per-tag path (default): batched adds + per-mon untag ----
                if addition:
                    protos = [hex_to_proto[u] for u in addition if u in hex_to_proto]
                    miss = len(addition) - len(protos)
                    # apply_members RETURNS total_applied and only log.error()s its failures. That return
                    # used to be discarded and the REQUESTED count printed as if it were the applied
                    # count, so a partial write read as a clean one. (The atomic branch above was always
                    # honest, and the removal loop below counts real successes, so this bit only ever
                    # affected hand-runs without --atomic -- but "added 40/40" for 12 writes is exactly
                    # the kind of false confidence this whole file exists to remove.)
                    applied = tag_ops.apply_members(bt, svc, tagproto, protos)
                    if applied is None:          # tolerate an older tag_ops that returns nothing
                        applied = len(protos)
                    print(f'    added {applied}/{len(addition)}'
                          + (f' ({miss} not in bag)' if miss else ''))
                    if applied != len(protos):
                        write_failed = True
                        print(f'    !! {len(protos) - applied} add(s) did NOT apply for {name}')
                ok = 0
                for uh in sorted(removal):
                    lp = hex_to_proto.get(uh)
                    if not lp:
                        print(f'    ! {uh}: no live proto'); continue
                    try:
                        if tag_ops.untag_one(bt, svc, lp, tagproto).get('ok'):
                            ok += 1
                    except Exception as exc:
                        print(f'    ! {uh}: {exc}')
                if removal:
                    print(f'    removed {ok}/{len(removal)}')
                    if ok != len(removal):
                        write_failed = True
            # ---- RETIRED tags (granular_tags.RETIRED_TAGS, 2026-09-09): strip every member they still hold on
            # the device. Never created, never pushed from a file; the empty shell is deleted later by
            # retire_tags.py (DeleteTag is rate-limited, 1-3 per session -- tag_ops note 7).
            _retired_live = [n for n in _gt.RETIRED_TAGS if n in srv]
            for name in _retired_live:
                su, unmapped, _ = server_uids_of(srv[name], proto_to_hex, _stale)   # retired: strip stale-bound too
                if not su:
                    print(f'  {name}: RETIRED, already empty on the device (retire_tags.py deletes the shell)'); continue
                print(f'  {name}: RETIRED -> stripping {len(su)} member(s)' + (f' (+{unmapped} unmapped)' if unmapped else ''))
                if dry:
                    continue
                try:
                    tagproto = tag_ops.create_tag(bt, svc, name, 0, index=_ix)   # exists -> returns its live tagproto; colour ignored
                except tag_ops.DuplicateTagName as exc:
                    print(f'  !! {name}: SKIPPED this pass -- {exc}')
                    write_failed = True
                    continue
                if atomic:
                    for uh in su: _chg(uh, 'remove', tagproto)
                    continue
                ok = 0
                for uh in sorted(su):
                    lp = hex_to_proto.get(uh)
                    if not lp:
                        continue
                    try:
                        if tag_ops.untag_one(bt, svc, lp, tagproto).get('ok'):
                            ok += 1
                    except Exception as exc:
                        print(f'    ! {uh}: {exc}')
                print(f'    removed {ok}/{len(su)}')
                if ok != len(su):
                    write_failed = True
            # ---- atomic mode: ONE apply_changes for ALL tags' adds+removes ----
            if atomic and not dry and change_map:
                # 'uid' (H01): bulk_apply_changes writes a change only through a pointer that still IS this mon
                changes = [{'proto': hex_to_proto[u], 'uid': str(int(u, 16)), 'add': sorted(v['add']),
                            'remove': sorted(v['remove'])}
                           for u, v in change_map.items() if u in hex_to_proto]
                miss = len(change_map) - len(changes)
                rpcs = (len(changes) + 149) // 150
                n = tag_ops.apply_changes(bt, svc, changes)
                ntags = len([t for t in targets if t in PLAN])
                print(f'  [atomic] applied {n}/{len(changes)} mons across {ntags} tags in '
                      f'{rpcs} RPC(s)' + (f'  ({miss} uids not in bag)' if miss else ''))
                if n != len(changes):
                    write_failed = True
                # THE SERVER'S VERDICT (H02-2, 2026-09-29): a batch the server REFUSED fails the push (the tag on the
                # phone may not hold what the report is about to say); no answer inside the wait is said, not failed.
                _sv = tag_ops.LAST_SERVER
                if _sv.get('batches'):
                    print('  SERVER: %d/%d batch(es) Success, %d refused, %d no answer%s'
                          % (_sv['confirmed'], _sv['batches'], _sv['refused'], _sv['no_answer'],
                             '' if not (_sv['refused'] or _sv['no_answer']) else
                             ' -- %s' % '; '.join(str(d.get('detail')) for d in _sv['details']
                                                   if d.get('verdict') != 'confirmed')[:300]))
                    if _sv['refused']:
                        write_failed = True
        finally:
            bt.unload()

        # verify SET EQUALITY. CRITICAL: tagging a mon REALLOCATES its
        # PokemonProto, so the start-of-session proto_to_hex goes STALE for every
        # freshly-written mon -- they'd false-negative as "short" even though the
        # write persisted (this exact trap fooled an earlier run). Re-walk the bag
        # AFTER the writes for fresh pointers. The independent authority remains
        # `reconcile_tags.py --report` (fresh session, padded-DB-uid mapping).
        # Freshly-ADDED mons can false-short for a few seconds: tagging REALLOCATES
        # their proto, so the post-write walk maps the new proto but the service
        # binding still points at the old one until the cache settles (removals
        # never trip this -- no new binding). Re-walk+re-check up to 3x before
        # crying drift. Independent authority remains reconcile_tags --report.
        print('\n=== VERIFY (set equality, fresh post-write bag-walk) ===')
        allok, lines = False, []
        # MORE PATIENCE FOR ADDS ONLY (2026-09-26): a 24-mon push read Transfer 0/5, XXL -4 and Variant #2 -9 at +10 s and
        # was exactly right a minute later -- a false SYNC FAILED that also skipped the report. Shortfalls get up to ~55 s;
        # an EXTRA (a removal that did not land) still fails after the third check -- waiting never fixes that one.
        _WAITS = (0, 4, 6, 10, 15, 20)
        for vattempt in range(len(_WAITS)):
            if vattempt:
                time.sleep(_WAITS[vattempt])   # first check immediately; sleep only on a miss (2026-09-12)
            _extra_seen = False
            bag_map2 = pg.walk_bag_protos(sess, bag)
            proto_to_hex2 = {pp: format(int(d), 'x') for d, pp in bag_map2.items()}
            live2 = set(proto_to_hex2.values())   # a wanted uid the user RELEASED since the file was built is not "short" (2026-09-12)
            post = enum_by_name(sess, svc)
            _h2p2 = {v: k for k, v in proto_to_hex2.items()}
            _stale2 = stale_members(sess, list(post.values()), live_hex_fn(_h2p2), _h2p2)
            allok, lines = True, []
            for name in list(targets) + _retired_live:
                if name in PLAN:
                    fn, _ = PLAN[name]
                    want = file_uids(fn)
                elif name in _gt.RETIRED_TAGS:
                    want = set()                                   # retired: must be EMPTY on the device
                    if name not in post:
                        continue                                   # already deleted -- also fine
                else:
                    continue
                if name not in post:
                    if not want:
                        continue                                   # empty-set contract: nothing to be on the device
                    lines.append(f'  {name:<16} MISSING from server'); allok = False; continue
                su, _, su_conf = server_uids_of(post[name], proto_to_hex2, _stale2)
                extra, short = su - want, (want - su_conf) & live2   # extra: any binding; short: only a confirmed one counts   # released-while-syncing mons cannot be tagged; not drift
                _hatch = set()
                if short or extra:                                 # HATCHLINGS: isEgg_ stays 1 on a fresh hatch for a day or two and
                    try:                                           # the game silently ignores tag writes on it, adds AND removals
                        import sqlite3 as _sq3                     # (Squirtle 2026-09-13, Litten 2026-09-16). Deferred, not drift.
                        _c3 = _sq3.connect('file:pokemon.db?mode=ro', uri=True)
                        _hatch = {u for u in (short | extra) if (_c3.execute('SELECT is_egg FROM pokemon WHERE uid_hex=?', (u.zfill(16),)).fetchone() or [0])[0] == 1}
                        # NOT A BAG MON (2026-09-29 02:27): the Hundo binding held 12 pointers that resolved to EGG protos (pid 0,
                        # never in pokemon.db) -- freed hundo objects reused by eggs. An "extra" that is not a bag mon is a cache
                        # ghost, not a member: ignored on an advisory tag (listed), still a FAIL on the pile.
                        _nodb = {u for u in extra if _c3.execute('SELECT 1 FROM pokemon WHERE uid_hex=? AND in_bag=1', (u.zfill(16),)).fetchone() is None}
                        _c3.close()
                    except Exception as _he:
                        _nodb = set()
                        print('  (hatchling check skipped: %s)' % _he)
                    short = short - _hatch
                    extra = extra - (set() if _is_pile_target(name) else _hatch)   # an EXTRA on Transfer always fails (2026-09-26)
                    if _nodb:
                        lines.append('      %s: %d extra member(s) that are not bag mons (egg / freed object reused): %s'
                                     % ('FAILS on the pile' if _is_pile_target(name) else 'ignored', len(_nodb), ', '.join(sorted(_nodb)[:8])))
                        if not _is_pile_target(name):
                            extra = extra - _nodb
                # LOCKED MONS (user 2026-09-16: "there's things such as buddy and gym and showcase pokemon"): the game
                # ignores tag writes on the buddy, a gym defender or a showcase entry, so a lone member can stay
                # short/extra for days (Litten 57%, Variant #2). Such a miss on an ADVISORY tag, or a SHORT on
                # Transfer (it cannot be released while locked anyway), is DEFERRED and retried next pass -- it never
                # fails the sync (which also skipped the DB mirror and produced phantom drift). An EXTRA on Transfer
                # still fails: a keeper would be one release away once it unlocks.
                # GHOST BINDINGS (2026-09-26): an EXTRA only through a stale binding whose mon's live tag list LACKS the tag --
                # the game's record says untagged, a removal cannot clear a cache ghost. Shown and ignored on an advisory tag;
                # on Transfer it still FAILS (the in-game tag view may list it, and a keeper must never look releasable).
                _ghost = extra & (su - su_conf)
                if _ghost:
                    lines.append('      stale binding, live tag list lacks it (%s): %s' % ('FAILS on the pile' if _is_pile_target(name) else 'ignored', ', '.join(sorted(_ghost))))
                    if not _is_pile_target(name):
                        extra = extra - _ghost
                _defer = (extra | short) if not _is_pile_target(name) else set(short)
                if len(_defer) > 3:
                    _defer = set()   # more than 3 is cache lag after a big push, not locked mons: let the retry judge it (2026-09-17)
                if _defer:
                    lines.append(f'      deferred (locked: buddy / gym / showcase, or fresh): {", ".join(sorted(_defer))}')
                extra, short = extra - _defer, short - _defer
                flag = 'OK' if not extra and not short else f'extra={len(extra)} short={len(short)}'
                if extra or short:
                    allok = False
                if extra:
                    _extra_seen = True
                lines.append(f'  {name:<16} server={len(su)} want={len(want)}  [{flag}]')
                if _hatch:
                    lines.append('      deferred: %d hatchling(s) still flagged isEgg (tag write ignored by the game until it clears): %s' % (len(_hatch), ', '.join(sorted(_hatch))))
                if extra or short:                     # name the members: a 1-mon miss must be diagnosable from the log (2026-09-13)
                    import sqlite3 as _sq
                    try:
                        _c = _sq.connect('file:pokemon.db?mode=ro', uri=True)
                        def _d(us):
                            o = []
                            for _u in sorted(us)[:5]:
                                _r = _c.execute('SELECT species_name, iv_total, creation_date FROM pokemon WHERE uid_hex=?', (_u.zfill(16),)).fetchone()
                                o.append('%s %d%% caught %sZ' % (_r[0], (_r[1] or 0) / 45 * 100, (_r[2] or '?')[11:16]) if _r else _u)
                            return ', '.join(o) + (' ...' if len(us) > 5 else '')
                        lines.append('      ' + ' | '.join(x for x in ((('extra: ' + _d(extra)) if extra else ''), (('short: ' + _d(short)) if short else '')) if x))
                        _c.close()
                    except Exception as _e:
                        lines.append('      (members: %s)' % _e)
            if allok:
                break
            if vattempt >= 2 and _extra_seen:
                break
            if vattempt < len(_WAITS) - 1:
                print(f'  (attempt {vattempt+1}: not yet equal -- likely add cache-lag, re-walking)')
        # THE GRAPH THIS PUSH AND ITS VERIFY WENT THROUGH MUST STILL BE THE LIVE ONE (H01, 2026-09-29). The verify above
        # re-read the very bag / TaggingRpcService it wrote through; after an in-process rebuild that is a frozen copy
        # agreeing with itself -- the 2026-09-29 "ALL TARGETS EXACTLY SYNCED" while the game's Transfer tag held 0.
        if allok and not dry:
            try:
                pg.revalidate_graph(sess)
            except pg.GraphRefusal as _gc:
                allok = False
                lines.append('  VERIFY VOID -- %s' % _gc)
        print('\n'.join(lines))
        print('\nALL TARGETS EXACTLY SYNCED' if allok else
              '\nstill not equal (freshly-added mons may just need a moment; '
              'confirm with reconcile_tags.py --report)')
    finally:
        sess.detach()
    print('done.')
    # EXIT CODE (2026-09-02). `grep -n 'sys.exit'` used to find NOTHING in this file: allok was computed
    # across the 3-attempt set-equality verify, the failure was PRINTED, and then main() fell off the
    # end returning None -- so the dashboard's /api/sync reported "done" over a push that had provably
    # not landed. The verify already retries 3x for add cache-lag, so reaching here with allok=False is
    # a real write failure, not a transient. A non-zero rc also stops the steps that follow, which is
    # what keeps set_db_tags_from_files from mirroring an unverified push into auth_tag_names.
    if dry:
        return 0                      # a dry-run compares nothing and pushes nothing
    return 0 if (allok and not write_failed) else 1


if __name__ == '__main__':
    sys.exit(main())
