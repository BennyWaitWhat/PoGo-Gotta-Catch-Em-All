import frida, subprocess, json
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    findMethodByEnum: function(needle) {
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
        var cGF = bind('il2cpp_class_get_fields','pointer',['pointer','pointer']);
        var fGN = bind('il2cpp_field_get_name','pointer',['pointer']);
        var fGF = bind('il2cpp_field_get_flags','int',['pointer']);
        var fGSV = bind('il2cpp_field_static_get_value','void',['pointer','pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (iGN(img).readCString() !== 'holo-protos.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                if (cGN(cls).readCString() !== 'Method') continue;
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var f, results = {};
                while ((f = cGF(cls, iter)) && !f.isNull()) {
                    var fName = fGN(f).readCString();
                    var flags = fGF(f);
                    if ((flags & 0x10) === 0 || (flags & 0x40) === 0) continue;
                    if (fName.toLowerCase().indexOf(needle.toLowerCase()) < 0) continue;
                    var vbuf = Memory.alloc(8); vbuf.writeS64(0);
                    try { fGSV(f, vbuf); var v = vbuf.readS32(); results[v] = fName; } catch(e) {}
                }
                if (Object.keys(results).length > 0) return results;
            }
        }
        return {error:'not found'};
    },

    findRpcDispatcher: function() {
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
        var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
        var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
        var mGPC = bind('il2cpp_method_get_param_count','int',['pointer']);
        var mGP = bind('il2cpp_method_get_param','pointer',['pointer','int']);
        var tGN = bind('il2cpp_type_get_name','pointer',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var methods = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (iGN(img).readCString() !== 'holo-game.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var c = iGC(img, ci);
                if (!c || c.isNull()) continue;
                var clsName = cGN(c).readCString();
                var ns = cGNS(c).readCString();
                if ((ns + '.' + clsName).indexOf('Rpc') < 0) continue;
                if (clsName.indexOf('Service') >= 0 && clsName.indexOf('Wai') < 0) continue;
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var m;
                while ((m = cGM(c, iter)) && !m.isNull()) {
                    var n = mGN(m).readCString();
                    if (n.indexOf('Submit') >= 0 || n.indexOf('Send') >= 0 || n.indexOf('Sleep') >= 0 || n.indexOf('Waina') >= 0) {
                        methods.push({cls: clsName, ns: ns, method: n, params: mGPC(m)});
                        if (methods.length > 30) return methods;
                    }
                }
            }
        }
        return methods;
    }
};
"""
sc = sess.create_script(js); sc.load()
print('=== Holoholo.Rpc.Method values matching "waina"/"sleep" ===')
print(json.dumps(sc.exports_sync.find_method_by_enum('waina'), indent=2))
print(json.dumps(sc.exports_sync.find_method_by_enum('sleep'), indent=2))
print('\n=== Rpc methods related to Submit/Send/Sleep/Waina ===')
for h in sc.exports_sync.find_rpc_dispatcher()[:30]:
    print(f"  {h['ns']}.{h['cls']}.{h['method']}({h['params']})")
sess.detach()
