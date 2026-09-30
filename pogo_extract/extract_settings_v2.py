"""Single-pass: scan for PokemonSettingsProto klass byte pattern, read each instance's stats."""
import frida, subprocess, json

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    extract: function() {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var dom = dG();
        var sp = Memory.alloc(4);
        var asms = dGA(dom, sp); var na = sp.readS32();
        var protoImg = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-protos.dll'){ protoImg=i; break; } }
        var psCls = cFN(protoImg, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PokemonSettingsProto'));
        if (!psCls || psCls.isNull()) return {err:'no PSP class'};

        // Build klass byte pattern (little-endian)
        var bn = BigInt(psCls.toString());
        var pattern = '';
        for (var i = 0; i < 8; i++) {
            var b = Number((bn >> BigInt(i*8)) & 0xffn);
            pattern += ('0' + b.toString(16)).slice(-2) + ' ';
        }
        pattern = pattern.trim();

        // Single-pass scan
        var hits = [];
        var ranges = Process.enumerateRanges('rw-');
        for (var r = 0; r < ranges.length; r++) {
            if (ranges[r].size > 256*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, pattern).forEach(function(m){
                    hits.push(m.address);
                });
            } catch(e) {}
        }

        // For each hit, try to read PokemonSettingsProto fields
        var seen = {};
        var results = [];
        for (var i = 0; i < hits.length; i++) {
            try {
                var p = hits[i];
                // uniqueId_ (string ptr) at +0x10
                var uniqStr = p.add(0x10).readPointer();
                if (uniqStr.isNull()) continue;
                var len = uniqStr.add(0x10).readS32();
                if (len <= 0 || len > 100) continue;
                var chars = [];
                var ok = true;
                for (var ci = 0; ci < len; ci++) {
                    var c = uniqStr.add(0x14 + ci*2).readU16();
                    if (c < 32 || c > 126) { ok = false; break; }
                    chars.push(String.fromCharCode(c));
                }
                if (!ok) continue;
                var name = chars.join('');
                if (!/^[A-Z][A-Z_0-9]+$/.test(name)) continue;

                // form_ at +0x9c
                var form = p.add(0x9c).readS32();
                // stats_ pointer at +0x30
                var statsPtr = p.add(0x30).readPointer();
                if (statsPtr.isNull()) continue;
                var sta = statsPtr.add(0x10).readS32();
                var atk = statsPtr.add(0x14).readS32();
                var defe = statsPtr.add(0x18).readS32();
                if (sta < 1 || sta > 1000 || atk < 1 || atk > 1000 || defe < 1 || defe > 1000) continue;

                var key = name + '|' + form;
                if (seen[key]) continue;
                seen[key] = true;
                results.push({uniqueId: name, form: form, atk: atk, def: defe, sta: sta});
            } catch(e) {}
        }
        return {ok:true, klass: psCls.toString(), totalHits: hits.length, valid: results.length, results: results};
    }
};
"""
script = sess.create_script(js)
script.load()
print("Scanning for PokemonSettingsProto instances...")
r = script.exports_sync.extract()
print(f"Klass: {r.get('klass')}")
print(f"Total hits: {r.get('totalHits')}")
print(f"Valid extracted: {r.get('valid')}")

# Show samples
for entry in r.get('results', [])[:15]:
    print(f"  {entry['uniqueId']:35s} f={entry['form']:>5}  atk={entry['atk']:>3} def={entry['def']:>3} sta={entry['sta']:>3}")

# Save
with open('all_base_stats.json','w') as f:
    json.dump(r.get('results', []), f, indent=2)
print(f"\nSaved all_base_stats.json")
sess.detach()
