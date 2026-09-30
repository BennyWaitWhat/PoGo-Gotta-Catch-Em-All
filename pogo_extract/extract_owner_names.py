"""Extract original owner nickname for all traded/lucky pokemon."""
import frida, time, subprocess, sqlite3

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Get list of traded/lucky pokemon
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
cols = {r[1] for r in c.execute('PRAGMA table_info(pokemon)').fetchall()}
if 'original_owner_name' not in cols:
    c.execute('ALTER TABLE pokemon ADD COLUMN original_owner_name TEXT')
conn.commit()

rows = c.execute("SELECT uid_hex, uid FROM pokemon WHERE in_bag=1 AND (is_lucky=1 OR is_traded_flag_v2=1)").fetchall()
def to_uid(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
target_uids = [to_uid(r[1]) for r in rows]
print(f"Traded/Lucky pokemon to scan: {len(target_uids)}")

js = """
rpc.exports = {
    extractNames: function(uids) {
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

        // Walk bag, read original owner from each PokemonProto at +0x100 (string ptr)
        var bagCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga = cMN(bagCls, Memory.allocUtf8String('get_AllPokemon'), 0);
        // Need bag instance - heap scan won't work, but we can find via other means
        // Actually, just walk our existing bag pointer by finding any PokemonProto with the right UIDs

        var wanted = {}; for (var i = 0; i < uids.length; i++) wanted[uids[i]] = true;
        var results = {};

        // Scan rw- memory for PokemonProto klass byte pattern... or use a known bag
        // Alternative: heap-scan for protos and check each one's UID
        var protoCls = cFN(gi, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PokemonProto'));
        if (!protoCls || protoCls.isNull()) {
            var protoImg = null;
            for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-protos.dll'){ protoImg=i; break; } }
            protoCls = cFN(protoImg, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PokemonProto'));
        }
        // Build klass byte pattern
        var bn = BigInt(protoCls.toString());
        var pattern = '';
        for (var i = 0; i < 8; i++) {
            var b = Number((bn >> BigInt(i*8)) & 0xffn);
            pattern += ('0' + b.toString(16)).slice(-2) + ' ';
        }
        pattern = pattern.trim();

        var ranges = Process.enumerateRanges('rw-');
        for (var r = 0; r < ranges.length; r++) {
            if (ranges[r].size > 256*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, pattern).forEach(function(m){
                    try {
                        var p = m.address;
                        // PokemonProto: uid_low at +32, uid_high at +36
                        var lo = p.add(32).readS32();
                        var hi = p.add(36).readS32();
                        var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
                        var uidStr = uidNum.toString();
                        if (!wanted[uidStr] || results[uidStr] !== undefined) return;
                        // Read string ptr at +0x100
                        var strPtr = p.add(0x100).readPointer();
                        if (strPtr.isNull()) return;
                        var len = strPtr.add(0x10).readS32();
                        if (len <= 0 || len > 100) return;
                        var chars = [];
                        for (var ci = 0; ci < len; ci++) {
                            var ch = strPtr.add(0x14 + ci*2).readU16();
                            if (ch < 32 || ch > 126) { chars = null; break; }
                            chars.push(String.fromCharCode(ch));
                        }
                        if (chars) results[uidStr] = chars.join('');
                    } catch(e) {}
                });
            } catch(e) {}
        }
        return results;
    }
};
"""
script = sess.create_script(js)
script.load()
print("Scanning heap for proto + reading owner names...")
results = script.exports_sync.extract_names(target_uids)
print(f"Got names for {len(results)}/{len(target_uids)}")

# Update DB
for uid_str, name in results.items():
    uid_unsigned = int(uid_str)
    uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
    c.execute("UPDATE pokemon SET original_owner_name=? WHERE uid_hex=?", (name, uid_hex))
conn.commit()

# Show distinct names
print("\n=== Distinct original owner names ===")
for r in c.execute("""SELECT original_owner_name, COUNT(*) FROM pokemon
    WHERE in_bag=1 AND (is_lucky=1 OR is_traded_flag_v2=1) AND original_owner_name IS NOT NULL
    GROUP BY original_owner_name ORDER BY 2 DESC"""):
    print(f"  '{r[0]}': {r[1]}")

n_blank = c.execute("SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND (is_lucky=1 OR is_traded_flag_v2=1) AND (original_owner_name IS NULL OR original_owner_name = '')").fetchone()[0]
print(f"\nNo owner extracted: {n_blank}")
sess.detach()
