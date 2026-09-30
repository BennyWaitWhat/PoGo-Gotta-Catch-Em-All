console.log('[pwned] hello from injected agent');
console.log('[pwned] modules: ' + Process.enumerateModules().length);
const il2cpp = Process.findModuleByName('libil2cpp.so');
console.log('[pwned] il2cpp: ' + (il2cpp ? il2cpp.base : 'NOT FOUND'));
setInterval(() => {}, 1000);
