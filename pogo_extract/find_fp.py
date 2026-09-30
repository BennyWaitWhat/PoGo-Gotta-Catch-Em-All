"""Find the false positive: any KEEP pokemon with CLAUDE_TX."""
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

conn = sqlite3.connect("pokemon.db")
c = conn.cursor()
c.execute("SELECT uid, uid_hex, species_name, cp, iv_pct, form, is_hundo, is_lucky, is_shiny, is_best_buddy, alignment FROM pokemon WHERE cull_decision='KEEP'")
keep_rows = c.fetchall()
conn.close()
print(f"Checking {len(keep_rows)} KEEP pokemon for CLAUDE_TX...")

fps = []
for i, (uid, uid_hex, sp, cp, iv, form, ih, il, isn, ib, al) in enumerate(keep_rows):
    low = uid & 0xFFFFFFFF; high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    p = script.exports_sync.find_pokemon_proto(low, high)
    if not p.get("ok"): continue
    try:
        res = script.exports_sync.get_pokemon_tags(real, p["ptr"])
    except: continue
    if not res.get("ok"): continue
    tags = res.get("tags") or []
    if "CLAUDE_TX" in tags:
        fps.append((uid_hex, sp, cp, iv, form, tags, ih, il, isn, ib, al))
        print(f"  FP: {uid_hex} {sp} CP{cp} IV{iv}% form={form} tags={tags} hundo={ih} lucky={il} shiny={isn} bb={ib} align={al}")
    if (i+1) % 500 == 0:
        print(f"  ...{i+1}/{len(keep_rows)} fps={len(fps)}")

print(f"\nTotal false positives: {len(fps)}")
with open("false_positives.json","w") as f: json.dump([list(r) for r in fps], f, indent=2)
sess.detach()
