"""Deep dive into Pokemod's memory looking for rank cache."""
import frida, subprocess, json

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    findAllStrings: function(query) {
        // Scan for string and return all hits
        var pattern = '';
        for (var i = 0; i < query.length; i++) {
            pattern += ('0' + query.charCodeAt(i).toString(16)).slice(-2) + ' ';
        }
        var hits = [];
        var ranges = Process.enumerateRanges('r--');
        for (var r = 0; r < ranges.length; r++) {
            if (ranges[r].size > 100*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, pattern.trim()).forEach(function(m){
                    hits.push({addr: m.address.toString(), rangeBase: ranges[r].base.toString(),
                               rangeSize: ranges[r].size, prot: ranges[r].protection,
                               file: ranges[r].file ? ranges[r].file.path : null});
                });
            } catch(e) {}
        }
        return hits;
    },
    examineRange: function(addr, len) {
        var p = ptr(addr);
        try {
            var bytes = p.readByteArray(len);
            var u8 = new Uint8Array(bytes);
            var hex = '';
            var ascii = '';
            for (var i = 0; i < u8.length; i++) {
                hex += ('0' + u8[i].toString(16)).slice(-2) + ' ';
                ascii += (u8[i] >= 32 && u8[i] < 127) ? String.fromCharCode(u8[i]) : '.';
                if ((i+1) % 32 === 0) { hex += '\\n  '; ascii += '\\n  '; }
            }
            return {hex: hex, ascii: ascii};
        } catch(e) { return {err: e.message}; }
    },
    listAllRanges: function() {
        var ranges = Process.enumerateRanges('r--');
        return ranges.filter(function(r){
            return r.size < 100*1024*1024 && !r.file;
        }).map(function(r) {
            return {base: r.base.toString(), size: r.size, prot: r.protection};
        });
    },
    /* Hook IL2CPP string allocation and capture any 'PvP Rank' strings created */
    hookStringNew: function(durationMs) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        var captured = [];
        Interceptor.attach(exp.il2cpp_string_new, {
            onEnter: function(args) {
                this.input = args[0];
            },
            onLeave: function(retval) {
                try {
                    var s = this.input.readCString();
                    if (s && s.length < 200 && s.indexOf('Rank') >= 0) {
                        captured.push({input: s, output: retval.toString()});
                        send({type:'rs', msg: 'string: ' + s});
                    }
                } catch(e) {}
            }
        });
        send({type:'h', msg: 'hooked il2cpp_string_new for ' + durationMs + 'ms'});
        return {ok: true, captured: captured};
    }
};
"""
script = sess.create_script(js)
script.load()

# Find ALL "PvP Rank" hits
print('=== All hits for "PvP Rank: " (template + rendered) ===')
hits = script.exports_sync.find_all_strings('PvP Rank: ')
for h in hits[:20]:
    print(f"  addr={h['addr']} rangeBase={h['rangeBase']} prot={h['prot']} file={h['file']}")

print(f"\nTotal: {len(hits)}")

print('\n=== Examining first hit context ===')
if hits:
    addr = int(hits[0]['addr'], 16)
    # Read 100 bytes before and 200 after
    m = script.exports_sync.examine_range(hex(addr - 50), 300)
    if 'ascii' in m:
        print('  ' + m['ascii'][:600])

print('\n=== All anonymous (file=None) memory ranges (potential Pokemod regions) ===')
ranges = script.exports_sync.list_all_ranges()
ranges.sort(key=lambda r: -r['size'])
for r in ranges[:15]:
    print(f"  base={r['base']} size={r['size']:>10} prot={r['prot']}")

sess.detach()
