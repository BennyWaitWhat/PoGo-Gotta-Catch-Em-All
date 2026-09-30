"""Probe BackgroundFriendActivitiesCachingService instance fields more carefully."""
import frida, json, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
ACT = '0x790e7f48c0'

js = """
rpc.exports = {
    probe: function(addr) {
        var inst = ptr(addr);
        // Read first 0x100 bytes as pointers
        var fields = [];
        for (var off = 0; off < 0x100; off += 8) {
            try {
                var p = inst.add(off).readPointer();
                var info = {off: '+0x' + off.toString(16).padStart(2,'0'), val: p.toString()};
                if (!p.isNull()) {
                    // Try interpreting as Dictionary (+0x18 entries, +0x20 count)
                    try {
                        var c = p.add(0x20).readS32();
                        if (c >= 0 && c < 100000) info.maybeDictCount = c;
                    } catch(e) {}
                    // Try interpreting as int32
                    if ((BigInt(p.toString()) & 0xffffffffffff0000n) === 0n) {
                        info.asInt = parseInt(p.toString(), 16);
                    }
                }
                fields.push(info);
            } catch(e) { fields.push({off:'+0x'+off.toString(16), err:e.toString()}); }
        }
        return fields;
    }
};
"""
sc = sess.create_script(js); sc.load()
print(f"Probing instance {ACT}:")
fields = sc.exports_sync.probe(ACT)
for f in fields:
    extras = []
    if 'maybeDictCount' in f: extras.append(f"dictCnt={f['maybeDictCount']}")
    if 'asInt' in f: extras.append(f"int={f['asInt']}")
    if 'err' in f: extras.append('ERR')
    print(f"  {f['off']}  {f.get('val','?')}  {' '.join(extras)}")
sess.detach()
