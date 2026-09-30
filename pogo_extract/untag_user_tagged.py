"""URGENT: Untag CLAUDE_TX from any pokemon that already has user-tags (GMAX, DMAX, etc.)."""
import frida, sqlite3, json, time
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read() + """
rpc.exports.readProtoUid = function(ptrStr) {
    try {
        var p = ptr(ptrStr);
        return {lo: p.add(32).readS32(), hi: p.add(36).readS32()};
    } catch(e) { return {err: e.message}; }
};
""")
script.on("message", lambda m, data: None)
script.load()
script.exports_sync.init_status()
script.exports_sync.index_pokemon()
real = "0x71bed7fe80"
ftid = script.exports_sync.find_tag_id_by_name(real, "CLAUDE_TX")
tag_proto = ftid["tagProtoAddr"]

# Get all user-tagged UIDs
TARGETS = ["D-Max","G-MAX","Mega","MegaHundos","Hundos","Shinyyy","TeamEevee","0-15-15","UL","Location Card","U","Trade","Nundos","Traded","Trade to Osiris","HUUUGE"]
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
    if names: tag_idx_by_name[names[0]] = t.get("i")

user_tagged_uids = set()
for tag_name in TARGETS:
    if tag_name not in tag_idx_by_name: continue
    binding = script.exports_sync.get_pokemon_for_tag(real, tag_idx_by_name[tag_name])
    if not binding.get("ok"): continue
    for k, v in binding.get("dump", {}).items():
        if k.endswith("_listish") and isinstance(v, dict) and v.get("count", 0) > 0:
            for s in v.get("sample", []):
                pi = int(s["asI64"])
                if pi < 0: pi += 2**64
                u = script.exports_sync.read_proto_uid(hex(pi))
                if u.get("err"): continue
                lo = u["lo"] & 0xFFFFFFFF
                hi = u["hi"] & 0xFFFFFFFF
                full = (hi << 32) | lo
                if full >= 2**63: full -= 2**64
                user_tagged_uids.add(full)
            break
print(f"Total user-tagged pokemon: {len(user_tagged_uids)}")

# Cross-check with TRANSFER list
conn = sqlite3.connect("pokemon.db")
c = conn.cursor()
c.execute("SELECT uid, uid_hex, species_name, cp, iv_pct FROM pokemon WHERE cull_decision='TRANSFER'")
transfers = c.fetchall()
conn.close()
to_untag = [(uid, uid_hex, sp, cp, iv) for uid, uid_hex, sp, cp, iv in transfers if uid in user_tagged_uids]
print(f"Conflicts to untag: {len(to_untag)}")

# Untag each
untagged = 0
failed = 0
for uid, uid_hex, sp, cp, iv in to_untag:
    low = uid & 0xFFFFFFFF; high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    p = script.exports_sync.find_pokemon_proto(low, high)
    if not p.get("ok"):
        failed += 1; continue
    r = script.exports_sync.bulk_untag_one(real, p["ptr"], tag_proto)
    if r.get("ok"):
        untagged += 1
    else:
        failed += 1
    if (untagged + failed) % 30 == 0:
        print(f"  progress: ok={untagged} failed={failed}")
    time.sleep(0.3)
print(f"\nFinal: untagged={untagged} failed={failed}")
sess.detach()
