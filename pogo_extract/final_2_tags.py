"""Find and tag the remaining 2 Evolve Me adds (Scatterbug Ocean + Tandemaus)."""
import frida, json, time, subprocess, sqlite3
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f'PID: {adb_pid}')
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

BAG = '0x798ae7c780'
SVC = '0x798a77fd00'
ADD_UIDS_HEX = ['4c808fe3eb3d1cbe', '447d2d2b9ac25db8']

c = sqlite3.connect('pokemon.db').cursor()
def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
def hex_to_uid_str(uh):
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    return to_uid_str(r[0]) if r else None
add_str = [hex_to_uid_str(u) for u in ADD_UIDS_HEX]
print(f"Looking for uid_strs: {add_str}")

# Re-walk bag and dump matching keys
js_walk = """
rpc.exports = {
    walkAndFind: function(bag, uids) {
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
        var found = {}; var allKeys = []; var node = head; var iters = 0;
        while (node && !node.isNull() && iters < count + 200) {
            try {
                var key = node.add(0x28).readU64().toString();
                allKeys.push(key);
                if (wanted[key]) found[key] = node.add(0x30).readPointer().toString();
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }
        return {iters: iters, totalKeys: allKeys.length, found: found, sampleLastKeys: allKeys.slice(-5), sampleFirstKeys: allKeys.slice(0,5)};
    }
};
"""
walker = sess.create_script(js_walk)
walker.load()
r = walker.exports_sync.walk_and_find(BAG, add_str)
print(f"Walked iters={r['iters']} keys={r['totalKeys']}")
print(f"  first 5: {r['sampleFirstKeys']}")
print(f"  last 5: {r['sampleLastKeys']}")
print(f"Found: {r['found']}")
walker.unload()

# If found, tag them
if r['found']:
    script = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
    script.load()
    script.exports_sync.init_status()
    ftid = script.exports_sync.find_tag_id_by_name(SVC, 'Evolve Me')
    print(f"\ntag idx={ftid['idx']}")
    ptrs = list(r['found'].values())
    print(f"Tagging {len(ptrs)} ptrs...")
    res = script.exports_sync.bulk_tag_many(SVC, ftid['tagProtoAddr'], ptrs)
    print(f"  result: {res}")
    time.sleep(2)
    chk = script.exports_sync.get_pokemon_for_tag(SVC, ftid['idx'])
    print(f"\nFinal Evolve Me count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")
else:
    print("\n!! Neither uid found in bag walk - they might have evolved or been transferred")
    # Check current state
    for uh in ADD_UIDS_HEX:
        rr = c.execute("SELECT in_bag, species_name, form, iv_total FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
        print(f"  {uh}: {rr}")
sess.detach()
