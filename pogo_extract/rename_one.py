"""Single-mon nickname set/clear via rename_pokemon.js on the proven pogo_il2cpp gadget session.
Usage: python rename_one.py <uid_hex> [nickname]   (empty/omitted nickname = CLEAR -> reverts to species name)
"""
import sys, time, json
import pogo_il2cpp as pg

uid_hex = sys.argv[1]
nick = sys.argv[2] if len(sys.argv) > 2 else ""
uid = int(uid_hex, 16)
low = uid & 0xFFFFFFFF
high = (uid >> 32) & 0xFFFFFFFF
if low > 0x7FFFFFFF:  low -= 0x100000000
if high > 0x7FFFFFFF: high -= 0x100000000

sess, pid = pg.get_session()
print(f"attached pid={pid}; target uid={uid_hex} low={low} high={high} nick={nick!r}")
src = open("rename_pokemon.js", "r", encoding="utf-8").read()
script = sess.create_script(src)
def on_msg(m, d):
    if m.get("type") == "send":
        print("  [JS]", str(m["payload"].get("msg", m["payload"]))[:300])
    elif m.get("type") == "error":
        print("  [FRIDA-ERR]", m.get("description"))
script.on("message", on_msg)
script.load()

st = None
for i in range(25):
    st = script.exports_sync.init_status()
    if st.get("ready"):
        print("init ready:", st); break
    time.sleep(1)
if not st or not st.get("ready"):
    print("INIT FAILED:", st); sess.detach(); sys.exit(1)

r = script.exports_sync.count_pokemon()
print("heap protos:", r.get("count") if isinstance(r, dict) else r)

res = script.exports_sync.rename(low, high, nick)
print("RESULT:", json.dumps(res))
time.sleep(8)   # let the promise resolve / server round-trip
sess.detach()
print("detached.")
