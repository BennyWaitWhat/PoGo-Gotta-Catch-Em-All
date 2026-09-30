"""Find which pokemon have user's D-Max or G-MAX tags. Cross-check against cull TRANSFER list.
Any in TRANSFER list got tagged with CLAUDE_TX -> need to untag immediately."""
import frida, sqlite3, json, time
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
script.on("message", lambda m, data: None)
script.load()
script.exports_sync.init_status()
script.exports_sync.index_pokemon()
real = "0x71bed7fe80"

# Get tag list to map names to indices
listing = script.exports_sync.list_all_tags(real)
tag_idx_by_name = {}
for t in listing.get("tags", []):
    names = []
    def walk(x):
        if isinstance(x, dict):
            for k,v in x.items():
                if 'str' in k.lower() and isinstance(v,str) and v.strip() and len(v)<60: names.append(v)
                else: walk(v)
        elif isinstance(x, list):
            for y in x: walk(y)
    walk(t)
    if names:
        tag_idx_by_name[names[0]] = t.get("i")

print("Tag indices:")
for n, i in tag_idx_by_name.items(): print(f"  {n} -> {i}")

# Connect to DB
conn = sqlite3.connect("pokemon.db")
c = conn.cursor()
# Build proto-pointer-to-uid map
import json
# Get raw protos from the index by querying each candidate
# We have proto pointers from get_pokemon_for_tag bindings - need to read each and extract UID

# Approach: use Frida to read UID at offset +32 of each proto pointer
# Add helper to bulk_tag.js... actually use existing find_pokemon_proto in reverse.
# Simpler: read each proto pointer's bytes via Frida and parse UID

def read_uid_from_proto(proto_str):
    # Use Frida's evaluate via script.post or inline read
    pass

# Use Frida to read the proto's UID directly via a helper export
# Actually we have getPokemonTags - takes a proto pointer. But we want UID FROM proto pointer.
# Easiest: enumerate binding's pokemon list, get proto pointers, then look each up via binary read.

# Bigger approach: for each tag we care about, ask Frida to dump the binding's proto list and read UIDs
import struct

# Add a quick UID reader
script.unload()
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read() + """
rpc.exports.readProtoUid = function(ptrStr) {
    try {
        var p = ptr(ptrStr);
        var lo = p.add(32).readS32();
        var hi = p.add(36).readS32();
        // Combine to int64
        return {lo: lo, hi: hi};
    } catch(e) { return {err: e.message}; }
};
""")
script.on("message", lambda m, data: None)
script.load()
script.exports_sync.init_status()

# For each tag of interest, get its bindings
TARGETS = ["D-Max", "G-MAX", "Mega", "MegaHundos", "Hundos", "Shinyyy", "TeamEevee", "0-15-15", "UL", "Location Card", "U", "Trade", "Nundos", "Traded", "Trade to Osiris", "HUUUGE", "f u claude", "another test"]
all_user_tagged_uids = set()
for tag_name in TARGETS:
    if tag_name not in tag_idx_by_name: continue
    idx = tag_idx_by_name[tag_name]
    binding = script.exports_sync.get_pokemon_for_tag(real, idx)
    if not binding.get("ok"):
        print(f"{tag_name}: binding fail")
        continue
    dump = binding.get("dump", {})
    # Find the proto-list field
    for k, v in dump.items():
        if k.endswith("_listish") and isinstance(v, dict) and v.get("count", 0) > 0:
            count = v["count"]
            # We have only first 10 in sample - need full list. Re-read with extended sample.
            # For now, work with what we have; this is conservative
            print(f"{tag_name}: {count} pokemon tagged")
            for s in v.get("sample", []):
                proto_int = int(s["asI64"])
                if proto_int < 0: proto_int += 2**64
                proto_ptr = hex(proto_int)
                uid = script.exports_sync.read_proto_uid(proto_ptr)
                if uid.get("err"): continue
                lo = uid["lo"] & 0xFFFFFFFF
                hi = uid["hi"] & 0xFFFFFFFF
                full_uid = (hi << 32) | lo
                if full_uid >= 2**63: full_uid -= 2**64
                all_user_tagged_uids.add(full_uid)
            break

print(f"\nTotal user-tagged pokemon UIDs collected: {len(all_user_tagged_uids)}")

# Cross-check with cull TRANSFER list
c.execute("SELECT uid, uid_hex, species_name, cp, iv_pct FROM pokemon WHERE cull_decision='TRANSFER'")
transfers = c.fetchall()
conflicts = []
for uid, uid_hex, sp, cp, iv in transfers:
    if uid in all_user_tagged_uids:
        conflicts.append((uid_hex, sp, cp, iv))
print(f"\nTransferables that ARE user-tagged (FALSE POSITIVES): {len(conflicts)}")
for c_ in conflicts:
    print(f"  {c_}")

with open("user_tagged_conflicts.json","w") as f: json.dump(conflicts, f, indent=2)
sess.detach()
