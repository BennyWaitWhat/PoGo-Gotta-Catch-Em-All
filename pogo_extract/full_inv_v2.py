"""Walk the LinkedList<KVP<UInt64, PokemonProto>> from PokemonBagImpl to get ALL pokemon.

LinkedHashMap @ valuesAddr+0x10 (or via direct dictionary)
LinkedHashMap.list @ +0x18 -> LinkedList<KVP>
LinkedList.head @ +0x10 -> first node
LinkedListNode<T>: list@+0x10, next@+0x18, prev@+0x20, item (KVP struct)@+0x28
KVP<UInt64, PokemonProto>: key(UInt64)@+0x28, value(ptr)@+0x30
"""
import frida, json, time

mgr = frida.get_device_manager()
d = mgr.add_remote_device('127.0.0.1:27047')
sess = d.attach(d.enumerate_processes()[0].pid)

# Use full_inventory.js for getAllPokemon, then walk the list manually
js = """
var fns = {};
var pokemonBagClass = null;
var getAllMethod = null;
var bagInstance = null;

function init() {
    var il2cpp = Process.findModuleByName('libil2cpp.so');
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
    function bind(n,r,a){ return new NativeFunction(exp[n],r,a); }
    fns.dG = bind('il2cpp_domain_get','pointer',[]);
    fns.dGA = bind('il2cpp_domain_get_assemblies','pointer',['pointer','pointer']);
    fns.aGI = bind('il2cpp_assembly_get_image','pointer',['pointer']);
    fns.iGN = bind('il2cpp_image_get_name','pointer',['pointer']);
    fns.cFN = bind('il2cpp_class_from_name','pointer',['pointer','pointer','pointer']);
    fns.cMN = bind('il2cpp_class_get_method_from_name','pointer',['pointer','pointer','int']);
    fns.cGM = bind('il2cpp_class_get_methods','pointer',['pointer','pointer']);
    fns.mGN = bind('il2cpp_method_get_name','pointer',['pointer']);
    fns.tA = bind('il2cpp_thread_attach','pointer',['pointer']);
    fns.rI = bind('il2cpp_runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
    fns.tA(fns.dG());
    var sp = Memory.alloc(4);
    var asms = fns.dGA(fns.dG(), sp);
    var na = sp.readS32();
    var gi = null;
    for (var a=0;a<na;a++){ var i=fns.aGI(asms.add(a*Process.pointerSize).readPointer()); if (fns.iGN(i).readCString()==='holo-game.dll'){ gi=i; break; } }
    pokemonBagClass = fns.cFN(gi, Memory.allocUtf8String('Niantic.Holoholo.Internal'), Memory.allocUtf8String('PokemonBagImpl'));
    getAllMethod = fns.cMN(pokemonBagClass, Memory.allocUtf8String('get_AllPokemon'), 0);
}

function readBytesHex(p, n) {
    try {
        var bs = p.readByteArray(n);
        var u8 = new Uint8Array(bs);
        var s = '';
        for (var i = 0; i < u8.length; i++) s += ('0' + u8[i].toString(16)).slice(-2);
        return s;
    } catch(e) { return null; }
}

rpc.exports = {
    setup: function() { init(); return {ok:true}; },

    setBag: function(b) { bagInstance = b; return {ok:true}; },

    /* Hook bag methods to capture instance */
    hook: function() {
        if (!getAllMethod) init();
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, n=0;
        while ((m = fns.cGM(pokemonBagClass, iter)) && !m.isNull()) {
            try {
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (!bagInstance) {
                            bagInstance = args[0].toString();
                            send({type:'status', msg:'bag captured: ' + bagInstance});
                        }
                    }
                });
                n++;
            } catch(e) {}
        }
        return {ok:true, hooked:n};
    },

    getBag: function() { return {bag: bagInstance}; },

    /* Walk the LinkedList and dump all pokemon. */
    dumpFullInventory: function() {
        if (!bagInstance) return {ok:false, err:'no bag'};
        if (!getAllMethod) init();
        var inst = ptr(bagInstance);

        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var values = fns.rI(getAllMethod, inst, ptr(0), exc);
        if (!exc.readPointer().isNull()) return {ok:false, err:'exc'};
        if (values.isNull()) return {ok:false, err:'null values'};

        // ValueCollection +0x10 -> LinkedHashMap
        var lhm = values.add(0x10).readPointer();
        if (lhm.isNull()) return {ok:false, err:'no lhm'};

        // LinkedHashMap +0x18 -> LinkedList
        var list = lhm.add(0x18).readPointer();
        if (list.isNull()) return {ok:false, err:'no list'};

        var count = list.add(0x18).readS32();
        var head = list.add(0x10).readPointer();
        if (head.isNull()) return {ok:false, err:'no head', count: count};

        // Walk forward via next pointer until we cycle back to head
        var results = [];
        var node = head;
        var iters = 0;
        var maxIters = count + 100;
        while (node && !node.isNull() && iters < maxIters) {
            try {
                // KVP at +0x28: key(UInt64)@+0x28, value(ptr)@+0x30
                var key = node.add(0x28).readU64().toString();
                var protoPtr = node.add(0x30).readPointer();
                results.push({key: key, ptr: protoPtr.toString()});

                // next at +0x18
                var next = node.add(0x18).readPointer();
                if (next.isNull() || next.equals(head)) break;
                node = next;
            } catch(e) { break; }
            iters++;
        }
        return {ok:true, count: count, walked: results.length, items: results};
    },

    /* Read proto data for a batch of pointers. */
    readBatch: function(ptrs) {
        var out = {};
        for (var i = 0; i < ptrs.length; i++) {
            try {
                var p = ptr(ptrs[i]);
                var lo = p.add(32).readS32();
                var hi = p.add(36).readS32();
                var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
                var rec = {uid: uidNum.toString(), pid: p.add(40).readS32(), ptr: ptrs[i]};
                rec.protoBytes = readBytesHex(p, 0x200);
                try {
                    var dispPtr = p.add(0xd8).readPointer();
                    if (!dispPtr.isNull()) {
                        rec.displayBytes = readBytesHex(dispPtr, 0x80);
                        try {
                            var locPtr = dispPtr.add(0x58).readPointer();
                            if (!locPtr.isNull()) rec.locBytes = readBytesHex(locPtr, 0x40);
                        } catch(e) {}
                        try {
                            var megaPtr = dispPtr.add(0x50).readPointer();
                            if (!megaPtr.isNull()) rec.megaBytes = readBytesHex(megaPtr, 0x40);
                        } catch(e) {}
                    }
                } catch(e) {}
                try {
                    var tagsPtr = p.add(0x180).readPointer();
                    if (!tagsPtr.isNull()) {
                        var tc = tagsPtr.add(0x18).readS32();
                        if (tc > 0 && tc < 100) {
                            var items = tagsPtr.add(0x10).readPointer();
                            if (!items.isNull()) {
                                var ids = [];
                                for (var j = 0; j < tc; j++) {
                                    try { ids.push(items.add(0x20 + j*8).readU64().toString()); } catch(e) {}
                                }
                                rec.tagIds = ids;
                                rec.tagCount = tc;
                            }
                        }
                    }
                } catch(e) {}
                out[uidNum.toString()] = rec;
            } catch(e) {}
        }
        return {ok:true, count: Object.keys(out).length, results: out};
    }
};
"""

