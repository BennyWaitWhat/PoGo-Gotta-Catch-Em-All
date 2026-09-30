/*
 * Find PokemonBagImpl across all assemblies, then get its instance.
 */

var il2cpp = Process.getModuleByName("libil2cpp.so");
var exports_map = {};
var il2cpp_exports = il2cpp.enumerateExports();
for (var i = 0; i < il2cpp_exports.length; i++) {
    if (il2cpp_exports[i].name.indexOf("il2cpp_") === 0)
        exports_map[il2cpp_exports[i].name] = il2cpp_exports[i].address;
}

function bind(name, ret, args) {
    if (!exports_map[name]) return null;
    return new NativeFunction(exports_map[name], ret, args);
}

var il2cpp_domain_get = bind("il2cpp_domain_get", 'pointer', []);
var il2cpp_domain_get_assemblies = bind("il2cpp_domain_get_assemblies", 'pointer', ['pointer', 'pointer']);
var il2cpp_assembly_get_image = bind("il2cpp_assembly_get_image", 'pointer', ['pointer']);
var il2cpp_image_get_name = bind("il2cpp_image_get_name", 'pointer', ['pointer']);
var il2cpp_image_get_class_count = bind("il2cpp_image_get_class_count", 'int', ['pointer']);
var il2cpp_image_get_class = bind("il2cpp_image_get_class", 'pointer', ['pointer', 'int']);
var il2cpp_class_from_name = bind("il2cpp_class_from_name", 'pointer', ['pointer', 'pointer', 'pointer']);
var il2cpp_class_get_name = bind("il2cpp_class_get_name", 'pointer', ['pointer']);
var il2cpp_class_get_namespace = bind("il2cpp_class_get_namespace", 'pointer', ['pointer']);
var il2cpp_class_get_method_from_name = bind("il2cpp_class_get_method_from_name", 'pointer', ['pointer', 'pointer', 'int']);
var il2cpp_class_get_fields = bind("il2cpp_class_get_fields", 'pointer', ['pointer', 'pointer']);
var il2cpp_class_get_field_from_name = bind("il2cpp_class_get_field_from_name", 'pointer', ['pointer', 'pointer']);
var il2cpp_field_get_name = bind("il2cpp_field_get_name", 'pointer', ['pointer']);
var il2cpp_field_get_offset = bind("il2cpp_field_get_offset", 'int', ['pointer']);
var il2cpp_field_get_value_object = bind("il2cpp_field_get_value_object", 'pointer', ['pointer', 'pointer']);
var il2cpp_runtime_invoke = bind("il2cpp_runtime_invoke", 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
var il2cpp_thread_attach = bind("il2cpp_thread_attach", 'pointer', ['pointer']);
var il2cpp_array_length = bind("il2cpp_array_length", 'int', ['pointer']);
var il2cpp_class_get_parent = bind("il2cpp_class_get_parent", 'pointer', ['pointer']);
var il2cpp_field_get_type = bind("il2cpp_field_get_type", 'pointer', ['pointer']);
var il2cpp_type_get_name = bind("il2cpp_type_get_name", 'pointer', ['pointer']);

var domain = il2cpp_domain_get();
il2cpp_thread_attach(domain);

var sizePtr = Memory.alloc(4);
var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
var numAssemblies = sizePtr.readS32();

send({type: "status", msg: "Searching " + numAssemblies + " assemblies for PokemonBag..."});

// Search all assemblies for PokemonBagImpl
var searchNames = ["PokemonBagImpl", "PokemonBagService", "PokemonBag"];
var searchNs = ["Niantic.Holoholo.Internal", "Niantic.Holoholo", "Niantic.Holoholo.Services",
                "Niantic.Holoholo.Inventory", ""];

var found = null;

for (var a = 0; a < numAssemblies && !found; a++) {
    var assembly = assemblies.add(a * Process.pointerSize).readPointer();
    var image = il2cpp_assembly_get_image(assembly);

    for (var si = 0; si < searchNames.length && !found; si++) {
        for (var ni = 0; ni < searchNs.length && !found; ni++) {
            var nsP = Memory.allocUtf8String(searchNs[ni]);
            var cnP = Memory.allocUtf8String(searchNames[si]);
            var cls = il2cpp_class_from_name(image, nsP, cnP);
            if (!cls.isNull()) {
                var imgName = il2cpp_image_get_name(image).readCString();
                found = {cls: cls, name: searchNames[si], ns: searchNs[ni], image: imgName, imagePtr: image};
                send({type: "status", msg: "FOUND: " + searchNs[ni] + "." + searchNames[si] + " in " + imgName});
            }
        }
    }
}

if (!found) {
    // Brute force: scan all classes in all assemblies
    send({type: "status", msg: "Not found via class_from_name, brute-force scanning..."});
    for (var a = 0; a < numAssemblies; a++) {
        var assembly = assemblies.add(a * Process.pointerSize).readPointer();
        var image = il2cpp_assembly_get_image(assembly);
        var classCount = il2cpp_image_get_class_count(image);

        for (var c = 0; c < classCount; c++) {
            var cls = il2cpp_image_get_class(image, c);
            if (cls.isNull()) continue;
            var cname = il2cpp_class_get_name(cls).readCString();
            if (cname && cname.indexOf("PokemonBag") >= 0) {
                var cns = il2cpp_class_get_namespace(cls).readCString();
                var imgName = il2cpp_image_get_name(image).readCString();
                send({type: "status", msg: "BruteForce found: " + cns + "." + cname + " in " + imgName});
                if (cname === "PokemonBagImpl") {
                    found = {cls: cls, name: cname, ns: cns, image: imgName, imagePtr: image};
                }
            }
        }
    }
}

if (found) {
    send({type: "status", msg: "Examining " + found.ns + "." + found.name + "..."});

    // Enumerate all fields
    var iterPtr = Memory.alloc(Process.pointerSize);
    iterPtr.writePointer(ptr(0));
    var allFields = [];
    while (true) {
        var field = il2cpp_class_get_fields(found.cls, iterPtr);
        if (field.isNull()) break;
        var fname = il2cpp_field_get_name(field).readCString();
        var foffset = il2cpp_field_get_offset(field);
        allFields.push({name: fname, offset: foffset});
    }
    send({type: "bag_fields", data: allFields});

    // Look for methods
    var methodNames = ["GetAllPokemon", "get_AllPokemon", "get_Pokemons", "GetPokemons",
                       "get_allPokemon", "get_Pokemon", "get_Items", "GetAll",
                       "get_AllPokemonDict", "get_PokemonById", "GetPokemonById",
                       "get_Count", "GetCount", "get_PokemonList", "GetPokemonList"];
    var foundMethods = [];
    for (var m = 0; m < methodNames.length; m++) {
        var mPtr = Memory.allocUtf8String(methodNames[m]);
        for (var p = 0; p <= 2; p++) {
            var meth = il2cpp_class_get_method_from_name(found.cls, mPtr, p);
            if (meth && !meth.isNull()) {
                foundMethods.push({name: methodNames[m], params: p, ptr: meth.toString()});
            }
        }
    }
    send({type: "bag_methods", data: foundMethods});

    // Check parent class too
    var parent = il2cpp_class_get_parent(found.cls);
    if (parent && !parent.isNull()) {
        var parentName = il2cpp_class_get_name(parent).readCString();
        var parentNs = il2cpp_class_get_namespace(parent).readCString();
        send({type: "status", msg: "Parent class: " + parentNs + "." + parentName});
    }
}

// Also look for IPokemonBag interface implementations
var iPokemonBagNames = ["IPokemonBag", "IPokemonBagService"];
for (var ib = 0; ib < iPokemonBagNames.length; ib++) {
    for (var a = 0; a < numAssemblies; a++) {
        var assembly = assemblies.add(a * Process.pointerSize).readPointer();
        var image = il2cpp_assembly_get_image(assembly);
        for (var ni = 0; ni < searchNs.length; ni++) {
            var nsP = Memory.allocUtf8String(searchNs[ni]);
            var cnP = Memory.allocUtf8String(iPokemonBagNames[ib]);
            var cls = il2cpp_class_from_name(image, nsP, cnP);
            if (!cls.isNull()) {
                var imgName = il2cpp_image_get_name(image).readCString();
                send({type: "status", msg: "Interface: " + searchNs[ni] + "." + iPokemonBagNames[ib] + " in " + imgName});

                // Get methods on interface
                var ifMethods = ["GetAllPokemon", "get_AllPokemon", "get_Pokemons", "GetPokemons"];
                for (var m = 0; m < ifMethods.length; m++) {
                    var mPtr = Memory.allocUtf8String(ifMethods[m]);
                    for (var p = 0; p <= 1; p++) {
                        var meth = il2cpp_class_get_method_from_name(cls, mPtr, p);
                        if (meth && !meth.isNull()) {
                            send({type: "status", msg: "  Interface method: " + ifMethods[m] + "(params=" + p + ")"});
                        }
                    }
                }
                break;
            }
        }
    }
}

send({type: "done", msg: "Bag search complete"});
