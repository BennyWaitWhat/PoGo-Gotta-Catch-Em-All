"""Hook every BLE-related C++ function in libholoholo.so to capture PGP traffic."""
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

var mod = Process.findModuleByName('libholoholo.so');
var allExports = mod.enumerateExports();

// Find all BLE-related functions
var bleKeywords = ['Bluetooth', 'Peripheral', 'Characteristic', 'sfida', 'Pgp', 'Plus', 'Sleep', 'Waina'];
var hits = [];
allExports.forEach(function(e) {
    var n = e.name;
    for (var i = 0; i < bleKeywords.length; i++) {
        if (n.indexOf(bleKeywords[i]) >= 0) { hits.push(e); break; }
    }
});
send({type:'h', msg: 'Found '+hits.length+' BLE-related exports'});

// Categorize and hook the most interesting ones
var hookCount = 0;
hits.forEach(function(e) {
    var n = e.name;
    // Hook anything with GetAddress / WriteValue / SetValue / OnDataReceived / Send / Notify
    var interesting = false;
    var category = '';
    if (n.indexOf('GetAddress') >= 0 || n.indexOf('GetMacAddress') >= 0) { interesting = true; category = 'addr'; }
    else if (n.indexOf('WriteValue') >= 0 || n.indexOf('Write') >= 0 && n.indexOf('Characteristic') >= 0) { interesting = true; category = 'write'; }
    else if (n.indexOf('OnDataReceived') >= 0 || n.indexOf('Notification') >= 0 || n.indexOf('Notify') >= 0) { interesting = true; category = 'notify'; }
    else if (n.indexOf('GetUuid') >= 0 || n.indexOf('GetUUID') >= 0) { interesting = true; category = 'uuid'; }
    else if (n.indexOf('OnConnect') >= 0 || n.indexOf('OnDisconnect') >= 0) { interesting = true; category = 'conn'; }
    else if (n.indexOf('ReadValue') >= 0 || n.indexOf('Read') >= 0 && n.indexOf('Characteristic') >= 0) { interesting = true; category = 'read'; }
    else if (n.indexOf('OnSleepLog') >= 0 || n.indexOf('SleepLog') >= 0) { interesting = true; category = 'sleeplog'; }
    if (!interesting) return;

    try {
        Interceptor.attach(e.address, {
            onEnter: function(args) {
                var rec = {fn: n, cat: category, ts: Date.now()};
                // Try to read first 4 args as pointer + dereferenced strings
                for (var i = 0; i < 4; i++) {
                    try {
                        var p = args[i];
                        if (!p.isNull()) {
                            // Try to read as C string (12 bytes is typical for a MAC string)
                            try {
                                var s = p.readCString(64);
                                if (s && s.length > 0 && /^[a-zA-Z0-9:_.\\-\\s]+$/.test(s) && s.length < 60) {
                                    rec['arg'+i+'_str'] = s;
                                }
                            } catch(e) {}
                        }
                    } catch(e) {}
                }
                captures.push(rec);
            }
        });
        hookCount++;
    } catch(e) {}
});
send({type:'h', msg: 'Hooked '+hookCount+' interesting BLE methods'});
"""
sc = sess.create_script(js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}", flush=True)
sc.on('message', on)
sc.load()
print("Watching for BLE activity for 60s...", flush=True)
time.sleep(2)

mac_found = None
for i in range(60):
    time.sleep(1)
    caps = sc.exports_sync.fetch()
    for c in caps:
        # Look for MAC addresses in any captured string
        for k, v in c.items():
            if k.startswith('arg') and k.endswith('_str') and isinstance(v, str):
                if ':' in v and len(v) >= 17 and v.count(':') == 5:
                    print(f"  [{i+1}s] *** MAC found: {v} (in {c['fn'][:60]}) ***", flush=True)
                    mac_found = v
        if c.get('cat') in ('write', 'notify', 'sleeplog'):
            print(f"  [{i+1}s] {c['cat']}: {c['fn'][:80]}", flush=True)

print(f"\nMAC: {mac_found}", flush=True)
sess.detach()
