"""Generic runner: attach to PoGO and run a JS script."""
import frida, sys, json, threading

import subprocess
result = subprocess.run(['adb', '-s', '100.98.158.56:5555', 'shell', 'su -c "pidof com.nianticlabs.pokemongo"'],
                       capture_output=True, text=True)
POGO_PID = int(result.stdout.strip().split()[0])
print(f"PoGO PID: {POGO_PID}")

results = []
done = threading.Event()

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            t = p.get('type','')
            if t == 'error':
                print(f"  [ERROR] {p['msg']}")
            elif t == 'done':
                print(f"  [DONE] {p.get('msg','')}")
                done.set()
            elif t == 'pokemon_data':
                print(f"  [pokemon_data] Got {p.get('count', 0)} pokemon!")
                # Save pokemon data immediately
                with open('pokemon_dump.json', 'w') as pf:
                    json.dump(p.get('data', []), pf, indent=2)
                print(f"  Saved to pokemon_dump.json")
            elif t == 'progress':
                print(f"  [progress] {p.get('count', 0)}/{p.get('total', '?')}")
            else:
                content = p.get('msg', p.get('data', p))
                if isinstance(content, (dict, list)):
                    print(f"  [{t}] {json.dumps(content, indent=2)[:2000]}")
                else:
                    print(f"  [{t}] {content}")
            results.append(p)
        else:
            print(f"  {p}")
    elif msg['type'] == 'error':
        print(f"  [SCRIPT ERROR] {msg.get('description','?')}")
        if 'stack' in msg:
            print(f"  {msg['stack'][:500]}")

script_file = sys.argv[1] if len(sys.argv) > 1 else 'il2cpp_find_bag.js'
print(f"Loading {script_file}...")

mgr = frida.get_device_manager()
dev = mgr.add_remote_device('127.0.0.1:31337')
session = dev.attach(POGO_PID)

with open(script_file) as f:
    source = f.read()

script = session.create_script(source)
script.on('message', on_message)
script.load()
print("Running...")

timeout = 120 if 'extract_full' in script_file else 60
done.wait(timeout=timeout)
if not done.is_set():
    print("  [TIMEOUT] Script did not signal completion")

with open(script_file.replace('.js', '_results.json'), 'w') as f:
    json.dump(results, f, indent=2)

try:
    session.detach()
except:
    pass
print("Done.")
