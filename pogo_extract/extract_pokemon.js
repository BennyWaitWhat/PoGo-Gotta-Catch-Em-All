/*
 * Extract Pokemon inventory data.
 * Uses native libc write() since Frida's File API doesn't work here.
 */

// Native file I/O via libc
var libc = Process.getModuleByName("libc.so");
var open_addr, write_addr, close_addr;

var exports = libc.enumerateExports();
for (var i = 0; i < exports.length; i++) {
    if (exports[i].name === "open") open_addr = exports[i].address;
    if (exports[i].name === "write") write_addr = exports[i].address;
    if (exports[i].name === "close") close_addr = exports[i].address;
}

var libc_open = new NativeFunction(open_addr, 'int', ['pointer', 'int', 'int']);
var libc_write = new NativeFunction(write_addr, 'int', ['int', 'pointer', 'int']);
var libc_close = new NativeFunction(close_addr, 'int', ['int']);

function writeToFile(path, content) {
    var pathPtr = Memory.allocUtf8String(path);
    // O_WRONLY | O_CREAT | O_TRUNC = 0x241
    var fd = libc_open(pathPtr, 0x241, 0o666);
    if (fd < 0) return false;
    var contentPtr = Memory.allocUtf8String(content);
    var len = content.length;
    libc_write(fd, contentPtr, len);
    libc_close(fd);
    return true;
}

// Test write immediately
var ok = writeToFile("/sdcard/pogo_extract_status.txt", "SCRIPT_LOADED: Java=" + (typeof Java));
if (!ok) {
    // Try alternate path
    writeToFile("/data/local/tmp/pogo_extract_status.txt", "SCRIPT_LOADED: Java=" + (typeof Java));
}

// Main extraction
if (typeof Java !== "undefined" && Java.available) {
    writeToFile("/sdcard/pogo_extract_status.txt", "JAVA_OK: enumerating classes...");

    Java.perform(function() {
        var found = [];
        Java.enumerateLoadedClasses({
            onMatch: function(name) {
                var lower = name.toLowerCase();
                if (lower.indexOf("pokemon") >= 0 || lower.indexOf("inventory") >= 0 ||
                    lower.indexOf("pokemonproto") >= 0 || lower.indexOf("holoholo") >= 0) {
                    found.push(name);
                }
            },
            onComplete: function() {
                var result = "CLASSES_FOUND: " + found.length + "\n" + found.join("\n");
                writeToFile("/sdcard/pogo_extract_classes.txt", result);
                writeToFile("/sdcard/pogo_extract_status.txt", "DONE: " + found.length + " classes found");
            }
        });
    });
} else {
    writeToFile("/sdcard/pogo_extract_status.txt", "NO_JAVA");
}
