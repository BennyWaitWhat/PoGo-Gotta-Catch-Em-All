"""Debug a single PokedexEntryProto to find correct CategoryStatus layout."""
import frida, json, time, subprocess
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

INST = '0x7a09846960'

js = """
rpc.exports = {
    debug: function(addr, pid) {
        var inst = ptr(addr);
        var dictAll = inst.add(0x10).readPointer();
        var entries = dictAll.add(0x18).readPointer();
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);

        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var key = ep.add(8).readS32();
            if (key !== pid) continue;
            var protoPtr = ep.add(16).readPointer();

            // Dump bytes at proto +0x00 to +0xa0
            var dump = {};
            dump.proto = protoPtr.toString();
            dump.entryNum = protoPtr.add(0x10).readS32();
            dump.timesCaptured = protoPtr.add(0x18).readS32();
            dump.timesEncountered = protoPtr.add(0x14).readS32();
            dump.capturedShiny = protoPtr.add(0x40).readU8();
            dump.timesLuckyReceived = protoPtr.add(0x64).readS32();
            dump.timesPurified = protoPtr.add(0x68).readS32();

            // Read raw bytes at +0x80 (where CategoryStatus is)
            var mapPtr = protoPtr.add(0x80).readPointer();
            dump.mapPtr = mapPtr.toString();
            dump.mapPtrIsNull = mapPtr.isNull();

            if (!mapPtr.isNull()) {
                // Try various MapField layouts
                // Read first 0x40 bytes from mapField
                var mapBytes = [];
                for (var j = 0; j < 0x40; j += 8) {
                    mapBytes.push({off: '+0x'+j.toString(16), val: mapPtr.add(j).readPointer().toString()});
                }
                dump.mapFieldRaw = mapBytes;

                // Try +0x10 (might be the dict if map is first)
                // Try +0x18 (list)
                // Try +0x20 (after equality comparers)
                // Try +0x28
                var candidates = [0x10, 0x18, 0x20, 0x28, 0x30];
                dump.candidateProbes = [];
                for (var c = 0; c < candidates.length; c++) {
                    var off = candidates[c];
                    try {
                        var p = mapPtr.add(off).readPointer();
                        if (p.isNull()) {
                            dump.candidateProbes.push({off: off, val: 'null'});
                            continue;
                        }
                        // Try reading as Dictionary: count at +0x20
                        var count = -1, listCount = -1;
                        try { count = p.add(0x20).readS32(); } catch(e) {}
                        try { listCount = p.add(0x18).readS32(); } catch(e) {}
                        dump.candidateProbes.push({off: off, ptr: p.toString(), dictCount: count, listCount: listCount});
                    } catch(e) {
                        dump.candidateProbes.push({off: off, err: e.toString()});
                    }
                }
            }
            return dump;
        }
        return {error: 'pid not found'};
    }
};
"""
script = sess.create_script(js)
script.load()
for pid in [3, 1, 133]:  # Venusaur (has hundo), Bulbasaur, Eevee
    print(f"\n=== PID {pid} ===")
    r = script.exports_sync.debug(INST, pid)
    print(json.dumps(r, indent=2))
sess.detach()
