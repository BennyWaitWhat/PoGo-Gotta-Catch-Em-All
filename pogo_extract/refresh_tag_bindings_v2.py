"""Refresh DB tag membership from authoritative binding service (v2).

Refactor of refresh_tag_bindings.py using pogo_il2cpp helper:
  - Singleton lookup via liveness API (no 60s hook-and-wait).
  - No hardcoded SVC/BAG fallback.
  - Bag walk reused from pogo_il2cpp.walk_bag_protos.
  - il2cpp_runtime_class_init called on TaggingRpcService at startup.

Note: PoGo has two parallel object trees (likely main + Unity-editor/scene-pool).
Both PokemonBagImpl and TaggingRpcService appear twice. The tag bindings of
either svc instance resolve cleanly against its paired bag's protos and yield
identical (uid -> tag) sets. We merge both bags' proto->uid maps so any svc
choice resolves all proto pointers.
"""
import sqlite3
import time
from collections import defaultdict

import pogo_il2cpp as pg

_T0 = time.time()
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")
_tick("start")

sess, pid = pg.get_session()
_tick(f"get_session -> pid={pid}")

# find_singleton asserts ==1 hit; PokemonBagImpl + TaggingRpcService each return 2.
# Use the underlying RPC directly to get all live instances.
script = pg.get_script_with_helpers(sess)
try:
    bag_hits = script.exports_sync.find_singleton('Niantic.Holoholo.Internal', 'PokemonBagImpl')['hits']
    svc_hits = script.exports_sync.find_singleton('Niantic.Holoholo.Tagging', 'TaggingRpcService')['hits']
finally:
    script.unload()
_tick(f"liveness scan -> bag hits={bag_hits} svc hits={svc_hits}")

# Walk every bag and merge proto -> uid. The two bags share their proto pointers
# in disjoint sets, so merging is safe (no key collisions).
proto_to_uid = {}
total_bag_entries = 0
for ba in bag_hits:
    uid_to_proto = pg.walk_bag_protos(sess, ba)
    total_bag_entries += len(uid_to_proto)
    for uid, proto in uid_to_proto.items():
        proto_to_uid[proto] = uid
_tick(f"walked {len(bag_hits)} bag(s), {total_bag_entries} entries, {len(proto_to_uid)} unique protos")

# Enumerate tags + bindings on the first svc candidate. class_init it first.
TAG_ENUM_JS = r"""
rpc.exports = {
    enumTagBindings: function(svcAddrStr) {
        var svcCls = cFN('Niantic.Holoholo.Tagging', 'TaggingRpcService');
        class_init(svcCls);
        var gnt  = cMN(svcCls, 'get_NumberOfTags', 0);
        var gctb = cMN(svcCls, 'GetCachedTagToPokemonBindingForIndex', 1);
        var svc = ptr(svcAddrStr);
        var ret = rI(gnt, svc, ptr(0), null);
        var totalTags = ret.add(0x10).readS32();
        var out = {};
        for (var i = 0; i < totalTags; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var bp = rI(gctb, svc, args, null);
            if (bp.isNull()) continue;
            var tagProto = bp.add(0x10).readPointer();
            var name = '';
            try {
                var ns = tagProto.add(0x40).readPointer();
                if (!ns.isNull()) {
                    var len = ns.add(0x10).readS32();
                    if (len > 0 && len < 100) {
                        var chars = [];
                        for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                        name = chars.join('');
                    }
                }
            } catch(e) {}
            var listPtr = bp.add(0x18).readPointer();
            var count = listPtr.add(0x18).readS32();
            var items = listPtr.add(0x10).readPointer();
            var protos = [];
            for (var j = 0; j < count; j++) {
                try {
                    protos.push(items.add(0x20 + j*8).readPointer().toString());
                } catch(e) {}
            }
            out[name] = {idx: i, count: count, protos: protos};
        }
        return {ok: true, totalTags: totalTags, bindings: out};
    }
};
"""

svc_addr = svc_hits[0]
_rpc = time.time()
script = pg.get_script_with_helpers(sess, TAG_ENUM_JS)
try:
    r = script.exports_sync.enum_tag_bindings(svc_addr)
finally:
    script.unload()
_tick(f"enum_tag_bindings(svc={svc_addr}) RPC took {time.time()-_rpc:.2f}s")

bindings = {}
for name, b in r['bindings'].items():
    uids = [proto_to_uid[p] for p in b['protos'] if p in proto_to_uid]
    bindings[name] = {'idx': b['idx'], 'count': b['count'], 'uids': uids}
    print(f"  {name}: count={b['count']} resolved={len(uids)}")

# Update DB
_db_start = time.time()
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
cols = {row[1] for row in c.execute('PRAGMA table_info(pokemon)').fetchall()}
if 'auth_tag_names' not in cols:
    c.execute("ALTER TABLE pokemon ADD COLUMN auth_tag_names TEXT")
c.execute("UPDATE pokemon SET auth_tag_names=NULL")
_tick(f"DB reset auth_tag_names ({time.time()-_db_start:.2f}s)")

uid_to_tags = defaultdict(list)
for name, b in bindings.items():
    for uid_str in b['uids']:
        uid_unsigned = int(uid_str)
        uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
        uid_to_tags[uid_hex].append(name)

n = 0
_loop = time.time()
for uid_hex, tags in uid_to_tags.items():
    c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?", (';'.join(tags), uid_hex))
    n += 1
_tick(f"per-uid UPDATE loop done ({n} rows in {time.time()-_loop:.2f}s)")
conn.commit()
_tick("conn.commit done")
print(f"\nUpdated auth_tag_names for {n} pokemon")
sess.detach()
_tick("done")
