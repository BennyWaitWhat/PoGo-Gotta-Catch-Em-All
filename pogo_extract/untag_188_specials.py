"""Capture real instance + untag all 188 specials we missed."""
import frida, sqlite3, time
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
captured = []
def on(m, data):
    p = m.get("payload",{})
    if isinstance(p,dict):
        msg = p.get("msg","")
        if "captured this @" in msg:
            captured.append(msg.split("@")[1].strip().split(" ")[0])
script.on("message", on)
script.load()
script.exports_sync.init_status()
script.exports_sync.hook_for_real_instance(60)
print(">>> Open PoGo's tag manager so hook fires (waiting up to 60s)...")
real = None
for i in range(60):
    time.sleep(1)
    try:
        cap = script.exports_sync.get_captured()
        if cap.get("captured"):
            real = list(cap["captured"].keys())[0]
            print(f"captured: {real}")
            break
    except: pass
if not real:
    print("FAILED to capture real instance")
    exit(1)

script.exports_sync.index_pokemon()
ftid = script.exports_sync.find_tag_id_by_name(real, "CLAUDE_TX")
if not ftid.get("ok"):
    print(f"CLAUDE_TX find failed: {ftid}")
    exit(1)
tag_proto = ftid["tagProtoAddr"]
print(f"CLAUDE_TX tagProto: {tag_proto}")

conn = sqlite3.connect("pokemon.db")
c = conn.cursor()
c.execute("""SELECT uid, uid_hex, species_name, cp,
       bread_mode, has_location_card, display_costume
   FROM pokemon
   WHERE cull_decision='TRANSFER'
     AND (bread_mode!=0 OR has_location_card=1 OR is_strong_pokemon=1
          OR display_costume!=0 OR current_temp_evolution!=0
          OR has_mega_evolution_level=1)""")
targets = c.fetchall()
conn.close()
print(f"\nUntagging {len(targets)} pokemon...")

ok = 0
fail = 0
for uid, uid_hex, sp, cp, bread, locc, costume in targets:
    low = uid & 0xFFFFFFFF; high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    p = script.exports_sync.find_pokemon_proto(low, high)
    if not p.get("ok"):
        fail += 1; continue
    # Try with retry
    for retry in range(3):
        r = script.exports_sync.bulk_untag_one(real, p["ptr"], tag_proto)
        if r.get("ok"):
            ok += 1; break
        time.sleep(0.4)
    else:
        fail += 1
    if (ok+fail) % 30 == 0:
        print(f"  progress: ok={ok} fail={fail}")
    time.sleep(0.2)
print(f"\nFinal: untagged={ok} failed={fail}")
sess.detach()
