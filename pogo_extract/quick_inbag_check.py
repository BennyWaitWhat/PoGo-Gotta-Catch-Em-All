"""Walk bag with known pointer, dump UIDs only, update in_bag flags."""
import frida, json, subprocess, sqlite3
BAG = '0x79c5a97800'
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    walk: function(bagAddr) {
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
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var bagCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga = cMN(bagCls, Memory.allocUtf8String('get_AllPokemon'), 0);
        var bag = ptr(bagAddr);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = rI(ga, bag, ptr(0), exc);
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        var lcount = list.add(0x18).readS32();
        var uids = [];
        var node = head; var iters = 0;
        while (node && !node.isNull() && iters < lcount + 100) {
            try {
                var key = node.add(0x28).readU64().toString();
                uids.push(key);
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }
        return {count: lcount, uids: uids};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.walk(BAG)
print(f"Bag list count: {r['count']}, walked: {len(r['uids'])}")

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
auth_uids = set()
for uid_str in r['uids']:
    uid_unsigned = int(uid_str)
    uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
    auth_uids.add(uid_hex)
c.execute("UPDATE pokemon SET in_bag=0")
n = 0
for uh in auth_uids:
    n += c.execute("UPDATE pokemon SET in_bag=1 WHERE uid_hex=?", (uh,)).rowcount
print(f"Marked in_bag=1 for {n} DB rows")
db_uids = set(r2[0] for r2 in c.execute("SELECT uid_hex FROM pokemon").fetchall())
new_uids = auth_uids - db_uids
ghost = db_uids - auth_uids
print(f"NEW (not in DB): {len(new_uids)}")
print(f"GHOSTS (in DB, not in bag): {len(ghost)}")
conn.commit()
sess.detach()
