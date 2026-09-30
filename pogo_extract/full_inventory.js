/* full_inventory.js — get the COMPLETE pokemon inventory via PokemonBagImpl.get_AllPokemon
 * This bypasses the heap-cache problem: the bag holds references to ALL pokemon, even
 * ones whose proto objects haven't been viewed/scrolled in the storage UI.
 */
var state = {ready:false, err:null};
var fns = {};
var bagInstance = null;
var pokemonBagClass = null;
var getAllMethod = null;
var getCountMethod = null;
var pokemonProtoClass = null;
var protoImage = null;

function init() {
    if (state.ready) return true;
    if (state.err) return false;

    var il2cpp = Process.findModuleByName("libil2cpp.so");
    if (!il2cpp) { state.err = "no il2cpp"; return false; }
    var exp = {};
    il2cpp.enumerateExports().forEach(function(e){
        if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
    });
    function bind(n, r, a) { return exp[n] ? new NativeFunction(exp[n], r, a) : null; }

    fns.dG = bind("il2cpp_domain_get",'pointer',[]);
    fns.dGA = bind("il2cpp_domain_get_assemblies",'pointer',['pointer','pointer']);
    fns.aGI = bind("il2cpp_assembly_get_image",'pointer',['pointer']);
    fns.iGN = bind("il2cpp_image_get_name",'pointer',['pointer']);
    fns.cFN = bind("il2cpp_class_from_name",'pointer',['pointer','pointer','pointer']);
    fns.cMN = bind("il2cpp_class_get_method_from_name",'pointer',['pointer','pointer','int']);
    fns.cGM = bind("il2cpp_class_get_methods",'pointer',['pointer','pointer']);
    fns.mGN = bind("il2cpp_method_get_name",'pointer',['pointer']);
    fns.tA = bind("il2cpp_thread_attach",'pointer',['pointer']);
    fns.rI = bind("il2cpp_runtime_invoke",'pointer',['pointer','pointer','pointer','pointer']);

    var dom = fns.dG();
    fns.tA(dom);
    var sp = Memory.alloc(4);
    var asms = fns.dGA(dom, sp);
    var na = sp.readS32();
    var gameImage = null;
    for (var a = 0; a < na; a++) {
        var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
        var nm = fns.iGN(img).readCString();
        if (nm === "holo-game.dll") gameImage = img;
        if (nm === "holo-protos.dll") protoImage = img;
    }
    if (!gameImage || !protoImage) { state.err = "missing image"; return false; }

    pokemonBagClass = fns.cFN(gameImage,
        Memory.allocUtf8String("Niantic.Holoholo.Internal"),
        Memory.allocUtf8String("PokemonBagImpl"));
    if (!pokemonBagClass || pokemonBagClass.isNull()) { state.err = "no PokemonBagImpl"; return false; }

    pokemonProtoClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("PokemonProto"));

    getAllMethod = fns.cMN(pokemonBagClass, Memory.allocUtf8String("get_AllPokemon"), 0);
    getCountMethod = fns.cMN(pokemonBagClass, Memory.allocUtf8String("get_Count"), 0);

    state.ready = true;
    return true;
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
    initStatus: function() {
        init();
        return {ready:state.ready, err:state.err,
                bag: pokemonBagClass ? pokemonBagClass.toString() : null,
                getAll: getAllMethod ? getAllMethod.toString() : null};
    },

    /* Hook the bag methods so when the game calls them, we capture the instance.
       Game calls get_Count or get_AllPokemon during virtually any storage interaction. */
    hookForBagInstance: function() {
        if (!init()) return {ok:false, err:state.err};
        var hooked = [];

        function hookMethod(method, name) {
            if (!method || method.isNull()) return false;
            try {
                var addr = method.readPointer();
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (!bagInstance) {
                            bagInstance = args[0].toString();
                            send({type:"status", msg:"captured bag instance @ " + bagInstance + " via " + name});
                        }
                    }
                });
                hooked.push(name);
                return true;
            } catch(e) { return false; }
        }

        hookMethod(getCountMethod, "get_Count");
        hookMethod(getAllMethod, "get_AllPokemon");

        // Hook ALL methods to maximize chance of catching
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = fns.cGM(pokemonBagClass, iter)) && !m.isNull()) {
            try {
                var name = fns.mGN(m).readCString();
                if (hooked.indexOf(name) >= 0) continue;
                var addr = m.readPointer();
                if (addr.isNull()) continue;
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (!bagInstance) {
                            bagInstance = args[0].toString();
                            send({type:"status", msg:"captured bag @ " + bagInstance});
                        }
                    }
                });
                hooked.push(name);
            } catch(e) {}
        }
        return {ok:true, hookedCount: hooked.length};
    },

    getBagInstance: function() {
        return {ok:true, bag: bagInstance};
    },

    /* Heap scan for PokemonBagImpl. */
    scanForBagInstance: function() {
        if (!init()) return {ok:false, err:state.err};
        var hits = [];
        var ranges = Process.enumerateRanges('rw-');
        var klassStr = pokemonBagClass.toString().replace("0x","");
        var pattern = klassStr.match(/.{2}/g).reverse().join(' ');
        for (var r = 0; r < ranges.length; r++) {
            if (hits.length >= 5) break;
            if (ranges[r].size > 256*1024*1024) continue;
            try {
                Memory.scanSync(ranges[r].base, ranges[r].size, pattern).forEach(function(m){
                    if (hits.length < 5) hits.push(m.address.toString());
                });
            } catch(e) {}
        }
        return {ok:true, hits: hits};
    },

    /* Try to set bag instance from a pointer string (for testing) */
    setBagInstance: function(ptrStr) {
        bagInstance = ptrStr;
        return {ok:true};
    },

    /* Invoke get_AllPokemon on captured/given instance, return list info. */
    getAllPokemon: function(instanceStr) {
        if (!init()) return {ok:false, err:state.err};
        var inst = instanceStr ? ptr(instanceStr) : (bagInstance ? ptr(bagInstance) : null);
        if (!inst) return {ok:false, err:"no instance"};

        // Get count first
        var exc1 = Memory.alloc(Process.pointerSize); exc1.writePointer(ptr(0));
        var countRet = fns.rI(getCountMethod, inst, ptr(0), exc1);
        if (!exc1.readPointer().isNull()) return {ok:false, err:"get_Count threw"};
        // Boxed int return: value at +0x10
        var count = countRet.add(0x10).readS32();

        // Invoke get_AllPokemon
        var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
        var ret = fns.rI(getAllMethod, inst, ptr(0), exc2);
        if (!exc2.readPointer().isNull()) return {ok:false, err:"get_AllPokemon threw"};
        if (ret.isNull()) return {ok:false, err:"null return"};

        // Probe layout: try List<T> with items@+0x10 size@+0x18
        var listSize = -1, itemsPtr = null, layoutTried = [];
        var trials = [
            {sizeOff: 0x18, itemsOff: 0x10},
            {sizeOff: 0x10, itemsOff: 0x18},
            {sizeOff: 0x20, itemsOff: 0x18},
        ];
        for (var t = 0; t < trials.length; t++) {
            try {
                var sz = ret.add(trials[t].sizeOff).readS32();
                var arr = ret.add(trials[t].itemsOff).readPointer();
                layoutTried.push({tr: trials[t], sz: sz, arr: arr.toString()});
                if (sz > 0 && sz < 100000 && !arr.isNull()) {
                    listSize = sz;
                    itemsPtr = arr;
                    break;
                }
            } catch(e) {}
        }

        return {
            ok: true,
            count: count,
            retAddr: ret.toString(),
            listSize: listSize,
            itemsPtr: itemsPtr ? itemsPtr.toString() : null,
            layoutTried: layoutTried
        };
    },

    /* Once we know the list layout, dump all pokemon via the items array.
       Each item is a pointer (or struct?) to a PokemonProto-like wrapper.
       Returns an array of ptr addresses. */
    dumpAllProtoPtrs: function(instanceStr, sizeOff, itemsOff, dataOff) {
        if (!init()) return {ok:false, err:state.err};
        var inst = instanceStr ? ptr(instanceStr) : (bagInstance ? ptr(bagInstance) : null);
        if (!inst) return {ok:false, err:"no instance"};

        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(getAllMethod, inst, ptr(0), exc);
        if (!exc.readPointer().isNull()) return {ok:false, err:"threw"};
        if (ret.isNull()) return {ok:false, err:"null"};

        var size = ret.add(sizeOff).readS32();
        var arr = ret.add(itemsOff).readPointer();
        if (size <= 0 || arr.isNull()) return {ok:false, err:"empty"};

        var ptrs = [];
        for (var i = 0; i < size; i++) {
            try {
                var p = arr.add(dataOff + i*Process.pointerSize).readPointer();
                ptrs.push(p.toString());
            } catch(e) {}
        }
        return {ok:true, count:size, ptrs:ptrs};
    },

    /* For each proto pointer, read uid/pid + display proto bytes. Returns dict. */
    readProtoBatch: function(ptrStrArray) {
        if (!init()) return {ok:false, err:state.err};
        var results = {};
        for (var i = 0; i < ptrStrArray.length; i++) {
            try {
                var p = ptr(ptrStrArray[i]);
                var lo = p.add(32).readS32();
                var hi = p.add(36).readS32();
                var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
                var pid = p.add(40).readS32();
                var rec = {uid: uidNum.toString(), pid: pid, ptr: ptrStrArray[i]};
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
                        if (tc >= 0 && tc < 100) {
                            rec.tagCount = tc;
                            if (tc > 0) {
                                var items = tagsPtr.add(0x10).readPointer();
                                if (!items.isNull()) {
                                    var ids = [];
                                    for (var j = 0; j < tc; j++) {
                                        try { ids.push(items.add(0x20 + j*8).readU64().toString()); } catch(e) {}
                                    }
                                    rec.tagIds = ids;
                                }
                            }
                        }
                    }
                } catch(e) {}
                results[uidNum.toString()] = rec;
            } catch(e) {
                results['err_' + i] = {err: e.message, ptr: ptrStrArray[i]};
            }
        }
        return {ok:true, count: Object.keys(results).length, results: results};
    }
};
