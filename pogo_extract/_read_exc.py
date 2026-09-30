import frida, subprocess, json
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    readExc: function(addr) {
        var p = ptr(addr);
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var addrs = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
        var ogc = bind('il2cpp_object_get_class','pointer',['pointer']);
        var cGN = bind('il2cpp_class_get_name','pointer',['pointer']);
        var cGNS = bind('il2cpp_class_get_namespace','pointer',['pointer']);
        function readUtf16Str(p2) {
            if (p2.isNull()) return '';
            var len = p2.add(0x10).readS32();
            if (len <= 0 || len > 1000) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(p2.add(0x14 + i*2).readU16()));
            return chars.join('');
        }
        var cls = ogc(p);
        var clsName = cGN(cls).readCString();
        var ns = cGNS(cls).readCString();
        // Exception fields: standard .NET layout typically has _message at known offset
        // Try +0x18 (string _message) and +0x20 (string _stackTrace)
        var msgs = {};
        for (var off = 0x10; off < 0x80; off += 8) {
            try {
                var sp = p.add(off).readPointer();
                if (!sp.isNull()) {
                    var s = readUtf16Str(sp);
                    if (s && s.length > 0 && s.length < 500) msgs['+0x'+off.toString(16)] = s;
                }
            } catch(e) {}
        }
        return {ns: ns, name: clsName, possibleStrs: msgs};
    }
};
"""
sc = sess.create_script(js); sc.load()
print('=== bayqExc 0x752c871780 ===')
print(json.dumps(sc.exports_sync.read_exc('0x752c871780'), indent=2))
print('=== sendExc 0x752c8716e0 ===')
print(json.dumps(sc.exports_sync.read_exc('0x752c8716e0'), indent=2))
sess.detach()
