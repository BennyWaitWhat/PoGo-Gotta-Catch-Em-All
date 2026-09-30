"""Hardened tag-operations module for PoGo Frida tag writes.

Rationale for warm-up and backoff:

1. **AddTag flakiness**: The AddTag RPC (add_tag_on_instance) intermittently
   fails to create a tag. It ALWAYS fails in the first seconds after an app
   restart because the server-side RPC channel has not finished initializing.
   create_tag() works around this by issuing find_tag_id_by_name first, and
   if the tag is missing it calls AddTag then polls find_tag_id_by_name with
   exponential backoff (3s, 5s, 5s, 8s) until the tag appears or attempts
   are exhausted.

2. **bulk_untag_one warm-up NPE**: The very first call to bulk_untag_one in
   a fresh Frida session throws a NullReferenceException (the IL2CPP
   runtime class initializer has not run yet for the generic List<>
   instantiations used by SetPokemonTags). untag_one() fires a sacrificial
   warm-up call, catches any error, sleeps 0.5s, then performs the real
   untag with up to 3 retries.

3. **Proto-cache lag**: After bulk_tag_many writes tags, the in-process
   TaggingRpcService cache may not update instantly. apply_members()
   batches calls (default 100) with per-batch retry (up to 3) and
   validates built==requested before moving on.

4. **ensure_ready()**: Before any write operation, the caller should
   confirm that the TaggingRpcService is responsive. This function issues
   a harmless get_NumberOfTags probe via find_tag_id_by_name on a known
   tag and retries with backoff until a response comes back.

5. **"ok" / "built==N" is NOT proof of persistence.** Every RPC in this module
   reports what the CLIENT accepted, not what the SERVER stored. AddTag returns
   ok=True for a colour the game rejects and the tag never appears (see
   MAX_TAG_COLOR); AddTag also fails outright in the first seconds after an app
   restart while still looking healthy; and the in-process TaggingRpcService
   cache lags a write by seconds. So:
     - create_tag NEVER trusts its own AddTag return -- it re-reads the tag
       back with find_tag_id_by_name and only then claims success. That
       read-back is the only "proof" this file is entitled to produce.
     - apply_members / apply_changes CANNOT read back (there is no cheap
       per-mon membership refetch), so their return value is deliberately
       named and logged as ACCEPTED, never "applied" or "succeeded". Do not
       treat it as persistence. The proof of a membership write is a genuine
       server refetch: reconcile_tags.py --report, or verify_tags_live.py.

6. **Every write needs a FRESH bag-walk proto.** A PokemonProto address is only
   valid for the bag walk that produced it, in the session that produced it.
   Reusing a cached/bound proto from an earlier walk (or a previous Frida
   session) hands IL2CPP a stale pointer and SetPokemonTags throws
   NullReferenceException. Callers must pass protos from
   pg.find_protos_for_uids() performed in the SAME session as the write. This
   module cannot verify that for you; it is a caller contract, restated on
   each write primitive.

7. **Tag DELETION is rate limited too** (measured: only 1-3 DeleteTag calls
   succeed per session before DeleteTag starts throwing -- MEASURED AGAIN
   2026-09-09: 15 EMPTY tags deleted in one game session, 3 s settle + a
   collateral census between each, zero refusals; the limit seems to bite
   on tags that still hold members, so strip first, then delete -- BUT 2026-09-23 it bit on EMPTY shells too:
   3 deleted, the 4th refused, and a fresh session 10 min later refused the 1st; so plan on ~3 per window),
   on top of the
   creation throttle in _MIN_CREATE_GAP. This module has NO delete primitive
   and deliberately keeps none -- deleting a tag is how 'Mega' was collaterally
   destroyed. Deletion lives in system/scripts/safe_nuke_tags.py, which
   re-enumerates and verifies between every deletion. Removing a mon from a
   tag is untag_one() (membership removal) -- a different RPC, not subject to
   the DeleteTag limit.

Usage as CLI:
    python tag_ops.py apply <TagName> <color_int 0-8>
    Reads members from pokemon.db (auth_tag_names LIKE '%;Name;%'),
    bag-walks for proto addresses, creates the tag if absent, applies
    membership, and mirrors results to the DB.

    THE RELEASE PILE IS GATED. `apply` refuses for a pile tag (Transfer /
    6 Transfer) unless ALL THREE hold -- see cmd_apply():
      a) --yes-push-the-release-pile was typed explicitly, AND
      b) the DB member set this command would push is IDENTICAL to the
         tagset file that the gate is about to check, AND
      c) preflight_transfer.py runs right here, right now, and exits 0.
    Any other tag is unchanged: one command, no ceremony (the recovery path
    in system/procedures/recover.md still works exactly as written).

Usage as library:
    import tag_ops
    ensure_ready(sess, svc, bt)
    tp = create_tag(bt, svc, "GL", 3)
    n  = apply_members(bt, svc, tp, proto_list)   # n = ACCEPTED, not persisted
    untag_one(bt, svc, proto, tagproto)

    The library is UNGATED by design. prune_tags.py is the ONLY sanctioned pile
    pusher and it enforces the pre-flight stamp itself (2026-09-07). Every OTHER
    importer of these primitives has to refuse pile tags on its own; as of
    2026-09-07 the score is:
      - apply_tagsets.py       GATED -- is_pile_tag() on both the named tag and the
                               PLAN lookup, before pg.get_session().
      - prune_server_tag.py    GATED -- is_pile_tag() on argv before it attaches.
      - push_armored_tags.py   NOT GATED (lives at the project root, not here).
      - pile_pardon.py         NOT GATED (project root). It names 'Transfer'
                               directly and rewrites Transfer.txt; it only REMOVES
                               members, which is the safe direction, but nothing
                               stops it.
    The gate added here guards the hand-typed CLI, which is the one path with
    nothing in front of it.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import json                      # the server-answer dump (H02-2); without it the dump failed silently
import time
import sqlite3
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tag_ops")

HERE = os.path.dirname(os.path.abspath(__file__))
# Walk up two levels: system/scripts -> system -> project root
PROJECT_ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
DB_PATH = os.path.join(PROJECT_ROOT, "pokemon.db")
BULK_TAG_JS = os.path.join(PROJECT_ROOT, "bulk_tag.js")
TAGSET_DIR = os.path.join(PROJECT_ROOT, "system", "analysis", "tagsets")
PREFLIGHT_PY = os.path.join(HERE, "preflight_transfer.py")

# ---------------------------------------------------------------------------
# Colour range. PokemonTagColor is 0-8.
# ---------------------------------------------------------------------------
# 9 is the trap: AddTag accepts it, returns ok=True, and the tag NEVER
# materialises. That reads exactly like an account tag cap and caused three
# wrong diagnoses on 2026-09-02. Anything out of range must raise BEFORE a
# single RPC is fired, on every creation path.
MAX_TAG_COLOR = 8


def check_color(color, name="<tag>"):
    """Raise ValueError unless *color* is a valid PokemonTagColor (0..8).

    The single choke point for the colour rule. create_tag() calls it (that is
    the only tag-creation path in this module) and the CLI calls it at
    argument-parse time, so a bad colour fails before Frida is ever touched.
    """
    try:
        c = int(color)
    except (TypeError, ValueError):
        raise ValueError("tag '%s': colour %r is not an integer -- PokemonTagColor is 0-%d."
                         % (name, color, MAX_TAG_COLOR))
    if not (0 <= c <= MAX_TAG_COLOR):
        raise ValueError("tag '%s': colour %r is out of range -- PokemonTagColor is 0-%d. "
                         "9 silently no-ops: AddTag returns ok and the tag never appears."
                         % (name, color, MAX_TAG_COLOR))
    return c


# ---------------------------------------------------------------------------
# Release-pile identification
# ---------------------------------------------------------------------------
# The Transfer pile is the ONE irreversible output: the human reads it off the
# phone and mass-releases those mons by hand. TAGGING IS NOT RELEASING, but
# tagging is the last automated step before a human destroys a pokemon, so it
# is the last place a gate can still help.
#
# Matched on a NORMALISED name (casefold, underscores read as spaces) so that
# 'Transfer', 'transfer', '6 Transfer' and '6_Transfer' all trip the gate. No
# other tag in the registry normalises into this set.
PILE_TAG_NAMES = frozenset({"transfer", "6 transfer"})


def _norm_tag(name):
    """Canonical tag spelling. Also accepts the tagset FILENAME form ('Transfer.txt',
    'system/analysis/tagsets/6_Transfer.txt'): 2026-09-07 'Transfer.txt' slipped past
    is_pile_tag() because only prune_tags.py knew to strip the path and suffix.

    ORDER MATTERS: strip whitespace and surrounding quotes BEFORE testing for the
    '.txt' suffix, the same order prune_tags._norm_tag uses. Testing first meant
    'Transfer.txt\\n' and 'Transfer.txt ' -- exactly what a caller that reads a
    manifest or a `ls` listing line-by-line produces -- did not end with '.txt',
    kept the suffix, and normalised to 'transfer.txt', which is not in
    PILE_TAG_NAMES. Measured 2026-09-07: eight spellings of the pile that
    prune_tags refused, this function called safe (trailing space, trailing
    newline, leading+trailing spaces, "double" and 'single' quotes, a quoted or
    newline-terminated tagset path). Both apply_tagsets.py and prune_server_tag.py
    feed raw argv straight into is_pile_tag(), so every one of those was a live
    hole. Over-matching is the correct bias here: a false pile-positive costs one
    re-run, a false pile-negative costs the collection.
    """
    n = str(name).strip().strip("'\"").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if n.casefold().endswith(".txt"):
        n = n[:-4]
    return " ".join(n.replace("_", " ").split()).casefold()


def is_pile_tag(name):
    """True if *name* means the irreversible release pile, in any spelling."""
    return _norm_tag(name) in PILE_TAG_NAMES


def _norm_uid(u):
    """Canonical uid: unpadded lowercase hex (same rule as prune_tags.norm)."""
    return format(int(u, 16), "x")


def tagset_path(name):
    """The tagset FILE backing a tag name.

    Filename rule: swap SPACES only. '#' and '+' must survive the round-trip
    ('Location Card #1-3' -> 'Location_Card_#1-3.txt', 'Traded by E+F' ->
    'Traded_by_E+F.txt'); sanitising them breaks the mapping.
    """
    return os.path.join(TAGSET_DIR, str(name).replace(" ", "_") + ".txt")


def _read_tagset(path):
    with open(path, encoding="utf-8") as f:
        return {_norm_uid(u) for u in f.read().split() if u.strip()}

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

_BACKOFF_SCHEDULE = [3.0, 5.0, 5.0, 8.0, 8.0, 13.0]

# CREATION THROTTLE (2026-09-02). The per-tag backoff above is fine, but nothing spaced CONSECUTIVE
# create_tag calls: prune_tags creates its whole PLAN in a loop, so each new tag's first AddTag fired
# immediately after the previous tag's. Creating 12 tags that way, every one after the first two failed
# -- AddTag returned ok=True and the tag never materialised, which reads exactly like an account tag cap
# and was misdiagnosed as one. Spaced out, creation succeeds every time. Server-side rate limit, not a cap.
_MIN_CREATE_GAP = 8.0
# Seeded at import, NOT 0.0: prune_tags resolves ~11 existing tags with rapid find_tag_id_by_name calls
# and then fires the FIRST create immediately. Lookups count toward the same server rate limit, so that
# first create was the one that failed every time while later ones would have been throttled. Seeding
# means even the first create waits out the gap.
_last_create_ts = [time.time()]


def _throttle_create():
    gap = time.time() - _last_create_ts[0]
    if gap < _MIN_CREATE_GAP:
        wait = _MIN_CREATE_GAP - gap
        log.info("create_tag: throttling %.1fs (tag creation is rate-limited server-side)", wait)
        time.sleep(wait)
    _last_create_ts[0] = time.time()


def _sleep_backoff(attempt, schedule=None):
    """Sleep for the duration at `attempt` index in the schedule."""
    s = schedule or _BACKOFF_SCHEDULE
    delay = s[min(attempt, len(s) - 1)]
    log.debug("backoff sleep %.1fs (attempt %d)", delay, attempt)
    time.sleep(delay)


def ensure_ready(sess, svc, bt, max_wait=60):
    """Warm-up: confirm the TaggingRpcService is responding.

    Calls find_tag_id_by_name for a tag that almost certainly exists
    (any tag -- the first one the service knows about). If the service
    is still booting after an app restart, this will fail; we retry with
    backoff until *max_wait* seconds have elapsed.

    Args:
        sess: frida.Session (unused directly, kept for API symmetry).
        svc:  TaggingRpcService instance address string.
        bt:   Loaded bulk_tag.js Frida script.
        max_wait: Total seconds to keep retrying before raising.

    Raises:
        RuntimeError: If the service never responds.
    """
    deadline = time.monotonic() + max_wait
    attempt = 0
    # Use a harmless probe: try to find any tag by using a name that
    # may or may not exist.  Even a "not found" response proves the
    # RPC channel is alive.  An exception or transport error means the
    # service isn't ready.
    probe_tag = "__warmup_probe__"
    while True:
        try:
            r = bt.exports_sync.find_tag_id_by_name(svc, probe_tag)
            # Any dict response (ok:true OR ok:false/err:"not found") means
            # the RPC path works.
            if isinstance(r, dict):
                log.info("ensure_ready: service responsive (attempt %d)", attempt)
                # B11 (design review 2026-09-24): lookups count toward the SAME server rate limit as AddTag, and the
                # import-time seed is long gone after a 30 s walk -- so restart the create gap here: the first create
                # after this probe (and prune's burst of lookups) waits the full _MIN_CREATE_GAP. Costs 0 s unless a
                # tag is actually created.
                _last_create_ts[0] = time.time()
                return
        except Exception as exc:
            log.warning("ensure_ready: attempt %d failed: %s", attempt, exc)
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"TaggingRpcService did not respond within {max_wait}s"
            )
        _sleep_backoff(attempt)
        attempt += 1


class DuplicateTagName(RuntimeError):
    """2+ tags on the phone carry one name. find_tag_id_by_name returns the FIRST, so a write could land on either copy."""


# (2026-09-30) poll this long for a tag an AddTag just created before EVER sending a second AddTag for it
VERIFY_WINDOW_S = 30.0


def _dup_guard(bt, svc, name):
    """Raise DuplicateTagName when 2+ tags carry `name` (13:51 on 2026-09-30: two 'Evolve for UL', one empty -- the
    members went to one, prune's verify read the other, and the post-push reconcile blocked retire / Remote Trade /
    order). An older bulk_tag.js without countTagsByName: logged, never guessed."""
    try:
        r = bt.exports_sync.count_tags_by_name(svc, name) or {}
    except Exception as exc:
        log.warning("create_tag: cannot count the tags named %r (%s) -- duplicate guard skipped", name, exc)
        return
    if r.get("ok") and int(r.get("count") or 0) > 1:
        raise DuplicateTagName(
            "%d tags on the phone are named %r (%s): a write would land on either copy. Remove the empty copy with "
            "`python system/scripts/safe_nuke_tags.py --empty-duplicates \"%s\"`"
            % (r["count"], name, ", ".join(r.get("addrs") or []), name))


def create_tag(bt, svc, name, color, attempts=5):
    """Create a tag or return its proto address if it already exists.

    1. find_tag_id_by_name -- if found, return immediately.
    2. add_tag_on_instance -- fire the AddTag RPC.
    3. Poll find_tag_id_by_name with exponential backoff to confirm
       the server materialised the tag -- for up to VERIFY_WINDOW_S before
       another AddTag is ever sent (a slow cache is not a failed AddTag).
    4. Refuse (DuplicateTagName) when 2+ tags carry the name.

    Args:
        bt:       Loaded bulk_tag.js Frida script.
        svc:      TaggingRpcService instance address string.
        name:     Tag name string.
        color:    PokemonTagColor integer (0-8). 9 is REJECTED by the game -- AddTag reports
                  success and the tag never materialises (measured 2026-09-02).
        attempts: Max create+verify cycles.

    Returns:
        tagProtoAddr string -- READ BACK from the server, not merely accepted.

    Raises:
        ValueError:   If *color* is not a valid PokemonTagColor (0-8).
        RuntimeError: If tag creation fails after all attempts.
    """
    color = check_color(color, name)

    # Check if it already exists.
    r = bt.exports_sync.find_tag_id_by_name(svc, name)
    if r.get("ok"):
        log.info("create_tag: '%s' already exists @ %s", name, r["tagProtoAddr"])
        _dup_guard(bt, svc, name)
        return r["tagProtoAddr"]

    last_err = None
    for attempt in range(attempts):
        log.info(
            "create_tag: AddTag('%s', color=%d) attempt %d/%d",
            name, color, attempt + 1, attempts,
        )
        try:
            _throttle_create()
            bt.exports_sync.add_tag_on_instance(svc, name, color)
        except Exception as exc:
            log.warning("create_tag: AddTag RPC threw: %s", exc)
            last_err = exc
            _sleep_backoff(attempt)
            continue

        # Give the server time to register the new tag, then verify. A MISS IS NOT A FAILURE (2026-09-30 13:51: 'Evolve
        # for UL' was not in the client cache 3 s after its AddTag; the retry sent a SECOND AddTag and the phone got two
        # tags of that name). An AddTag that returned without throwing is polled for VERIFY_WINDOW_S first.
        t_end, k = time.time() + VERIFY_WINDOW_S, attempt
        while True:
            _sleep_backoff(k)
            r = bt.exports_sync.find_tag_id_by_name(svc, name)
            if r.get("ok") or time.time() >= t_end:
                break
            k += 1
        if r.get("ok"):
            log.info(
                "create_tag: '%s' confirmed @ %s (attempt %d)",
                name, r["tagProtoAddr"], attempt + 1,
            )
            _dup_guard(bt, svc, name)
            return r["tagProtoAddr"]
        last_err = r.get("err", "find returned not-ok")
        log.warning(
            "create_tag: verify failed on attempt %d: %s", attempt + 1, last_err
        )

    raise RuntimeError(
        f"create_tag('{name}'): failed after {attempts} attempts. Last error: {last_err}"
    )


def apply_members(bt, svc, tagproto, proto_list, batch=100):
    """Apply tag membership in batches with per-batch retry.

    Calls bulk_tag_many for each batch of *batch* proto addresses.
    Each batch is retried up to 3 times; a batch is ACCEPTED when built ==
    len(batch_slice). Logs any failed batches.

    NOT PROOF OF PERSISTENCE. built==N means the client built and submitted N
    PokemonTagChanges; it does not mean the server stored them, and the
    in-process cache lags the write. Prove a membership write with a real
    server refetch (reconcile_tags.py --report / verify_tags_live.py).

    CALLER CONTRACT: *proto_list* must come from a bag walk performed in the
    SAME Frida session as this call. A stale/cached proto throws
    NullReferenceException inside SetPokemonTags.

    Args:
        bt:         Loaded bulk_tag.js Frida script.
        svc:        TaggingRpcService instance address string.
        tagproto:   Tag proto address string (from create_tag).
        proto_list: List of FRESH PokemonProto address strings.
        batch:      Batch size (default 100).

    Returns:
        int -- number of protos the server ACCEPTED (not verified-persisted).
    """
    if not proto_list:
        return 0

    total_applied = 0
    total_batches = (len(proto_list) + batch - 1) // batch
    failed_batches = []

    for bi in range(0, len(proto_list), batch):
        chunk = proto_list[bi : bi + batch]
        batch_num = bi // batch + 1
        ok = False
        last_result = None
        for retry in range(3):
            try:
                r = bt.exports_sync.bulk_tag_many(svc, tagproto, chunk)
                last_result = r
                if r.get("ok") and r.get("built", 0) == len(chunk):
                    total_applied += len(chunk)
                    ok = True
                    break
                log.warning(
                    "apply_members: batch %d/%d retry %d: built=%s requested=%d err=%s %s",
                    batch_num, total_batches, retry,
                    r.get("built"), len(chunk), r.get("err"), r.get("excClass") or '',
                )
            except Exception as exc:
                last_result = str(exc)
                log.warning(
                    "apply_members: batch %d/%d retry %d threw: %s",
                    batch_num, total_batches, retry, exc,
                )
            time.sleep(0.6)

        if not ok:
            failed_batches.append((batch_num, last_result))
            log.error(
                "apply_members: batch %d/%d FAILED after 3 retries: %s",
                batch_num, total_batches, last_result,
            )
        elif bi + batch < len(proto_list):
            # Brief pause between successful batches to avoid flooding.
            time.sleep(0.4)

    if failed_batches:
        log.warning(
            "apply_members: %d/%d batches failed: %s",
            len(failed_batches), total_batches,
            [b[0] for b in failed_batches],
        )
    else:
        log.info(
            "apply_members: all %d/%d batches ACCEPTED (%d protos) -- acceptance is not "
            "persistence; confirm with reconcile_tags.py --report",
            total_batches, total_batches, total_applied,
        )
    return total_applied


# THE SERVER'S ANSWER TO THE LAST apply_changes (H02-2, 2026-09-29). Until now no step of the cull observed the server:
# "ACCEPTED" meant the managed call did not throw. bulk_apply_changes now hands back a GC handle on SetPokemonTags'
# promise; each batch waits (<= SERVER_WAIT_S) for it to settle and reads the reply's status (1 = Success, like
# order_tags' EditResult). confirmed / refused / no_answer are per batch; refused = the server said no (or threw).
LAST_SERVER = {'batches': 0, 'confirmed': 0, 'refused': 0, 'no_answer': 0, 'details': []}
SERVER_WAIT_S = 20
_SERVER_DUMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'analysis',
                            'last_tag_server_answer.json')


def _outproto_status(node):
    """('confirmed'|'refused', detail) from an *OutProto dump's status / result field (1 = Success), else (None, None)."""
    if not isinstance(node, dict) or not (node.get('cls') or '').endswith('OutProto'):
        return None, None
    for k, v in (node.get('f') or {}).items():
        if not any(w in k.lower() for w in ('status', 'result')):
            continue
        if isinstance(v, dict) and 'v' in v:
            v = v['v']
        if isinstance(v, int):
            return ('confirmed' if v == 1 else 'refused'), '%s.%s=%s' % (node['cls'], k, v)
        if isinstance(v, list) and v:
            return ('confirmed' if all(x == 1 for x in v) else 'refused'), '%s.%s=%s' % (node['cls'], k, v[:10])
    return None, None


