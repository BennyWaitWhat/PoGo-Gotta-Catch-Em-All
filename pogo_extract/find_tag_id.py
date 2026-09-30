"""Find CLAUDE_TX tag ID."""
import frida, json
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
def on(m,data):
    p = m.get("payload",{})
    if isinstance(p, dict) and p.get("type") in ("status","ready"): print("[js]", p.get("msg",""))
script.on("message", on)
script.load()
script.exports_sync.init_status()
result = script.exports_sync.find_tag_id_by_name("0x71d96f8900", "CLAUDE_TX")
print(json.dumps(result, indent=2))
sess.detach()
