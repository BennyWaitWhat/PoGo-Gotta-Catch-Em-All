"""
Spawn PoGO via Frida, resume it, then hook Java Cipher.doFinal()
once the VM is available to capture decrypted game data.
"""
import frida
import sys
import time
import subprocess
import os

FRIDA_HOST = "127.0.0.1:31337"
PACKAGE = "com.nianticlabs.pokemongo"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "captures")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# This script waits for Java VM to be available, then hooks Cipher
HOOK_SCRIPT = """
var captureCount = 0;
var totalDecrypted = 0;
var capturing = true;

function hookCipher() {
    Java.perform(function() {
        send({type: 'info', msg: 'Java VM ready. Hooking Cipher.doFinal...'});

        var Cipher = Java.use('javax.crypto.Cipher');

        // doFinal(byte[])
        Cipher.doFinal.overload('[B').implementation = function(input) {
            var result = this.doFinal(input);
            if (!capturing || !result) return result;

            if (result.length > 1000) {
                totalDecrypted += result.length;
                captureCount++;
                // Convert Java byte[] to ArrayBuffer
                var len = result.length;
                var buf = new ArrayBuffer(len);
                var view = new Uint8Array(buf);
                for (var i = 0; i < len; i++) {
                    view[i] = result[i] & 0xff;
                }
                send({type: 'data', id: captureCount, size: len}, buf);
            }
            return result;
        };

        // doFinal(byte[], int, int)
        try {
            Cipher.doFinal.overload('[B', 'int', 'int').implementation = function(input, off, len) {
                var result = this.doFinal(input, off, len);
                if (!capturing || !result) return result;

                if (result.length > 1000) {
                    totalDecrypted += result.length;
                    captureCount++;
                    var rlen = result.length;
                    var buf = new ArrayBuffer(rlen);
                    var view = new Uint8Array(buf);
                    for (var i = 0; i < rlen; i++) {
                        view[i] = result[i] & 0xff;
                    }
                    send({type: 'data', id: captureCount, size: rlen}, buf);
                }
                return result;
            };
        } catch(e) {
            send({type: 'info', msg: 'doFinal([B,int,int) hook skipped: ' + e.message});
        }

        send({type: 'info', msg: 'Hooks installed. Waiting for game traffic...'});
    });
}

// Wait for Java to be available then hook
function waitForJava() {
    if (Java.available) {
        hookCipher();
    } else {
        send({type: 'info', msg: 'Java not ready, retrying in 1s...'});
        setTimeout(waitForJava, 1000);
    }
}

waitForJava();

rpc.exports = {
    status: function() {
        return {totalDecrypted: totalDecrypted, captureCount: captureCount};
    },
    stop: function() {
        capturing = false;
        return {totalDecrypted: totalDecrypted, captureCount: captureCount};
    }
};
"""

captures = []

def on_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        if isinstance(payload, str):
            print(f"[*] {payload}", flush=True)
        elif payload.get('type') == 'info':
            print(f"[*] {payload['msg']}", flush=True)
        elif payload.get('type') == 'error':
            print(f"[!] {payload['msg']}", flush=True)
        elif payload.get('type') == 'data':
            cid = payload['id']
            size = payload['size']
            filename = f"decrypt_{cid}_{size}b.bin"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(data)
            captures.append({'file': filepath, 'size': size})
            print(f"[+] {filename} ({size}B)", flush=True)
    elif message['type'] == 'error':
        print(f"[!] {message.get('description', '')} line:{message.get('lineNumber','?')}", flush=True)

def main():
    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)

    print("Force-stopping Pokemon GO...", flush=True)
    subprocess.run(["adb", "shell", "su", "-c", "am force-stop com.nianticlabs.pokemongo"],
                   capture_output=True)
    time.sleep(2)

    print("Spawning (suspended)...", flush=True)
    pid = device.spawn([PACKAGE])
    print(f"PID: {pid}", flush=True)

    print("Attaching...", flush=True)
    session = device.attach(pid)

    # Resume first so the Java VM starts
    print("Resuming process first (so Java VM initializes)...", flush=True)
    device.resume(pid)
    print("Waiting 10s for Java VM to start...", flush=True)
    time.sleep(10)

    # Now load the script with v8 runtime
    print("Loading Java hook script...", flush=True)
    script = session.create_script(HOOK_SCRIPT, runtime='v8')
    script.on('message', on_message)
    script.load()

    print(flush=True)
    print("=" * 50, flush=True)
    print("  CAPTURING. Open Pokemon storage when map loads.", flush=True)
    print("  (Pokeball > Pokemon)", flush=True)
    print("=" * 50, flush=True)
    print(flush=True)

    try:
        for i in range(180):
            time.sleep(1)
            if i > 0 and i % 15 == 0:
                try:
                    s = script.exports_sync.status()
                    print(f"  [{i}s] decrypted={s['totalDecrypted']}B captures={s['captureCount']}", flush=True)
                except Exception as e:
                    print(f"  [{i}s] Lost: {e}", flush=True)
                    break
    except KeyboardInterrupt:
        pass

    try:
        r = script.exports_sync.stop()
        print(f"\nFinal: {r}", flush=True)
    except:
        pass

    print(f"\nSaved {len(captures)} files:", flush=True)
    total_size = sum(c['size'] for c in captures)
    for c in captures:
        print(f"  {os.path.basename(c['file'])} ({c['size']}B)", flush=True)
    print(f"Total: {total_size}B across {len(captures)} files", flush=True)

    try:
        session.detach()
    except:
        pass

if __name__ == "__main__":
    main()
