"""fix_remote_trade_dupe.py -- ONE-SHOT (2026-09-19): merge the duplicate "Remote Trade" tag into the user's own one.

What went wrong: push_remote_trade.py looked the tag up through `{t['name']: t for t in enumerate_all_tag_members(svc)}`.
A dict keyed by NAME collapses two tags that share a name, so his own "Remote Trade" (17 members, Visible to Forever
Friends) was overwritten in the lookup, the script concluded it did not exist, and create_tag made a SECOND tag with
the same name holding the 252 picks. Tags must be identified by tagId, never by name.

This repair, in one gated session:
  1. enumerate EVERY tag (as a list, no name collapsing) and find all tags named "Remote Trade";
  2. HIS = the one whose members are not the pick set; MINE = the one holding the picks;
  3. per-mon deltas: every pick gains HIS tag and loses MINE; his old members that are not picks lose HIS tag
     (the "clean out the current ones" he asked for);
  4. verify against the server, then DeleteTag the duplicate and mirror pokemon.db.
Never releases anything.
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)

TAG = 'Remote Trade'
PICKS = os.path.join(ROOT, 'system', 'analysis', '_remote_trade_picks.json')
norm = lambda u: format(int(u, 16), 'x')


def main():
    import pogo_il2cpp as pg, tag_ops
    from reconcile_tags import ENUM_MEMBERS_JS
    from ready_gate import ensure_ready_for_writes
    from nuke_all_tags import JS as NUKE_JS

    want = {norm(u) for u in json.load(open(PICKS, encoding='utf-8'))}
    print('picks on file: %d' % len(want))
    pg.wait_ready_to_attach(timeout_s=300)
    sess, pid = pg.get_session(); print('attached pid %d' % pid)
    try:
        ensure_ready_for_writes(sess, pid)
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        bm = pg.walk_bag_protos(sess, bag)
        h2p = {format(int(d), 'x'): pp for d, pp in bm.items()}
        p2h = {pp: uh for uh, pp in h2p.items()}
        print('bag-walk: %d live protos' % len(h2p))

        en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            all_tags = en.exports_sync.enumerate_all_tag_members(svc)
        finally:
            en.unload()
        mine = [t for t in all_tags if t['name'] == TAG]
        print('tags named %r: %d' % (TAG, len(mine)))
        for t in mine:
            print('   tagProto %s -> %d member(s)' % (t['tagProto'], len(t.get('members') or [])))
        if len(mine) < 2:
            print('only one tag by that name -- nothing to merge.'); return 0
        scored = []
        for t in mine:
            mem = {p2h[p] for p in (t.get('members') or []) if p in p2h}
            scored.append((len(mem & want), t, mem))
        scored.sort(key=lambda x: -x[0])
        dupe, dupe_mem = scored[0][1], scored[0][2]          # the one holding the picks = the one I created
        his, his_mem = scored[1][1], scored[1][2]            # the user's own tag
        print('MINE (to delete): %d member(s), %d of them picks' % (len(dupe_mem), scored[0][0]))
        print('HIS  (to fill):   %d member(s), %d of them picks' % (len(his_mem), scored[1][0]))
        if scored[1][0] > scored[0][0]:
            raise SystemExit('ABORT: cannot tell the two apart safely.')

        live_want = {u for u in want if u in h2p}
        deltas = {}
        for u in live_want:
            add = [his['tagProto']] if u not in his_mem else []
            rem = [dupe['tagProto']] if u in dupe_mem else []
            if add or rem:
                deltas[u] = {'add': add, 'remove': rem}
        for u in his_mem - live_want:                        # clean out the current ones
            if u in h2p:
                deltas.setdefault(u, {'add': [], 'remove': []})['remove'].append(his['tagProto'])
        for u in dupe_mem - live_want:
            if u in h2p:
                deltas.setdefault(u, {'add': [], 'remove': []})['remove'].append(dupe['tagProto'])
        print('change records: %d' % len(deltas))

        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            try:
                bt.exports_sync.bulk_apply_changes(svc, [])
            except Exception as e:
                print('  (warm-up threw, ignored: %s)' % e)
            time.sleep(0.5)
            changes = [{'proto': h2p[u], 'add': d['add'], 'remove': d['remove']} for u, d in sorted(deltas.items())]
            n = tag_ops.apply_changes(bt, svc, changes, batch=150)
            print('apply_changes -> %d/%d' % (n, len(changes)))
            if n != len(changes):
                raise SystemExit('ABORT: partial apply -- duplicate NOT deleted, nothing mirrored.')
        finally:
            bt.unload()

        print('\n=== VERIFY ===')
        ok = False
        for attempt in range(3):
            time.sleep(5 if attempt == 0 else 7)
            bm2 = pg.walk_bag_protos(sess, bag)
            q2h = {pp: format(int(d), 'x') for d, pp in bm2.items()}
            en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
            try:
                post = [t for t in en.exports_sync.enumerate_all_tag_members(svc) if t['name'] == TAG]
            finally:
                en.unload()
            byproto = {t['tagProto']: {q2h[p] for p in (t.get('members') or []) if p in q2h} for t in post}
            hm = byproto.get(his['tagProto'], set()); dm = byproto.get(dupe['tagProto'], set())
            print('  attempt %d: yours %d (want %d) | duplicate %d (want 0)' % (attempt + 1, len(hm), len(live_want), len(dm)))
            if hm == live_want and not dm:
                ok = True; break
        if not ok:
            print('DRIFT -- duplicate NOT deleted. Re-run to settle (client cache lag after a big push).'); return 1

        sc = pg.get_script_with_helpers(sess, NUKE_JS)
        try:
            tags_full = sc.exports_sync.enum_tags_full(svc)
            tid = next((t['tagId'] for t in tags_full if t['name'] == TAG and int(t.get('memberCount') or 0) == 0), None)
            if tid is None:
                print('the empty duplicate is not visible yet -- run again in a minute to delete it.'); return 1
            r = sc.exports_sync.del_tag(svc, tid)
            print('DeleteTag(empty %r id=%s) -> %s' % (TAG, tid, r))
        finally:
            sc.unload()
        tag_ops._mirror_db(TAG, sorted(live_want))
        print('DONE: %r is your own tag with %d member(s); the duplicate is gone.' % (TAG, len(live_want)))
        return 0
    finally:
        sess.detach()


if __name__ == '__main__':
    sys.exit(main())
