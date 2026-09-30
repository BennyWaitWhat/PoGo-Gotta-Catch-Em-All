"""Find all PokemonStatsAttributesProto + their parent PokemonSettingsProto."""
import frida, subprocess, json

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    extractAll: function() {
        // Strategy: scan rw- memory for any pattern matching PokemonStatsAttributesProto.
        // Each PokemonStatsAttributesProto is preceded by IL2CPP klass header (16 bytes).
        // Layout: [klass_ptr][monitor][BaseStamina i32][BaseAttack i32][BaseDefense i32][DodgeEnergyDelta i32]
        // Total size: 32 bytes (object header 16 + 16 fields)
        // Also: PokemonSettingsProto.stats_ is at +0x30, points to a PokemonStatsAttributesProto

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
        var statsCls = cFN(protoImg, Memory.allocUtf8String('Holoholo.Rpc'), Memory.allocUtf8String('PokemonStatsAttributesProto'));
        if (!statsCls || statsCls.isNull()) return {err:'no class'};
        var statsClsStr = statsCls.toString();

        // Heap-scan for PokemonStatsAttributesProto instances by klass byte pattern
        // Klass at +0 of object. So scan for klass bytes.
        var klassNum = parseInt(statsClsStr);
        var klassBytes = '';
        for (var i = 0; i < 8; i++) {
            klassBytes += ('0' + ((klassNum >> (i*8)) & 0xff).toString(16)).slice(-2) + ' ';
        }
        // Use BigInt for safety
        var bn = BigInt(statsClsStr);
        klassBytes = '';
        for (var i = 0; i < 8; i++) {
            var b = Number((bn >> BigInt(i*8)) & 0xffn);
            klassBytes += ('0' + b.toString(16)).slice(-2) + ' ';
        }
        var pattern = klassBytes.trim();

        // First find all stats instances
        var statsInstances = [];
        var ranges = Process.enumerateRanges('rw-');
        for (var r = 0; r < ranges.length; r++) {
            if (ranges[r].size > 256*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, pattern).forEach(function(m){
                    try {
                        // Verify by reading following bytes - should look like sane stats
                        var sta = m.address.add(0x10).readS32();
                        var atk = m.address.add(0x14).readS32();
                        var def = m.address.add(0x18).readS32();
                        if (sta > 0 && sta < 1000 && atk > 0 && atk < 1000 && def > 0 && def < 1000) {
                            statsInstances.push({addr: m.address, atk: atk, def: def, sta: sta});
                        }
                    } catch(e) {}
                });
            } catch(e) {}
        }

        // Now for each stats instance, find the parent PokemonSettingsProto by searching
        // for pointers to this stats addr in memory. Pointer would be at parent+0x30.
        var results = [];
        for (var i = 0; i < statsInstances.length; i++) {
            var si = statsInstances[i];
            // Convert addr to little-endian byte pattern for search
            var addrNum = BigInt(si.addr.toString());
            var addrBytes = '';
            for (var b = 0; b < 8; b++) {
                var byte = Number((addrNum >> BigInt(b*8)) & 0xffn);
                addrBytes += ('0' + byte.toString(16)).slice(-2) + ' ';
            }
            addrBytes = addrBytes.trim();

            // Search for this pointer
            var parents = [];
            for (var r = 0; r < ranges.length; r++) {
                if (ranges[r].size > 256*1024*1024) continue;
                if (parents.length >= 3) break;
                try {
                    Memory.scanSync(ranges[r].base, ranges[r].size, addrBytes).forEach(function(m){
                        if (parents.length < 3) {
                            // The match is at offset 0x30 of parent. So parent = m.address - 0x30
                            var parent = m.address.sub(0x30);
                            try {
                                // Verify by reading uniqueId_ at parent+0x10 (string)
                                var uniqStr = parent.add(0x10).readPointer();
                                if (uniqStr.isNull()) return;
                                var len = uniqStr.add(0x10).readS32();
                                if (len <= 0 || len > 100) return;
                                var chars = [];
                                for (var ci = 0; ci < len; ci++) {
                                    var c = uniqStr.add(0x14 + ci*2).readU16();
                                    if (c < 32 || c > 126) { chars = null; break; }
                                    chars.push(String.fromCharCode(c));
                                }
                                if (!chars) return;
                                var name = chars.join('');
                                if (!/^[A-Z][A-Z_0-9]+$/.test(name)) return;
                                var form = parent.add(0x9c).readS32();
                                parents.push({parent: parent.toString(), uniqueId: name, form: form});
                            } catch(e) {}
                        }
                    });
                } catch(e) {}
            }
            if (parents.length > 0) {
                results.push({
                    statsAddr: si.addr.toString(), atk: si.atk, def: si.def, sta: si.sta,
                    parents: parents
                });
            }
        }
        return {ok:true, count: results.length, totalStatsInstances: statsInstances.length, results: results};
    }
};
"""
script = sess.create_script(js)
script.load()
r = script.exports_sync.extract_all()
print(f"Stats instances found: {r.get('totalStatsInstances')}")
print(f"With identified parents: {r.get('count')}")

# Build mapping
mapping = {}
for entry in r.get('results', []):
    for parent in entry['parents']:
        key = (parent['uniqueId'], parent['form'])
        mapping[key] = (entry['atk'], entry['def'], entry['sta'])

print(f"\nUnique (uniqueId, form): {len(mapping)}")
print("\nSamples:")
for (n, f), (atk, defe, sta) in list(mapping.items())[:20]:
    print(f"  {n:30s} f={f:>5}  atk={atk} def={defe} sta={sta}")

# Save
with open('all_base_stats.json','w') as f:
    json.dump([{'uniqueId': k[0], 'form': k[1], 'atk': v[0], 'def': v[1], 'sta': v[2]} for k, v in mapping.items()], f, indent=2)
print(f"\nSaved all_base_stats.json with {len(mapping)} entries")
sess.detach()
