const il2cpp = Process.findModuleByName('libil2cpp.so');
const libnotmain = Process.findModuleByName('libnotmain.so');
const libunity = Process.findModuleByName('libunity.so');
send({
  pid: Process.id,
  modules_total: Process.enumerateModules().length,
  il2cpp_base: il2cpp ? il2cpp.base.toString() : null,
  il2cpp_size: il2cpp ? il2cpp.size : null,
  libnotmain_base: libnotmain ? libnotmain.base.toString() : null,
  libunity_base: libunity ? libunity.base.toString() : null
});
