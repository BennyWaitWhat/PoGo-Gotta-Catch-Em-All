/*
 * Pokemon extraction v3: Find PokemonProto instances directly via targeted heap scan.
 * Avoids whole-process memory scan that crashed v2.
 *
 * Strategy:
 * - Only scan memory regions with [anon:libc_malloc] or empty filename (Mono heap)
 * - Skip regions > 64MB (avoid backing maps, file regions)
 * - Process scan results in chunks to avoid OOM
 */

// Wait for libil2cpp.so to be loaded
var il2cpp = null;
for (var retries = 0; retries < 30; retries++) {
    try {
        il2cpp = Process.getModuleByName("libil2cpp.so");
        if (il2cpp) break;
    } catch(e) {
        // Module not loaded yet, wait
    }
    Thread.sleep(1);
}
if (!il2cpp) {
    send({type: "error", msg: "libil2cpp.so not loaded after 30s"});
    send({type: "done", msg: "FAILED"});
    throw new Error("libil2cpp not loaded");
}
send({type: "status", msg: "libil2cpp.so loaded at " + il2cpp.base});

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
var il2cpp_thread_attach = bind("il2cpp_thread_attach", 'pointer', ['pointer']);

var domain = il2cpp_domain_get();
il2cpp_thread_attach(domain);

var sizePtr = Memory.alloc(4);
var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
var numAssemblies = sizePtr.readS32();

var protoImage = null;
for (var a = 0; a < numAssemblies; a++) {
    var assembly = assemblies.add(a * Process.pointerSize).readPointer();
    var image = il2cpp_assembly_get_image(assembly);
    var imgName = il2cpp_image_get_name(image).readCString();
    if (imgName === "holo-protos.dll") protoImage = image;
}

var pokemonProtoClass = il2cpp_class_from_name(protoImage,
    Memory.allocUtf8String("Holoholo.Rpc"),
    Memory.allocUtf8String("PokemonProto"));

send({type: "status", msg: "PokemonProto class: " + pokemonProtoClass});

// Field offsets (confirmed earlier)
var FIELDS = {
    id: 32, pokemonId: 40, cp: 44, stamina: 48,
    move1: 56, move2: 60, move3: 276,
    ivAtk: 112, ivDef: 116, ivSta: 120,
    heightM: 104, weightKg: 108, cpMultiplier: 124,
    nickname: 184, pokeball: 128,
    creationTimeMs: 160, isLucky: 272, deployedFortId: 64
};

// Build the byte pattern for the klass pointer (little-endian)
var ptrVal = pokemonProtoClass;
var patternBytes = [];
var tmp = ptrVal;
for (var b = 0; b < 8; b++) {
    var byte = tmp.and(0xFF).toInt32();
    patternBytes.push((byte < 16 ? '0' : '') + byte.toString(16));
    tmp = tmp.shr(8);
}
var pattern = patternBytes.join(' ');
send({type: "status", msg: "Pattern: " + pattern});

// Get only HEAP regions - filter by name
var allRanges = Process.enumerateRanges('rw-');
send({type: "status", msg: "Total rw- regions: " + allRanges.length});

// Get range details with file backing info
var ranges = [];
var modulesByName = {};
Process.enumerateModules().forEach(function(m) {
    modulesByName[m.path] = m;
});

// Filter: only anonymous (no file backing) regions of reasonable size
var heapRanges = [];
allRanges.forEach(function(r) {
    if (r.size > 64 * 1024 * 1024) return; // Skip > 64MB
    if (r.size < 4096) return; // Skip < 4KB
    if (r.file) return; // Skip file-backed
    heapRanges.push(r);
});

send({type: "status", msg: "Filtered heap regions: " + heapRanges.length});

// Sample a few to verify
for (var i = 0; i < Math.min(5, heapRanges.length); i++) {
    send({type: "status", msg: "  range[" + i + "]: " + heapRanges[i].base + " size=" + heapRanges[i].size});
}

// Scan in batches with try/catch for safety
var allMatches = [];
var scanned = 0;
var failed = 0;

