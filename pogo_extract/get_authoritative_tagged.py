"""Get the authoritative list of CLAUDE_TX-tagged pokemon from TagToPokemonBinding service.

The binding stores PokemonProto pointers (not UIDs). We dereference each pointer to
get the underlying UID.
"""
import frida, json, sqlite3
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(d.enumerate_processes()[0].pid)
script = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
script.load()
script.exports_sync.init_status()
SERVICE = '0x6ff1d41f80'

# Get binding entries
r = script.exports_sync.get_pokemon_for_tag(SERVICE, 16)
listish = r['dump']['+0x18_listish']
proto_ptrs = [int(s['asI64']) for s in listish['sample']]
print(f"Server-side CLAUDE_TX-tagged count: {listish['count']}")
print(f"Got {len(proto_ptrs)} proto pointers")

# For each proto ptr, read UID at offset 32 (low) and 36 (high)
# Build a mini script eval since JS has direct memory access
proto_ptrs_hex = [f"0x{p:x}" for p in proto_ptrs]

# Inject a helper to read UIDs
script.unload()
helper_js = """
rpc.exports = {
    readUidsFromProtos: function(ptrArray) {
        var results = [];
        for (var i = 0; i < ptrArray.length; i++) {
            try {
                var p = ptr(ptrArray[i]);
                var lo = p.add(32).readS32();
                var hi = p.add(36).readS32();
                var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
                var pid = p.add(40).readS32();
                results.push({ptr: ptrArray[i], uid: uidNum.toString(), pid: pid});
            } catch(e) {
                results.push({ptr: ptrArray[i], err: e.message});
            }
        }
        return {ok:true, results: results};
    }
};
"""
script2 = sess.create_script(helper_js)
script2.load()
result = script2.exports_sync.read_uids_from_protos(proto_ptrs_hex)
sess.detach()

uids = []
for entry in result['results']:
    if 'uid' in entry:
        uid_unsigned = int(entry['uid'])
        uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
        uids.append({'ptr': entry['ptr'], 'uid_hex': uid_hex, 'uid_unsigned': uid_unsigned, 'pid': entry['pid']})
    else:
        print(f"  ERR: {entry}")

print(f"\nResolved {len(uids)} UIDs")

# Save and reconcile with DB
with open('authoritative_tagged.json','w') as f:
    json.dump(uids, f, indent=2)

# Now mark in DB which pokemon are AUTHORITATIVELY tagged
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
if 'authoritative_claudetx' not in cols:
    c.execute("ALTER TABLE pokemon ADD COLUMN authoritative_claudetx INTEGER")
c.execute("UPDATE pokemon SET authoritative_claudetx=0")
for u in uids:
    c.execute("UPDATE pokemon SET authoritative_claudetx=1 WHERE uid_hex=?", (u['uid_hex'],))
conn.commit()

# Reconcile
n_tagged = c.execute("SELECT COUNT(*) FROM pokemon WHERE authoritative_claudetx=1").fetchone()[0]
n_should_keep = c.execute("SELECT COUNT(*) FROM pokemon WHERE authoritative_claudetx=1 AND cull_decision_v2='KEEP'").fetchone()[0]
n_should_xfer = c.execute("SELECT COUNT(*) FROM pokemon WHERE authoritative_claudetx=1 AND cull_decision_v2='TRANSFER'").fetchone()[0]
n_missing = c.execute("SELECT COUNT(*) FROM pokemon WHERE authoritative_claudetx=0 AND cull_decision_v2='TRANSFER'").fetchone()[0]

print(f"\n=== AUTHORITATIVE STATE ===")
print(f"  Currently tagged:                {n_tagged}")
print(f"  Tagged & should KEEP (FPs):      {n_should_keep}")
print(f"  Tagged & should TRANSFER (good): {n_should_xfer}")
print(f"  Not tagged & should TRANSFER:    {n_missing}")

# Show FPs
print(f"\n=== Remaining false positives (still tagged but should keep) ===")
for r in c.execute('''SELECT uid_hex, species_name, cp, iv_pct, cull_reason_v2
    FROM pokemon WHERE authoritative_claudetx=1 AND cull_decision_v2='KEEP'
    LIMIT 30'''):
    print(f"  {r[0]} {r[1]:15s} CP{r[2]:4d} IV{r[3]:.1f} -> {r[4][:60]}")

conn.close()
