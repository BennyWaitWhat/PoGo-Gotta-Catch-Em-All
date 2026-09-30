"""Read PokedexImpl per-entry CategoryStatus map to find FourStar (hundo) acquired entries.

PokedexImpl singleton -> 10 dicts (cugr=All gen0, cugs=Kanto gen1, cugt=Johto gen2, cugu=Hoenn gen3,
cugv=Sinnoh gen4, cugw=Unova gen5, cugx=Kalos gen6, cugy=Alola gen7, cugz=Galar gen8, cuha=Paldea gen9).

Each dict: Dictionary<int(pokemonId), PokedexEntryProto>.
Each PokedexEntryProto +0x80 -> MapField<String, PokedexCategoryStatus>.
MapField layout: +0x28 -> LinkedList<KVP<String, Status>> (preserves insertion order).
LinkedList: +0x10 head node, +0x18 count.
LinkedListNode: +0x18 next, +0x28 KVP { +0x00 key:String*, +0x08 value:Status* }.
PokedexCategoryStatus: +0x10 PokedexCategory enum, +0x14 Encountered, +0x15 Acquired.
PokedexCategory enum: 0=Unset, 1=All, 2=Mega, 3=Shiny, 4=Lucky, 5=ThreeStar,
                      6=FourStar, 7=Shadow, 8=Purified, 9=Costume, 10=BreadMode,
                      11=BreadDoughMode, 12=ShinyThreeStar, 13=ShinyFourStar,
                      14=SizeXxs, 15=SizeXxl
"""
import frida, json, time, subprocess
_T0 = time.time()
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")
_tick("start")
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
_tick("adb pidof done")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
_tick("attached")

