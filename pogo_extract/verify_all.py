"""Full verification: check EVERY pokemon for CLAUDE_TX presence and cross-reference cull_decision."""
import frida, sqlite3, json, time

mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("bulk_tag.js","r",encoding="utf-8").read())
script.on("message", lambda m, data: None)
script.load()
script.exports_sync.init_status()
print("Indexing pokemon protos...")
idx = script.exports_sync.index_pokemon()
print(f"  indexed: {idx['count']}")

real = "0x71bed7fe80"

conn = sqlite3.connect("pokemon.db")
c = conn.cursor()
c.execute("SELECT uid, uid_hex, species_name, cp, iv_pct, cull_decision, is_hundo, is_lucky, is_shiny, is_best_buddy, alignment FROM pokemon")
rows = c.fetchall()
conn.close()
print(f"Total pokemon to check: {len(rows)}")

results = {
    "TP": [],  # TRANSFER with CLAUDE_TX (correct)
    "FP": [],  # KEEP with CLAUDE_TX (BAD - false positive)
    "FN": [],  # TRANSFER without CLAUDE_TX (coverage gap)
    "TN": [],  # KEEP without CLAUDE_TX (correct)
    "PROTO_NOT_FOUND": [],  # couldn't resolve to heap pointer
    "TAGS_NULL": [],  # GetAllTags returned null
}

t0 = time.time()
for i, (uid, uid_hex, sp, cp, iv, decision, is_h, is_l, is_s, is_b, alignment) in enumerate(rows):
    low = uid & 0xFFFFFFFF; high = (uid >> 32) & 0xFFFFFFFF
    if low > 0x7FFFFFFF: low -= 0x100000000
    if high > 0x7FFFFFFF: high -= 0x100000000
    p = script.exports_sync.find_pokemon_proto(low, high)
    if not p.get("ok"):
        results["PROTO_NOT_FOUND"].append((uid_hex, sp, cp, iv, decision))
        continue
    res = script.exports_sync.get_pokemon_tags(real, p["ptr"])
    if not res.get("ok"):
        results["TAGS_NULL"].append((uid_hex, sp, cp, iv, decision))
        continue
    tags = res.get("tags") or []
    has_tx = "CLAUDE_TX" in tags
    rec = (uid_hex, sp, cp, iv, decision, is_h, is_l, is_s, is_b, alignment, tags)
    if decision == "TRANSFER" and has_tx: results["TP"].append(rec)
    elif decision == "KEEP" and has_tx: results["FP"].append(rec)
    elif decision == "TRANSFER" and not has_tx: results["FN"].append(rec)
    else: results["TN"].append(rec)

    if (i+1) % 500 == 0:
        elapsed = time.time() - t0
        rate = (i+1)/elapsed
        eta = (len(rows)-i-1)/rate
        print(f"  {i+1}/{len(rows)} | TP={len(results['TP'])} FP={len(results['FP'])} FN={len(results['FN'])} TN={len(results['TN'])} not_found={len(results['PROTO_NOT_FOUND'])} | rate={rate:.0f}/s eta={eta:.0f}s")

print()
print("=" * 70)
print("FULL VERIFICATION RESULTS")
print("=" * 70)
print(f"  True Positive (TRANSFER + tagged):  {len(results['TP'])}")
print(f"  FALSE POSITIVE (KEEP + tagged):     {len(results['FP'])}  <-- safety violation if > 0")
print(f"  False Negative (TRANSFER + untagged): {len(results['FN'])}  <-- coverage gap")
print(f"  True Negative (KEEP + untagged):     {len(results['TN'])}")
print(f"  Proto not in heap:                  {len(results['PROTO_NOT_FOUND'])}")
print(f"  GetAllTags returned null:           {len(results['TAGS_NULL'])}")

if results["FP"]:
    print()
    print("=== FALSE POSITIVES (untouchables tagged - DANGER) ===")
    for r in results["FP"][:50]:
        uid_hex, sp, cp, iv, decision, is_h, is_l, is_s, is_b, alignment, tags = r
        why = []
        if is_h: why.append("hundo")
        if is_l: why.append("lucky")
        if is_s: why.append("shiny")
        if is_b: why.append("best_buddy")
        if alignment != 0: why.append(f"align={alignment}")
        print(f"  {uid_hex} {sp:18s} CP{cp:>4} IV{iv:>5}% kept_because={why} tags={tags}")

# Save full
with open("verify_all_result.json","w") as f:
    json.dump({k: v if k in ("PROTO_NOT_FOUND","TAGS_NULL") else len(v) for k, v in results.items()}, f, indent=2)
    # also dump the actual records
import pickle
with open("verify_all_raw.pkl","wb") as f: pickle.dump(results, f)

sess.detach()
