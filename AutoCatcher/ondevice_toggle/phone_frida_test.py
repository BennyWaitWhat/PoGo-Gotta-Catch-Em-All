import frida, subprocess
print("frida", frida.__version__)
def pogo_pid():
    try:
        out = subprocess.run(["/system/bin/pidof", "com.nianticlabs.pokemongo"], capture_output=True, text=True)
        return int(out.stdout.split()[0]) if out.stdout.strip() else None
    except Exception:
        return None
dm = frida.get_device_manager()
dev = dm.add_remote_device("127.0.0.1:27047")
print("device:", dev)
try:
    procs = dev.enumerate_processes()
    print("procs:", [(p.pid, p.name) for p in procs][:6])
except Exception as e:
    print("enum err:", repr(e))
pid = pogo_pid()
print("pogo pid:", pid)
session = None
for target in [pid, "Gadget", 0]:
    if target is None:
        continue
    try:
        session = dev.attach(target)
        print("ATTACHED via", repr(target))
        break
    except Exception as e:
        print("attach", repr(target), "->", repr(e))
if session:
    sc = session.create_script("rpc.exports.ping=function(){return 6*7;};")
    sc.load()
    print("rpc ping ->", sc.exports_sync.ping())
    print("=== FRIDA_PHONE_CONNECT_OK ===")
    sc.unload(); session.detach()
else:
    print("=== NO ATTACH ===")
