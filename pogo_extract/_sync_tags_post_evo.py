"""Reconcile every tag against the now-fresh DB after evolution.

For each of the 21 tags, derive the expected UID set from primary rules
(JUMBO uses top-2-per-species by weight UNION height), compare to what's
on the server, then add/remove the diff. Single Frida session.

Cleanly handles:
  - new catches that need to be added to Shiny/Hundos/whatever
  - evolved specimens (new UID) that should pick up Shiny/JUMBO from parent
  - JUMBO top-2 prune as species composition shifts
  - dead bindings on server (transferred/evolved old UIDs) – tracked but
    can't be untagged because the proto is no longer in the live bag.
"""
import json, os, sqlite3, time
from collections import defaultdict
import pogo_il2cpp as pg

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'pokemon.db')
BULK_TAG_JS = os.path.join(HERE, 'bulk_tag.js')
LEGACY_JSON = os.path.join(HERE, 'legacy_accurate.json')

# Rule per tag. None ⇒ special handling.
TAG_RULES = {
    'Best Buddy':     "was_best_buddy_badge=1",
    'Hundos':         "iv_total=45",
    'Nundos':         "is_zero=1 AND pokemon_id!=0",
    '0-15-15':        "iv_atk=0 AND iv_def=15 AND iv_sta=15",
    'Lucky':          "is_lucky=1",
    'Shiny':          "fresh_shiny=1",
    'Shadow':         "fresh_alignment=1",
    'Purified':       "fresh_alignment=2",
    'Legendary':      "is_legendary=1",
    'Mythical':       "is_mythical=1",
    'Hatched':        "hatched_from_egg=1",
    'Traded':         "(is_traded=1 OR is_traded_flag_v2=1)",
    'Background':     "fresh_has_location_card=1",
    'JUMBO':          None,   # top-2 per species (weight ∪ height)
    'Adventure Eff':  "adventure_effects_left>0",
    'From Ethan':     "(is_traded_flag_v2=1 OR is_lucky=1) AND lower(original_owner_name)='ethanmateovz'",
    'From Florandez': "(is_traded_flag_v2=1 OR is_lucky=1) AND lower(original_owner_name)='florandez'",
    'Legacy':         None,   # legacy_accurate.json ∩ in_bag=1
    'Dynamax':        "fresh_bread_mode=1",
    'Gigantamax':     "fresh_bread_mode=2",
    'GL':             "gl_rank=1",
}

ENUM_JS = r"""
function enumerateTagsWithBindings(svcAddrStr) {
    _ensureInit();
    var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m, gnt = null, gctb = null;
    while ((m = IL2.cGM(svcCls, iter)) && !m.isNull()) {
        var nm = IL2.mGN(m).readCString();
        if (nm === 'get_NumberOfTags') gnt = m;
        if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
    }
    var svc = ptr(svcAddrStr);
    var ret = rI(gnt, svc, ptr(0), null);
    var totalTags = ret.add(0x10).readS32();
    var out = [];
    for (var i = 0; i < totalTags; i++) {
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var bp = rI(gctb, svc, args, null);
        if (bp.isNull()) continue;
        var tagProto = bp.add(0x10).readPointer();
        var name = '';
        try {
            var ns = tagProto.add(0x40).readPointer();
            if (!ns.isNull()) {
                var len = ns.add(0x10).readS32();
                if (len > 0 && len < 100) {
                    var chars = [];
                    for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                    name = chars.join('');
                }
            }
        } catch(e) {}
        // The binding holds a List<PokemonProto*>. Walk it and read each
        // entry's PokemonProto.id (UInt64 at +0x18 within PokemonProto).
        var uids = [];
        try {
            var lst = bp.add(0x18).readPointer();
            if (!lst.isNull()) {
                var arr = lst.add(0x10).readPointer();
                var count = lst.add(0x18).readS32();
                if (count > 0 && count < 5000) {
                    for (var k = 0; k < count; k++) {
                        var protoPtr = arr.add(0x20 + k * Process.pointerSize).readPointer();
                        if (!protoPtr.isNull()) {
                            try {
                                var uid = protoPtr.add(0x18).readU64();
                                uids.push(uid.toString());
                            } catch(e) {}
                        }
                    }
                }
            }
        } catch(e) {}
        out.push({name:name, tagProto:tagProto.toString(), uids:uids});
    }
    return out;
}
rpc.exports.enumerateTagsWithBindings = enumerateTagsWithBindings;
"""


