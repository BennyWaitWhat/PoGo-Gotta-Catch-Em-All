import frida, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    find: function(needle) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var iGCC = bind('il2cpp_image_get_class_count','int',['pointer']);
        var iGC = bind('il2cpp_image_get_class','pointer',['pointer','int']);
        var cGN = bind('il2cpp_class_get_name','pointer',['pointer']);
        var cGNS = bind('il2cpp_class_get_namespace','pointer',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var hits = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            var iN = iGN(img).readCString();
            if (iN !== 'holo-game.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var c = iGC(img, ci);
                if (!c || c.isNull()) continue;
                var name = cGN(c).readCString();
                if (name.toLowerCase().indexOf(needle.toLowerCase()) < 0) continue;
                hits.push({ns: cGNS(c).readCString(), name: name});
                if (hits.length > 100) return hits;
            }
        }
        return hits;
    }
};
"""
sc = sess.create_script(js); sc.load()
import json
print('=== Pgp classes ===')
for h in sc.exports_sync.find('Pgp')[:60]:
    print(f"  {h['ns']}.{h['name']}")
print('\n=== Sfida classes ===')
for h in sc.exports_sync.find('Sfida')[:30]:
    print(f"  {h['ns']}.{h['name']}")
print('\n=== Bluetooth/BLE classes ===')
for h in sc.exports_sync.find('Bluetooth')[:30]:
    print(f"  {h['ns']}.{h['name']}")
sess.detach()
