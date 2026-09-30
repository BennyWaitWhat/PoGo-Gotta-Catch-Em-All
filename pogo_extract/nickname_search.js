/*
 * Find IL2CPP classes/methods related to nickname/rename pokemon.
 * Chunks work via setImmediate to avoid blocking the JS thread for too long.
 */

var il2cpp = Process.getModuleByName("libil2cpp.so");
var exports_map = {};
il2cpp.enumerateExports().forEach(function(e) {
    if (e.name.indexOf("il2cpp_") === 0) exports_map[e.name] = e.address;
});

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
var il2cpp_class_get_name = bind("il2cpp_class_get_name", 'pointer', ['pointer']);
var il2cpp_class_get_namespace = bind("il2cpp_class_get_namespace", 'pointer', ['pointer']);
var il2cpp_class_get_methods = bind("il2cpp_class_get_methods", 'pointer', ['pointer', 'pointer']);
var il2cpp_method_get_name = bind("il2cpp_method_get_name", 'pointer', ['pointer']);
var il2cpp_method_get_param_count = bind("il2cpp_method_get_param_count", 'int', ['pointer']);
var il2cpp_method_get_param = bind("il2cpp_method_get_param", 'pointer', ['pointer', 'int']);
var il2cpp_method_get_param_name = bind("il2cpp_method_get_param_name", 'pointer', ['pointer', 'int']);
var il2cpp_method_get_return_type = bind("il2cpp_method_get_return_type", 'pointer', ['pointer']);
var il2cpp_type_get_name = bind("il2cpp_type_get_name", 'pointer', ['pointer']);
var il2cpp_thread_attach = bind("il2cpp_thread_attach", 'pointer', ['pointer']);

var domain = il2cpp_domain_get();
il2cpp_thread_attach(domain);

var sizePtr = Memory.alloc(4);
var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
var numAssemblies = sizePtr.readS32();
send({type: "status", msg: "Assemblies: " + numAssemblies});

// Patterns
var classPatterns = ["nickname", "rename", "pokemonbag", "pokemoninventory", "inventoryservice", "pokemonservice", "playeractionservice", "nicknamepokemon", "useraction"];
var methodPatterns = ["nickname", "rename", "setnick"];

var classMatches = [];
var methodMatches = [];

function methodSignature(method) {
    try {
        var name = il2cpp_method_get_name(method).readCString();
        var paramCount = il2cpp_method_get_param_count(method);
        var params = [];
        for (var i = 0; i < paramCount; i++) {
            var ptype = il2cpp_method_get_param(method, i);
            var pname = il2cpp_method_get_param_name(method, i);
            var typeName = ptype && !ptype.isNull() ? il2cpp_type_get_name(ptype).readCString() : "?";
            var paramName = pname && !pname.isNull() ? pname.readCString() : "p" + i;
            params.push(typeName + " " + paramName);
        }
        var rtype = il2cpp_method_get_return_type(method);
        var rtName = rtype && !rtype.isNull() ? il2cpp_type_get_name(rtype).readCString() : "void";
        return rtName + " " + name + "(" + params.join(", ") + ")";
    } catch (e) {
        return "<sig-err>";
    }
}

function shouldSkipImage(name) {
    if (!name) return true;
    if (name.indexOf("System.") === 0) return true;
    if (name.indexOf("UnityEngine.") === 0) return true;
    if (name.indexOf("mscorlib") === 0) return true;
    if (name.indexOf("netstandard") === 0) return true;
    if (name.indexOf("Mono.") === 0) return true;
    if (name === "Unity.") return true;
    return false;
}

// Collect images first
var imagesToScan = [];
for (var ai = 0; ai < numAssemblies; ai++) {
    var assembly = assemblies.add(ai * Process.pointerSize).readPointer();
    var image = il2cpp_assembly_get_image(assembly);
    var imgName = il2cpp_image_get_name(image).readCString();
    if (shouldSkipImage(imgName)) continue;
    imagesToScan.push({image: image, name: imgName});
}
send({type: "status", msg: "Images to scan: " + imagesToScan.length});

// Process one image at a time, scheduled via setImmediate
var imgIdx = 0;

function processNextImage() {
    if (imgIdx >= imagesToScan.length) {
        // Done
        send({type: "class_matches", count: classMatches.length, data: classMatches});
        send({type: "method_matches", count: methodMatches.length, data: methodMatches});
        send({type: "done", msg: "Search complete"});
        return;
    }

    var img = imagesToScan[imgIdx++];
    try {
        var classCount = il2cpp_image_get_class_count(img.image);
        var localCM = 0, localMM = 0;

        for (var ci = 0; ci < classCount; ci++) {
            var klass = il2cpp_image_get_class(img.image, ci);
            if (klass.isNull()) continue;

            var cnamePtr = il2cpp_class_get_name(klass);
            if (cnamePtr.isNull()) continue;
            var cname = cnamePtr.readCString();
            if (!cname) continue;
            var lcname = cname.toLowerCase();

            var cnsPtr = il2cpp_class_get_namespace(klass);
            var cns = cnsPtr && !cnsPtr.isNull() ? cnsPtr.readCString() : "";

            var classHit = false;
            for (var p = 0; p < classPatterns.length; p++) {
                if (lcname.indexOf(classPatterns[p]) >= 0) { classHit = true; break; }
            }
            if (classHit) {
                classMatches.push({image: img.name, ns: cns, name: cname, ptr: klass.toString()});
                localCM++;
            }

            var nsRelevant = (cns && (cns.indexOf("Niantic") >= 0 || cns.indexOf("Holoholo") >= 0)) || classHit;
            if (!nsRelevant) continue;

            try {
                var iter = Memory.alloc(Process.pointerSize);
                iter.writePointer(ptr(0));
                var method;
                while ((method = il2cpp_class_get_methods(klass, iter)) && !method.isNull()) {
                    var mnamePtr = il2cpp_method_get_name(method);
                    if (mnamePtr.isNull()) continue;
                    var mname = mnamePtr.readCString();
                    if (!mname) continue;
                    var lmname = mname.toLowerCase();

                    var methodHit = false;
                    for (var mp = 0; mp < methodPatterns.length; mp++) {
                        if (lmname.indexOf(methodPatterns[mp]) >= 0) { methodHit = true; break; }
                    }
                    if (methodHit) {
                        methodMatches.push({
                            image: img.name,
                            ns: cns,
                            klass: cname,
                            method: mname,
                            sig: methodSignature(method),
                            ptr: method.toString()
                        });
                        localMM++;
                    }
                }
            } catch (e) {}
        }

        send({type: "img_done", idx: imgIdx, total: imagesToScan.length, name: img.name, classes: classCount, classMatches: localCM, methodMatches: localMM});
    } catch (e) {
        send({type: "img_err", name: img.name, err: e.message});
    }

    // Schedule next image with a short delay to keep the JS thread responsive
    setTimeout(processNextImage, 0);
}

processNextImage();
