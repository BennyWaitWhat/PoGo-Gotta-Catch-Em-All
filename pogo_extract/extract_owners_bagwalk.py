"""Extract owner name via bag walk (more reliable than klass scan)."""
import frida, time, subprocess, sqlite3
BAG = '0x7ef8367a00'
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    extractAll: function(bag, uids) {
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
        var bagCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga = cMN(bagCls, Memory.allocUtf8String('get_AllPokemon'), 0);
        var inst = ptr(bag);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = rI(ga, inst, ptr(0), exc);
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        var count = list.add(0x18).readS32();
        var wanted = {}; for (var i = 0; i < uids.length; i++) wanted[uids[i]] = true;
        var results = {};
        var node = head; var iters = 0;
        while (node && !node.isNull() && iters < count + 100) {
            try {
                var key = node.add(0x28).readU64().toString();
                if (wanted[key]) {
                    var proto = node.add(0x30).readPointer();
                    try {
                        var strPtr = proto.add(0x100).readPointer();
                        if (!strPtr.isNull()) {
                            var len = strPtr.add(0x10).readS32();
                            if (len > 0 && len < 100) {
                                var chars = [];
                                for (var ci = 0; ci < len; ci++) {
                                    var c = strPtr.add(0x14 + ci*2).readU16();
                                    if (c < 32 || c > 126) { chars = null; break; }
                                    chars.push(String.fromCharCode(c));
                                }
                                if (chars) results[key] = chars.join('');
                                else results[key] = '';
                            } else { results[key] = ''; }
                        } else { results[key] = ''; }
                    } catch(e) { results[key] = ''; }
                }
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }
        return results;
    }
};
"""
script = sess.create_script(js)
script.load()
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
rows = c.execute("SELECT uid_hex, uid FROM pokemon WHERE in_bag=1 AND (is_lucky=1 OR is_traded_flag_v2=1)").fetchall()
def to_uid(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
target_uids = [to_uid(r[1]) for r in rows]
print(f"Scanning {len(target_uids)} traded/lucky")
results = script.exports_sync.extract_all(BAG, target_uids)
print(f"Got: {len(results)}")
# Update DB (clear existing first to overwrite stale)
for uid_str, name in results.items():
    uid_unsigned = int(uid_str)
    uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
    c.execute("UPDATE pokemon SET original_owner_name=? WHERE uid_hex=?", (name, uid_hex))
conn.commit()
sess.detach()

# Distinct counts
print("\n=== Distinct owners ===")
for r in c.execute("""SELECT original_owner_name, COUNT(*) FROM pokemon
    WHERE in_bag=1 AND (is_lucky=1 OR is_traded_flag_v2=1) AND original_owner_name IS NOT NULL
    GROUP BY original_owner_name ORDER BY 2 DESC"""):
    print(f"  '{r[0]}': {r[1]}")
n_blank = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (is_lucky=1 OR is_traded_flag_v2=1) AND (original_owner_name IS NULL OR original_owner_name = '')").fetchone()[0]
print(f"  (no owner): {n_blank}")