def _message(node):
    """The first string field named like a message inside an exception dump."""
    if not isinstance(node, dict):
        return None
    for k, v in (node.get('f') or {}).items():
        if isinstance(v, dict) and v.get('cls') == 'String' and 'message' in k.lower():
            return v.get('s')
    return None


def _server_status(node):
    """('confirmed'|'refused'|None, detail) from a promise dump. Niantic's Promise<T> (Gym Battle, proven on the gym
    side): errorCalled=1 -> refused (errorValue's _message); completeCalled=1 -> settled: the reply *OutProto's status
    when it has one, else 'settled (value <cls>)' = confirmed; both 0 -> pending (None, 'pending'). A wrapper without
    the flags is followed through its Promise field (.base / ._assetPromise); the old scan is the last resort."""
    if not isinstance(node, dict):
        return None, None
    f = node.get('f') or {}
    if 'completeCalled' in f or 'errorCalled' in f:
        if f.get('errorCalled') == 1:
            ev = f.get('errorValue')
            return 'refused', '%s: %s' % ((ev or {}).get('cls') if isinstance(ev, dict) else ev, _message(ev))
        if f.get('completeCalled') == 1:
            cv = f.get('completedValue')
            st, d = _outproto_status(cv)
            if st:
                return st, d
            return 'confirmed', 'settled (value %s)' % ((cv or {}).get('cls') if isinstance(cv, dict) else cv)
        return None, 'pending'
    for v in f.values():
        if isinstance(v, dict) and 'Promise' in (v.get('cls') or ''):
            st, d = _server_status(v)
            if st or d:
                return st, d
    cls = node.get('cls') or ''
    if 'Exception' in cls:
        return 'refused', '%s: %s' % (cls, _message(node))
    st, d = _outproto_status(node)
    if st:
        return st, d
    for v in f.values():
        st, d = _server_status(v)
        if st:
            return st, d
    return None, None


