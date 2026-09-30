"""Bulk-verify all NULL-field transfers via live proto read."""
import frida, subprocess, sqlite3, struct
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
BAG = '0x772ee1ea00'

c = sqlite3.connect('pokemon.db').cursor()
rows = c.execute("SELECT uid_hex, uid, species_name FROM pokemon WHERE in_bag=1 AND cull_decision_v8='TRANSFER' AND (is_best_buddy IS NULL OR is_deployed IS NULL)").fetchall()
print(f"NULL-field transfers to verify: {len(rows)}")

def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
uid_to_hex = {to_uid_str(r[1]): (r[0], r[2]) for r in rows}

js = """
rpc.exports = {
    walk: function(bag, uids) {
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
        var tA=bind('il2cpp_thread_attach','pointer',['pointer']); tA(dG());
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
                if (wanted[key]) {
                    var proto = node.add(0x30).readPointer();
                    // BestBuddy float at +172, deployed_fort string ptr at +0x40 (string base ptr empty if not deployed)
                    var bb_float = proto.add(172).readFloat();
                    var deployed_str_ptr = proto.add(0x40).readPointer();
                    var str_len = 0;
                    if (!deployed_str_ptr.isNull()) {
                        try { str_len = deployed_str_ptr.add(0x10).readS32(); } catch(e) { str_len = -1; }
                    }
                    found[key] = {bb: bb_float, dep_len: str_len};
                }
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
sc = sess.create_script(js); sc.load()
uid_list = list(uid_to_hex.keys())
r = sc.exports_sync.walk(BAG, uid_list)
found = r['found']
print(f"Found protos: {len(found)}/{len(uid_list)}")
bb_violations = []
dep_violations = []
not_found = []
for us, (uh, sp) in uid_to_hex.items():
    if us not in found:
        not_found.append((uh, sp))
        continue
    info = found[us]
    if info['bb'] > 0:
        bb_violations.append((uh, sp, info['bb']))
    if info['dep_len'] > 0:
        dep_violations.append((uh, sp, info['dep_len']))
print(f"\nBestBuddy violations: {len(bb_violations)}")
for v in bb_violations[:10]: print(f"  {v[0]} {v[1]:12s} bb_float={v[2]:.3f}")
print(f"Deployed violations: {len(dep_violations)}")
for v in dep_violations[:10]: print(f"  {v[0]} {v[1]:12s} dep_str_len={v[2]}")
print(f"Not found in bag: {len(not_found)}")
for nf in not_found[:5]: print(f"  {nf[0]} {nf[1]}")
sess.detach()
