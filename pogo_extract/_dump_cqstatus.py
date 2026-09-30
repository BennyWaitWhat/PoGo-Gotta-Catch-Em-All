import frida, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    findStatuses: function() {
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
        var hits = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (iGN(img).readCString() !== 'holo-protos.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                if (cGN(cls).readCString() !== 'Status') continue;
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var f, results = {};
                while ((f = cGF(cls, iter)) && !f.isNull()) {
                    var fName = fGN(f).readCString();
                    var flags = fGF(f);
                    if ((flags & 0x10) === 0 || (flags & 0x40) === 0) continue;
                    var vbuf = Memory.alloc(8); vbuf.writeS64(0);
                    try { fGSV(f, vbuf); var v = vbuf.readS32(); results[v] = fName; } catch(e) {}
                }
                if (Object.keys(results).length === 0) continue;
                // Filter to status enums with QUEST-related field names
                var fnames = Object.values(results).join('|').toUpperCase();
                if (fnames.indexOf('QUEST') >= 0 || fnames.indexOf('PROGRESS_NOT_COMPLETE') >= 0 || fnames.indexOf('NOT_COMPLETED') >= 0 || fnames.indexOf('ALREADY') >= 0) {
                    hits.push({ns: cGNS(cls).readCString(), values: results});
                }
            }
        }
        return hits;
    }
};
"""
sc = sess.create_script(js); sc.load()
hits = sc.exports_sync.find_statuses()
for h in hits[:10]:
    print(f"\n.Status (in {h['ns']}):")
    for v, name in sorted(h['values'].items(), key=lambda x:int(x[0])):
        print(f"  {v} = {name}")
sess.detach()
