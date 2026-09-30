/*
 * Pokemon GO IL2CPP inventory extraction via Frida.
 *
 * Strategy:
 * 1. Resolve IL2CPP API functions from libil2cpp.so exports
 * 2. Find PokemonProto class and its fields
 * 3. Enumerate all Pokemon in the bag
 * 4. Send data back via Frida send() messages
 *
 * Must be injected with spawn (before anti-cheat):
 *   frida-inject -D <device> -f com.nianticlabs.pokemongo -s il2cpp_extract.js --no-pause
 * Or via our spawn_inject.py wrapper.
 */

// Resolve IL2CPP exports
var il2cpp = Process.getModuleByName("libil2cpp.so");
var exports_map = {};
var needed = [
    "il2cpp_domain_get",
    "il2cpp_domain_get_assemblies",
    "il2cpp_assembly_get_image",
    "il2cpp_class_from_name",
    "il2cpp_class_get_method_from_name",
    "il2cpp_class_get_fields",
    "il2cpp_class_get_field_from_name",
    "il2cpp_field_get_name",
    "il2cpp_field_get_offset",
    "il2cpp_field_get_value",
    "il2cpp_field_get_value_object",
    "il2cpp_runtime_invoke",
    "il2cpp_thread_attach",
    "il2cpp_domain_get",
    "il2cpp_string_chars",
    "il2cpp_string_length",
    "il2cpp_string_new",
    "il2cpp_object_new",
    "il2cpp_array_length",
    "il2cpp_image_get_class_count",
    "il2cpp_image_get_class",
    "il2cpp_class_get_name",
    "il2cpp_class_get_namespace",
    "il2cpp_class_get_type",
    "il2cpp_type_get_name",
    "il2cpp_method_get_param_count",
];

var il2cpp_exports = il2cpp.enumerateExports();
for (var i = 0; i < il2cpp_exports.length; i++) {
    var e = il2cpp_exports[i];
    if (needed.indexOf(e.name) >= 0) {
        exports_map[e.name] = e.address;
    }
}

send({type: "status", msg: "IL2CPP exports resolved: " + Object.keys(exports_map).length + "/" + needed.length});

// Check we have the critical ones
var missing = [];
for (var j = 0; j < needed.length; j++) {
    if (!exports_map[needed[j]]) missing.push(needed[j]);
}
if (missing.length > 0) {
    send({type: "error", msg: "Missing IL2CPP exports: " + missing.join(", ")});
}

