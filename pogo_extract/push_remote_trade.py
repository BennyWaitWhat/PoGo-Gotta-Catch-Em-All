"""push_remote_trade.py -- set the in-game "Remote Trade" tag (visible to Forever Friends) to an EXACT membership.

User 2026-09-19: "Any shiny that I have more than 2 of, list the other lower iv ones for remote trade. clean out the
current ones i have" -> "all of them but only the bottom 3 for each".

The picks come from system/analysis/_remote_trade_picks.json (built by the scan: every shiny species+form group with
more than 2 copies contributes its BOTTOM 3 by IV among the copies below the best 2, skipping anything that cannot be
remote-traded -- already traded or lucky, shadow, untradable per the game master, caught in the last 30 days -- and
anything carrying another collectible axis: legacy move, background, XXL, Dynamax/Gigantamax, costume, hundo).

Pattern copied from push_armored_plan.py: one gated Frida session, live bag walk, per-mon DELTA records so every other
tag each mon carries survives, one batched apply_changes, a re-walk verify, then the DB mirror. Current members that
are not in the new list have the tag REMOVED ("clean out the current ones"). Never releases anything; a tag is a
reversible label, and this script refuses to touch the release pile.
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
import sqlite3

TAG = 'Remote Trade'
COLOUR = 3                      # only used if the tag does not exist (PokemonTagColor is 0-8)
PICKS = os.path.join(ROOT, 'system', 'analysis', '_remote_trade_picks.json')
DRY = '--dry-run' in sys.argv
norm = lambda u: format(int(u, 16), 'x')


def main():
    import tag_ops
    if tag_ops.is_pile_tag(TAG):
        raise SystemExit('REFUSING: %r is the release pile.' % TAG)
    want = {norm(u) for u in json.load(open(PICKS, encoding='utf-8'))}
    print('%s: %d picks from %s' % (TAG, len(want), os.path.basename(PICKS)))
    con = sqlite3.connect('file:%s?mode=ro' % os.path.join(ROOT, 'pokemon.db'), uri=True)
    rows = {norm(r[0]): r[1] for r in con.execute('SELECT uid_hex, species_name FROM pokemon WHERE in_bag=1')}
    con.close()
    unknown = want - set(rows)
    if unknown:
        print('  %d pick(s) are not in the last walk -- dropped: %s' % (len(unknown), sorted(unknown)[:4]))
        want -= unknown
    if DRY:
        print('--dry-run: nothing written, no phone contact.'); return 0

    import pogo_il2cpp as pg
    from reconcile_tags import ENUM_MEMBERS_JS
    from ready_gate import ensure_ready_for_writes

    def enum_by_name(sess, svc):
        en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
        try:
            return {t['name']: t for t in en.exports_sync.enumerate_all_tag_members(svc)}
        finally:
            en.unload()

    print('gating: waiting for an attach-safe PoGo...')
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
        gone = want - set(h2p)
        if gone:
            print('  %d pick(s) left the bag since the walk -- dropped: %d' % (len(gone), len(gone)))
            want -= gone

        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            pre_raw = enum_by_name(sess, svc)
            if TAG in pre_raw:
                tagproto = pre_raw[TAG]['tagProto']
                cur = {p2h[p] for p in pre_raw[TAG]['members'] if p in p2h}
                print('%s exists with %d member(s)' % (TAG, len(cur)))
            else:
                tagproto = tag_ops.create_tag(bt, svc, TAG, COLOUR)
                cur = set(); print('%s CREATED (colour %d)' % (TAG, COLOUR))
            add, rem = want - cur, cur - want
            print('to add %d | to remove %d | already right %d' % (len(add), len(rem), len(want & cur)))
            for u in sorted(rem):
                print('   clearing: %s' % rows.get(u, u))
            changes = ([{'proto': h2p[u], 'add': [tagproto], 'remove': []} for u in sorted(add)] +
                       [{'proto': h2p[u], 'add': [], 'remove': [tagproto]} for u in sorted(rem)])
            if changes:
                try:
                    bt.exports_sync.bulk_apply_changes(svc, [])      # first-call NRE warm-up
                except Exception as e:
                    print('  (warm-up threw, ignored: %s)' % e)
                time.sleep(0.5)
                n = tag_ops.apply_changes(bt, svc, changes, batch=150)
                print('apply_changes -> %d/%d' % (n, len(changes)))
                if n != len(changes):
                    raise SystemExit('ABORT: partial apply -- the DB mirror was NOT rewritten.')
        finally:
            bt.unload()

        print('\n=== VERIFY (re-walk each attempt: tagging reallocates protos) ===')
        final = None
        for attempt in range(3):
            time.sleep(5 if attempt == 0 else 7)
            bm2 = pg.walk_bag_protos(sess, bag)
            q2h = {pp: format(int(d), 'x') for d, pp in bm2.items()}
            post_raw = enum_by_name(sess, svc)
            got = {q2h[p] for p in (post_raw.get(TAG) or {}).get('members', []) if p in q2h}
            print('  attempt %d: server says %d member(s) (want %d)' % (attempt + 1, len(got), len(want)))
            final = got
            if got == want:
                break
        if final == want:
            tag_ops._mirror_db(TAG, sorted(final))
            print('VERIFIED: %s = %d member(s); pokemon.db mirrored.' % (TAG, len(final)))
            return 0
        print('DRIFT: server %d vs wanted %d (missing %d, extra %d) -- client cache lag is normal right after a big '
              'push; re-run to settle.' % (len(final or ()), len(want), len(want - (final or set())), len((final or set()) - want)))
        return 1
    finally:
        sess.detach()


if __name__ == '__main__':
    sys.exit(main())
