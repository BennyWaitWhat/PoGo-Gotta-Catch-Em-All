"""Read live proto bytes for 5 NULL-field transfers, decode BestBuddy + DeployedFort."""
import frida, subprocess, sqlite3, struct
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

BAG = '0x73001bd980'
c = sqlite3.connect('pokemon.db').cursor()
suspects = ['24fd1b41abd3a03b','0c540f3aee0cef75','4fbabdd1865b8fc7','9c0e53489b49604f','37f76da8294faaf9']
uid_strs = []
for uh in suspects:
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    if r:
        u = int(r[0]); u = u if u >= 0 else u + 2**64
        uid_strs.append((uh, str(u)))

js = """
rpc.exports = {
    probe: function(bag, uids) {
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
                if (wanted[key]) {
                    var proto=node.add(0x30).readPointer();
                    var bytes = proto.readByteArray(512);
                    found[key] = {addr: proto.toString(), bytes: Array.prototype.slice.call(new Uint8Array(bytes))};
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
r = sc.exports_sync.probe(BAG, [u[1] for u in uid_strs])
print(f"Found: {len(r['found'])}/{len(uid_strs)}")
for uh, us in uid_strs:
    if us not in r['found']:
        print(f"  {uh}: NOT FOUND")
        continue
    info = r['found'][us]
    bs = bytes(info['bytes'])
    bb_float = struct.unpack_from('<f', bs, 172)[0]
    # DeployedFortId is a string ptr at offset 56 (managed proto offset)
    # Easier: check buddy_km_walked and other float patterns
    bb = bb_float > 0
    # Look for deployed_fort_id string ptr at various offsets - non-null means deployed
    nonzero_ptr_off = []
    for off in [56, 64, 72, 80, 88, 96]:
        ptr_v = struct.unpack_from('<Q', bs, off)[0]
        if 0x70_0000_0000 < ptr_v < 0x80_0000_0000:  # heap range
            nonzero_ptr_off.append(f"+{off:#x}={ptr_v:#x}")
    print(f"  {uh}: addr={info['addr']}  BB_float@+172={bb_float:.3f}  is_BB={bb}  ptrs={nonzero_ptr_off[:3]}")
sess.detach()
