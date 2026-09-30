// Account snapshot IL2CPP introspection engine. Appended after pogo_il2cpp JS_PREAMBLE
// (which defines IL2, cFN, cMN, rI, liveness_find_instances, _ensureInit and rpc.exports).
// We AUGMENT rpc.exports with introspection primitives.

var EX = null;
function _ensureEX() {
    if (EX) return;
    _ensureInit();
    var il2 = Process.findModuleByName('libil2cpp.so');
    function b(n, ret, args) {
        var a = il2.findExportByName(n);
        return a ? new NativeFunction(a, ret, args) : null;
    }
    EX = {
        cGF:  b('il2cpp_class_get_fields', 'pointer', ['pointer', 'pointer']),
        fGN:  b('il2cpp_field_get_name', 'pointer', ['pointer']),
        fGO:  b('il2cpp_field_get_offset', 'uint32', ['pointer']),
        fGT:  b('il2cpp_field_get_type', 'pointer', ['pointer']),
        tGN:  b('il2cpp_type_get_name', 'pointer', ['pointer']),
        cGM:  b('il2cpp_class_get_methods', 'pointer', ['pointer', 'pointer']),
        mGN:  b('il2cpp_method_get_name', 'pointer', ['pointer']),
        mGPC: b('il2cpp_method_get_param_count', 'uint32', ['pointer']),
        oGC:  b('il2cpp_object_get_class', 'pointer', ['pointer']),
        cGNa: b('il2cpp_class_get_name', 'pointer', ['pointer']),
        cGNs: b('il2cpp_class_get_namespace', 'pointer', ['pointer']),
    };
}

// Read all instance fields of an object by resolving its class FROM the object itself
// (works regardless of which image the class lives in - fixes holo-protos.dll lookups).
function _readObjFields(inst) {
    var k = EX.oGC(inst);
    if (!k || k.isNull()) return { err: 'no class from object' };
    var nm = EX.cGNa(k) ? EX.cGNa(k).readCString() : '?';
    var ns = EX.cGNs(k) ? EX.cGNs(k).readCString() : '';
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var out = {}, f;
    while (!(f = EX.cGF(k, it)).isNull()) {
        var fn = EX.fGN(f).readCString();
        var off = EX.fGO(f);
        var t = EX.fGT(f); var tn = t ? EX.tGN(t).readCString() : '';
        var v = {};
        try { v.i32 = inst.add(off).readS32(); } catch (e) {}
        try { v.i64 = inst.add(off).readS64().toString(); } catch (e) {}
        try { v.f32 = inst.add(off).readFloat(); } catch (e) {}
        try {
            var sp = inst.add(off).readPointer();
            if (!sp.isNull()) { var len = sp.add(0x10).readS32(); if (len >= 0 && len < 256) { var s = sp.add(0x14).readUtf16String(len); if (s) v.str = s; } }
        } catch (e) {}
        out[fn] = { off: off, type: tn, val: v };
        if (Object.keys(out).length > 300) break;
    }
    return { className: (ns ? ns + '.' : '') + nm, fields: out };
}

// Interpret a runtime_invoke return pointer (boxed value type, string, or object) several ways.
function _readMulti(p) {
    var o = { ptr: p.isNull() ? null : p.toString() };
    if (p.isNull()) return o;
    try { o.i32 = p.add(0x10).readS32(); } catch (e) {}
    try { o.i64 = p.add(0x10).readS64().toString(); } catch (e) {}
    try { o.f32 = p.add(0x10).readFloat(); } catch (e) {}
    try { o.u8 = p.add(0x10).readU8(); } catch (e) {}
    try {
        var len = p.add(0x10).readS32();
        if (len >= 0 && len < 256) { var s = p.add(0x14).readUtf16String(len); if (s) o.str = s; }
    } catch (e) {}
    return o;
}

rpc.exports.enumMethods = function (ns, cls) {
    _ensureEX();
    var k = cFN(ns, cls);
    if (!k || k.isNull()) return { err: 'class not found' };
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var out = [], m;
    while (!(m = EX.cGM(k, it)).isNull()) {
        out.push({ name: EX.mGN(m).readCString(), argc: EX.mGPC(m) });
        if (out.length > 600) break;
    }
    return out;
};

