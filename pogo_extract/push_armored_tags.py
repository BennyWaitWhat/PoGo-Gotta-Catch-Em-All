"""ADDITIVE-ONLY push of two new server tags: 'Armored UL' and 'Armored ML'.

ONE Frida attach. Creates the two tags and adds exactly their 5 members each.
It NEVER removes a member and NEVER touches any other tag -- there is no untag/
prune path in this file at all. It snapshots EVERY server tag's membership
before the writes and re-checks after, so "no pre-existing tag lost members" is
proved, not assumed.

Usage: python push_armored_tags.py [--dry-run]
"""
import os, sys, time, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'system', 'scripts'))
os.chdir(HERE)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pogo_il2cpp as pg
import tag_ops
from reconcile_tags import ENUM_MEMBERS_JS

TD = os.path.join(HERE, 'system', 'analysis', 'tagsets')

# name -> (tagset filename, PokemonTagColor 0-8).  9 is the silent-no-op trap.
PLAN = {
    'Armored UL': ('Armored_UL.txt', 0),
    'Armored ML': ('Armored_ML.txt', 7),
}

DRY = '--dry-run' in sys.argv[1:]


def norm(x):
    return format(int(x, 16), 'x')


def file_uids(fn):
    with open(os.path.join(TD, fn), encoding='utf-8') as fh:
        return {norm(u) for u in fh.read().split() if u.strip()}


def enum_by_name(sess, svc):
    en = pg.get_script_with_helpers(sess, ENUM_MEMBERS_JS)
    try:
        return {t['name']: t for t in en.exports_sync.enumerate_all_tag_members(svc)}
    finally:
        en.unload()


def uidset(info, proto_to_hex):
    s, unmapped = set(), 0
    for pp in info['members']:
        uh = proto_to_hex.get(pp)
        if uh:
            s.add(uh)
        else:
            unmapped += 1
    return s, unmapped


def main():
    for name, (fn, color) in PLAN.items():
        assert 0 <= color <= 8, 'colour out of range for %s' % name
        w = file_uids(fn)
        assert len(w) == 5, '%s: expected 5 uids, got %d' % (fn, len(w))
        print('plan %-12s colour=%d  file=%s  want=%d' % (name, color, fn, len(w)))

    sess, pid = pg.get_session()
    print('attached pid %d  %s' % (pid, '[DRY-RUN]' if DRY else '[LIVE]'))
    try:
        if not DRY:
            from ready_gate import ensure_ready_for_writes
            ensure_ready_for_writes(sess, pid)

        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        bag_map = pg.walk_bag_protos(sess, bag)
        hex_to_proto = {format(int(d), 'x'): pp for d, pp in bag_map.items()}
        proto_to_hex = {pp: uh for uh, pp in hex_to_proto.items()}
        print('bag-walk: %d live protos' % len(hex_to_proto))

        # ---- PRE snapshot of EVERY server tag ----
        pre_raw = enum_by_name(sess, svc)
        pre = {}
        for nm, info in pre_raw.items():
            s, unm = uidset(info, proto_to_hex)
            pre[nm] = s
        print('PRE: %d server tags' % len(pre))
        for nm in sorted(pre):
            print('   pre  %-22s %d' % (nm, len(pre[nm])))
        json.dump({k: sorted(v) for k, v in pre.items()},
                  open(os.path.join(HERE, '_armored_pre_tags.json'), 'w'), indent=0)

        # ---- resolve our targets BEFORE any write; abort if any is missing ----
        targets = {}
        for name, (fn, color) in PLAN.items():
            want = file_uids(fn)
            missing = [u for u in want if u not in hex_to_proto]
            if missing:
                raise SystemExit('ABORT: %s -- uid(s) not in live bag: %s' % (name, missing))
            targets[name] = (want, color)
            already = pre.get(name)
            print('%s: exists=%s  want=%d  to-add=%d' % (
                name, 'yes(%d)' % len(already) if already is not None else 'no',
                len(want), len(want - (already or set()))))

        if DRY:
            print('dry-run: no writes'); return 0

        bt = tag_ops._load_bulk_tag_script(sess)
        applied_report = {}
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            for name, (want, color) in targets.items():
                tagproto = tag_ops.create_tag(bt, svc, name, color)
                print('  %s -> tagproto %s' % (name, tagproto))
                add = sorted(want - pre.get(name, set()))
                protos = [hex_to_proto[u] for u in add]
                n = tag_ops.apply_members(bt, svc, tagproto, protos)
                if n is None:
                    n = len(protos)
                applied_report[name] = (n, len(protos))
                print('  %s: applied %d/%d' % (name, n, len(protos)))
        finally:
            bt.unload()

        # ---- VERIFY: re-walk (tagging REALLOCATES protos) + re-enumerate ----
        print('\n=== VERIFY ===')
        allok = False
        for attempt in range(3):
            time.sleep(5 if attempt == 0 else 7)
            bm2 = pg.walk_bag_protos(sess, bag)
            p2h = {pp: format(int(d), 'x') for d, pp in bm2.items()}
            post_raw = enum_by_name(sess, svc)
            post = {}
            for nm, info in post_raw.items():
                s, _ = uidset(info, p2h)
                post[nm] = s
            allok = True
            lines = []
            for name, (want, _c) in targets.items():
                got = post.get(name)
                if got is None:
                    lines.append('  %-22s MISSING from server' % name); allok = False; continue
                extra, short = got - want, want - got
                ok = not extra and not short
                if not ok:
                    allok = False
                lines.append('  %-22s server=%d want=%d [%s]' % (
                    name, len(got), len(want), 'OK' if ok else 'extra=%d short=%d' % (len(extra), len(short))))
            # regression guard: no PRE-EXISTING tag may lose a member
            lost = {}
            for nm, s in pre.items():
                if nm in PLAN:
                    continue
                gone = s - post.get(nm, set())
                if gone:
                    lost[nm] = sorted(gone)
            lines.append('  pre-existing tags that LOST members: %d %s' % (len(lost), lost if lost else 'OK'))
            if lost:
                allok = False
            print('\n'.join(lines))
            if allok:
                break
            if attempt < 2:
                print('  (attempt %d not clean -- add cache-lag is normal, re-walking)' % (attempt + 1))
            json.dump({k: sorted(v) for k, v in post.items()},
                      open(os.path.join(HERE, '_armored_post_tags.json'), 'w'), indent=0)
        print('\nRESULT: %s' % ('BOTH TAGS EXACT, NOTHING LOST' if allok else 'NOT CLEAN -- see above'))
    finally:
        sess.detach()
    print('detached.')
    bad = any(a != t for a, t in applied_report.values()) if not DRY else False
    return 0 if (allok and not bad) else 1


if __name__ == '__main__':
    sys.exit(main())
