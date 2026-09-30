"""Connect to ZygiskFrida-injected gadget, hook get_NumberOfTags,
capture real `this` pointer when UI calls it, then call AddTag on the captured instance."""
import frida, time, json

mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
print(f"Connected: {d.name}")

procs = d.enumerate_processes()
gadget_pid = procs[0].pid
print(f"Gadget PID (= PoGo PID): {gadget_pid}")

src = open("bulk_tag.js","r",encoding="utf-8").read()
sess = d.attach(gadget_pid)
script = sess.create_script(src)

captured = []
def on_msg(message, data):
    if message.get("type") == "send":
        p = message["payload"]
        t = p.get("type", "msg")
        msg = p.get("msg", "")
        print(f"[{t}] {msg}")
        if "captured this @" in msg:
            captured.append(msg.split("@")[1].strip())

script.on("message", on_msg)
script.load()

# Init
print("\nCalling init...")
st = script.exports_sync.init_status()
print(f"  init: {st}")
if not st.get("ready"):
    print("FAILED:", st.get("err")); exit(1)

# Hook get_NumberOfTags - waits for UI to fire
print("\nHooking get_NumberOfTags...")
result = script.exports_sync.hook_for_real_instance(60)
print(f"  hook: {result}")

print("\n>>>> INTERACT WITH POGO'S TAG MANAGER NOW <<<<")
print(">>>> Scroll, tap tags, etc. for 30 seconds <<<<\n")

for i in range(30, 0, -1):
    if i % 5 == 0:
        cap = script.exports_sync.get_captured()
        print(f"  {i}s remaining - captured so far: {cap.get('captured', {})}")
    time.sleep(1)

print("\nFinal captured instances:")
final = script.exports_sync.get_captured()
print(json.dumps(final, indent=2))

if final.get("captured") and len(final["captured"]) > 0:
    real_instance = list(final["captured"].keys())[0]
    print(f"\nREAL TaggingRpcService instance: {real_instance}")
    print("Now we can call AddTag on this for real.")

print("\nKeeping session alive 5s...")
time.sleep(5)
sess.detach()
