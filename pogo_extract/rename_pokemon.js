/*
 * rename_pokemon.js  -- lazy init version
 *
 * Renames pokemon by calling Niantic.Holoholo.Internal.PokemonBagImpl::NicknamePokemon
 *
 * All il2cpp resolution is deferred until first rpc call so script.load()
 * doesn't time out when PoGo is still booting.
 */

var state = {ready: false, err: null};
var fns = {};
var pokemonProtoClass = null;
var bagClass = null;
var nickMethod = null;

function init() {
    if (state.ready) return true;
    if (state.err) return false;
    try {
        var il2cpp = Process.findModuleByName("libil2cpp.so");
        if (!il2cpp) { state.err = "libil2cpp.so not loaded yet"; return false; }

        var exp = {};
        il2cpp.enumerateExports().forEach(function(e) {
            if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
        });
        function bind(n, r, a) { return exp[n] ? new NativeFunction(exp[n], r, a) : null; }

        fns.dG  = bind("il2cpp_domain_get",'pointer',[]);
        fns.dGA = bind("il2cpp_domain_get_assemblies",'pointer',['pointer','pointer']);
        fns.aGI = bind("il2cpp_assembly_get_image",'pointer',['pointer']);
        fns.iGN = bind("il2cpp_image_get_name",'pointer',['pointer']);
        fns.cFN = bind("il2cpp_class_from_name",'pointer',['pointer','pointer','pointer']);
        fns.cGM = bind("il2cpp_class_get_methods",'pointer',['pointer','pointer']);
        fns.mGN = bind("il2cpp_method_get_name",'pointer',['pointer']);
        fns.mGPC = bind("il2cpp_method_get_param_count",'int',['pointer']);
        fns.tA  = bind("il2cpp_thread_attach",'pointer',['pointer']);
        fns.sN  = bind("il2cpp_string_new",'pointer',['pointer']);
        fns.rI  = bind("il2cpp_runtime_invoke",'pointer',['pointer','pointer','pointer','pointer']);

        var dom = fns.dG();
        fns.tA(dom);

        var sp = Memory.alloc(4);
        var asms = fns.dGA(dom, sp);
        var na = sp.readS32();

        var protoImage = null;
        var gameImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            var nm = fns.iGN(img).readCString();
            if (nm === "holo-protos.dll") protoImage = img;
            if (nm === "holo-game.dll") gameImage = img;
        }
        if (!protoImage || !gameImage) {
            state.err = "missing image: protos=" + protoImage + " game=" + gameImage;
            return false;
        }

        pokemonProtoClass = fns.cFN(protoImage,
            Memory.allocUtf8String("Holoholo.Rpc"),
            Memory.allocUtf8String("PokemonProto"));
        if (!pokemonProtoClass || pokemonProtoClass.isNull()) {
            state.err = "PokemonProto class not found";
            return false;
        }

        bagClass = fns.cFN(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Internal"),
            Memory.allocUtf8String("PokemonBagImpl"));
        if (!bagClass || bagClass.isNull()) {
            state.err = "PokemonBagImpl class not found";
            return false;
        }

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m;
        while ((m = fns.cGM(bagClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "NicknamePokemon" && fns.mGPC(m) === 2) {
                nickMethod = m; break;
            }
        }
        if (!nickMethod) { state.err = "NicknamePokemon method not found"; return false; }

        state.ready = true;
        send({type:"status", msg: "init OK: PokemonProto=" + pokemonProtoClass + " bag=" + bagClass + " method=" + nickMethod});
        return true;
    } catch (e) {
        state.err = "init exception: " + e.message;
        return false;
    }
}

function buildKlassPattern(klass) {
    var bytes = [];
    var t = klass;
    for (var b = 0; b < 8; b++) {
        var v = t.and(0xFF).toInt32();
        bytes.push((v < 16 ? '0' : '') + v.toString(16));
        t = t.shr(8);
    }
    return bytes.join(' ');
}

function heapScan(klass, label, maxMatches) {
    var pat = buildKlassPattern(klass);
    var ranges = [];
    Process.enumerateRanges('rw-').forEach(function(r) {
        if (r.size > 64*1024*1024) return;
        if (r.size < 4096) return;
        if (r.file) return;
        ranges.push(r);
    });
    var matches = [];
    for (var ri = 0; ri < ranges.length; ri++) {
        try {
            var rs = Memory.scanSync(ranges[ri].base, ranges[ri].size, pat);
            for (var k = 0; k < rs.length; k++) matches.push(rs[k].address);
        } catch(e) {}
        if (maxMatches && matches.length > maxMatches) break;
    }
    send({type:"status", msg: label + " scan: " + matches.length + " matches in " + ranges.length + " ranges"});
    return matches;
}

function findPokemonByUid(uidLow, uidHigh) {
    var matches = heapScan(pokemonProtoClass, "PokemonProto", 10000);
    for (var i = 0; i < matches.length; i++) {
        try {
            var addr = matches[i];
            var lo = addr.add(32).readS32();
            var hi = addr.add(36).readS32();
            if (lo === uidLow && hi === uidHigh) {
                var pokemonId = addr.add(40).readS32();
                if (pokemonId < 1 || pokemonId > 1100) continue;
                return addr;
            }
        } catch(e) {}
    }
    return null;
}

function findBagInstance() {
    var matches = heapScan(bagClass, "PokemonBagImpl", 100);
    if (matches.length === 0) return null;
    return matches[0];
}

rpc.exports = {
    initStatus: function() { init(); return {ready: state.ready, err: state.err}; },

    countPokemon: function() {
        if (!init()) return {ok: false, err: state.err};
        var matches = heapScan(pokemonProtoClass, "PokemonProto", 10000);
        return {ok: true, count: matches.length};
    },

    listBagInstances: function() {
        if (!init()) return {ok: false, err: state.err};
        return heapScan(bagClass, "PokemonBagImpl", 100).map(function(a) { return a.toString(); });
    },

    rename: function(uidLow, uidHigh, nickname) {
        if (!init()) return {ok: false, err: state.err};
        try {
            send({type:"status", msg: "Looking for pokemon uidLow=" + uidLow + " uidHigh=" + uidHigh});
            var protoPtr = findPokemonByUid(uidLow|0, uidHigh|0);
            if (!protoPtr) return {ok: false, err: "pokemon not found in heap"};
            send({type:"status", msg: "Found proto @ " + protoPtr +
                " (pokemonId=" + protoPtr.add(40).readS32() +
                " cp=" + protoPtr.add(44).readS32() + ")"});

            var bagPtr = findBagInstance();
            if (!bagPtr) return {ok: false, err: "PokemonBagImpl instance not found"};
            send({type:"status", msg: "Found bag @ " + bagPtr});

            var nickStrPtr = fns.sN(Memory.allocUtf8String(nickname));
            var args = Memory.alloc(2 * Process.pointerSize);
            args.writePointer(protoPtr);
            args.add(Process.pointerSize).writePointer(nickStrPtr);
            var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));

            send({type:"status", msg: "Invoking NicknamePokemon..."});
            var promise = fns.rI(nickMethod, bagPtr, args, exc);
            var excPtr = exc.readPointer();
            if (!excPtr.isNull()) {
                return {ok: false, err: "exception thrown", excPtr: excPtr.toString()};
            }
            return {ok: true, promise: promise.toString(), protoPtr: protoPtr.toString(), bagPtr: bagPtr.toString()};
        } catch (e) {
            return {ok: false, err: "JS exception: " + e.message + "\n" + e.stack};
        }
    }
};

send({type:"ready", msg: "rpc.exports loaded (lazy init)"});
