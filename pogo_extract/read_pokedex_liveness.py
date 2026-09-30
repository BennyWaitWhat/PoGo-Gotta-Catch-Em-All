"""Use IL2CPP liveness API for fast PokedexImpl lookup (zero false positives).
Per agent recommendation: il2cpp_unity_liveness_calculation_from_statics walks live objects of a class."""
import frida, json, subprocess, sys, time
sys.stdout.reconfigure(line_buffering=True)
subprocess.run(['adb','connect','100.98.158.56:5555'], capture_output=True)
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PID: {pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(pid)

js = r"""
var IL2 = null, CLS = null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    IL2 = {
        dG: bind('il2cpp_domain_get','pointer',[]),
        dGA: bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']),
        aGI: bind('il2cpp_assembly_get_image','pointer',['pointer']),
        iGN: bind('il2cpp_image_get_name','pointer',['pointer']),
        cFN: bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']),
        tA: bind('il2cpp_thread_attach','pointer',['pointer']),
        // Liveness API:
        livenessAlloc: exp['il2cpp_unity_liveness_allocate_struct'] ? bind('il2cpp_unity_liveness_allocate_struct','pointer',['pointer','int','pointer','pointer','pointer']) : null,
        livenessFromStatics: exp['il2cpp_unity_liveness_calculation_from_statics'] ? bind('il2cpp_unity_liveness_calculation_from_statics','void',['pointer']) : null,
        livenessFinalize: exp['il2cpp_unity_liveness_finalize'] ? bind('il2cpp_unity_liveness_finalize','void',['pointer']) : null,
        livenessFreeStruct: exp['il2cpp_unity_liveness_free_struct'] ? bind('il2cpp_unity_liveness_free_struct','void',['pointer']) : null,
        stopWorld: exp['il2cpp_stop_gc_world'] ? bind('il2cpp_stop_gc_world','void',[]) : null,
        startWorld: exp['il2cpp_start_gc_world'] ? bind('il2cpp_start_gc_world','void',[]) : null,
        alloc: bind('il2cpp_alloc','pointer',['size_t']),
        free: bind('il2cpp_free','void',['pointer']),
    };
    IL2.tA(IL2.dG());
    var sp = Memory.alloc(4); var asms = IL2.dGA(IL2.dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=IL2.aGI(asms.add(a*Process.pointerSize).readPointer()); if (IL2.iGN(i).readCString()==='holo-game.dll'){gi=i;break;} }
    CLS = IL2.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokedexImpl'));
    return {ok:true, hasLiveness: !!(IL2.livenessAlloc && IL2.livenessFromStatics)};
}

rpc.exports = {
    init: init,
    findPokedexInstances: function() {
        if (!CLS) init();
        if (!IL2.livenessAlloc) return {err: 'liveness API not exported in this libil2cpp.so'};
        var hits = [];
        var onObjects = new NativeCallback(function(objects, count, userData) {
            for (var i = 0; i < count; i++) {
                hits.push(objects.add(i * Process.pointerSize).readPointer().toString());
            }
        }, 'void', ['pointer','int','pointer']);
        var realloc = new NativeCallback(function(handle, size, userData) {
            if (!handle.isNull() && size.compare(0) === 0) { IL2.free(handle); return ptr(0); }
            return IL2.alloc(size);
        }, 'pointer', ['pointer','size_t','pointer']);
        try {
            if (IL2.stopWorld) IL2.stopWorld();
            var state = IL2.livenessAlloc(CLS, 0, onObjects, ptr(0), realloc);
            IL2.livenessFromStatics(state);
            if (IL2.livenessFinalize) IL2.livenessFinalize(state);
            if (IL2.startWorld) IL2.startWorld();
            if (IL2.livenessFreeStruct) IL2.livenessFreeStruct(state);
        } catch(e) {
            if (IL2.startWorld) { try { IL2.startWorld(); } catch(e2){} }
            return {err: 'liveness threw: ' + e.toString()};
        }
        return {hits: hits};
    },
    readHundos: function(addr) {
        function readUtf16Str(strPtr) { if (strPtr.isNull()) return ''; var len = strPtr.add(0x10).readS32(); if (len <= 0 || len > 200) return ''; var chars = []; for (var i = 0; i < len; i++) chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16())); return chars.join(''); }
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
            // FULL schema, matching pogo_pipeline.pipelineReadDex -- this file is shared state;
            // a slim {pid,hundo} overwrite silently emptied account_report's caught set (2026-06-09).
            var timesCaptured = protoPtr.add(0x18).readS32();
            var capturedForms = [];
            try {
                var cf = protoPtr.add(0x50).readPointer();
                if (!cf.isNull()) {
                    var cfn = cf.add(0x18).readS32();
                    // CLAMP not cutoff -- Pikachu is at 46 forms; <60 dropped the whole list (audit F20)
                    if (cfn > 0 && cfn < 1000) {
                        var cfx = Math.min(cfn, 256);
                        var cfi = cf.add(0x10).readPointer();
                        for (var ci = 0; ci < cfx; ci++) capturedForms.push(cfi.add(0x20 + ci*4).readS32());
                    }
                }
            } catch(e) {}
            var hundoAcq = false, shinyHundoAcq = false, purifiedAcq = false;
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
                                if (catEnum === 16 && acq) purifiedAcq = true;
                            }
                            var next = node.add(0x18).readPointer();
                            if (next.isNull() || next.equals(head)) break;
                            node = next;
                        } catch(e) { break; }
                        iters++;
                    }
                }
            }
            results.push({pid: pidv, times: timesCaptured, forms: capturedForms, hundo: hundoAcq, shinyHundo: shinyHundoAcq, purified: purifiedAcq});
        }
        return {count: results.length, entries: results};
    }
};
"""
sc = sess.create_script(js); sc.load()
init_r = sc.exports_sync.init()
print(f"Init: {init_r}")
if not init_r.get('hasLiveness'):
    print("Liveness API not available - libil2cpp.so doesn't export the needed symbols")
    sess.detach(); exit(1)

print("Calling liveness API for PokedexImpl instances...")
r = sc.exports_sync.find_pokedex_instances()
print(f"Result: {r}")
if r.get('err'):
    sess.detach(); exit(1)
hits = r['hits']
print(f"Found {len(hits)} live PokedexImpl instance(s)")
if not hits:
    print("No live instances - dex not yet initialized?")
    sess.detach(); exit(1)

# Read hundos from the first (only) instance
inst = hits[0]
print(f"Reading from {inst}...")
hr = sc.exports_sync.read_hundos(inst)
print(f"Walked {hr['count']} entries")

by_pid = {e['pid']: e for e in hr['entries']}
targets = {
    452:'Drapion', 18:'Pidgeot', 331:'Cacnea', 486:'Regigigas', 131:'Lapras',
    460:'Abomasnow', 497:'Serperior', 334:'Altaria', 143:'Snorlax', 365:'Walrein',
    82:'Magneton', 277:'Swellow', 38:'Ninetales', 8:'Wartortle', 380:'Latias',
    344:'Claydol', 566:'Archen', 524:'Roggenrola'
}
print(f"\n{'Species':<15} {'pid':>4} {'live_dex_hundo':>14} {'new_to_dex?':>12}")
print('-'*55)
new_count = 0
for pid_t, name in sorted(targets.items()):
    e = by_pid.get(pid_t, {})
    h = e.get('hundo', False)
    is_new = not h
    if is_new: new_count += 1
    print(f"{name:<15} {pid_t:>4} {('YES' if h else 'no'):>14} {('NEW!' if is_new else ''):>12}")
print(f"\nCandidates that would be NEW dex hundo (LIVE data): {new_count}")
# Write with the SAME contract as pogo_pipeline.step_read_dex: stash .prev, full entries,
# and regenerate the caught-state derivatives so downstream tools never see schema drift.
import os, shutil
if os.path.exists('pokedex_hundos_live.json'):
    shutil.copyfile('pokedex_hundos_live.json', 'pokedex_hundos_live.prev.json')
with open('pokedex_hundos_live.json','w') as f:
    json.dump({'pid_when_scanned': pid, 'addr': inst, 'count': hr['count'], 'entries': hr['entries']}, f)
caught = sorted({e['pid'] for e in hr['entries'] if e.get('times', 0) > 0})
with open('dex_caught.json', 'w') as f:
    json.dump(caught, f)
caught_forms = {str(e['pid']): e.get('forms', []) for e in hr['entries'] if e.get('times', 0) > 0}
with open('dex_caught_forms.json', 'w') as f:
    json.dump(caught_forms, f)
print(f"Saved pokedex_hundos_live.json (+.prev stash, dex_caught.json {len(caught)}, dex_caught_forms.json)")
sess.detach()
