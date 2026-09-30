"""
Diagnostic: spawn PoGO, try to hook SSL_read with maximum error detail.
"""
import frida
import sys
import time
import subprocess

FRIDA_HOST = "127.0.0.1:31337"
PACKAGE = "com.nianticlabs.pokemongo"

DIAG_SCRIPT = """
send({type: 'step', msg: 'Script starting...'});

// Step 1: Check Module.findExportByName exists
send({type: 'step', msg: 'typeof Module.findExportByName = ' + typeof Module.findExportByName});

// Step 2: Try finding SSL_read
var addr;
try {
    addr = Module.findExportByName("libssl.so", "SSL_read");
    send({type: 'step', msg: 'findExportByName("libssl.so", "SSL_read") = ' + addr});
    send({type: 'step', msg: 'type of result: ' + typeof addr});
    if (addr) {
        send({type: 'step', msg: 'addr.isNull(): ' + addr.isNull()});
    }
} catch(e) {
    send({type: 'step', msg: 'findExportByName threw: ' + e.message + ' stack: ' + e.stack});
}

// Step 3: Try getExportByName (throws on failure instead of returning null)
try {
    var addr2 = Module.getExportByName("libssl.so", "SSL_read");
    send({type: 'step', msg: 'getExportByName result: ' + addr2});
} catch(e) {
    send({type: 'step', msg: 'getExportByName threw: ' + e.message});
}

// Step 4: Try the full path
try {
    var addr3 = Module.findExportByName("/apex/com.android.conscrypt/lib64/libssl.so", "SSL_read");
    send({type: 'step', msg: 'findExportByName(full_path) = ' + addr3});
} catch(e) {
    send({type: 'step', msg: 'full path threw: ' + e.message});
}

// Step 5: Enumerate and find manually
try {
    var mods = Process.enumerateModules();
    var found = false;
    for (var i = 0; i < mods.length; i++) {
        if (mods[i].name === 'libssl.so') {
            send({type: 'step', msg: 'Found libssl.so module: base=' + mods[i].base + ' path=' + mods[i].path});
            // Try enumerateExports
            var exports = mods[i].enumerateExports();
            for (var j = 0; j < exports.length; j++) {
                if (exports[j].name === 'SSL_read') {
                    send({type: 'step', msg: 'SSL_read export: addr=' + exports[j].address + ' type=' + exports[j].type});
                    found = true;
                    // Try to hook this address directly
                    try {
                        Interceptor.attach(exports[j].address, {
                            onEnter: function(args) {
                                send({type: 'hook', msg: 'SSL_read called! buf_size=' + args[2].toInt32()});
                            }
                        });
                        send({type: 'step', msg: 'HOOK INSTALLED via direct address!'});
                    } catch(e2) {
                        send({type: 'step', msg: 'Interceptor.attach failed: ' + e2.message + ' stack: ' + e2.stack});
                    }
                    break;
                }
            }
            break;
        }
    }
    if (!found) {
        send({type: 'step', msg: 'SSL_read not found in exports enumeration'});
    }
} catch(e) {
    send({type: 'step', msg: 'Manual enum threw: ' + e.message});
}

send({type: 'step', msg: 'Diagnostic complete.'});
"""

def on_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        if isinstance(payload, str):
            print(f"  {payload}")
        else:
            print(f"  [{payload.get('type','')}] {payload.get('msg','')}")
    elif message['type'] == 'error':
        print(f"  [ERROR] {message.get('description', '')} at {message.get('lineNumber','?')}")
        if 'stack' in message:
            print(f"          {message['stack']}")

def main():
    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)

    print("Killing PoGO...")
    subprocess.run(["adb", "shell", "su", "-c", "am force-stop com.nianticlabs.pokemongo"],
                   capture_output=True)
    time.sleep(2)

    print(f"Spawning {PACKAGE} (suspended)...")
    pid = device.spawn([PACKAGE])
    print(f"PID: {pid}")

    print("Attaching...")
    session = device.attach(pid)

    print("Loading diagnostic script...")
    script = session.create_script(DIAG_SCRIPT)
    script.on('message', on_message)
    script.load()
    time.sleep(3)

    print("\nDiagnostic while suspended done. Resuming...")
    device.resume(pid)
    time.sleep(5)

    print("Session alive?", not session.is_detached)
    session.detach()
    print("Done.")

if __name__ == "__main__":
    main()
