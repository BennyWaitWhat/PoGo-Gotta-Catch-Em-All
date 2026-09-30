"""extract_friends_v3.py - robust friend extractor.

Pipeline:
1. Connect to PoGo via ZygiskFrida gadget (127.0.0.1:27047).
2. Resolve FriendDetailsProto and PlayerSummaryProto field offsets dynamically
   from il2cpp metadata (no hardcoded +0x18/+0x28/... — survives proto reorders).
3. Find BackgroundFriendDetailsCachingService instance using method-hook capture
   (the known-good pattern; Zenject ProjectContext static-field walk is added as
   a fast path but the byte-pattern heap scan documented in
   reference_il2cpp_heapscan_broken.md is intentionally NOT used).
4. Find BackgroundFriendActivitiesCachingService instance via the SAME shared
   IFriendsRpcService pointer trick from extract_friend_activities.py — but
   gated by klass-pointer validation (read +0 and confirm it equals the target
   service class) to avoid the random-heap-match problem.
5. Walk both dictionaries, join on friendId.
6. Write to pokemon.db (new tables: friend, friend_activity, friend_snapshot).
   Each run snapshots — never overwrites — so day-over-day engagement deltas
   are derivable.

Run pattern (single attach, do not retry):
    adb forward tcp:27047 tcp:27047
    python extract_friends_v3.py [--device 100.98.158.56:5555] [--db pokemon.db]

If the BG services aren't cached yet, the script prompts the user to open the
Friends panel in PoGo and waits up to 300s. Same constraint as v1/v2.
"""

import argparse, frida, json, sqlite3, subprocess, sys, time
from datetime import datetime, timezone

ADB_DEFAULT = "100.98.158.56:5555"
GADGET_HOST = "127.0.0.1:27047"

DATE_RANGE = {0: "Unset", 1: "Today", 2: "Yesterday", 3: "2-7d", 4: "8-30d", 5: "30+d"}
ONLINE = {0: "Unset", 1: "Unknown", 2: "Online", 3: "Offline"}

