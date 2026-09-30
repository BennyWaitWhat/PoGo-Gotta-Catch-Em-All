"""Get the COMPLETE pokemon inventory via PokemonBagImpl.get_AllPokemon."""
import frida, json, time, subprocess

adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PoGo PID: {adb_pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(adb_pid)
script = sess.create_script(open("full_inventory.js","r",encoding="utf-8").read())

captured_msgs = []
def on(m, data):
    p = m.get("payload",{})
    if isinstance(p,dict):
        msg = p.get("msg","")
        captured_msgs.append(msg)
        if "captured bag" in msg or "captured" in msg:
            print(f"  [hook] {msg}")
script.on("message", on)
script.load()
print(script.exports_sync.init_status())

# First try heap scan for bag instance
print("\nHeap scan for PokemonBagImpl...")
sr = script.exports_sync.scan_for_bag_instance()
print(f"  hits: {sr.get('hits')}")

# Hook bag methods
print("\nInstalling hooks on PokemonBagImpl...")
hr = script.exports_sync.hook_for_bag_instance()
print(f"  hooked {hr.get('hookedCount')} methods")

print(">>> Interact with PoGo (open inventory, scroll, anything) - waiting up to 60s for hook to fire...")
bag_inst = None
for i in range(60):
    time.sleep(1)
    bi = script.exports_sync.get_bag_instance()
    if bi.get("bag"):
        bag_inst = bi["bag"]
        break

# Fallback: try heap-scan hits directly
if not bag_inst:
    print("\nHook didn't fire, trying heap-scan candidates...")
    for cand in sr.get('hits', []):
        print(f"  trying {cand}")
        script.exports_sync.set_bag_instance(cand)
        try:
            r = script.exports_sync.get_all_pokemon(cand)
            if r.get("ok") and r.get("listSize") and r["listSize"] > 1000:
                print(f"  CANDIDATE WORKS: count={r.get('count')} listSize={r['listSize']}")
                bag_inst = cand
                break
            else:
                print(f"    no: {r}")
        except Exception as e:
            print(f"    exc: {e}")

if not bag_inst:
    print("FAILED to get bag instance")
    sess.detach()
    exit(1)

print(f"\nUsing bag instance: {bag_inst}")
r = script.exports_sync.get_all_pokemon(bag_inst)
print(f"Result: count={r.get('count')} listSize={r.get('listSize')}")
print(f"Layout tried: {json.dumps(r.get('layoutTried'), indent=2)}")

if not r.get("listSize") or r["listSize"] < 100:
    print("Bag list is too small or wrong layout")
    sess.detach()
    exit(1)

# Find the right offsets
size_off = 0x18; items_off = 0x10
for trial in r.get('layoutTried', []):
    if trial.get('sz', 0) > 1000:
        size_off = trial['tr']['sizeOff']
        items_off = trial['tr']['itemsOff']
        break

print(f"\nUsing size_off=0x{size_off:x}, items_off=0x{items_off:x}")
print("Dumping all proto pointers...")
dr = script.exports_sync.dump_all_proto_ptrs(bag_inst, size_off, items_off, 0x20)
if not dr.get("ok"):
    print(f"FAILED: {dr}")
    sess.detach()
    exit(1)
print(f"Got {dr.get('count')} proto pointers")

ptrs = dr["ptrs"]
print(f"\nReading proto data in batches of 500...")
all_results = {}
for i in range(0, len(ptrs), 500):
    chunk = ptrs[i:i+500]
    rb = script.exports_sync.read_proto_batch(chunk)
    if rb.get("ok"):
        all_results.update(rb["results"])
        print(f"  batch {i//500+1}: {len(rb['results'])} entries (total: {len(all_results)})")
    else:
        print(f"  batch {i//500+1} FAILED")

print(f"\nTotal pokemon read: {len(all_results)}")

# Save
with open("full_inventory.json","w") as f:
    json.dump({"count": len(all_results), "results": all_results}, f)
print("Saved full_inventory.json")

sess.detach()
