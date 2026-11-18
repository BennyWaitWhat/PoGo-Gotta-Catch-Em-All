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

TWO FALSE ALARMS, FIXED 2026-11-18 (Benny 17:44, on a cull that printed four warnings: "DUDE, whats with these
warnings?!?!?! fix them"):
  - The census check called every count that dropped COLLATERAL. At 17:16 that was 'Transfer 7 -> 4': he had released
    the three new pile Pokemon during the 3 s wait. The check now reads WHO left (released_members): a member that is no
    longer in the bag is his release, said in one plain line, and the run goes on. A Pokemon that left a tag and is
    still in the bag stops the run exactly as before, and so does everything the check cannot read.
  - A DeleteTag that threw was printed as "rate limit reached" with the exception dropped, so nobody ever read what the
    game said (the 1-3-per-session limit above was inferred from such lines). The line now carries the exception's own
    class and message (exc_text_js). The one text known to be the game's first-call hiccup (tag_ops.first_call_hiccup)
    gets ONE more try after the settle wait; anything else still ends the run and still reads as a warning.
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


def released_members(before, after, left_bag):
    """{tag: the uids that left it} for every tag whose member count DROPPED between two censuses only because those
    Pokemon are no longer in the bag: he released (or traded, or evolved) them while the check waited.
    before / after: safe_nuke_tags.tag_census of an enumeration WITH member uids. left_bag(uids) -> the ones that are no
    longer in the bag; asked once, and only when a count dropped.
    Everything else stays what check_collateral makes of it: a list that was not read on both sides, a member that
    could not be read, a count that does not match its list, a member that joined, and a Pokemon that left a tag and is
    STILL in the bag -- that last one is what a delete hitting the wrong tag looks like."""
    cand = {}
    for name, b in before.items():
        a = after.get(name)
        if a is None or a['memberCount'] >= b['memberCount']:
            continue
        bu, au = b.get('memberUids'), a.get('memberUids')
        if bu is None or au is None or '' in bu or '' in au or len(bu) != b['memberCount'] or len(au) != a['memberCount']:
            continue
        lost = set(bu) - set(au)
        if set(au) - set(bu) or len(lost) != len(bu) - len(au):
            continue
        cand[name] = lost
    if not cand:
        return {}
    gone = set(left_bag(sorted(set().union(*cand.values()))))
    return {n: u for n, u in cand.items() if u <= gone}


_EXC_JS_FROM, _EXC_JS_TO = 'var _GHAPI = null;', "// Niantic's Promise<T>"


def exc_text_js(path=None):
    """bulk_tag.js's own exception reader (_excText and the helpers it calls), cut out between its first line and the
    comment after it, to put in front of the delete script: the SAME code that has read SetPokemonTags' exceptions on
    the phone since 2026-11-17, not a second copy of it. '' when the file or a mark is missing -- the delete then names
    the exception's class only. The file is tag_ops.BULK_TAG_JS, the one the writers load: its name is not spelled here,
    because audit_invariants counts every script that names it as one that can ADD tag members."""
    import tag_ops
    try:
        with open(path or tag_ops.BULK_TAG_JS, encoding='utf-8') as f:
            src = f.read()
        a = src.index(_EXC_JS_FROM)
        js = src[a:src.index(_EXC_JS_TO, a)]
    except (OSError, ValueError):
        return ''
    return js if 'function _excText(exc)' in js and 'rpc.exports' not in js else ''


def refusal_line(t, res, sent):
    """(routine, line) for an empty shell the game did not delete. routine = both tries hit the game's known first-call
    hiccup: the shell is still there and the next cull tries again, which is no warning. Any other exception is news:
    its line keeps the words the cull's scan ('threw') and its retire relay ('refused') look for."""
    import tag_ops
    what = ' -- '.join(x for x in (res.get('excClass'), res.get('excText')) if x) or 'an exception nothing could be read from'
    if tag_ops.first_call_hiccup(res.get('excText')):
        return True, ("  %-20s still there: the game's known first-call hiccup on %s (%s) -- the next cull tries again"
                      % (t, 'both tries' if sent > 1 else 'the first try', what))
    return False, '  %-20s DeleteTag refused: the game threw %s -- stopping this run' % (t, what)


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
    import tag_ops
    deleted, left = [], []
    try:
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        script = pg.get_script_with_helpers(sess, exc_text_js() + '\n' + snt.JS)
        tags = snt.enumerate_tags(script, svc)
        census = snt.tag_census(tags)
        _dups = snt.duplicate_names(tags)     # (2026-09-30) a by-name census hides one copy of a duplicated name
        if _dups:
            print('duplicate tag names on the device, not touched here: %s (safe_nuke_tags.py --empty-duplicates)'
                  % ', '.join('%r x%d' % (n, len(v)) for n, v in sorted(_dups.items())))
            census = {n: v for n, v in census.items() if n not in _dups}
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
        bag = []                              # the bag singleton: picked only if a tag's count ever drops

        def left_bag(uids):
            """Which of these Pokemon are no longer in the bag: one read of the bag for exactly these uids (it stops no
            world). A release whose answer is still on its way gets a second look 2 s later."""
            if not bag:
                bag.append(pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl'))
            still = set(uids)
            for k in range(2):
                if k:
                    time.sleep(2.0)
                still = set(pg.find_protos_for_uids(sess, bag[0], sorted(uids)))
                if not still:
                    break
            return set(uids) - still

        for t in empty[:a.max]:
            sent, res = 0, {}
            while True:
                now = snt.enumerate_tags(script, svc, True)
                fresh = snt.tag_census(now)
                # ONE more try, only after the game's known first-call hiccup and only while the shell is still there
                again = sent == 1 and not res.get('ok') and tag_ops.first_call_hiccup(res.get('excText'))
                if t not in fresh or fresh[t]['memberCount'] > 0 or (sent and not again):
                    break
                if not sent:
                    for name, info in fresh.items():
                        if name != t:
                            before[name] = info
                res = script.exports_sync.del_tag(svc, fresh[t]['tagId'])
                sent += 1
                time.sleep(snt.SETTLE_DELAY)
            if not sent:
                if t not in fresh:
                    print('  %-20s already gone' % t); deleted.append(t); left.remove(t)
                else:
                    print('  %-20s regained %d member(s) -- skipping' % (t, fresh[t]['memberCount']))
                continue
            gone = t not in fresh
            if not gone and not res.get('ok'):    # the game threw and the shell is still there
                print(refusal_line(t, res, sent)[1])
                break
            rel, why = {}, ''
            try:
                rel = released_members({n: v for n, v in before.items() if n != t}, fresh, left_bag)
            except Exception as e:                # no bag read: a dropped count stays the alarm it always was
                why = '%s: %s' % (type(e).__name__, e)
            for n, u in sorted(rel.items()):
                print('  %-20s %d member(s) fewer while this ran: no longer in the bag (released, traded or evolved) -- '
                      'not the delete' % (n, len(u)))
                before[n] = fresh[n]
            ok, problems = snt.check_collateral(before, now, t)
            if not ok:
                print('  *** COLLATERAL CHANGE DETECTED after deleting %r -- stopping ***' % t)
                for p in problems:
                    print('     ', p)
                if why:
                    print('      (whether those Pokemon were released is not known: the bag read stopped with %s)' % why)
                if gone:
                    deleted.append(t); left.remove(t)
                break
            how = ''
            if not res.get('ok'):
                how = ' (the game answered the call with %s; the tag is gone all the same)' % (res.get('excClass') or 'an exception')
            elif sent > 1:
                how = " on the second try (the first hit the game's known first-call hiccup)"
            print('  %-20s deleted%s, every other tag intact' % (t, how))
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
