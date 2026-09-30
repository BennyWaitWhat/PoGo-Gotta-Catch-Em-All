"""Untag the 2 form-variant shadows incorrectly cull'd."""
import frida, json, time

SERVICE = "0x725ab6e400"
TAG_PROTO = "0x725a2a0cc0"

# Hardcoded from earlier query
targets = [
    {'uid_hex': 'e290fd1c0b178731', 'species': 'Ninetales (form 57)'},
    {'uid_hex': 'ea63a9a8bf32fa2d', 'species': 'Sandslash (form 53)'},
]

import sqlite3
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
for t in targets:
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (t['uid_hex'],)).fetchone()
    t['uid'] = r[0]
conn.close()

mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(31828)
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
        print(f"  {t['uid_hex']} {t['species']}: not in heap-index")
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

# Verify
ftid = script.exports_sync.find_tag_id_by_name(SERVICE, "CLAUDE_TX")
br = script.exports_sync.get_pokemon_for_tag(SERVICE, ftid['idx'])
print(f"Server CLAUDE_TX count now: {br['dump']['+0x18_listish']['count']}")
sess.detach()