def _server_answer(bt, h, timeout=None):
    """Wait for one SetPokemonTags promise; returns (verdict, detail, last dump). Always frees the handle."""
    t0, last = time.time(), None
    try:
        while time.time() - t0 < (timeout or SERVER_WAIT_S):
            try:
                last = bt.exports_sync.promise_state(h)
            except Exception as e:            # an older bulk_tag.js without the export, or a read fault: no answer
                return None, 'promise read failed: %s' % e, last
            st, d = _server_status(last)
            if st:
                return st, d, last
            time.sleep(0.25)
        return None, 'no answer in %d s' % (timeout or SERVER_WAIT_S), last
    finally:
        try:
            bt.exports_sync.promise_free(h)
        except Exception:
            pass


def apply_changes(bt, svc, changes, batch=150):
    """Atomically apply per-mon tag changes -- 1 SetPokemonTags RPC per `batch`.

    `changes`: list of dicts {'proto': addr_str, 'add': [tagproto_str,...],
    'remove': [tagproto_str,...]} (add/remove each optional). Every batch becomes
    ONE bulk_apply_changes -> ONE List<PokemonTagChanges> -> ONE SetPokemonTags,
    so a whole multi-tag sync (all adds AND all removals across all tags) costs a
    handful of RPCs instead of one-per-removal + one-per-100-add. Per-batch retry
    (3x); success requires built == len(batch). Returns total mons applied.

    Uses the SAME field configs as the proven single-purpose drivers (see the
    bulk_apply_changes JS doc): populated-add+null-remove == bulkTagMany,
    empty-add+populated-remove == bulkUntagOne.

    NOT PROOF OF PERSISTENCE -- built==N is client-side acceptance only; see
    apply_members. CALLER CONTRACT: every 'proto' must come from a bag walk in
    THIS Frida session (a stale proto throws NullReferenceException).
    """
    changes = [c for c in changes if c.get('add') or c.get('remove')]
    LAST_SERVER.clear()
    LAST_SERVER.update(batches=0, confirmed=0, refused=0, no_answer=0, details=[])
    if not changes:
        return 0
    total = 0
    nb = (len(changes) + batch - 1) // batch
    failed = []
    mismatched = []
    for bi in range(0, len(changes), batch):
        chunk = changes[bi:bi + batch]
        bn = bi // batch + 1
        ok = False
        last = None
        for retry in range(3):
            try:
                r = bt.exports_sync.bulk_apply_changes(svc, chunk)
                last = r
                _mm = r.get("mismatched") or []
                if _mm:
                    # H01: these pointers are no longer those mons -- NOT written, and NOT retried with the same
                    # pointers (a retry re-sends every change of the batch through protos the first send reallocated)
                    log.error("apply_changes: batch %d/%d: %d change(s) NOT written -- the proto no longer holds that "
                              "mon (released / evolved / re-tagged since the walk): %s", bn, nb, len(_mm), _mm[:10])
                    mismatched.extend(_mm)
                if r.get("ok") and r.get("built", 0) == len(chunk) - len(_mm):
                    total += r["built"]
                    ok = True
                    LAST_SERVER['batches'] += 1
                    if r.get("promise"):          # H02-2: what did the SERVER say about this batch?
                        _v, _d, _dump = _server_answer(bt, r["promise"])
                        if _v == 'confirmed':
                            LAST_SERVER['confirmed'] += 1
                        elif _v == 'refused':
                            LAST_SERVER['refused'] += 1
                            log.error("apply_changes: batch %d/%d: the SERVER REFUSED it (%s)", bn, nb, _d)
                        else:
                            LAST_SERVER['no_answer'] += 1
                            log.warning("apply_changes: batch %d/%d: no server answer (%s)", bn, nb, _d)
                        LAST_SERVER['details'].append({'batch': bn, 'verdict': _v, 'detail': _d})
                        if _v != 'confirmed' or not os.path.exists(_SERVER_DUMP):
                            try:                  # the raw reply, for the first run and for anything not a Success
                                with open(_SERVER_DUMP, 'w', encoding='utf-8') as _fh:
                                    json.dump({'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'batch': bn, 'verdict': _v,
                                               'detail': _d, 'dump': _dump}, _fh, indent=1, default=str)
                            except Exception as _de:
                                log.warning("apply_changes: server-answer dump not written (%s)", _de)
                    else:
                        LAST_SERVER['no_answer'] += 1
                        LAST_SERVER['details'].append({'batch': bn, 'verdict': None, 'detail': 'no promise handle'})
                    break
                if _mm:
                    break
                log.warning("apply_changes: batch %d/%d retry %d: built=%s requested=%d err=%s %s",
                            bn, nb, retry, r.get("built"), len(chunk), r.get("err"), r.get("excClass") or '')
            except Exception as exc:
                last = str(exc)
                log.warning("apply_changes: batch %d/%d retry %d threw: %s", bn, nb, retry, exc)
            time.sleep(0.6)
        if not ok:
            failed.append((bn, last))
            log.error("apply_changes: batch %d/%d FAILED after 3 retries: %s", bn, nb, last)
        elif bi + batch < len(changes):
            time.sleep(0.4)
    if failed:
        log.warning("apply_changes: %d/%d batches failed: %s", len(failed), nb, [b[0] for b in failed])
    elif mismatched:
        log.warning("apply_changes: %d mons ACCEPTED, %d NOT written (stale proto pointer) -- the caller must fail "
                    "this sync and re-walk", total, len(mismatched))
    else:
        log.info("apply_changes: all %d batch(es) ACCEPTED (%d mons) -- acceptance is not "
                 "persistence; confirm with reconcile_tags.py --report", nb, total)
    if LAST_SERVER['batches']:
        _lvl = log.error if LAST_SERVER['refused'] else (log.warning if LAST_SERVER['no_answer'] else log.info)
        _lvl("apply_changes: SERVER answered %d/%d batch(es): %d Success, %d refused, %d no answer",
             LAST_SERVER['confirmed'] + LAST_SERVER['refused'], LAST_SERVER['batches'], LAST_SERVER['confirmed'],
             LAST_SERVER['refused'], LAST_SERVER['no_answer'])
    return total


