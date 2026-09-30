"""Untag 8 over-tagged JUMBOs - self-contained, fresh PID + fresh hooks each run."""
import frida, time, subprocess, sqlite3, sys
sys.stdout.reconfigure(line_buffering=True)
subprocess.run(['adb','connect','100.98.158.56:5555'], capture_output=True)
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PoGo PID: {adb_pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Compute target untag set
conn = sqlite3.connect('pokemon.db'); conn.row_factory = sqlite3.Row; c = conn.cursor()
rows = c.execute('SELECT * FROM pokemon WHERE in_bag=1 AND pokemon_size_category=5').fetchall()
groups = {}
for p in rows:
    key = (p['pokemon_id'], p['form'] or 0, p['fresh_costume'] or 0)
    groups.setdefault(key, []).append(p)
target = set()
for key, lst in groups.items():
    for p in sorted(lst, key=lambda x: -(x['weight_kg'] or 0))[:2]: target.add(p['uid_hex'])
    for p in sorted(lst, key=lambda x: -(x['height_m'] or 0))[:2]: target.add(p['uid_hex'])
srv = {r[0] for r in c.execute("SELECT uid_hex FROM pokemon WHERE in_bag=1 AND auth_tag_names LIKE '%JUMBO%'")}
to_remove = sorted(srv - target)
print(f"Target JUMBO: {len(target)}  Server: {len(srv)}  To remove: {len(to_remove)}")
def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
uid_strs = []
for uh in to_remove:
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    if r: uid_strs.append((uh, to_uid_str(r[0])))

# Single combined script: hook + heap scan + walk + tag operations
combined_js = """
var fns={}; var bagInst=null, svcInstHook=null; var bagCls=null, svcCls=null, gi=null;
function initIL2() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG=bind('il2cpp_domain_get','pointer',[]); fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']); fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']); fns.cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.cMN=bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
    fns.rI=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
    fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']); fns.tA(fns.dG());
    var sp = Memory.alloc(4); var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    bagCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
    svcCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
}

rpc.exports = {
    setup: function() {
        initIL2();
        // Hook only a few key methods per class to avoid overloading
        function hookKey(cls, names, label) {
            var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
            var m, found = 0;
            while ((m = fns.cGM(cls, iter)) && !m.isNull()) {
                var nm = fns.mGN(m).readCString();
                if (names.indexOf(nm) >= 0) {
                    try {
                        var addr = m.readPointer();
                        if (addr.isNull()) continue;
                        Interceptor.attach(addr, {
                            onEnter: function(args) {
                                if (label === 'bag' && !bagInst) { bagInst = args[0].toString(); send({type:'h', msg:'bag '+bagInst}); }
                                if (label === 'svc' && !svcInstHook) { svcInstHook = args[0].toString(); send({type:'h', msg:'svc '+svcInstHook}); }
                            }
                        });
                        found++;
                    } catch(e) {}
                }
            }
            return found;
        }
        var n1 = hookKey(bagCls, ['get_AllPokemon','get_Count','get_AllPokemonProtos','GetPokemonByUid'], 'bag');
        var n2 = hookKey(svcCls, ['GetEnabledFilter','get_NumberOfTags','GetCachedTagToPokemonBindingForIndex','GetAllTags','SetPokemonTags','UpdateTagsForFilter'], 'svc');
        send({type:'h', msg:'hooked bag='+n1+' svc='+n2});
        return {ok:true};
    },
    get: function() { return {bag: bagInst, svc: svcInstHook}; },
    scanSvcChunk: function(startHi, sizeBytes) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, gnt = null;
        while ((m = fns.cGM(svcCls, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === 'get_NumberOfTags') gnt = m;
        }
        var hits = [];
        var startAddr = ptr(startHi);
        var endAddr = startAddr.add(sizeBytes);
        // Limit which ranges to scan based on overlap with [startAddr, endAddr]
        Process.enumerateRanges({protection:'rw-'}).forEach(function(r){
            if (hits.length > 10) return;
            var rEnd = r.base.add(r.size);
            if (r.base.compare(endAddr) >= 0 || rEnd.compare(startAddr) <= 0) return;
            var p = r.base.compare(startAddr) > 0 ? r.base : startAddr;
            var e = rEnd.compare(endAddr) < 0 ? rEnd : endAddr;
            while (p.compare(e) < 0 && hits.length < 10) {
                try {
                    if (p.readPointer().equals(svcCls)) {
                        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
                        var ret = fns.rI(gnt, p, ptr(0), exc);
                        if (exc.readPointer().isNull()) {
                            var n = ret.add(0x10).readS32();
                            if (n >= 12 && n < 50) hits.push({addr: p.toString(), tags: n});
                        }
                    }
                } catch(e2) {}
                p = p.add(8);
            }
        });
        return {hits: hits};
    },
    findProtos: function(bagAddr, uids) {
        var ga = fns.cMN(bagCls, Memory.allocUtf8String('get_AllPokemon'), 0);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = fns.rI(ga, ptr(bagAddr), ptr(0), exc);
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        var count = list.add(0x18).readS32();
        var wanted = {}; for (var i=0;i<uids.length;i++) wanted[uids[i]] = true;
        var found = {}; var node = head; var iters = 0;
        while (node && !node.isNull() && iters < count + 200) {
            try {
                var key = node.add(0x28).readU64().toString();
                if (wanted[key]) found[key] = node.add(0x30).readPointer().toString();
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }
        return {found: found};
    }
};
"""
sc = sess.create_script(combined_js)
def on(m, data):
    p = m.get('payload',{})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
sc.on('message', on); sc.load(); sc.exports_sync.setup()

print("Waiting up to 90s for bag+svc hooks (interact with PoGo storage/tag screen)...")
BAG = SVC = None
for i in range(90):
    time.sleep(1)
    g = sc.exports_sync.get()
    if g.get('bag') and not BAG: BAG = g['bag']
    if g.get('svc') and not SVC: SVC = g['svc']
    if BAG and SVC: break
if not SVC:
    print("SVC hook didn't fire, chunked heap-scanning IL2CPP range...")
    # Scan 4 GiB starting from typical IL2CPP base in 256 MiB chunks
    base = 0x7000000000
    chunk = 0x10000000  # 256 MiB
    for offset in range(0, 0x1000000000, chunk):
        if SVC: break
        try:
            sr = sc.exports_sync.scan_svc_chunk(base + offset, chunk)
            if sr['hits']:
                print(f"  base=0x{base+offset:x} hits: {sr['hits']}")
                SVC = sr['hits'][0]['addr']
                print(f"Picked SVC = {SVC}")
                break
        except Exception as e:
            print(f"  scan chunk fail at 0x{base+offset:x}: {e}")
            break
if not BAG:
    BAG = '0x772ee1ea00'
    print(f"bag hook didn't fire, using cached {BAG}")
if not SVC:
    print(f"FAILED: svc={SVC}"); sess.detach(); exit(1)
print(f"bag={BAG} svc={SVC}")

r = sc.exports_sync.find_protos(BAG, [u[1] for u in uid_strs])
found = r['found']
print(f"\nFound protos: {len(found)}/{len(uid_strs)}")

# Load bulk_tag.js in same session
bulk = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
bulk.load(); bulk.exports_sync.init_status()

ftid = bulk.exports_sync.find_tag_id_by_name(SVC, 'JUMBO')
print(f"JUMBO: idx={ftid.get('idx')} tagProto={ftid.get('tagProtoAddr')}")
if not ftid.get('ok'):
    print("FAIL: JUMBO not found"); sess.detach(); exit(1)

# Warm-up: try untag first one (may NPE; ignore)
first_uh, first_us = uid_strs[0]
if first_us in found:
    try: bulk.exports_sync.bulk_untag_one(SVC, found[first_us], ftid['tagProtoAddr'])
    except Exception as e: print(f"  warm-up exc: {e}")
    time.sleep(0.6)

removed = 0
for uh, us in uid_strs:
    if us not in found:
        print(f"  {uh}: NO PROTO"); continue
    try:
        res = bulk.exports_sync.bulk_untag_one(SVC, found[us], ftid['tagProtoAddr'])
        ok = res.get('ok'); err = res.get('err','')
    except Exception as e:
        ok = False; err = str(e)
    print(f"  {uh}: ok={ok} {err}")
    if ok: removed += 1
    time.sleep(0.4)

print(f"\nUntagged: {removed}/{len(uid_strs)}")
time.sleep(2)
chk = bulk.exports_sync.get_pokemon_for_tag(SVC, ftid['idx'])
print(f"Final JUMBO server count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")
sess.detach()
