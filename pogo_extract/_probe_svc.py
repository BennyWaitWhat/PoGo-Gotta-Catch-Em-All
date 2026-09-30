"""Probe a candidate svc address with get_NumberOfTags."""
import frida, subprocess
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PoGo PID: {adb_pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    probeSvc: function(svcAddr) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG=bind('il2cpp_domain_get','pointer',[]);
        var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
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
        if (!gnt) return {err: 'no gnt method'};
        var inst = ptr(svcAddr);
        var klass = inst.readPointer();
        var sameKlass = klass.equals(svcCls);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        try {
            var ret = rI(gnt, inst, ptr(0), exc);
            if (!exc.readPointer().isNull()) return {svcCls: svcCls.toString(), klass: klass.toString(), sameKlass: sameKlass, err: 'threw'};
            var n = ret.add(0x10).readS32();
            return {svcCls: svcCls.toString(), klass: klass.toString(), sameKlass: sameKlass, numTags: n};
        } catch(e) { return {err: e.toString(), svcCls: svcCls.toString(), klass: klass.toString(), sameKlass: sameKlass}; }
    }
};
"""
sc = sess.create_script(js); sc.load()
candidates = ['0x76a4615980']
for cand in candidates:
    r = sc.exports_sync.probe_svc(cand)
    print(f"  {cand}: {r}")
sess.detach()