for (var ri = 0; ri < heapRanges.length; ri++) {
    var r = heapRanges[ri];
    try {
        var matches = Memory.scanSync(r.base, r.size, pattern);
        for (var m = 0; m < matches.length; m++) {
            allMatches.push(matches[m].address);
        }
        scanned++;
    } catch(e) {
        failed++;
    }

    if (ri % 50 === 0 && ri > 0) {
        send({type: "status", msg: "  scanned " + ri + "/" + heapRanges.length + " regions, " + allMatches.length + " matches so far"});
    }

    // Stop early if we have enough matches
    if (allMatches.length > 5000) {
        send({type: "status", msg: "  Found enough matches (" + allMatches.length + "), stopping scan"});
        break;
    }
}

send({type: "status", msg: "Scan complete: " + allMatches.length + " matches in " + scanned + " regions (" + failed + " failed)"});

// Validate matches by reading PokemonProto fields and checking sanity
var pokemon = [];
var seen = {};
var errors = 0;

for (var i = 0; i < allMatches.length; i++) {
    var addr = allMatches[i];

    try {
        // Quick sanity check: pokemonId should be 1-1100, cp should be 10-9999
        var pokemonId = addr.add(FIELDS.pokemonId).readS32();
        var cp = addr.add(FIELDS.cp).readS32();
        var ivAtk = addr.add(FIELDS.ivAtk).readS32();
        var ivDef = addr.add(FIELDS.ivDef).readS32();
        var ivSta = addr.add(FIELDS.ivSta).readS32();

        // Validate: realistic pokemon
        if (pokemonId < 1 || pokemonId > 1100) continue;
        if (cp < 10 || cp > 9999) continue;
        if (ivAtk < 0 || ivAtk > 15) continue;
        if (ivDef < 0 || ivDef > 15) continue;
        if (ivSta < 0 || ivSta > 15) continue;

        var p = {addr: addr.toString()};
        p.id = readInt64(addr, FIELDS.id);
        p.pokemonId = pokemonId;
        p.cp = cp;
        p.stamina = addr.add(FIELDS.stamina).readS32();
        p.move1 = addr.add(FIELDS.move1).readS32();
        p.move2 = addr.add(FIELDS.move2).readS32();
        p.move3 = addr.add(FIELDS.move3).readS32();
        p.ivAtk = ivAtk;
        p.ivDef = ivDef;
        p.ivSta = ivSta;
        p.heightM = addr.add(FIELDS.heightM).readFloat();
        p.weightKg = addr.add(FIELDS.weightKg).readFloat();
        p.cpMultiplier = addr.add(FIELDS.cpMultiplier).readFloat();
        p.pokeball = addr.add(FIELDS.pokeball).readS32();
        p.creationTimeMs = readInt64(addr, FIELDS.creationTimeMs);
        p.isLucky = addr.add(FIELDS.isLucky).readU8() !== 0;

        // Filter validation: cpMultiplier should be 0.094 to 0.9
        if (p.cpMultiplier < 0.05 || p.cpMultiplier > 0.95) continue;
        // height/weight should be reasonable
        if (p.heightM <= 0 || p.heightM > 30) continue;
        if (p.weightKg <= 0 || p.weightKg > 1000) continue;

        // Dedupe by ID
        var idKey = String(p.id);
        if (seen[idKey]) continue;
        seen[idKey] = true;

        // Read nickname
        try {
            var nickPtr = addr.add(FIELDS.nickname).readPointer();
            if (!nickPtr.isNull()) {
                var len = nickPtr.add(0x10).readS32();
                if (len > 0 && len < 50) {
                    p.nickname = nickPtr.add(0x14).readUtf16String(len);
                }
            }
        } catch(e) {}

        pokemon.push(p);
    } catch(e) {
        errors++;
    }
}

send({type: "status", msg: "Validated: " + pokemon.length + " unique pokemon, " + errors + " errors"});

// Send in batches to avoid message size limits
var batchSize = 100;
for (var b = 0; b < pokemon.length; b += batchSize) {
    var batch = pokemon.slice(b, b + batchSize);
    send({type: "pokemon_batch", offset: b, total: pokemon.length, data: batch});
}

send({type: "pokemon_data", count: pokemon.length, data: pokemon});
send({type: "done", msg: "Extracted " + pokemon.length + " pokemon!"});

function readInt64(base, offset) {
    var low = base.add(offset).readU32();
    var high = base.add(offset + 4).readU32();
    if (high === 0) return low;
    return (high * 4294967296) + low;
}
