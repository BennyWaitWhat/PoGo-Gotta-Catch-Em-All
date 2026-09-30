/*
 * Quick IL2CPP class resolution - no delay.
 * For attaching to already-running PoGO (with Pokemod handling anti-cheat).
 */

// Resolve IL2CPP exports
var il2cpp = Process.getModuleByName("libil2cpp.so");
var exports_map = {};

var il2cpp_exports = il2cpp.enumerateExports();
for (var i = 0; i < il2cpp_exports.length; i++) {
    var e = il2cpp_exports[i];
    if (e.name.indexOf("il2cpp_") === 0) {
        exports_map[e.name] = e.address;
    }
}

send({type: "status", msg: "Resolved " + Object.keys(exports_map).length + " il2cpp exports"});

// Bind critical functions
function bind(name, ret, args) {
    if (!exports_map[name]) { send({type: "error", msg: "Missing: " + name}); return null; }
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
var il2cpp_string_length = bind("il2cpp_string_length", 'int', ['pointer']);
var il2cpp_string_chars = bind("il2cpp_string_chars", 'pointer', ['pointer']);
var il2cpp_method_get_param_count = bind("il2cpp_method_get_param_count", 'int', ['pointer']);

// Attach thread
var domain = il2cpp_domain_get();
if (domain.isNull()) {
    send({type: "error", msg: "Domain is NULL"});
} else {
    send({type: "status", msg: "Domain: " + domain});
    il2cpp_thread_attach(domain);
    send({type: "status", msg: "Thread attached"});

    // Get assemblies
    var sizePtr = Memory.alloc(4);
    var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
    var numAssemblies = sizePtr.readS32();
    send({type: "status", msg: "Assemblies: " + numAssemblies});

    // Find the image containing PokemonProto
    var nsPtr = Memory.allocUtf8String("Holoholo.Rpc");
    var classNamePtr = Memory.allocUtf8String("PokemonProto");
    var targetImage = null;
    var pokemonProtoClass = null;

    for (var a = 0; a < numAssemblies; a++) {
        var assembly = assemblies.add(a * Process.pointerSize).readPointer();
        var image = il2cpp_assembly_get_image(assembly);
        var klass = il2cpp_class_from_name(image, nsPtr, classNamePtr);
        if (!klass.isNull()) {
            targetImage = image;
            pokemonProtoClass = klass;
            var imgName = il2cpp_image_get_name(image).readCString();
            send({type: "status", msg: "Found PokemonProto in: " + imgName});
            break;
        }
    }

    if (!pokemonProtoClass) {
        send({type: "error", msg: "PokemonProto not found in any assembly"});
    } else {
        // Get field offsets
        var fieldNames = [
            "pokemonId_", "cp_", "stamina_", "staminaMax_",
            "move1_", "move2_", "move3_",
            "individualAttack_", "individualDefense_", "individualStamina_",
            "heightM_", "weightKg_", "nickname_", "pokeball_",
            "cpMultiplier_", "numAdditionalCpMultiplier_",
            "creationTimeMs_", "pokemonDisplay_",
            "isLucky_", "deployedFortId_", "id_"
        ];

        var fields = {};
        for (var f = 0; f < fieldNames.length; f++) {
            var fnPtr = Memory.allocUtf8String(fieldNames[f]);
            var field = il2cpp_class_get_field_from_name(pokemonProtoClass, fnPtr);
            if (!field.isNull()) {
                fields[fieldNames[f]] = il2cpp_field_get_offset(field);
            }
        }
        send({type: "fields", data: fields});

        // Now find PokemonBagImpl or PokemonBagService
        var bagClasses = ["PokemonBagImpl", "PokemonBagService", "PokemonBag"];
        var bagNamespaces = ["Niantic.Holoholo.Internal", "Niantic.Holoholo", "Niantic.Holoholo.Inventory", "Niantic.Holoholo.Services", ""];
        var pokemonBagClass = null;
        var foundBagName = "";

        for (var bi = 0; bi < bagClasses.length && !pokemonBagClass; bi++) {
            for (var ni = 0; ni < bagNamespaces.length && !pokemonBagClass; ni++) {
                var nsP = Memory.allocUtf8String(bagNamespaces[ni]);
                var cnP = Memory.allocUtf8String(bagClasses[bi]);
                var cls = il2cpp_class_from_name(targetImage, nsP, cnP);
                if (!cls.isNull()) {
                    pokemonBagClass = cls;
                    foundBagName = bagNamespaces[ni] + "." + bagClasses[bi];
                    send({type: "status", msg: "Found bag class: " + foundBagName});
                }
            }
        }

        if (!pokemonBagClass) {
            // Search all classes in image for anything with "PokemonBag" in the name
            send({type: "status", msg: "Bag class not found directly, scanning image..."});
            var classCount = il2cpp_image_get_class_count(targetImage);
            send({type: "status", msg: "Image has " + classCount + " classes, scanning..."});

            var bagMatches = [];
            for (var c = 0; c < classCount; c++) {
                var cls = il2cpp_image_get_class(targetImage, c);
                if (cls.isNull()) continue;
                var cname = il2cpp_class_get_name(cls).readCString();
                if (cname && (cname.indexOf("PokemonBag") >= 0 ||
                              cname.indexOf("Inventory") >= 0 && cname.indexOf("Widget") < 0 && cname.indexOf("Gui") < 0)) {
                    var cns = il2cpp_class_get_namespace(cls).readCString();
                    bagMatches.push({ns: cns, name: cname, ptr: cls.toString()});
                }
            }
            send({type: "bag_candidates", data: bagMatches});
        } else {
            // Look for GetAllPokemon or similar methods
            var methodNames = ["GetAllPokemon", "get_AllPokemon", "GetPokemons", "get_Pokemons",
                              "get_allPokemon", "GetAll", "get_All", "get_Pokemon", "get_Items"];
            var foundMethods = [];
            for (var m = 0; m < methodNames.length; m++) {
                var mPtr = Memory.allocUtf8String(methodNames[m]);
                for (var p = 0; p <= 2; p++) {
                    var meth = il2cpp_class_get_method_from_name(pokemonBagClass, mPtr, p);
                    if (meth && !meth.isNull()) {
                        foundMethods.push({name: methodNames[m], params: p, ptr: meth.toString()});
                    }
                }
            }
            send({type: "methods", data: foundMethods});

            // Also check for a static Instance field or similar singleton accessor
            var singletonFields = ["instance_", "_instance", "s_instance", "Instance"];
            var foundSingletons = [];
            for (var s = 0; s < singletonFields.length; s++) {
                var sfPtr = Memory.allocUtf8String(singletonFields[s]);
                var sf = il2cpp_class_get_field_from_name(pokemonBagClass, sfPtr);
                if (sf && !sf.isNull()) {
                    foundSingletons.push({name: singletonFields[s], offset: il2cpp_field_get_offset(sf)});
                }
            }
            send({type: "singletons", data: foundSingletons});
        }

        send({type: "done", msg: "Class resolution complete"});
    }
}
