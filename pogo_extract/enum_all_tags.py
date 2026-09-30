"""Enumerate every binding index 0..50 to find all server-side tags."""
import frida, subprocess, time
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Use cached svc
SVC = '0x7275723100'
js = """
rpc.exports = {
    enum: function(svcAddr) {
        var inst = ptr(svcAddr);
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
        var rI = bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var svcCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, gnt=null, gctb=null;
        while ((m = cGM(svcCls, iter)) && !m.isNull()) {
            var nm = mGN(m).readCString();
            if (nm === 'get_NumberOfTags') gnt = m;
            if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
        }
        function readUtf16(p) {
            if (p.isNull()) return '';
            var len = p.add(0x10).readS32();
            if (len <= 0 || len > 100) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(p.add(0x14 + i*2).readU16()));
            return chars.join('');
        }
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = rI(gnt, inst, ptr(0), exc);
        var totalTags = ret.add(0x10).readS32();
        var allTags = [];
        for (var i = 0; i < Math.max(totalTags, 50); i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var ex2 = Memory.alloc(Process.pointerSize); ex2.writePointer(ptr(0));
            var bp = rI(gctb, inst, args, ex2);
            if (bp.isNull()) {
                allTags.push({idx: i, name: '(null binding)'});
                continue;
            }
            var tagProto = bp.add(0x10).readPointer();
            var name = '';
            try {
                var ns = tagProto.add(0x40).readPointer();
                name = readUtf16(ns);
            } catch(e) {}
            var listPtr = bp.add(0x18).readPointer();
            var count = listPtr.isNull() ? -1 : listPtr.add(0x18).readS32();
            allTags.push({idx: i, name: name, count: count});
        }
        return {totalTags: totalTags, tags: allTags};
    }
};
"""
sc = sess.create_script(js); sc.load()
r = sc.exports_sync.enum(SVC)
print(f"GetNumberOfTags(): {r['totalTags']}")
print(f"\nEnumerated indices 0..{len(r['tags'])-1}:")
for t in r['tags']:
    if 'count' in t:
        print(f"  idx={t['idx']:3d}  name='{t['name']}'  count={t['count']}")
    else:
        print(f"  idx={t['idx']:3d}  {t['name']}")
sess.detach()
