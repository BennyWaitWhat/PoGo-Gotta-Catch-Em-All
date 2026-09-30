"""test_atomic_changes.py -- validate tag_ops.apply_changes / bulk_apply_changes
on-device with a SAFE, REVERSIBLE round-trip on an EXISTING label tag:

  1) atomically REMOVE the tag from 2 mons in ONE RPC  -> expect count - 2
  2) atomically ADD it back to the same 2 in ONE RPC   -> expect count restored

Proves multi-mon batching + both directions + persistence through the atomic
path, without ever touching the release pile. Leaves the server EXACTLY as
found. Re-walks the bag after each write (tagging reallocates protos).

WHICH TAG, AND WHY IT IS NEVER A NEW ONE (2026-09-07)
----------------------------------------------------
This test originally ran on '6 Transfer' -- the irreversible RELEASE PILE --
which a test must never touch. The first fix pointed TAG at a private
'_atomic_test' label, and that was worse: tag_ops.create_tag() is
find-OR-CREATE, and it ran BEFORE the membership read. On a tag that does not
exist yet, every run therefore (a) minted a permanent new device tag, (b) read
back 0 members, (c) printed 'need >=2 members with live protos' and returned.
One junk tag per run and ZERO test coverage. The junk is not cheaply
removable either: DeleteTag is rate-limited to 1-3 calls per session, tag_ops
deliberately keeps no delete primitive at all (deleting a tag is how the
'Mega' tag was collaterally destroyed), and deletion is a hand-supervised
operation in safe_nuke_tags.py.

So this test now runs on a tag that ALREADY EXISTS with hundreds of members,
and it can no longer bring a tag into existence under any code path:
  * TAG is resolved with a FIND-ONLY lookup -- bulk_tag.js findTagIdByName,
    which walks the cached tag->pokemon bindings and reads names. It issues no
    RPC and writes nothing. If TAG is absent this run ABORTS; it never creates.
  * the release pile is refused with a real `if` + sys.exit, NOT an assert:
    `python -O` strips asserts, and this is the one check in the file that must
    never be strippable.

Why disturbing a LABEL tag's membership for ~3 seconds cannot move the pile:
  * keep_policy.py, preflight_transfer.py and the tagset builder read the tag
    columns (tag_ids / fresh_tag_ids / fresh_tag_count) ZERO times, and
    keep_policy lists auth_tag_names in _OUTPUT_COLS, which excludes it from
    the provenance digest. Tag membership is pipeline OUTPUT; it is not an
    input to any keep decision, so it cannot add or remove a single uid from
    the Transfer pile.
  * 'Legacy Moves' is one of the managed tags in prune_tags.PLAN, so if the
    add-back ever failed the next sanctioned sync would restore it anyway. The
    failure paths below print that command rather than leaving it implicit.
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
os.chdir(ROOT)
import pogo_il2cpp as pg
import tag_ops
from reconcile_tags import ENUM_MEMBERS_JS

# An EXISTING, purely advisory label tag with hundreds of members: 340 in the DB
# mirror (auth_tag_names) and 340 on the device in the 2026-09-07 03:48 live tag
# enumeration. Must already exist on the phone -- this script never creates a
# tag, it ABORTS instead. 2026-09-07: was '6 Transfer' (the release
# pile -- a test must never touch it), then '_atomic_test' (which did not exist,
# so create_tag minted it and the test measured nothing).
TAG = 'Legacy Moves'

# NOT an assert: `python -O` strips asserts, and a stripped pile check is a
# check that is not there. This is the file's hard floor -- if TAG ever names
# the release pile in any spelling, the run stops before it can attach.
if tag_ops.is_pile_tag(TAG):
    sys.exit('test tag must not be the release pile (got %r)' % (TAG,))

# The self-heal command, printed on any path that could leave the tag short.
RESTORE_HINT = 'python system/scripts/prune_tags.py --atomic "%s"' % TAG


def walk(sess, bag):
    bm = pg.walk_bag_protos(sess, bag)
    h2p = {format(int(d), 'x'): pp for d, pp in bm.items()}
    p2h = {pp: uh for uh, pp in h2p.items()}
    return h2p, p2h


def enum_members(sess, svc, p2h):
    en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
    try:
        tags = {t['name']: t for t in en.exports_sync.enumerate_all_tag_members(svc)}
    finally:
        en.unload()
    info = tags.get(TAG)
    if not info:
        return set()
    return {p2h[pp] for pp in info['members'] if pp in p2h}


def find_tag_only(bt, svc, name):
    """Resolve *name* to its tagProtoAddr WITHOUT the create half of create_tag().

    tag_ops.create_tag() is find-OR-CREATE. A test has no business creating a
    tag, so this deliberately calls only the find half and returns None when the
    tag is absent. bulk_tag.js findTagIdByName reads the cached bindings; it
    fires no RPC and mutates nothing.
    """
    r = bt.exports_sync.find_tag_id_by_name(svc, name) or {}
    # `or None` so an ok=True with a blank/absent address still reads as "absent"
    # rather than being carried forward as a proto the writes would choke on.
    return (r.get('tagProtoAddr') or None) if r.get('ok') else None


def main():
    sess, pid = pg.get_session()
    print('attached pid', pid)
    try:
        from ready_gate import ensure_ready_for_writes
        ensure_ready_for_writes(sess, pid)
    except Exception as e:
        print(f'[ready_gate] {e}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        h2p, p2h = walk(sess, bag)
        print('bag-walk:', len(h2p), 'live protos')

        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)

            # ---- resolve TAG, FIND-ONLY. Never create. ----
            tp = find_tag_only(bt, svc, TAG)
            if tp is None:
                print(f'ABORT: tag {TAG!r} does not exist on this device.')
                print('       This test never creates a tag (DeleteTag is rate-limited to 1-3 per '
                      'session, so an accidental tag is effectively permanent).')
                print('       Point TAG at an existing label tag with >=2 members, or push this one '
                      f'first: {RESTORE_HINT}')
                return
            print('tagproto', tp)

            before = enum_members(sess, svc, p2h)
            print(f'BEFORE: {TAG} = {len(before)}')
            picks = [u for u in sorted(before) if u in h2p][:2]
            if len(picks) < 2:
                print(f'FAIL: need >=2 members with live protos (tag has {len(before)} member(s) '
                      f'resolvable in this bag walk). Nothing was written.')
                return
            print('picks:', picks)

            # ---- 1) atomic REMOVE both in ONE RPC ----
            t0 = time.time()
            n = tag_ops.apply_changes(bt, svc, [{'proto': h2p[u], 'remove': [tp]} for u in picks])
            print(f'remove: accepted {n} in {time.time()-t0:.2f}s (1 RPC)')
            time.sleep(3)
            h2p, p2h = walk(sess, bag)
            after_rem = enum_members(sess, svc, p2h)
            rem_ok = len(after_rem) == len(before) - 2 and all(u not in after_rem for u in picks)
            print(f'AFTER REMOVE: {len(after_rem)} (expect {len(before)-2})  -> {"OK" if rem_ok else "FAIL"}')

            # ---- 2) atomic ADD both back in ONE RPC (fresh protos) ----
            # A pick whose proto did not survive the re-walk CANNOT be restored in
            # this session. That used to be a silent `if u in h2p` filter, which
            # left the mon quietly untagged; say so out loud instead.
            lost = [u for u in picks if u not in h2p]
            if lost:
                print(f'WARN: {lost} lost their proto in the re-walk and cannot be added back here. '
                      f'{TAG} is left SHORT. Restore with: {RESTORE_HINT}')
            restore = [u for u in picks if u in h2p]
            t0 = time.time()
            n = tag_ops.apply_changes(bt, svc, [{'proto': h2p[u], 'add': [tp]} for u in restore])
            print(f'add: accepted {n} in {time.time()-t0:.2f}s (1 RPC)')
            time.sleep(3)
            h2p, p2h = walk(sess, bag)
            final = enum_members(sess, svc, p2h)
            add_ok = final == before
            print(f'AFTER ADD-BACK: {len(final)} (expect {len(before)})  -> {"OK" if add_ok else "FAIL"}')
            if not add_ok:
                print(f'       server NOT restored -- missing {sorted(before - final)}, '
                      f'extra {sorted(final - before)}. Restore with: {RESTORE_HINT}')

            print('\n=== ' + ('PASS: atomic add+remove both persist, server restored exactly'
                              if (rem_ok and add_ok) else 'FAIL: see above') + ' ===')
        finally:
            bt.unload()
    finally:
        sess.detach()


if __name__ == '__main__':
    main()