// Bind IL2CPP API functions
var il2cpp_domain_get = new NativeFunction(exports_map["il2cpp_domain_get"], 'pointer', []);
var il2cpp_domain_get_assemblies = new NativeFunction(exports_map["il2cpp_domain_get_assemblies"], 'pointer', ['pointer', 'pointer']);
var il2cpp_thread_attach = new NativeFunction(exports_map["il2cpp_thread_attach"], 'pointer', ['pointer']);
var il2cpp_class_from_name = new NativeFunction(exports_map["il2cpp_class_from_name"], 'pointer', ['pointer', 'pointer', 'pointer']);
var il2cpp_class_get_method_from_name = new NativeFunction(exports_map["il2cpp_class_get_method_from_name"], 'pointer', ['pointer', 'pointer', 'int']);
var il2cpp_class_get_field_from_name = new NativeFunction(exports_map["il2cpp_class_get_field_from_name"], 'pointer', ['pointer', 'pointer']);
var il2cpp_field_get_offset = new NativeFunction(exports_map["il2cpp_field_get_offset"], 'int', ['pointer']);
var il2cpp_field_get_value_object = new NativeFunction(exports_map["il2cpp_field_get_value_object"], 'pointer', ['pointer', 'pointer']);
var il2cpp_runtime_invoke = new NativeFunction(exports_map["il2cpp_runtime_invoke"], 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
var il2cpp_string_chars = exports_map["il2cpp_string_chars"] ? new NativeFunction(exports_map["il2cpp_string_chars"], 'pointer', ['pointer']) : null;
var il2cpp_string_length = exports_map["il2cpp_string_length"] ? new NativeFunction(exports_map["il2cpp_string_length"], 'int', ['pointer']) : null;
var il2cpp_array_length = new NativeFunction(exports_map["il2cpp_array_length"], 'int', ['pointer']);
var il2cpp_image_get_class_count = exports_map["il2cpp_image_get_class_count"] ? new NativeFunction(exports_map["il2cpp_image_get_class_count"], 'int', ['pointer']) : null;
var il2cpp_image_get_class = exports_map["il2cpp_image_get_class"] ? new NativeFunction(exports_map["il2cpp_image_get_class"], 'pointer', ['pointer', 'int']) : null;
var il2cpp_class_get_name = exports_map["il2cpp_class_get_name"] ? new NativeFunction(exports_map["il2cpp_class_get_name"], 'pointer', ['pointer']) : null;
var il2cpp_class_get_namespace = exports_map["il2cpp_class_get_namespace"] ? new NativeFunction(exports_map["il2cpp_class_get_namespace"], 'pointer', ['pointer']) : null;

// Helper: read IL2CPP string object (C# System.String layout: vtable ptr, length at +0x10, chars at +0x14)
function readIl2cppString(strObj) {
    if (strObj.isNull()) return null;
    // IL2CPP string layout: [MethodTable*][m_stringLength (int32 at offset 0x10)][m_firstChar (at offset 0x14)]
    var len = strObj.add(0x10).readS32();
    if (len <= 0 || len > 100) return null;
    var chars = strObj.add(0x14).readUtf16String(len);
    return chars;
}

// Helper: read int32 field from IL2CPP object
function readInt32Field(obj, offset) {
    return obj.add(offset).readS32();
}

// Helper: read float field
function readFloatField(obj, offset) {
    return obj.add(offset).readFloat();
}

// Helper: read bool field
function readBoolField(obj, offset) {
    return obj.add(offset).readU8() !== 0;
}

// Helper: read int64 field
function readInt64Field(obj, offset) {
    var low = obj.add(offset).readU32();
    var high = obj.add(offset + 4).readS32();
    return high * 0x100000000 + low;
}

// Helper: read pointer field (object reference)
function readPtrField(obj, offset) {
    return obj.add(offset).readPointer();
}

// Wait for game to be fully loaded, then extract
function waitAndExtract() {
    send({type: "status", msg: "Waiting 30s for game to fully load..."});

    setTimeout(function() {
        try {
            extract();
        } catch(e) {
            send({type: "error", msg: "Extract failed: " + e.message + "\n" + e.stack});
        }
    }, 30000);
}

function extract() {
    // Attach current thread to IL2CPP
    var domain = il2cpp_domain_get();
    send({type: "status", msg: "Domain: " + domain});

    if (domain.isNull()) {
        send({type: "error", msg: "il2cpp_domain_get returned NULL - game not loaded yet"});
        return;
    }

    il2cpp_thread_attach(domain);
    send({type: "status", msg: "Thread attached to IL2CPP domain"});

    // Get assemblies
    var sizePtr = Memory.alloc(4);
    var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
    var numAssemblies = sizePtr.readS32();
    send({type: "status", msg: "Assemblies: " + numAssemblies});

    // We need to find the image that contains Holoholo.Rpc namespace
    // First, let's find il2cpp_assembly_get_image
    var il2cpp_assembly_get_image = null;
    for (var i = 0; i < il2cpp_exports.length; i++) {
        if (il2cpp_exports[i].name === "il2cpp_assembly_get_image") {
            il2cpp_assembly_get_image = new NativeFunction(il2cpp_exports[i].address, 'pointer', ['pointer']);
            break;
        }
    }

    if (!il2cpp_assembly_get_image) {
        send({type: "error", msg: "il2cpp_assembly_get_image not found"});
        return;
    }

    // Also find il2cpp_image_get_name
    var il2cpp_image_get_name = null;
    for (var i = 0; i < il2cpp_exports.length; i++) {
        if (il2cpp_exports[i].name === "il2cpp_image_get_name") {
            il2cpp_image_get_name = new NativeFunction(il2cpp_exports[i].address, 'pointer', ['pointer']);
            break;
        }
    }

    // Search assemblies for Holoholo.Rpc.PokemonProto
    var targetImage = null;
    var nsPtr = Memory.allocUtf8String("Holoholo.Rpc");
    var classNamePtr = Memory.allocUtf8String("PokemonProto");

    for (var a = 0; a < numAssemblies; a++) {
        var assembly = assemblies.add(a * Process.pointerSize).readPointer();
        var image = il2cpp_assembly_get_image(assembly);

        // Try to find PokemonProto in this image
        var klass = il2cpp_class_from_name(image, nsPtr, classNamePtr);
        if (!klass.isNull()) {
            targetImage = image;
            send({type: "status", msg: "Found PokemonProto in assembly #" + a});
            if (il2cpp_image_get_name) {
                var imgName = il2cpp_image_get_name(image).readCString();
                send({type: "status", msg: "Image name: " + imgName});
            }
            break;
        }
    }

    if (!targetImage) {
        send({type: "error", msg: "Could not find Holoholo.Rpc.PokemonProto in any assembly"});
        return;
    }

    // Now find PokemonProto class and its fields
    var pokemonProtoClass = il2cpp_class_from_name(targetImage, nsPtr, classNamePtr);
    send({type: "status", msg: "PokemonProto class: " + pokemonProtoClass});

    // Get field offsets for PokemonProto
    var fields = {};
    var fieldNames = [
        "pokemonId_", "cp_", "stamina_", "staminaMax_", "move1_", "move2_", "move3_",
        "individualAttack_", "individualDefense_", "individualStamina_",
        "heightM_", "weightKg_", "nickname_", "pokeball_",
        "cpMultiplier_", "numAdditionalCpMultiplier_",
        "creationTimeMs_", "pokemonDisplay_",
        "isLucky_", "isBad_", "move2IsPurifiedExclusive_",
        "deployedFortId_"
    ];

    for (var f = 0; f < fieldNames.length; f++) {
        var fnPtr = Memory.allocUtf8String(fieldNames[f]);
        var field = il2cpp_class_get_field_from_name(pokemonProtoClass, fnPtr);
        if (!field.isNull()) {
            var offset = il2cpp_field_get_offset(field);
            fields[fieldNames[f]] = offset;
        }
    }

    send({type: "status", msg: "PokemonProto fields resolved: " + JSON.stringify(fields)});

    // Now we need to find PokemonBagImpl or the singleton that holds the inventory
    // Try: Niantic.Holoholo.Internal.PokemonBagImpl
    var bagNsPtr = Memory.allocUtf8String("Niantic.Holoholo.Internal");
    var bagClassPtr = Memory.allocUtf8String("PokemonBagImpl");
    var pokemonBagClass = il2cpp_class_from_name(targetImage, bagNsPtr, bagClassPtr);

    if (pokemonBagClass.isNull()) {
        // Try other namespaces
        var altNs = ["Niantic.Holoholo", "Niantic.Holoholo.Inventory", ""];
        for (var n = 0; n < altNs.length; n++) {
            var nsP = Memory.allocUtf8String(altNs[n]);
            pokemonBagClass = il2cpp_class_from_name(targetImage, nsP, bagClassPtr);
            if (!pokemonBagClass.isNull()) {
                send({type: "status", msg: "Found PokemonBagImpl in namespace: " + altNs[n]});
                break;
            }
        }
    }

    if (pokemonBagClass.isNull()) {
        send({type: "status", msg: "PokemonBagImpl not found directly, searching all classes..."});

        // Enumerate classes in the image to find it
        if (il2cpp_image_get_class_count && il2cpp_image_get_class && il2cpp_class_get_name && il2cpp_class_get_namespace) {
            var classCount = il2cpp_image_get_class_count(targetImage);
            send({type: "status", msg: "Searching " + classCount + " classes..."});

            var found_classes = [];
            for (var c = 0; c < classCount; c++) {
                var cls = il2cpp_image_get_class(targetImage, c);
                if (cls.isNull()) continue;
                var name = il2cpp_class_get_name(cls).readCString();
                if (name && (name.indexOf("PokemonBag") >= 0 || name.indexOf("AllPokemon") >= 0)) {
                    var ns = il2cpp_class_get_namespace(cls).readCString();
                    found_classes.push(ns + "." + name);
                }
            }
            send({type: "status", msg: "Bag-related classes: " + JSON.stringify(found_classes)});
        }
        return;
    }

    // Find GetAllPokemon method
    var getAllMethodName = Memory.allocUtf8String("GetAllPokemon");
    var getAllMethod = il2cpp_class_get_method_from_name(pokemonBagClass, getAllMethodName, 0);

    if (getAllMethod.isNull()) {
        send({type: "status", msg: "GetAllPokemon(0 params) not found, trying with 1 param..."});
        getAllMethod = il2cpp_class_get_method_from_name(pokemonBagClass, getAllMethodName, 1);
    }

    if (getAllMethod.isNull()) {
        send({type: "error", msg: "GetAllPokemon method not found on PokemonBagImpl"});
        // List available methods
        var methodNames = ["GetAllPokemon", "get_AllPokemon", "GetPokemons", "get_Pokemons", "get_allPokemon"];
        for (var m = 0; m < methodNames.length; m++) {
            var mPtr = Memory.allocUtf8String(methodNames[m]);
            for (var p = 0; p <= 3; p++) {
                var meth = il2cpp_class_get_method_from_name(pokemonBagClass, mPtr, p);
                if (!meth.isNull()) {
                    send({type: "status", msg: "Found method: " + methodNames[m] + " (params=" + p + ")"});
                }
            }
        }
        return;
    }

    send({type: "status", msg: "GetAllPokemon method: " + getAllMethod});

    // TODO: We need the PokemonBagImpl singleton instance
    // This requires finding how to get the instance (likely via dependency injection / ServiceLocator)
    // For now, report what we found
    send({type: "status", msg: "READY: PokemonProto class and fields located. Need instance access strategy."});
    send({type: "fields", data: fields});
}

// Delay start to allow game to load
waitAndExtract();
