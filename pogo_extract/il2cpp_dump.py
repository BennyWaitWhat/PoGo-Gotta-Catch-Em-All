"""
IL2CPP Pokemon Inventory Extractor.

Attaches to running PoGO process via frida-server, resolves IL2CPP classes,
and dumps all Pokemon data before anti-cheat kills the session (~10-20s window).

Usage: python il2cpp_dump.py
"""
import frida
import sys
import json
import time
import threading

DEVICE_ADDR = '127.0.0.1:31337'  # frida-server via ADB port forward
POGO_PACKAGE = 'com.nianticlabs.pokemongo'

results = []
done_event = threading.Event()
error_msg = None

def on_message(message, data):
    global error_msg
    if message['type'] == 'send':
        payload = message['payload']
        if isinstance(payload, dict):
            msg_type = payload.get('type', '')
            if msg_type == 'status':
                print(f"  [status] {payload['msg']}")
            elif msg_type == 'error':
                print(f"  [ERROR] {payload['msg']}")
                error_msg = payload['msg']
            elif msg_type == 'fields':
                print(f"  [fields] {json.dumps(payload['data'], indent=2)}")
                results.append(payload)
            elif msg_type == 'pokemon':
                results.append(payload)
                count = len([r for r in results if r.get('type') == 'pokemon'])
                if count % 100 == 0:
                    print(f"  [pokemon] {count} extracted so far...")
            elif msg_type == 'done':
                print(f"  [DONE] {payload.get('msg', '')}")
                done_event.set()
            else:
                print(f"  [{msg_type}] {payload}")
        else:
            print(f"  [msg] {payload}")
    elif message['type'] == 'error':
        print(f"  [script error] {message.get('description', message)}")
        error_msg = message.get('description', str(message))

def main():
    # Connect to frida-server
    print(f"Connecting to frida-server at {DEVICE_ADDR}...")
    mgr = frida.get_device_manager()
    device = mgr.add_remote_device(DEVICE_ADDR)
    print(f"  Device: {device.name}")

    # Find PoGO process
    print("Looking for Pokemon GO process...")
    try:
        # Try by name first
        proc = device.get_process(POGO_PACKAGE)
        pid = proc.pid
        print(f"  Found: PID {pid}")
    except frida.ProcessNotFoundError:
        # Try by PID directly if hidden from enumeration
        print("  Not found via name (anti-cheat hides it)")
        pid_input = input("  Enter PoGO PID manually (from 'adb shell pidof'): ").strip()
        pid = int(pid_input)

    # Attach
    print(f"Attaching to PID {pid}...")
    session = device.attach(pid)
    print("  Attached! Loading script...")

    # Read the IL2CPP extraction script
    with open('il2cpp_extract.js', 'r') as f:
        script_source = f.read()

    # Create and load script
    script = session.create_script(script_source)
    script.on('message', on_message)
    script.load()
    print("  Script loaded. Waiting for results (30s game load + extraction)...")

    # Wait for completion or timeout
    try:
        done_event.wait(timeout=90)
    except KeyboardInterrupt:
        print("\nInterrupted by user")

    # Save results
    if results:
        outfile = 'il2cpp_results.json'
        with open(outfile, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved {len(results)} results to {outfile}")
    else:
        print("\nNo results collected")
        if error_msg:
            print(f"Last error: {error_msg}")

    # Cleanup
    try:
        session.detach()
    except:
        pass

if __name__ == '__main__':
    main()
