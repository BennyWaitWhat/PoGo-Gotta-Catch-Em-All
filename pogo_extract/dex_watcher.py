"""Watch Pokedex deltas by hooking NianticInventoryCache.HandleInventoryDelta.

Hooks the per-RPC inventory ingest path. The platform-side InventoryItemProto
holds wire bytes (ByteString), so rather than re-parse the wire, we observe the
decoded result: snapshot PokedexImpl state on onEnter, snapshot again on
onLeave, diff to emit per-(pid, category) events.

Captures: catches, evolves, purifies, trades, hatches, raid awards, AR scans -
anything that touches the dex via inventory delta apply.

Schema:
    CREATE TABLE dex_events (
        ts_ms INTEGER,
        pokemon_id INTEGER,
        category TEXT,
        encountered INTEGER,
        acquired INTEGER,
        delta TEXT  -- 'new_encounter' | 'new_acquisition' | 'rollback'
    );

Usage: python dex_watcher.py [seconds]
"""
import frida
import json
import sqlite3
import sys
import time
import pogo_il2cpp as pg

DB_PATH = 'dex_events.db'
DEFAULT_DURATION_S = 60


JS = r"""
// PokedexImpl holds 10 Dictionary<int, PokedexEntryProto> at +0x10..+0x58.
// PokedexEntryProto layout (from research_pokedex_inv_types.json):
//   +0x10 PokedexEntryNumber  i32
//   +0x14 TimesEncountered    i32
//   +0x18 TimesCaptured       i32
//   +0x40 CapturedShiny       u8
//   +0x60 EncounteredShiny    u8
//   +0x64 TimesLuckyReceived  i32
//   +0x68 TimesPurified       i32
//   +0x80 CategoryStatus      MapField<string, PokedexCategoryStatus>
//   +0xb8 LastCaptureTimestampMs u64
//
// MapField<TK,TV> layout (Niantic.Protobuf.Collections):
//   +0x18 LinkedList<KeyValuePair<TK,TV>>
// LinkedList: +0x10 head node, +0x18 count
// Node: +0x18 next, +0x28 (or +0x30) value object (KeyValuePair)
//
// We need only the acquired-bit per category for diffing.

function readPokedexEntry(pep) {
    if (!pep || pep.isNull()) return null;
    var entry = {
        pid: pep.add(0x10).readS32(),
        enc: pep.add(0x14).readS32(),
        cap: pep.add(0x18).readS32(),
        shiny: pep.add(0x40).readU8(),
        encShiny: pep.add(0x60).readU8(),
        lucky: pep.add(0x64).readS32(),
        purified: pep.add(0x68).readS32(),
        cats: {}  // catEnum -> {enc:0/1, acq:0/1}
    };
    try {
        var mf = pep.add(0x80).readPointer();
        if (!mf.isNull()) {
            var list = mf.add(0x18).readPointer();
            if (!list.isNull()) {
                var head = list.add(0x10).readPointer();
                var count = list.add(0x18).readS32();
                var node = head, i = 0;
                while (node && !node.isNull() && i < count + 5) {
                    try {
                        var kvp = node.add(0x30).readPointer();
                        if (!kvp.isNull()) {
                            // PokedexCategoryStatus layout (from CategoryStatus walk in prior research):
                            //   +0x10 Category enum i32
                            //   +0x14 Encountered u8
                            //   +0x15 Acquired u8
                            var catEnum = kvp.add(0x10).readS32();
                            var encB = kvp.add(0x14).readU8();
                            var acqB = kvp.add(0x15).readU8();
                            entry.cats[catEnum] = {enc: encB, acq: acqB};
                        }
                        var nxt = node.add(0x18).readPointer();
                        if (nxt.isNull() || nxt.equals(head)) break;
                        node = nxt;
                    } catch(e) { break; }
                    i++;
                }
            }
        }
    } catch(e) {}
    return entry;
}

function snapshotPokedex(pdexPtr) {
    var inst = ptr(pdexPtr);
    var offsets = [0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40, 0x48, 0x50, 0x58];
    var byPid = {};
    for (var di = 0; di < offsets.length; di++) {
        var dp = inst.add(offsets[di]).readPointer();
        if (dp.isNull()) continue;
        var entries = dp.add(0x18).readPointer();
        if (entries.isNull()) continue;
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var key = ep.add(8).readS32();
            var valPtr = ep.add(16).readPointer();
            if (valPtr.isNull()) continue;
            var e = readPokedexEntry(valPtr);
            if (!e) continue;
            // Keep the entry with the highest cap count if duplicates show up across dicts
            var existing = byPid[e.pid];
            if (!existing || e.cap > existing.cap || (e.cap === existing.cap && e.enc > existing.enc)) {
                byPid[e.pid] = e;
            }
        }
    }
    return byPid;
}

var PDEX_PTR = null;
var HID_PTR  = null;
var inFlight = null;
var hookHandle = null;

function installHook() {
    if (hookHandle) return {ok:true, already:true};
    if (!HID_PTR || !PDEX_PTR) return {err:'pointers not set'};
    var hidNative = ptr(HID_PTR);
    hookHandle = Interceptor.attach(hidNative, {
        onEnter: function(args) {
            try {
                var snap = snapshotPokedex(PDEX_PTR);
                inFlight = {ts: Date.now(), pre: snap};
            } catch(e) { send({type:'err', where:'onEnter', msg:e.toString()}); }
        },
        onLeave: function(retval) {
            try {
                if (!inFlight) return;
                var post = snapshotPokedex(PDEX_PTR);
                var pre = inFlight.pre;
                var ts = Date.now();
                var events = [];
                // Union of pids in pre/post
                var allPids = {};
                for (var k in pre)  allPids[k] = 1;
                for (var k in post) allPids[k] = 1;
                for (var pidStr in allPids) {
                    var a = pre[pidStr];
                    var b = post[pidStr];
                    if (!b) continue;  // entries don't get deleted from dex
                    // Compare category-by-category
                    var allCats = {};
                    if (a) { for (var c in a.cats) allCats[c] = 1; }
                    for (var c in b.cats) allCats[c] = 1;
                    for (var cStr in allCats) {
                        var aCat = a ? a.cats[cStr] : null;
                        var bCat = b.cats[cStr];
                        if (!bCat) continue;
                        var encBefore = aCat ? aCat.enc : 0;
                        var acqBefore = aCat ? aCat.acq : 0;
                        var encAfter  = bCat.enc;
                        var acqAfter  = bCat.acq;
                        if (encBefore !== encAfter || acqBefore !== acqAfter) {
                            var delta = null;
                            if (acqBefore === 0 && acqAfter === 1)      delta = 'new_acquisition';
                            else if (encBefore === 0 && encAfter === 1) delta = 'new_encounter';
                            else if (acqBefore === 1 && acqAfter === 0) delta = 'rollback';
                            else if (encBefore === 1 && encAfter === 0) delta = 'rollback';
                            else                                         delta = 'change';
                            events.push({
                                ts: ts, pid: parseInt(pidStr,10), cat: parseInt(cStr,10),
                                enc: encAfter, acq: acqAfter, delta: delta
                            });
                        }
                    }
                    // Also emit a synthetic non-category event for shiny/lucky/purified/cap changes
                    if (a) {
                        if (a.cap !== b.cap || a.enc !== b.enc || a.shiny !== b.shiny || a.encShiny !== b.encShiny || a.lucky !== b.lucky || a.purified !== b.purified) {
                            send({type:'stat', ts:ts, pid:parseInt(pidStr,10),
                                  pre:{cap:a.cap,enc:a.enc,shiny:a.shiny,encShiny:a.encShiny,lucky:a.lucky,purified:a.purified},
                                  post:{cap:b.cap,enc:b.enc,shiny:b.shiny,encShiny:b.encShiny,lucky:b.lucky,purified:b.purified}});
                        }
                    } else {
                        // brand-new pid in dict
                        send({type:'stat', ts:ts, pid:parseInt(pidStr,10),
                              pre:null,
                              post:{cap:b.cap,enc:b.enc,shiny:b.shiny,encShiny:b.encShiny,lucky:b.lucky,purified:b.purified}});
                    }
                }
                if (events.length > 0) {
                    send({type:'events', events:events});
                }
                inFlight = null;
            } catch(e) {
                send({type:'err', where:'onLeave', msg:e.toString()});
                inFlight = null;
            }
        }
    });
    return {ok:true};
}

rpc.exports = {
    init: function() { _ensureInit(); return {ok:true, gameImage: GAME_IMAGE ? GAME_IMAGE.toString() : null}; },
    findSingleton: function(ns, cls) {
        var klass = cFN(ns, cls);
        if (klass.isNull()) return {err:'class not found'};
        return liveness_find_instances(klass);
    },
    setPointers: function(pdex, hid) {
        PDEX_PTR = pdex; HID_PTR = hid;
        return {pdex:pdex, hid:hid};
    },
    install: function() { return installHook(); },
    snapshot: function() {
        if (!PDEX_PTR) return {err:'no pdex'};
        return snapshotPokedex(PDEX_PTR);
    }
};
"""


