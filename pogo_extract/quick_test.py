"""
Quick IL2CPP test - attach to running PoGO, resolve classes, get field offsets.
"""
import frida
import sys
import json
import time
import threading

POGO_PID = 27560  # Known PID from earlier

results = []
done_event = threading.Event()

def on_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        if isinstance(payload, dict):
            msg_type = payload.get('type', '')
            if msg_type == 'status':
                print(f"  [status] {payload['msg']}")
            elif msg_type == 'error':
                print(f"  [ERROR] {payload['msg']}")
            elif msg_type == 'fields':
                print(f"  [fields] {json.dumps(payload['data'], indent=2)}")
                results.append(payload)
            elif msg_type == 'bag_candidates':
                print(f"  [bag_candidates] {json.dumps(payload['data'], indent=2)}")
                results.append(payload)
            elif msg_type == 'methods':
                print(f"  [methods] {json.dumps(payload['data'], indent=2)}")
                results.append(payload)
            elif msg_type == 'singletons':
                print(f"  [singletons] {json.dumps(payload['data'], indent=2)}")
                results.append(payload)
            elif msg_type == 'done':
                print(f"  [DONE] {payload.get('msg', '')}")
                done_event.set()
            else:
                print(f"  [{msg_type}] {json.dumps(payload) if isinstance(payload, dict) else payload}")
        else:
            print(f"  [msg] {payload}")
    elif message['type'] == 'error':
        print(f"  [script error] {message.get('description', message)}")
        if 'stack' in message:
            print(f"    {message['stack']}")

def main():
    print(f"Connecting to frida-server at 127.0.0.1:31337...")
    mgr = frida.get_device_manager()
    device = mgr.add_remote_device('127.0.0.1:31337')

    print(f"Attaching to PoGO PID {POGO_PID}...")
    try:
        session = device.attach(POGO_PID)
    except frida.ProcessNotFoundError:
        print("PID not found! Trying to enumerate...")
        for proc in device.enumerate_processes():
            if 'pokemon' in proc.name.lower() or 'niantic' in proc.name.lower():
                print(f"  Found: {proc.name} (PID {proc.pid})")
        return
    except Exception as e:
        print(f"Attach failed: {e}")
        return

    print("  Attached! Loading IL2CPP script...")

    with open('il2cpp_quick.js', 'r') as f:
        script_source = f.read()

    script = session.create_script(script_source)
    script.on('message', on_message)

    try:
        script.load()
    except Exception as e:
        print(f"Script load failed: {e}")
        return

    print("  Script running, waiting for results...")

    # Wait max 30s
    done_event.wait(timeout=30)

    # Save
    if results:
        with open('il2cpp_quick_results.json', 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved {len(results)} results to il2cpp_quick_results.json")

    try:
        session.detach()
        print("Detached cleanly")
    except:
        print("Session already dead (anti-cheat?)")

if __name__ == '__main__':
    main()
