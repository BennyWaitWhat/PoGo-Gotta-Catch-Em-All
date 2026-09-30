"""Apply tag-drift fixes across multiple server tags in one Frida session.

For each configured tag, compute the (to-tag, to-untag) deltas vs the current
bag DB and apply them via the bag-walk proto-resolution path (NOT
index_pokemon — per LRN-20260521-003).

Tag config — rules verified 2026-05-27 against the live game and audit_tags.py:
  Nundos         is_zero=1 AND pokemon_id!=0          (pid=0 = empty slot ghosts)
  Hundos         iv_total=45
  JUMBO          pokemon_size_category=5              (5=XXL in PoGo's enum)
  Adventure Eff  adventure_effects_left>0             (NOT fresh_pokemon_badge!=0; column-bug)
  GL             gl_rank=1                            (per-(species,form), not global)
  UL             ul_rank=1                            (same)

Ordered smallest-first to validate the mechanism before the big batches.

Usage:
  python _tag_drift_fix.py [--dry-run] [--tags TAG1,TAG2,...]
"""
import argparse, os, sqlite3, sys, time

import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')

# (tag_name, where_clause). Order: smallest deltas first.
TAG_CONFIGS = [
    ('Nundos',         'is_zero=1 AND pokemon_id!=0'),
    ('Hundos',         'iv_total=45'),
    ('JUMBO',          'pokemon_size_category=5'),
    ('From Ethan',     "(is_traded_flag_v2=1 OR is_lucky=1) AND lower(original_owner_name)='ethanmateovz'"),
    ('From Florandez', "(is_traded_flag_v2=1 OR is_lucky=1) AND lower(original_owner_name)='florandez'"),
    ('Adventure Eff',  'adventure_effects_left>0'),
    ('GL',             'gl_rank=1'),
    ('UL',             'ul_rank=1'),
]

BATCH_SIZE = 100   # bulkTagMany chunk; pipeline uses 100 with backoff
BATCH_DELAY = 0.6  # seconds between consecutive batches
UNTAG_DELAY = 0.35


def _uid_dec(uid_hex):
    return str(int(uid_hex, 16))


