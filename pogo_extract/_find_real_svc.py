"""Find the real TaggingRpcService instance by heap-scanning for instances with 12 tags."""
import frida, subprocess, time
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PoGo PID: {adb_pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    scan: function() {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG=bind('il2cpp_domain_get','pointer',[]); var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']); var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
        var mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
        var rI=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var tA=bind('il2cpp_thread_attach','pointer',['pointer']); tA(dG());
        var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32();
        var gi=null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){gi=i;break;} }
        var svcCls=cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
        var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, gnt=null;
        while ((m = cGM(svcCls, iter)) && !m.isNull()) {
            if (mGN(m).readCString() === 'get_NumberOfTags') gnt = m;
        }
        // Scan all heap ranges for pointers that point to objects whose klass is svcCls
        var hits = [];
        Process.enumerateRangesSync({protection:'rw-'}).forEach(function(r){
            if (r.size > 0x10000000 || hits.length > 30) return;
            try {
                var p = r.base;
                var end = r.base.add(r.size);
                while (p.compare(end) < 0) {
                    try {
                        var klass = p.readPointer();
                        if (klass.equals(svcCls)) {
                            // Try get_NumberOfTags
                            var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
                            var ret = rI(gnt, p, ptr(0), exc);
                            if (!exc.readPointer().isNull()) { p = p.add(8); continue; }
                            var n = ret.add(0x10).readS32();
                            if (n > 0 && n < 200) hits.push({addr: p.toString(), tags: n});
                            if (hits.length > 30) break;
                        }
                    } catch(e) {}
                    p = p.add(8);
                }
            } catch(e) {}
        });
        return {svcClass: svcCls.toString(), hits: hits};
    }
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.scan()
print(f"TaggingRpcService class: {r['svcClass']}")
print(f"Heap hits with valid get_NumberOfTags response:")
for h in r['hits']:
    print(f"  {h['addr']}  tags={h['tags']}")
sess.detach()
