/*
 * Full Pokemon extraction: find PokemonBagImpl instance and dump all pokemon.
 *
 * Strategy: Find the instance via static fields, GC handle scanning, or
 * by hooking get_AllPokemon and waiting for the game to call it.
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
var il2cpp_class_from_name = bind("il2cpp_class_from_name", 'pointer', ['pointer', 'pointer', 'pointer']);
var il2cpp_class_get_method_from_name = bind("il2cpp_class_get_method_from_name", 'pointer', ['pointer', 'pointer', 'int']);
var il2cpp_class_get_field_from_name = bind("il2cpp_class_get_field_from_name", 'pointer', ['pointer', 'pointer']);
var il2cpp_field_get_offset = bind("il2cpp_field_get_offset", 'int', ['pointer']);
var il2cpp_field_get_value_object = bind("il2cpp_field_get_value_object", 'pointer', ['pointer', 'pointer']);
var il2cpp_runtime_invoke = bind("il2cpp_runtime_invoke", 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
var il2cpp_thread_attach = bind("il2cpp_thread_attach", 'pointer', ['pointer']);
var il2cpp_array_length = bind("il2cpp_array_length", 'int', ['pointer']);
var il2cpp_string_length = bind("il2cpp_string_length", 'int', ['pointer']);
var il2cpp_string_chars = bind("il2cpp_string_chars", 'pointer', ['pointer']);
var il2cpp_class_get_static_field_data = bind("il2cpp_class_get_static_field_data", 'pointer', ['pointer']);
var il2cpp_method_get_from_reflection = bind("il2cpp_method_get_from_reflection", 'pointer', ['pointer']);
var il2cpp_image_get_class_count = bind("il2cpp_image_get_class_count", 'int', ['pointer']);
var il2cpp_image_get_class = bind("il2cpp_image_get_class", 'pointer', ['pointer', 'int']);
var il2cpp_class_get_name = bind("il2cpp_class_get_name", 'pointer', ['pointer']);
var il2cpp_class_get_namespace = bind("il2cpp_class_get_namespace", 'pointer', ['pointer']);
var il2cpp_class_get_fields = bind("il2cpp_class_get_fields", 'pointer', ['pointer', 'pointer']);
var il2cpp_field_get_name = bind("il2cpp_field_get_name", 'pointer', ['pointer']);
var il2cpp_object_get_class = bind("il2cpp_object_get_class", 'pointer', ['pointer']);

var domain = il2cpp_domain_get();
il2cpp_thread_attach(domain);

var sizePtr = Memory.alloc(4);
var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
var numAssemblies = sizePtr.readS32();

// Find holo-game.dll image
var gameImage = null;
var protoImage = null;
for (var a = 0; a < numAssemblies; a++) {
    var assembly = assemblies.add(a * Process.pointerSize).readPointer();
    var image = il2cpp_assembly_get_image(assembly);
    var imgName = il2cpp_image_get_name(image).readCString();
    if (imgName === "holo-game.dll") gameImage = image;
    if (imgName === "holo-protos.dll") protoImage = image;
}

send({type: "status", msg: "Images found: game=" + (gameImage ? "yes" : "no") + " proto=" + (protoImage ? "yes" : "no")});

// Get PokemonBagImpl class
var bagNs = Memory.allocUtf8String("Niantic.Holoholo.Internal");
var bagName = Memory.allocUtf8String("PokemonBagImpl");
var pokemonBagClass = il2cpp_class_from_name(gameImage, bagNs, bagName);

// Get PokemonProto class (for field offsets)
var protoNs = Memory.allocUtf8String("Holoholo.Rpc");
var protoName = Memory.allocUtf8String("PokemonProto");
var pokemonProtoClass = il2cpp_class_from_name(protoImage, protoNs, protoName);

send({type: "status", msg: "PokemonBagImpl: " + pokemonBagClass + ", PokemonProto: " + pokemonProtoClass});

// PokemonProto field offsets (from previous run)
var FIELDS = {
    id: 32,          // int64 - unique ID
    pokemonId: 40,   // int32 - species (dex number)
    cp: 44,          // int32
    stamina: 48,     // int32
    move1: 56,       // int32 (enum)
    move2: 60,       // int32 (enum)
    move3: 276,      // int32 (enum)
    ivAtk: 112,      // int32
    ivDef: 116,      // int32
    ivSta: 120,      // int32
    heightM: 104,    // float
    weightKg: 108,   // float
    cpMultiplier: 124, // float
    nickname: 184,   // pointer to Il2CppString
    pokeball: 128,   // int32 (enum)
    creationTimeMs: 160, // int64
    pokemonDisplay: 216, // pointer to PokemonDisplayProto
    isLucky: 272,    // bool
    deployedFortId: 64,  // pointer to string
};

// Strategy 1: Check if PokemonBagImpl has static field data (singleton pattern)
if (il2cpp_class_get_static_field_data) {
    var staticData = il2cpp_class_get_static_field_data(pokemonBagClass);
    send({type: "status", msg: "Static field data ptr: " + staticData});

    // Static fields with offset 0 from our earlier scan: cuhv, cuhw, cuhx, cuhy, cuhz
    // These are likely at staticData + 0, +8, +16, +24, +32
    if (staticData && !staticData.isNull()) {
        for (var si = 0; si < 5; si++) {
            var val = staticData.add(si * 8).readPointer();
            send({type: "status", msg: "  static[" + si + "] = " + val});
            if (!val.isNull()) {
                // Could be our instance! Check if it's a valid object
                try {
                    var objClass = il2cpp_object_get_class(val);
                    if (objClass && !objClass.isNull()) {
                        var cn = il2cpp_class_get_name(objClass).readCString();
                        send({type: "status", msg: "    -> class: " + cn});
                    }
                } catch(e) {}
            }
        }
    }
}

// Strategy 2: Hook get_AllPokemon and intercept when game calls it
// The method is at a known address from previous run
var getAllMethod = il2cpp_class_get_method_from_name(pokemonBagClass, Memory.allocUtf8String("get_AllPokemon"), 0);
var getCountMethod = il2cpp_class_get_method_from_name(pokemonBagClass, Memory.allocUtf8String("get_Count"), 0);

send({type: "status", msg: "get_AllPokemon method: " + getAllMethod});
send({type: "status", msg: "get_Count method: " + getCountMethod});

if (getAllMethod && !getAllMethod.isNull()) {
    // In IL2CPP, MethodInfo has the method pointer at offset 0
    var methodPtr = getAllMethod.readPointer();
    send({type: "status", msg: "get_AllPokemon native code at: " + methodPtr});

    // Hook it
    Interceptor.attach(methodPtr, {
        onEnter: function(args) {
            // args[0] = this (PokemonBagImpl instance)
            this.instance = args[0];
            send({type: "status", msg: "get_AllPokemon called! instance=" + this.instance});
        },
        onLeave: function(retval) {
            // retval is the collection/list of PokemonProto objects
            if (retval.isNull()) {
                send({type: "status", msg: "get_AllPokemon returned null"});
                return;
            }

            send({type: "status", msg: "get_AllPokemon returned: " + retval});

            // Try to read it as a List<T> or array
            // IL2CPP List<T> has: [vtable, _items (array), _size (int32)]
            // offset: _items at 0x10, _size at 0x18
            try {
                var itemsArray = retval.add(0x10).readPointer();
                var size = retval.add(0x18).readS32();
                send({type: "status", msg: "List size: " + size + ", items array: " + itemsArray});

                if (size > 0 && size < 10000 && !itemsArray.isNull()) {
                    extractPokemon(itemsArray, size);
                }
            } catch(e) {
                send({type: "status", msg: "List read failed, trying IReadOnlyList..."});
                // Maybe it's returning something else (IReadOnlyList, array, etc)
                try {
                    // Try as raw array: length at +0x18, elements start at +0x20
                    var arrLen = retval.add(0x18).readS32();
                    send({type: "status", msg: "Trying as array, length field: " + arrLen});
                    if (arrLen > 0 && arrLen < 10000) {
                        extractPokemonFromArray(retval, arrLen);
                    }
                } catch(e2) {
                    send({type: "error", msg: "Could not read return value: " + e2.message});
                }
            }
        }
    });

    send({type: "status", msg: "Hook installed on get_AllPokemon. Waiting for game to call it..."});
    send({type: "status", msg: "Open Pokemon inventory in game to trigger the call!"});

    // Also hook get_Count to capture the instance
    if (getCountMethod && !getCountMethod.isNull()) {
        var countMethodPtr = getCountMethod.readPointer();
        Interceptor.attach(countMethodPtr, {
            onEnter: function(args) {
                this.instance = args[0];
            },
            onLeave: function(retval) {
                var count = retval.toInt32();
                send({type: "status", msg: "get_Count called! count=" + count + " instance=" + this.instance});

                // Now call get_AllPokemon ourselves using this instance
                if (count > 0) {
                    send({type: "status", msg: "Invoking get_AllPokemon on captured instance..."});
                    var excPtr = Memory.alloc(Process.pointerSize);
                    excPtr.writePointer(ptr(0));
                    var result = il2cpp_runtime_invoke(getAllMethod, this.instance, ptr(0), excPtr);
                    var exc = excPtr.readPointer();
                    if (!exc.isNull()) {
                        send({type: "error", msg: "runtime_invoke threw exception"});
                    } else if (!result.isNull()) {
                        send({type: "status", msg: "Direct invoke result: " + result});
                        // The result should be processed by our hook above
                    }
                }
            }
        });
        send({type: "status", msg: "Also hooked get_Count"});
    }
}

function extractPokemon(itemsArray, size) {
    send({type: "status", msg: "Extracting " + size + " pokemon..."});
    var pokemon = [];

    // Array elements start at offset 0x20 (after vtable, typeinfo, bounds, max_length)
    var elemStart = itemsArray.add(0x20);

    for (var i = 0; i < size; i++) {
        var objPtr = elemStart.add(i * Process.pointerSize).readPointer();
        if (objPtr.isNull()) continue;

        try {
            var poke = readPokemonProto(objPtr);
            pokemon.push(poke);

            if (pokemon.length % 500 === 0) {
                send({type: "progress", count: pokemon.length, total: size});
            }
        } catch(e) {
            send({type: "status", msg: "Error reading pokemon #" + i + ": " + e.message});
        }
    }

    send({type: "pokemon_data", count: pokemon.length, data: pokemon});
    send({type: "done", msg: "Extracted " + pokemon.length + " pokemon!"});
}

function extractPokemonFromArray(arr, size) {
    send({type: "status", msg: "Extracting " + size + " pokemon from array..."});
    var pokemon = [];
    var elemStart = arr.add(0x20);

    for (var i = 0; i < size; i++) {
        var objPtr = elemStart.add(i * Process.pointerSize).readPointer();
        if (objPtr.isNull()) continue;
        try {
            pokemon.push(readPokemonProto(objPtr));
        } catch(e) {}
    }

    send({type: "pokemon_data", count: pokemon.length, data: pokemon});
    send({type: "done", msg: "Extracted " + pokemon.length + " pokemon!"});
}

function readPokemonProto(ptr) {
    var p = {};
    p.id = readInt64(ptr, FIELDS.id);
    p.pokemonId = ptr.add(FIELDS.pokemonId).readS32();
    p.cp = ptr.add(FIELDS.cp).readS32();
    p.stamina = ptr.add(FIELDS.stamina).readS32();
    p.move1 = ptr.add(FIELDS.move1).readS32();
    p.move2 = ptr.add(FIELDS.move2).readS32();
    p.move3 = ptr.add(FIELDS.move3).readS32();
    p.ivAtk = ptr.add(FIELDS.ivAtk).readS32();
    p.ivDef = ptr.add(FIELDS.ivDef).readS32();
    p.ivSta = ptr.add(FIELDS.ivSta).readS32();
    p.heightM = ptr.add(FIELDS.heightM).readFloat();
    p.weightKg = ptr.add(FIELDS.weightKg).readFloat();
    p.cpMultiplier = ptr.add(FIELDS.cpMultiplier).readFloat();
    p.pokeball = ptr.add(FIELDS.pokeball).readS32();
    p.creationTimeMs = readInt64(ptr, FIELDS.creationTimeMs);
    p.isLucky = ptr.add(FIELDS.isLucky).readU8() !== 0;

    // Read nickname (Il2CppString*)
    var nickPtr = ptr.add(FIELDS.nickname).readPointer();
    if (!nickPtr.isNull()) {
        try {
            var len = nickPtr.add(0x10).readS32();
            if (len > 0 && len < 50) {
                p.nickname = nickPtr.add(0x14).readUtf16String(len);
            } else {
                p.nickname = "";
            }
        } catch(e) { p.nickname = ""; }
    } else {
        p.nickname = "";
    }

    // Read deployed fort id
    var fortPtr = ptr.add(FIELDS.deployedFortId).readPointer();
    if (!fortPtr.isNull()) {
        try {
            var flen = fortPtr.add(0x10).readS32();
            if (flen > 0 && flen < 100) {
                p.deployedFortId = fortPtr.add(0x14).readUtf16String(flen);
            } else {
                p.deployedFortId = "";
            }
        } catch(e) { p.deployedFortId = ""; }
    } else {
        p.deployedFortId = "";
    }

    // Calculate level from cpMultiplier
    p.level = cpMultiplierToLevel(p.cpMultiplier);

    return p;
}

function readInt64(base, offset) {
    // Read as two 32-bit parts for JavaScript safety
    var low = base.add(offset).readU32();
    var high = base.add(offset + 4).readU32();
    // Return as string to avoid precision loss
    if (high === 0) return low;
    return "0x" + high.toString(16) + low.toString(16).padStart(8, '0');
}

function cpMultiplierToLevel(cpm) {
    // CPM to level lookup (approximate)
    var cpms = [0.094,0.135,0.166,0.192,0.215,0.236,0.255,0.273,0.290,0.306,
                0.321,0.335,0.349,0.362,0.375,0.387,0.399,0.411,0.422,0.432,
                0.443,0.453,0.462,0.472,0.481,0.490,0.499,0.508,0.517,0.525,
                0.534,0.542,0.550,0.558,0.566,0.574,0.582,0.589,0.597,0.604,
                0.612,0.619,0.626,0.633,0.640,0.647,0.654,0.661,0.667,0.674,
                0.681,0.688,0.694,0.700,0.706,0.713,0.719,0.725,0.731,0.737,
                0.743,0.749,0.755,0.761,0.767,0.773,0.779,0.784,0.790,0.796,
                0.801,0.807,0.812,0.818,0.823,0.829,0.834,0.840,0.845,0.850,
                0.855,0.860,0.865,0.870,0.875,0.880,0.885,0.890,0.894,0.899];
    var closest = 1;
    var minDiff = 999;
    for (var i = 0; i < cpms.length; i++) {
        var diff = Math.abs(cpm - cpms[i]);
        if (diff < minDiff) {
            minDiff = diff;
            closest = i + 1;  // levels are 1-indexed, half levels are i+0.5
        }
    }
    return closest * 0.5 + 0.5;  // Approximate
}
