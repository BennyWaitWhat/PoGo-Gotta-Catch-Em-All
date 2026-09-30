import frida, subprocess, json
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    fields: function(ns, name) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cGF = bind('il2cpp_class_get_fields','pointer',['pointer','pointer']);
        var fGN = bind('il2cpp_field_get_name','pointer',['pointer']);
        var fGOFF = bind('il2cpp_field_get_offset','uint32',['pointer']);
        var fGT = bind('il2cpp_field_get_type','pointer',['pointer']);
        var tGN = bind('il2cpp_type_get_name','pointer',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var cls = cFN(gi, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
        if (cls.isNull()) return {error:'not found'};
        var fields = []; var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var f;
        while ((f = cGF(cls, iter)) && !f.isNull()) {
            var tn='?'; try { tn = tGN(fGT(f)).readCString(); } catch(e) {}
            fields.push({name: fGN(f).readCString(), offset: fGOFF(f), type: tn.substring(0,80)});
        }
        return {fields: fields};
    }
};
"""
sc = sess.create_script(js); sc.load()
print(json.dumps(sc.exports_sync.fields('Niantic.Holoholo.Rpc', 'RpcRequest'), indent=2))
sess.detach()