def untag_one(bt, svc, proto, tagproto):
    """Remove a tag from one pokemon with warm-up + retry.

    Fires a sacrificial warm-up call first (catches any exception,
    sleeps 0.5s), then issues the real untag with up to 3 retries.
    The warm-up avoids the NullReferenceException that bulk_untag_one
    throws on the first call in a fresh Frida session.

    This removes MEMBERSHIP; it does not delete the tag. It is therefore NOT
    subject to the DeleteTag rate limit (1-3 deletions per session before
    DeleteTag throws) -- that limit belongs to safe_nuke_tags.py. A removal can
    never push a mon INTO the release pile, only out of it.

    CALLER CONTRACT: *proto* must come from a bag walk in THIS Frida session.

    Args:
        bt:       Loaded bulk_tag.js Frida script.
        svc:      TaggingRpcService instance address string.
        proto:    PokemonProto address string.
        tagproto: Tag proto address string.

    Returns:
        dict -- the bulk_untag_one result on success.

    Raises:
        RuntimeError: If all retries fail.
    """
    # Warm-up call -- same args, result discarded.
    try:
        bt.exports_sync.bulk_untag_one(svc, proto, tagproto)
    except Exception:
        pass
    time.sleep(0.5)

    last_err = None
    for attempt in range(3):
        try:
            r = bt.exports_sync.bulk_untag_one(svc, proto, tagproto)
            if r.get("ok"):
                return r
            last_err = r.get("err", "untag returned not-ok")
            log.warning("untag_one: attempt %d: %s", attempt + 1, last_err)
        except Exception as exc:
            last_err = str(exc)
            log.warning("untag_one: attempt %d threw: %s", attempt + 1, exc)
        time.sleep(0.5)

    raise RuntimeError(
        f"untag_one: failed after 3 retries. Last error: {last_err}"
    )


