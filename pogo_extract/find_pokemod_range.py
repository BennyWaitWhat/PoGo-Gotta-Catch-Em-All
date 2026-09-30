"""Find Pokemod's memory range and look for ranking data structure."""
import frida, subprocess

adb_pid = int(subprocess.check_output(['adb','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

js = """
rpc.exports = {
    findRangesAround: function(addr) {
        var p = ptr(addr);
        var ranges = Process.enumerateRanges('r--');
        for (var i = 0; i < ranges.length; i++) {
            var r = ranges[i];
            if (p.compare(r.base) >= 0 && p.compare(r.base.add(r.size)) < 0) {
                return {base: r.base.toString(), size: r.size, prot: r.protection, file: r.file ? r.file.path : null};
            }
        }
        return null;
    },
    listRangesNear: function(addr, beforeKb, afterKb) {
        var p = ptr(addr);
        var ranges = Process.enumerateRanges('---');
        var nearby = [];
        for (var i = 0; i < ranges.length; i++) {
            var r = ranges[i];
            var diff = r.base.compare(p);
            // very rough: within +/- 100MB
            try {
                var distance = parseInt(r.base.toString()) - parseInt(p.toString());
                if (Math.abs(distance) < 100*1024*1024) {
                    nearby.push({base: r.base.toString(), size: r.size, prot: r.protection, file: r.file ? r.file.path : null, dist: distance});
                }
            } catch(e) {}
        }
        nearby.sort(function(a, b) { return Math.abs(a.dist) - Math.abs(b.dist); });
        return nearby.slice(0, 20);
    },
    findStrings: function(queries) {
        var hits = [];
        var ranges = Process.enumerateRanges('r--');
        for (var q = 0; q < queries.length; q++) {
            var qstr = queries[q];
            var pattern = '';
            for (var i = 0; i < qstr.length; i++) {
                pattern += ('0' + qstr.charCodeAt(i).toString(16)).slice(-2) + ' ';
            }
            var samples = [];
            for (var r = 0; r < ranges.length && samples.length < 10; r++) {
                if (ranges[r].size > 100*1024*1024) continue;
                try {
                    Memory.scanSync(ranges[r].base, ranges[r].size, pattern.trim()).forEach(function(m){
                        if (samples.length < 10) samples.push(m.address.toString());
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

print('=== Range containing PvP Rank string ===')
print(script.exports_sync.find_ranges_around('0x72a1ff65b8'))

print('\n=== Ranges near Pokemod string ===')
near = script.exports_sync.list_ranges_near('0x72a1ff1680', 0, 0)
for r in near[:10]:
    print(f"  base={r['base']} size={r['size']:>10} prot={r['prot']} dist={r['dist']:>12} file={r['file']}")

print('\n=== Searching for PvP-specific strings ===')
hits = script.exports_sync.find_strings([
    'GreatLeagueRank', 'UltraLeagueRank', 'getRank', 'computeRank',
    'pvpRanker', 'leagueRanker', 'StatProductRanker',
    'pokemonRanks', 'rankCache', 'rankMap',
    'great_league', 'ultra_league',
    '/4096)', 'leagueRank',
    'Pokemod.PvP', 'pvp_rank', 'GLRank', 'ULRank'
])
for h in hits:
    if h['count']:
        print(f"  {h['q']:30s} {h['count']:>3} hits  {h['samples'][:3]}")
sess.detach()
