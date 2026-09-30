"""Dump MapField class layout to understand iteration."""
import frida, subprocess
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
        var fGOFF = bind('il2cpp_field_get_offset','uint32',['pointer']);
        var fGT = bind('il2cpp_field_get_type','pointer',['pointer']);
        var tGN = bind('il2cpp_type_get_name','pointer',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());

        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var hits = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (iGN(img).readCString() !== 'Niantic.Protobuf.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                var name = cGN(cls).readCString();
                if (name === 'MapField`2') {
                    var fields = []; var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                    var f;
                    while ((f = cGF(cls, iter)) && !f.isNull()) {
                        var tn = '?';
                        try { tn = tGN(fGT(f)).readCString(); } catch(e) {}
                        fields.push({name: fGN(f).readCString(), offset: fGOFF(f), type: tn});
                    }
                    return {name: name, ns: cGNS(cls).readCString(), fields: fields};
                }
            }
        }
        return {error:'not found'};
    }
};
"""
script = sess.create_script(js)
script.load()
import json
r = script.exports_sync.dump()
print(json.dumps(r, indent=2))
sess.detach()