def derive_expected(conn):
    expected = {}
    # All SQL rules
    for name, rule in TAG_RULES.items():
        if rule is None: continue
        rows = conn.execute(
            f"SELECT uid_hex FROM pokemon WHERE in_bag=1 AND ({rule})"
        ).fetchall()
        expected[name] = {r[0] for r in rows}
    # Legacy
    try:
        with open(LEGACY_JSON, encoding='utf-8') as f:
            legacy = json.load(f)
        leg = {e['uid_hex'] for e in legacy}
        inbag = {r[0] for r in conn.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1")}
        expected['Legacy'] = leg & inbag
    except FileNotFoundError:
        expected['Legacy'] = set()
    # JUMBO: top-2 per species (weight ∪ height)
    xxl = conn.execute(
        "SELECT uid_hex, pokemon_id, form, weight_kg, height_m "
        "FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5"
    ).fetchall()
    by_sp = defaultdict(list)
    for r in xxl:
        by_sp[(r[1], r[2] or 0)].append(r)
    keep = set()
    for sp_key, rows in by_sp.items():
        rs_w = sorted(rows, key=lambda r: r[3], reverse=True)[:2]
        rs_h = sorted(rows, key=lambda r: r[4], reverse=True)[:2]
        for r in rs_w + rs_h:
            keep.add(r[0])
    expected['JUMBO'] = keep
    return expected


def main():
    print('Reading DB and computing expected per-tag membership...')
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    expected = derive_expected(conn)
    conn.close()

    print('\nExpected per-tag size:')
    for name in TAG_RULES:
        print(f'  {name:<16} {len(expected[name]):>5}')

    print('\nAttaching...')
    sess, pid = pg.get_session()
    print(f'  pid={pid}')

    try:
        svc = pg.pick_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
        bag = pg.pick_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
        print(f'  svc @ {svc}\n  bag @ {bag}')

        enum = pg.get_script_with_helpers(sess, ENUM_JS)
        srv = enum.exports_sync.enumerate_tags_with_bindings(svc)
        enum.unload()

        # Convert server UIDs (signed dec str) -> unsigned hex
        srv_by_name = {}
        for t in srv:
            uids_hex = set()
            for u in t['uids']:
                v = int(u) & 0xFFFFFFFFFFFFFFFF
                uids_hex.add(f'{v:016x}')
            srv_by_name[t['name']] = {'tagProto': t['tagProto'], 'uids': uids_hex}

        # Compute diffs
        diffs = {}
        for name, exp_uids in expected.items():
            if name not in srv_by_name:
                print(f'  ! tag {name!r} missing on server')
                continue
            srv_uids = srv_by_name[name]['uids']
            to_add = exp_uids - srv_uids
            to_rm = srv_uids - exp_uids
            diffs[name] = (to_add, to_rm)
            if to_add or to_rm:
                print(f'  {name:<16} +{len(to_add)}  -{len(to_rm)}')

        if not any(d[0] or d[1] for d in diffs.values()):
            print('\nAll tags already in sync. Nothing to do.')
            return

        # Bag-walk every UID we need to touch
        all_touch = set()
        for to_add, to_rm in diffs.values():
            all_touch |= to_add | to_rm
        all_dec = sorted({str(int(u, 16)) for u in all_touch})
        print(f'\nBag-walking {len(all_dec)} UIDs to touch...')
        proto_map = pg.find_protos_for_uids(sess, bag, all_dec)
        print(f'  resolved {len(proto_map)}/{len(all_dec)}')

        bt = sess.create_script(open(BULK_TAG_JS, encoding='utf-8').read())
        bt.on('message', lambda m, d: None)
        bt.load()
        bt.exports_sync.init_status()

        # Apply diffs
        net_added = 0
        net_removed = 0
        dead_skip = 0
        for name, (to_add, to_rm) in diffs.items():
            if not (to_add or to_rm): continue
            tagproto = srv_by_name[name]['tagProto']
            # Adds
            if to_add:
                pairs = []
                for u in to_add:
                    p = proto_map.get(str(int(u, 16)))
                    if p: pairs.append((u, p))
                    else: dead_skip += 1
                if pairs:
                    BATCH = 25
                    added = 0
                    for i in range(0, len(pairs), BATCH):
                        cu = [u for u, _ in pairs[i:i+BATCH]]
                        cp = [p for _, p in pairs[i:i+BATCH]]
                        res = bt.exports_sync.bulk_tag_many(svc, tagproto, cp)
                        if res.get('ok') and res.get('built', 0) == len(cp):
                            added += len(cu)
                            # DB mirror inline
                            cnx = sqlite3.connect(DB); cur = cnx.cursor()
                            for uh in cu:
                                row = cur.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
                                tags = [t for t in ((row[0] if row else None) or '').split(';') if t]
                                if name not in tags: tags.append(name)
                                cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                                            (';'.join(tags), uh))
                            cnx.commit(); cnx.close()
                        else:
                            print(f'    ! {name} add batch {i}: {res}')
                        time.sleep(0.3)
                    print(f'  {name:<16} added {added}/{len(to_add)}')
                    net_added += added
            # Removes
            if to_rm:
                removed = 0
                for u in to_rm:
                    p = proto_map.get(str(int(u, 16)))
                    if not p:
                        dead_skip += 1
                        continue
                    res = bt.exports_sync.bulk_untag_one(svc, p, tagproto)
                    if res.get('ok'):
                        removed += 1
                        cnx = sqlite3.connect(DB); cur = cnx.cursor()
                        row = cur.execute("SELECT auth_tag_names FROM pokemon WHERE uid_hex=?", (u,)).fetchone()
                        tags = [t for t in ((row[0] if row else None) or '').split(';') if t and t != name]
                        cur.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?",
                                    (';'.join(tags) if tags else None, u))
                        cnx.commit(); cnx.close()
                    else:
                        print(f'    ! {name} remove {u}: {res}')
                    time.sleep(0.3)
                print(f'  {name:<16} removed {removed}/{len(to_rm)}')
                net_removed += removed

        bt.unload()
        print(f'\nTotal: +{net_added}  -{net_removed}  (skipped {dead_skip} dead UIDs not in live bag)')
    finally:
        sess.detach()


if __name__ == '__main__':
    main()
