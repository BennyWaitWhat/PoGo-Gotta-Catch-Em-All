"""Remote Trade + Evolve for Size + the tag ORDER in ONE gated Frida session (speed study 2026-09-24, user: "1. ok";
tag order 2026-09-24: "reorder all the tags, but the most active ones i use on top").

Each tag used to open its own session: attach + the write gate (a fixed 3 s PID-stability sleep, ~15 adb calls) +
the bag/svc singleton picks, ~9 s apiece. Here that happens ONCE; then each tag runs its own unchanged sync() --
its own fresh bag walk ("I do want the re-walks"), binding read, push, verify and DB mirror. A failure in one never
stops the other, and neither can fail the cull: these are labels, never the pile. Remote Trade writes only the tag
proto the game's own get_RemoteTradeTagBinding returns (never a tag looked up by name); Evolve for Size refuses the
pile tag (tag_ops.is_pile_tag) before any walk or write.

  python sync_post_tags.py            # both, one session
  python sync_post_tags.py --dry-run  # compute both deltas' inputs, no phone contact

The tag order (system/scripts/order_tags.py ORDER) is read last, after any tag this pass created: a pure read when it
already matches, else every tag's SortIndex is sent again, each confirmed by the server. It never touches members.

Output: each step's lines under a '=== REMOTE TRADE ===' / '=== EVOLVE FOR SIZE ===' / '=== TAG ORDER ===' marker
(full_audit splits on them).
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'system', 'scripts'))
os.chdir(ROOT)
import sync_remote_trade as rt
import json, time
RT_STAMP = os.path.join('system', 'analysis', 'remote_trade_verified.json')   # {'offers': [...], 'ts': epoch} of the last verified set
RT_REVERIFY_H = 6.0                                                            # re-verify an unchanged offer set this often


def _forget_rt_stamp(why):
    """No proof this pass -> no skip next pass: remove remote_trade_verified.json (H04, 2026-09-29)."""
    try:
        os.remove(RT_STAMP)
        print('Remote Trade: not verified (%s) -- the skip stamp is cleared; the next cull re-verifies' % why)
    except FileNotFoundError:
        print('Remote Trade: not verified (%s) -- no skip stamp written; the next cull re-verifies' % why)
    except OSError as e:
        print('!! Remote Trade: not verified (%s) and %s could NOT be removed (%s) -- delete it by hand' % (why, RT_STAMP, e))


def main():
    # each tag's inputs in its OWN try: a crash computing one must not cost the other its refresh (review 2026-09-24)
    rt_want = es_want = None
    print('=== REMOTE TRADE ===')
    try:
        _w, stats = rt.remote_trade_picks.compute()
        rt_want = {rt.norm(u) for u in _w}
        print('Remote Trade offers computed: %d  (%s)' % (len(rt_want), ', '.join('%s %d' % kv for kv in sorted(stats.items()))))
    except Exception as e:
        print('REMOTE TRADE stopped: its offers could not be computed -- %s: %s' % (type(e).__name__, e))
    # SKIP THE RE-VERIFY WHEN NOTHING CHANGED (user 2026-09-29, workflow review pick 4): the offer set was re-read and
    # re-verified on the phone every cull (~30 s, 'already up to date' every time). Same offers as the last VERIFIED
    # push and that verify younger than RT_REVERIFY_H -> no walk, no read; a changed set or an old verify runs it all.
    rt_skip = None
    if rt_want is not None:
        try:
            _st = json.load(open(RT_STAMP, encoding='utf-8'))
            _age = (time.time() - float(_st.get('ts') or 0)) / 3600
            # a stamp from a VERIFIED outcome only (R-B review): one without 'outcome' was written by the pre-H04 writer
            # on ANY rc 0 -- "binding unavailable" and "NOT confirmed" included
            if (set(_st.get('offers') or []) == rt_want and _age < RT_REVERIFY_H
                    and _st.get('outcome') in ('already up to date', 'pushed and verified')):
                rt_skip = _age
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    if rt_skip is not None:
        print('Remote Trade: same %d offers as the set verified %.1f h ago -- skipped (re-verified every %g h)'
              % (len(rt_want), rt_skip, RT_REVERIFY_H))
    # --reconcile / --retire (2026-09-30, cull speed pick 2): full_audit's post-push checks ride THIS session -- the
    # reconcile report first (read-only; drift -> rc 3 and no label write at all), then retire's empty-shell deletions,
    # Remote Trade and the tag order. One attach instead of three. A failed offer computation no longer skips them.
    shared = '--reconcile' in sys.argv or '--retire' in sys.argv
    if rt_want is None and not shared:
        return 1
    if '--dry-run' in sys.argv:
        print('--dry-run: no phone contact.'); return 0

    import pogo_il2cpp as pg
    from ready_gate import ensure_ready_for_writes
    pg.wait_ready_to_attach(timeout_s=300)
    sess, pid = pg.get_session()
    rc = 0 if rt_want is not None else 1
    try:
        if '--reconcile' in sys.argv:
            print('=== RECONCILE ===', flush=True)
            import argparse, reconcile_tags
            try:
                _rr = reconcile_tags.run(argparse.Namespace(report=True, fix_db=False, fix_server=False, tags=None,
                                                            verbose=False, allow_untag=False, force_mass=False),
                                         sess=sess, pid=pid)
            except Exception as e:
                print('RECONCILE failed: %s: %s' % (type(e).__name__, e)); _rr = 1
            if _rr:
                print('RECONCILE rc=%d -- no label writes this pass' % _rr, flush=True)
                return 3
        _rs = ensure_ready_for_writes(sess, pid)
        if '--retire' in sys.argv:               # where the separate retire step ran: right after the push, before the
            print('=== RETIRE ===', flush=True)  # tag order (which then fixes the order around any deleted shell)
            try:                                 # fail-soft, like the step it replaces: never changes the rc
                import retire_tags
                _ta = retire_tags.args([])
                _plan = retire_tags.plan(_ta)
                if _plan is not None:
                    retire_tags.run_on_session(sess, pid, _ta, *_plan)
            except Exception as e:
                print('RETIRE failed: %s: %s' % (type(e).__name__, e))
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        # the gate just picked AND probed TaggingRpcService in this session (Stage 2, 2026-09-24): no second pick
        svc = getattr(_rs, 'svc_addr', '') or pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        # 'Evolve for Size' RETIRED 2026-09-29: its picks are Evolve Once / Twice members now (granular_tags.evolve_advice),
        # pushed by prune with every other tag -- one phone step fewer here.
        for marker, want, run in (('=== REMOTE TRADE ===', rt_want, lambda: rt.sync(sess, bag, svc, rt_want)),):
            print(marker, flush=True)
            name = marker.strip('= ')
            if rt_skip is not None:
                continue                          # said above, before the attach
            if want is None:
                print('%s stopped: no offers computed (see above)' % name)
                continue
            try:
                os.remove(RT_STAMP)                 # R-B review: a push killed half-way (timeout, Ctrl-C) must not leave an
            except OSError:                         # older proof behind for an identical offer set to trust
                pass
            try:
                r = run() or 0
            except SystemExit as e:
                print('%s stopped: %s' % (name, e)); r = 1
            except Exception as e:
                print('%s failed: %s: %s' % (name, type(e).__name__, e)); r = 1
            if r:
                print('%s rc=%d' % (name, r))       # its OWN rc line, under its own marker (review 2026-09-24)
                _o = getattr(rt, 'LAST', {}).get('outcome')
                _forget_rt_stamp('rc=%d%s' % (r, (', ' + _o) if _o else ''))
            elif not getattr(rt, 'LAST', {}).get('verified'):
                # rc 0 IS NOT PROOF (2026-09-29, H04): sync() also returns 0 for "binding unavailable" and "NOT confirmed:
                # N missing, M extra". Only a read-back equal to the offers may start the RT_REVERIFY_H skip, and an
                # unproven push voids the previous stamp -- the phone no longer holds the set that stamp vouched for.
                _forget_rt_stamp(getattr(rt, 'LAST', {}).get('outcome') or 'not verified')
            else:
                try:
                    json.dump({'offers': sorted(want), 'ts': time.time(), 'outcome': rt.LAST.get('outcome')},
                              open(RT_STAMP, 'w', encoding='utf-8'))
                except OSError:
                    pass
            rc |= r
        print('=== TAG ORDER ===', flush=True)
        try:
            import order_tags
            _n, _ok = order_tags.keep_order(pg, sess, svc)
            rc |= 0 if _ok else 1
        except Exception as e:                   # a label nicety: report it, never fail the cull over it
            print('TAG ORDER failed: %s: %s' % (type(e).__name__, e)); rc |= 1
    finally:
        sess.detach()
    return rc


if __name__ == '__main__':
    sys.exit(main())
