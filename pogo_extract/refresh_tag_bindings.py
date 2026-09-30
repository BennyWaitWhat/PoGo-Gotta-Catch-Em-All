"""Refresh DB tag membership from authoritative binding service.
Replaces stale fresh_tag_ids data with actual server-state bindings."""
import frida, json, subprocess, time, sqlite3

_T0 = time.time()
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")
_tick("start")

adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PoGo PID: {adb_pid}")
_tick("adb pidof done")
subprocess.run(['adb','forward','tcp:27047','tcp:27047'], capture_output=True)
_tick("adb forward done")

mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(adb_pid)
_tick("attached")

# Hook bag and service
hook_js = """
var fns={}; var bagCls=null, svcCls=null; var bagInst=null, svcInst=null;
function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG=bind('il2cpp_domain_get','pointer',[]);
    fns.dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN=bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.cGM=bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.mGN=bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.tA=bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4);
    var asms = fns.dGA(fns.dG(), sp); var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    bagCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
    svcCls = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
    function hookAll(cls, label) {
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = fns.cGM(cls, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
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
    p = m.get('payload',{})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on)
hs.load()
_tick("hook script loaded")
hs.exports_sync.setup()
_tick("hook setup() returned (Interceptor.attach for all PokemonBagImpl + TaggingRpcService methods)")
print("Waiting up to 60s for hooks (interact with PoGo)...")
bag = svc = None
_wait_start = time.time()
for i in range(60):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('bag') and not bag: bag = g['bag']
    if g.get('svc') and not svc: svc = g['svc']
    if bag and svc: break
_tick(f"hooks fired (or timeout) after {time.time()-_wait_start:.1f}s")
if not svc:
    svc = '0x72f822ac80'
    print(f"svc hook didn't fire, using cached {svc}")
if not bag:
    bag = '0x72f6b7f800'
    print(f"bag hook didn't fire, using cached {bag}")

# Now enumerate tags and their bindings, plus build proto-pointer -> uid map via bag walk
js2 = """
rpc.exports = {
    enumBindings: function(svcAddr, bagAddr) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG = bind('il2cpp_domain_get','pointer',[]);
        var dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
        var cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
        var cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
        var mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
        var cMN = bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
        var rI = bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
        var dom = dG();
        var sp = Memory.alloc(4); var asms = dGA(dom, sp); var na = sp.readS32();
        var gi = null;
        for (var a=0;a<na;a++){ var i=aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
        var svcCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
        var bagCls = cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
        var ga = cMN(bagCls, Memory.allocUtf8String('get_AllPokemon'), 0);

        // Build proto-pointer -> uid map via bag walk
        var bag = ptr(bagAddr);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = rI(ga, bag, ptr(0), exc);
        var lhm = values.add(0x10).readPointer();
        var list = lhm.add(0x18).readPointer();
        var head = list.add(0x10).readPointer();
        var lcount = list.add(0x18).readS32();
        var ptrToUid = {};
        var node = head; var iters = 0;
        while (node && !node.isNull() && iters < lcount + 100) {
            try {
                var key = node.add(0x28).readU64().toString();
                var proto = node.add(0x30).readPointer();
                ptrToUid[proto.toString()] = key;
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }

        // Enum tags
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, gnt=null, gctb=null;
        while ((m = cGM(svcCls, iter)) && !m.isNull()) {
            var nm = mGN(m).readCString();
            if (nm === 'get_NumberOfTags') gnt = m;
            if (nm === 'GetCachedTagToPokemonBindingForIndex') gctb = m;
        }
        var svc = ptr(svcAddr);
        var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
        var ret = rI(gnt, svc, ptr(0), exc2);
        var totalTags = ret.add(0x10).readS32();

        var bindings = {};
        for (var i = 0; i < totalTags; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var exc3 = Memory.alloc(Process.pointerSize); exc3.writePointer(ptr(0));
            var bp = rI(gctb, svc, args, exc3);
            if (bp.isNull()) continue;
            var tagProto = bp.add(0x10).readPointer();
            var name = '';
            try {
                var ns = tagProto.add(0x40).readPointer();
                if (!ns.isNull()) {
                    var len = ns.add(0x10).readS32();
                    if (len > 0 && len < 100) {
                        var chars = [];
                        for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(ns.add(0x14 + ci*2).readU16()));
                        name = chars.join('');
                    }
                }
            } catch(e) {}
            // List of pokemon proto pointers at +0x18
            var listPtr = bp.add(0x18).readPointer();
            var count = listPtr.add(0x18).readS32();
            var items = listPtr.add(0x10).readPointer();
            var uids = [];
            for (var j = 0; j < count; j++) {
                try {
                    var pp = items.add(0x20 + j*8).readPointer();
                    var uid = ptrToUid[pp.toString()];
                    if (uid) uids.push(uid);
                } catch(e) {}
            }
            bindings[name] = {idx:i, count:count, uids:uids};
        }
        return {ok:true, bindings: bindings, walked: Object.keys(ptrToUid).length};
    }
};
"""
hs.unload()
_tick("hook unloaded")
script = sess.create_script(js2)
script.load()
_tick("enum_bindings script loaded")
_rpc = time.time()
r = script.exports_sync.enum_bindings(svc, bag)
_tick(f"enum_bindings RPC took {time.time()-_rpc:.2f}s (walked {r['walked']} bag entries)")
print(f"\nWalked {r['walked']} bag entries")
for name, b in r['bindings'].items():
    print(f"  {name}: count={b['count']} resolved={len(b['uids'])}")

# Update DB
_db_start = time.time()
conn = sqlite3.connect('pokemon.db')
c = conn.cursor()
cols = {row[1] for row in c.execute('PRAGMA table_info(pokemon)').fetchall()}
if 'auth_tag_names' not in cols:
    c.execute("ALTER TABLE pokemon ADD COLUMN auth_tag_names TEXT")
c.execute("UPDATE pokemon SET auth_tag_names=NULL")
_tick(f"DB reset auth_tag_names ({time.time()-_db_start:.2f}s)")

# Build uid_hex -> tag names list
from collections import defaultdict
uid_to_tags = defaultdict(list)
for name, b in r['bindings'].items():
    for uid_str in b['uids']:
        uid_unsigned = int(uid_str)
        uid_hex = f"{uid_unsigned & 0xFFFFFFFFFFFFFFFF:016x}"
        uid_to_tags[uid_hex].append(name)

n = 0
_loop = time.time()
for uid_hex, tags in uid_to_tags.items():
    c.execute("UPDATE pokemon SET auth_tag_names=? WHERE uid_hex=?", (';'.join(tags), uid_hex))
    n += 1
_tick(f"per-uid UPDATE loop done ({n} rows in {time.time()-_loop:.2f}s = {(time.time()-_loop)*1000/max(1,n):.1f}ms/row)")
conn.commit()
_tick("conn.commit done")
print(f"\nUpdated auth_tag_names for {n} pokemon")
sess.detach()
_tick("done")
