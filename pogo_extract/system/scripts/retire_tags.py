"""retire_tags.py -- delete the EMPTY device shells of retired tags, one at a time, within the DeleteTag rate limit.

WHY (2026-09-09, user: "I feel like I have too many tags and some are redundant" -> 15 tags retired). A retired tag
lives in granular_tags.RETIRED_TAGS. The pipeline handles it in three steps, each safe on its own:
  1. build_tagsets deletes its stale tagset file            (no producer, no orphan)
  2. prune_tags strips every member it still holds on the device, never creates it
  3. THIS script deletes the empty shell -- one DeleteTag per tag, re-enumerate + collateral check between
     deletions (safe_nuke_tags.py's method: a tight delete loop once collaterally destroyed 'Mega'), and it
     STOPS at the first DeleteTag failure because the game only honours 1-3 deletions per session
     (tag_ops.py note 7). full_audit runs it fail-soft after every good sync, so the shells drain over cycles.

RULES: never deletes a tag that still has members (prune first); never touches the pile (tag_ops.is_pile_tag);
deletes only a RETIRED_TAGS name or a registered tag whose tagset file is PRESENT AND EMPTY (an empty managed shell --
since 2026-09-26 that includes every 'Stop at <stage>' nobody needs now); --max N caps deletions per run; --dry-run lists.
Exit 0 always unless the attach itself fails -- the number of shells left is printed on the last line.
"""
import sys, os, time, argparse, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
os.chdir(ROOT)


EMPTY_SINCE = os.path.join('system', 'analysis', 'empty_since.json')   # {tag: first pass its tagset was empty (ISO)}


def grace_filter(empty_files, hours, now=None, path=EMPTY_SINCE):
    """Which empty managed shells are OLD enough to delete. An evolve tag flips between 0 and 1 members from one cull
    to the next; deleting the shell at the first empty pass and re-creating it at the next reshuffled the whole tag
    order every cull (27-33 SortIndex edits + a DeleteTag + an AddTag; the post-tags step went from ~15 s to ~40-60 s,
    2026-09-27..29). So a shell is deleted only after it has been empty for `hours` (first-empty stamps in EMPTY_SINCE;
    a tag with members again is forgotten). Returns (due, waiting)."""
    import datetime as _dt
    now = now or _dt.datetime.now()
    try:
        seen = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        seen = {}
    seen = {t: s for t, s in seen.items() if t in empty_files}         # regained members -> the clock resets
    for t in empty_files:
        seen.setdefault(t, now.strftime('%Y-%m-%dT%H:%M'))
    due = [t for t in empty_files if (now - _dt.datetime.strptime(seen[t], '%Y-%m-%dT%H:%M')).total_seconds() >= hours * 3600]
    waiting = [t for t in empty_files if t not in due]
    try:
        json.dump(seen, open(path + '.tmp', 'w', encoding='utf-8'), indent=0)
        os.replace(path + '.tmp', path)
    except OSError:
        pass
    return due, waiting


def args(argv=None):
    ap = argparse.ArgumentParser()
    # 20, not 3 (user 2026-09-23: "delete the tags they're empty"). The 1-3-per-session limit bites on tags that
    # still hold members; this loop deletes EMPTY shells only, re-checks each right before deleting, runs a
    # collateral census after every one and stops on the first refusal. Measured 2026-09-09: 15 empty tags in one
    # session, zero refusals -- but 2026-09-23: 3 empty shells, then refused, and refused again 10 min later (tag_ops note 7).
    ap.add_argument('--max', type=int, default=20, help='empty-shell deletions per run (stops on the first refusal)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--grace-hours', type=float, default=24.0, help='an EMPTY managed shell is deleted only after this long empty (0 = at once)')
    ap.add_argument('--bookkeep-only', action='store_true',
                    help="update the first-empty stamps from this pass's tagsets and exit -- no attach (H04-10)")
    return ap.parse_args(argv)


def plan(a):
    """The no-phone half: the grace bookkeeping, then what could be deleted -> (retired, empty_files), or None when
    there is nothing to do (the reason is printed)."""
    import granular_tags
    from tag_ops import is_pile_tag
    retired = [t for t in granular_tags.RETIRED_TAGS if not is_pile_tag(t)]
    # EMPTY MANAGED TAGSETS, read BEFORE the attach (2026-09-26): a 'Stop at <stage>' nobody needs any more is written
    # empty (granular_tags.STOP_REGISTRY) and its shell must go even on a day RETIRED_TAGS is empty -- the old early
    # return below only asked about retired tags and would have skipped every empty shell.
    td = granular_tags.tagset_dir()
    exempt = {v['tag'] for v in granular_tags.EXEMPT_TAGSETS.values() if v['tag']}
    empty_files = [t for t, (fn, _c) in granular_tags.registry().items()
                   if not is_pile_tag(t) and t not in exempt and os.path.exists(os.path.join(td, fn))
                   and not open(os.path.join(td, fn), encoding='utf-8').read().split()]
    empty_files, waiting = grace_filter(empty_files, a.grace_hours)
    if a.bookkeep_only:
        # EVERY PASS, NOT ONLY WHEN WE DELETE (H04-10, 2026-09-29): full_audit runs the deleting retire only when the sync
        # touched a retired / empty tag, so a tag that refilled for a few passes kept its old first-empty stamp and was
        # deleted the moment it emptied again -- the churn the 24 h grace exists to stop. This is the no-phone half.
        print('grace bookkeeping: %d empty managed shell(s) tracked, %d due' % (len(empty_files) + len(waiting), len(empty_files)))
        return None
    if waiting:
        print('empty managed shells kept for now (empty less than %g h): %s' % (a.grace_hours, ', '.join(waiting)))
    if not retired and not empty_files:
        print('no retired tags configured and no empty managed tagset due -- nothing to do'); return None
    return retired, empty_files


