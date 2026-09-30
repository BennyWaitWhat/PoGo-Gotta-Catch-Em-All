"""Find an RPC dispatch path that takes either bytes or non-generic message."""
import frida, subprocess, json
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    findDispatch: function() {
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
        var hits = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            var iN = iGN(img).readCString();
            if (iN !== 'holo-game.dll' && iN !== 'holo-protos.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var c = iGC(img, ci);
                if (!c || c.isNull()) continue;
                var clsName = cGN(c).readCString();
                var ns = cGNS(c).readCString();
                if ((ns + '.' + clsName).indexOf('Rpc') < 0 && clsName.indexOf('Request') < 0) continue;
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var m;
                while ((m = cGM(c, iter)) && !m.isNull()) {
                    var n = mGN(m).readCString();
                    var pc = mGPC(m);
                    var hasIMessage = false; var hasInt = false; var hasBytes = false;
                    var paramTypes = [];
                    for (var pi = 0; pi < pc; pi++) {
                        var pt='?'; try { pt = tGN(mGP(m, pi)).readCString(); } catch(e) {}
                        paramTypes.push(pt);
                        if (pt.indexOf('IMessage') >= 0) hasIMessage = true;
                        if (pt === 'System.Int32' || pt === 'Holoholo.Rpc.Method') hasInt = true;
                        if (pt.indexOf('ByteString') >= 0 || pt.indexOf('Byte[]') >= 0) hasBytes = true;
                    }
                    if (hasIMessage && hasInt) hits.push({cls:clsName, ns:ns, method:n, params:paramTypes, score: 'IMessage+Int'});
                    else if (hasBytes && hasInt) hits.push({cls:clsName, ns:ns, method:n, params:paramTypes, score: 'Bytes+Int'});
                }
            }
        }
        return hits;
    }
};
"""
sc = sess.create_script(js); sc.load()
hits = sc.exports_sync.find_dispatch()
print(f'Found {len(hits)} candidate dispatch methods:')
for h in hits[:30]:
    print(f"  [{h['score']}] {h['ns']}.{h['cls']}.{h['method']}({', '.join(p[:50] for p in h['params'])})")
sess.detach()
