"""Dump fields/methods for FriendshipDataProto and BackgroundFriendDetailsCachingService."""
import frida, json, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    dumpClass: function(image, ns, name) {
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
        var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
        var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
        var mGPC = bind('il2cpp_method_get_param_count','int',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (iGN(img).readCString() !== image) continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                if (cGN(cls).readCString() !== name) continue;
                if (ns && cGNS(cls).readCString() !== ns) continue;
                var fields = []; var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var f;
                while ((f = cGF(cls, iter)) && !f.isNull()) {
                    var tname = '?';
                    try { tname = tGN(fGT(f)).readCString(); } catch(e) {}
                    fields.push({name: fGN(f).readCString(), offset: fGOFF(f), type: tname});
                }
                var methods = []; var miter = Memory.alloc(Process.pointerSize); miter.writePointer(ptr(0));
                var m;
                while ((m = cGM(cls, miter)) && !m.isNull()) {
                    methods.push({name: mGN(m).readCString(), params: mGPC(m)});
                }
                return {found: true, fields: fields, methods: methods};
            }
        }
        return {found: false};
    }
};
"""
script = sess.create_script(js)
script.load()
for img, ns, nm in [
    ('holo-protos.dll','Holoholo.Rpc','CompleteQuestProto'),
    ('holo-protos.dll','Holoholo.Rpc','CompleteQuestOutProto'),
    ('holo-protos.dll','Holoholo.Rpc','RemoveQuestProto'),
]:
    print(f"\n=== {ns}.{nm} ({img}) ===")
    r = script.exports_sync.dump_class(img, ns, nm)
    if r['found']:
        print(' Fields:')
        for f in r['fields'][:30]:
            print(f"   +0x{f['offset']:03x}  {f['type']:50s} {f['name']}")
        print(' Methods:')
        for m in r['methods'][:30]:
            print(f"   {m['name']}({m['params']})")
    else:
        print('  NOT FOUND')
sess.detach()