def find_handle_inventory_delta_fnptr(sess):
    """Resolve InventoryCache.HandleInventoryDelta function pointer."""
    extra = r"""
function findMethod(ns, name, methodName, np) {
    _ensureInit();
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name]=e.address; });
    var cFN2 = new NativeFunction(exp['il2cpp_class_from_name'],'pointer',['pointer','pointer','pointer']);
    var cGMFN = new NativeFunction(exp['il2cpp_class_get_method_from_name'],'pointer',['pointer','pointer','int']);
    var cls = cFN2(GAME_IMAGE, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
    if (cls.isNull()) return null;
    var m = cGMFN(cls, Memory.allocUtf8String(methodName), np);
    if (m.isNull()) return null;
    return m.readPointer().toString();
}
rpc.exports.findMethod = function(ns, name, methodName, np) { return findMethod(ns, name, methodName, np); };
"""
    sc = pg.get_script_with_helpers(sess, extra)
    try:
        return sc.exports_sync.find_method('Niantic.Holoholo.Collections', 'InventoryCache', 'HandleInventoryDelta', 1)
    finally:
        sc.unload()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dex_events (
            ts_ms INTEGER,
            pokemon_id INTEGER,
            category TEXT,
            encountered INTEGER,
            acquired INTEGER,
            delta TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dex_stat_events (
            ts_ms INTEGER,
            pokemon_id INTEGER,
            pre_cap INTEGER, pre_enc INTEGER, pre_shiny INTEGER, pre_enc_shiny INTEGER, pre_lucky INTEGER, pre_purified INTEGER,
            post_cap INTEGER, post_enc INTEGER, post_shiny INTEGER, post_enc_shiny INTEGER, post_lucky INTEGER, post_purified INTEGER
        )
    """)
    conn.commit()
    return conn


# PokedexCategory enum values - from prior research, FourStar = 14
# Other key values: Default=0, Normal/Mini/Big/Huge =1..4, Shiny=5, Lucky=6, Shadow=7, Purified=8,
# Costumed=9, ThreeStar=11, FourStar=14. Full enum unknown; we'll store the raw int and tag known names.
CATEGORY_NAMES = {
    0: 'Default',
    1: 'Mini',
    2: 'Big',
    3: 'Huge',
    4: 'XL',
    5: 'Shiny',
    6: 'Lucky',
    7: 'Shadow',
    8: 'Purified',
    9: 'Costumed',
    10: 'TwoStar',
    11: 'ThreeStar',
    13: 'TempEvo',
    14: 'FourStar',
}


def category_name(c):
    return CATEGORY_NAMES.get(c, f'cat_{c}')


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DURATION_S
    conn = init_db()

    sess, pid = pg.get_session()
    print(f"PID={pid}")

    # 1. Resolve PokedexImpl - may have multiple instances (DI default + real).
    # Pick the one whose dicts contain entries.
    probe_sc = pg.get_script_with_helpers(sess)
    try:
        r = probe_sc.exports_sync.find_singleton('Niantic.Holoholo.Internal', 'PokedexImpl')
        hits = r.get('hits', [])
    finally:
        probe_sc.unload()
    if not hits:
        print("ERROR: no PokedexImpl found")
        sys.exit(1)

    def first_dict_count(sess, addr):
        sc2 = sess.create_script(r"""
rpc.exports.cnt = function(addrStr) {
    var inst = ptr(addrStr);
    var dp = inst.add(0x10).readPointer();
    if (dp.isNull()) return -1;
    return dp.add(0x20).readS32();
};
""")
        sc2.load()
        try:
            return sc2.exports_sync.cnt(addr)
        finally:
            sc2.unload()

    pdex = None
    for cand in hits:
        c = first_dict_count(sess, cand)
        print(f"  candidate {cand} first-dict count={c}")
        if c > 0:
            pdex = cand
            break
    if not pdex:
        pdex = hits[0]
    print(f"PokedexImpl: {pdex}")

    # 2. Resolve HandleInventoryDelta fn ptr
    hid = find_handle_inventory_delta_fnptr(sess)
    print(f"HandleInventoryDelta fnPtr: {hid}")
    if not hid:
        print("ERROR: could not resolve HandleInventoryDelta")
        sys.exit(1)

    # 3. Load main script with hook logic
    sc = sess.create_script(pg.JS_PREAMBLE + JS)

    captured_events = []
    captured_stats = []

    def on_msg(message, data):
        p = message.get('payload', {})
        if not isinstance(p, dict):
            return
        t = p.get('type')
        if t == 'events':
            for ev in p['events']:
                captured_events.append(ev)
                cn = category_name(ev['cat'])
                tag = ev['delta'].upper()
                ts = time.strftime('%H:%M:%S', time.localtime(ev['ts'] / 1000))
                print(f"  [{ts}] {tag:18s} pid={ev['pid']:4d}  cat={cn:12s}  enc={ev['enc']}  acq={ev['acq']}")
        elif t == 'stat':
            captured_stats.append(p)
            ts = time.strftime('%H:%M:%S', time.localtime(p['ts'] / 1000))
            pre = p.get('pre')
            post = p['post']
            if pre is None:
                print(f"  [{ts}] STAT-NEW           pid={p['pid']:4d}  cap=0->{post['cap']} enc=0->{post['enc']} shiny=0->{post['shiny']} encShiny=0->{post['encShiny']} lucky=0->{post['lucky']} pur=0->{post['purified']}")
            else:
                changes = []
                for k in ('cap','enc','shiny','encShiny','lucky','purified'):
                    if pre[k] != post[k]:
                        changes.append(f"{k}={pre[k]}->{post[k]}")
                print(f"  [{ts}] STAT-CHANGE        pid={p['pid']:4d}  {' '.join(changes)}")
        elif t == 'err':
            print(f"  [ERR] {p.get('where')}: {p.get('msg')}")

    sc.on('message', on_msg)
    sc.load()

    sc.exports_sync.init()
    sc.exports_sync.set_pointers(pdex, hid)
    install_r = sc.exports_sync.install()
    print(f"Hook install: {install_r}")

    # Take initial snapshot just to confirm walk works
    initial = sc.exports_sync.snapshot()
    if isinstance(initial, dict) and 'err' not in initial:
        nz = sum(1 for e in initial.values() if e.get('cap', 0) > 0)
        print(f"Initial snapshot: {len(initial)} dex entries, {nz} with cap>0")

    print(f"\nWatching for {duration}s. Open PoGo, catch/evolve/spin/anything that talks to the server.")
    print(f"CTRL+C to stop early.\n")
    start = time.time()
    try:
        while time.time() - start < duration:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[interrupted]")

    # Persist
    rows = []
    for ev in captured_events:
        rows.append((
            ev['ts'],
            ev['pid'],
            category_name(ev['cat']),
            ev['enc'],
            ev['acq'],
            ev['delta'],
        ))
    if rows:
        conn.executemany(
            "INSERT INTO dex_events (ts_ms, pokemon_id, category, encountered, acquired, delta) VALUES (?,?,?,?,?,?)",
            rows
        )
    stat_rows = []
    for p in captured_stats:
        pre = p.get('pre') or {'cap':0,'enc':0,'shiny':0,'encShiny':0,'lucky':0,'purified':0}
        post = p['post']
        stat_rows.append((
            p['ts'], p['pid'],
            pre['cap'], pre['enc'], pre['shiny'], pre['encShiny'], pre['lucky'], pre['purified'],
            post['cap'], post['enc'], post['shiny'], post['encShiny'], post['lucky'], post['purified'],
        ))
    if stat_rows:
        conn.executemany(
            "INSERT INTO dex_stat_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            stat_rows
        )
    conn.commit()

    print(f"\nCaptured {len(captured_events)} category events, {len(captured_stats)} stat changes")
    print(f"Saved to {DB_PATH}")

    sc.unload()
    sess.detach()


if __name__ == '__main__':
    main()
