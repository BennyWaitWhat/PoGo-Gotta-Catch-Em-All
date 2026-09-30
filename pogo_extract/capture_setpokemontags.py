"""Hook + capture user's SetPokemonTags call. User MUST create a tag and assign pokemon to it."""
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
hook = script.exports_sync.hook_for_real_instance(120)
print(f"Hooks: {hook['methods']}")
print()
print(">>>> NOW: in PoGo, create a new tag (any name) AND assign random pokemon to it <<<<")
print(">>>> I am polling every 3 seconds for SetPokemonTags fire <<<<")
print()

for i in range(60):
    time.sleep(3)
    cap = script.exports_sync.get_captured()
    captured_keys = list(cap.get("captured", {}).keys())
    spt = cap.get("setPokemonTagsArgs")
    add_args = cap.get("addTagArgs")
    if i % 5 == 0:
        print(f"  t={i*3}s instances={len(captured_keys)} addTag_seen={bool(add_args)} setPokemonTags_seen={bool(spt)}")
    if spt:
        print(f"\n>>>> CAPTURED SetPokemonTags <<<<")
        print(f"  this: {spt['thisPtr']}")
        print(f"  list: {spt['listPtr']}")
        print()
        print("Dumping List<PokemonTagChanges> structure...")
        dump = script.exports_sync.dump_captured_list()
        print(json.dumps(dump, indent=2))
        break

# Save final state
final = {
    "captured": script.exports_sync.get_captured(),
    "list_dump": script.exports_sync.dump_captured_list() if cap.get("setPokemonTagsArgs") else None
}
with open("setpokemontags_capture.json","w") as f: json.dump(final, f, indent=2)
print("\nSaved to setpokemontags_capture.json")
sess.detach()
