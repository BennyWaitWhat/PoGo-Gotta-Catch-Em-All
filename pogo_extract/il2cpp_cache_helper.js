/* il2cpp_cache_helper.js
 *
 * Frida-side helper for cached IL2CPP lookups. The Python caller injects a
 * CACHE constant before this code (string-format substitution) containing:
 *   { exports: { name: rva, ... },
 *     field_offsets: { "Holoholo.Rpc.PokemonProto": {fieldName: int, ...}, ... },
 *     image_hints: { "Niantic.Holoholo.Internal.PokemonBagImpl": "holo-game.dll", ... }
 *   }
 *
 * Pattern (Python side):
 *     helper = open("il2cpp_cache_helper.js").read()
 *     blob = "var CACHE = " + cache.to_js_literal() + ";\n" + helper + script_body
 *     sess.create_script(blob)
 *
 * After this loads, `IL2CPP` is available in the script with:
 *   IL2CPP.fn.<api>            -- prebound NativeFunctions for cached exports
 *   IL2CPP.getClass(qn)        -- resolve Il2CppClass*, memoized
 *   IL2CPP.getMethod(qn, n, c) -- resolve MethodInfo*, single-call
 *   IL2CPP.getFieldOffset(qn, name) -- cached managed-field offset
 *   IL2CPP.ensureDomain()      -- attach current thread once
 */

