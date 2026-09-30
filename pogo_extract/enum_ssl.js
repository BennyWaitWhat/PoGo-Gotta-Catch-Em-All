var mods = Process.enumerateModules();
var sslMods = mods.filter(function(m) { return m.name.toLowerCase().indexOf('ssl') >= 0; });
sslMods.forEach(function(m) {
    send('MODULE: ' + m.name + ' @ ' + m.base + ' (path: ' + m.path + ')');
    var addr = Module.findExportByName(m.name, 'SSL_read');
    if (addr) {
        send('  FOUND SSL_read at ' + addr.toString());
    } else {
        send('  SSL_read NOT found in ' + m.name);
    }
});
// Also try full path approach
var fullPath = '/apex/com.android.conscrypt/lib64/libssl.so';
var addr2 = Module.findExportByName(fullPath, 'SSL_read');
send('Full path lookup: ' + (addr2 ? addr2.toString() : 'NULL'));
// Try null (search all modules)
var addr3 = Module.findExportByName(null, 'SSL_read');
send('Null module lookup: ' + (addr3 ? addr3.toString() : 'NULL'));
