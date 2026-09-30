import frida, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    dump: function(image, ns, name) {
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
        var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
        var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
        var mGPC = bind('il2cpp_method_get_param_count','int',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (image && iGN(img).readCString() !== image) continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                if (cGN(cls).readCString() !== name) continue;
                if (ns && cGNS(cls).readCString() !== ns) continue;
                var fields = []; var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var f;
                while ((f = cGF(cls, iter)) && !f.isNull()) {
                    var tn='?'; try { tn = tGN(fGT(f)).readCString(); } catch(e) {}
                    fields.push({name: fGN(f).readCString(), offset: fGOFF(f), type: tn});
                }
                var methods = []; var miter = Memory.alloc(Process.pointerSize); miter.writePointer(ptr(0));
                var m;
                while ((m = cGM(cls, miter)) && !m.isNull()) {
                    methods.push({name: mGN(m).readCString(), params: mGPC(m)});
                }
                return {fields: fields, methods: methods};
            }
        }
        return {error: 'not found'};
    },

    findMethodsContaining: function(needle) {
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
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var hits = [];
        for (var ai = 0; ai < na; ai++) {
            var img = aGI(asms.add(ai*Process.pointerSize).readPointer());
            if (iGN(img).readCString() !== 'holo-game.dll') continue;
            var cc = iGCC(img);
            for (var ci = 0; ci < cc; ci++) {
                var cls = iGC(img, ci);
                if (!cls || cls.isNull()) continue;
                var clsName = cGN(cls).readCString();
                var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
                var m;
                while ((m = cGM(cls, iter)) && !m.isNull()) {
                    var n = mGN(m).readCString();
                    if (n.toLowerCase().indexOf(needle.toLowerCase()) < 0) continue;
                    hits.push({cls: clsName, ns: cGNS(cls).readCString(), method: n, params: mGPC(m)});
                    if (hits.length > 50) return hits;
                }
            }
        }
        return hits;
    }
};
"""
sc = sess.create_script(js); sc.load()
import json
print('=== SubmitSleepRecordsQuestProto ===')
print(json.dumps(sc.exports_sync.dump('holo-protos.dll', 'Holoholo.Rpc', 'SubmitSleepRecordsQuestProto'), indent=2))
print('=== Methods containing "submitsleep" ===')
for h in sc.exports_sync.find_methods_containing('submitsleep')[:30]:
    print(f"  {h['ns']}.{h['cls']}.{h['method']}({h['params']})")
print('\n=== Methods containing "wainasubmit" ===')
for h in sc.exports_sync.find_methods_containing('wainasubmit')[:30]:
    print(f"  {h['ns']}.{h['cls']}.{h['method']}({h['params']})")
print('\n=== Methods containing "TriggerSnorlax" or SleepingSnorlax ===')
for h in sc.exports_sync.find_methods_containing('snorlax')[:30]:
    print(f"  {h['ns']}.{h['cls']}.{h['method']}({h['params']})")
sess.detach()
