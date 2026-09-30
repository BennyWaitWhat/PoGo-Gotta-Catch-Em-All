"""Test AddTag on REAL TaggingRpcService instance, verify by re-listing."""
import frida, json, time
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

REAL = "0x71d96f8900"
TEST_NAME = "CLAUDE_TX"

print(f"\n>>> Calling AddTag('{TEST_NAME}', 1) on REAL instance {REAL}")
result = script.exports_sync.add_tag_on_instance(REAL, TEST_NAME, 1)
print(f"  result: {result}")

print("\n>>> Waiting 5s for server round-trip...")
time.sleep(5)

print(">>> Re-listing all tags...")
listing = script.exports_sync.list_all_tags(REAL)
print(f"\n=== {listing.get('count')} tags ===")
for t in listing.get("tags", []):
    names = []
    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if 'str' in k.lower() and isinstance(v, str) and v.strip() and len(v) < 60:
                    names.append(v)
                else: walk(v)
        elif isinstance(d, list):
            for x in d: walk(x)
    walk(t)
    marker = " <<< NEW" if any(TEST_NAME in n for n in names) else ""
    print(f"  [{t.get('i','?'):>2}] {' | '.join(names) if names else '(no name)'}{marker}")

sess.detach()
