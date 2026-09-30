/*
 * extract_submessages.js — read MegaEvolutionLevel and LocationCard sub-messages
 * for every PokemonProto in heap. Reads each sub-message's klass + dumps fields
 * via il2cpp_class_get_fields, then by-uid: dereference 0x50 / 0x58 / 0x88 of
 * the live PokemonDisplayProto and read sub-message fields by offset.
 *
 * Sub-message classes (in holo-protos.dll):
 *   Holoholo.Rpc.PokemonMegaEvolutionLevelProto   — pointer at +0x50 of display
 *   Holoholo.Rpc.LocationCardDisplayProto         — pointer at +0x58 of display
 *   Holoholo.Rpc.TempEvoLocationDisplayAttributes — pointer at +0x88 of display
 *
 * Driver flow:
 *   1) probeFields() to learn each class's layout
 *   2) buildProtoIndex() to map uid → live PokemonProto pointer
 *   3) extract({uidList}) returns per-uid {mega, locationCard, tempEvo} structs
 */

var fns = {};
var state = {ready: false, err: null};
var pokemonProtoClass = null;
var protoImage = null;
var displayClass = null;
var megaClass = null;
var locCardClass = null;
var locCardInnerClass = null;
var tempEvoClass = null;

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
    fns.cGM = bind("il2cpp_class_get_methods",'pointer',['pointer','pointer']);
    fns.mGN = bind("il2cpp_method_get_name",'pointer',['pointer']);
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
    if (!protoImage) { state.err = "holo-protos.dll not found"; return false; }

    pokemonProtoClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("PokemonProto"));
    displayClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("PokemonDisplayProto"));
    megaClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("PokemonMegaEvolutionLevelProto"));
    locCardClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("LocationCardDisplayProto"));
    // Try the inner type at +0x10 of LocationCardDisplayProto.
    locCardInnerClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("LocationCard"));
    tempEvoClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("TempEvoLocationDisplayAttributes"));
    if (!tempEvoClass || tempEvoClass.isNull()) {
        // Try alternate name
        tempEvoClass = fns.cFN(protoImage,
            Memory.allocUtf8String("Holoholo.Rpc"),
            Memory.allocUtf8String("PokemonTempEvolutionLocationCardProto"));
    }

    if (!pokemonProtoClass || pokemonProtoClass.isNull()) { state.err = "PokemonProto class missing"; return false; }

    state.ready = true;
    return true;
}

