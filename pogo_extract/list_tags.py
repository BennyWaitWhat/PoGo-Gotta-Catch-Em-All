import frida, json
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
def on(m,data):
    p = m.get("payload",{})
    if p.get("type") in ("status","ready"): print("[js]", p.get("msg",""))
script.on("message", on)
script.load()
script.exports_sync.init_status()
result = script.exports_sync.list_all_tags("0x71d96f8900")
# Save full + extract tag names to clean output
import json
with open("all_tags_dump.json","w") as f: json.dump(result, f, indent=2)
print(f"\n=== ALL {result.get('count','?')} TAGS (extracted names) ===")
for t in result.get("tags", []):
    names = []
    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if 'str' in k.lower() and isinstance(v, str) and v.strip() and len(v) < 60:
                    names.append(v)
                else:
                    walk(v)
        elif isinstance(d, list):
            for x in d: walk(x)
    walk(t)
    print(f"  [{t.get('i','?'):>2}] {' | '.join(names) if names else '(no name found)'}")
sess.detach()
