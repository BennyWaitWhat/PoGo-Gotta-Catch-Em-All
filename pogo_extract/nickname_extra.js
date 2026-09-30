/* Quick: list methods of PokemonBagService and PokemonInfoPanel and NicknamePokemonProto. */
var il2cpp = Process.getModuleByName("libil2cpp.so");
var exports_map = {};
il2cpp.enumerateExports().forEach(function(e) {
    if (e.name.indexOf("il2cpp_") === 0) exports_map[e.name] = e.address;
});
function bind(n, r, a) { return exports_map[n] ? new NativeFunction(exports_map[n], r, a) : null; }

var dG = bind("il2cpp_domain_get",'pointer',[]);
var dGA = bind("il2cpp_domain_get_assemblies",'pointer',['pointer','pointer']);
var aGI = bind("il2cpp_assembly_get_image",'pointer',['pointer']);
var iGN = bind("il2cpp_image_get_name",'pointer',['pointer']);
var cFN = bind("il2cpp_class_from_name",'pointer',['pointer','pointer','pointer']);
var cGM = bind("il2cpp_class_get_methods",'pointer',['pointer','pointer']);
var mGN = bind("il2cpp_method_get_name",'pointer',['pointer']);
var mGPC = bind("il2cpp_method_get_param_count",'int',['pointer']);
var mGP = bind("il2cpp_method_get_param",'pointer',['pointer','int']);
var mGPN = bind("il2cpp_method_get_param_name",'pointer',['pointer','int']);
var mGRT = bind("il2cpp_method_get_return_type",'pointer',['pointer']);
var tGN = bind("il2cpp_type_get_name",'pointer',['pointer']);
var tA = bind("il2cpp_thread_attach",'pointer',['pointer']);
var cGF = bind("il2cpp_class_get_fields",'pointer',['pointer','pointer']);
var fGN = bind("il2cpp_field_get_name",'pointer',['pointer']);
var fGT = bind("il2cpp_field_get_type",'pointer',['pointer']);

var dom = dG(); tA(dom);
var sp = Memory.alloc(4);
var asms = dGA(dom, sp);
var na = sp.readS32();

function findClass(ns, name) {
    var nsP = Memory.allocUtf8String(ns);
    var nP = Memory.allocUtf8String(name);
    for (var i = 0; i < na; i++) {
        var img = aGI(asms.add(i*Process.pointerSize).readPointer());
        var k = cFN(img, nsP, nP);
        if (!k.isNull()) return {klass: k, image: iGN(img).readCString()};
    }
    return null;
}

function dumpMethods(clsInfo, label) {
    if (!clsInfo) { send({type:'msg', msg: label + ': NOT FOUND'}); return; }
    send({type:'msg', msg: '=== ' + label + ' (' + clsInfo.image + ') ==='});
    var iter = Memory.alloc(Process.pointerSize);
    iter.writePointer(ptr(0));
    var m;
    var methods = [];
    while ((m = cGM(clsInfo.klass, iter)) && !m.isNull()) {
        try {
            var name = mGN(m).readCString();
            var pc = mGPC(m);
            var params = [];
            for (var i = 0; i < pc; i++) {
                var pt = mGP(m, i);
                var pn = mGPN(m, i);
                params.push((pt && !pt.isNull() ? tGN(pt).readCString() : '?') + ' ' + (pn && !pn.isNull() ? pn.readCString() : 'p'+i));
            }
            var rt = mGRT(m);
            var rn = rt && !rt.isNull() ? tGN(rt).readCString() : 'void';
            methods.push({name: name, sig: rn + ' ' + name + '(' + params.join(', ') + ')', ptr: m.toString()});
        } catch (e) {}
    }
    send({type: 'methods', label: label, image: clsInfo.image, data: methods});
}

dumpMethods(findClass("Niantic.Holoholo.Services", "PokemonBagService"), "PokemonBagService");
dumpMethods(findClass("Niantic.Holoholo.Services", "IPokemonBagService"), "IPokemonBagService");
dumpMethods(findClass("Niantic.Holoholo.UI.Pokemon", "PokemonInfoPanel"), "PokemonInfoPanel");
dumpMethods(findClass("Holoholo.Rpc", "NicknamePokemonProto"), "NicknamePokemonProto");
dumpMethods(findClass("Holoholo.Rpc", "NicknamePokemonOutProto"), "NicknamePokemonOutProto");
send({type: 'done'});
