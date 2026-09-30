"""Enumerate all native modules + find pgp/holo/sleep symbols."""
import frida, subprocess
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
js = """
rpc.exports = {
    listModules: function() {
        var mods = Process.enumerateModules();
        return mods.map(function(m){ return {name:m.name, base:m.base.toString(), size:m.size, path:m.path}; })
            .filter(function(m){ return m.name.toLowerCase().match(/pgp|holo|sleep|wear|sfida|niantic|libpoke/); });
    },
    listExports: function(modName) {
        try {
            var exps = Module.enumerateExports(modName);
            return exps.filter(function(e){
                var n = e.name.toLowerCase();
                return n.indexOf('pgp')>=0 || n.indexOf('sleep')>=0 || n.indexOf('waina')>=0 || n.indexOf('sfida')>=0;
            }).slice(0, 50).map(function(e){return {name:e.name, addr:e.address.toString()};});
        } catch(e) { return {error:e.toString()}; }
    },
    findStringRefs: function(modName, str) {
        var mod = Process.findModuleByName(modName);
        if (!mod) return {error:'mod not found'};
        var hits = [];
        try {
            Memory.scanSync(mod.base, mod.size, str.split('').map(function(c){
                return ('0'+c.charCodeAt(0).toString(16)).slice(-2);
            }).join(' ')).forEach(function(m){
                hits.push(m.address.toString());
            });
        } catch(e) { return {error:e.toString()}; }
        return {hits: hits.slice(0, 10), total: hits.length};
    }
};
"""
sc = sess.create_script(js); sc.load()
import json
print('=== Relevant modules ===')
mods = sc.exports_sync.list_modules()
for m in mods:
    print(f"  {m['name']:30s} base={m['base']} size={m['size']} path={m['path']}")
print('\n=== libpogoplus / similar exports (top 50) ===')
for m in mods:
    if 'pgp' in m['name'].lower() or 'plus' in m['name'].lower() or 'wear' in m['name'].lower() or 'pokemon' in m['name'].lower():
        print(f"\n--- {m['name']} ---")
        exps = sc.exports_sync.list_exports(m['name'])
        if isinstance(exps, list):
            for e in exps[:30]: print(f"  {e['addr']}  {e['name'][:80]}")
sess.detach()