def main():
    a = args()
    p = plan(a)
    if p is None:
        return 0
    import pogo_il2cpp as pg
    pg.wait_ready_to_attach(timeout_s=300)
    sess, pid = pg.get_session()
    print('attached pid %d' % pid)
    return run_on_session(sess, pid, a, *p, own=True)


def run_on_session(sess, pid, a, retired, empty_files, own=False):
    """The phone half on a live session. own=False (2026-09-30, cull speed pick 2): sync_post_tags.py --retire runs it in
    the post-push session it already holds -- no attach of its own, and that session stays attached for its owner."""
    import pogo_il2cpp as pg
    import safe_nuke_tags as snt          # JS + enumerate/census/collateral helpers; main() is __main__-guarded
    deleted, left = [], []
    try:
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        script = pg.get_script_with_helpers(sess, snt.JS)
        tags = snt.enumerate_tags(script, svc)
        census = snt.tag_census(tags)
        # EMPTY MANAGED SHELLS (2026-09-09, same user complaint): a vocabulary tag nobody qualifies for right now
        # (Safety Hold after its hold cleared) is a 0-member entry in the in-game list. prune never creates a tag
        # for an empty want, so deleting the shell is symmetric: the day someone qualifies, prune recreates it.
        # Never the pile, never an exempt tag, and only when the tagset file is PRESENT AND EMPTY (the engine's
        # explicit "nobody qualifies"), never when the file is missing (producer did not run -> do not touch).
        # empty_files (above, same test) includes every empty 'Stop at <stage>' in the registry (2026-09-26).
        empty_managed = [t for t in empty_files if t in census and census[t]['memberCount'] == 0]
        if empty_managed:
            print('empty managed shells (file present and empty): %s' % ', '.join(empty_managed))
        present = [t for t in retired if t in census] + empty_managed
        if not present:
            print('retired shells on the device: 0 -- all clear'); return 0
        busy = [t for t in present if census[t]['memberCount'] > 0]
        empty = [t for t in present if census[t]['memberCount'] == 0]
        for t in busy:
            print('  %-20s still holds %d member(s) -- prune_tags strips it first; not deleting' % (t, census[t]['memberCount']))
        print('empty retired shells: %d -> deleting up to %d this run%s' % (len(empty), a.max, ' [DRY RUN]' if a.dry_run else ''))
        left = list(empty)
        if a.dry_run:
            return 0
        before = dict(census)
        for t in empty[:a.max]:
            fresh = snt.tag_census(snt.enumerate_tags(script, svc))
            if t not in fresh:
                print('  %-20s already gone' % t); deleted.append(t); left.remove(t); continue
            if fresh[t]['memberCount'] > 0:
                print('  %-20s regained %d member(s) -- skipping' % (t, fresh[t]['memberCount'])); continue
            for name, info in fresh.items():
                if name != t:
                    before[name] = info
            res = script.exports_sync.del_tag(svc, fresh[t]['tagId'])
            if not res.get('ok'):
                print('  %-20s DeleteTag refused (%s) -- rate limit reached; stopping this run' % (t, res.get('err', '?')))
                break
            time.sleep(snt.SETTLE_DELAY)
            after = snt.enumerate_tags(script, svc)
            ok, problems = snt.check_collateral(before, after, t)
            if not ok:
                print('  *** COLLATERAL CHANGE DETECTED after deleting %r -- stopping ***' % t)
                for p in problems:
                    print('     ', p)
                if t not in snt.tag_census(after):
                    deleted.append(t); left.remove(t)
                break
            print('  %-20s deleted, every other tag intact' % t)
            deleted.append(t); left.remove(t); before.pop(t, None)
    finally:
        if own:
            sess.detach()
    for t in deleted:
        try:
            snt.clear_db_mirror(snt.DB, t)
        except Exception as e:
            print('  (db mirror for %r not cleared: %s)' % (t, e))
    print('retired shells: deleted %d (%s); %d left for later runs%s'
          % (len(deleted), ', '.join(deleted) or '-', len(left), (': ' + ', '.join(left)) if left else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
