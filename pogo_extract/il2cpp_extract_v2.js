/*
 * Pokemon extraction v2: NO HOOKS (avoids conflicts with Pokemod).
 * Directly finds the PokemonBagImpl instance and reads memory.
 *
 * Strategy: Find the singleton via DI container or static references,
 * then call get_AllPokemon via runtime_invoke and read the returned list.
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
var il2cpp_class_get_field_from_name = bind("il2cpp_class_get_field_from_name", 'pointer', ['pointer', 'pointer']);
var il2cpp_class_get_fields = bind("il2cpp_class_get_fields", 'pointer', ['pointer', 'pointer']);
var il2cpp_field_get_name = bind("il2cpp_field_get_name", 'pointer', ['pointer']);
var il2cpp_field_get_offset = bind("il2cpp_field_get_offset", 'int', ['pointer']);
var il2cpp_field_get_value_object = bind("il2cpp_field_get_value_object", 'pointer', ['pointer', 'pointer']);
var il2cpp_runtime_invoke = bind("il2cpp_runtime_invoke", 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
var il2cpp_thread_attach = bind("il2cpp_thread_attach", 'pointer', ['pointer']);
var il2cpp_array_length = bind("il2cpp_array_length", 'int', ['pointer']);
var il2cpp_class_get_static_field_data = bind("il2cpp_class_get_static_field_data", 'pointer', ['pointer']);
var il2cpp_object_get_class = bind("il2cpp_object_get_class", 'pointer', ['pointer']);

var domain = il2cpp_domain_get();
il2cpp_thread_attach(domain);

var sizePtr = Memory.alloc(4);
var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
var numAssemblies = sizePtr.readS32();

// Find images
var gameImage = null, protoImage = null;
for (var a = 0; a < numAssemblies; a++) {
    var assembly = assemblies.add(a * Process.pointerSize).readPointer();
    var image = il2cpp_assembly_get_image(assembly);
    var imgName = il2cpp_image_get_name(image).readCString();
    if (imgName === "holo-game.dll") gameImage = image;
    if (imgName === "holo-protos.dll") protoImage = image;
}

// Find classes
var pokemonBagClass = il2cpp_class_from_name(gameImage,
    Memory.allocUtf8String("Niantic.Holoholo.Internal"),
    Memory.allocUtf8String("PokemonBagImpl"));

var pokemonProtoClass = il2cpp_class_from_name(protoImage,
    Memory.allocUtf8String("Holoholo.Rpc"),
    Memory.allocUtf8String("PokemonProto"));

send({type: "status", msg: "Classes: Bag=" + pokemonBagClass + " Proto=" + pokemonProtoClass});

// PokemonProto field offsets
var FIELDS = {
    id: 32, pokemonId: 40, cp: 44, stamina: 48,
    move1: 56, move2: 60, move3: 276,
    ivAtk: 112, ivDef: 116, ivSta: 120,
    heightM: 104, weightKg: 108, cpMultiplier: 124,
    nickname: 184, pokeball: 128,
    creationTimeMs: 160, pokemonDisplay: 216,
    isLucky: 272, deployedFortId: 64
};

// Find the PokemonBagImpl INSTANCE
// Approach: Look for classes that HOLD a reference to IPokemonBag/PokemonBagImpl
// In Unity DI (Zenject), singletons are stored in containers.
// Alternative: find a known singleton that references it.

// Let's look for NianticInventoryCache or ServiceLocator
var serviceLocatorClasses = [
    {ns: "Niantic.Holoholo", name: "ServiceLocator"},
    {ns: "Niantic.Holoholo", name: "GameMaster"},
    {ns: "Niantic.Holoholo", name: "Singletons"},
    {ns: "", name: "GameMasterClient"},
    {ns: "Niantic.Holoholo", name: "HoloholoGlobalContext"},
    {ns: "Niantic.Holoholo.DependencyInjection", name: "NianticContainer"},
    {ns: "Niantic.Holoholo.DependencyInjection", name: "ServiceProvider"},
];

var foundContainer = null;
for (var sc = 0; sc < serviceLocatorClasses.length; sc++) {
    var nsP = Memory.allocUtf8String(serviceLocatorClasses[sc].ns);
    var cnP = Memory.allocUtf8String(serviceLocatorClasses[sc].name);
    var cls = il2cpp_class_from_name(gameImage, nsP, cnP);
    if (!cls.isNull()) {
        send({type: "status", msg: "Found: " + serviceLocatorClasses[sc].ns + "." + serviceLocatorClasses[sc].name});
        foundContainer = {cls: cls, ns: serviceLocatorClasses[sc].ns, name: serviceLocatorClasses[sc].name};
    }
}

// Check PokemonBagImpl static fields
var staticData = il2cpp_class_get_static_field_data(pokemonBagClass);
send({type: "status", msg: "PokemonBagImpl static data: " + staticData});

if (staticData && !staticData.isNull()) {
    // The static fields cuhv-cuhz had offset 0 in our scan
    // In IL2CPP, static field data is a separate block. Let's read first few pointers.
    for (var si = 0; si < 8; si++) {
        try {
            var val = staticData.add(si * Process.pointerSize).readPointer();
            if (!val.isNull()) {
                try {
                    var objClass = il2cpp_object_get_class(val);
                    if (objClass && !objClass.isNull()) {
                        var cn = il2cpp_class_get_name(objClass).readCString();
                        var cns = il2cpp_class_get_namespace(objClass).readCString();
                        send({type: "status", msg: "  static[" + si + "] = " + val + " -> " + cns + "." + cn});
                    } else {
                        send({type: "status", msg: "  static[" + si + "] = " + val + " (not an object)"});
                    }
                } catch(e) {
                    send({type: "status", msg: "  static[" + si + "] = " + val + " (read error: " + e.message + ")"});
                }
            }
        } catch(e) {}
    }
}

// Alternative approach: find the DiContainer / Zenject container
// Zenject stores bindings in dictionaries. Let's check common patterns.
var zenjectNames = [
    {ns: "Zenject", name: "DiContainer"},
    {ns: "Zenject", name: "SceneContext"},
    {ns: "Zenject", name: "ProjectContext"},
    {ns: "VContainer", name: "LifetimeScope"},
    {ns: "VContainer", name: "Container"},
];

for (var zi = 0; zi < zenjectNames.length; zi++) {
    for (var a = 0; a < numAssemblies; a++) {
        var assembly = assemblies.add(a * Process.pointerSize).readPointer();
        var image = il2cpp_assembly_get_image(assembly);
        var nsP = Memory.allocUtf8String(zenjectNames[zi].ns);
        var cnP = Memory.allocUtf8String(zenjectNames[zi].name);
        var cls = il2cpp_class_from_name(image, nsP, cnP);
        if (!cls.isNull()) {
            var imgName = il2cpp_image_get_name(image).readCString();
            send({type: "status", msg: "DI: " + zenjectNames[zi].ns + "." + zenjectNames[zi].name + " in " + imgName});
            break;
        }
    }
}

// Let's also look at instance fields of PokemonBagImpl to understand the data structure
// Field "cuhl" at offset 16 - likely the dictionary/list holding pokemon
// Let's look for the allPokemon field directly
var allPokemonField = il2cpp_class_get_field_from_name(pokemonBagClass, Memory.allocUtf8String("cuhl"));
send({type: "status", msg: "cuhl field: offset " + (allPokemonField.isNull() ? "N/A" : il2cpp_field_get_offset(allPokemonField))});

// Actually, the cleanest approach given we can't find the instance:
// Search the GC heap for objects of type PokemonBagImpl
// IL2CPP objects start with a klass pointer. We know pokemonBagClass address.
// We can scan memory ranges for this pointer value.

send({type: "status", msg: "Attempting GC heap scan for PokemonBagImpl instances..."});
send({type: "status", msg: "Looking for klass pointer: " + pokemonBagClass});

// Scan all readable memory regions for objects with vtable pointing to our class
var ranges = Process.enumerateRanges('r--');
var instancesFound = [];

// The klass pointer is at offset 0 of every IL2CPP object
var targetKlass = pokemonBagClass;
var patternBytes = [];
// Convert pointer to byte pattern
var targetAddr = targetKlass;
for (var b = 0; b < Process.pointerSize; b++) {
    patternBytes.push(targetAddr.and(0xFF).toInt32());
    targetAddr = targetAddr.shr(8);
}
var pattern = patternBytes.map(function(b) { return (b < 16 ? '0' : '') + b.toString(16); }).join(' ');
send({type: "status", msg: "Scanning for pattern: " + pattern});

var scanCount = 0;
for (var r = 0; r < ranges.length; r++) {
    var range = ranges[r];
    // Only scan heap-like regions (rw- with reasonable size)
    if (range.protection !== 'rw-') continue;
    if (range.size > 500 * 1024 * 1024) continue; // Skip huge regions
    if (range.size < 4096) continue;

    scanCount++;
    var matches = Memory.scanSync(range.base, range.size, pattern);
    for (var mi = 0; mi < matches.length; mi++) {
        instancesFound.push(matches[mi].address);
    }

    if (instancesFound.length > 0 && scanCount > 100) break; // Found some, stop early
}

send({type: "status", msg: "Memory scan: checked " + scanCount + " regions, found " + instancesFound.length + " potential instances"});

if (instancesFound.length > 0 && instancesFound.length < 20) {
    // Validate each potential instance
    var getAllMethod = il2cpp_class_get_method_from_name(pokemonBagClass, Memory.allocUtf8String("get_AllPokemon"), 0);
    var getCountMethod = il2cpp_class_get_method_from_name(pokemonBagClass, Memory.allocUtf8String("get_Count"), 0);

    for (var ii = 0; ii < instancesFound.length && ii < 5; ii++) {
        var instanceAddr = instancesFound[ii];
        send({type: "status", msg: "Trying instance at " + instanceAddr + "..."});

        try {
            // Try calling get_Count on this instance
            var excPtr = Memory.alloc(Process.pointerSize);
            excPtr.writePointer(ptr(0));
            var countResult = il2cpp_runtime_invoke(getCountMethod, instanceAddr, ptr(0), excPtr);
            var exc = excPtr.readPointer();

            if (exc.isNull() && countResult && !countResult.isNull()) {
                // Unbox int32 result: value at object+0x10
                var count = countResult.add(0x10).readS32();
                send({type: "status", msg: "  get_Count() = " + count});

                if (count > 0 && count < 10000) {
                    send({type: "status", msg: "  VALID INSTANCE! Calling get_AllPokemon..."});

                    excPtr.writePointer(ptr(0));
                    var allResult = il2cpp_runtime_invoke(getAllMethod, instanceAddr, ptr(0), excPtr);
                    exc = excPtr.readPointer();

                    if (exc.isNull() && allResult && !allResult.isNull()) {
                        send({type: "status", msg: "  get_AllPokemon returned: " + allResult});
                        extractFromList(allResult, count);
                        break;
                    } else {
                        send({type: "status", msg: "  get_AllPokemon failed (exc=" + exc + ")"});
                    }
                }
            } else {
                if (!exc.isNull()) {
                    send({type: "status", msg: "  Exception thrown"});
                } else {
                    send({type: "status", msg: "  Returned null or invalid"});
                }
            }
        } catch(e) {
            send({type: "status", msg: "  Error: " + e.message});
        }
    }
} else if (instancesFound.length >= 20) {
    send({type: "status", msg: "Too many matches - might be false positives. Try different approach."});
}

function extractFromList(listObj, expectedCount) {
    send({type: "status", msg: "Reading list structure..."});

    // System.Collections.Generic.List<T> layout in IL2CPP:
    // +0x00: klass pointer
    // +0x08: monitor
    // +0x10: _items (T[] array)
    // +0x18: _size (int32)
    var itemsArray = listObj.add(0x10).readPointer();
    var size = listObj.add(0x18).readS32();

    send({type: "status", msg: "List _items=" + itemsArray + " _size=" + size});

    if (size <= 0 || size > 10000 || itemsArray.isNull()) {
        // Maybe it's IReadOnlyList/wrapper, try other offsets
        send({type: "status", msg: "Trying alternative list layouts..."});

        // Try: could be a wrapper around a List
        for (var off = 0x10; off <= 0x30; off += 8) {
            try {
                var inner = listObj.add(off).readPointer();
                if (!inner.isNull()) {
                    var innerItems = inner.add(0x10).readPointer();
                    var innerSize = inner.add(0x18).readS32();
                    if (innerSize > 0 && innerSize < 10000 && !innerItems.isNull()) {
                        send({type: "status", msg: "Found inner list at offset " + off + " with " + innerSize + " items"});
                        itemsArray = innerItems;
                        size = innerSize;
                        break;
                    }
                }
            } catch(e) {}
        }
    }

    if (size <= 0 || itemsArray.isNull()) {
        send({type: "error", msg: "Could not find valid items array"});
        return;
    }

    send({type: "status", msg: "Extracting " + size + " pokemon from array..."});

    // IL2CPP array: [klass(8)][monitor(8)][bounds(8)][max_length(8)][elements...]
    // Elements start at offset 0x20 on 64-bit
    var elemStart = itemsArray.add(0x20);
    var pokemon = [];
    var errors = 0;

    for (var i = 0; i < size; i++) {
        var objPtr = elemStart.add(i * Process.pointerSize).readPointer();
        if (objPtr.isNull()) continue;

        try {
            var p = {};
            p.id = readInt64(objPtr, FIELDS.id);
            p.pokemonId = objPtr.add(FIELDS.pokemonId).readS32();
            p.cp = objPtr.add(FIELDS.cp).readS32();
            p.stamina = objPtr.add(FIELDS.stamina).readS32();
            p.move1 = objPtr.add(FIELDS.move1).readS32();
            p.move2 = objPtr.add(FIELDS.move2).readS32();
            p.move3 = objPtr.add(FIELDS.move3).readS32();
            p.ivAtk = objPtr.add(FIELDS.ivAtk).readS32();
            p.ivDef = objPtr.add(FIELDS.ivDef).readS32();
            p.ivSta = objPtr.add(FIELDS.ivSta).readS32();
            p.heightM = objPtr.add(FIELDS.heightM).readFloat();
            p.weightKg = objPtr.add(FIELDS.weightKg).readFloat();
            p.cpMultiplier = objPtr.add(FIELDS.cpMultiplier).readFloat();
            p.pokeball = objPtr.add(FIELDS.pokeball).readS32();
            p.creationTimeMs = readInt64(objPtr, FIELDS.creationTimeMs);
            p.isLucky = objPtr.add(FIELDS.isLucky).readU8() !== 0;

            // Nickname
            var nickPtr = objPtr.add(FIELDS.nickname).readPointer();
            if (!nickPtr.isNull()) {
                try {
                    var len = nickPtr.add(0x10).readS32();
                    if (len > 0 && len < 50) {
                        p.nickname = nickPtr.add(0x14).readUtf16String(len);
                    } else { p.nickname = ""; }
                } catch(e) { p.nickname = ""; }
            } else { p.nickname = ""; }

            // Deployed fort
            var fortPtr = objPtr.add(FIELDS.deployedFortId).readPointer();
            if (!fortPtr.isNull()) {
                try {
                    var flen = fortPtr.add(0x10).readS32();
                    if (flen > 0 && flen < 100) {
                        p.deployedFortId = fortPtr.add(0x14).readUtf16String(flen);
                    } else { p.deployedFortId = ""; }
                } catch(e) { p.deployedFortId = ""; }
            } else { p.deployedFortId = ""; }

            pokemon.push(p);

            if (pokemon.length % 500 === 0) {
                send({type: "progress", count: pokemon.length, total: size});
            }
        } catch(e) {
            errors++;
            if (errors <= 3) {
                send({type: "status", msg: "Error reading pokemon #" + i + ": " + e.message});
            }
        }
    }

    send({type: "status", msg: "Extraction complete: " + pokemon.length + " pokemon, " + errors + " errors"});

    // Send in batches to avoid message size limits
    var batchSize = 200;
    for (var b = 0; b < pokemon.length; b += batchSize) {
        var batch = pokemon.slice(b, b + batchSize);
        send({type: "pokemon_batch", batch: b / batchSize, data: batch});
    }

    send({type: "pokemon_data", count: pokemon.length, data: pokemon});
    send({type: "done", msg: "Extracted " + pokemon.length + " pokemon successfully!"});
}

function readInt64(base, offset) {
    var low = base.add(offset).readU32();
    var high = base.add(offset + 4).readU32();
    if (high === 0) return low;
    return (high * 4294967296) + low;
}
