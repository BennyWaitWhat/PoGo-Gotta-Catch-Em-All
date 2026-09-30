"""Untag the 87 false positives identified by fresh poll + comprehensive untouchable rules.

Uses bulk_tag.js which has bulkUntagOne. Fresh Frida session.
"""
import frida, json, time

with open('untag_list_v3.json') as f:
    targets = json.load(f)
print(f'Loaded {len(targets)} targets to untag')

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
script.exports_sync.hook_for_real_instance(180)
print(">>> OPEN PoGo's Manage Tags screen (Pokemon -> filter dropdown -> any tag) (waiting up to 180s)...")
real = None
for i in range(180):
    time.sleep(1)
    try:
        cap = script.exports_sync.get_captured()
        if cap.get("captured"):
            real = list(cap["captured"].keys())[0]
            print(f"captured: {real}")
            break
    except: pass
    if i % 15 == 0 and i > 0:
        print(f"  still waiting... {i}/180s")
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

print(f"\nUntagging {len(targets)} pokemon...")

ok = 0
fail = 0
fail_log = []
for t in targets:
    uid = t['uid']
    low = uid & 0xFFFFFFFF; high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    p = script.exports_sync.find_pokemon_proto(low, high)
    if not p.get("ok"):
        fail += 1
        fail_log.append({'uid_hex': t['uid_hex'], 'reason': 'find_proto_failed', 'species': t.get('species')})
        continue
    success = False
    last_err = None
    for retry in range(3):
        try:
            r = script.exports_sync.bulk_untag_one(real, p["ptr"], tag_proto)
            if r.get("ok"):
                ok += 1
                success = True
                break
            else:
                last_err = r
        except Exception as e:
            last_err = str(e)
        time.sleep(0.5)
    if not success:
        fail += 1
        fail_log.append({'uid_hex': t['uid_hex'], 'species': t.get('species'), 'err': str(last_err)})
    if (ok+fail) % 20 == 0:
        print(f"  progress: ok={ok} fail={fail} ({ok+fail}/{len(targets)})")
    time.sleep(0.25)

print(f"\nFinal: untagged={ok} failed={fail}")
if fail_log:
    with open('untag_v3_fail.json', 'w') as f:
        json.dump(fail_log, f, indent=2)
    print(f"Wrote untag_v3_fail.json")
sess.detach()