# Hook to capture instance
hook_js = """
var inst = null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var addrs = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) addrs[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(addrs[n],r,a); }
    var dG = bind('il2cpp_domain_get','pointer',[]);
    var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    var tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    tA(dG());
    var sp = Memory.alloc(4); var asms = dGA(dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var cls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokedexImpl'));
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = cGM(cls, iter)) && !m.isNull()) {
        try {
            var addr = m.readPointer();
            if (addr.isNull()) continue;
            Interceptor.attach(addr, {
                onEnter: function(args) {
                    if (!inst) { inst = args[0].toString(); send({type:'h', msg:'inst '+inst}); }
                }
            });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {inst: inst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
_tick("hook script loaded")
hs.exports_sync.setup()
_tick("hook setup() returned (Interceptor.attach for all PokedexImpl methods)")
print("Waiting up to 60s for PokedexImpl hook...")
inst = None
_wait_start = time.time()
for i in range(60):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('inst'):
        inst = g['inst']; break
_tick(f"hook wait done after {time.time()-_wait_start:.1f}s (inst={'CAPTURED' if inst else 'TIMEOUT'})")
if not inst:
    # Try multiple heap-scan candidates - first one with non-empty cugr dict wins
    candidates = ['0x72f0053bf8', '0x72fdd93110', '0x72fdd9a4d0', '0x72fdd9a550', '0x72fdd9a590']
    inst = candidates[0]
    print(f"Hook didn't fire, trying heap-scan candidates starting with {inst}")
print(f"PokedexImpl: {inst}")
hs.unload()

js = """
rpc.exports = {
    readAllHundos: function(addr) {
        var inst = ptr(addr);
        function readUtf16Str(strPtr) {
            if (strPtr.isNull()) return '';
            var len = strPtr.add(0x10).readS32();
            if (len <= 0 || len > 200) return '';
            var chars = [];
            for (var i = 0; i < len; i++) chars.push(String.fromCharCode(strPtr.add(0x14 + i*2).readU16()));
            return chars.join('');
        }

        // Iterate cugr (All dict at +0x10): Dictionary<int, PokedexEntryProto>
        var dictAll = inst.add(0x10).readPointer();
        var entries = dictAll.add(0x18).readPointer();
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);

        var results = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var pid = ep.add(8).readS32();
            var protoPtr = ep.add(16).readPointer();
            if (protoPtr.isNull()) continue;

            // PokedexEntryProto +0x10 EntryNumber, +0x18 TimesCaptured, +0x40 CapturedShiny, +0x80 CategoryStatus MapField
            var entryNum = protoPtr.add(0x10).readS32();
            var timesCaptured = protoPtr.add(0x18).readS32();
            var capturedShiny = protoPtr.add(0x40).readU8();

            // Walk CategoryStatus MapField: object at +0x80 -> list (LinkedList<KVP>) at +0x28 of MapField
            var mapField = protoPtr.add(0x80).readPointer();
            var hundoAcq = false, hundoEnc = false;
            var shinyHundoAcq = false;
            var threeStarAcq = false;
            var luckyAcq = false;
            var shadowAcq = false, purifiedAcq = false;
            var hundoTimestamp = '0';
            var categories = [];
            if (!mapField.isNull()) {
                var list = mapField.add(0x18).readPointer();
                if (!list.isNull()) {
                    var head = list.add(0x10).readPointer();
                    var lcount = list.add(0x18).readS32();
                    var node = head; var iters = 0;
                    while (node && !node.isNull() && iters < lcount + 50) {
                        try {
                            // LinkedListNode<KVP<String, Status>>: +0x18 next, +0x28 item (KVP)
                            var kvpKey = node.add(0x28).readPointer();  // String*
                            var kvpVal = node.add(0x30).readPointer(); // Status*
                            var keyStr = readUtf16Str(kvpKey);
                            if (!kvpVal.isNull()) {
                                var catEnum = kvpVal.add(0x10).readS32();
                                var enc = kvpVal.add(0x14).readU8();
                                var acq = kvpVal.add(0x15).readU8();
                                var ts = kvpVal.add(0x18).readU64().toString();
                                categories.push({k:keyStr, c:catEnum, e:enc, a:acq, t:ts});
                                if (catEnum === 14 && acq) { hundoAcq = true; hundoTimestamp = ts; }
                                if (catEnum === 14 && enc) hundoEnc = true;
                                if (catEnum === 102 && acq) shinyHundoAcq = true;
                                if (catEnum === 13 && acq) threeStarAcq = true;
                                if (catEnum === 12 && acq) luckyAcq = true;
                                if (catEnum === 15 && acq) shadowAcq = true;
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
            results.push({
                pid: pid, entryNum: entryNum, captured: timesCaptured, shiny: capturedShiny,
                hundo: hundoAcq, hundoEnc: hundoEnc, hundoTs: hundoTimestamp,
                shinyHundo: shinyHundoAcq, threeStar: threeStarAcq, lucky: luckyAcq,
                shadow: shadowAcq, purified: purifiedAcq,
                cats: categories
            });
        }
        return {count: results.length, entries: results};
    }
};
"""
script = sess.create_script(js)
script.load()
_tick("reader script loaded")
# If hook didn't fire and we used a candidate, try multiple
r = None
try_list = [inst]
if 'candidates' in dir(): try_list = candidates
for cand in try_list:
    try:
        _p = time.time()
        r = script.exports_sync.read_all_hundos(cand)
        _tick(f"read_all_hundos RPC ({time.time()-_p:.2f}s, count={r['count']}) cand={cand}")
        if r['count'] > 100:
            print(f"\nUsing candidate {cand} - walked {r['count']} entries")
            break
    except Exception as e:
        print(f"  {cand}: {e}")
        continue
if not r or r.get('count', 0) < 100:
    print("Failed to find valid PokedexImpl"); sess.detach(); exit(1)
print(f"\nWalked {r['count']} pokedex entries")

# Stats
hundos = [e for e in r['entries'] if e['hundo']]
shiny_hundos = [e for e in r['entries'] if e['shinyHundo']]
threes = [e for e in r['entries'] if e['threeStar']]
print(f"\nHundo (FourStar acquired): {len(hundos)}")
print(f"Shiny hundo (ShinyFourStar acquired): {len(shiny_hundos)}")
print(f"ThreeStar acquired: {len(threes)}")

# Save
_p = time.time()
with open('pokedex_full.json','w') as f:
    json.dump(r, f, indent=2)
_tick(f"json.dump ({time.time()-_p:.2f}s)")
print(f"\nSaved {r['count']} entries to pokedex_full.json")

# Print a few specific entries to verify
for pid in [1, 3, 133, 25]:  # Bulbasaur, Venusaur, Eevee, Pikachu
    e = next((x for x in r['entries'] if x['pid'] == pid), None)
    if e:
        print(f"\nPID {pid}: hundo={e['hundo']} threeStar={e['threeStar']} shiny={bool(e['shiny'])} shinyHundo={e['shinyHundo']}")
        print(f"  categories: {[(c['k'], c['c'], 'A' if c['a'] else '-', 'E' if c['e'] else '-') for c in e['cats']]}")
sess.detach()
_tick("done")