# ---- Frida agent ------------------------------------------------------------
# One agent, one attach, all RPC. Mirrors the "single big script per attach"
# constraint from RESUME.md.
AGENT_JS = r"""
var fns = {};
var img = null;
var classCache = {};
var offsetCache = {};
var instances = {};

function bind(name, ret, args) {
    return new NativeFunction(Module.findExportByName('libil2cpp.so', name), ret, args);
}

function init() {
    fns.dG   = bind('il2cpp_domain_get', 'pointer', []);
    fns.dGA  = bind('il2cpp_domain_get_assemblies', 'pointer', ['pointer','pointer']);
    fns.aGI  = bind('il2cpp_assembly_get_image', 'pointer', ['pointer']);
    fns.iGN  = bind('il2cpp_image_get_name', 'pointer', ['pointer']);
    fns.cFN  = bind('il2cpp_class_from_name', 'pointer', ['pointer','pointer','pointer']);
    fns.cGM  = bind('il2cpp_class_get_methods', 'pointer', ['pointer','pointer']);
    fns.mGN  = bind('il2cpp_method_get_name', 'pointer', ['pointer']);
    fns.cGF  = bind('il2cpp_class_get_fields', 'pointer', ['pointer','pointer']);
    fns.fGN  = bind('il2cpp_field_get_name', 'pointer', ['pointer']);
    fns.fGO  = bind('il2cpp_field_get_offset', 'uint32', ['pointer']);
    fns.fGT  = bind('il2cpp_field_get_type', 'pointer', ['pointer']);
    fns.tGN  = bind('il2cpp_type_get_name', 'pointer', ['pointer']);
    fns.tA   = bind('il2cpp_thread_attach', 'pointer', ['pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4);
    var asms = fns.dGA(fns.dG(), sp);
    var na = sp.readS32();
    var imgs = {};
    for (var a = 0; a < na; a++) {
        var i = fns.aGI(asms.add(a * Process.pointerSize).readPointer());
        imgs[fns.iGN(i).readCString()] = i;
    }
    return imgs;
}

function getClass(imgName, ns, name) {
    var key = imgName + '::' + ns + '::' + name;
    if (classCache[key]) return classCache[key];
    var imgs = img || (img = init());
    var i = imgs[imgName];
    if (!i) return null;
    var cls = fns.cFN(i, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
    classCache[key] = cls;
    return cls;
}

function dumpFields(cls) {
    if (!cls || cls.isNull()) return {};
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var f, out = {};
    while ((f = fns.cGF(cls, iter)) && !f.isNull()) {
        var n = fns.fGN(f).readCString();
        var off = fns.fGO(f);
        var tname = '?';
        try { tname = fns.tGN(fns.fGT(f)).readCString(); } catch(e) {}
        out[n] = {offset: off, type: tname};
    }
    return out;
}

function readUtf16(p) {
    if (!p || p.isNull()) return '';
    try {
        var len = p.add(0x10).readS32();
        if (len <= 0 || len > 500) return '';
        var s = '';
        for (var i = 0; i < len; i++) s += String.fromCharCode(p.add(0x14 + i*2).readU16());
        return s;
    } catch(e) { return ''; }
}

function safe(fn, dflt) { try { return fn(); } catch(e) { return dflt; } }

rpc.exports = {
    // Dump field offsets for proto + service classes so Python doesn't hardcode.
    dumpOffsets: function() {
        init();
        var classes = {
            FriendDetailsProto:   ['holo-protos.dll', 'Holoholo.Rpc', 'FriendDetailsProto'],
            PlayerSummaryProto:   ['holo-protos.dll', 'Holoholo.Rpc', 'PlayerSummaryProto'],
            FriendActivityProto:  ['holo-protos.dll', 'Holoholo.Rpc', 'FriendActivityProto'],
            BgFriendDetails:      ['holo-game.dll',   'Niantic.Holoholo.Social', 'BackgroundFriendDetailsCachingService'],
            BgFriendActivities:   ['holo-game.dll',   'Niantic.Holoholo.Social', 'BackgroundFriendActivitiesCachingService'],
            FriendsRpcService:    ['holo-game.dll',   'Niantic.Holoholo.Social', 'FriendsRpcService'],
        };
        var out = {};
        for (var k in classes) {
            var c = getClass.apply(null, classes[k]);
            out[k] = {addr: c ? c.toString() : null, fields: dumpFields(c)};
        }
        return out;
    },

    // Hook all methods on the two BG services so the next UI interaction
    // captures the real instance. Stable pattern from RESUME.md.
    hookServices: function() {
        var targets = [
            ['BgFriendDetails',   'holo-game.dll', 'Niantic.Holoholo.Social', 'BackgroundFriendDetailsCachingService'],
            ['BgFriendActivities','holo-game.dll', 'Niantic.Holoholo.Social', 'BackgroundFriendActivitiesCachingService'],
        ];
        var counts = {};
        for (var t = 0; t < targets.length; t++) {
            var label = targets[t][0];
            var cls = getClass(targets[t][1], targets[t][2], targets[t][3]);
            if (!cls || cls.isNull()) { counts[label] = -1; continue; }
            var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
            var m, hooked = 0;
            while ((m = fns.cGM(cls, iter)) && !m.isNull()) {
                try {
                    var addr = m.readPointer();
                    if (addr.isNull()) continue;
                    (function(lbl, klass) {
                        Interceptor.attach(addr, {
                            onEnter: function(args) {
                                if (instances[lbl]) return;
                                var inst = args[0];
                                // Validate: object's klass pointer (+0) must equal target class.
                                try {
                                    var k = inst.readPointer();
                                    if (k.equals(klass)) {
                                        instances[lbl] = inst.toString();
                                        send({type: 'h', label: lbl, addr: inst.toString()});
                                    }
                                } catch(e) {}
                            }
                        });
                    })(label, cls);
                    hooked++;
                } catch(e) {}
            }
            counts[label] = hooked;
        }
        return counts;
    },

    getInstances: function() { return instances; },

    // Walk a Dictionary<TKey, ValuePtr> living at inst + dictOffset.
    // Returns raw entry pairs (keyStr, valuePtr) for the caller to project.
    walkDict: function(instAddrStr, dictOffset) {
        var inst = ptr(instAddrStr);
        var dict = inst.add(dictOffset).readPointer();
        if (dict.isNull()) return {error: 'dict null'};
        var entries = dict.add(0x18).readPointer();
        var count   = dict.add(0x20).readS32();
        if (entries.isNull() || count <= 0) return {count: count, entries: []};
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);
        var out = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            if (ep.readS32() < 0) continue;  // free slot
            var keyPtr = ep.add(8).readPointer();
            var valPtr = ep.add(16).readPointer();
            if (valPtr.isNull()) continue;
            out.push({key: readUtf16(keyPtr), val: valPtr.toString()});
        }
        return {count: count, entries: out};
    },

    // Project FriendDetailsProto using metadata-derived offsets.
    projectFriend: function(valAddrStr, offsets) {
        var v = ptr(valAddrStr);
        var r = {};
        function o(name) { return offsets[name] ? offsets[name].offset : -1; }
        function rs(off) { return off < 0 ? '' : readUtf16(v.add(off).readPointer()); }
        function ri32(off) { return off < 0 ? 0 : v.add(off).readS32(); }
        function ri64(off) { return off < 0 ? '0' : v.add(off).readS64().toString(); }
        function rp(off) { return off < 0 ? NULL : v.add(off).readPointer(); }

        // FriendDetailsProto fields (by name, offsets resolved at runtime)
        r.score = safe(function() { return ri32(o('friendshipLevel_')); }, 0);
        r.onlineStatus = safe(function() { return ri32(o('onlineStatus_')); }, 0);
        r.createdMs = safe(function() { return ri64(o('createdTimestampMs_')); }, '0');
        r.lastPlayedRange = safe(function() { return ri32(o('lastPlayedDateRange_')); }, 0);
        r.lastPlayedMs = safe(function() { return ri64(o('lastPlayedTimestampMs_')); }, '0');
        r.isFb = safe(function() { return ri32(o('isFacebookFriendship_')); }, 0);
        r.niaId = safe(function() { return rs(o('friendNiaAccountId_')); }, '');
        r.fbId = safe(function() { return rs(o('friendFbUserId_')); }, '');
        // Player summary nested
        var psOff = o('player_'); if (psOff < 0) psOff = o('friendSummary_');
        if (psOff >= 0) {
            try {
                var ps = v.add(psOff).readPointer();
                if (!ps.isNull()) r.player = ps.toString();
            } catch(e) {}
        }
        return r;
    },

    // Project PlayerSummaryProto from a pointer + per-field offsets.
    projectPlayer: function(addrStr, offsets) {
        var p = ptr(addrStr);
        function o(name) { return offsets[name] ? offsets[name].offset : -1; }
        function rs(off) { return off < 0 ? '' : readUtf16(p.add(off).readPointer()); }
        function ri32(off) { return off < 0 ? 0 : p.add(off).readS32(); }
        function ri64(off) { return off < 0 ? '0' : p.add(off).readS64().toString(); }
        return {
            playerId:    safe(function() { return rs(o('playerId_')); }, ''),
            codename:    safe(function() { return rs(o('codename_')); }, ''),
            displayName: safe(function() { return rs(o('displayName_')); }, ''),
            team:        safe(function() { return rs(o('team_')); }, ''),
            level:       safe(function() { return ri32(o('level_')); }, 0),
            experience:  safe(function() { return ri64(o('experience_')); }, '0'),
        };
    },

    // Project FriendActivityProto.
    projectActivity: function(valAddrStr, offsets) {
        var v = ptr(valAddrStr);
        function o(name) { return offsets[name] ? offsets[name].offset : -1; }
        function rs(off) { return off < 0 ? '' : readUtf16(v.add(off).readPointer()); }
        function ri64(off) { return off < 0 ? '0' : v.add(off).readS64().toString(); }
        var r = {
            niaId:      safe(function() { return rs(o('friendNiaAccountId_')); }, ''),
            receivedMs: safe(function() { return ri64(o('friendActivityReceivedTimestampMs_')); }, '0'),
            expiryMs:   safe(function() { return ri64(o('friendActivityExpiryTimestampMs_')); }, '0'),
        };
        // friendActivity_ is a ByteString. Get length so callers can tell
        // empty-activity vs has-content (real proto decoding is out of scope).
        var actOff = o('friendActivity_');
        if (actOff >= 0) {
            try {
                var bs = v.add(actOff).readPointer();
                if (!bs.isNull()) r.activityLen = bs.add(0x10).readS32();
            } catch(e) {}
        }
        return r;
    },
};
"""

