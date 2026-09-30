import frida, subprocess
r = subprocess.run(['adb', '-s', '100.98.158.56:5555', 'shell', 'su -c "pidof com.nianticlabs.pokemongo"'],
                   capture_output=True, text=True)
pid = int(r.stdout.strip().split()[0])
print(f"PoGO PID: {pid}")

mgr = frida.get_device_manager()
dev = mgr.add_remote_device('127.0.0.1:31337')

procs = dev.enumerate_processes()
print(f"Frida sees {len(procs)} processes")
for p in procs:
    if 'pokemon' in p.name.lower() or 'niantic' in p.name.lower():
        print(f"  {p.name} (PID {p.pid})")

try:
    s = dev.attach(pid)
    print(f"  ATTACH SUCCESS! pid={pid}")
    s.detach()
except Exception as e:
    print(f"  ATTACH FAILED: {e}")