script = sess.create_script(js)
def on(m, data):
    p = m.get('payload',{})
    if isinstance(p,dict) and 'msg' in p:
        print(f"  [hook] {p['msg']}")
script.on('message', on)
script.load()

print("setup...")
print(script.exports_sync.setup())

print("Installing hooks...")
print(script.exports_sync.hook())

print(">>> Interact with PoGo storage (open inventory, scroll a tiny bit) - waiting up to 60s for hook...")
bag = None
for i in range(60):
    time.sleep(1)
    b = script.exports_sync.get_bag()
    if b.get('bag'):
        bag = b['bag']; break

if not bag:
    # fallback: try the cached one from earlier run
    bag = '0x72b9ed0b80'
    print(f"Hook didn't fire, trying cached bag {bag}")
    script.exports_sync.set_bag(bag)

print(f"\nDumping full inventory via LinkedList walk...")
r = script.exports_sync.dump_full_inventory()
if not r.get('ok'):
    print(f"FAILED: {r}")
    sess.detach()
    exit(1)

print(f"  reported count: {r['count']}, walked: {r['walked']}")

# Check for shadows in the walked list
items = r['items']
ptrs = [i['ptr'] for i in items]
print(f"\nReading proto data in batches of 500...")
all_results = {}
for i in range(0, len(ptrs), 500):
    chunk = ptrs[i:i+500]
    rb = script.exports_sync.read_batch(chunk)
    if rb.get('ok'):
        all_results.update(rb['results'])
        print(f"  batch {i//500+1}: total {len(all_results)}")

# Count shadows
import struct
shadow_count = 0
shadow_uids = []
for uid, rec in all_results.items():
    db = rec.get('displayBytes')
    if not db: continue
    bs = bytes.fromhex(db)
    if len(bs) >= 0x28:
        align = struct.unpack_from('<i', bs, 0x24)[0]
        if align == 1:
            shadow_count += 1
            shadow_uids.append(uid)
print(f"\n=== SHADOWS in full inventory: {shadow_count} ===")

# Save full inventory
with open('full_inventory_v2.json','w') as f:
    json.dump({"count": r['count'], "walked": r['walked'], "results": all_results}, f)
print(f"Saved full_inventory_v2.json")

sess.detach()
