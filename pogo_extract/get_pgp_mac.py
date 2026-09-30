"""Hook Android BluetoothDevice.getAddress() to capture PGP MAC, services, characteristics."""
import frida, json, time, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}', flush=True)
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
var captures = [];
rpc.exports = { fetch: function() { var r = captures.slice(); captures = []; return r; } };
Java.perform(function() {
    try {
    var BluetoothDevice = Java.use('android.bluetooth.BluetoothDevice');
    BluetoothDevice.getName.implementation = function() {
        var n = this.getName.call(this);
        var addr = this.getAddress.call(this);
        if (n && (n.indexOf('Pokemon') >= 0 || n.indexOf('Plus') >= 0 || addr.toLowerCase().endsWith(':0a:b3'))) {
            captures.push({event:'getName', name: n, addr: addr});
            send({type:'h', msg: 'PGP getName: name='+n+' addr='+addr});
        }
        return n;
    };
    BluetoothDevice.getAddress.implementation = function() {
        var addr = this.getAddress.call(this);
        if (addr && addr.toLowerCase().endsWith(':0a:b3')) {
            captures.push({event:'getAddress', addr: addr});
            send({type:'h', msg: 'PGP getAddress: '+addr});
        }
        return addr;
    };

    // Hook BluetoothGatt operations
    try {
        var BluetoothGatt = Java.use('android.bluetooth.BluetoothGatt');
        BluetoothGatt.discoverServices.implementation = function() {
            var dev = this.getDevice.call(this);
            send({type:'h', msg: 'GATT discoverServices on '+dev.getAddress()});
            captures.push({event:'discoverServices', addr: dev.getAddress()});
            return this.discoverServices.call(this);
        };
        BluetoothGatt.readCharacteristic.implementation = function(c) {
            var u = c.getUuid().toString();
            captures.push({event:'readCharacteristic', uuid: u});
            send({type:'h', msg: 'readCharacteristic '+u});
            return this.readCharacteristic.call(this, c);
        };
        BluetoothGatt.writeCharacteristic.overload('android.bluetooth.BluetoothGattCharacteristic').implementation = function(c) {
            var u = c.getUuid().toString();
            var v = c.getValue();
            var hex = '';
            if (v) {
                for (var i = 0; i < v.length; i++) {
                    var b = v[i] & 0xff;
                    hex += ('0'+b.toString(16)).slice(-2);
                }
            }
            captures.push({event:'writeCharacteristic', uuid: u, value: hex});
            send({type:'h', msg: 'writeCharacteristic '+u+' = '+hex});
            return this.writeCharacteristic.overload('android.bluetooth.BluetoothGattCharacteristic').call(this, c);
        };
    } catch(e) { send({type:'h', msg: 'BluetoothGatt hook err: '+e.toString()}); }
    send({type:'h', msg: 'Java hooks installed OK'});
    } catch(e) { send({type:'h', msg: 'Outer Java err: '+e.toString()}); }
});
"""
sc = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  HOOK: {p['msg']}", flush=True)
sc.on('message', on)
sc.load()
print("Hooks installed on Android Bluetooth APIs.", flush=True)
print("Waiting up to 60s for PoGo to access PGP (will fire on connect/poll)...", flush=True)
for i in range(60):
    time.sleep(1)
    caps = sc.exports_sync.fetch()
    for c in caps:
        print(f"  [{i+1}s] {c}", flush=True)
print("\n=== Final captures ===", flush=True)
final = sc.exports_sync.fetch()
print(json.dumps(final, indent=2), flush=True)
sess.detach()
