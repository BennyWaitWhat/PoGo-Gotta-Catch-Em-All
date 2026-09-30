"""Quick re-poll of just tag_ids to update fresh_tag_ids in DB."""
import frida, json, time, sqlite3

mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open("fresh_poll.js","r",encoding="utf-8").read())
script.load()
script.exports_sync.init_status()
print("Polling...")
r = script.exports_sync.fresh_poll_all()
print(f"Done. ok={r.get('ok')}, withTags={r['stats'].get('withTags')}")

CLAUDE_TX = '15974071496501899036'
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

# Update fresh_tag_ids only
n_updated = 0
n_with_claude = 0
for uid_str, rec in r['results'].items():
    tag_ids = ';'.join(rec.get('tagIds', []))
    uid = int(uid_str)
    if uid > (2**63 - 1):
        uid_signed = uid - 2**64
    else:
        uid_signed = uid
    uid_hex = f"{uid & 0xFFFFFFFFFFFFFFFF:016x}"
    c.execute("UPDATE pokemon SET fresh_tag_ids=? WHERE uid_hex=?", (tag_ids, uid_hex))
    n_updated += c.rowcount
    if CLAUDE_TX in tag_ids:
        n_with_claude += 1

conn.commit()
print(f"Updated {n_updated} rows. {n_with_claude} have CLAUDE_TX")
conn.close()
sess.detach()
