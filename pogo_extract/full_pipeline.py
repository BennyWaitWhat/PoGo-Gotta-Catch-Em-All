"""End-to-end: hook, wait for capture, validate, find CLAUDE_TX tag id, dump structure.
USER ACTION: open PoGo tag manager and keep it OPEN throughout the run."""
import frida, json, time
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
def on(m,data):
    p = m.get("payload",{})
    if isinstance(p, dict) and p.get("type") in ("status","ready"):
        print("[js]", p.get("msg",""))
script.on("message", on)
script.load()
script.exports_sync.init_status()

# Hook
hook_result = script.exports_sync.hook_for_real_instance(120)
print(f"Hook result: {hook_result}")
print("\n>>> KEEP TAG MANAGER OPEN AND CREATE A NEW TAG to fire AddTag hook. Polling...")
real = None
for i in range(40):  # up to 40s
    time.sleep(1)
    cap = script.exports_sync.get_captured()
    if cap.get("captured"):
        real = list(cap["captured"].keys())[0]
        print(f"  CAPTURED at t={i}s: {real}")
        break
    if i % 5 == 0:
        print(f"  t={i}s waiting...")

if not real:
    print("FAILED - no capture. .ctor not firing.")
    sess.detach()
    exit(1)

# Validate
val = script.exports_sync.validate_instance(real)
print(f"\nValidate: tagCount={val.get('boxedInt')}, klassMatches={val.get('klassMatches')}")

# Find CLAUDE_TX
print(f"\nLooking up CLAUDE_TX...")
ftid = script.exports_sync.find_tag_id_by_name(real, "CLAUDE_TX")
print(json.dumps(ftid, indent=2))

sess.detach()
