"""
Frida-based SSL capture for Pokemon GO inventory extraction.
Attaches to the running PoGO process, hooks SSL_read, captures large responses.
"""
import frida
import sys
import time
import os

FRIDA_HOST = "127.0.0.1:31337"
POGO_PID = 25460
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "ssl_dump.js")
CAPTURE_DURATION = 60  # seconds to capture

captures = []
total_bytes = 0

def on_message(message, data):
    global total_bytes
    if message['type'] == 'send':
        payload = message['payload']
        if payload['type'] == 'info':
            print(f"[*] {payload['msg']}")
        elif payload['type'] == 'error':
            print(f"[!] {payload['msg']}")
        elif payload['type'] == 'capture':
            captures.append(payload)
            print(f"[+] CAPTURED: {payload['file']} ({payload['size']} bytes)")
        elif payload['type'] == 'write':
            pass  # SSL_write notifications (request sizes)
    elif message['type'] == 'error':
        print(f"[!] Script error: {message.get('description', message)}")

def main():
    print(f"Connecting to frida-server at {FRIDA_HOST}...")
    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)

    print(f"Attaching to PID {POGO_PID} (Pokemon GO)...")
    session = device.attach(POGO_PID)

    print("Loading SSL hook script...")
    with open(SCRIPT_PATH, "r") as f:
        script_source = f.read()

    script = session.create_script(script_source)
    script.on('message', on_message)
    script.load()

    print()
    print("=" * 60)
    print("  HOOK ACTIVE - SSL_read is being monitored")
    print("  ")
    print("  NOW: Open your Pokemon storage in Pokemon GO")
    print("       (tap the Pokeball > Pokemon)")
    print("  ")
    print(f"  Capturing for {CAPTURE_DURATION} seconds...")
    print("=" * 60)
    print()

    try:
        for i in range(CAPTURE_DURATION):
            time.sleep(1)
            if i > 0 and i % 10 == 0:
                status = script.exports_sync.status()
                print(f"  [{i}s] bytes_read={status['totalBytesRead']}, captures={status['captureCount']}, sessions={status['activeSessions']}")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    print("\nStopping capture...")
    result = script.exports_sync.stop()
    print(f"Result: {result}")

    print(f"\nTotal captures: {len(captures)}")
    for c in captures:
        print(f"  {c['file']} - {c['size']} bytes")

    session.detach()
    print("\nDone. Pull captures with: adb pull /sdcard/pogo_capture/")

if __name__ == "__main__":
    main()
