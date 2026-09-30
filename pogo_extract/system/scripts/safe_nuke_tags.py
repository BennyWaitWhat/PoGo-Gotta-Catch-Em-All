"""safe_nuke_tags.py -- Hardened tag-deletion with collateral detection.

ROOT CAUSE this replaces:
  _nuke_tags.py deleted multiple tags in a multi-pass loop, re-reading tagId
  from tagProto pointers between deletions. After each DeleteTag RPC the
  in-game TaggingRpcService proto cache reorganises its internal list: indices
  shift, and previously-valid tagProto pointers can now reference a DIFFERENT
  tag's proto. Reading the tagId from a stale/reused pointer therefore sends
  DeleteTag for the WRONG tag -- this is how 'Mega' was collaterally deleted
  and 'Costume' was emptied.

HOW THIS SCRIPT PREVENTS COLLATERAL:
  1. Before any deletion, snapshot ALL tags {name, tagId, memberCount}.
  2. Delete ONE tag at a time: re-enumerate fresh, find the single target by
     exact name match, read its tagId from the fresh enumeration, call
     DeleteTag, sleep for cache settle, then RE-ENUMERATE and VERIFY:
       (a) the target tag is gone,
       (b) every non-target tag still exists with the SAME memberCount.
     If any non-target tag disappeared or lost members, ABORT immediately
     and print exactly what changed.
  3. Only after full verification of one deletion proceed to the next.
  4. DB mirror (pokemon.db auth_tag_names) is updated only for tags that
     were confirmed deleted.

REFUSES THE RELEASE PILE: DeleteTag on 'Transfer' / '6 Transfer' is not a route INTO
  the pile, but it destroys the very list the user hand-releases from, and a deleted tag
  cannot be undeleted. main() refuses any pile spelling (tag_ops.is_pile_tag) before
  argparse and before any attach -- including under --dry-run, because there is no safe
  rehearsal of deleting the pile. Delete it in-game if that is really the intent.

Usage:
  python safe_nuke_tags.py TagA TagB ...
  python safe_nuke_tags.py --dry-run TagA TagB ...
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import argparse
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# repo root is two levels up from system/scripts/ -- ensure pogo_il2cpp imports
# whether invoked as `python system/scripts/safe_nuke_tags.py` or from anywhere
sys.path.insert(0, HERE)  # tag_ops.py sits beside this file
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..')))

import pogo_il2cpp as pg
# Pile gate, see main(). Aliased on purpose: a plain `is_pile_tag` would go unbound the
# moment some function body did a local `import tag_ops` (that is what bit prune_server_tag.py).
from tag_ops import is_pile_tag as _is_pile

# DB lives two levels up from system/scripts/
DB = os.path.join(HERE, '..', '..', 'pokemon.db')

# Sleep seconds between DeleteTag and the verification re-enumerate.
SETTLE_DELAY = 3.0

# ---------------------------------------------------------------------------
# Frida JS -- enumerate tags with memberCount, delete a single tag
# ---------------------------------------------------------------------------
JS = r"""
function enumTagsFull(s) {
    _ensureInit();
    var cl = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var it = Memory.alloc(Process.pointerSize);
    it.writePointer(ptr(0));
    var m, gn = null, gb = null;
    while ((m = IL2.cGM(cl, it)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        if (nm === 'get_NumberOfTags') gn = m;
        if (nm === 'GetCachedTagToPokemonBindingForIndex') gb = m;
    }
    var svc = ptr(s);
    var tot = rI(gn, svc, ptr(0), null).add(0x10).readS32();
    var out = [];
    for (var i = 0; i < tot; i++) {
        var ib = Memory.alloc(4);
        ib.writeS32(i);
        var ar = Memory.alloc(Process.pointerSize);
        ar.writePointer(ib);
        var bp = rI(gb, svc, ar, null);
        if (bp.isNull()) continue;
        var tp = bp.add(0x10).readPointer();
        // tag name (UTF-16 string at tagProto+0x40)
        var nm = '';
        try {
            var ns = tp.add(0x40).readPointer();
            var ln = ns.add(0x10).readS32();
            if (ln > 0 && ln < 100) {
                var ch = [];
                for (var ci = 0; ci < ln; ci++)
                    ch.push(String.fromCharCode(ns.add(0x14 + ci * 2).readU16()));
                nm = ch.join('');
            }
        } catch (e) {}
        // tagId (uint64 at tagProto+0x38)
        var tid = '0';
        try { tid = tp.add(0x38).readU64().toString(); } catch (e) {}
        // memberCount: binding+0x18 -> pokemonList, list+0x18 -> count
        var mc = 0;
        try {
            var pokemonList = bp.add(0x18).readPointer();
            if (!pokemonList.isNull()) {
                mc = pokemonList.add(0x18).readS32();
            }
        } catch (e) {}
        out.push({name: nm, tagId: tid, memberCount: mc});
    }
    return out;
}

function delTag(s, tidStr) {
    _ensureInit();
    var cl = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var it = Memory.alloc(Process.pointerSize);
    it.writePointer(ptr(0));
    var m, dm = null;
    while ((m = IL2.cGM(cl, it)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'DeleteTag') { dm = m; break; }
    }
    if (!dm) return {ok: false, err: 'no DeleteTag method found'};
    var idBuf = Memory.alloc(8);
    idBuf.writeU64(uint64(tidStr));
    var args = Memory.alloc(Process.pointerSize);
    args.writePointer(idBuf);
    var exc = Memory.alloc(Process.pointerSize);
    exc.writePointer(ptr(0));
    rI(dm, ptr(s), args, exc);
    if (!exc.readPointer().isNull())
        return {ok: false, err: 'DeleteTag threw an exception'};
    return {ok: true};
}

rpc.exports.enumTagsFull = enumTagsFull;
rpc.exports.delTag = delTag;
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def enumerate_tags(script, svc):
    """Return list of {name, tagId, memberCount} from a fresh enumeration."""
    return script.exports_sync.enum_tags_full(svc)


def tag_census(tags):
    """Build {name: {tagId, memberCount}} dict for quick lookup."""
    return {t['name']: {'tagId': t['tagId'], 'memberCount': t['memberCount']}
            for t in tags}


def check_collateral(before, after_tags, deleted_name):
    """Compare after-state to before-census, ignoring the just-deleted tag.

    Returns (ok: bool, problems: list[str]).
    """
    after = tag_census(after_tags)
    problems = []
    for name, info in before.items():
        if name == deleted_name:
            if name in after:
                problems.append(
                    f'  Target "{name}" still exists after deletion (tagId {info["tagId"]})')
            continue
        if name not in after:
            problems.append(
                f'  COLLATERAL: tag "{name}" (tagId {info["tagId"]}, '
                f'{info["memberCount"]} members) DISAPPEARED')
        elif after[name]['memberCount'] != info['memberCount']:
            problems.append(
                f'  COLLATERAL: tag "{name}" memberCount changed '
                f'{info["memberCount"]} -> {after[name]["memberCount"]}')
    return (len(problems) == 0, problems)


def clear_db_mirror(db_path, tag_name):
    """Remove tag_name from auth_tag_names in pokemon.db."""
    if not os.path.isfile(db_path):
        print(f'  [db] pokemon.db not found at {db_path}, skipping DB update')
        return 0
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT uid_hex, auth_tag_names FROM pokemon "
        "WHERE (';' || COALESCE(auth_tag_names,'') || ';') LIKE ?",
        (f'%;{tag_name};%',)
    ).fetchall()
    updated = 0
    for uid, atn in rows:
        tags = [t for t in (atn or '').split(';') if t and t != tag_name]
        cur.execute(
            "UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
            (';'.join(tags) if tags else None, uid))
        updated += 1
    conn.commit()
    conn.close()
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # 2026-09-07 PILE GATE. This is the only tag-DELETING script, and DeleteTag is
    # irreversible: deleting 'Transfer' would destroy the hand-release list itself (and
    # clear_db_mirror() would then strip the tag out of pokemon.db.auth_tag_names on the way
    # out). Checked before argparse and before any attach, so a refusal never costs a Frida
    # session, and applied to --dry-run too -- there is no safe rehearsal of this. argv is a
    # superset of the parsed tag list, so nothing can slip past by arriving as a flag value.
    for _a in sys.argv[1:]:
        if _is_pile(_a):
            sys.exit("REFUSING: '%s' is the irreversible release pile tag -- deleting it "
                     "destroys the hand-release list. Delete it in-game if you really mean "
                     "to." % _a)
    parser = argparse.ArgumentParser(
        description='Safely delete named tags one-at-a-time with collateral detection.')
    parser.add_argument('tags', nargs='+', help='Tag names to delete')
    parser.add_argument('--dry-run', action='store_true',
                        help='Enumerate and print plan without deleting anything')
    args = parser.parse_args()

    targets = args.tags
    dry_run = args.dry_run

    print(f'Target tags to delete: {targets}')
    if dry_run:
        print('[DRY RUN] Will enumerate and plan only -- no deletions.')
    print()

    # --- Attach ---
    sess, pid = pg.get_session()
    print(f'Attached to PID {pid}')
    svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
    print(f'TaggingRpcService singleton: {svc}')
    script = pg.get_script_with_helpers(sess, JS)

    try:
        # --- Step 1: Before census ---
        before_tags = enumerate_tags(script, svc)
        before = tag_census(before_tags)
        print(f'\nBefore census: {len(before_tags)} tags total')
        print('-' * 60)
        for t in sorted(before_tags, key=lambda x: x['name']):
            marker = ' << TARGET' if t['name'] in targets else ''
            print(f"  {t['name']:30s}  id={t['tagId']:>22s}  members={t['memberCount']}{marker}")
        print('-' * 60)

        found = [n for n in targets if n in before]
        missing = [n for n in targets if n not in before]
        if missing:
            print(f'\nWARNING: target tags not found (will skip): {missing}')
        if not found:
            print('\nNo target tags found. Nothing to do.')
            return

        print(f'\nPlan: delete {len(found)} tag(s) in order: {found}')

        if dry_run:
            print('\n[DRY RUN] Stopping here. No tags were deleted.')
            return

        # --- Step 2-4: Delete one at a time with verification ---
        confirmed_deleted = []

        for i, target_name in enumerate(found, 1):
            print(f'\n=== [{i}/{len(found)}] Deleting "{target_name}" ===')

            # Fresh re-enumerate to get current tagId
            fresh_tags = enumerate_tags(script, svc)
            fresh = tag_census(fresh_tags)

            if target_name not in fresh:
                print(f'  Tag "{target_name}" no longer present (already gone?). Skipping.')
                confirmed_deleted.append(target_name)
                continue

            tag_id = fresh[target_name]['tagId']
            member_count = fresh[target_name]['memberCount']
            print(f'  Fresh tagId={tag_id}, memberCount={member_count}')

            # Update before-census with latest fresh state for non-targets
            # so collateral check compares against the most recent known state
            for name, info in fresh.items():
                if name != target_name:
                    before[name] = info

            # Delete
            print(f'  Calling DeleteTag({tag_id})...')
            result = script.exports_sync.del_tag(svc, tag_id)
            if not result.get('ok'):
                print(f'  ERROR: DeleteTag failed: {result.get("err", "unknown")}')
                print('  ABORTING -- no further deletions.')
                break

            print(f'  DeleteTag returned ok. Sleeping {SETTLE_DELAY}s for cache settle...')
            time.sleep(SETTLE_DELAY)

            # Verify
            print('  Re-enumerating for verification...')
            after_tags = enumerate_tags(script, svc)
            ok, problems = check_collateral(before, after_tags, target_name)

            if not ok:
                print('\n  *** COLLATERAL DAMAGE DETECTED -- ABORTING ***')
                for p in problems:
                    print(p)
                print(f'\n  Stopped after deleting "{target_name}". '
                      f'{len(found) - i} target(s) NOT attempted.')
                # Still record this one as deleted if the target is actually gone
                after = tag_census(after_tags)
                if target_name not in after:
                    confirmed_deleted.append(target_name)
                break

            print(f'  Verified: "{target_name}" gone, all other tags intact.')
            confirmed_deleted.append(target_name)

            # Update before-census: remove deleted tag so next iteration's
            # collateral check doesn't expect it
            before.pop(target_name, None)

        # --- Step 5: Final state ---
        print('\n' + '=' * 60)
        final_tags = enumerate_tags(script, svc)
        print(f'Final state: {len(final_tags)} tags')
        for t in sorted(final_tags, key=lambda x: x['name']):
            print(f"  {t['name']:30s}  id={t['tagId']:>22s}  members={t['memberCount']}")

        # --- Step 6: DB mirror ---
        if confirmed_deleted:
            print(f'\nClearing DB mirror for confirmed deletions: {confirmed_deleted}')
            for name in confirmed_deleted:
                n = clear_db_mirror(DB, name)
                print(f'  "{name}": updated {n} rows in pokemon.db')
        else:
            print('\nNo confirmed deletions -- DB mirror unchanged.')

        remaining = [n for n in targets
                     if n in tag_census(final_tags)]
        if remaining:
            print(f'\nWARNING: these targets still exist: {remaining}')
        else:
            print(f'\nAll targets removed successfully.')

    finally:
        try:
            script.unload()
        except Exception:
            pass
        sess.detach()


if __name__ == '__main__':
    main()
