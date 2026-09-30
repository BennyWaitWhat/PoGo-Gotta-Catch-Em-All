"""Heap-scan all PokemonSettingsProto instances and extract base stats per (form)."""
import frida, json, subprocess

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
var fns = {};
var psClass = null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG = bind('il2cpp_domain_get','pointer',[]);
    fns.dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4);
    var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    var protoImg = null;
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-protos.dll'){ protoImg=i; break; } }
    psClass = fns.cFN(protoImg, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PokemonSettingsProto'));
}

rpc.exports = {
    extract: function() {
        init();
        var hits = [];
        var ranges = Process.enumerateRanges('rw-');
        var klassStr = psClass.toString().replace('0x','');
        var pattern = klassStr.match(/.{2}/g).reverse().join(' ');
        for (var r = 0; r < ranges.length; r++) {
            if (ranges[r].size > 256*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, pattern).forEach(function(m){
                    hits.push(m.address);
                });
            } catch(e) {}
        }
        var results = [];
        var seen = {};
        for (var i = 0; i < hits.length; i++) {
            try {
                var p = hits[i];
                // uniqueId_ at +0x10 (string ptr)
                var uniqStr = p.add(0x10).readPointer();
                if (uniqStr.isNull()) continue;
                var len = uniqStr.add(0x10).readS32();
                if (len <= 0 || len > 100) continue;
                var chars = [];
                for (var ci = 0; ci < len; ci++) {
                    var c = uniqStr.add(0x14 + ci*2).readU16();
                    if (c < 32 || c > 126) { chars = null; break; }
                    chars.push(String.fromCharCode(c));
                }
                if (!chars) continue;
                var name = chars.join('');
                if (!/^[A-Z_]+$/.test(name)) continue;

                var form = p.add(0x9c).readS32();
                var statsPtr = p.add(0x30).readPointer();
                if (statsPtr.isNull()) continue;
                var sta = statsPtr.add(0x10).readS32();
                var atk = statsPtr.add(0x14).readS32();
                var def = statsPtr.add(0x18).readS32();
                if (sta < 1 || sta > 1000 || atk < 1 || atk > 1000 || def < 1 || def > 1000) continue;

                var key = name + '|' + form;
                if (seen[key]) continue;
                seen[key] = true;
                results.push({uniqueId: name, form: form, atk: atk, def: def, sta: sta});
            } catch(e) {}
        }
        return results;
    }
};
"""
script = sess.create_script(js)
script.load()
results = script.exports_sync.extract()
print(f'Extracted {len(results)} unique (species, form) entries')

# Show sample
for r in results[:10]:
    print(f"  {r['uniqueId']:30s} form={r['form']:>4}  atk={r['atk']} def={r['def']} sta={r['sta']}")

# Save
with open('base_stats.json','w') as f:
    json.dump(results, f, indent=2)
print(f'Wrote base_stats.json')
sess.detach()
