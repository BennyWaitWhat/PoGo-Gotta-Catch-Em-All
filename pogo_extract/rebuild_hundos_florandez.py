"""Recreate Hundos + From Florandez tags and re-tag all members."""
import frida, json, time, subprocess, sqlite3, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

BAG = '0x73001bd980'
SVC = '0x7275723100'

c = sqlite3.connect('pokemon.db').cursor()

# Get UIDs to tag
hundos = [r[0] for r in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND iv_total=45").fetchall()]
florandez = [r[0] for r in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND (is_traded_flag_v2=1 OR is_lucky=1) AND lower(original_owner_name)='florandez'").fetchall()]
print(f"Hundos to tag: {len(hundos)}", flush=True)
print(f"From Florandez to tag: {len(florandez)}", flush=True)

# Walk bag for proto pointers
def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
all_uids = list(set(hundos + florandez))
uid_strs = []
for uh in all_uids:
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    if r: uid_strs.append((uh, to_uid_str(r[0])))

js_walk = """
rpc.exports = {
    findProtos: function(bag, uids) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cMN = bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
        var rI = bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga = cMN(cls, Memory.allocUtf8String('get_AllPokemon'), 0);
        var inst = ptr(bag);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = rI(ga, inst, ptr(0), exc);
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        var count = list.add(0x18).readS32();
        var wanted = {}; for (var i = 0; i < uids.length; i++) wanted[uids[i]] = true;
        var found = {}; var node = head; var iters = 0;
        while (node && !node.isNull() && iters < count + 200) {
            try {
                var key = node.add(0x28).readU64().toString();
                if (wanted[key]) found[key] = node.add(0x30).readPointer().toString();
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }
        return {found: found};
    }
};
"""
walker = sess.create_script(js_walk); walker.load()
r = walker.exports_sync.find_protos(BAG, [u[1] for u in uid_strs])
found = r['found']
print(f"Found protos: {len(found)}/{len(uid_strs)}", flush=True)
hex_to_proto = {uh: found[u] for uh, u in uid_strs if u in found}

# Load bulk_tag.js
bulk = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
bulk.load(); bulk.exports_sync.init_status()

# Create both tags
for tag_name, color in [('Hundos', 2), ('From Florandez', 6)]:
    print(f"\n=== Creating tag '{tag_name}' color={color} ===", flush=True)
    res = bulk.exports_sync.add_tag_on_instance(SVC, tag_name, color)
    print(f"  result: {res}", flush=True)
    time.sleep(1.5)

# Re-tag members
for tag_name, uids in [('Hundos', hundos), ('From Florandez', florandez)]:
    print(f"\n=== Tagging {len(uids)} as '{tag_name}' ===", flush=True)
    ftid = bulk.exports_sync.find_tag_id_by_name(SVC, tag_name)
    if not ftid.get('ok'):
        print(f"  FAIL: tag '{tag_name}' not found after creation", flush=True)
        continue
    ptrs = [hex_to_proto[uh] for uh in uids if uh in hex_to_proto]
    print(f"  {len(ptrs)} ptrs to tag, tagProto={ftid['tagProtoAddr']} idx={ftid['idx']}", flush=True)
    if not ptrs: continue
    # warm-up
    bulk.exports_sync.bulk_tag_many(SVC, ftid['tagProtoAddr'], ptrs[:1])
    time.sleep(0.8)
    for i in range(0, len(ptrs), 30):
        chunk = ptrs[i:i+30]
        res = bulk.exports_sync.bulk_tag_many(SVC, ftid['tagProtoAddr'], chunk)
        ok = 'ok' if res.get('ok') else f"FAIL {res.get('err')}"
        print(f"  batch {i//30+1} ({len(chunk)}): {ok} built={res.get('built',0)}", flush=True)
        time.sleep(0.4)
    time.sleep(2)
    chk = bulk.exports_sync.get_pokemon_for_tag(SVC, ftid['idx'])
    print(f"  Final {tag_name} count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}", flush=True)

sess.detach()
