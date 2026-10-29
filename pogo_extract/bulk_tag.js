/*
 * bulk_tag.js — apply tags to a batch of pokemon by UID via the
 * Niantic.Holoholo.Tagging.TaggingRpcService.SetPokemonTagsForPokemon path.
 *
 * Driver flow:
 *   1) Resolve TaggingRpcService class + the SetTags-style method
 *   2) Locate a TaggingRpcService instance via heap scan
 *   3) For each pokemon UID we want to tag, find the PokemonProto pointer
 *   4) Build the tag list arg, invoke the RPC method
 *
 * Returns progress via send() for each tagged UID. Designed to run inside one
 * Frida session for as long as libconceal allows; whatever finishes is good.
 */

var state = {ready: false, err: null};
var fns = {};
var pokemonProtoClass = null;
var taggingServiceClass = null;
var setTagsMethod = null;
var setTagsParamCount = 0;
var listIntClass = null;
var capturedThisPointers = {};
var capturedSetPokemonTagsArgs = null;  // (this, listPtr) on first SetPokemonTags call
var capturedAddTagArgs = null;           // (this, name, color) on first AddTag

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
    fns.mGPC = bind("il2cpp_method_get_param_count",'int',['pointer']);
    fns.mGP = bind("il2cpp_method_get_param",'pointer',['pointer','int']);
    fns.tGN = bind("il2cpp_type_get_name",'pointer',['pointer']);
    fns.tA  = bind("il2cpp_thread_attach",'pointer',['pointer']);
    fns.objNew = bind("il2cpp_object_new",'pointer',['pointer']);
    fns.rI  = bind("il2cpp_runtime_invoke",'pointer',['pointer','pointer','pointer','pointer']);
    fns.cN  = bind("il2cpp_class_get_name",'pointer',['pointer']);
    fns.cGNs = bind("il2cpp_class_get_namespace",'pointer',['pointer']);
    fns.rCI  = bind("il2cpp_runtime_class_init",'void',['pointer']);
    fns.cFT  = bind("il2cpp_class_from_type",'pointer',['pointer']);
    fns.cGF  = bind("il2cpp_class_get_fields",'pointer',['pointer','pointer']);
    fns.fGN  = bind("il2cpp_field_get_name",'pointer',['pointer']);
    fns.fGT  = bind("il2cpp_field_get_type",'pointer',['pointer']);

    var dom = fns.dG();
    fns.tA(dom);

    var sp = Memory.alloc(4);
    var asms = fns.dGA(dom, sp);
    var na = sp.readS32();

    // Find images
    var protoImage = null, gameImage = null, mscorlibImage = null;
    for (var a = 0; a < na; a++) {
        var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
        var nm = fns.iGN(img).readCString();
        if (nm === "holo-protos.dll") protoImage = img;
        if (nm === "holo-game.dll") gameImage = img;
        if (nm === "mscorlib.dll") mscorlibImage = img;
    }
    if (!protoImage || !gameImage) {
        state.err = "missing image: protos=" + protoImage + " game=" + gameImage;
        return false;
    }

    pokemonProtoClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("PokemonProto"));
    if (!pokemonProtoClass || pokemonProtoClass.isNull()) {
        state.err = "PokemonProto class not found"; return false;
    }

    // Try TaggingRpcService - the actual implementation
    taggingServiceClass = fns.cFN(gameImage,
        Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
        Memory.allocUtf8String("TaggingRpcService"));
    if (!taggingServiceClass || taggingServiceClass.isNull()) {
        state.err = "TaggingRpcService class not found"; return false;
    }
    send({type:"status", msg:"TaggingRpcService class @ " + taggingServiceClass});

    // Enumerate methods, find Set/Add tags method
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var m;
    var methods = [];
    while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
        try {
            var name = fns.mGN(m).readCString();
            var pc = fns.mGPC(m);
            var params = [];
            for (var i = 0; i < pc; i++) {
                var pt = fns.mGP(m, i);
                if (pt && !pt.isNull()) {
                    var tn = fns.tGN(pt).readCString();
                    params.push(tn);
                }
            }
            methods.push({name: name, params: params, ptr: m.toString()});
        } catch (e) {}
    }
    send({type:"methods", data: methods});

    // Pick the right method - look for Set/Add tags with PokemonProto + tag list args
    for (var i = 0; i < methods.length; i++) {
        var meth = methods[i];
        var nl = meth.name.toLowerCase();
        if (nl.indexOf('set') >= 0 && nl.indexOf('tag') >= 0 && meth.params.length >= 2) {
            setTagsMethod = ptr(meth.ptr);
            setTagsParamCount = meth.params.length;
            send({type:"status", msg:"Picked method: " + meth.name + " (" + meth.params.join(", ") + ")"});
            break;
        }
    }
    if (!setTagsMethod) {
        // Fallback: any "tag" method with multiple args
        for (var i = 0; i < methods.length; i++) {
            var meth = methods[i];
            var nl = meth.name.toLowerCase();
            if (nl.indexOf('tag') >= 0 && meth.params.length >= 2 && nl.indexOf('get') < 0) {
                setTagsMethod = ptr(meth.ptr);
                setTagsParamCount = meth.params.length;
                send({type:"status", msg:"Fallback method: " + meth.name});
                break;
            }
        }
    }
    if (!setTagsMethod) { state.err = "Could not find SetTags method"; return false; }

    // Eliminate the "first SetPokemonTags throws 'abort was called'" quirk.
    //
    // Why: il2cpp-generated method bodies guard their entry with a per-method
    // s_Il2CppMethodInitialized flag that lazily runs metadata init + every
    // referenced class's static .cctor on first hit. il2cpp_runtime_invoke
    // bypasses that guard, so the first call into SetPokemonTags enters the
    // generated body with the inflated List<PokemonTagProto>,
    // List<PokemonTagChanges>, and PokemonTagChanges classes still flagged
    // RuntimeClassNeedsInit. Hitting one of them inside the method body
    // aborts the runtime, which Frida surfaces as "Error: abort was called".
    //
    // Fix: drive il2cpp_runtime_class_init on every class the SetPokemonTags
    // path will touch, while we are still on a thread that can tolerate a
    // .cctor running. After this, no warm-up call is needed.
    primeTaggingClasses(gameImage, protoImage);

    state.ready = true;
    send({type:"status", msg:"init OK"});
    return true;
}

function primeTaggingClasses(gameImage, protoImage) {
    if (!fns.rCI || !fns.cFT) {
        send({type:"status", msg:"prime skipped: missing il2cpp_runtime_class_init / il2cpp_class_from_type"});
        return;
    }

    function initKlass(k, label) {
        if (!k || k.isNull()) return;
        try { fns.rCI(k); send({type:"status", msg:"primed " + label}); }
        catch (e) { send({type:"status", msg:"prime " + label + " threw: " + e.message}); }
    }

    // 1. The service class itself (its .cctor caches metadata pointers).
    initKlass(taggingServiceClass, "TaggingRpcService");

    // 2. PokemonTagChanges (the per-pokemon change record).
    var ptcClass = fns.cFN(gameImage,
        Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
        Memory.allocUtf8String("PokemonTagChanges"));
    initKlass(ptcClass, "PokemonTagChanges");

    // 3. The inflated List<PokemonTagChanges> resolved from SetPokemonTags
    //    parameter 0. This is the critical one: it is a generic instantiation
    //    that lives entirely in metadata until something forces its init.
    try {
        var paramType = fns.mGP(setTagsMethod, 0);
        var listChangesClass = fns.cFT(paramType);
        initKlass(listChangesClass, "List<PokemonTagChanges>");
    } catch (e) {
        send({type:"status", msg:"prime List<PokemonTagChanges> failed: " + e.message});
    }

    // 4. The inflated List<PokemonTagProto> resolved from
    //    PokemonTagChanges.TagsToAdd / TagsToRemove field types. Both fields
    //    are the same generic instantiation, so initializing one is enough.
    if (ptcClass && !ptcClass.isNull() && fns.cGF && fns.fGN && fns.fGT) {
        try {
            var fIter = Memory.alloc(Process.pointerSize); fIter.writePointer(ptr(0));
            var f;
            while ((f = fns.cGF(ptcClass, fIter)) && !f.isNull()) {
                var fname = fns.fGN(f).readCString();
                if (fname === "TagsToAdd" || fname === "TagsToRemove") {
                    var listProtoClass = fns.cFT(fns.fGT(f));
                    initKlass(listProtoClass, "List<PokemonTagProto> via " + fname);
                    break;
                }
            }
        } catch (e) {
            send({type:"status", msg:"prime List<PokemonTagProto> failed: " + e.message});
        }
    }

    // 5. PokemonTagProto itself (the element type).
    var ptpClass = fns.cFN(protoImage,
        Memory.allocUtf8String("Holoholo.Rpc"),
        Memory.allocUtf8String("PokemonTagProto"));
    initKlass(ptpClass, "PokemonTagProto");
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
    return matches;
}

