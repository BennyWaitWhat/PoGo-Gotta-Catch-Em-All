import frida, subprocess, json
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    dump: function(name) {
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
        var mGRT = bind('il2cpp_method_get_return_type','pointer',['pointer']);
        var cGF = bind('il2cpp_class_get_fields','pointer',['pointer','pointer']);
        var fGN = bind('il2cpp_field_get_name','pointer',['pointer']);
        var fGOFF = bind('il2cpp_field_get_offset','uint32',['pointer']);
        var fGT = bind('il2cpp_field_get_type','pointer',['pointer']);
        var fGF = bind('il2cpp_field_get_flags','int',['pointer']);
        var fGSV = bind('il2cpp_field_static_get_value','void',['pointer','pointer']);
        var tGN = bind('il2cpp_type_get_name','pointer',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (iGN(img).readCString() !== 'holo-game.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var c = iGC(img, ci);
                if (!c || c.isNull()) continue;
                if (cGN(c).readCString() !== name) continue;
                var fields = []; var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var f;
                while ((f = cGF(c, iter)) && !f.isNull()) {
                    var tn='?'; try { tn = tGN(fGT(f)).readCString(); } catch(e) {}
                    var flags = fGF(f);
                    var entry = {name: fGN(f).readCString(), offset: fGOFF(f), type: tn.substring(0,80), isStatic: !!(flags & 0x10)};
                    // If static + reference, try reading the value
                    if ((flags & 0x10) && (flags & 0x40) === 0) {
                        try {
                            var vbuf = Memory.alloc(8); vbuf.writeU64(0);
                            fGSV(f, vbuf);
                            entry.staticVal = vbuf.readPointer().toString();
                        } catch(e) {}
                    }
                    fields.push(entry);
                }
                var miter = Memory.alloc(Process.pointerSize); miter.writePointer(ptr(0));
                var methods = []; var m;
                while ((m = cGM(c, miter)) && !m.isNull()) {
                    var n = mGN(m).readCString();
                    var pc = mGPC(m);
                    var ps = [];
                    for (var pi = 0; pi < pc; pi++) {
                        var pt='?'; try { pt = tGN(mGP(m, pi)).readCString(); } catch(e) {}
                        ps.push(pt.substring(0,80));
                    }
                    var rt='?'; try { rt = tGN(mGRT(m)).readCString().substring(0,80); } catch(e) {}
                    methods.push({name: n, params: ps, ret: rt});
                }
                return {ns: cGNS(c).readCString(), name: name, fields: fields, methods: methods};
            }
        }
        return {error:'not found'};
    }
};
"""
sc = sess.create_script(js); sc.load()
for cn in ['PgpReadUnreadSleepLogs_', 'PgpOnStart_', 'PgpEntryPoints', 'PgpNativeBindings']:
    print(f'\n=== {cn} ===')
    r = sc.exports_sync.dump(cn)
    print(json.dumps(r, indent=2)[:3000])
sess.detach()
