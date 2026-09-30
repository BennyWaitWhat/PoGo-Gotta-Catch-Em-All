import frida, subprocess
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    big: function(addr, before, after) {
        var p = ptr(addr);
        try {
            var bytes = p.sub(before).readByteArray(before + after);
            var u8 = new Uint8Array(bytes);
            var lines = [];
            for (var i = 0; i < u8.length; i += 16) {
                var hex = '';
                var ascii = '';
                for (var j = 0; j < 16 && i+j < u8.length; j++) {
                    hex += ('0' + u8[i+j].toString(16)).slice(-2) + ' ';
                    ascii += (u8[i+j] >= 32 && u8[i+j] < 127) ? String.fromCharCode(u8[i+j]) : '.';
                }
                var off = (i - before).toString();
                lines.push('+' + off.padStart(5) + '  ' + hex.padEnd(48) + '  ' + ascii);
            }
            return lines.join('\\n');
        } catch(e) { return 'err: ' + e.message; }
    }
};
"""
script = sess.create_script(js)
script.load()
# Hit 3 - the third UID match for Machamp
import sys
addr = sys.argv[1] if len(sys.argv) > 1 else '0x7252a3d318'
print(f'=== {addr} (-64, +256) ===')
print(script.exports_sync.big(addr, 64, 256))
sess.detach()
