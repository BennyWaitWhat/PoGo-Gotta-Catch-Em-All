"""
Reattach to already-running PoGO (spawned via Frida earlier).
Install SSL hook and capture inventory when user opens Pokemon storage.
"""
import frida
import sys
import time
import os

FRIDA_HOST = "127.0.0.1:31337"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "captures")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SSL_HOOK_SCRIPT = """
var MIN_SIZE = 50000;
var sessionData = {};
var captureCount = 0;
var totalBytesRead = 0;
var capturing = true;

function findExport(moduleName, exportName) {
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++) {
        if (mods[i].name === moduleName) {
            var exports = mods[i].enumerateExports();
            for (var j = 0; j < exports.length; j++) {
                if (exports[j].name === exportName) {
                    return exports[j].address;
                }
            }
            break;
        }
    }
    return null;
}

var ssl_read_addr = findExport("libssl.so", "SSL_read");
if (!ssl_read_addr) {
    send({type: 'error', msg: 'SSL_read not found!'});
} else {
    send({type: 'info', msg: 'SSL_read at ' + ssl_read_addr + ' - hooking...'});

    Interceptor.attach(ssl_read_addr, {
        onEnter: function(args) {
            this.ssl = args[0].toString();
            this.buf = args[1];
            this.num = args[2].toInt32();
        },
        onLeave: function(retval) {
            try {
                if (!capturing) return;
                var size = retval.toInt32();
                if (size <= 0) return;
                totalBytesRead += size;
                if (!sessionData[this.ssl]) {
                    sessionData[this.ssl] = {chunks: [], total: 0};
                }
                var data = this.buf.readByteArray(size);
                if (!data) return;
                sessionData[this.ssl].chunks.push(data);
                sessionData[this.ssl].total += size;
                if (sessionData[this.ssl].total >= MIN_SIZE) {
                    captureCount++;
                    var totalSize = sessionData[this.ssl].total;
                    var combined = new Uint8Array(totalSize);
                    var offset = 0;
                    for (var i = 0; i < sessionData[this.ssl].chunks.length; i++) {
                        var arr = new Uint8Array(sessionData[this.ssl].chunks[i]);
                        combined.set(arr, offset);
                        offset += arr.length;
                    }
                    send({type: 'data', id: captureCount, size: totalSize, ssl: this.ssl}, combined.buffer);
                    sessionData[this.ssl] = {chunks: [], total: 0};
                }
            } catch(e) {}
        }
    });

    send({type: 'info', msg: 'Hook active! Open Pokemon storage now.'});
}

rpc.exports = {
    status: function() {
        return {totalBytesRead: totalBytesRead, captureCount: captureCount, activeSessions: Object.keys(sessionData).length};
    },
    flush: function() {
        capturing = false;
        var flushed = 0;
        Object.keys(sessionData).forEach(function(ssl) {
            if (sessionData[ssl].total > 5000) {
                flushed++;
                captureCount++;
                var totalSize = sessionData[ssl].total;
                var combined = new Uint8Array(totalSize);
                var offset = 0;
                for (var i = 0; i < sessionData[ssl].chunks.length; i++) {
                    var arr = new Uint8Array(sessionData[ssl].chunks[i]);
                    combined.set(arr, offset);
                    offset += arr.length;
                }
                send({type: 'data', id: captureCount, size: totalSize, ssl: ssl, final: true}, combined.buffer);
                sessionData[ssl] = {chunks: [], total: 0};
            }
        });
        return {flushed: flushed, totalBytes: totalBytesRead, captures: captureCount};
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
            tag = "final" if payload.get('final') else "capture"
            filename = f"{tag}_{cid}_{size}b.bin"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(data)
            captures.append({'file': filepath, 'size': size})
            print(f"[+] SAVED: {filename} ({size} bytes)", flush=True)
    elif message['type'] == 'error':
        print(f"[!] Error: {message.get('description', '')}", flush=True)

def main():
    # Get current PoGO PID
    import subprocess
    r = subprocess.run(["adb", "shell", "ps -A | grep com.nianticlabs.pokemongo$"],
                      capture_output=True, text=True)
    pid = int(r.stdout.split()[1])
    print(f"PoGO PID: {pid}", flush=True)

    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)
    print("Attaching...", flush=True)
    session = device.attach(pid)

    print("Installing SSL hook...", flush=True)
    script = session.create_script(SSL_HOOK_SCRIPT)
    script.on('message', on_message)
    script.load()
    time.sleep(1)

    print(flush=True)
    print("=" * 60, flush=True)
    print("  READY! Open Pokemon storage NOW (Pokeball > Pokemon)", flush=True)
    print("  Capturing for 90 seconds...", flush=True)
    print("=" * 60, flush=True)
    print(flush=True)

    try:
        for i in range(90):
            time.sleep(1)
            if i > 0 and i % 10 == 0:
                try:
                    s = script.exports_sync.status()
                    print(f"  [{i}s] read={s['totalBytesRead']}B captures={s['captureCount']} sessions={s['activeSessions']}", flush=True)
                except Exception as e:
                    print(f"  [{i}s] Lost: {e}", flush=True)
                    break
    except KeyboardInterrupt:
        pass

    print("\nFlushing...", flush=True)
    try:
        r = script.exports_sync.flush()
        print(f"Flush: {r}", flush=True)
    except:
        pass

    print(f"\nTotal: {len(captures)} captures", flush=True)
    for c in captures:
        print(f"  {os.path.basename(c['file'])} ({c['size']}B)", flush=True)

    try:
        session.detach()
    except:
        pass

if __name__ == "__main__":
    main()