rpc.exports.enumFields = function (ns, cls) {
    _ensureEX();
    var k = cFN(ns, cls);
    if (!k || k.isNull()) return { err: 'class not found' };
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var out = [], f;
    while (!(f = EX.cGF(k, it)).isNull()) {
        var t = EX.fGT(f);
        out.push({ name: EX.fGN(f).readCString(), off: EX.fGO(f), type: t ? EX.tGN(t).readCString() : null });
        if (out.length > 400) break;
    }
    return out;
};

// Resolve an object's class from itself and dump its fields (image-agnostic).
rpc.exports.readObjFields = function (instPtrStr) {
    _ensureEX();
    var inst = ptr(instPtrStr);
    if (inst.isNull()) return { err: 'null instance' };
    try { return _readObjFields(inst); } catch (e) { return { err: 'threw: ' + e.toString() }; }
};

rpc.exports.findAll = function (ns, cls) {
    _ensureEX();
    var k = cFN(ns, cls);
    if (!k || k.isNull()) return { err: 'class not found' };
    return liveness_find_instances(k);  // {hits:[ptrStr]} or {err}
};

// Call a 0-arg getter on an instance (or static if instPtr null). Returns _readMulti of the result.
rpc.exports.callGetter = function (ns, cls, name, instPtrStr) {
    _ensureEX();
    var k = cFN(ns, cls);
    if (!k || k.isNull()) return { err: 'class not found' };
    var m = cMN(k, name, 0);
    if (!m || m.isNull()) return { err: 'method not found: ' + name };
    var inst = instPtrStr ? ptr(instPtrStr) : ptr(0);
    try {
        var r = rI(m, inst, ptr(0), null);
        return _readMulti(r);
    } catch (e) { return { err: 'invoke threw: ' + e.toString() }; }
};

// Call a 1-int-arg method (e.g. GetItemCount(int), GetCandyCountForPokemonFamily(int)).
rpc.exports.callIntArg = function (ns, cls, name, instPtrStr, intval) {
    _ensureEX();
    var k = cFN(ns, cls);
    if (!k || k.isNull()) return { err: 'class not found' };
    var m = cMN(k, name, 1);
    if (!m || m.isNull()) return { err: 'method not found: ' + name };
    var inst = instPtrStr ? ptr(instPtrStr) : ptr(0);
    var argArr = Memory.alloc(Process.pointerSize);
    var valbuf = Memory.alloc(4); valbuf.writeS32(intval);
    argArr.writePointer(valbuf);
    try {
        var r = rI(m, inst, argArr, null);
        return _readMulti(r);
    } catch (e) { return { err: 'invoke threw: ' + e.toString() }; }
};

// Read every instance field of an object (given its class) by offset, multi-interpreted.
rpc.exports.readFieldsAt = function (instPtrStr, ns, cls) {
    _ensureEX();
    var k = cFN(ns, cls);
    if (!k || k.isNull()) return { err: 'class not found' };
    var inst = ptr(instPtrStr);
    if (inst.isNull()) return { err: 'null instance' };
    var it = Memory.alloc(Process.pointerSize); it.writePointer(ptr(0));
    var out = {}, f;
    while (!(f = EX.cGF(k, it)).isNull()) {
        var nm = EX.fGN(f).readCString();
        var off = EX.fGO(f);
        var t = EX.fGT(f); var tn = t ? EX.tGN(t).readCString() : '';
        var v = {};
        try { v.i32 = inst.add(off).readS32(); } catch (e) {}
        try { v.i64 = inst.add(off).readS64().toString(); } catch (e) {}
        try { v.f32 = inst.add(off).readFloat(); } catch (e) {}
        try {
            var sp = inst.add(off).readPointer();
            if (!sp.isNull()) {
                var len = sp.add(0x10).readS32();
                if (len >= 0 && len < 256) { var s = sp.add(0x14).readUtf16String(len); if (s) v.str = s; }
            }
        } catch (e) {}
        out[nm] = { off: off, type: tn, val: v };
        if (Object.keys(out).length > 300) break;
    }
    return out;
};