# ---------------------------------------------------------------------------
# CLI: python tag_ops.py apply <TagName> <color>
# ---------------------------------------------------------------------------

def _load_bulk_tag_script(sess):
    """Load bulk_tag.js into the given Frida session and return the script."""
    with open(BULK_TAG_JS, encoding="utf-8") as f:
        js = f.read()
    bt = sess.create_script(js)
    bt.on("message", lambda m, d: None)
    bt.load()
    bt.exports_sync.init_status()
    return bt


def _mirror_db(tag_name, uid_hexes):
    """Mirror tag membership into pokemon.db auth_tag_names."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    updated = 0
    for uh in uid_hexes:
        row = cur.execute(
            "SELECT auth_tag_names FROM pokemon WHERE uid_hex = ?", (uh,)
        ).fetchone()
        if not row:
            continue
        existing = [t for t in (row[0] or "").split(";") if t]
        if tag_name not in existing:
            existing.append(tag_name)
            cur.execute(
                "UPDATE pokemon SET auth_tag_names = ? WHERE uid_hex = ?",
                (";".join(existing), uh),
            )
            updated += 1
    conn.commit()
    conn.close()
    log.info("mirror_db: updated %d rows for tag '%s'", updated, tag_name)


def _near_miss_tags(tag_name):
    """Bag tag names that differ from *tag_name* only in case, spacing or underscores.

    Membership selection is exact containment (see cmd_apply), so a case or spacing
    slip now selects ZERO rows where the old LIKE would have selected the right
    mons and then pushed them to a differently-spelled server tag. Zero rows is the
    safe outcome, but silent zero rows is a mystery; this turns it into a message.
    Read-only, best-effort: a failure here must never affect the caller.
    """
    want = _norm_tag(tag_name)
    found = set()
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            for (v,) in conn.execute(
                    "SELECT DISTINCT auth_tag_names FROM pokemon WHERE in_bag = 1"):
                for t in (v or "").split(";"):
                    t = t.strip()
                    if t and t != tag_name and _norm_tag(t) == want:
                        found.add(t)
        finally:
            conn.close()
    except Exception as exc:                                  # pragma: no cover
        log.debug("near-miss probe failed (ignored): %s", exc)
    return sorted(found)


# ---------------------------------------------------------------------------
# THE RELEASE-PILE GATE
# ---------------------------------------------------------------------------
# WHY THIS EXISTS: `python tag_ops.py apply Transfer 1` used to push the
# irreversible release pile straight from pokemon.db.auth_tag_names to the
# phone with NOTHING in front of it -- no keep_policy, no build_tagsets, no
# preflight_transfer. A forensic audit found 24 mons culled that a correct
# engine would have kept and 18 gone for good, including a GL #2-of-4096
# Mudbray. This is the one path where a single mistyped command reaches the
# irreversible output.
#
# WHY A GATE AND NOT JUST A SCARY FLAG: a bare --i-know-what-im-doing flag only
# defends against a typo. The failure mode that actually destroyed pokemon was
# not "I did not mean to type this" -- it was "the pile I pushed had never been
# checked for keepers". A flag cannot see that; only running the keeper gate
# can. Worse, a blanket flag on every tag trains the hand to type it reflexively
# so it is already muscle memory on the day it matters. So the flag is kept
# (it makes the dangerous invocation impossible to reach by accident) but it is
# NOT sufficient on its own, and it is demanded ONLY for pile tags -- every
# keep tag stays a single frictionless command, because a safety measure people
# route around protects nobody. See system/procedures/recover.md, which is
# unaffected.
#
# THE THREE CONDITIONS (all required, checked before Frida is touched):
#   a) --yes-push-the-release-pile typed explicitly.
#   b) The set this command would push (from the DB) is IDENTICAL to the set
#      the gate is about to vet (Transfer.txt). This is the
#      "the artifact that was audited was not the artifact that got pushed"
#      defect the dashboard already fixed for /api/sync; the CLI reads a
#      DIFFERENT source (auth_tag_names) than preflight reads (Transfer.txt),
#      so without this check a PASS would bless a pile nobody looked at.
#   c) preflight_transfer.py runs HERE, NOW, and exits 0. Not a cached verdict,
#      not a receipt file -- a fresh run against the current DB. There is no
#      staleness window a re-run cannot close.
GATE_FLAG = "--yes-push-the-release-pile"


def preflight_gate(tag_name, uid_hexes, allow_no_live_deployment=False, timeout_s=900):
    """Vet a hand-typed release-pile push. Returns None to allow, or a refusal string.

    NEVER returns None on a check it could not perform -- an unreadable tagset,
    a crashed preflight and a timed-out preflight are all refusals. A gate that
    passes what it did not inspect is not a gate.
    """
    import subprocess

    pushed = {_norm_uid(u) for u in uid_hexes}

    # (b) the set being pushed must BE the set the gate inspects.
    vetted_path = os.path.join(TAGSET_DIR, "Transfer.txt")   # the file preflight_transfer reads
    if not os.path.exists(vetted_path):
        return ("%s does not exist, so preflight_transfer has nothing to vet. Run keep_policy.py "
                "+ build_tagsets.py first." % vetted_path)
    try:
        vetted = _read_tagset(vetted_path)
    except Exception as exc:
        return "could not read %s (%s) -- refusing rather than pushing an unvetted pile." % (
            vetted_path, exc)

    if pushed != vetted:
        only_db = sorted(pushed - vetted)
        only_file = sorted(vetted - pushed)
        return (
            "the pile this command would push is NOT the pile preflight_transfer vets.\n"
            "    DB auth_tag_names '%s': %d uid(s)\n"
            "    %s: %d uid(s)\n"
            "    only in the DB (would be pushed UNVETTED): %s\n"
            "    only in the file (vetted but would NOT be pushed): %s\n"
            "    Re-run the sanctioned path (keep_policy -> build_tagsets -> preflight -> "
            "prune_tags --atomic, i.e. the dashboard's /api/sync) so the two agree. Pushing a "
            "pile the gate never inspected is exactly the defect that destroyed 18 pokemon."
            % (tag_name, len(pushed), os.path.basename(vetted_path), len(vetted),
               only_db[:8] or "none", only_file[:8] or "none"))

    if not vetted:
        return "the pile is EMPTY -- nothing to push."

    # (c) a FRESH preflight run. Frida is single-client and preflight reads
    # deployment live, so this must finish and detach before we attach below.
    cmd = [sys.executable, PREFLIGHT_PY]
    if allow_no_live_deployment:
        cmd.append("--allow-no-live-deployment")
    log.info("release-pile gate: running %s on %d uid(s) -- this attaches Frida; nothing else "
             "may be attached right now", os.path.basename(PREFLIGHT_PY), len(vetted))
    try:
        r = subprocess.run(cmd, cwd=PROJECT_ROOT, timeout=timeout_s,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        return ("preflight_transfer.py did not finish within %ds. Refusing -- an unfinished gate "
                "is a failed gate." % timeout_s)
    except Exception as exc:
        return "could not run preflight_transfer.py (%s). Refusing." % exc

    out = (r.stdout or b"").decode("utf-8", "replace")
    print(out)
    if r.returncode != 0:
        return ("preflight_transfer.py exited %d -- it found a REAL KEEPER in the pile, a uid it "
                "could not read, or it could not perform the live deployment check. DO NOT push. "
                "Investigate keep_policy / the tagset above before anything reaches the phone."
                % r.returncode)

    log.info("release-pile gate: PASSED (fresh preflight, exit 0, %d uid(s) matched)", len(vetted))
    return None


def cmd_apply(args):
    """CLI handler for 'apply' sub-command."""
    tag_name = args.tag_name
    # Fail on a bad colour BEFORE the bag walk, the Frida attach and the gate.
    color = check_color(args.color, tag_name)

    # 1. THE GATE, PART A -- decided on the name that was TYPED, before a single
    #    row is read. Until 2026-09-07 the membership query ran first and the
    #    refusal was reached only afterwards, which meant the gate's answer could
    #    disagree with the query's: see the query note below, where four wildcard
    #    spellings each selected the pile's rows while is_pile_tag() called that
    #    same spelling not-a-pile. Judging the typed name first removes the gap
    #    between "what did you name" and "what did that name select" entirely --
    #    there is no membership set in existence yet to disagree with.
    pile = is_pile_tag(tag_name)
    if pile:
        log.warning("'%s' is THE IRREVERSIBLE RELEASE PILE.", tag_name)
        if not getattr(args, "yes_push_the_release_pile", False):
            log.error(
                "REFUSING.\n"
                "    `tag_ops.py apply %s` pushes the release pile to the phone with no engine, "
                "no build_tagsets and no keeper gate in front of it.\n"
                "    The sanctioned way to push this pile is the dashboard (/api/sync), which "
                "runs keep_policy -> build_tagsets -> preflight_transfer -> prune_tags --atomic.\n"
                "    If you really mean to push it from here, re-run with %s and this command "
                "will run preflight_transfer itself and refuse on rc != 0.",
                tag_name, GATE_FLAG)
            sys.exit(2)

    # 2. Query DB for members -- EXACT ';name;' containment via instr(), NOT LIKE.
    #    A tag name is raw operator text and LIKE reads '%' and '_' inside it as
    #    WILDCARDS. Measured against this DB on 2026-09-07: 'Transfe_', '_ransfer',
    #    'Trans%fer', 'T%r' and 'Transfer%' each resolved the release pile's 25
    #    rows, and a bare '%' resolved all 5728 rows in the bag -- while
    #    is_pile_tag() answered False for every one of those spellings, so the
    #    step-1 gate never fired and nothing else stood between the query and
    #    pg.get_session(). instr() has no metacharacters, so a tag name now selects
    #    exactly the rows carrying that literal name and nothing else. This is the
    #    same test prune_server_tag.py uses, so "which rows does this tag name
    #    select" has ONE answer across the codebase.
    #
    #    Note this is also case-SENSITIVE where LIKE was not: 'safety hold' used to
    #    select the 'Safety Hold' members and then push them to a differently-named
    #    server tag. Selecting nothing is the safe direction, and _near_miss_tags()
    #    below turns the silence into a legible message.
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT uid_hex FROM pokemon "
        "WHERE in_bag = 1 "
        "  AND instr(';' || COALESCE(auth_tag_names, '') || ';', ';' || ? || ';') > 0",
        (tag_name,),
    ).fetchall()
    conn.close()
    uid_hexes = [r[0] for r in rows]

    # 3. THE GATE, PART B -- needs the resolved member set, so it can only run now.
    #    Deliberately BEFORE the empty-set early return: for a pile tag an empty DB
    #    set is not "nothing to do", it is a pokemon.db/Transfer.txt divergence, and
    #    preflight_gate reports and refuses it (an empty pushed set can never equal
    #    a non-empty vetted set, so condition (b) fails). preflight_gate compares
    #    the two sets BEFORE it spawns preflight_transfer, so a refusal here costs
    #    no Frida attach.
    if pile:
        log.warning("release pile: %d uid(s) selected from the DB.", len(uid_hexes))
        refusal = preflight_gate(tag_name, uid_hexes,
                                 allow_no_live_deployment=getattr(
                                     args, "allow_no_live_deployment", False))
        if refusal:
            log.error("REFUSING to push the release pile: %s", refusal)
            sys.exit(2)

    if not uid_hexes:
        log.warning("No DB members found for tag '%s'", tag_name)
        near = _near_miss_tags(tag_name)
        if near:
            log.warning("  tag names are matched EXACTLY, case and spacing included -- "
                        "did you mean %s?", " or ".join(repr(n) for n in near))
        return

    uid_decs = sorted({str(int(u, 16)) for u in uid_hexes})
    log.info("Tag '%s': %d members in DB", tag_name, len(uid_hexes))

    # Late import -- only needed once we are actually going to the phone, and
    # deliberately AFTER the gate so a refusal can never be pre-empted by an
    # import error in the Frida stack.
    sys.path.insert(0, PROJECT_ROOT)
    import pogo_il2cpp as pg  # noqa: E402

    # 2. Frida session.
    sess, pid = pg.get_session()
    log.info("Attached to PID %d", pid)
    try:
        bag = pg.pick_singleton(
            sess, "Niantic.Holoholo.Internal", "PokemonBagImpl"
        )
        svc = pg.pick_singleton(
            sess, "Niantic.Holoholo.Tagging", "TaggingRpcService"
        )
        proto_map = pg.find_protos_for_uids(sess, bag, uid_decs)
        log.info("Bag-walk: %d/%d protos resolved", len(proto_map), len(uid_decs))

        bt = _load_bulk_tag_script(sess)
        try:
            # 3. Warm-up.
            ensure_ready(sess, svc, bt)

            # 4. Create or find tag.
            tagproto = create_tag(bt, svc, tag_name, color)

            # 5. Build proto list (preserve order).
            protos = [
                proto_map[str(int(u, 16))]
                for u in uid_hexes
                if str(int(u, 16)) in proto_map
            ]
            log.info("Applying %d protos to tag '%s'", len(protos), tag_name)

            # 6. Apply.
            applied = apply_members(bt, svc, tagproto, protos)
            log.info("Applied %d/%d members", applied, len(protos))

            # 7. Mirror DB.
            applied_uids = [
                u for u in uid_hexes if str(int(u, 16)) in proto_map
            ]
            _mirror_db(tag_name, applied_uids)
        finally:
            bt.unload()
    finally:
        sess.detach()


def _color_arg(v):
    """argparse type for the colour: reject out-of-range at parse time."""
    try:
        return check_color(v)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def main():
    parser = argparse.ArgumentParser(
        description="Hardened PoGo tag operations (warm-up + backoff)."
    )
    sub = parser.add_subparsers(dest="command")
    apply_p = sub.add_parser(
        "apply",
        help="Create tag (if needed) and apply DB members to the server.",
    )
    apply_p.add_argument("tag_name", help="Server tag name")
    # 0-8, NOT 0-9. The old help said 0-9; colour 9 is accepted by AddTag,
    # returns ok=True and the tag silently never materialises.
    apply_p.add_argument("color", type=_color_arg,
                         help="PokemonTagColor int (0-%d)" % MAX_TAG_COLOR)
    apply_p.add_argument(GATE_FLAG, action="store_true",
                         help="Required for a release-pile tag (Transfer). Even with it, this "
                              "command runs preflight_transfer.py and refuses on rc != 0.")
    apply_p.add_argument("--allow-no-live-deployment", action="store_true",
                         help="Passed through to preflight_transfer when Frida cannot read gym "
                              "deployment live. Accepts a DB-only verdict -- weaker gate.")

    args = parser.parse_args()
    if args.command == "apply":
        cmd_apply(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