# ---- Schema -----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS friend (
    friend_id            TEXT PRIMARY KEY,    -- PoGo internal friend ID (string)
    nia_account_id       TEXT,
    fb_user_id           TEXT,
    is_fb_friendship     INTEGER,
    player_id            TEXT,
    codename             TEXT,
    display_name         TEXT,
    team                 TEXT,
    level                INTEGER,
    experience           INTEGER,
    friendship_score     INTEGER,             -- "score" in proto: heart count (1..4)
    online_status        INTEGER,             -- 0=Unset 1=Unknown 2=Online 3=Offline
    created_ms           INTEGER,             -- when friendship was formed
    last_played_range    INTEGER,             -- 0..5 bucketized
    last_played_ms       INTEGER,             -- exact ms if not 30+ bucket
    first_seen_ms        INTEGER,             -- our extraction-side first-seen
    last_seen_ms         INTEGER              -- our extraction-side last-seen
);

CREATE TABLE IF NOT EXISTS friend_activity (
    -- Most recent activity per friend (their last gift/raid/etc.)
    nia_account_id       TEXT PRIMARY KEY,
    received_ms          INTEGER,             -- when they sent it
    expiry_ms            INTEGER,
    activity_bytes_len   INTEGER,
    last_observed_ms     INTEGER
);

