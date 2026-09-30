"""Untag 5 remaining FPs (top3-bucket-rank2/3 cases v2 saved). Cached service instance."""
import frida, json, time

SERVICE = "0x6ff1d41f80"
TAG_PROTO = "0x70139999c0"

with open('untag_5_remaining.json') as f:
    targets = json.load(f)
print(f'Untagging {len(targets)} FPs')

mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
script.load()
script.exports_sync.init_status()
script.exports_sync.index_pokemon()

ok = 0; fail = 0
for t in targets:
    uid = t['uid']
    low = uid & 0xFFFFFFFF; high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    p = script.exports_sync.find_pokemon_proto(low, high)
    if not p.get("ok"):
        print(f"  {t['uid_hex']} {t['species']}: not in index")
        fail += 1
        continue
    r = script.exports_sync.bulk_untag_one(SERVICE, p["ptr"], TAG_PROTO)
    if r.get("ok"):
        print(f"  {t['uid_hex']} {t['species']}: untagged")
        ok += 1
    else:
        print(f"  {t['uid_hex']} {t['species']}: FAIL {r}")
        fail += 1
    time.sleep(0.3)

print(f"\nFinal: ok={ok} fail={fail}")
sess.detach()
