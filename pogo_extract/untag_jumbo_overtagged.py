"""Untag 8 over-tagged JUMBOs (rank 3+ in both weight & height per group)."""
import frida, time, subprocess, sqlite3, sys
sys.stdout.reconfigure(line_buffering=True)
subprocess.run(['adb','-s','100.98.158.56:5555','forward','tcp:27047','tcp:27047'], capture_output=True)
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PoGo PID: {adb_pid}")
mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)

# Hook fresh bag+svc
hook_js = """
var fns={}; var bagInst=null, svcInst=null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG=bind('il2cpp_domain_get','pointer',[]); fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']); fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']); fns.cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']); fns.tA(fns.dG());
    var sp = Memory.alloc(4); var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    var bagCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
    var svcCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
    function hookAll(cls, label) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = fns.cGM(cls, iter)) && !m.isNull()) {
            try { var addr = m.readPointer(); if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (label === 'bag' && !bagInst) { bagInst = args[0].toString(); send({type:'h', msg:'bag '+bagInst}); }
                        if (label === 'svc' && !svcInst) { svcInst = args[0].toString(); send({type:'h', msg:'svc '+svcInst}); }
                    }
                });
            } catch(e) {}
        }
    }
    hookAll(bagCls, 'bag'); hookAll(svcCls, 'svc');
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {bag: bagInst, svc: svcInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m, data):
    p = m.get('payload', {})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on); hs.load(); hs.exports_sync.setup()
print("Waiting for bag+svc hooks (interact with PoGo)...")
BAG = SVC = None
for i in range(120):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('bag') and not BAG: BAG = g['bag']
    if g.get('svc') and not SVC: SVC = g['svc']
    if BAG and SVC: break
if not SVC:
    print("SVC hook didn't fire, heap-scanning...")
    scan_js = """
    rpc.exports = {
        scan: function() {
            var il2cpp = Process.findModuleByName('libil2cpp.so');
            var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
            function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
            var dG=bind('il2cpp_domain_get','pointer',[]);
            var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
            var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
            var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
            var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
            var cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
            var mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
            var rI=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
            var tA=bind('il2cpp_thread_attach','pointer',['pointer']); tA(dG());
            var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32();
            var gi=null;
            for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){gi=i;break;} }
            var svcCls=cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
            var iter=Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
            var m, gnt=null;
            while ((m = cGM(svcCls, iter)) && !m.isNull()) {
                if (mGN(m).readCString() === 'get_NumberOfTags') gnt = m;
            }
            var hits = [];
            Process.enumerateRanges({protection:'rw-'}).forEach(function(r){
                if (r.size > 0x10000000 || hits.length > 10) return;
                var p = r.base; var end = r.base.add(r.size);
                while (p.compare(end) < 0) {
                    try {
                        if (p.readPointer().equals(svcCls)) {
                            var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
                            var ret = rI(gnt, p, ptr(0), exc);
                            if (exc.readPointer().isNull()) {
                                var n = ret.add(0x10).readS32();
                                if (n >= 12 && n < 50) { hits.push({addr: p.toString(), tags: n}); if (hits.length > 5) break; }
                            }
                        }
                    } catch(e) {}
                    p = p.add(8);
                }
            });
            return {hits: hits};
        }
    };
    """
    scan = sess.create_script(scan_js); scan.load()
    sr = scan.exports_sync.scan()
    print(f"Heap hits: {sr['hits']}")
    if sr['hits']:
        SVC = sr['hits'][0]['addr']
        print(f"Using SVC = {SVC} (tags={sr['hits'][0]['tags']})")
    scan.unload()
if not BAG or not SVC:
    print(f"FAILED: bag={BAG} svc={SVC}"); sess.detach(); exit(1)
print(f"bag={BAG} svc={SVC}")
hs.unload()

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
print(f"Target JUMBO count: {len(target)}  Server: {len(srv)}  Removing: {len(to_remove)}")

def to_uid_str(uid):
    u = int(uid); return str(u if u >= 0 else u + 2**64)
uid_strs = []
for uh in to_remove:
    r = c.execute("SELECT uid FROM pokemon WHERE uid_hex=?", (uh,)).fetchone()
    if r: uid_strs.append((uh, to_uid_str(r[0])))

js_walk = """
rpc.exports = {
    findProtos: function(bag, uids) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG=bind('il2cpp_domain_get','pointer',[]); var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']); var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cMN=bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
        var rI=bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var sp=Memory.alloc(4); var asms=dGA(dG(),sp); var na=sp.readS32();
        var gi=null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){gi=i;break;} }
        var cls=cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga=cMN(cls, Memory.allocUtf8String('get_AllPokemon'),0);
        var exc=Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values=rI(ga, ptr(bag), ptr(0), exc);
        var lhm=values.add(0x10).readPointer(); var list=lhm.add(0x18).readPointer();
        var head=list.add(0x10).readPointer(); var count=list.add(0x18).readS32();
        var wanted={}; for (var i=0;i<uids.length;i++) wanted[uids[i]]=true;
        var found={}; var node=head; var iters=0;
        while (node && !node.isNull() && iters < count + 200) {
            try {
                var key=node.add(0x28).readU64().toString();
                if (wanted[key]) found[key] = node.add(0x30).readPointer().toString();
                var next=node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node=next;
            } catch(e) { break; }
            iters++;
        }
        return {found: found};
    }
};
"""
walker = sess.create_script(js_walk); walker.load()
r = walker.exports_sync.find_protos(BAG, [u[1] for u in uid_strs])
found = r['found']
print(f"Found protos: {len(found)}/{len(uid_strs)}")

bulk = sess.create_script(open('bulk_tag.js','r',encoding='utf-8').read())
bulk.load(); bulk.exports_sync.init_status()
ftid = bulk.exports_sync.find_tag_id_by_name(SVC, 'JUMBO')
print(f"JUMBO tag info: idx={ftid.get('idx')} tagProto={ftid.get('tagProtoAddr')}")
if not ftid.get('ok'):
    print("FAIL: JUMBO tag not found"); sess.detach(); exit(1)

# Warm-up untag the first one twice (first call may NPE)
print("Warm-up call...")
first_uh, first_us = uid_strs[0]
if first_us in found:
    try: bulk.exports_sync.bulk_untag_one(SVC, found[first_us], ftid['tagProtoAddr'])
    except: pass
    time.sleep(0.5)

removed = 0
for uh, us in uid_strs:
    if us not in found:
        print(f"  {uh}: NO PROTO"); continue
    proto = found[us]
    res = bulk.exports_sync.bulk_untag_one(SVC, proto, ftid['tagProtoAddr'])
    ok = res.get('ok')
    print(f"  {uh}: ok={ok} {res.get('err','')}")
    if ok: removed += 1
    time.sleep(0.4)

print(f"\nUntagged: {removed}/{len(uid_strs)}")
time.sleep(2)
chk = bulk.exports_sync.get_pokemon_for_tag(SVC, ftid['idx'])
print(f"Final JUMBO server count: {chk.get('dump',{}).get('+0x18_listish',{}).get('count','?')}")
sess.detach()
