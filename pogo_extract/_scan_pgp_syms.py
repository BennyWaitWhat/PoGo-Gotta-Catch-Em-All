import frida, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    allExports: function(modName, filter) {
        var mod = Process.findModuleByName(modName);
        if (!mod) return [];
        var exps = mod.enumerateExports();
        var r = exps.map(function(e){return {name:e.name, addr:e.address.toString()};});
        if (filter) {
            r = r.filter(function(e){
                var n = e.name.toLowerCase();
                for (var i = 0; i < filter.length; i++) if (n.indexOf(filter[i]) >= 0) return true;
                return false;
            });
        }
        return r;
    },
    allSymbols: function(modName, filter) {
        var mod = Process.findModuleByName(modName);
        if (!mod) return [];
        var syms = mod.enumerateSymbols();
        var r = syms.map(function(s){return {name:s.name, addr:s.address.toString(), type:s.type};});
        if (filter) {
            r = r.filter(function(s){
                var n = s.name.toLowerCase();
                for (var i = 0; i < filter.length; i++) if (n.indexOf(filter[i]) >= 0) return true;
                return false;
            });
        }
        return r;
    },
    countTotal: function(modName) {
        var mod = Process.findModuleByName(modName);
        if (!mod) return -1;
        return {exports: mod.enumerateExports().length, symbols: mod.enumerateSymbols().length};
    }
};
"""
sc = sess.create_script(js); sc.load()
filters = ['pgp','sleep','waina','sfida','plus']
print('=== Counts ===')
for m in ['libNianticLabsPlugin.so', 'libholoholo.so']:
    print(f"  {m}: {sc.exports_sync.count_total(m)}")
print('\n=== libNianticLabsPlugin.so EXPORTS matching pgp/sleep/waina/sfida/plus ===')
exps = sc.exports_sync.all_exports('libNianticLabsPlugin.so', filters)
print(f"Found {len(exps)}")
for e in exps[:50]:
    print(f"  {e['addr']}  {e['name'][:90]}")
print('\n=== libNianticLabsPlugin.so SYMBOLS matching ===')
syms = sc.exports_sync.all_symbols('libNianticLabsPlugin.so', filters)
print(f"Found {len(syms)}")
for s in syms[:50]:
    print(f"  {s['addr']}  [{s['type']}]  {s['name'][:90]}")
sess.detach()