def compute_deltas(conn, tag_filter=None):
    plans = []
    for name, where in TAG_CONFIGS:
        if tag_filter and name not in tag_filter:
            continue
        expected = {r[0] for r in conn.execute(
            f"SELECT uid_hex FROM pokemon WHERE in_bag=1 AND ({where})"
        )}
        tagged = {uh for uh, txt in conn.execute(
            "SELECT uid_hex, auth_tag_names FROM pokemon "
            "WHERE in_bag=1 AND auth_tag_names LIKE ?",
            ('%' + name + '%',)
        ) if name in (txt or '').split(';')}
        plans.append({
            'tag': name, 'rule': where,
            'to_tag': sorted(expected - tagged),
            'to_untag': sorted(tagged - expected),
            'expected_count': len(expected),
            'tagged_count': len(tagged),
        })
    return plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--tags', default='', help='comma-separated subset of tag names')
    args = ap.parse_args()

    tag_filter = {t.strip() for t in args.tags.split(',') if t.strip()} or None

    # 1. plan from current DB state
    conn_ro = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    plans = compute_deltas(conn_ro, tag_filter)
    conn_ro.close()

    print(f"=== Plan ===")
    total_tag = total_untag = 0
    all_uids_dec = set()
    for p in plans:
        total_tag += len(p['to_tag'])
        total_untag += len(p['to_untag'])
        print(f"  {p['tag']:<16} expected={p['expected_count']:>4} "
              f"tagged={p['tagged_count']:>4} -> TAG {len(p['to_tag']):>3} "
              f"UNTAG {len(p['to_untag']):>3}")
        for uh in p['to_tag']:    all_uids_dec.add(_uid_dec(uh))
        for uh in p['to_untag']:  all_uids_dec.add(_uid_dec(uh))
    print(f"  --")
    print(f"  TOTAL: {total_tag} tag, {total_untag} untag "
          f"({len(all_uids_dec)} distinct UIDs to resolve via bag-walk)")

    if args.dry_run:
        print("\n(--dry-run; no server writes)")
        return
    if total_tag == 0 and total_untag == 0:
        print("Nothing to do.")
        return

    # 2. attach + singletons + single bag-walk for everything
    print(f"\n=== Attach + bag-walk ===")
    sess, pid = pg.get_session()
    print(f"  pid={pid}")

    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f"  bag @ {bag}")
        print(f"  svc @ {svc}")

        t0 = time.time()
        proto_map = pg.find_protos_for_uids(sess, bag, sorted(all_uids_dec))
        print(f"  bag-walk resolved {len(proto_map)}/{len(all_uids_dec)} protos in {time.time()-t0:.2f}s")
        missing = sorted(set(all_uids_dec) - set(proto_map.keys()))
        if missing:
            print(f"  ! {len(missing)} uids unresolved (will skip): {missing[:5]}"
                  + ('...' if len(missing)>5 else ''))

        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        # 3. per-tag: find tag proto -> untag -> tag (batched)
        results = {}
        for p in plans:
            tag_name = p['tag']
            print(f"\n=== {tag_name} ===  TAG {len(p['to_tag'])} / UNTAG {len(p['to_untag'])}")
            r = {'tagged': [], 'untagged': [], 'errors': []}

            ftid = bt.exports_sync.find_tag_id_by_name(svc, tag_name)
            if not ftid.get('ok'):
                print(f"  ! tag {tag_name!r} not found on server: {ftid}")
                r['errors'].append(f'tag_not_found:{ftid}')
                results[tag_name] = r
                continue
            tag_proto = ftid['tagProtoAddr']

            # untag first
            for uh in p['to_untag']:
                pp = proto_map.get(_uid_dec(uh))
                if pp is None:
                    print(f"  SKIP UNTAG {uh}: no proto")
                    continue
                res = bt.exports_sync.bulk_untag_one(svc, pp, tag_proto)
                if res.get('ok'):
                    r['untagged'].append(uh)
                else:
                    print(f"  ! UNTAG {uh} failed: {res}")
                    r['errors'].append(f'untag {uh}: {res}')
                time.sleep(UNTAG_DELAY)
            if p['to_untag']:
                print(f"  untagged: {len(r['untagged'])}/{len(p['to_untag'])}")

            # batched tag
            uids = [uh for uh in p['to_tag'] if proto_map.get(_uid_dec(uh)) is not None]
            protos = [proto_map[_uid_dec(uh)] for uh in uids]
            i = 0
            while i < len(protos):
                chunk_uids = uids[i:i+BATCH_SIZE]
                chunk_protos = protos[i:i+BATCH_SIZE]
                res = bt.exports_sync.bulk_tag_many(svc, tag_proto, chunk_protos)
                ok = res.get('ok')
                built = res.get('built', 0)
                if ok and built == len(chunk_protos):
                    r['tagged'].extend(chunk_uids)
                    print(f"  TAG {i}-{i+len(chunk_protos)}: ok built={built}")
                elif ok:
                    print(f"  ! TAG {i}-{i+len(chunk_protos)} partial built={built}/{len(chunk_protos)} — DB not mirrored for this batch")
                    r['errors'].append(f'partial_build {i}: {built}/{len(chunk_protos)}')
                else:
                    print(f"  ! TAG {i}-{i+len(chunk_protos)} FAILED: {res}")
                    r['errors'].append(f'tag_batch {i}: {res}')
                i += BATCH_SIZE
                if i < len(protos):
                    time.sleep(BATCH_DELAY)
            if p['to_tag']:
                print(f"  tagged:   {len(r['tagged'])}/{len(p['to_tag'])}")

            results[tag_name] = r

        bt.unload()
    finally:
        sess.detach()

    # 4. mirror to local DB
    print(f"\n=== Updating local DB auth_tag_names ===")
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    for tag_name, r in results.items():
        for uh in r['tagged']:
            cur = c.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
            tags = [t for t in (cur[0] or '').split(';') if t]
            if tag_name not in tags:
                tags.append(tag_name)
            c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                      (';'.join(tags), uh))
        for uh in r['untagged']:
            cur = c.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
            tags = [t for t in (cur[0] or '').split(';') if t and t != tag_name]
            c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                      (';'.join(tags) if tags else None, uh))
    conn.commit()
    conn.close()

    # 5. summary
    print(f"\n=== Summary ===")
    grand_t = grand_u = grand_e = 0
    for tag_name, r in results.items():
        grand_t += len(r['tagged']); grand_u += len(r['untagged']); grand_e += len(r['errors'])
        marker = '!' if r['errors'] else ' '
        print(f"  {marker} {tag_name:<16} tagged {len(r['tagged']):>3}, untagged {len(r['untagged']):>3}"
              + (f"   errors={len(r['errors'])}" if r['errors'] else ""))
        for e in r['errors'][:3]:
            print(f"      - {e}")
    print(f"  TOTAL: tagged {grand_t}, untagged {grand_u}"
          + (f", ERRORS {grand_e}" if grand_e else ""))


if __name__ == '__main__':
    main()