// Cache of pokemon proto pointers
var protoIndex = null;  // Map of "low,high" -> ptr
function buildProtoIndex() {
    var matches = heapScan(pokemonProtoClass, "PokemonProto", 20000);
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

// IDENTITY AT WRITE TIME (H01, 2026-09-29). A proto pointer is only a pointer: the walk that produced it ran seconds
// earlier (or, in prune's per-tag path, several writes earlier -- every tag write REALLOCATES the mon's proto). A proto
// dropped by a release / evolve / re-tag is collected by bdwgc and its block handed to the next object of that size --
// often another PokemonProto (the catcher runs during culls). Is it STILL a PokemonProto carrying this uid (id_ @0x20,
// proto_layout.json)? Pure reads, no managed call.
// R7 (Gym Battle review): the id_ offset is read from PokemonProto's own field table once (0x20 in proto_layout.json
// today), so a layout change cannot turn every change into a silent "mismatched".
var _PROTO_ID_OFF = null;
function _protoIdOff() {
    if (_PROTO_ID_OFF !== null) return _PROTO_ID_OFF;
    _PROTO_ID_OFF = 0x20;
    try { _ghFields(pokemonProtoClass, false).forEach(function (f) { if (f.name === 'id_') _PROTO_ID_OFF = f.off; }); } catch (e) {}
    return _PROTO_ID_OFF;
}
function protoStillIs(protoStr, uidStr) {
    try {
        var p = ptr(protoStr);
        if (p.isNull() || !pokemonProtoClass) return false;
        return p.readPointer().equals(pokemonProtoClass) && p.add(_protoIdOff()).readU64().toString() === String(uidStr);
    } catch (e) { return false; }
}

var serviceInstance = null;
function findServiceInstance() {
    if (serviceInstance) return serviceInstance;
    var matches = heapScan(taggingServiceClass, "TaggingRpcService", 10);
    if (matches.length === 0) return null;
    // R2 (Gym Battle review, 2026-09-29): after an in-process rebuild the first hit can be the STALE service. The legacy
    // callers (run_bulk_tag.py / extract_tag_ids.py) get no guess: more than one instance -> refuse; the cull passes
    // the live graph's service (pogo_il2cpp.pick_singleton) to bulkApplyChanges instead.
    if (matches.length > 1) {
        state.err = matches.length + " TaggingRpcService instances (the game rebuilt its services) -- refusing to guess; " +
                    "pass the live one from pogo_il2cpp.pick_singleton";
        return null;
    }
    serviceInstance = matches[0];
    return serviceInstance;
}

rpc.exports = {
    initStatus: function() { init(); return {ready: state.ready, err: state.err}; },

    discoverMethods: function() {
        if (!init()) return {ok: false, err: state.err};
        return {ok: true};
    },

    indexPokemon: function() {
        if (!init()) return {ok: false, err: state.err};
        protoIndex = buildProtoIndex();
        return {ok: true, count: Object.keys(protoIndex).length};
    },


    /* Get tag ID by name - iterate bindings, find match. */
    findTagIdByName: function(instanceStr, tagName) {
        if (!init()) return {ok:false, err:state.err};
        var inst = ptr(instanceStr);
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount=null, getBinding=null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            var nm = fns.mGN(m).readCString();
            if (nm === "get_NumberOfTags") getCount = m;
            if (nm === "GetCachedTagToPokemonBindingForIndex") getBinding = m;
        }
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(getCount, inst, ptr(0), exc);
        var count = ret.add(0x10).readS32();

        for (var i = 0; i < count; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize);
            args.writePointer(idxBuf);
            var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
            var bindingPtr = fns.rI(getBinding, inst, args, exc2);
            if (!exc2.readPointer().isNull() || bindingPtr.isNull()) continue;

            // TagToPokemonBinding @ +0x10 -> PokemonTagProto pointer
            try {
                var tagProto = bindingPtr.add(0x10).readPointer();
                if (tagProto.isNull()) continue;
                // Tag name was found at +0x40 of nested PokemonTagProto in our enum
                var nameStrPtr = tagProto.add(0x40).readPointer();
                if (nameStrPtr.isNull()) continue;
                var len = nameStrPtr.add(0x10).readS32();
                if (len <= 0 || len > 100) continue;
                var chars = [];
                for (var ci = 0; ci < len; ci++)
                    chars.push(String.fromCharCode(nameStrPtr.add(0x14 + ci*2).readU16()));
                var s = chars.join('');
                if (s === tagName) {
                    // Probe ALL offsets 0x00..0x80 for tag ID (non-zero small ints/longs)
                    var dump = {};
                    for (var off = 0; off <= 0x80; off += 4) {
                        try {
                            var v32 = tagProto.add(off).readS32();
                            if (v32 != 0) dump['+0x' + off.toString(16) + '_i32'] = v32;
                        } catch(e) {}
                    }
                    for (var off = 0; off <= 0x80; off += 8) {
                        try {
                            var v64 = tagProto.add(off).readS64().toString();
                            if (v64 != "0" && v64.length < 20) dump['+0x' + off.toString(16) + '_i64'] = v64;
                        } catch(e) {}
                    }
                    return {ok:true, name:s, idx:i, tagProtoAddr: tagProto.toString(), bindingAddr: bindingPtr.toString(), dump: dump};
                }
            } catch(e) {}
        }
        return {ok:false, err:"not found"};
    },

    /* How many cached tags carry exactly this name (2026-09-30: a verify-miss retry in tag_ops.create_tag made TWO
       'Evolve for UL'). findTagIdByName returns the FIRST match, so with a duplicate name every write is ambiguous. */
    countTagsByName: function(instanceStr, tagName) {
        if (!init()) return {ok:false, err:state.err};
        var inst = ptr(instanceStr);
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount=null, getBinding=null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            var nm = fns.mGN(m).readCString();
            if (nm === "get_NumberOfTags") getCount = m;
            if (nm === "GetCachedTagToPokemonBindingForIndex") getBinding = m;
        }
        if (!getCount || !getBinding) return {ok:false, err:"missing methods"};
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(getCount, inst, ptr(0), exc);
        if (!exc.readPointer().isNull()) return {ok:false, err:"count exc"};
        var count = ret.add(0x10).readS32();
        var n = 0, addrs = [];
        for (var i = 0; i < count; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
            var bindingPtr = fns.rI(getBinding, inst, args, exc2);
            if (!exc2.readPointer().isNull() || bindingPtr.isNull()) continue;
            try {
                var tagProto = bindingPtr.add(0x10).readPointer();
                if (tagProto.isNull()) continue;
                var nameStrPtr = tagProto.add(0x40).readPointer();
                if (nameStrPtr.isNull()) continue;
                var len = nameStrPtr.add(0x10).readS32();
                if (len <= 0 || len > 100) continue;
                var chars = [];
                for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(nameStrPtr.add(0x14 + ci*2).readU16()));
                if (chars.join('') === tagName) { n++; addrs.push(tagProto.toString()); }
            } catch(e) {}
        }
        return {ok:true, count:n, addrs:addrs};
    },

    /* Every cached tag as [name, tagProtoAddr], in binding order (2026-10-29, cull speed: prune looked ~30 tags up one by
       one, findTagIdByName + countTagsByName = 2 RPCs apiece, ~4 s). The walk and filters of countTagsByName: a name's
       first address is findTagIdByName's answer, its number of addresses countTagsByName's count. Read-only. */
    tagsByName: function(instanceStr) {
        if (!init()) return {ok:false, err:state.err};
        var inst = ptr(instanceStr);
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount=null, getBinding=null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            var nm = fns.mGN(m).readCString();
            if (nm === "get_NumberOfTags") getCount = m;
            if (nm === "GetCachedTagToPokemonBindingForIndex") getBinding = m;
        }
        if (!getCount || !getBinding) return {ok:false, err:"missing methods"};
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(getCount, inst, ptr(0), exc);
        if (!exc.readPointer().isNull()) return {ok:false, err:"count exc"};
        var count = ret.add(0x10).readS32();
        var tags = [];
        for (var i = 0; i < count; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
            var bindingPtr = fns.rI(getBinding, inst, args, exc2);
            if (!exc2.readPointer().isNull() || bindingPtr.isNull()) continue;
            try {
                var tagProto = bindingPtr.add(0x10).readPointer();
                if (tagProto.isNull()) continue;
                var nameStrPtr = tagProto.add(0x40).readPointer();
                if (nameStrPtr.isNull()) continue;
                var len = nameStrPtr.add(0x10).readS32();
                if (len <= 0 || len > 100) continue;
                var chars = [];
                for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(nameStrPtr.add(0x14 + ci*2).readU16()));
                tags.push([chars.join(''), tagProto.toString()]);
            } catch(e) {}
        }
        return {ok:true, tags:tags};
    },

    /* Look up pokemon proto pointer by uid from internal index. */
    findPokemonProto: function(uidLow, uidHigh) {
        if (!init()) return {ok:false, err:state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();
        var key = (uidLow|0) + "," + (uidHigh|0);
        var p = protoIndex[key];
        return p ? {ok:true, ptr: p.toString()} : {ok:false, err:"not in index", key:key, indexSize: Object.keys(protoIndex).length};
    },

    /* Dump RepeatedField structure for ANY pokemon by UID. Returns:
       - tagsPtr (the +0x180 pointer)
       - bytes 0..0x40 as i32/i64/ptr triples
       - candidate count + items pointer reads at common offsets
       - if a likely items pointer exists, dump first N u64s as candidate tag IDs */
    dumpRepeatedField: function(uidLow, uidHigh) {
        if (!init()) return {ok:false, err:state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();
        var key = (uidLow|0) + "," + (uidHigh|0);
        var proto = protoIndex[key];
        if (!proto) return {ok:false, err:"not in index", key:key, indexSize: Object.keys(protoIndex).length};

        var out = {protoAddr: proto.toString()};
        var tagsPtr;
        try { tagsPtr = proto.add(0x180).readPointer(); }
        catch(e) { return {ok:false, err:"can't read +0x180: " + e.message}; }
        out.tagsPtr = tagsPtr.toString();
        if (tagsPtr.isNull()) return {ok:true, dump: out, note:"tagsPtr is null"};

        try {
            var k = tagsPtr.readPointer();
            out.klass = k.toString();
            try { out.klassName = fns.cGNs(k).readCString() + "." + fns.cN(k).readCString(); } catch(e) {}
        } catch(e) { out.klassErr = e.message; }

        var bytes = {};
        for (var off = 0; off <= 0x40; off += 4) {
            try { bytes['+0x' + off.toString(16) + '_i32'] = tagsPtr.add(off).readS32(); } catch(e) {}
        }
        for (var off = 0; off <= 0x40; off += 8) {
            try { bytes['+0x' + off.toString(16) + '_i64'] = tagsPtr.add(off).readS64().toString(); } catch(e) {}
            try {
                var p = tagsPtr.add(off).readPointer();
                bytes['+0x' + off.toString(16) + '_ptr'] = p.toString();
            } catch(e) {}
        }
        out.bytes = bytes;

        // Try common count offsets (0x10, 0x14, 0x18, 0x1c, 0x20)
        // and items-pointer offsets (0x10, 0x18, 0x20, 0x28).
        var trials = [];
        var countOffs = [0x10, 0x14, 0x18, 0x1c, 0x20];
        var itemOffs  = [0x10, 0x18, 0x20, 0x28];
        for (var c = 0; c < countOffs.length; c++) {
            var co = countOffs[c];
            var cnt;
            try { cnt = tagsPtr.add(co).readS32(); } catch(e) { continue; }
            if (cnt < 0 || cnt > 50) continue;
            for (var i = 0; i < itemOffs.length; i++) {
                var io = itemOffs[i];
                if (io === co) continue;
                var items;
                try { items = tagsPtr.add(io).readPointer(); } catch(e) { continue; }
                if (items.isNull()) continue;
                // Try Items as a C# array (klass@+0, monitor@+8, length@+0x18, data@+0x20)
                // OR a raw u64[] starting earlier. Test both.
                var t = {countOff:'0x'+co.toString(16), itemsOff:'0x'+io.toString(16), count:cnt, itemsAddr:items.toString()};
                try {
                    var arrLen = items.add(0x18).readS32();
                    t.arrLen = arrLen;
                } catch(e) { t.arrLenErr = e.message; }
                var ids_at20 = [], ids_at10 = [], ids_at0 = [];
                for (var j = 0; j < Math.min(cnt > 0 ? cnt : 5, 8); j++) {
                    try { ids_at20.push(items.add(0x20 + j*8).readS64().toString()); } catch(e) {}
                    try { ids_at10.push(items.add(0x10 + j*8).readS64().toString()); } catch(e) {}
                    try { ids_at0.push(items.add(j*8).readS64().toString()); } catch(e) {}
                }
                t.ids_at_data_0x20 = ids_at20;
                t.ids_at_data_0x10 = ids_at10;
                t.ids_at_data_0x00 = ids_at0;
                trials.push(t);
            }
        }
        out.trials = trials;
        return {ok:true, dump: out};
    },

    /* Enumerate every PokemonTagProto instance in heap, return [{id, name, addr}].
       Used to map the 64-bit snowflake IDs in pokemonTagIds_ back to user-visible
       names (TeamEevee, U, Hundos, etc.). */
    enumerateTagProtos: function() {
        if (!init()) return {ok:false, err:state.err};
        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var protoImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-protos.dll") { protoImage = img; break; }
        }
        if (!protoImage) return {ok:false, err:"no holo-protos"};

        var ptpClass = fns.cFN(protoImage,
            Memory.allocUtf8String("Holoholo.Rpc"),
            Memory.allocUtf8String("PokemonTagProto"));
        if (!ptpClass || ptpClass.isNull()) return {ok:false, err:"PokemonTagProto class not found"};

        var matches = heapScan(ptpClass, "PokemonTagProto", 5000);
        var seen = {};
        var results = [];
        for (var i = 0; i < matches.length; i++) {
            var addr = matches[i];
            var rec = {addr: addr.toString()};
            // Probe likely ID offsets (0x18, 0x20, 0x28, 0x30, 0x38) for a non-zero u64.
            // PokemonTagProto.id is the snowflake-style 64-bit value.
            for (var off = 0x10; off <= 0x40; off += 8) {
                try {
                    var v = addr.add(off).readS64().toString();
                    if (v !== "0" && v.length < 22) {
                        rec['+0x' + off.toString(16) + '_i64'] = v;
                    }
                    // Also unsigned form (matches extractAllTagIds output).
                    var u = addr.add(off).readU64().toString();
                    if (u !== "0" && u.length < 22) {
                        rec['+0x' + off.toString(16) + '_u64'] = u;
                    }
                } catch(e) {}
            }
            // Try name string at +0x40
            try {
                var nsp = addr.add(0x40).readPointer();
                if (!nsp.isNull()) {
                    var len = nsp.add(0x10).readS32();
                    if (len > 0 && len < 100) {
                        var chars = [];
                        for (var ci = 0; ci < len; ci++)
                            chars.push(String.fromCharCode(nsp.add(0x14 + ci*2).readU16()));
                        var s = chars.join('');
                        if (/^[\x20-\x7e]+$/.test(s)) rec.name = s;
                    }
                }
            } catch(e) {}
            // Dedup by name (multiple instances exist for the same tag)
            var key = rec.name || ("anon_" + addr.toString());
            if (seen[key]) continue;
            seen[key] = true;
            results.push(rec);
        }
        return {ok:true, count: results.length, scanned: matches.length, results: results};
    },

    /* Bulk extract pokemon_tag_ids_ for ALL pokemon in proto index.
       Caller passes the offsets discovered via dumpRepeatedField:
       - countOff: int32 offset within the RepeatedField struct holding count
       - itemsOff: pointer offset within the RepeatedField struct holding items pointer
       - dataOff:  byte offset within items array where the first u64 lives (commonly 0x20)
       Returns dict uid_str -> [tag_id_str, ...] */
    extractAllTagIds: function(countOff, itemsOff, dataOff) {
        if (!init()) return {ok:false, err:state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();
        countOff = countOff|0;
        itemsOff = itemsOff|0;
        dataOff  = dataOff|0;

        var results = {};
        var stats = {total:0, withTags:0, errors:0, totalTagAssignments:0};
        for (var key in protoIndex) {
            stats.total++;
            var proto = protoIndex[key];
            var lo, hi;
            try { lo = proto.add(32).readS32(); hi = proto.add(36).readS32(); }
            catch(e) { stats.errors++; continue; }
            var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
            var uidStr = uidNum.toString();

            try {
                var tagsPtr = proto.add(0x180).readPointer();
                if (tagsPtr.isNull()) continue;
                var cnt = tagsPtr.add(countOff).readS32();
                if (cnt <= 0 || cnt > 50) continue;
                var items = tagsPtr.add(itemsOff).readPointer();
                if (items.isNull()) continue;
                var ids = [];
                for (var j = 0; j < cnt; j++) {
                    try { ids.push(items.add(dataOff + j*8).readU64().toString()); } catch(e) {}
                }
                if (ids.length > 0) {
                    results[uidStr] = ids;
                    stats.withTags++;
                    stats.totalTagAssignments += ids.length;
                }
            } catch(e) { stats.errors++; }
        }
        return {ok:true, stats: stats, results: results};
    },

    /* Probe RepeatedField structure for a known case (user-tagged pokemon). */
    probeRepeatedField: function(uidLow, uidHigh) {
        if (!init()) return {ok:false, err:state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();
        var key = uidLow + "," + uidHigh;
        var proto = protoIndex[key];
        if (!proto) return {ok:false, err:"not in index"};

        var dump = {};
        // pokemonTagIds_ at 0x180 - read pointer + dump bytes
        var tagsPtr = proto.add(0x180).readPointer();
        dump.tagsPtr = tagsPtr.toString();
        if (!tagsPtr.isNull()) {
            var bytes = {};
            for (var off = 0; off <= 0x40; off += 4) {
                try {
                    bytes['+0x' + off.toString(16) + '_i32'] = tagsPtr.add(off).readS32();
                } catch(e) {}
            }
            for (var off = 0; off <= 0x40; off += 8) {
                try {
                    bytes['+0x' + off.toString(16) + '_ptr'] = tagsPtr.add(off).readPointer().toString();
                } catch(e) {}
            }
            dump.tagsBytes = bytes;
        }
        return {ok:true, dump:dump};
    },

    /* Walk all pokemon protos in heap, extract breadMoves count + tag count. */
    extractRuntimeFlags: function() {
        if (!init()) return {ok:false, err:state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();

        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();

        var results = {};  // uid_str -> {tagCount, breadCount, tagIds[]}
        for (var key in protoIndex) {
            var proto = protoIndex[key];
            var rec = {};
            try {
                // pokemonTagIds_ at +0x180 is a RepeatedField<UInt64> POINTER
                var tagsPtr = proto.add(0x180).readPointer();
                if (!tagsPtr.isNull()) {
                    // RepeatedField layout: header (16), then count, items
                    // Niantic's RepeatedField has _count at offset 0x10 typically
                    var tagCount = tagsPtr.add(0x10).readS32();
                    if (tagCount >= 0 && tagCount < 100) {
                        rec.tagCount = tagCount;
                        // Items array at offset 0x18 typically
                        var itemsArr = tagsPtr.add(0x18).readPointer();
                        var tagIds = [];
                        if (!itemsArr.isNull()) {
                            // C# Array layout: header (16), length (4), data starts at 0x20
                            for (var i = 0; i < Math.min(tagCount, 20); i++) {
                                try {
                                    tagIds.push(itemsArr.add(0x20 + i*8).readS64().toString());
                                } catch(e) {}
                            }
                        }
                        rec.tagIds = tagIds;
                    }
                }
            } catch(e) {}

            try {
                // breadMoves_ at +0x1c8
                var breadPtr = proto.add(0x1c8).readPointer();
                if (!breadPtr.isNull()) {
                    var breadCount = breadPtr.add(0x10).readS32();
                    if (breadCount >= 0 && breadCount < 100) rec.breadCount = breadCount;
                }
            } catch(e) {}

            // also re-read uid for safety
            try {
                var lo = proto.add(32).readS32();
                var hi = proto.add(36).readS32();
                var uidNum = (BigInt(hi) << 32n) | (BigInt(lo) & 0xFFFFFFFFn);
                rec.uid = uidNum.toString();
            } catch(e) {}

            if (rec.uid) results[rec.uid] = rec;
        }
        return {ok:true, count: Object.keys(results).length, results: results};
    },

    /* Probe PokemonDisplayProto fields. */
    probePokemonDisplayProtoFields: function() {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var cGF = new NativeFunction(bind.il2cpp_class_get_fields,'pointer',['pointer','pointer']);
        var fGN = new NativeFunction(bind.il2cpp_field_get_name,'pointer',['pointer']);
        var fGT = new NativeFunction(bind.il2cpp_field_get_type,'pointer',['pointer']);
        var fGO = new NativeFunction(bind.il2cpp_field_get_offset,'uint32',['pointer']);

        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var protoImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-protos.dll") { protoImage = img; break; }
        }
        var displayClass = fns.cFN(protoImage,
            Memory.allocUtf8String("Holoholo.Rpc"),
            Memory.allocUtf8String("PokemonDisplayProto"));

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var f, fields = [];
        while ((f = cGF(displayClass, iter)) && !f.isNull()) {
            try {
                fields.push({
                    name: fGN(f).readCString(),
                    type: fns.tGN(fGT(f)).readCString(),
                    offset: '0x' + fGO(f).toString(16)
                });
            } catch(e) {}
        }
        return {ok:true, fields: fields};
    },

    /* Read pokemonDisplay sub-proto for a given pokemon proto pointer. */
    readDisplayProto: function(protoPtrStr) {
        if (!init()) return {ok:false, err:state.err};
        var proto = ptr(protoPtrStr);
        try {
            var displayPtr = proto.add(0xd8).readPointer();
            if (displayPtr.isNull()) return {ok:false, err:"display null"};
            // Dump first 0x40 bytes
            var dump = {addr: displayPtr.toString()};
            for (var off = 0; off <= 0x40; off += 4) {
                try { dump['+0x' + off.toString(16) + '_i32'] = displayPtr.add(off).readS32(); } catch(e) {}
            }
            return {ok:true, dump:dump};
        } catch(e) { return {ok:false, err:e.message}; }
    },

    /* Probe PokemonProto fields - find dynamax/gigantamax related ones. */
    probePokemonProtoFields: function() {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var cGF = new NativeFunction(bind.il2cpp_class_get_fields,'pointer',['pointer','pointer']);
        var fGN = new NativeFunction(bind.il2cpp_field_get_name,'pointer',['pointer']);
        var fGT = new NativeFunction(bind.il2cpp_field_get_type,'pointer',['pointer']);
        var fGO = new NativeFunction(bind.il2cpp_field_get_offset,'uint32',['pointer']);

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var f, fields = [];
        while ((f = cGF(pokemonProtoClass, iter)) && !f.isNull()) {
            try {
                var fieldName = fGN(f).readCString();
                var fieldType = fns.tGN(fGT(f)).readCString();
                var fieldOffset = fGO(f);
                fields.push({name: fieldName, type: fieldType, offset: '0x' + fieldOffset.toString(16)});
            } catch(e) {}
        }
        return {ok:true, fields: fields};
    },

    /* Get pokemon UIDs assigned to a specific tag (by index). */
    getPokemonForTag: function(serviceInstanceStr, tagIdx) {
        if (!init()) return {ok:false, err:state.err};
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getBinding=null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "GetCachedTagToPokemonBindingForIndex") { getBinding = m; break; }
        }
        var idxBuf = Memory.alloc(4); idxBuf.writeS32(tagIdx);
        var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var bindingPtr = fns.rI(getBinding, ptr(serviceInstanceStr), args, exc);
        if (!exc.readPointer().isNull() || bindingPtr.isNull()) return {ok:false, err:"binding not found"};

        // TagToPokemonBinding has a list of pokemon UIDs at some offset.
        // Probe field at +0x20 onward for a List<long> or similar
        var dump = {bindingAddr: bindingPtr.toString()};
        for (var off = 0x10; off <= 0x60; off += 8) {
            try {
                var v = bindingPtr.add(off).readPointer();
                if (v.isNull()) continue;
                // Try as List<long> - klass@+0, items@+0x10, count@+0x18
                try {
                    var count = v.add(0x18).readS32();
                    if (count > 0 && count < 100000) {
                        var items = v.add(0x10).readPointer();
                        if (!items.isNull()) {
                            var sample = [];
                            var arrLen = items.add(0x18).readS32();
                            // Sample first 5 + last 5 to detect format
                            for (var i = 0; i < count; i++) {
                                try {
                                    var elem = items.add(0x20 + i*8);
                                    sample.push({i:i, asI64: elem.readS64().toString()});
                                } catch(e) {}
                            }
                            dump['+0x' + off.toString(16) + '_listish'] = {count:count, arrLen:arrLen, sample:sample};
                        }
                    }
                } catch(e) {}
            } catch(e) {}
        }
        return {ok:true, dump:dump};
    },

    /* Read tags ON a specific pokemon - returns array of tag names. */
    getPokemonTags: function(serviceInstanceStr, pokemonProtoStr) {
        if (!init()) return {ok:false, err:state.err};
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getAllTags = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "GetAllTags") { getAllTags = m; break; }
        }
        if (!getAllTags) return {ok:false, err:"no GetAllTags"};

        var args = Memory.alloc(Process.pointerSize);
        args.writePointer(ptr(pokemonProtoStr));
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(getAllTags, ptr(serviceInstanceStr), args, exc);
        if (!exc.readPointer().isNull()) return {ok:false, err:"exc"};
        if (ret.isNull()) return {ok:true, tags:[]};

        // ret is List<PokemonTagProto>. Read items array at +0x10, count at +0x18
        var items = ret.add(0x10).readPointer();
        var count = ret.add(0x18).readS32();
        var tags = [];
        if (!items.isNull()) {
            for (var i = 0; i < count; i++) {
                try {
                    var tagProto = items.add(0x20 + i*Process.pointerSize).readPointer();
                    if (tagProto.isNull()) continue;
                    // Tag name string at +0x40 of PokemonTagProto, then string layout +0x10 length, +0x14 chars
                    var nameStr = tagProto.add(0x40).readPointer();
                    if (nameStr.isNull()) continue;
                    var len = nameStr.add(0x10).readS32();
                    if (len <= 0 || len > 100) continue;
                    var chars = [];
                    for (var ci = 0; ci < len; ci++)
                        chars.push(String.fromCharCode(nameStr.add(0x14 + ci*2).readU16()));
                    tags.push(chars.join(''));
                } catch(e) {}
            }
        }
        return {ok:true, tags:tags, count:count};
    },

    /* UNTAG: remove a tag from a single pokemon via TagsToRemove. */
    bulkUntagOne: function(serviceInstanceStr, pokemonProtoStr, tagProtoStr) {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var objNew = new NativeFunction(bind.il2cpp_object_new,'pointer',['pointer']);
        var classFromType = new NativeFunction(bind.il2cpp_class_from_type,'pointer',['pointer']);

        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var gameImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-game.dll") { gameImage = img; break; }
        }
        var ptcClass = fns.cFN(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
            Memory.allocUtf8String("PokemonTagChanges"));

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, setMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "SetPokemonTags") { setMethod = m; break; }
        }
        var listChangesClass = classFromType(fns.mGP(setMethod, 0));

        var cGF = new NativeFunction(bind.il2cpp_class_get_fields,'pointer',['pointer','pointer']);
        var fGN = new NativeFunction(bind.il2cpp_field_get_name,'pointer',['pointer']);
        var fGT = new NativeFunction(bind.il2cpp_field_get_type,'pointer',['pointer']);
        var fIter = Memory.alloc(Process.pointerSize); fIter.writePointer(ptr(0));
        var f, listProtoClass = null;
        while ((f = cGF(ptcClass, fIter)) && !f.isNull()) {
            if (fGN(f).readCString() === "TagsToRemove") { listProtoClass = classFromType(fGT(f)); break; }
        }

        function findMethod(klass, name, paramCount) {
            var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
            var mm;
            while ((mm = fns.cGM(klass, it)) && !mm.isNull()) {
                if (fns.mGN(mm).readCString() === name && fns.mGPC(mm) === paramCount) return mm;
            }
            return null;
        }
        var listProtoCtor = findMethod(listProtoClass, ".ctor", 0);
        var listProtoAdd = findMethod(listProtoClass, "Add", 1);
        var listChangesCtor = findMethod(listChangesClass, ".ctor", 0);
        var listChangesAdd = findMethod(listChangesClass, "Add", 1);
        var noArgs = Memory.alloc(8);

        // Inner List<PokemonTagProto> with the tag to REMOVE
        var removeList = objNew(listProtoClass);
        var exc1 = Memory.alloc(Process.pointerSize); exc1.writePointer(ptr(0));
        fns.rI(listProtoCtor, removeList, noArgs, exc1);
        var addArg1 = Memory.alloc(Process.pointerSize);
        addArg1.writePointer(ptr(tagProtoStr));
        var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
        fns.rI(listProtoAdd, removeList, addArg1, exc2);

        // Empty TagsToAdd: use ctor(int) so _items array is initialized
        var addList = objNew(listProtoClass);
        // Find ctor with 1 int param (capacity)
        var listProtoCtorCap = findMethod(listProtoClass, ".ctor", 1);
        if (listProtoCtorCap) {
            var capBuf = Memory.alloc(4); capBuf.writeS32(0);
            var capArgs = Memory.alloc(Process.pointerSize);
            capArgs.writePointer(capBuf);
            var excAdd = Memory.alloc(Process.pointerSize); excAdd.writePointer(ptr(0));
            fns.rI(listProtoCtorCap, addList, capArgs, excAdd);
        } else {
            // Fallback: 0-arg ctor + dummy add/clear
            var excAdd = Memory.alloc(Process.pointerSize); excAdd.writePointer(ptr(0));
            fns.rI(listProtoCtor, addList, noArgs, excAdd);
        }
        var ptcInst = objNew(ptcClass);
        ptcInst.add(0x10).writePointer(ptr(pokemonProtoStr));
        ptcInst.add(0x18).writePointer(addList);
        ptcInst.add(0x20).writePointer(removeList);

        // Outer list with this one item
        var outerList = objNew(listChangesClass);
        var exc3 = Memory.alloc(Process.pointerSize); exc3.writePointer(ptr(0));
        fns.rI(listChangesCtor, outerList, noArgs, exc3);
        var addArg2 = Memory.alloc(Process.pointerSize);
        addArg2.writePointer(ptcInst);
        var exc4 = Memory.alloc(Process.pointerSize); exc4.writePointer(ptr(0));
        fns.rI(listChangesAdd, outerList, addArg2, exc4);

        var setArgs = Memory.alloc(Process.pointerSize);
        setArgs.writePointer(outerList);
        var excF = Memory.alloc(Process.pointerSize); excF.writePointer(ptr(0));
        var ret = fns.rI(setMethod, ptr(serviceInstanceStr), setArgs, excF);
        if (!excF.readPointer().isNull()) {
            var k = excF.readPointer().readPointer();
            return {ok:false, err:"exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString()};
        }
        return {ok:true, ret: ret.toString()};
    },

    /* BULK: build a multi-item List<PokemonTagChanges>, call SetPokemonTags ONCE. */
    bulkTagMany: function(serviceInstanceStr, tagProtoStr, pokemonProtoArray) {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var objNew = new NativeFunction(bind.il2cpp_object_new,'pointer',['pointer']);
        var classFromType = new NativeFunction(bind.il2cpp_class_from_type,'pointer',['pointer']);

        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var gameImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-game.dll") { gameImage = img; break; }
        }
        var ptcClass = fns.cFN(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
            Memory.allocUtf8String("PokemonTagChanges"));

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, setMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "SetPokemonTags") { setMethod = m; break; }
        }
        var listChangesClass = classFromType(fns.mGP(setMethod, 0));

        var cGF = new NativeFunction(bind.il2cpp_class_get_fields,'pointer',['pointer','pointer']);
        var fGN = new NativeFunction(bind.il2cpp_field_get_name,'pointer',['pointer']);
        var fGT = new NativeFunction(bind.il2cpp_field_get_type,'pointer',['pointer']);
        var fIter = Memory.alloc(Process.pointerSize); fIter.writePointer(ptr(0));
        var f, listProtoClass = null;
        while ((f = cGF(ptcClass, fIter)) && !f.isNull()) {
            if (fGN(f).readCString() === "TagsToAdd") { listProtoClass = classFromType(fGT(f)); break; }
        }

        function findMethod(klass, name, paramCount) {
            var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
            var mm;
            while ((mm = fns.cGM(klass, it)) && !mm.isNull()) {
                if (fns.mGN(mm).readCString() === name && fns.mGPC(mm) === paramCount) return mm;
            }
            return null;
        }
        var listProtoCtor = findMethod(listProtoClass, ".ctor", 0);
        var listProtoAdd = findMethod(listProtoClass, "Add", 1);
        var listChangesCtor = findMethod(listChangesClass, ".ctor", 0);
        var listChangesAdd = findMethod(listChangesClass, "Add", 1);

        var noArgs = Memory.alloc(8);

        // Build outer List<PokemonTagChanges>
        var outerList = objNew(listChangesClass);
        var exc0 = Memory.alloc(Process.pointerSize); exc0.writePointer(ptr(0));
        fns.rI(listChangesCtor, outerList, noArgs, exc0);
        if (!exc0.readPointer().isNull()) return {ok:false, err:"outer ctor exc"};

        // For each pokemon: build inner List<PokemonTagProto> + PokemonTagChanges, add to outer
        var built = 0;
        for (var i = 0; i < pokemonProtoArray.length; i++) {
            var protoPtr = ptr(pokemonProtoArray[i]);
            var innerList = objNew(listProtoClass);
            var excA = Memory.alloc(Process.pointerSize); excA.writePointer(ptr(0));
            fns.rI(listProtoCtor, innerList, noArgs, excA);
            if (!excA.readPointer().isNull()) continue;

            var addArg = Memory.alloc(Process.pointerSize);
            addArg.writePointer(ptr(tagProtoStr));
            var excB = Memory.alloc(Process.pointerSize); excB.writePointer(ptr(0));
            fns.rI(listProtoAdd, innerList, addArg, excB);
            if (!excB.readPointer().isNull()) continue;

            var ptcInst = objNew(ptcClass);
            ptcInst.add(0x10).writePointer(protoPtr);
            ptcInst.add(0x18).writePointer(innerList);
            ptcInst.add(0x20).writePointer(ptr(0));

            var addArgC = Memory.alloc(Process.pointerSize);
            addArgC.writePointer(ptcInst);
            var excC = Memory.alloc(Process.pointerSize); excC.writePointer(ptr(0));
            fns.rI(listChangesAdd, outerList, addArgC, excC);
            if (!excC.readPointer().isNull()) continue;
            built++;
        }

        // Invoke SetPokemonTags(outerList)
        var setArgs = Memory.alloc(Process.pointerSize);
        setArgs.writePointer(outerList);
        var excF = Memory.alloc(Process.pointerSize); excF.writePointer(ptr(0));
        var ret = fns.rI(setMethod, ptr(serviceInstanceStr), setArgs, excF);
        if (!excF.readPointer().isNull()) {
            var k = excF.readPointer().readPointer();
            return {ok:false, err:"SetPokemonTags exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString(), built: built};
        }
        return {ok:true, ret: ret.toString(), built: built, requested: pokemonProtoArray.length};
    },

    /* ATOMIC BULK CHANGES: changesArray = [{proto:"0x..", add:["tagProto",..],
       remove:["tagProto",..]}, ..] -> ONE List<PokemonTagChanges> where each item
       carries its OWN TagsToAdd + TagsToRemove -> ONE SetPokemonTags call. This
       collapses an entire multi-tag sync (every add AND every removal across all
       tags) into 1 RPC per batch, instead of one-per-removal (bulkUntagOne) plus
       one-per-100-add (bulkTagMany). Field configs reuse the two PROVEN paths:
       populated TagsToAdd + null TagsToRemove = bulkTagMany; empty(capacity-ctor)
       TagsToAdd + populated TagsToRemove = bulkUntagOne; the both-populated case
       just combines the two independently-proven fields. */
    bulkApplyChanges: function(serviceInstanceStr, changesArray) {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var objNew = new NativeFunction(bind.il2cpp_object_new,'pointer',['pointer']);
        var classFromType = new NativeFunction(bind.il2cpp_class_from_type,'pointer',['pointer']);

        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var gameImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-game.dll") { gameImage = img; break; }
        }
        var ptcClass = fns.cFN(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
            Memory.allocUtf8String("PokemonTagChanges"));

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, setMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "SetPokemonTags") { setMethod = m; break; }
        }
        if (!setMethod) return {ok:false, err:"no SetPokemonTags"};
        var listChangesClass = classFromType(fns.mGP(setMethod, 0));

        var cGF = new NativeFunction(bind.il2cpp_class_get_fields,'pointer',['pointer','pointer']);
        var fGN = new NativeFunction(bind.il2cpp_field_get_name,'pointer',['pointer']);
        var fGT = new NativeFunction(bind.il2cpp_field_get_type,'pointer',['pointer']);
        var fIter = Memory.alloc(Process.pointerSize); fIter.writePointer(ptr(0));
        var f, listProtoClass = null;
        while ((f = cGF(ptcClass, fIter)) && !f.isNull()) {
            if (fGN(f).readCString() === "TagsToAdd") { listProtoClass = classFromType(fGT(f)); break; }
        }
        if (!listProtoClass) return {ok:false, err:"no TagsToAdd field"};

        function findMethod(klass, name, paramCount) {
            var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
            var mm;
            while ((mm = fns.cGM(klass, it)) && !mm.isNull()) {
                if (fns.mGN(mm).readCString() === name && fns.mGPC(mm) === paramCount) return mm;
            }
            return null;
        }
        var listProtoCtor = findMethod(listProtoClass, ".ctor", 0);
        var listProtoCtorCap = findMethod(listProtoClass, ".ctor", 1);
        var listProtoAdd = findMethod(listProtoClass, "Add", 1);
        var listChangesCtor = findMethod(listChangesClass, ".ctor", 0);
        var listChangesAdd = findMethod(listChangesClass, "Add", 1);
        if (!listProtoCtor || !listProtoAdd || !listChangesCtor || !listChangesAdd)
            return {ok:false, err:"missing methods", lpc:!!listProtoCtor, lpa:!!listProtoAdd, lcc:!!listChangesCtor, lca:!!listChangesAdd};
        var noArgs = Memory.alloc(8);

        function makeList(tagProtos) {           // populated List<PokemonTagProto>
            var lst = objNew(listProtoClass);
            var e1 = Memory.alloc(Process.pointerSize); e1.writePointer(ptr(0));
            fns.rI(listProtoCtor, lst, noArgs, e1);
            for (var t = 0; t < tagProtos.length; t++) {
                var aArg = Memory.alloc(Process.pointerSize); aArg.writePointer(ptr(tagProtos[t]));
                var e2 = Memory.alloc(Process.pointerSize); e2.writePointer(ptr(0));
                fns.rI(listProtoAdd, lst, aArg, e2);
            }
            return lst;
        }
        function makeEmptyList() {                // empty list w/ _items initialized (capacity ctor)
            var lst = objNew(listProtoClass);
            if (listProtoCtorCap) {
                var capBuf = Memory.alloc(4); capBuf.writeS32(0);
                var capArgs = Memory.alloc(Process.pointerSize); capArgs.writePointer(capBuf);
                var e = Memory.alloc(Process.pointerSize); e.writePointer(ptr(0));
                fns.rI(listProtoCtorCap, lst, capArgs, e);
            } else {
                var e = Memory.alloc(Process.pointerSize); e.writePointer(ptr(0));
                fns.rI(listProtoCtor, lst, noArgs, e);
            }
            return lst;
        }

        var outerList = objNew(listChangesClass);
        var exc0 = Memory.alloc(Process.pointerSize); exc0.writePointer(ptr(0));
        fns.rI(listChangesCtor, outerList, noArgs, exc0);
        if (!exc0.readPointer().isNull()) return {ok:false, err:"outer ctor exc"};

        var built = 0, skipped = 0, mismatched = [];
        for (var i = 0; i < changesArray.length; i++) {
            var rec = changesArray[i];
            var adds = rec.add || [];
            var rems = rec.remove || [];
            if (adds.length === 0 && rems.length === 0) { skipped++; continue; }
            // a change that names its uid is written only through a pointer that is STILL that mon (protoStillIs)
            if (rec.uid !== undefined && rec.uid !== null && !protoStillIs(rec.proto, rec.uid)) {
                skipped++; mismatched.push(String(rec.uid)); continue;
            }

            var addList = adds.length ? makeList(adds) : makeEmptyList();
            var remPtr  = rems.length ? makeList(rems) : ptr(0);   // null remove = proven bulkTagMany config

            var ptcInst = objNew(ptcClass);
            ptcInst.add(0x10).writePointer(ptr(rec.proto));
            ptcInst.add(0x18).writePointer(addList);
            ptcInst.add(0x20).writePointer(remPtr);

            var aC = Memory.alloc(Process.pointerSize); aC.writePointer(ptcInst);
            var eC = Memory.alloc(Process.pointerSize); eC.writePointer(ptr(0));
            fns.rI(listChangesAdd, outerList, aC, eC);
            if (!eC.readPointer().isNull()) { skipped++; continue; }
            built++;
        }

        var setArgs = Memory.alloc(Process.pointerSize);
        setArgs.writePointer(outerList);
        var excF = Memory.alloc(Process.pointerSize); excF.writePointer(ptr(0));
        var ret = fns.rI(setMethod, ptr(serviceInstanceStr), setArgs, excF);
        if (!excF.readPointer().isNull()) {
            var k = excF.readPointer().readPointer();
            return {ok:false, err:"SetPokemonTags exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString(), built: built};
        }
        // THE SERVER'S ANSWER (H02-2, 2026-09-29): SetPokemonTags returns the RPC's promise. A GC handle on it lets the caller
        // wait for the server's reply (promiseState / promiseFree below, order_tags' proven pattern) instead of reading
        // "the managed call did not throw" as "the server took it".
        var ph = null;
        try { if (!ret.isNull()) ph = _GH().ghNew(ret, 0).toString(); } catch (e) { ph = null; }
        return {ok:true, ret: ret.toString(), built: built, skipped: skipped, requested: changesArray.length, mismatched: mismatched,
                promise: ph};
    },

    /* FULL PIPELINE: build a 1-item List<PokemonTagChanges>, call SetPokemonTags. */
    bulkTagSingle: function(serviceInstanceStr, pokemonProtoStr, tagProtoStr) {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var objNew = new NativeFunction(bind.il2cpp_object_new,'pointer',['pointer']);
        var classFromType = new NativeFunction(bind.il2cpp_class_from_type,'pointer',['pointer']);

        // Resolve images
        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var gameImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-game.dll") { gameImage = img; break; }
        }

        var ptcClass = fns.cFN(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
            Memory.allocUtf8String("PokemonTagChanges"));

        // Get SetPokemonTags + its List<PokemonTagChanges> param type
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, setMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "SetPokemonTags") { setMethod = m; break; }
        }
        var listChangesType = fns.mGP(setMethod, 0);
        var listChangesClass = classFromType(listChangesType);

        // Find PokemonTagChanges.TagsToAdd field type → List<PokemonTagProto> class
        var cGF = new NativeFunction(bind.il2cpp_class_get_fields,'pointer',['pointer','pointer']);
        var fGN = new NativeFunction(bind.il2cpp_field_get_name,'pointer',['pointer']);
        var fGT = new NativeFunction(bind.il2cpp_field_get_type,'pointer',['pointer']);
        var fIter = Memory.alloc(Process.pointerSize); fIter.writePointer(ptr(0));
        var f, listProtoClass = null;
        while ((f = cGF(ptcClass, fIter)) && !f.isNull()) {
            if (fGN(f).readCString() === "TagsToAdd") {
                listProtoClass = classFromType(fGT(f));
                break;
            }
        }
        if (!listProtoClass) return {ok:false, err:"no TagsToAdd field"};

        // Find ctors and Add methods
        function findMethod(klass, name, paramCount) {
            var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
            var mm;
            while ((mm = fns.cGM(klass, it)) && !mm.isNull()) {
                if (fns.mGN(mm).readCString() === name && fns.mGPC(mm) === paramCount) return mm;
            }
            return null;
        }

        var listProtoCtor = findMethod(listProtoClass, ".ctor", 0);
        var listProtoAdd = findMethod(listProtoClass, "Add", 1);
        var listChangesCtor = findMethod(listChangesClass, ".ctor", 0);
        var listChangesAdd = findMethod(listChangesClass, "Add", 1);
        if (!listProtoCtor || !listProtoAdd || !listChangesCtor || !listChangesAdd) {
            return {ok:false, err:"missing methods", lpc:!!listProtoCtor, lpa:!!listProtoAdd, lcc:!!listChangesCtor, lca:!!listChangesAdd};
        }

        // 1. Allocate inner List<PokemonTagProto>, ctor, Add(tagProto)
        var innerList = objNew(listProtoClass);
        var noArgs = Memory.alloc(8);  // dummy 8-byte buf for "no args"
        var exc1 = Memory.alloc(Process.pointerSize); exc1.writePointer(ptr(0));
        fns.rI(listProtoCtor, innerList, noArgs, exc1);
        if (!exc1.readPointer().isNull()) {
            var k = exc1.readPointer().readPointer();
            return {ok:false, err:"innerList ctor exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString()};
        }
        var addArg1 = Memory.alloc(Process.pointerSize);
        addArg1.writePointer(ptr(tagProtoStr));
        var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
        fns.rI(listProtoAdd, innerList, addArg1, exc2);
        if (!exc2.readPointer().isNull()) {
            var k = exc2.readPointer().readPointer();
            return {ok:false, err:"innerList Add exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString()};
        }

        // 2. Allocate PokemonTagChanges, set fields
        var ptcInst = objNew(ptcClass);
        ptcInst.add(0x10).writePointer(ptr(pokemonProtoStr));
        ptcInst.add(0x18).writePointer(innerList);
        ptcInst.add(0x20).writePointer(ptr(0));  // TagsToRemove = empty/null

        // 3. Allocate outer List<PokemonTagChanges>, ctor, Add(ptcInst)
        var outerList = objNew(listChangesClass);
        var exc3 = Memory.alloc(Process.pointerSize); exc3.writePointer(ptr(0));
        fns.rI(listChangesCtor, outerList, noArgs, exc3);
        if (!exc3.readPointer().isNull()) return {ok:false, err:"outerList ctor exc"};
        var addArg2 = Memory.alloc(Process.pointerSize);
        addArg2.writePointer(ptcInst);
        var exc4 = Memory.alloc(Process.pointerSize); exc4.writePointer(ptr(0));
        fns.rI(listChangesAdd, outerList, addArg2, exc4);
        if (!exc4.readPointer().isNull()) return {ok:false, err:"outerList Add exc"};

        // 4. Call SetPokemonTags(outerList)
        var setArgs = Memory.alloc(Process.pointerSize);
        setArgs.writePointer(outerList);
        var exc5 = Memory.alloc(Process.pointerSize); exc5.writePointer(ptr(0));
        var ret = fns.rI(setMethod, ptr(serviceInstanceStr), setArgs, exc5);
        if (!exc5.readPointer().isNull()) {
            var k = exc5.readPointer().readPointer();
            return {ok:false, err:"SetPokemonTags exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString()};
        }
        return {ok:true, ret: ret.toString(), innerList: innerList.toString(), outerList: outerList.toString(), ptcInst: ptcInst.toString()};
    },

    /* Test: just call SetPokemonTags(null) to see what happens. */
    setPokemonTagsNull: function(serviceInstanceStr) {
        if (!init()) return {ok:false, err:state.err};
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, setMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "SetPokemonTags") { setMethod = m; break; }
        }
        if (!setMethod) return {ok:false, err:"no method"};

        var args = Memory.alloc(Process.pointerSize);
        args.writePointer(ptr(0));  // null list
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(setMethod, ptr(serviceInstanceStr), args, exc);
        if (!exc.readPointer().isNull()) {
            var k = exc.readPointer().readPointer();
            return {ok:false, err:"exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString()};
        }
        return {ok:true, ret: ret.toString()};
    },

    /* Get List<PokemonTagChanges> klass from SetPokemonTags's param type. */
    getListClassForSetTags: function() {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var typeGetClass = new NativeFunction(bind.il2cpp_class_from_type,'pointer',['pointer']);

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, setMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "SetPokemonTags") { setMethod = m; break; }
        }
        if (!setMethod) return {ok:false, err:"no method"};

        var paramType = fns.mGP(setMethod, 0);
        var listKlass = typeGetClass(paramType);
        var ns = fns.cGNs(listKlass).readCString();
        var name = fns.cN(listKlass).readCString();
        return {ok:true, listKlass: listKlass.toString(), klassName: ns + "." + name};
    },

    /* Build and invoke SetPokemonTags - test with one pokemon, one tag. */
    bulkTagOne: function(serviceInstanceStr, pokemonProtoStr, tagProtoStr) {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();
        var objNew = new NativeFunction(bind.il2cpp_object_new,'pointer',['pointer']);
        var classFromName = fns.cFN;
        var inflateGen = bind.il2cpp_class_inflate_generic_class;
        var typeGetClass = bind.il2cpp_type_get_class_or_element_class;

        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var gameImage = null, mscorlib = null, protoImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            var nm = fns.iGN(img).readCString();
            if (nm === "holo-game.dll") gameImage = img;
            if (nm === "mscorlib.dll") mscorlib = img;
            if (nm === "holo-protos.dll") protoImage = img;
        }

        // Resolve classes
        var ptcClass = classFromName(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
            Memory.allocUtf8String("PokemonTagChanges"));
        var ptpClass = classFromName(protoImage,
            Memory.allocUtf8String("Holoholo.Rpc"),
            Memory.allocUtf8String("PokemonTagProto"));
        if (!ptcClass || ptcClass.isNull()) return {ok:false, err:"no PokemonTagChanges class"};

        // 1. Find a List<PokemonTagProto> instance somewhere in heap to use as template
        // Scan for List<T> klass pattern - look for lists with TagsToAdd-shaped contents.
        // ALTERNATIVE: just allocate raw memory pretending to be a minimal list.
        // Actually - construct a List<PokemonTagProto> via the inflated generic.

        // SIMPLEST PATH: allocate PokemonTagChanges, set PokemonProto field,
        // allocate List<PokemonTagProto> via il2cpp_object_new on its inflated class.
        // To find inflated class: scan heap for existing instances OR use heap-walker.

        // Try: scan heap for any object whose klass name matches "List`1<PokemonTagProto>"
        // First, just allocate PokemonTagChanges as a smoke test.
        var ptcInstance = objNew(ptcClass);
        if (ptcInstance.isNull()) return {ok:false, err:"PokemonTagChanges new failed"};

        // Set PokemonProto field
        ptcInstance.add(0x10).writePointer(ptr(pokemonProtoStr));

        // For TagsToAdd: try writing the tag proto directly as a singleton "list"
        // (this might not work since it expects List<>, but try)
        // Allocate a tiny memory region pretending to be a List<>
        // C# List<T> layout: klass@+0, monitor@+8, items_array@+0x10, count@+0x18

        // Find a List<PokemonTagProto> instance in heap to copy as template
        var listMatch = null;
        // Search heap for any List<> with PokemonTagProto klass referenced...
        // Skip for now - just leave TagsToAdd null and see what SetPokemonTags does
        ptcInstance.add(0x18).writePointer(ptr(0));
        ptcInstance.add(0x20).writePointer(ptr(0));

        // Now build a List<PokemonTagChanges> for SetPokemonTags(list)
        // Same problem - need List<> class. Let me look at the captured 0x71bed7fe80
        // If we can call any method that returns List<PokemonTagChanges>, we get a template

        // Or - try invoking SetPokemonTags with a simple POKEMON-LESS setup just to see what happens
        return {ok:true, msg:"PokemonTagChanges allocated at " + ptcInstance.toString() +
                "; List construction is the next step", ptcInstance: ptcInstance.toString()};
    },

    /* Probe PokemonTagChanges class fields via il2cpp_class_get_fields. */
    probePokemonTagChangesFields: function() {
        if (!init()) return {ok:false, err:state.err};
        var bind = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name.indexOf("il2cpp_") === 0) exp[e.name] = e.address;
            });
            return exp;
        })();

        var cGF = bind.il2cpp_class_get_fields ? new NativeFunction(bind.il2cpp_class_get_fields,'pointer',['pointer','pointer']) : null;
        var fGN = bind.il2cpp_field_get_name ? new NativeFunction(bind.il2cpp_field_get_name,'pointer',['pointer']) : null;
        var fGT = bind.il2cpp_field_get_type ? new NativeFunction(bind.il2cpp_field_get_type,'pointer',['pointer']) : null;
        var fGO = bind.il2cpp_field_get_offset ? new NativeFunction(bind.il2cpp_field_get_offset,'uint32',['pointer']) : null;
        if (!cGF || !fGN || !fGT || !fGO) return {ok:false, err:"missing field exports"};

        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var gameImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-game.dll") { gameImage = img; break; }
        }
        var ptcClass = fns.cFN(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
            Memory.allocUtf8String("PokemonTagChanges"));

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var f, fields = [];
        while ((f = cGF(ptcClass, iter)) && !f.isNull()) {
            try {
                var fieldName = fGN(f).readCString();
                var fieldType = fns.tGN(fGT(f)).readCString();
                var fieldOffset = fGO(f);
                fields.push({name: fieldName, type: fieldType, offset: '0x' + fieldOffset.toString(16)});
            } catch(e) { fields.push({err: e.message}); }
        }
        return {ok:true, klass: ptcClass.toString(), fields: fields};
    },

    /* Probe PokemonTagChanges class - find its constructor + fields. */
    probePokemonTagChanges: function() {
        if (!init()) return {ok:false, err:state.err};
        var sp = Memory.alloc(4);
        var asms = fns.dGA(fns.dG(), sp);
        var na = sp.readS32();
        var gameImage = null;
        for (var a = 0; a < na; a++) {
            var img = fns.aGI(asms.add(a*Process.pointerSize).readPointer());
            if (fns.iGN(img).readCString() === "holo-game.dll") { gameImage = img; break; }
        }
        if (!gameImage) return {ok:false, err:"no holo-game"};

        var ptcClass = fns.cFN(gameImage,
            Memory.allocUtf8String("Niantic.Holoholo.Tagging"),
            Memory.allocUtf8String("PokemonTagChanges"));
        if (!ptcClass || ptcClass.isNull()) return {ok:false, err:"PokemonTagChanges class not found"};

        // List methods
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, methods = [];
        while ((m = fns.cGM(ptcClass, iter)) && !m.isNull()) {
            try {
                var name = fns.mGN(m).readCString();
                var pc = fns.mGPC(m);
                var params = [];
                for (var i = 0; i < pc; i++) {
                    var pt = fns.mGP(m, i);
                    if (pt && !pt.isNull()) params.push(fns.tGN(pt).readCString());
                }
                methods.push({name: name, params: params, ptr: m.toString()});
            } catch(e) {}
        }
        return {ok:true, klass: ptcClass.toString(), methods: methods};
    },

    /* AddTag on a SPECIFIC instance pointer (the real one we captured). */
    addTagOnInstance: function(instanceStr, name, colorInt) {
        if (!init()) return {ok:false, err:state.err};
        var inst = ptr(instanceStr);

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, addTag = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "AddTag" && fns.mGPC(m) === 2) { addTag = m; break; }
        }
        if (!addTag) return {ok:false, err:"no AddTag"};

        var sN = (function() {
            var exp = {};
            Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name === "il2cpp_string_new") exp[e.name] = e.address;
            });
            return new NativeFunction(exp.il2cpp_string_new, 'pointer', ['pointer']);
        })();

        var nameStr = sN(Memory.allocUtf8String(name));
        var colorBuf = Memory.alloc(4); colorBuf.writeS32(colorInt);
        var args = Memory.alloc(2 * Process.pointerSize);
        args.writePointer(nameStr);
        args.add(Process.pointerSize).writePointer(colorBuf);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(addTag, inst, args, exc);
        if (!exc.readPointer().isNull()) {
            var k = exc.readPointer().readPointer();
            return {ok:false, err:"exc", excClass: fns.cGNs(k).readCString() + "." + fns.cN(k).readCString()};
        }
        return {ok:true, ret: ret.toString()};
    },

    /* Enumerate ALL tags via GetCachedTagToPokemonBindingForIndex on real instance. */
    listAllTags: function(instanceStr) {
        if (!init()) return {ok:false, err:state.err};
        var inst = ptr(instanceStr);

        // Find methods
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount=null, getBinding=null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            var name = fns.mGN(m).readCString();
            if (name === "get_NumberOfTags") getCount = m;
            if (name === "GetCachedTagToPokemonBindingForIndex") getBinding = m;
        }
        if (!getCount || !getBinding) return {ok:false, err:"missing methods"};

        // Get count via boxed int
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = fns.rI(getCount, inst, ptr(0), exc);
        if (!exc.readPointer().isNull()) return {ok:false, err:"count exc"};
        var count = ret.add(0x10).readS32();
        send({type:"status", msg:"Total tags: " + count});

        var tags = [];
        for (var i = 0; i < count; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize);
            args.writePointer(idxBuf);
            var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
            try {
                var bindingPtr = fns.rI(getBinding, inst, args, exc2);
                if (!exc2.readPointer().isNull()) {
                    tags.push({i:i, err:"exc"});
                    continue;
                }
                if (bindingPtr.isNull()) { tags.push({i:i, err:"null"}); continue; }

                // Walk binding fields - probe offsets 0x00 to 0x40 looking for strings
                var bindingInfo = {i:i, addr: bindingPtr.toString()};
                try {
                    var klass = bindingPtr.readPointer();
                    bindingInfo.klassName = fns.cGNs(klass).readCString() + "." + fns.cN(klass).readCString();
                } catch(e) {}

                // Probe field offsets for object pointers and try to read C# strings
                var fields = [];
                for (var off = 0x10; off <= 0x40; off += 8) {
                    try {
                        var fp = bindingPtr.add(off).readPointer();
                        if (fp.isNull()) continue;
                        var fInfo = {off:'0x'+off.toString(16), ptr:fp.toString()};
                        // Try as C# string: vtable@+0, monitor@+8, length@+0x10, chars@+0x14 (UTF-16)
                        try {
                            var len = fp.add(0x10).readS32();
                            if (len > 0 && len < 200) {
                                var chars = [];
                                for (var ci = 0; ci < len; ci++)
                                    chars.push(String.fromCharCode(fp.add(0x14 + ci*2).readU16()));
                                var s = chars.join('');
                                if (/^[\x20-\x7e]+$/.test(s)) fInfo.asString = s;
                            }
                        } catch(e) {}
                        // Try as integer
                        try { fInfo.asInt = bindingPtr.add(off).readS64().toString(); } catch(e) {}
                        // Try nested object - read its klass
                        try {
                            var nestKlass = fp.readPointer();
                            var nestName = fns.cGNs(nestKlass).readCString() + "." + fns.cN(nestKlass).readCString();
                            if (nestName.indexOf("Niantic") >= 0 || nestName.indexOf("Holoholo") >= 0) {
                                fInfo.nestedKlass = nestName;
                                // Probe nested object DEEPLY for strings
                                for (var noff = 0; noff <= 0x80; noff += 8) {
                                    try {
                                        var fp2 = fp.add(noff).readPointer();
                                        if (fp2.isNull()) continue;
                                        var len2 = fp2.add(0x10).readS32();
                                        if (len2 > 0 && len2 < 100) {
                                            var chars2 = [];
                                            for (var ci2 = 0; ci2 < len2; ci2++)
                                                chars2.push(String.fromCharCode(fp2.add(0x14 + ci2*2).readU16()));
                                            var s2 = chars2.join('');
                                            if (/^[\x20-\x7e]+$/.test(s2) && s2.length > 0) {
                                                fInfo['nested_str_+0x' + noff.toString(16)] = s2;
                                            }
                                        }
                                    } catch(e) {}
                                }
                                // Also dump int values at fixed nested offsets
                                for (var noff2 = 0x18; noff2 <= 0x40; noff2 += 8) {
                                    try {
                                        var v = fp.add(noff2).readS64();
                                        if (v != 0) fInfo['nested_int_+0x' + noff2.toString(16)] = v.toString();
                                    } catch(e) {}
                                }
                            }
                        } catch(e) {}
                        fields.push(fInfo);
                    } catch(e) {}
                }
                bindingInfo.fields = fields;
                tags.push(bindingInfo);
            } catch(e) {
                tags.push({i:i, err:e.message});
            }
        }
        return {ok:true, count: count, tags: tags};
    },

    /* Validate a candidate instance: check klass + call get_NumberOfTags. */
    validateInstance: function(ptrStr) {
        if (!init()) return {ok:false, err:state.err};
        var inst = ptr(ptrStr);
        var report = {addr: ptrStr};
        try {
            var klass = inst.readPointer();
            report.klass = klass.toString();
            report.expectedKlass = taggingServiceClass.toString();
            report.klassMatches = (klass.toString() === taggingServiceClass.toString());
            try {
                var ns = fns.cGNs(klass).readCString();
                var nm = fns.cN(klass).readCString();
                report.klassName = ns + "." + nm;
            } catch(e) { report.klassErr = e.message; }
        } catch(e) { report.readErr = e.message; }

        // Try get_NumberOfTags
        try {
            var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
            var m, getCount = null;
            while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
                if (fns.mGN(m).readCString() === "get_NumberOfTags") { getCount = m; break; }
            }
            if (getCount) {
                var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
                var ret = fns.rI(getCount, inst, ptr(0), exc);
                if (exc.readPointer().isNull()) {
                    // Boxed int return: ptr -> {vtable@+0, monitor@+8, int@+0x10}
                    report.retPtr = ret.toString();
                    if (!ret.isNull()) {
                        try { report.boxedInt = ret.add(0x10).readS32(); } catch(e) {}
                        try { report.directInt = ret.toInt32(); } catch(e) {}
                    }
                } else {
                    report.invokeExc = "yes";
                }
            }
        } catch(e) { report.invokeErr = e.message; }
        return report;
    },

    /* Probe MethodInfo struct layout - find offset of native code pointer. */
    probeMethodInfo: function() {
        if (!init()) return {ok:false, err:state.err};
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "get_NumberOfTags") { getCount = m; break; }
        }
        if (!getCount) return {ok:false, err:"no method"};

        var probe = {methodInfo: getCount.toString(), offsets: []};
        for (var off = 0; off <= 0x40; off += 8) {
            try {
                var p = getCount.add(off).readPointer();
                var info = "+0x" + off.toString(16) + " = " + p.toString();
                // Check if it's in an executable region
                try {
                    var range = Process.findRangeByAddress(p);
                    if (range) info += " " + range.protection + " " + (range.file ? range.file.path : "anon");
                } catch(e) {}
                probe.offsets.push(info);
            } catch(e) { probe.offsets.push("+0x" + off.toString(16) + " err"); }
        }
        return probe;
    },

    /* Hook MULTIPLE TaggingRpcService methods. ANY UI interaction with tags fires SOMETHING. */
    hookForRealInstance: function(durationSec) {
        if (!init()) return {ok:false, err:state.err};

        // Hook EVERY method on the class - we want to know which fire during user actions
        var TARGET_METHODS = null;  // null = hook all

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, hookedCount = 0;
        var hookNames = [];
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            var name = fns.mGN(m).readCString();
            if (TARGET_METHODS === null || TARGET_METHODS.indexOf(name) >= 0) {
                try {
                    var nativeAddr = m.readPointer();
                    var capturedName = name;  // closure capture
                    Interceptor.attach(nativeAddr, {
                        onEnter: function(args) {
                            var thisPtr = args[0].toString();
                            if (!capturedThisPointers[thisPtr]) {
                                capturedThisPointers[thisPtr] = {count:0, methods:{}};
                                send({type:"status", msg:"captured this @ " + thisPtr + " via " + capturedName});
                            }
                            capturedThisPointers[thisPtr].count++;
                            capturedThisPointers[thisPtr].methods[capturedName] = (capturedThisPointers[thisPtr].methods[capturedName] || 0) + 1;

                            // Capture SetPokemonTags args - the List<PokemonTagChanges>
                            if (capturedName === "SetPokemonTags" && !capturedSetPokemonTagsArgs) {
                                capturedSetPokemonTagsArgs = {
                                    thisPtr: args[0].toString(),
                                    listPtr: args[1].toString()
                                };
                                send({type:"status", msg:"captured SetPokemonTags args: this=" + args[0] + " list=" + args[1]});
                            }
                            // Capture AddTag args
                            if (capturedName === "AddTag" && !capturedAddTagArgs) {
                                capturedAddTagArgs = {
                                    thisPtr: args[0].toString(),
                                    nameStrPtr: args[1].toString(),
                                    colorPtr: args[2].toString()
                                };
                                send({type:"status", msg:"captured AddTag args: name=" + args[1] + " color=" + args[2]});
                            }
                        }
                    });
                    hookedCount++;
                    hookNames.push(name);
                } catch(e) { send({type:"status", msg:"hook fail " + name + ": " + e.message}); }
            }
        }
        return {ok:true, hookedCount: hookedCount, methods: hookNames};
    },

    getCaptured: function() {
        return {ok:true, captured: capturedThisPointers, setPokemonTagsArgs: capturedSetPokemonTagsArgs, addTagArgs: capturedAddTagArgs};
    },

    /* Dump the captured List<PokemonTagChanges> structure so we know the layout. */
    dumpCapturedList: function() {
        if (!capturedSetPokemonTagsArgs) return {ok:false, err:"no SetPokemonTags captured yet"};
        var listPtr = ptr(capturedSetPokemonTagsArgs.listPtr);
        var dump = {addr: capturedSetPokemonTagsArgs.listPtr};
        try { dump.klass = listPtr.readPointer().toString(); } catch(e) {}
        // C# List<T>: klass@+0, monitor@+8, items_array@+0x10, count@+0x18, _version@+0x1c
        for (var off = 0; off <= 0x40; off += 4) {
            try {
                var v32 = listPtr.add(off).readS32();
                var v64 = listPtr.add(off).readS64().toString();
                if (v32 != 0) dump['+0x' + off.toString(16) + '_i32'] = v32;
                if (v64 != "0" && v64.length < 20) dump['+0x' + off.toString(16) + '_i64'] = v64;
            } catch(e) {}
        }
        // List items array typically at +0x10
        try {
            var itemsArr = listPtr.add(0x10).readPointer();
            dump.itemsArr = itemsArr.toString();
            dump.itemsCount = listPtr.add(0x18).readS32();
            // Array layout: klass@+0, monitor@+8, length@+0x10, items[0]@+0x20
            if (!itemsArr.isNull()) {
                var arrLen = itemsArr.add(0x18).readS32();
                dump.arrLen = arrLen;
                // First few elements (PokemonTagChanges structs or ptrs)
                var elems = [];
                for (var i = 0; i < Math.min(3, dump.itemsCount); i++) {
                    var elemAddr = itemsArr.add(0x20 + i*Process.pointerSize);
                    var elemPtr = elemAddr.readPointer();
                    var e = {i:i, addr:elemAddr.toString(), ptr:elemPtr.toString()};
                    // Dump PokemonTagChanges contents
                    if (!elemPtr.isNull()) {
                        try { e.klass = elemPtr.readPointer().toString(); } catch(_){}
                        var elemFields = {};
                        for (var off2 = 0; off2 <= 0x40; off2 += 8) {
                            try {
                                var pv = elemPtr.add(off2).readS64().toString();
                                if (pv != "0" && pv.length < 21) elemFields['+0x' + off2.toString(16)] = pv;
                            } catch(_){}
                        }
                        e.fields = elemFields;
                    }
                    elems.push(e);
                }
                dump.elements = elems;
            }
        } catch(e) { dump.parseErr = e.message; }
        return {ok:true, dump:dump};
    },

    /* Scan all klass matches, validate each via boxed-int return.
     * Real instance = boxedInt at ret+0x10 in 0..50 range. */
    findRealInstance: function() {
        if (!init()) return {ok:false, err:state.err};
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "get_NumberOfTags") { getCount = m; break; }
        }
        if (!getCount) return {ok:false, err:"no method"};

        var pat = buildKlassPattern(taggingServiceClass);
        var ranges = [];
        Process.enumerateRanges('rw-').forEach(function(r) {
            if (r.size > 512*1024*1024) return;
            if (r.size < 4096) return;
            ranges.push(r);
        });

        var sane = [];
        var totalMatches = 0;
        for (var ri = 0; ri < ranges.length; ri++) {
            var rs;
            try { rs = Memory.scanSync(ranges[ri].base, ranges[ri].size, pat); }
            catch(e) { continue; }
            for (var k = 0; k < rs.length; k++) {
                totalMatches++;
                var addr = rs[k].address;
                try {
                    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
                    var ret = fns.rI(getCount, addr, ptr(0), exc);
                    if (!exc.readPointer().isNull() || ret.isNull()) continue;
                    var c = ret.add(0x10).readS32();
                    if (c >= 0 && c <= 50) {
                        sane.push({addr: addr.toString(), count: c});
                        if (sane.length >= 5) return {ok:true, totalMatches:totalMatches, sane:sane};
                    }
                } catch(e) {}
            }
        }
        return {ok:true, totalMatches:totalMatches, sane:sane};
    },

    /* Find the REAL TaggingRpcService by enumerating ALL klass matches
     * and probing each with get_NumberOfTags. Real instance returns 0-50; garbage returns nonsense. */
    countTags: function() {
        if (!init()) return {ok:false, err:state.err};
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "get_NumberOfTags") { getCount = m; break; }
        }
        if (!getCount) return {ok:false, err:"no method"};

        // Get ALL matches across ALL heap regions, no maxMatches limit
        var pat = buildKlassPattern(taggingServiceClass);
        var ranges = [];
        Process.enumerateRanges('rw-').forEach(function(r) {
            if (r.size > 256*1024*1024) return;
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
        }
        send({type:"status", msg:"Total klass-pattern matches: " + matches.length});

        var sane = [];
        var insane = 0;
        for (var i = 0; i < matches.length; i++) {
            try {
                var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
                var ret = fns.rI(getCount, matches[i], ptr(0), exc);
                if (exc.readPointer().isNull()) {
                    var c = ret.toInt32();
                    if (c >= 0 && c <= 100) {
                        sane.push({addr: matches[i].toString(), count: c});
                    } else {
                        insane++;
                    }
                } else { insane++; }
            } catch(e) { insane++; }
        }
        return {ok:true, totalMatches: matches.length, sane: sane, insane: insane};
    },

    /* Find ALL TaggingRpcService instances in heap and probe each. */
    findAllInstances: function() {
        if (!init()) return {ok:false, err:state.err};
        var matches = heapScan(taggingServiceClass, "TaggingRpcService", 1000);
        var results = [];
        // Find get_NumberOfTags method
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCountMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "get_NumberOfTags") { getCountMethod = m; break; }
        }
        for (var i = 0; i < matches.length; i++) {
            var inst = matches[i];
            var info = {addr: inst.toString()};
            if (getCountMethod) {
                try {
                    var args = Memory.alloc(0);
                    var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
                    var ret = fns.rI(getCountMethod, inst, args, exc);
                    if (exc.readPointer().isNull()) {
                        // ret is boxed int? or unboxed pointer? for primitive return, check both
                        info.tagCount = ret.toInt32();
                        info.tagCountAlt = ret.readU32();
                    } else {
                        info.exception = "yes";
                    }
                } catch(e) { info.callErr = e.message; }
            }
            results.push(info);
        }
        return {ok:true, instances: results};
    },

    /* Minimal: BEFORE count, ADD tag, AFTER count. Single instance. 3 calls total. */
    addTagVerified: function(name, colorInt) {
        if (!init()) return {ok:false, err:state.err};

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, addTagMethod=null, getCountMethod=null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            var nm = fns.mGN(m).readCString();
            if (nm === "AddTag" && fns.mGPC(m) === 2) addTagMethod = m;
            if (nm === "get_NumberOfTags") getCountMethod = m;
        }
        if (!addTagMethod || !getCountMethod) return {ok:false, err:"missing methods"};

        var inst = findServiceInstance();
        if (!inst) return {ok:false, err:"no instance"};

        var report = {addr: inst.toString()};

        // BEFORE
        try {
            var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
            var ret = fns.rI(getCountMethod, inst, ptr(0), exc);
            report.beforeCount = exc.readPointer().isNull() ? ret.toInt32() : "exc";
        } catch(e) { report.beforeErr = e.message; }

        // ADD
        try {
            var exp = {}; Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                if (e.name === "il2cpp_string_new") exp[e.name] = e.address;
            });
            var sN = new NativeFunction(exp.il2cpp_string_new, 'pointer', ['pointer']);
            var nameStr = sN(Memory.allocUtf8String(name));
            var colorBuf = Memory.alloc(4); colorBuf.writeS32(colorInt);
            var args2 = Memory.alloc(2 * Process.pointerSize);
            args2.writePointer(nameStr);
            args2.add(Process.pointerSize).writePointer(colorBuf);
            var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
            var ret2 = fns.rI(addTagMethod, inst, args2, exc2);
            report.addTagRet = exc2.readPointer().isNull() ? ret2.toString() : "exc";
            // If success, dump fields of the returned object
            if (!exc2.readPointer().isNull()) {
                var k = exc2.readPointer().readPointer();
                report.addTagExc = fns.cGNs(k).readCString() + "." + fns.cN(k).readCString();
            } else if (!ret2.isNull()) {
                // dump a few longs
                report.retDump = [];
                for (var off = 0; off < 0x60; off += 8) {
                    try { report.retDump.push("+0x" + off.toString(16) + ": " + ret2.add(off).readPointer().toString()); }
                    catch(e) {}
                }
            }
        } catch(e) { report.addTagErr = e.message; }

        // AFTER
        try {
            var exc3 = Memory.alloc(Process.pointerSize); exc3.writePointer(ptr(0));
            var ret3 = fns.rI(getCountMethod, inst, ptr(0), exc3);
            report.afterCount = exc3.readPointer().isNull() ? ret3.toInt32() : "exc";
        } catch(e) { report.afterErr = e.message; }

        report.changed = (report.beforeCount !== report.afterCount);
        return {ok:true, report: report};
    },

    /* Dump all tag definitions from the user's account (via TaggingRpcService internal cache).
     * We find the TagCache object on the service and walk its tags. */
    listAllTagDefinitions: function() {
        if (!init()) return {ok:false, err:state.err};
        // Get the service instance, find its TagCache field
        var instance = findServiceInstance();
        if (!instance) return {ok:false, err:"no instance"};

        // Scan the service object's fields - look for pointers that look like a TagCache
        // Service object header: vtable @+0, klass @+8 (typical il2cpp object)
        // Then C# fields at +0x10 and onwards
        var found = [];
        for (var off = 0x10; off <= 0x100; off += 8) {
            try {
                var p = instance.add(off).readPointer();
                if (p.isNull()) continue;
                // Try to read as klass, see if name matches TagCache
                try {
                    var k = p.readPointer();  // potential klass pointer
                    var n = fns.cN(k).readCString();
                    var ns = fns.cGNs(k).readCString();
                    found.push({off: '0x' + off.toString(16), ptr: p.toString(), klassName: ns + "." + n});
                } catch(e) {}
            } catch(e) {}
        }
        return {ok:true, fields: found};
    },

    /* Read PokemonTagProto fields from a pointer (returned by AddTag etc.) */
    readPokemonTagProto: function(ptrStr) {
        if (!init()) return {ok:false, err:state.err};
        var p = ptr(ptrStr);
        var details = {ptr: ptrStr};
        // C# proto messages typically have:
        //   +0  vtable
        //   +8  klass
        //   +0x10... fields
        try { details.klass = p.readPointer().toString(); } catch(e) {}
        // Walk first 8 dwords to dump field-shaped data
        for (var off = 0x10; off <= 0x40; off += 8) {
            try {
                var v_ptr = p.add(off).readPointer();
                var v_i64 = p.add(off).readS64();
                details["off_0x" + off.toString(16) + "_ptr"] = v_ptr.toString();
                details["off_0x" + off.toString(16) + "_i64"] = v_i64.toString();
                // If it's a pointer, try to read it as a string
                try {
                    var len = v_ptr.add(0x10).readS32();
                    if (len > 0 && len < 100) {
                        var charsPtr = v_ptr.add(0x14);
                        var chars = [];
                        for (var i = 0; i < len; i++) chars.push(String.fromCharCode(charsPtr.add(i*2).readU16()));
                        details["off_0x" + off.toString(16) + "_str"] = chars.join('');
                    }
                } catch(e) {}
            } catch(e) {}
        }
        return {ok:true, details: details};
    },

    /* Read-only test: GetAllTags(PokemonProto) - safer than AddTag, just reads tags. */
    getAllTagsTest: function(uidLow, uidHigh) {
        if (!init()) return {ok: false, err: state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();
        var key = uidLow + "," + uidHigh;
        var protoPtr = protoIndex[key];
        if (!protoPtr) return {ok: false, err: "pokemon not in heap index", key: key};

        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getMethod = null;
        while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
            if (fns.mGN(m).readCString() === "GetAllTags") { getMethod = m; break; }
        }
        if (!getMethod) return {ok: false, err: "GetAllTags not found"};

        var instance = findServiceInstance();
        if (!instance) return {ok: false, err: "service instance not found"};

        try {
            var args = Memory.alloc(Process.pointerSize);
            args.writePointer(protoPtr);
            var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
            send({type:"status", msg:"Invoking GetAllTags on proto " + protoPtr});
            var ret = fns.rI(getMethod, instance, args, exc);
            var excPtr = exc.readPointer();
            if (!excPtr.isNull()) {
                var klass = excPtr.readPointer();
                return {ok:false, err:"exc", excClass: fns.cGNs(klass).readCString() + "." + fns.cN(klass).readCString()};
            }
            return {ok: true, ret: ret.toString(), retIsNull: ret.isNull()};
        } catch(e) {
            return {ok:false, err:"JS: " + e.message};
        }
    },

    /* Smoke test: invoke AddTag(string, color) on TaggingRpcService.
     * AddTag(System.String, Holoholo.Rpc.PokemonTagColor) - creates a new tag.
     * Color is an enum int. Returns IPromise<PokemonTagProto> probably.
     */
    addTagTest: function(name, colorInt) {
        if (!init()) return {ok: false, err: state.err};
        try {
            // Find AddTag method
            var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
            var m, addTagMethod = null;
            while ((m = fns.cGM(taggingServiceClass, iter)) && !m.isNull()) {
                if (fns.mGN(m).readCString() === "AddTag" && fns.mGPC(m) === 2) {
                    addTagMethod = m; break;
                }
            }
            if (!addTagMethod) return {ok: false, err: "AddTag method not found"};

            var instance = findServiceInstance();
            if (!instance) return {ok: false, err: "TaggingRpcService instance not found"};
            send({type:"status", msg:"Found service instance @ " + instance});

            // Build args: string name, color int
            var nameStr = (function() {
                var sn = (function(){
                    var exp = {};
                    Process.findModuleByName("libil2cpp.so").enumerateExports().forEach(function(e){
                        if (e.name === "il2cpp_string_new") exp[e.name] = e.address;
                    });
                    return new NativeFunction(exp.il2cpp_string_new, 'pointer', ['pointer']);
                })();
                return sn(Memory.allocUtf8String(name));
            })();

            // PokemonTagColor enum is value type, passed as boxed int or unboxed
            // For IL2CPP, value types are passed by reference of unboxed value
            var colorBuf = Memory.alloc(4); colorBuf.writeS32(colorInt);

            var args = Memory.alloc(2 * Process.pointerSize);
            args.writePointer(nameStr);
            args.add(Process.pointerSize).writePointer(colorBuf);

            var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
            send({type:"status", msg:"Invoking AddTag(" + name + ", color=" + colorInt + ")"});
            var ret = fns.rI(addTagMethod, instance, args, exc);
            var excPtr = exc.readPointer();
            if (!excPtr.isNull()) {
                // Read C# exception details
                var details = {excPtr: excPtr.toString()};
                try {
                    // Exception is a C# object: vtable at +0, klass at +0
                    var klass = excPtr.readPointer();
                    var className = fns.cN(klass).readCString();
                    var ns = fns.cGNs(klass).readCString();
                    details.exceptionClass = ns + "." + className;
                    // Standard exception fields - Message at offset 0x10 typically
                    for (var off = 0x10; off <= 0x40; off += 8) {
                        try {
                            var p = excPtr.add(off).readPointer();
                            if (!p.isNull()) {
                                // C# string: header + length + chars
                                var len = p.add(0x10).readS32();
                                if (len > 0 && len < 500) {
                                    var charsPtr = p.add(0x14);
                                    var chars = [];
                                    for (var i = 0; i < len; i++) chars.push(String.fromCharCode(charsPtr.add(i*2).readU16()));
                                    details["str_at_off_0x" + off.toString(16)] = chars.join('');
                                }
                            }
                        } catch(e) {}
                    }
                } catch(e) { details.readErr = e.message; }
                return {ok: false, err: "exception thrown", details: details};
            }
            return {ok: true, ret: ret.toString()};
        } catch (e) {
            return {ok: false, err: "JS exception: " + e.message + "\n" + e.stack};
        }
    },

    tagOne: function(uidLow, uidHigh, tagIds) {
        if (!init()) return {ok: false, err: state.err};
        if (!protoIndex) protoIndex = buildProtoIndex();
        var key = uidLow + "," + uidHigh;
        var protoPtr = protoIndex[key];
        if (!protoPtr) return {ok: false, err: "pokemon not in heap index"};
        var instance = findServiceInstance();
        if (!instance) return {ok: false, err: "TaggingRpcService instance not found"};

        try {
            var args = Memory.alloc(setTagsParamCount * Process.pointerSize);
            args.writePointer(protoPtr);
            // Second arg likely tag list - pass as-is for now (would need List<int> construction)
            args.add(Process.pointerSize).writePointer(ptr(0));
            var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
            var ret = fns.rI(setTagsMethod, instance, args, exc);
            var excPtr = exc.readPointer();
            if (!excPtr.isNull()) {
                return {ok: false, err: "exception", excPtr: excPtr.toString()};
            }
            return {ok: true, ret: ret.toString()};
        } catch (e) {
            return {ok: false, err: "JS exception: " + e.message};
        }
    }
};

