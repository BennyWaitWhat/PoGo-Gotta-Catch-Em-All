"""One-shot: heap-scan for PokedexImpl, probe each candidate, read fresh hundo state, save JSON."""
import frida, json, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
subprocess.run(['adb','connect','100.98.158.56:5555'], capture_output=True)
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PID: {pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

js = """
var fns={}, gi=null, cls=null;
function initIL2() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG=bind('il2cpp_domain_get','pointer',[]);
    fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']); fns.tA(fns.dG());
    var sp=Memory.alloc(4); var asms=fns.dGA(fns.dG(),sp); var na=sp.readS32();
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){gi=i;break;} }
    cls=fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokedexImpl'));
}
initIL2();

rpc.exports = {
    scanChunk: function(startHi, sizeBytes) {
        var hits = [];
        var startAddr = ptr(startHi); var endAddr = startAddr.add(sizeBytes);
        Process.enumerateRanges({protection:'rw-'}).forEach(function(r){
            if (hits.length > 50) return;
            var rEnd = r.base.add(r.size);
            if (r.base.compare(endAddr) >= 0 || rEnd.compare(startAddr) <= 0) return;
            var p = r.base.compare(startAddr) > 0 ? r.base : startAddr;
            var e = rEnd.compare(endAddr) < 0 ? rEnd : endAddr;
            while (p.compare(e) < 0 && hits.length < 50) {
                try { if (p.readPointer().equals(cls)) hits.push(p.toString()); } catch(e2) {}
                p = p.add(8);
            }
        });
        return {hits: hits};
    },
    probeCount: function(addr) {
        // Strict probe: validate every pointer is heap-resident before deref
        try {
            var inst = ptr(addr);
            // 0. klass slot at +0 still equals target class
            if (!inst.readPointer().equals(cls)) return {err:'klass mismatch'};
            // 1. dict pointer
            var dict = inst.add(0x10).readPointer();
            if (dict.isNull() || dict.and(7).compare(0) !== 0) return {err:'bad dict'};
            try { dict.readU8(); } catch(e) { return {err:'dict unreadable'}; }
            // 2. dict's klass at +0
            var dictKlass = dict.readPointer();
            if (dictKlass.isNull() || dictKlass.and(7).compare(0) !== 0) return {err:'bad dict klass'};
            try { dictKlass.readU8(); } catch(e) { return {err:'dict klass unreadable'}; }
            // 3. entries array
            var entries = dict.add(0x18).readPointer();
            if (entries.isNull() || entries.and(7).compare(0) !== 0) return {err:'bad entries'};
            try { entries.readU8(); } catch(e) { return {err:'entries unreadable'}; }
            // 4. count plausible
            var count = entries.add(0x18).readS32();
            if (count < 500 || count > 4000) return {err:'count oor', count: count};
            // 5. first proto valid
            var firstProto = entries.add(0x20).add(16).readPointer();
            if (firstProto.isNull() || firstProto.and(7).compare(0) !== 0) return {err:'bad first proto'};
            try { firstProto.readU8(); } catch(e) { return {err:'first proto unreadable'}; }
            return {count: count};
        } catch(e) { return {err: e.toString()}; }
    },
    readHundos: function(addr) {
        function readUtf16Str(strPtr) {
            if (strPtr.isNull()) return '';
            var len = strPtr.add(0x10).readS32();
            if (len <= 0 || len > 200) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
            return chars.join('');
        }
        var inst = ptr(addr);
        var dictAll = inst.add(0x10).readPointer();
        var entries = dictAll.add(0x18).readPointer();
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);
        var results = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var pidv = ep.add(8).readS32();
            var protoPtr = ep.add(16).readPointer();
            if (protoPtr.isNull()) continue;
            var hundoAcq = false, shinyHundoAcq = false;
            var mapField = protoPtr.add(0x80).readPointer();
            if (!mapField.isNull()) {
                var list = mapField.add(0x18).readPointer();
                if (!list.isNull()) {
                    var head = list.add(0x10).readPointer();
                    var lcount = list.add(0x18).readS32();
                    var node = head; var iters = 0;
                    while (node && !node.isNull() && iters < lcount + 50) {
                        try {
                            var kvpVal = node.add(0x30).readPointer();
                            if (!kvpVal.isNull()) {
                                var catEnum = kvpVal.add(0x10).readS32();
                                var acq = kvpVal.add(0x15).readU8();
                                if (catEnum === 14 && acq) hundoAcq = true;
                                if (catEnum === 102 && acq) shinyHundoAcq = true;
                            }
                            var next = node.add(0x18).readPointer();
                            if (next.isNull() || next.equals(head)) break;
                            node = next;
                        } catch(e) { break; }
                        iters++;
                    }
                }
            }
            results.push({pid: pidv, hundo: hundoAcq, shinyHundo: shinyHundoAcq});
        }
        return {count: results.length, entries: results};
    }
};
"""
sc = sess.create_script(js); sc.load()

# Stage 1: heap scan for PokedexImpl candidates
print("Heap-scanning for PokedexImpl...")
all_hits = []
base = 0x7000000000
chunk = 0x10000000
for offset in range(0, 0x1000000000, chunk):
    try:
        r = sc.exports_sync.scan_chunk(base + offset, chunk)
        if r['hits']:
            all_hits.extend(r['hits'])
            if len(all_hits) > 30: break
    except Exception as e:
        print(f"  scan fail at 0x{base+offset:x}: {e}")
        break
print(f"Found {len(all_hits)} candidates")

# Stage 2: probe each candidate for cugr dict count
print("\nProbing candidates (all results)...")
best = None; best_count = 0
result_buckets = {'err': 0, 'zero': 0, 'small': 0, 'good': 0, 'big': 0}
all_probes = []
for cand in all_hits:
    try:
        r = sc.exports_sync.probe_count(cand)
        if 'err' in r:
            result_buckets['err'] += 1
            continue
        cnt = r.get('count', 0)
        all_probes.append((cand, cnt))
        if cnt == 0: result_buckets['zero'] += 1
        elif cnt < 500: result_buckets['small'] += 1
        elif cnt < 4000: result_buckets['good'] += 1
        else: result_buckets['big'] += 1
        if 500 <= cnt < 4000 and cnt > best_count:
            best = cand; best_count = cnt
    except Exception as e:
        pass
print(f"  buckets: {result_buckets}")
print(f"  top 10 by count:")
for cand, cnt in sorted(all_probes, key=lambda x: -x[1])[:10]:
    print(f"    {cand}: count={cnt}")
print(f"\nChosen PokedexImpl: {best} (count={best_count})")
if not best:
    print("FAILED"); sess.detach(); exit(1)

# Stage 3: read hundo state
print("\nReading hundo state...")
r = sc.exports_sync.read_hundos(best)
print(f"Walked {r['count']} entries")
by_pid = {e['pid']: e for e in r['entries']}

# Save snapshot -- QUARANTINED filename (audit F11): this legacy heap-scan reader emits a SLIM schema
# ({pid,hundo,shinyHundo} -- no times/forms/purified). Writing the CANONICAL pokedex_hundos_live.json
# with it silently corrupts every downstream consumer (account_report reads 0 caught; evo_hundo_gap
# disagrees). Use read_pokedex_liveness.py / the pipeline for the canonical file.
with open('pokedex_hundos_live.heapscan.json','w') as f:
    json.dump({'pid_when_scanned': pid, 'addr': best, 'count': r['count'], 'entries': r['entries']}, f)
print("Saved pokedex_hundos_live.heapscan.json (slim schema -- NOT the canonical file; "
      "run read_pokedex_liveness.py or the pipeline for pokedex_hundos_live.json)")

# Stage 4: check the 18 candidates
targets = {
    452:'Drapion', 18:'Pidgeot', 331:'Cacnea', 486:'Regigigas', 131:'Lapras',
    460:'Abomasnow', 497:'Serperior', 334:'Altaria', 143:'Snorlax', 365:'Walrein',
    82:'Magneton', 277:'Swellow', 38:'Ninetales', 8:'Wartortle', 380:'Latias',
    344:'Claydol', 566:'Archen', 524:'Roggenrola'
}
print(f"\n{'Species':<15} {'pid':>4} {'dex_hundo':>10} {'shiny_hundo':>12} {'new?':>6}")
print('-'*60)
new_count = 0
for pid_t, name in sorted(targets.items()):
    e = by_pid.get(pid_t, {})
    h = e.get('hundo', False); sh = e.get('shinyHundo', False)
    is_new = not h
    if is_new: new_count += 1
    print(f"{name:<15} {pid_t:>4} {('YES' if h else 'no'):>10} {('YES' if sh else 'no'):>12} {('NEW!' if is_new else ''):>6}")
print(f"\nCandidates that would be NEW dex hundo: {new_count}")
sess.detach()
