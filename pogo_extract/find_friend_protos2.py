"""Find FriendDetailsProto and similar in holo-protos.dll only."""
import frida, json, subprocess
adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    findClasses: function(needle, imageFilter) {
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
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var hits = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            var imgName = iGN(img).readCString();
            if (imgName !== imageFilter) continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                var name = cGN(cls).readCString();
                if (name.toLowerCase().indexOf(needle.toLowerCase()) >= 0) {
                    hits.push({ns: cGNS(cls).readCString(), name: name});
                }
            }
        }
        return hits;
    }
};
"""
script = sess.create_script(js)
script.load()
print("=== holo-protos.dll classes with 'friend' ===")
for h in script.exports_sync.find_classes('friend', 'holo-protos.dll'):
    print(f"  {h['ns']:30s} {h['name']}")
print("\n=== holo-protos.dll classes with 'social' ===")
for h in script.exports_sync.find_classes('social', 'holo-protos.dll'):
    print(f"  {h['ns']:30s} {h['name']}")
sess.detach()
