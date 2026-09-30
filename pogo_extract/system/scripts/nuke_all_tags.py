"""nuke_all_tags.py -- delete EVERY server tag (clean-slate rebuild), then verify
in a FRESH re-attached session (the cache lags deletes, so same-session re-enum
is unreliable -- only a fresh attach reflects true server state).

Collateral-safe: reads ALL (name, tagId) in ONE enumeration up front. tagId is a
stable uint64 VALUE (copied), so deleting by cached id never re-reads a tagProto
pointer -- this avoids the list-reorg pointer-reuse bug that once emptied Costume
and deleted Mega (see safe_nuke_tags.py header).

Optionally clears pokemon.db auth_tag_names so apply_tagsets.py can repopulate
the surviving tag set from the verified files.

Usage:
  python nuke_all_tags.py --dry-run        # enumerate + plan only
  python nuke_all_tags.py                   # delete all server tags
  python nuke_all_tags.py --clear-db        # also NULL auth_tag_names (in_bag)
"""
import sys, os, time, argparse, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
import pogo_il2cpp as pg

DB = os.path.join(ROOT, 'pokemon.db')

JS = r"""
function enumTagsFull(s) {
    _ensureInit();
    var cl = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
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
        var ib = Memory.alloc(4); ib.writeS32(i);
        var ar = Memory.alloc(Process.pointerSize); ar.writePointer(ib);
        var bp = rI(gb, svc, ar, null);
        if (bp.isNull()) continue;
        var tp = bp.add(0x10).readPointer();
        var nm = '';
        try {
            var ns = tp.add(0x40).readPointer();
            var ln = ns.add(0x10).readS32();
            if (ln > 0 && ln < 100) { var ch = [];
                for (var ci = 0; ci < ln; ci++) ch.push(String.fromCharCode(ns.add(0x14 + ci * 2).readU16()));
                nm = ch.join(''); }
        } catch (e) {}
        var tid = '0';
        try { tid = tp.add(0x38).readU64().toString(); } catch (e) {}
        var mc = 0;
        try { var pl = bp.add(0x18).readPointer(); if (!pl.isNull()) mc = pl.add(0x18).readS32(); } catch (e) {}
        out.push({name: nm, tagId: tid, memberCount: mc});
    }
    return out;
}
function delTag(s, tidStr) {
    _ensureInit();
    var cl = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var m, dm = null;
    while ((m = IL2.cGM(cl, it)) && !m.isNull()) {
        if (IL2.mGN(m).readCString() === 'DeleteTag') { dm = m; break; }
    }
    if (!dm) return {ok: false, err: 'no DeleteTag'};
    var idBuf = Memory.alloc(8); idBuf.writeU64(uint64(tidStr));
    var args = Memory.alloc(Process.pointerSize); args.writePointer(idBuf);
    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
    rI(dm, ptr(s), args, exc);
    if (!exc.readPointer().isNull()) return {ok: false, err: 'DeleteTag threw'};
    return {ok: true};
}
rpc.exports.enumTagsFull = enumTagsFull;
rpc.exports.delTag = delTag;
"""


def enumerate_tags(sess):
    svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
    sc = pg.get_script_with_helpers(sess, JS)
    tags = sc.exports_sync.enum_tags_full(svc)
    return svc, sc, tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--clear-db', action='store_true')
    args = ap.parse_args()

    sess, pid = pg.get_session(); print(f'attached pid {pid}')
    svc, sc, tags = enumerate_tags(sess)
    print(f'\nBefore: {len(tags)} server tags')
    for t in sorted(tags, key=lambda x: x['name']):
        print(f"  {t['name']:30s} id={t['tagId']:>22s} members={t['memberCount']}")
    ids = [(t['name'], t['tagId']) for t in tags]      # cache stable ids up front

    if args.dry_run:
        print(f'\n[DRY RUN] would delete {len(ids)} tags. No changes.')
        sess.detach(); return

    try:                                   # 2026-05-30: DeleteTag silently no-ops unless foregrounded
        sys.path.insert(0, HERE)
        from ready_gate import ensure_ready_for_writes, NotReadyForWrites
        ensure_ready_for_writes(sess, pid)
    except NotReadyForWrites:
        sess.detach(); raise               # device genuinely not write-ready -> abort cleanly
    except Exception as _e:
        print(f'[ready_gate] skipped (gate error, proceeding): {_e}')

    print(f'\nDeleting {len(ids)} tags (by cached id, no pointer re-read)...')
    for name, tid in ids:
        try:
            r = sc.exports_sync.del_tag(svc, tid)
            print(f"  DeleteTag {name:30s} -> {r}")
        except Exception as e:
            print(f"  DeleteTag {name:30s} -> EXC {e}")
        time.sleep(0.4)
    time.sleep(3.0)
    sess.detach()

    # authoritative verify in a FRESH session (cache-lag immune)
    print('\nRe-attaching fresh to verify...')
    sess2, pid2 = pg.get_session()
    _, _, after = enumerate_tags(sess2)
    sess2.detach()
    print(f'After (fresh session): {len(after)} tags remain')
    for t in sorted(after, key=lambda x: x['name']):
        print(f"  STILL PRESENT: {t['name']} (members={t['memberCount']})")
    if not after:
        print('  -> server is clean (0 tags).')

    if args.clear_db:
        c = sqlite3.connect(DB)
        n = c.execute("UPDATE pokemon SET auth_tag_names=NULL WHERE in_bag=1 AND auth_tag_names IS NOT NULL").rowcount
        c.commit(); c.close()
        print(f'\nCleared DB auth_tag_names on {n} in_bag rows.')
    print('done.')


if __name__ == '__main__':
    main()
