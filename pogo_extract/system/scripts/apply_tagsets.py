"""Apply the verified tag membership sets (system/analysis/tagsets/*.txt) to the
server in ONE Frida session (one attach, one bag-walk, create+apply each tag),
reusing tag_ops' hardened primitives (warm-up, backoff create, batched apply,
collateral-safe). Mirrors each tag into pokemon.db.auth_tag_names.

PRECONDITION: the two REBUILD tags (1 GL Meta, 1 UL Meta) must be safe_nuke'd
FIRST so create_tag() makes them fresh -- otherwise apply would UNION new members
onto the old broken ones.
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
os.chdir(ROOT)
import pogo_il2cpp as pg
import tag_ops
sys.stdout.reconfigure(encoding='utf-8')

TD = os.path.join(ROOT, 'system', 'analysis', 'tagsets')
# (tag name, tagset file, PokemonTagColor) -- GL=color1, UL=color2, XXL=5
PLAN = [
    ('GL IV',         'GL_IV.txt',         1),
    ('UL IV',         'UL_IV.txt',         2),
    ('XXL',           'XXL.txt',           5),
    # 'Transfer' REMOVED 2026-09-07: this script is add-only and has NO keeper gate. The
    # irreversible pile goes ONLY through preflight_transfer.py -> prune_tags.py --atomic.
    ('Hundo',         'Hundo.txt',         1),
    ('Nundo',         'Nundo.txt',         2),
    ('Event',         'Event.txt',         4),
    # 'Best Buddy' REMOVED 2026-09-07: the axis was retired 2026-06-08 and its tagset file no
    # longer exists; a bare run was dying on FileNotFoundError instead of running.
    ('Traded by E+F', 'Traded_by_E+F.txt', 7),
    ('Legacy Moves',  'Legacy_Moves.txt',  3),
]
# DROPPED 2026-05-29: 1 GL Meta / 1 UL Meta / 1 GL Least Bad / 1 UL Least Bad
# (species-tier "meta" concept removed); 2 Mega (earlier). Delete these from the
# server with safe_nuke_tags.py before applying.


def main():
    only = set(a for a in sys.argv[1:])     # optional: limit to these tag names
    plan, alluids = [], set()
    for name, f, color in PLAN:
        if only and name not in only:
            continue
        uids = [u.strip() for u in open(os.path.join(TD, f)).read().split() if u.strip()]
        plan.append((name, color, uids)); alluids.update(uids)
    print(f'{len(plan)} tags, {len(alluids)} unique uids to resolve')

    # 2026-09-07 PILE GATE. apply_members is a UNION (add-only, cannot self-correct), this script
    # writes the DB mirror directly (a mistaken run makes the DB agree with the phone, erasing the
    # drift), and it has no --dry-run. It must never be able to name the release pile. The sanctioned
    # path is preflight_transfer.py (writes system/analysis/preflight_stamp.json) -> prune_tags.py
    # --atomic (refuses without a fresh, matching stamp). Checked before pg.get_session() so a refusal
    # never costs a Frida attach.
    for name, _c, _u in plan:
        if tag_ops.is_pile_tag(name):
            sys.exit("REFUSING: '%s' is the irreversible release pile. Push it with the sanctioned "
                     "path (preflight_transfer.py -> prune_tags.py --atomic), which verifies the "
                     "pre-flight stamp. This script is add-only and has no keeper gate." % name)
    for name in only:
        if tag_ops.is_pile_tag(name):
            sys.exit("REFUSING: '%s' is the irreversible release pile and is not in this script's "
                     "PLAN. Use preflight_transfer.py -> prune_tags.py --atomic." % name)

    if not plan:
        sys.exit('nothing to apply: no PLAN tag matched %r -- refusing to attach for an empty plan' % sorted(only))

    sess, pid = pg.get_session(); print('attached pid', pid)
    try:                                   # 2026-05-29 pre-flight: foreground/screen/freezer/tag-svc
        from ready_gate import ensure_ready_for_writes, NotReadyForWrites
        ensure_ready_for_writes(sess, pid)
    except NotReadyForWrites:
        raise                              # device genuinely not write-ready -> abort cleanly
    except Exception as _e:
        print(f'[ready_gate] skipped (gate error, proceeding): {_e}')
    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        uid_decs = sorted({str(int(u, 16)) for u in alluids})
        proto_map = pg.find_protos_for_uids(sess, bag, uid_decs)
        print(f'bag-walk: {len(proto_map)}/{len(uid_decs)} protos resolved')

        bt = tag_ops._load_bulk_tag_script(sess)
        try:
            tag_ops.ensure_ready(sess, svc, bt)
            for name, color, uids in plan:
                tagproto = tag_ops.create_tag(bt, svc, name, color)
                protos = [proto_map[str(int(u, 16))] for u in uids
                          if str(int(u, 16)) in proto_map]
                applied = tag_ops.apply_members(bt, svc, tagproto, protos)
                got = [u for u in uids if str(int(u, 16)) in proto_map]
                tag_ops._mirror_db(name, got)
                miss = len(uids) - len(got)
                print(f'  {name:<16} applied {applied}/{len(uids)}'
                      + (f'  ({miss} uids not in bag)' if miss else ''))
        finally:
            bt.unload()
    finally:
        sess.detach()
    print('done.')


if __name__ == '__main__':
    main()
