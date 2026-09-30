"""Walk live bag via LinkedHashMap pattern, dump all protos, save full_inventory_v3.json."""
import frida, json, subprocess, time

_T0 = time.time()
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")

_tick("start")
adb_pid = int(subprocess.check_output(['adb','-s','100.98.158.56:5555','shell','pidof com.nianticlabs.pokemongo']).decode().strip())
print(f"PoGo PID: {adb_pid}")
_tick("adb pidof done")
mgr = frida.get_device_manager()
d = mgr.add_remote_device("127.0.0.1:27047")
sess = d.attach(adb_pid)
_tick("attached")

# Step 1: hook to capture bag instance
hook_js = """
var fns={}; var bagInst=null;
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
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    while ((m = fns.cGM(bagCls, iter)) && !m.isNull()) {
        try { var addr = m.readPointer(); if (addr.isNull()) continue;
            Interceptor.attach(addr, { onEnter: function(args) { if (!bagInst) { bagInst = args[0].toString(); send({type:'h', msg:'bag '+bagInst}); } } });
        } catch(e) {}
    }
}
rpc.exports = { setup: function() { init(); return {ok:true}; }, get: function() { return {bag: bagInst}; } };
"""
hs = sess.create_script(hook_js)
def on(m,data):
    p = m.get('payload',{})
    if isinstance(p, dict) and 'msg' in p: print(f"  {p['msg']}")
hs.on('message', on); hs.load(); _tick("hook script loaded")
hs.exports_sync.setup()
_tick("hook setup() returned")
print("Waiting for bag hook (interact with PoGo)...")
bag = None
_wait_start = time.time()
for i in range(90):
    time.sleep(1)
    g = hs.exports_sync.get()
    if g.get('bag'): bag = g['bag']; break
_tick(f"hook fired after {time.time()-_wait_start:.1f}s of wait")
if not bag:
    print("FAILED to capture bag instance"); sess.detach(); exit(1)
print(f"bag={bag}")
hs.unload()
_tick("hook unloaded")

# Step 2: walk bag and dump all protos
js = """
function readBytesHex(p, n) {
    var b = p.readByteArray(n);
    var u8 = new Uint8Array(b);
    var s = '';
    for (var i = 0; i < u8.length; i++) { var h = u8[i].toString(16); s += (h.length===1?'0':'') + h; }
    return s;
}
rpc.exports = {
    walkAll: function(bag) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {}; il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
        var dG=bind('il2cpp_domain_get','pointer',[]);
        var dGA=bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
        var aGI=bind('il2cpp_assembly_get_image','pointer',['pointer']);
        var iGN=bind('il2cpp_image_get_name','pointer',['pointer']);
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
        var lhm=values.add(0x10).readPointer();
        var list=lhm.add(0x18).readPointer();
        var head=list.add(0x10).readPointer();
        var count=list.add(0x18).readS32();
        return {count: count, head: head.toString(), listAddr: list.toString()};
    },
    dumpProtos: function(headStr, startIdx, maxN) {
        var head = ptr(headStr);
        var node = head;
        // Skip startIdx nodes
        for (var s = 0; s < startIdx; s++) {
            try {
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) return {done:true, results:{}};
                node = next;
            } catch(e) { return {done:true, results:{}}; }
        }
        var results = {};
        var n = 0;
        while (n < maxN && node && !node.isNull()) {
            try {
                var uidStr = node.add(0x28).readU64().toString();
                var proto = node.add(0x30).readPointer();
                if (proto.isNull()) break;
                var rec = {ptr: proto.toString()};
                rec.protoBytes = readBytesHex(proto, 0x200);
                try {
                    var dispPtr = proto.add(0xd8).readPointer();
                    if (!dispPtr.isNull()) {
                        rec.displayBytes = readBytesHex(dispPtr, 0x80);
                        try { var locPtr = dispPtr.add(0x58).readPointer(); if (!locPtr.isNull()) rec.locBytes = readBytesHex(locPtr, 0x40); } catch(e) {}
                        try { var megaPtr = dispPtr.add(0x50).readPointer(); if (!megaPtr.isNull()) rec.megaBytes = readBytesHex(megaPtr, 0x40); } catch(e) {}
                    }
                } catch(e) {}
                try {
                    var tagsPtr = proto.add(0x180).readPointer();
                    if (!tagsPtr.isNull()) {
                        var tc = tagsPtr.add(0x18).readS32();
                        var tagIds = [];
                        if (tc > 0 && tc < 50) {
                            var items = tagsPtr.add(0x10).readPointer();
                            for (var ti = 0; ti < tc; ti++) {
                                try {
                                    var tagAddr = items.add(0x20 + ti*8).readPointer();
                                    if (!tagAddr.isNull()) {
                                        var tidStr = tagAddr.add(0x10).readU64().toString();
                                        tagIds.push(tidStr);
                                    }
                                } catch(e) {}
                            }
                        }
                        rec.tagCount = tc;
                        rec.tagIds = tagIds;
                    } else { rec.tagCount = 0; rec.tagIds = []; }
                } catch(e) {}
                results[uidStr] = rec;
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) { n++; break; }
                node = next;
                n++;
            } catch(e) { break; }
        }
        return {done:false, results:results, lastNode:node.toString(), processed:n};
    }
};
"""
sc = sess.create_script(js); sc.load()
_tick("walk script loaded")
info = sc.exports_sync.walk_all(bag)
_tick(f"walk_all RPC returned (count={info['count']})")
print(f"\nBag has {info['count']} entries (head={info['head']})")

# Dump in batches of 200
all_results = {}
batch_size = 200
total = info['count']
_batch_start = time.time()
_batch_n = 0
for start in range(0, total + batch_size, batch_size):
    _b = time.time()
    r = sc.exports_sync.dump_protos(info['head'], start, batch_size)
    _batch_n += 1
    print(f"  [batch {_batch_n} RPC={time.time()-_b:.2f}s] start={start}")
    if r.get('done'): break
    all_results.update(r['results'])
    print(f"  dumped {len(all_results)}/{total}")
    if r.get('processed', 0) == 0: break
_tick(f"all dump_protos done ({_batch_n} batches, mean {(time.time()-_batch_start)/max(1,_batch_n):.2f}s/batch)")

print(f"\nTotal pokemon read: {len(all_results)}")
_w = time.time()
with open("full_inventory_v3.json","w") as f:
    json.dump({"count": len(all_results), "results": all_results}, f)
_tick(f"json.dump took {time.time()-_w:.2f}s")
print("Saved full_inventory_v3.json")
sess.detach()
_tick("detached")

import eggs_walker
egg_stats = eggs_walker.upsert_eggs('full_inventory_v3.json')
print(f"Eggs: {egg_stats}")
_tick("done")
