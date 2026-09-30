/*
 * fresh_poll.js — single-shot bulk extraction of every PokemonProto in heap.
 *
 * Reads, per pokemon:
 *   - uid (low/high i32 at +32/+36) -> full u64
 *   - pokemonId (i32 at +40)
 *   - cp (i32 at +0x44 - approx, will probe)
 *   - displayProto bytes (0x80 bytes from proto+0xd8 deref)
 *   - locationCard sub-message bytes (0x40 bytes from displayProto+0x58 deref)
 *   - megaEvolutionLevel sub-message bytes (0x20 bytes from displayProto+0x50 deref)
 *   - pokemonTagIds_ tag ids (RepeatedField at +0x180)
 *   - breadMoves_ count (RepeatedField at +0x1c8)
 *   - favorite_ bool (+0xb0)
 *   - is_lucky / is_purified / etc as discovered
 *
 * Also performs a one-time probe of LocationCard class layout.
 */

var state = {ready:false, err:null};
var fns = {};
var pokemonProtoClass = null;
var protoImage = null;

function init() {
    if (state.ready) return true;
    if (state.err) return false;

    var il2cpp = Process.findModuleByName("libil2cpp.so");
    if (!il2cpp) { state.err = "libil2cpp.so not loaded"; return false; }

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
    fns.cGF = bind("il2cpp_class_get_fields",'pointer',['pointer','pointer']);
    fns.fGN = bind("il2cpp_field_get_name",'pointer',['pointer']);
    fns.fGT = bind("il2cpp_field_get_type",'pointer',['pointer']);
    fns.fGO = bind("il2cpp_field_get_offset",'uint32',['pointer']);
    fns.tGN = bind("il2cpp_type_get_name",'pointer',['pointer']);
    fns.tA  = bind("il2cpp_thread_attach",'pointer',['pointer']);
    fns.cN  = bind("il2cpp_class_get_name",'pointer',['pointer']);
    fns.cGNs = bind("il2cpp_class_get_namespace",'pointer',['pointer']);

    var dom = fns.dG();
    fns.tA(dom);

    var sp = Memory.alloc(4);
    var asms = fns.dGA(dom, sp);
    var na = sp.readS32();
    for (var a = 0; a < na; a++) {
        var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
        if (fns.iGN(img).readCString() === "holo-protos.dll") { protoImage = img; break; }
    }
    if (!protoImage) { state.err = "no holo-protos"; return false; }

    pokemonProtoClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("PokemonProto"));
    if (!pokemonProtoClass || pokemonProtoClass.isNull()) {
        state.err = "PokemonProto class not found"; return false;
    }
    state.ready = true;
    return true;
}

// Heap scan via klass byte pattern in mapped pages
function heapScan(klass, label, max) {
    var hits = [];
    var ranges = Process.enumerateRanges('rw-');
    var klassStr = klass.toString();
    for (var r = 0; r < ranges.length; r++) {
        if (hits.length >= max) break;
        var range = ranges[r];
        if (range.size > 256*1024*1024) continue;  // skip huge pages
        try {
            Memory.scanSync(range.base, range.size, klassStr.replace("0x","").match(/.{2}/g).reverse().join(' ')).forEach(function(m) {
                if (hits.length < max) hits.push(m.address);
            });
        } catch(e) {}
    }
    return hits;
}

function buildProtoIndex() {
    var matches = heapScan(pokemonProtoClass, "PokemonProto", 30000);
    var idx = {};
    for (var i = 0; i < matches.length; i++) {
        try {
            var addr = matches[i];
            var pid = addr.add(40).readS32();
            if (pid < 1 || pid > 1100) continue;
            var lo = addr.add(32).readS32();
            var hi = addr.add(36).readS32();
            var key = lo + "," + hi;
            // Dedup - prefer first
            if (!idx[key]) idx[key] = addr;
        } catch(e) {}
    }
    return idx;
}

function readBytesHex(p, n) {
    try {
        var bs = p.readByteArray(n);
        var u8 = new Uint8Array(bs);
        var s = '';
        for (var i = 0; i < u8.length; i++) {
            s += ('0' + u8[i].toString(16)).slice(-2);
        }
        return s;
    } catch(e) { return null; }
}

