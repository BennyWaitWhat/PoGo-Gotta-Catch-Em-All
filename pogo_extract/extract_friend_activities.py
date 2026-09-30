"""Walk BackgroundFriendActivitiesCachingService.dfcm to get per-friend last-activity timestamps.
Also heap-scan for BackgroundFriendDetailsCachingService via shared IFriendsRpcService field."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

ACTIVITIES_INST = '0x790e7f48c0'

js = """
rpc.exports = {
    walkActivities: function(addr) {
        var inst = ptr(addr);
        var dict = inst.add(0x80).readPointer();
        if (dict.isNull()) return {error:'dfcm null'};
        var entries = dict.add(0x18).readPointer();
        var count = dict.add(0x20).readS32();
        if (entries.isNull()) return {error:'entries null', count:count};
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);

        function readUtf16Str(p) {
            if (p.isNull()) return '';
            var len = p.add(0x10).readS32();
            if (len <= 0 || len > 200) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(p.add(0x14 + i*2).readU16()));
            return chars.join('');
        }

        var results = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var keyPtr = ep.add(8).readPointer();
            var valPtr = ep.add(16).readPointer();
            if (valPtr.isNull()) continue;

            // FriendActivityProto offsets:
            // +0x18 niaAccountId_, +0x20 friendActivity_ (ByteString), +0x28 receivedTs, +0x30 expiryTs
            var rec = {
                key: readUtf16Str(keyPtr),
                niaId: readUtf16Str(valPtr.add(0x18).readPointer()),
                receivedMs: valPtr.add(0x28).readS64().toString(),
                expiryMs: valPtr.add(0x30).readS64().toString(),
            };
            // Try reading first byte of activity to know if it has data
            try {
                var bs = valPtr.add(0x20).readPointer();
                if (!bs.isNull()) {
                    var bsLen = bs.add(0x10).readS32();
                    rec.activityBytesLen = bsLen;
                }
            } catch(e) {}
            results.push(rec);
        }
        return {count: count, walked: results.length, friends: results};
    },

    findDetailsService: function(activitiesAddr) {
        // Activities service has IFriendsRpcService at +0x50. Details service has same.
        // Heap scan rw memory for objects whose +0x50 matches.
        var actInst = ptr(activitiesAddr);
        var rpcSvc = actInst.add(0x50).readPointer();
        if (rpcSvc.isNull()) return {error: 'no rpc svc'};

        var rpcSvcStr = rpcSvc.toString();
        var pattern = '';
        var bn = BigInt(rpcSvc.toString());
        for (var i = 0; i < 8; i++) {
            var b = Number((bn >> BigInt(i*8)) & 0xffn);
            pattern += ('0' + b.toString(16)).slice(-2) + ' ';
        }
        pattern = pattern.trim();

        var hits = [];
        var ranges = Process.enumerateRanges('rw-');
        for (var ri = 0; ri < ranges.length; ri++) {
            var r = ranges[ri];
            if (r.size > 256*1024*1024) continue;
            try {
                Memory.scanSync(r.base, r.size, pattern).forEach(function(m){
                    // m.address points to where rpcSvcStr appears. Look at -0x50 to find candidate object header.
                    try {
                        var candidate = m.address.sub(0x50);
                        // Sanity check: candidate should look like a managed object (klass at +0)
                        var klass = candidate.readPointer();
                        if (klass.isNull()) return;
                        // Only consider candidates not equal to activitiesAddr itself
                        if (candidate.equals(actInst)) return;
                        // Read +0x80 to check if it has a Dictionary
                        var maybeDict = candidate.add(0x80).readPointer();
                        if (maybeDict.isNull()) return;
                        var dictCount = -1;
                        try { dictCount = maybeDict.add(0x20).readS32(); } catch(e) {}
                        hits.push({addr: candidate.toString(), dictCount: dictCount});
                    } catch(e) {}
                });
            } catch(e) {}
            if (hits.length > 30) break;
        }
        return {rpcSvc: rpcSvcStr, hits: hits};
    }
};
"""
script = sess.create_script(js)
script.load()

print(f"Walking activities at {ACTIVITIES_INST}...")
r = script.exports_sync.walk_activities(ACTIVITIES_INST)
print(f"  count: {r.get('count')}, walked: {r.get('walked')}")
from datetime import datetime, timezone
def fmt_ts(ms):
    try:
        ms_int = int(ms)
        if ms_int <= 0: return '0'
        return datetime.fromtimestamp(ms_int/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    except: return '?'
if 'friends' in r:
    print("\nPer-friend last activity received timestamp:")
    print(f"{'NiaAccountId (truncated)':<26} {'LastActivity':<18} {'Expires':<18} {'BytesLen':>8}")
    print('-'*80)
    sorted_f = sorted(r['friends'], key=lambda x: -int(x.get('receivedMs','0')))
    for f in sorted_f:
        print(f"{f.get('niaId','?')[:25]:<26} {fmt_ts(f['receivedMs']):<18} {fmt_ts(f.get('expiryMs','0')):<18} {f.get('activityBytesLen','?'):>8}")
    with open('friend_activities.json','w') as fh: json.dump(r, fh, indent=2)

print(f"\n=== Heap-scanning for BackgroundFriendDetailsCachingService ===")
hr = script.exports_sync.find_details_service(ACTIVITIES_INST)
print(f"RPC svc: {hr.get('rpcSvc')}")
print(f"Hits ({len(hr.get('hits',[]))}):")
for h in hr.get('hits',[])[:20]:
    print(f"  candidate {h['addr']}  dictCount={h['dictCount']}")
sess.detach()
