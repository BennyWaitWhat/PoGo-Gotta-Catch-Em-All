"""Quick targeted dump of PokemonBagService etc. methods."""
import frida, json, subprocess, time

def get_pid():
    r = subprocess.run(["adb","shell","su","-c","pidof com.nianticlabs.pokemongo"], capture_output=True, text=True)
    s = r.stdout.strip()
    return int(s.split()[0]) if s else None

def unfreeze(pid):
    subprocess.run(["adb","shell","su","-c", f"echo 0 > /sys/fs/cgroup/apps/uid_10468/pid_{pid}/cgroup.freeze"], capture_output=True)

results = {}
done = False
def on_msg(message, data):
    global done
    if message.get("type") != "send": return
    p = message["payload"]
    t = p.get("type")
    if t == "msg":
        print(p["msg"])
    elif t == "methods":
        results[p["label"]] = {"image": p["image"], "methods": p["data"]}
        print(f"  {p['label']}: {len(p['data'])} methods")
    elif t == "done":
        done = True

mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:31337")
pid = get_pid()
print(f"PID: {pid}")
unfreeze(pid)
session = d.attach(pid)
with open("nickname_extra.js") as f:
    script = session.create_script(f.read())
script.on("message", on_msg)
script.load()
waited = 0
while not done and waited < 60:
    time.sleep(1); waited += 1
    if waited % 2 == 0: unfreeze(pid)

with open("nickname_extra_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"Saved to nickname_extra_results.json")
session.detach()