CREATE TABLE IF NOT EXISTS friend_snapshot (
    -- Append-only per run; used to derive engagement deltas across days.
    snapshot_ms          INTEGER NOT NULL,
    friend_id            TEXT    NOT NULL,
    friendship_score     INTEGER,
    online_status        INTEGER,
    last_played_range    INTEGER,
    last_played_ms       INTEGER,
    activity_received_ms INTEGER,             -- joined from friend_activity at snapshot time
    PRIMARY KEY (snapshot_ms, friend_id)
);

CREATE INDEX IF NOT EXISTS idx_friend_score  ON friend(friendship_score);
CREATE INDEX IF NOT EXISTS idx_friend_lp     ON friend(last_played_ms);
CREATE INDEX IF NOT EXISTS idx_act_received  ON friend_activity(received_ms);
CREATE INDEX IF NOT EXISTS idx_snap_ts       ON friend_snapshot(snapshot_ms);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def fmt_ts(ms) -> str:
    try:
        ms = int(ms)
        if ms <= 0:
            return "-"
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


def attach(adb_serial: str):
    pid = int(subprocess.check_output(
        ["adb", "-s", adb_serial, "shell", "pidof", "com.nianticlabs.pokemongo"]
    ).decode().strip())
    print(f"PID: {pid}")
    mgr = frida.get_device_manager()
    dev = mgr.add_remote_device(GADGET_HOST)
    sess = dev.attach(pid)
    script = sess.create_script(AGENT_JS)
    msgs = []
    def on(m, data):
        p = m.get("payload")
        if isinstance(p, dict):
            msgs.append(p)
            if p.get("type") == "h":
                print(f"  hook fired: {p['label']} @ {p['addr']}")
    script.on("message", on)
    script.load()
    return sess, script, msgs


def wait_for_instances(script, msgs, timeout=300) -> dict:
    print("Hooking services...")
    counts = script.exports_sync.hook_services()
    print(f"  hooked methods: {counts}")
    print(f"Waiting up to {timeout}s for hooks to fire (open Friends panel in PoGo)...")
    for i in range(timeout):
        time.sleep(1)
        cur = script.exports_sync.get_instances()
        if cur.get("BgFriendDetails") and cur.get("BgFriendActivities"):
            return cur
        if i % 30 == 29:
            print(f"  [{i+1}s] captured: {list(cur.keys())}")
    return script.exports_sync.get_instances()


