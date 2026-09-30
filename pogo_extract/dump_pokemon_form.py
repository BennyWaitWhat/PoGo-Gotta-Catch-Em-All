"""Dump PokemonForm enum from holo-protos.dll via class iteration."""
import frida, json, subprocess
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    dump: function() {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var iGCC = bind('il2cpp_image_get_class_count','int',['pointer']);
        var iGC = bind('il2cpp_image_get_class','pointer',['pointer','int']);
        var cGN = bind('il2cpp_class_get_name','pointer',['pointer']);
        var cGNS = bind('il2cpp_class_get_namespace','pointer',['pointer']);
        var cGF = bind('il2cpp_class_get_fields','pointer',['pointer','pointer']);
        var fGN = bind('il2cpp_field_get_name','pointer',['pointer']);
        var fGF = bind('il2cpp_field_get_flags','int',['pointer']);
        var fGSV = bind('il2cpp_field_static_get_value','void',['pointer','pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());

        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            var imgName = iGN(img).readCString();
            if (imgName !== 'holo-protos.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                var name = cGN(cls).readCString();
                if (name !== 'Form') continue;
                var ns = cGNS(cls).readCString();
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var f, results = {};
                while ((f = cGF(cls, iter)) && !f.isNull()) {
                    var fName = fGN(f).readCString();
                    var flags = fGF(f);
                    if ((flags & 0x10) === 0) continue;
                    if ((flags & 0x40) === 0) continue;
                    var vbuf = Memory.alloc(8); vbuf.writeS64(0);
                    try { fGSV(f, vbuf); var v = vbuf.readS32(); results[v] = fName; } catch(e) {}
                }
                return {ns: ns, count: Object.keys(results).length, enum: results};
            }
        }
        return {error:'PokemonForm class not found'};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.dump()
if 'error' in r:
    print(r); sess.detach(); exit(1)
print(f"Found PokemonForm enum: {r['count']} entries")
with open('form_enum.json','w') as f:
    json.dump(r['enum'], f, indent=2)
print(f"Saved to form_enum.json")

# Show vivillon family
fams = ('VIVILLON','SCATTERBUG','SPEWPA','TANDEMAUS','MAUSHOLD','ROCKRUFF','LYCANROC')
for v, name in sorted(r['enum'].items(), key=lambda kv: int(kv[0])):
    n = name.upper()
    if any(x in n for x in fams):
        print(f'  {v}: {name}')
sess.detach()