var IL2CPP = (function() {
    if (typeof CACHE === "undefined") throw new Error("il2cpp_cache_helper: CACHE not injected");
    var EXPORT_RVAS = CACHE.exports;
    var FIELD_OFFSETS = CACHE.field_offsets || {};
    var IMAGE_HINTS = CACHE.image_hints || {};

    var mod = Process.findModuleByName("libil2cpp.so");
    if (!mod) throw new Error("libil2cpp.so not mapped yet");
    var base = mod.base;

    var fn = {};
    function bind(name, ret, args) {
        var rva = EXPORT_RVAS[name];
        if (rva === undefined) return null;
        return new NativeFunction(base.add(rva), ret, args);
    }
    fn.domain_get = bind("il2cpp_domain_get", "pointer", []);
    fn.domain_get_assemblies = bind("il2cpp_domain_get_assemblies", "pointer", ["pointer","pointer"]);
    fn.assembly_get_image = bind("il2cpp_assembly_get_image", "pointer", ["pointer"]);
    fn.image_get_name = bind("il2cpp_image_get_name", "pointer", ["pointer"]);
    fn.image_get_class_count = bind("il2cpp_image_get_class_count", "int", ["pointer"]);
    fn.image_get_class = bind("il2cpp_image_get_class", "pointer", ["pointer","int"]);
    fn.class_from_name = bind("il2cpp_class_from_name", "pointer", ["pointer","pointer","pointer"]);
    fn.class_get_name = bind("il2cpp_class_get_name", "pointer", ["pointer"]);
    fn.class_get_namespace = bind("il2cpp_class_get_namespace", "pointer", ["pointer"]);
    fn.class_get_method_from_name = bind("il2cpp_class_get_method_from_name", "pointer", ["pointer","pointer","int"]);
    fn.class_get_methods = bind("il2cpp_class_get_methods", "pointer", ["pointer","pointer"]);
    fn.class_get_field_from_name = bind("il2cpp_class_get_field_from_name", "pointer", ["pointer","pointer"]);
    fn.class_get_fields = bind("il2cpp_class_get_fields", "pointer", ["pointer","pointer"]);
    fn.method_get_name = bind("il2cpp_method_get_name", "pointer", ["pointer"]);
    fn.field_get_offset = bind("il2cpp_field_get_offset", "int", ["pointer"]);
    fn.field_get_name = bind("il2cpp_field_get_name", "pointer", ["pointer"]);
    fn.field_get_value_object = bind("il2cpp_field_get_value_object", "pointer", ["pointer","pointer"]);
    fn.runtime_invoke = bind("il2cpp_runtime_invoke", "pointer", ["pointer","pointer","pointer","pointer"]);
    fn.thread_attach = bind("il2cpp_thread_attach", "pointer", ["pointer"]);
    fn.string_chars = bind("il2cpp_string_chars", "pointer", ["pointer"]);
    fn.string_length = bind("il2cpp_string_length", "int", ["pointer"]);
    fn.array_length = bind("il2cpp_array_length", "int", ["pointer"]);

    var _domain = null;
    var _images = {};
    var _classes = {};
    var _strCache = {};

    function utf8(s) {
        var hit = _strCache[s];
        if (hit) return hit;
        var p = Memory.allocUtf8String(s);
        _strCache[s] = p;
        return p;
    }

    function ensureDomain() {
        if (_domain) return _domain;
        var d = fn.domain_get();
        if (d.isNull()) throw new Error("il2cpp_domain_get returned NULL");
        fn.thread_attach(d);
        _domain = d;
        return d;
    }

    function loadAllImages() {
        if (Object.keys(_images).length > 0) return;
        var dom = ensureDomain();
        var sp = Memory.alloc(4);
        var asms = fn.domain_get_assemblies(dom, sp);
        var n = sp.readS32();
        for (var i = 0; i < n; i++) {
            var img = fn.assembly_get_image(asms.add(i * Process.pointerSize).readPointer());
            if (img.isNull()) continue;
            _images[fn.image_get_name(img).readCString()] = img;
        }
    }

    function getImage(dllName) {
        loadAllImages();
        return _images[dllName] || null;
    }

    function getClass(qualifiedName) {
        var hit = _classes[qualifiedName];
        if (hit) return hit;
        var lastDot = qualifiedName.lastIndexOf(".");
        var ns = lastDot >= 0 ? qualifiedName.substring(0, lastDot) : "";
        var cls = lastDot >= 0 ? qualifiedName.substring(lastDot + 1) : qualifiedName;
        var nsP = utf8(ns);
        var clsP = utf8(cls);
        var hint = IMAGE_HINTS[qualifiedName];
        var dlls = hint ? [hint, "holo-game.dll", "holo-protos.dll", "Assembly-CSharp.dll"]
                        : ["holo-game.dll", "holo-protos.dll", "Assembly-CSharp.dll"];
        for (var i = 0; i < dlls.length; i++) {
            var img = getImage(dlls[i]);
            if (!img) continue;
            var k = fn.class_from_name(img, nsP, clsP);
            if (!k.isNull()) {
                _classes[qualifiedName] = k;
                return k;
            }
        }
        return null;
    }

    function getMethod(qualifiedName, methodName, argc) {
        var k = getClass(qualifiedName);
        if (!k) return null;
        var m = fn.class_get_method_from_name(k, utf8(methodName), argc);
        return m.isNull() ? null : m;
    }

    function getFieldOffset(qualifiedName, fieldName) {
        var bucket = FIELD_OFFSETS[qualifiedName];
        if (bucket && bucket[fieldName] !== undefined) return bucket[fieldName];
        var k = getClass(qualifiedName);
        if (!k) return -1;
        var f = fn.class_get_field_from_name(k, utf8(fieldName));
        if (f.isNull()) return -1;
        return fn.field_get_offset(f);
    }

    return {
        fn: fn,
        base: base,
        ensureDomain: ensureDomain,
        getImage: getImage,
        getClass: getClass,
        getMethod: getMethod,
        getFieldOffset: getFieldOffset,
        _stats: function() {
            return {
                exportsBound: Object.keys(fn).filter(function(k){return fn[k];}).length,
                imagesLoaded: Object.keys(_images).length,
                classesResolved: Object.keys(_classes).length,
                fieldOffsetsCached: Object.keys(FIELD_OFFSETS).length,
            };
        }
    };
})();