function probeClass(klass, label) {
    if (!klass || klass.isNull()) return {ok:false, err:label + " class null"};
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var f, fields = [];
    while ((f = fns.cGF(klass, iter)) && !f.isNull()) {
        try {
            fields.push({
                name: fns.fGN(f).readCString(),
                type: fns.tGN(fns.fGT(f)).readCString(),
                offset: fns.fGO(f)
            });
        } catch(e) {}
    }
    return {ok:true, klass: klass.toString(), fields: fields};
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

function heapScan(klass, maxMatches) {
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
    return matches;
}

var protoIndex = null;
function buildProtoIndex() {
    var matches = heapScan(pokemonProtoClass, 20000);
    var idx = {};
    for (var i = 0; i < matches.length; i++) {
        try {
            var addr = matches[i];
            var pid = addr.add(40).readS32();
            if (pid < 1 || pid > 1100) continue;
            var lo = addr.add(32).readS32();
            var hi = addr.add(36).readS32();
            idx[lo + "," + hi] = addr;
        } catch(e) {}
    }
    return idx;
}

// Read a sub-message and dump every field by offset/type via the field metadata.
// fieldMeta: [{name, type, offset}, ...]
// enumTypes: optional Set of type strings that are known enums (read as i32).
function readSubMessage(subPtr, fieldMeta, enumTypes) {
    if (!subPtr || subPtr.isNull()) return null;

    // Sanity: the first 8 bytes of any il2cpp object must be a klass pointer.
    // Don't dereference if it looks invalid.
    try {
        var maybeKlass = subPtr.readPointer();
        if (maybeKlass.isNull()) return null;
    } catch(e) { return null; }

    var out = {addr: subPtr.toString()};
    for (var i = 0; i < fieldMeta.length; i++) {
        var f = fieldMeta[i];
        if (f.offset < 0x10) continue;  // klass + monitor header
        try {
            var t = f.type;
            // Strip namespace
            var simple = t.indexOf('.') >= 0 ? t.substring(t.lastIndexOf('.')+1) : t;
            if (t === "System.Int32" || t === "int" || simple === "Int32") {
                out[f.name] = subPtr.add(f.offset).readS32();
            } else if (t === "System.Int64" || t === "long" || simple === "Int64") {
                out[f.name] = subPtr.add(f.offset).readS64().toString();
            } else if (t === "System.UInt32" || simple === "UInt32") {
                out[f.name] = subPtr.add(f.offset).readU32();
            } else if (t === "System.UInt64" || simple === "UInt64") {
                out[f.name] = subPtr.add(f.offset).readU64().toString();
            } else if (t === "System.Single" || t === "float" || simple === "Single") {
                out[f.name] = subPtr.add(f.offset).readFloat();
            } else if (t === "System.Double" || t === "double" || simple === "Double") {
                out[f.name] = subPtr.add(f.offset).readDouble();
            } else if (t === "System.Boolean" || t === "bool" || simple === "Boolean") {
                out[f.name] = subPtr.add(f.offset).readU8() !== 0;
            } else if (t === "System.Byte" || simple === "Byte") {
                out[f.name] = subPtr.add(f.offset).readU8();
            } else if (t === "System.String" || simple === "String") {
                var sp = subPtr.add(f.offset).readPointer();
                if (sp.isNull()) { out[f.name] = null; continue; }
                var len = sp.add(0x10).readS32();
                if (len < 0 || len > 1000) { out[f.name] = "<bad string len " + len + ">"; continue; }
                var chars = [];
                for (var ci = 0; ci < len; ci++)
                    chars.push(String.fromCharCode(sp.add(0x14 + ci*2).readU16()));
                out[f.name] = chars.join('');
            } else if (t.indexOf("Enum") >= 0 || /Types\+/.test(t) || (enumTypes && enumTypes[t])) {
                // Enums are i32 in IL2CPP
                out[f.name] = subPtr.add(f.offset).readS32();
            } else {
                // For everything else (sub-messages, arrays, etc.) record
                // whether the pointer is non-null and where.
                try {
                    var p = subPtr.add(f.offset).readPointer();
                    if (p.isNull()) {
                        out[f.name] = null;
                    } else {
                        out[f.name + "_ptr"] = p.toString();
                        // Best-effort: also record raw i32/i64 as fallback
                        out[f.name + "_i32"] = subPtr.add(f.offset).readS32();
                        out[f.name + "_i64"] = subPtr.add(f.offset).readS64().toString();
                    }
                } catch(e) {}
            }
        } catch(e) { out[f.name + "_err"] = e.message; }
    }
    return out;
}

rpc.exports = {
    initStatus: function() { init(); return {ready: state.ready, err: state.err}; },

    probeFields: function() {
        if (!init()) return {ok:false, err: state.err};
        return {
            ok: true,
            display:      probeClass(displayClass, "PokemonDisplayProto"),
            mega:         probeClass(megaClass, "PokemonMegaEvolutionLevelProto"),
            locCard:      probeClass(locCardClass, "LocationCardDisplayProto"),
            locCardInner: probeClass(locCardInnerClass, "LocationCard"),
            tempEvo:      probeClass(tempEvoClass, "TempEvoLocationDisplayAttributes"),
        };
    },

    indexPokemon: function() {
        if (!init()) return {ok:false, err: state.err};
        protoIndex = buildProtoIndex();
        return {ok:true, count: Object.keys(protoIndex).length};
    },

    /* Extract sub-message contents for every pokemon in heap.
     * enumTypes: dict of {type_string: true} for fields that should be read as i32.
     * Returns {uid_str: {mega:{...}, locationCard:{...}, locationCardInner:{...}, tempEvo:{...}, ...}} */
    extractAll: function(megaFields, locFields, locInnerFields, tempFields, enumTypes) {
        if (!init()) return {ok:false, err: state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();

        var results = {};
        var stats = {total: 0, withDisplay: 0, withMega: 0, withLoc: 0, withTemp: 0};

        for (var key in protoIndex) {
            var proto = protoIndex[key];
            stats.total++;
            try {
                var lo = proto.add(32).readS32();
                var hi = proto.add(36).readS32();
                var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
                var uid = uidNum.toString();

                // pokemonDisplay_ at +0xd8 of PokemonProto
                var displayPtr = proto.add(0xd8).readPointer();
                if (displayPtr.isNull()) continue;
                stats.withDisplay++;

                var rec = {uid: uid, displayPtr: displayPtr.toString()};

                // Verify the displayPtr looks valid: its first 8 bytes must be a klass
                // pointer matching displayClass. If not, this is a stale or false PokemonProto.
                try {
                    var dispKlass = displayPtr.readPointer();
                    if (dispKlass.toString() !== displayClass.toString()) continue;
                } catch(e) { continue; }

                var megaPtr = displayPtr.add(0x50).readPointer();
                if (!megaPtr.isNull()) {
                    // Validate sub-message klass
                    try {
                        var mk = megaPtr.readPointer();
                        if (mk.toString() === megaClass.toString()) {
                            rec.megaPtr = megaPtr.toString();
                            rec.mega = readSubMessage(megaPtr, megaFields, enumTypes);
                            if (rec.mega) stats.withMega++;
                        }
                    } catch(e) {}
                }
                var locPtr = displayPtr.add(0x58).readPointer();
                if (!locPtr.isNull()) {
                    try {
                        var lk = locPtr.readPointer();
                        if (lk.toString() === locCardClass.toString()) {
                            rec.locPtr = locPtr.toString();
                            rec.locationCard = readSubMessage(locPtr, locFields, enumTypes);
                            if (rec.locationCard) stats.withLoc++;
                        }
                    } catch(e) {}
                }
                if (tempEvoClass && !tempEvoClass.isNull()) {
                    var tempPtr = displayPtr.add(0x88).readPointer();
                    if (!tempPtr.isNull()) {
                        try {
                            var tk = tempPtr.readPointer();
                            if (tk.toString() === tempEvoClass.toString()) {
                                rec.tempPtr = tempPtr.toString();
                                rec.tempEvo = readSubMessage(tempPtr, tempFields, enumTypes);
                                if (rec.tempEvo) stats.withTemp++;
                            }
                        } catch(e) {}
                    }
                }

                if (rec.mega || rec.locationCard || rec.tempEvo) {
                    results[uid] = rec;
                }
            } catch(e) {}
        }
        return {ok:true, stats: stats, results: results};
    },
};

send({type:"ready", msg:"extract_submessages.js loaded"});
