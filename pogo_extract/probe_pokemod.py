"""Probe Pokemod's in-memory presence."""
import frida, subprocess

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    examineMemory: function(addrStr, len) {
        var p = ptr(addrStr);
        try {
            var bytes = p.readByteArray(len || 256);
            var u8 = new Uint8Array(bytes);
            var ascii = '';
            for (var i = 0; i < u8.length; i++) {
                ascii += (u8[i] >= 32 && u8[i] < 127) ? String.fromCharCode(u8[i]) : '.';
            }
            return {ascii: ascii};
        } catch(e) { return {err: e.message}; }
    },
    scanStrings: function(queryArr) {
        var hits = [];
        var ranges = Process.enumerateRanges('r--');
        for (var q = 0; q < queryArr.length; q++) {
            var qstr = queryArr[q];
            var pattern = '';
            for (var i = 0; i < qstr.length; i++) {
                pattern += ('0' + qstr.charCodeAt(i).toString(16)).slice(-2) + ' ';
            }
            var samples = [];
            for (var r = 0; r < ranges.length && samples.length < 5; r++) {
                if (ranges[r].size > 100*1024*1024) continue;
                try {
                    Memory.scanSync(ranges[r].base, ranges[r].size, pattern.trim()).forEach(function(m){
                        if (samples.length < 5) samples.push(m.address.toString());
                    });
                } catch(e) {}
            }
            hits.push({q: qstr, count: samples.length, samples: samples});
        }
        return hits;
    }
};
"""
script = sess.create_script(js)
script.load()

print('=== Memory around Pokemod string ===')
for addr in ['0x72a1ff1680', '0x72a1ffe220', '0x72a1ffe370']:
    m = script.exports_sync.examine_memory(addr, 200)
    if 'ascii' in m:
        print(f'\n{addr}:')
        print(m['ascii'])

print('\n=== Memory around PvP Rank string ===')
for addr in ['0x72a1ff65b8', '0x7340c704f8']:
    m = script.exports_sync.examine_memory(addr, 300)
    if 'ascii' in m:
        print(f'\n{addr}:')
        print(m['ascii'])

print('\n=== Looking for printf format strings related to rank ===')
queries = [
    'Great League: #', 'Ultra League: #',
    'GL #', 'UL #',
    '#%d/4096', '%d/4096', '/4096',
    'StatProd', 'GreatLeagueRank', 'UltraLeagueRank',
    '%.2f%%', '%d (%.1f%%)',
    'libpokemod', 'libconceal', 'pokemod_'
]
hits = script.exports_sync.scan_strings(queries)
for h in hits:
    if h['count']:
        print(f"  {repr(h['q']):25s} {h['count']} hits: {h['samples'][:3]}")
sess.detach()
