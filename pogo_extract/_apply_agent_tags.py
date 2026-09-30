"""Apply the 20 tag membership files produced by the 20 agents.

Reads rescan_report/agent_tags/*.json (each contains {name, color, uids, count, rule}).
Single Frida session: for each tag, find-existing or AddTag once, bag-walk union for
all UIDs, bulkTagMany per tag. No retries that pile up duplicates — if an AddTag
fails its find verification, that tag is skipped with a clear message.

Preserves the existing 'Best Buddy' tag (already on server with 17 members).
"""
import json, os, sqlite3, sys, time, shutil
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')
AGENT_DIR = os.path.join(HERE, 'rescan_report', 'agent_tags')

# Order matches the agent dispatch (matters only for color cycling)
TAG_FILES = [
    'Hundos.json', 'Nundos.json', '0-15-15.json',
    'Lucky.json', 'Shiny.json', 'Shadow.json', 'Purified.json',
    'Legendary.json', 'Mythical.json', 'Hatched.json', 'Traded.json',
    'Background.json', 'JUMBO.json', 'Adventure Eff.json',
    'From Ethan.json', 'From Florandez.json', 'Legacy.json',
    'Dynamax.json', 'Gigantamax.json', 'GL.json',
]


def _uid_dec(uid_hex):
    return str(int(uid_hex, 16))


def _to_hex(u):
    """Normalize a UID to 16-char unsigned-hex form. Accepts:
       - 16-char hex string (e.g. '003d54f7963988c0')
       - decimal string (signed or unsigned)
       - Python int (signed or unsigned)
    """
    if isinstance(u, int):
        return f'{u & 0xFFFFFFFFFFFFFFFF:016x}'
    if isinstance(u, str):
        s = u.strip()
        if s.lstrip('-').isdigit():
            return f'{int(s) & 0xFFFFFFFFFFFFFFFF:016x}'
        return s.lower()
    raise TypeError(f'unsupported uid type: {type(u).__name__}')


def main():
    # Load all 20 tag files
    plans = []
    total_uids = 0
    for fname in TAG_FILES:
        path = os.path.join(AGENT_DIR, fname)
        if not os.path.exists(path):
            print(f'  ! missing: {fname}')
            continue
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        plans.append(data)
        total_uids += data['count']
        print(f"  {data['name']:<16} color={data['color']}  n={data['count']:>5}")
    print(f'\n  Total tag-uid pairs: {total_uids}')

    # Union of all UIDs (handle both hex and signed-int forms in JSON)
    all_uids_hex = set()
    for plan in plans:
        for u in plan['uids']:
            all_uids_hex.add(_to_hex(u))
    all_uids_dec = sorted({str(int(u, 16)) for u in all_uids_hex})
    print(f'  Distinct UIDs to resolve via bag-walk: {len(all_uids_dec)}')

    # Snapshot
    stamp = time.strftime('%Y-%m-%d_%H%M%S')
    snap = os.path.join(HERE, '.db_snapshots', f'pokemon.db.{stamp}.pre_apply20.bak')
    os.makedirs(os.path.dirname(snap), exist_ok=True)
    shutil.copy2(DB, snap)
    print(f'\nSnapshot: {snap}')

    # Frida session
    print('\nAttaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')

    try:
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        print(f'  bag @ {bag}\n  svc @ {svc}')

        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        # Bag-walk for union
        t0 = time.time()
        proto_map = pg.find_protos_for_uids(sess, bag, all_uids_dec)
        print(f'  bag-walk resolved {len(proto_map)}/{len(all_uids_dec)} protos in {time.time()-t0:.2f}s')

        # For each tag: find-existing-or-add (no retries — single shot)
        print(f'\n=== Creating {len(plans)} tags ===')
        tag_protos = {}
        for plan in plans:
            name = plan['name']
            # Find-first: if it exists (e.g., 'Best Buddy' shouldn't be in our list but defensive),
            # reuse. Otherwise, AddTag once.
            ftid = bt.exports_sync.find_tag_id_by_name(svc, name)
            if ftid.get('ok'):
                tag_protos[name] = ftid['tagProtoAddr']
                print(f"  {name:<16} EXISTS @ {ftid['tagProtoAddr']}")
                continue
            res = bt.exports_sync.add_tag_on_instance(svc, name, plan['color'])
            time.sleep(1.8)
            ftid2 = bt.exports_sync.find_tag_id_by_name(svc, name)
            if ftid2.get('ok'):
                tag_protos[name] = ftid2['tagProtoAddr']
                print(f"  {name:<16} CREATED @ {ftid2['tagProtoAddr']}")
            else:
                print(f"  ! {name!r} not findable after AddTag — skipping membership for this tag")

        # Apply membership
        print(f'\n=== Applying membership ===')
        applied_summary = {}
        for plan in plans:
            name = plan['name']
            if name not in tag_protos:
                applied_summary[name] = (0, plan['count'])
                continue
            tagproto = tag_protos[name]
            uids_hex = [_to_hex(u) for u in plan['uids']]
            protos = [proto_map.get(_uid_dec(u)) for u in uids_hex]
            pairs = [(u, p) for u, p in zip(uids_hex, protos) if p is not None]
            valid_uids = [u for u, _ in pairs]
            valid_protos = [p for _, p in pairs]

            if not valid_protos:
                applied_summary[name] = (0, plan['count'])
                print(f"  {name:<16} 0/0 (no protos)")
                continue

            print(f"  {name:<16} {len(valid_protos):>5} members...")
            done = []
            BATCH = 100
            i = 0
            while i < len(valid_protos):
                cu = valid_uids[i:i+BATCH]; cp = valid_protos[i:i+BATCH]
                res = bt.exports_sync.bulk_tag_many(svc, tagproto, cp)
                if res.get('ok') and res.get('built', 0) == len(cp):
                    done.extend(cu)
                else:
                    print(f"    ! batch {i}: {res}")
                i += BATCH
                if i < len(valid_protos): time.sleep(0.5)
            applied_summary[name] = (len(done), plan['count'])

            # Mirror DB inline so progress isn't lost
            cnx = sqlite3.connect(DB); cur = cnx.cursor()
            for uh in done:
                row = cur.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
                tags = [t for t in (row[0] or '').split(';') if t]
                if name not in tags: tags.append(name)
                cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                            (';'.join(tags), uh))
            cnx.commit(); cnx.close()

        bt.unload()
    finally:
        sess.detach()

    print(f'\n=== Summary ===')
    for name, (done, target) in applied_summary.items():
        marker = ' OK' if done == target else ' !!'
        print(f"  {marker} {name:<16} {done}/{target}")


if __name__ == '__main__':
    main()
