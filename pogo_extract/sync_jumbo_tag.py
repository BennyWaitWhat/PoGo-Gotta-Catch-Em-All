"""Add 9 new JUMBOs (size_category=5 not in server tag) to server JUMBO tag."""
import frida, json, time, subprocess, sqlite3, sys
sys.stdout.reconfigure(line_buffering=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

BAG = '0x7711811980'
SVC = '0x7708cb2a00'

c = sqlite3.connect('pokemon.db').cursor()
rows = c.execute("""SELECT uid_hex, uid, species_name, iv_total, weight_kg
                    FROM pokemon
                    WHERE in_bag=1 AND pokemon_size_category=5
                    AND (auth_tag_names IS NULL OR auth_tag_names NOT LIKE '%JUMBO%')""").fetchall()
print(f"New JUMBOs to add: {len(rows)}")
for r in rows: print(f"  {r[0]} {r[2]} iv={r[3]} w={r[4]:.2f}kg")

def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
uid_strs = [(r[0], to_uid_str(r[1])) for r in rows]

js_walk = """
rpc.exports = {
    findProtos: function(bag, uids) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG=bind('il2cpp_domain_get','pointer',[]);
        var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cMN=bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
        var rI=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32();
        var gi=null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){gi=i;break;} }
        var cls=cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga=cMN(cls, Memory.allocUtf8String('get_AllPokemon'),0);
        var exc=Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values=rI(ga, ptr(bag), ptr(0), exc);
        var lhm=values.add(0x10).readPointer();
        var list=lhm.add(0x18).readPointer();
        var head=list.add(0x10).readPointer();
        var count=list.add(0x18).readS32();
        var wanted={}; for (var i=0;i<uids.length;i++) wanted[uids[i]]=true;
        var found={}; var node=head; var iters=0;
        while (node && !node.isNull() && iters < count + 200) {
            try {
                var key=node.add(0x28).readU64().toString();
                if (wanted[key]) found[key] = node.add(0x30).readPointer().toString();
                var next=node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node=next;
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
print(f"\nFound protos: {len(found)}/{len(uid_strs)}")

bulk = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
bulk.load(); bulk.exports_sync.init_status()

ftid = bulk.exports_sync.find_tag_id_by_name(SVC, 'JUMBO')
print(f"JUMBO tag info: idx={ftid.get('idx')} tagProto={ftid.get('tagProtoAddr')}")
if not ftid.get('ok'):
    print("FAIL: JUMBO tag not found"); sess.detach(); exit(1)

ptrs = [found[u] for _, u in uid_strs if u in found]
if not ptrs:
    print("No ptrs"); sess.detach(); exit(0)

# Warm-up
bulk.exports_sync.bulk_tag_many(SVC, ftid['tagProtoAddr'], ptrs[:1])
time.sleep(0.8)
res = bulk.exports_sync.bulk_tag_many(SVC, ftid['tagProtoAddr'], ptrs)
print(f"Tag result: built {res.get('built')}/{len(ptrs)}, ok={res.get('ok')}")
time.sleep(2)
chk = bulk.exports_sync.get_pokemon_for_tag(SVC, ftid['idx'])
print(f"Final JUMBO count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")
sess.detach()
