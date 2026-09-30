"""Look for Pokemod's per-pokemon rank cache.

Strategy: pick a known pokemon UID, search memory for it, look at neighbors for rank values.
"""
import frida, subprocess, json, sqlite3

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    findUidInMemory: function(uidUnsigned) {
        // uidUnsigned is a string of an unsigned 64-bit int
        var uidU64 = uint64(uidUnsigned);
        // Build little-endian 8-byte pattern
        var hex = uidU64.toString(16).padStart(16, '0');
        var bytes = hex.match(/.{2}/g).reverse().join(' ');
        var hits = [];
        var ranges = Process.enumerateRanges('rw-');
        for (var r = 0; r < ranges.length; r++) {
            if (ranges[r].size > 100*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, bytes).forEach(function(m){
                    hits.push({addr: m.address.toString(),
                               rangeBase: ranges[r].base.toString(),
                               rangeSize: ranges[r].size,
                               file: ranges[r].file ? ranges[r].file.path : null});
                });
            } catch(e) {}
        }
        return hits;
    },
    examineNeighborhood: function(addr, before, after) {
        var p = ptr(addr);
        try {
            var bytes = p.sub(before).readByteArray(before + after);
            var u8 = new Uint8Array(bytes);
            var hex = '';
            var ascii = '';
            for (var i = 0; i < u8.length; i++) {
                hex += ('0' + u8[i].toString(16)).slice(-2) + ' ';
                ascii += (u8[i] >= 32 && u8[i] < 127) ? String.fromCharCode(u8[i]) : '.';
                if ((i+1) % 32 === 0) { hex += '|'; ascii += '|'; }
            }
            return {hex: hex, ascii: ascii};
        } catch(e) { return {err: e.message}; }
    },
    /* Hook native dlsym to find Pokemod's exported functions */
    listRwxRanges: function() {
        var ranges = Process.enumerateRanges('r-x');
        return ranges.filter(function(r){ return r.size < 50*1024*1024 && !r.file; })
                     .map(function(r){ return {base: r.base.toString(), size: r.size, prot: r.protection}; });
    }
};
"""
script = sess.create_script(js)
script.load()

conn = sqlite3.connect('pokemon.db')
c = conn.cursor()

# Pick a few well-known pokemon: highest IV in popular species
# Use a hundo or near-hundo
test_pokemon = c.execute('''SELECT uid_hex, uid, species_name, cp, iv_pct
    FROM pokemon WHERE in_bag=1 AND iv_pct >= 100 AND species_name='Machamp'
    LIMIT 1''').fetchone()
if not test_pokemon:
    test_pokemon = c.execute('''SELECT uid_hex, uid, species_name, cp, iv_pct
        FROM pokemon WHERE in_bag=1 AND iv_pct >= 100 LIMIT 1''').fetchone()
uid_hex, uid, sp, cp, iv = test_pokemon
uid_unsigned = uid if uid >= 0 else uid + 2**64
print(f'Searching for UID of {sp} CP{cp} IV{iv} (uid={uid_unsigned}, hex={uid_hex})...')

hits = script.exports_sync.find_uid_in_memory(str(uid_unsigned))
print(f'Found {len(hits)} hits')

# Group hits by file (anonymous = potential Pokemod region)
from collections import defaultdict
by_range = defaultdict(list)
for h in hits[:50]:
    key = (h['rangeBase'], h['file'])
    by_range[key].append(h['addr'])
print('\nBy memory range:')
for (rb, f), addrs in by_range.items():
    print(f'  range={rb} file={f} -> {len(addrs)} hits')

# Show neighborhood of the first 5 hits
print('\n=== Neighborhood of first 3 hits (16 before, 32 after) ===')
for h in hits[:3]:
    print(f"\n  addr={h['addr']} file={h['file']}")
    m = script.exports_sync.examine_neighborhood(h['addr'], 16, 64)
    if 'hex' in m:
        print(f"    hex: {m['hex'][:200]}")
        print(f"    asc: {m['ascii'][:100]}")

# Also look for r-x anonymous ranges (Pokemod code)
print('\n=== Anonymous r-x ranges (potential Pokemod code) ===')
rwx = script.exports_sync.list_rwx_ranges()
for r in rwx[:10]:
    print(f"  base={r['base']} size={r['size']:>10}")

sess.detach()