rpc.exports = {
    initStatus: function() {
        var ok = init();
        return {ready: state.ready, err: state.err};
    },

    /* Probe LocationCard class layout to find the type field. */
    probeLocationCardClass: function() {
        if (!init()) return {ok:false, err:state.err};
        // Find PokemonDisplayProto class
        var displayClass = fns.cFN(protoImage,
            Memory.allocUtf8String("Holoholo.Rpc"),
            Memory.allocUtf8String("PokemonDisplayProto"));
        if (!displayClass || displayClass.isNull()) return {ok:false, err:"PokemonDisplayProto class not found"};

        // Iterate fields, find LocationCard
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var f, locationCardType = null;
        while ((f = fns.cGF(displayClass, iter)) && !f.isNull()) {
            try {
                var fieldName = fns.fGN(f).readCString();
                var fieldType = fns.tGN(fns.fGT(f)).readCString();
                var fieldOffset = fns.fGO(f);
                if (fieldName.toLowerCase().indexOf("locationcard") >= 0
                    || fieldOffset === 0x58) {
                    locationCardType = {name: fieldName, type: fieldType, offset: '0x'+fieldOffset.toString(16)};
                    break;
                }
            } catch(e) {}
        }
        if (!locationCardType) return {ok:false, err:"LocationCard field not found"};

        // Resolve the LocationCard class itself
        var lcClassName = locationCardType.type;
        // Type names look like "Holoholo.Rpc.PokemonDisplayProto/LocationCard" - grab last part
        var simpleName = lcClassName.split('/').pop().split('.').pop();
        var ns = lcClassName.split('.').slice(0, -1).join('.').split('/')[0];

        var lcClass = fns.cFN(protoImage,
            Memory.allocUtf8String(ns),
            Memory.allocUtf8String(simpleName));
        if (!lcClass || lcClass.isNull()) {
            // Try alt with full /-separated nested class
            var nestedClass = lcClassName.split('/');
            if (nestedClass.length > 1) {
                lcClass = fns.cFN(protoImage,
                    Memory.allocUtf8String(ns),
                    Memory.allocUtf8String(nestedClass.join('+')));
            }
        }

        var fields = [];
        if (lcClass && !lcClass.isNull()) {
            var iter2 = Memory.alloc(Process.pointerSize); iter2.writePointer(ptr(0));
            var f2;
            while ((f2 = fns.cGF(lcClass, iter2)) && !f2.isNull()) {
                try {
                    fields.push({
                        name: fns.fGN(f2).readCString(),
                        type: fns.tGN(fns.fGT(f2)).readCString(),
                        offset: '0x'+fns.fGO(f2).toString(16)
                    });
                } catch(e) {}
            }
        }
        return {
            ok:true,
            displayProtoLocationCardField: locationCardType,
            locationCardClass: lcClass ? lcClass.toString() : null,
            locationCardFields: fields
        };
    },

    /* Bulk fresh poll - returns dict uid_str -> all fresh fields. */
    freshPollAll: function() {
        if (!init()) return {ok:false, err:state.err};
        var idx = buildProtoIndex();
        var results = {};
        var stats = {total:0, withDisplay:0, withLoc:0, withMega:0, withTags:0, withBread:0, errors:0};

        for (var key in idx) {
            stats.total++;
            var proto = idx[key];
            var rec = {};

            try {
                var lo = proto.add(32).readS32();
                var hi = proto.add(36).readS32();
                var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
                rec.uid = uidNum.toString();
                rec.pokemonId = proto.add(40).readS32();
            } catch(e) { stats.errors++; continue; }

            // Full proto bytes (0x200 bytes - covers tags @ 0x180, bread @ 0x1c8)
            try {
                rec.protoBytes = readBytesHex(proto, 0x200);
            } catch(e) {}

            // Display proto bytes (0x80 bytes)
            try {
                var dispPtr = proto.add(0xd8).readPointer();
                if (!dispPtr.isNull()) {
                    rec.displayBytes = readBytesHex(dispPtr, 0x80);
                    stats.withDisplay++;

                    // LocationCard sub-message
                    try {
                        var locPtr = dispPtr.add(0x58).readPointer();
                        if (!locPtr.isNull()) {
                            rec.locBytes = readBytesHex(locPtr, 0x40);
                            stats.withLoc++;
                        }
                    } catch(e) {}

                    // MegaEvolutionLevel sub-message
                    try {
                        var megaPtr = dispPtr.add(0x50).readPointer();
                        if (!megaPtr.isNull()) {
                            rec.megaBytes = readBytesHex(megaPtr, 0x40);
                            stats.withMega++;
                        }
                    } catch(e) {}
                }
            } catch(e) {}

            // pokemonTagIds_ at +0x180
            try {
                var tagsPtr = proto.add(0x180).readPointer();
                if (!tagsPtr.isNull()) {
                    var tagCount = tagsPtr.add(0x18).readS32();
                    if (tagCount >= 0 && tagCount < 100) {
                        rec.tagCount = tagCount;
                        if (tagCount > 0) {
                            var itemsArr = tagsPtr.add(0x10).readPointer();
                            if (!itemsArr.isNull()) {
                                var tagIds = [];
                                for (var i = 0; i < tagCount; i++) {
                                    try {
                                        tagIds.push(itemsArr.add(0x20 + i*8).readU64().toString());
                                    } catch(e) {}
                                }
                                rec.tagIds = tagIds;
                                stats.withTags++;
                            }
                        }
                    }
                }
            } catch(e) {}

            // breadMoves_ at +0x1c8
            try {
                var breadPtr = proto.add(0x1c8).readPointer();
                if (!breadPtr.isNull()) {
                    var bcount = breadPtr.add(0x18).readS32();
                    if (bcount >= 0 && bcount < 100) {
                        rec.breadCount = bcount;
                        if (bcount > 0) stats.withBread++;
                    }
                }
            } catch(e) {}

            results[rec.uid] = rec;
        }
        return {ok:true, stats:stats, results:results};
    }
};
