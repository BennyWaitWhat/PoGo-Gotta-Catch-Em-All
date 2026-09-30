// Minimal frida-inject viability probe: does injecting LATE (game already up) + reaching IL2CPP work
// without the gadget-script-mode fault? Logs to BOTH stdout (frida-inject forwards console.log) and
// logcat tag "finject" (so it survives even if stdout is detached). Read-only — touches nothing.
function L(m) {
  try { console.log("[finject] " + m); } catch (e) {}
  try {
    var w = new NativeFunction(Module.findExportByName("liblog.so", "__android_log_write"), "int", ["int", "pointer", "pointer"]);
    w(3, Memory.allocUtf8String("finject"), Memory.allocUtf8String(m));
  } catch (e) {}
}
L("probe start — runtime check");
try {
  var il = Process.findModuleByName("libil2cpp.so");
  L("libil2cpp.so: " + (il ? il.base : "NOT FOUND"));
  if (!il) { L("ABORT no il2cpp"); }
  else {
    var e = {};
    il.enumerateExports().forEach(function (x) { if (x.name.indexOf("il2cpp_") === 0) e[x.name] = x.address; });
    L("il2cpp exports found: " + Object.keys(e).length);
    var dG = new NativeFunction(e["il2cpp_domain_get"], "pointer", []);
    var tA = new NativeFunction(e["il2cpp_thread_attach"], "pointer", ["pointer"]);
    var dom = dG();
    L("domain: " + dom);
    tA(dom);
    L("thread_attach ok");
    var dGA = new NativeFunction(e["il2cpp_domain_get_assemblies"], "pointer", ["pointer", "pointer"]);
    var aGI = new NativeFunction(e["il2cpp_assembly_get_image"], "pointer", ["pointer"]);
    var iGN = new NativeFunction(e["il2cpp_image_get_name"], "pointer", ["pointer"]);
    var iGCC = new NativeFunction(e["il2cpp_image_get_class_count"], "uint32", ["pointer"]);
    var iGC = new NativeFunction(e["il2cpp_image_get_class"], "pointer", ["pointer", "uint32"]);
    var CGN = new NativeFunction(e["il2cpp_class_get_name"], "pointer", ["pointer"]);
    var sp = Memory.alloc(4); var a = dGA(dom, sp); var n = sp.readS32();
    L("assemblies: " + n);
    var found = false;
    for (var i = 0; i < n && !found; i++) {
      var im = aGI(a.add(i * Process.pointerSize).readPointer());
      if (iGN(im).readCString() !== "holo-game.dll") continue;
      var cnt = iGCC(im);
      for (var j = 0; j < cnt; j++) {
        var k = iGC(im, j); if (k.isNull()) continue;
        try { if (CGN(k).readCString() === "PokeballThrow") { L("FOUND PokeballThrow @ " + k); found = true; break; } } catch (er) {}
      }
    }
    L("PROBE DONE found=" + found + " — frida-inject + IL2CPP WORKS, no fault");
  }
} catch (err) { L("PROBE ERROR: " + err); }
