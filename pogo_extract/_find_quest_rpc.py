import frida, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    findClassMethods: function(ns, nm) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
        var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
        var mGPC = bind('il2cpp_method_get_param_count','int',['pointer']);
        var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
        tA(dG());
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var cls = cFN(gi, Memory.allocUtf8String(ns), Memory.allocUtf8String(nm));
        if (!cls || cls.isNull()) return {error: 'class not found'};
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, methods = [];
        while ((m = cGM(cls, iter)) && !m.isNull()) {
            methods.push({name: mGN(m).readCString(), params: mGPC(m)});
        }
        return methods;
    }
};
"""
sc = sess.create_script(js); sc.load()
import json
for cn in ['QuestRpcService','IQuestRpcService','QuestAutoCompleteService','IQuestAutoCompleteService']:
    r = sc.exports_sync.find_class_methods('Niantic.Holoholo.Quests', cn)
    if isinstance(r, list):
        print(f"\n=== {cn} ({len(r)} methods) ===")
        for m in r[:50]:
            n = m['name']
            if any(k in n.lower() for k in ['complete','claim','remove','update','progress','force','redeem','sync','refresh','get','set','submit']):
                print(f"  {n}({m['params']})")
sess.detach()
