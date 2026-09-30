"""Dump HoloPokemonForm enum to JSON for form-id -> name mapping."""
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
        function safeBind(n,r,a){ if (!addrs[n]) return null; try { return new NativeFunction(addrs[n],r,a); } catch(e) { return null; } }
        var dG = safeBind('il2cpp_domain_get','pointer',[]);
        var dGA = safeBind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = safeBind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = safeBind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = safeBind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cGF = safeBind('il2cpp_class_get_fields','pointer',['pointer','pointer']);
        var fGN = safeBind('il2cpp_field_get_name','pointer',['pointer']);
        var fGF = safeBind('il2cpp_field_get_flags','int',['pointer']);
        var fGSV = safeBind('il2cpp_field_static_get_value','void',['pointer','pointer']);
        var fGOFF = safeBind('il2cpp_field_get_offset','uint32',['pointer']);
        var tA = safeBind('il2cpp_thread_attach','pointer',['pointer']);
        if (tA) tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var imgList = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            imgList.push({name: iGN(img).readCString(), ptr: img});
        }
        var candidates = [
            ['','PokemonForm'],
            ['','Form'],
            ['Holoholo.Rpc','HoloPokemonForm'],
            ['Holoholo.Rpc','PokemonForm'],
            ['','HoloPokemonForm'],
        ];
        for (var ii = 0; ii < imgList.length; ii++) {
            for (var ci = 0; ci < candidates.length; ci++) {
                var ns = candidates[ci][0]; var nm = candidates[ci][1];
                var nsArg = (ns === '') ? Memory.allocUtf8String('') : Memory.allocUtf8String(ns);
                var cls = cFN(imgList[ii].ptr, nsArg, Memory.allocUtf8String(nm));
                if (!cls || cls.isNull()) continue;
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
                if (Object.keys(results).length > 0)
                    return {found: imgList[ii].name + '/' + ns + '/' + nm, count: Object.keys(results).length, enum: results};
            }
        }
        return {error:'not found', images: imgList.map(function(x){return x.name;})};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.dump()
if 'error' in r:
    print(r); sess.detach(); exit(1)
print(f"Found: {r.get('found')}, count: {r.get('count')}")
with open('form_enum.json','w') as f:
    json.dump(r['enum'], f, indent=2)
for v, name in sorted(r['enum'].items(), key=lambda kv: int(kv[0])):
    n = name.upper()
    if any(x in n for x in ('VIVILLON','SCATTERBUG','SPEWPA','TANDEMAUS','MAUSHOLD','ROCKRUFF','LYCANROC')):
        print(f'  {v}: {name}')
sess.detach()
