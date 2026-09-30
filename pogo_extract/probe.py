"""Probe MethodInfo struct via gadget."""
import frida, json
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
procs = d.enumerate_processes()
sess = d.attach(procs[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
script.on("message", lambda m, data: print("[js]", m.get("payload")))
script.load()
print("init:", script.exports_sync.init_status())
print("probe:", json.dumps(script.exports_sync.probe_method_info(), indent=2))
sess.detach()
