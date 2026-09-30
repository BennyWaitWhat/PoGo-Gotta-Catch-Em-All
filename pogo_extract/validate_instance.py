"""Validate the captured TaggingRpcService instance pointer."""
import frida, json
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
script.on("message", lambda m, data: print("[js]", m.get("payload")))
script.load()
print("init:", script.exports_sync.init_status())
print("validate:", json.dumps(script.exports_sync.validate_instance("0x71d96f8900"), indent=2))
sess.detach()
