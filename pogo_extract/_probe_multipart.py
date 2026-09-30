"""Probe multipart structure of WAINA23_1 + dump WithMultiPartProto fields."""
import frida, subprocess, json
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    findMultiPart: function() {
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
        var fGOFF = bind('il2cpp_field_get_offset','uint32',['pointer']);
        var fGT = bind('il2cpp_field_get_type','pointer',['pointer']);
        var tGN = bind('il2cpp_type_get_name','pointer',['pointer']);
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
                var name = cGN(cls).readCString();
                if (name.indexOf('MultiPart') < 0 && name !== 'WithMultiPartProto' && name !== 'MultiPartQuestProto') continue;
                var fields = []; var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var f;
                while ((f = cGF(cls, iter)) && !f.isNull()) {
                    var tname='?'; try { tname = tGN(fGT(f)).readCString(); } catch(e) {}
                    fields.push({name: fGN(f).readCString(), offset: fGOFF(f), type: tname});
                }
                hits.push({ns: cGNS(cls).readCString(), name: name, fields: fields});
            }
        }
        return hits;
    },

    probeQuestPtr: function(qPtr) {
        var qp = ptr(qPtr);
        var bytes = [];
        for (var off = 0x10; off < 0x140; off += 8) {
            try {
                var p = qp.add(off).readPointer();
                var info = {off: '+0x' + off.toString(16), val: p.toString()};
                // Also read as int32 / int64 in case it's a small enum/bool
                if (!p.isNull()) {
                    var v = qp.add(off).readS32();
                    if (Math.abs(v) < 100000) info.asI32 = v;
                }
                bytes.push(info);
            } catch(e) { bytes.push({off:off, err:1}); break; }
        }
        return bytes;
    }
};
"""
sc = sess.create_script(js); sc.load()
print('=== MultiPart proto class candidates ===')
hits = sc.exports_sync.find_multi_part()
for h in hits[:20]:
    print(f"\n{h['ns']}.{h['name']}:")
    for f in h['fields'][:20]:
        print(f"  +0x{f['offset']:03x}  {f['type']:60s} {f['name']}")

print('\n=== Probing WAINA23_1 quest at 0x74c4c8a2a0 (0x10..0x140) ===')
qPtr = '0x74c4c8a2a0'
for b in sc.exports_sync.probe_quest_ptr(qPtr):
    extras = []
    if 'asI32' in b: extras.append(f'i32={b["asI32"]}')
    print(f"  {b['off']}  {b.get('val','?')}  {' '.join(extras)}")
sess.detach()