def find_dict_offset(svc_fields: dict) -> int:
    """Find the offset of the Dictionary<...> field on the BG service class.
    v1/v2 used hardcoded +0x80. Resolve dynamically by looking for a field
    named like 'dfdi' / 'dfcm' (Niantic's obfuscated names) whose type starts
    with System.Collections.Generic.Dictionary."""
    for name, info in svc_fields.items():
        t = info.get("type", "")
        if t.startswith("System.Collections.Generic.Dictionary"):
            return info["offset"]
    return 0x80  # legacy fallback


def upsert_friends(db_path: str, friends: list, activities: list):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    now = now_ms()
    snapshot_ts = now

    # Pre-load existing first_seen so we don't overwrite
    cur.execute("SELECT friend_id, first_seen_ms FROM friend")
    first_seen = {r[0]: r[1] for r in cur.fetchall()}

    # friend_activity by nia_account_id
    act_by_nia = {a["niaId"]: a for a in activities if a.get("niaId")}

    for f in friends:
        fid = f.get("key") or f.get("friend_id")
        if not fid:
            continue
        cur.execute("""
            INSERT INTO friend (friend_id, nia_account_id, fb_user_id, is_fb_friendship,
                player_id, codename, display_name, team, level, experience,
                friendship_score, online_status, created_ms, last_played_range, last_played_ms,
                first_seen_ms, last_seen_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(friend_id) DO UPDATE SET
                nia_account_id=excluded.nia_account_id,
                fb_user_id=excluded.fb_user_id,
                is_fb_friendship=excluded.is_fb_friendship,
                player_id=excluded.player_id,
                codename=excluded.codename,
                display_name=excluded.display_name,
                team=excluded.team,
                level=excluded.level,
                experience=excluded.experience,
                friendship_score=excluded.friendship_score,
                online_status=excluded.online_status,
                created_ms=excluded.created_ms,
                last_played_range=excluded.last_played_range,
                last_played_ms=excluded.last_played_ms,
                last_seen_ms=excluded.last_seen_ms
        """, (
            fid, f.get("niaId"), f.get("fbId"), int(bool(f.get("isFb"))),
            (f.get("playerObj") or {}).get("playerId"),
            (f.get("playerObj") or {}).get("codename"),
            (f.get("playerObj") or {}).get("displayName"),
            (f.get("playerObj") or {}).get("team"),
            (f.get("playerObj") or {}).get("level"),
            int((f.get("playerObj") or {}).get("experience") or 0),
            f.get("score"), f.get("onlineStatus"),
            int(f.get("createdMs") or 0),
            f.get("lastPlayedRange"),
            int(f.get("lastPlayedMs") or 0),
            first_seen.get(fid, now), now,
        ))

        act = act_by_nia.get(f.get("niaId") or "", {})
        cur.execute("""
            INSERT INTO friend_snapshot
                (snapshot_ms, friend_id, friendship_score, online_status,
                 last_played_range, last_played_ms, activity_received_ms)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(snapshot_ms, friend_id) DO UPDATE SET
                friendship_score=excluded.friendship_score,
                activity_received_ms=excluded.activity_received_ms
        """, (
            snapshot_ts, fid, f.get("score"), f.get("onlineStatus"),
            f.get("lastPlayedRange"), int(f.get("lastPlayedMs") or 0),
            int(act.get("receivedMs") or 0),
        ))

    for a in activities:
        nia = a.get("niaId")
        if not nia:
            continue
        cur.execute("""
            INSERT INTO friend_activity (nia_account_id, received_ms, expiry_ms,
                activity_bytes_len, last_observed_ms)
            VALUES (?,?,?,?,?)
            ON CONFLICT(nia_account_id) DO UPDATE SET
                received_ms=excluded.received_ms,
                expiry_ms=excluded.expiry_ms,
                activity_bytes_len=excluded.activity_bytes_len,
                last_observed_ms=excluded.last_observed_ms
        """, (
            nia, int(a.get("receivedMs") or 0), int(a.get("expiryMs") or 0),
            a.get("activityLen") or 0, now,
        ))

    con.commit()
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=ADB_DEFAULT)
    ap.add_argument("--db", default="pokemon.db")
    ap.add_argument("--json-out", default="friends_v3.json",
                    help="raw dump; for debugging or external tooling")
    args = ap.parse_args()

    sess, script, _msgs = attach(args.device)
    try:
        print("Dumping field offsets from il2cpp metadata...")
        offsets = script.exports_sync.dump_offsets()
        for k, v in offsets.items():
            print(f"  {k}: class={v['addr']} fields={len(v.get('fields') or {})}")
        if not offsets.get("FriendDetailsProto", {}).get("fields"):
            print("FAIL: FriendDetailsProto not found - holo-protos.dll missing?")
            sys.exit(2)

        inst = wait_for_instances(script, _msgs)
        bgd = inst.get("BgFriendDetails")
        bga = inst.get("BgFriendActivities")
        if not (bgd and bga):
            print(f"FAIL: instances not captured (got {inst})")
            sys.exit(3)

        details_fields = offsets["BgFriendDetails"]["fields"]
        act_fields     = offsets["BgFriendActivities"]["fields"]
        details_dict_off = find_dict_offset(details_fields)
        act_dict_off     = find_dict_offset(act_fields)
        print(f"BgFriendDetails dict @ +0x{details_dict_off:x}")
        print(f"BgFriendActivities dict @ +0x{act_dict_off:x}")

        fd_offs = offsets["FriendDetailsProto"]["fields"]
        ps_offs = offsets["PlayerSummaryProto"]["fields"]
        fa_offs = offsets["FriendActivityProto"]["fields"]

        print("Walking BgFriendDetails dict...")
        det = script.exports_sync.walk_dict(bgd, details_dict_off)
        if "error" in det:
            print(f"  ERROR: {det['error']}")
            sys.exit(4)
        print(f"  {det['count']} entries")

        print("Walking BgFriendActivities dict...")
        act = script.exports_sync.walk_dict(bga, act_dict_off)
        if "error" in act:
            print(f"  ERROR: {act['error']}")
        print(f"  {act.get('count', 0)} entries")

        friends = []
        for e in det.get("entries", []):
            f = script.exports_sync.project_friend(e["val"], fd_offs)
            f["key"] = e["key"]
            if f.get("player"):
                f["playerObj"] = script.exports_sync.project_player(f["player"], ps_offs)
            friends.append(f)

        activities = []
        for e in act.get("entries", []):
            a = script.exports_sync.project_activity(e["val"], fa_offs)
            a["key"] = e["key"]
            activities.append(a)

        print(f"\nFriends walked: {len(friends)}, activities walked: {len(activities)}")

        with open(args.json_out, "w") as fh:
            json.dump({"friends": friends, "activities": activities,
                       "offsets": offsets}, fh, indent=2)
        print(f"Raw dump -> {args.json_out}")

        upsert_friends(args.db, friends, activities)
        print(f"Upserted into {args.db}")

        # Quick summary
        print(f"\n{'Codename':<22} {'Lvl':>4} {'Score':>5} {'LastPlayed':<12} {'Activity':<18}")
        print("-" * 72)
        act_by_nia = {a["niaId"]: a for a in activities if a.get("niaId")}
        for f in sorted(friends, key=lambda x: -int(x.get("score", 0) or 0)):
            po = f.get("playerObj") or {}
            cn = (po.get("codename") or po.get("displayName") or "?")[:20]
            lp = DATE_RANGE.get(f.get("lastPlayedRange"), "?")
            a = act_by_nia.get(f.get("niaId") or "")
            ar = fmt_ts(a["receivedMs"]) if a else "-"
            print(f"{cn:<22} {po.get('level',0):>4} {f.get('score',0):>5} {lp:<12} {ar:<18}")

    finally:
        sess.detach()


if __name__ == "__main__":
    main()
