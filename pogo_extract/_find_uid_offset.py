"""Scan Pokemon proto bytes to find UID offset."""
import frida, subprocess, struct
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
SVC = '0x7275723100'

# Known UIDs and proto addrs from prior verify
# Munchlax UID hex 24fd1b41abd3a03b at addr 0x71aa864480
known = {
    '24fd1b41abd3a03b': '0x71aa864480',
    '0c540f3aee0cef75': '0x71aa864240',
    '4fbabdd1865b8fc7': '0x71aa864000',
}

js = """
rpc.exports = {
    dump: function(addr) {
        var p = ptr(addr);
        var bytes = p.readByteArray(256);
        return {bytes: Array.prototype.slice.call(new Uint8Array(bytes))};
    }
};
"""
sc = sess.create_script(js); sc.load()
for uh, addr in known.items():
    expected_uid = int(uh, 16)
    expected_signed = expected_uid if expected_uid < 2**63 else expected_uid - 2**64
    print(f"\n=== {uh} (uid={expected_uid}, signed={expected_signed}) @ {addr} ===")
    r = sc.exports_sync.dump(addr)
    bs = bytes(r['bytes'])
    # Scan every 8-byte aligned offset
    for off in range(0, 256, 8):
        try:
            v = struct.unpack_from('<Q', bs, off)[0]
            if v == expected_uid or v == (expected_signed % (2**64)):
                print(f"  +0x{off:02x} = 0x{v:016x}  *** UID MATCH ***")
            elif 0 < v < 2**32 and v < 100000:
                pass  # small int, probably an enum
            elif v > 2**63:
                # signed negative
                v_signed = v - 2**64
                if v_signed == expected_signed:
                    print(f"  +0x{off:02x} = 0x{v:016x} (signed {v_signed})  *** UID MATCH (signed) ***")
        except: pass
sess.detach()