// ---- SERVER ANSWERS (H02-2, 2026-09-29) -------------------------------------------------------------------------------
// A generic, read-only dump of a settled promise: its own + inherited fields, one level into each referenced object, and
// for an *OutProto one more level (its int / enum fields and repeated enums), so the caller can read the reply's status.
var _GHAPI = null;
function _GH() {
    if (_GHAPI) return _GHAPI;
    var e = {};
    Process.findModuleByName('libil2cpp.so').enumerateExports().forEach(function (x) { if (x.name.indexOf('il2cpp_') === 0) e[x.name] = x.address; });
    function b(n, r, a) { return e[n] ? new NativeFunction(e[n], r, a, {exceptions: 'propagate'}) : null; }
    _GHAPI = {oc: b('il2cpp_object_get_class', 'pointer', ['pointer']), flds: b('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']),
              fnm: b('il2cpp_field_get_name', 'pointer', ['pointer']), foff: b('il2cpp_field_get_offset', 'size_t', ['pointer']),
              ftyp: b('il2cpp_field_get_type', 'pointer', ['pointer']), fflg: b('il2cpp_field_get_flags', 'int', ['pointer']),
              tnm: b('il2cpp_type_get_name', 'pointer', ['pointer']), cft: b('il2cpp_class_from_type', 'pointer', ['pointer']),
              isVT: b('il2cpp_class_is_valuetype', 'bool', ['pointer']), cnm: b('il2cpp_class_get_name', 'pointer', ['pointer']),
              parent: b('il2cpp_class_get_parent', 'pointer', ['pointer']),
              ghNew: b('il2cpp_gchandle_new', 'pointer', ['pointer', 'bool']),      // Il2CppGCHandle is a POINTER (Unity 2021.2+)
              ghGet: b('il2cpp_gchandle_get_target', 'pointer', ['pointer']), ghFree: b('il2cpp_gchandle_free', 'void', ['pointer'])};
    return _GHAPI;
}
function _ghFields(k, inherited) {
    var y = _GH(), out = [];
    for (var c = k; c && !c.isNull(); c = inherited ? y.parent(c) : null) {
        if (y.cnm(c).readCString() === 'Object') break;
        var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0)); var f;
        while ((f = y.flds(c, it)) && !f.isNull()) {
            if (y.fflg(f) & 0x10) continue;
            var t = y.ftyp(f);
            out.push({name: y.fnm(f).readCString(), off: Number(y.foff(f)), type: y.tnm(t).readCString(), vt: y.isVT(y.cft(t)) ? 1 : 0});
        }
        if (!inherited) break;
    }
    return out;
}
function _ghRepeated(rf) {
    var arr = null, cnt = null;
    _ghFields(_GH().oc(rf), true).forEach(function (f) {
        if (/\[\]$/.test(f.type)) arr = rf.add(f.off).readPointer();
        else if (/Int32/.test(f.type)) cnt = rf.add(f.off).readS32();
    });
    if (arr === null || arr.isNull() || cnt === null || cnt < 0 || cnt > 256) return null;
    var v = []; for (var i = 0; i < cnt; i++) v.push(arr.add(0x20 + 4 * i).readS32()); return v;
}
function _ghStr(p) { try { var n = p.add(0x10).readS32(); return (n >= 0 && n < 400) ? p.add(0x14).readUtf16String(n) : null; } catch (e) { return null; } }
// Niantic's Promise<T> (Gym Battle, proven on GymFeedPokemonOutProto / MapPlaceDetails / Buddy* replies): completeCalled /
// errorCalled are the settle flags, completedValue holds the reply (*OutProto), errorValue an Exception (_message).
function _ghDump(obj, depth) {
    var y = _GH(), cls = y.cnm(y.oc(obj)).readCString(), o = {cls: cls, f: {}};
    _ghFields(y.oc(obj), true).forEach(function (f) {
        var a = obj.add(f.off);
        try {
            if (f.vt) { o.f[f.name] = /Boolean|Byte/.test(f.type) ? a.readU8() : (/Int64|UInt64/.test(f.type) ? a.readS64().toString() : a.readS32()); return; }
            var p = a.readPointer();
            if (p.isNull()) { o.f[f.name] = null; return; }
            var c = y.cnm(y.oc(p)).readCString();
            if (c === 'String') { o.f[f.name] = {cls: 'String', s: _ghStr(p)}; return; }
            if (/RepeatedField/.test(c)) { o.f[f.name] = {cls: c, v: _ghRepeated(p)}; return; }
            var deep = depth > 0 && (/OutProto$/.test(c) || /Exception/.test(c) || /Promise/.test(c)
                                     || f.name === 'completedValue' || f.name === 'errorValue');
            o.f[f.name] = deep ? _ghDump(p, depth - 1) : {cls: c};
        } catch (e) { o.f[f.name] = {err: String(e)}; }
    });
    return o;
}
rpc.exports.promiseState = function (h) {
    try { var p = _GH().ghGet(ptr(h)); return p.isNull() ? null : _ghDump(p, 3); }
    catch (e) { return {err: String(e)}; }
};
rpc.exports.promiseFree = function (h) { try { _GH().ghFree(ptr(h)); return true; } catch (e) { return false; } };

send({type:"ready", msg:"bulk_tag.js loaded"});
