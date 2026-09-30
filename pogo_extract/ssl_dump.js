/*
 * Frida script: Hook SSL_read in PoGO to capture decrypted network data.
 * Writes large responses (likely inventory) to /sdcard/pogo_capture/
 *
 * Usage: frida -U -p <PID> -l ssl_dump.js
 */

var CAPTURE_DIR = "/sdcard/pogo_capture/";
var MIN_SIZE_TO_SAVE = 50000; // Only save responses > 50KB (inventory is 1-5MB)
var sessionData = {};
var captureCount = 0;
var totalBytesRead = 0;
var capturing = true;

// Output dir must be created before running (adb shell mkdir -p /sdcard/pogo_capture)

// Find SSL_read in the system SSL library
var sslLib = "libssl.so";
var ssl_read_addr = Module.findExportByName(sslLib, "SSL_read");
var ssl_write_addr = Module.findExportByName(sslLib, "SSL_write");

if (!ssl_read_addr) {
    // Try full path
    ssl_read_addr = Module.findExportByName("/apex/com.android.conscrypt/lib64/libssl.so", "SSL_read");
    ssl_write_addr = Module.findExportByName("/apex/com.android.conscrypt/lib64/libssl.so", "SSL_write");
}

if (!ssl_read_addr) {
    send({type: 'error', msg: 'SSL_read not found!'});
} else {
    send({type: 'info', msg: 'SSL_read found at ' + ssl_read_addr});
    send({type: 'info', msg: 'SSL_write found at ' + ssl_write_addr});
    send({type: 'info', msg: 'Hooking... Open Pokemon storage in-game to trigger inventory fetch.'});

    // Track SSL sessions by SSL pointer
    Interceptor.attach(ssl_read_addr, {
        onEnter: function(args) {
            this.ssl = args[0].toString();
            this.buf = args[1];
            this.num = args[2].toInt32();
        },
        onLeave: function(retval) {
            if (!capturing) return;
            var size = retval.toInt32();
            if (size <= 0) return;

            totalBytesRead += size;

            // Accumulate data per SSL session
            if (!sessionData[this.ssl]) {
                sessionData[this.ssl] = [];
            }
            var chunk = Memory.readByteArray(this.buf, size);
            sessionData[this.ssl].push({size: size, data: chunk});

            // Calculate total size for this session
            var totalSize = 0;
            for (var i = 0; i < sessionData[this.ssl].length; i++) {
                totalSize += sessionData[this.ssl][i].size;
            }

            // If accumulated > threshold, likely inventory data - save it
            if (totalSize >= MIN_SIZE_TO_SAVE) {
                captureCount++;
                var filename = CAPTURE_DIR + "capture_" + captureCount + "_" + totalSize + "b.bin";

                // Combine all chunks
                var combined = new Uint8Array(totalSize);
                var offset = 0;
                for (var i = 0; i < sessionData[this.ssl].length; i++) {
                    var arr = new Uint8Array(sessionData[this.ssl][i].data);
                    combined.set(arr, offset);
                    offset += sessionData[this.ssl][i].size;
                }

                // Write to file
                var file = new File(filename, "wb");
                file.write(combined.buffer);
                file.flush();
                file.close();

                send({type: 'capture', file: filename, size: totalSize, session: this.ssl});

                // Reset this session
                sessionData[this.ssl] = [];
            }
        }
    });

    // Also hook SSL_write to log what requests are being made
    if (ssl_write_addr) {
        Interceptor.attach(ssl_write_addr, {
            onEnter: function(args) {
                if (!capturing) return;
                var size = args[2].toInt32();
                if (size > 100) {
                    // Log request sizes to help identify inventory request
                    send({type: 'write', size: size, ssl: args[0].toString()});
                }
            }
        });
    }
}

// RPC to control capture
rpc.exports = {
    stop: function() {
        capturing = false;
        send({type: 'info', msg: 'Capture stopped. Total bytes read: ' + totalBytesRead});
        // Flush any remaining session data above a lower threshold
        Object.keys(sessionData).forEach(function(ssl) {
            var totalSize = 0;
            for (var i = 0; i < sessionData[ssl].length; i++) {
                totalSize += sessionData[ssl][i].size;
            }
            if (totalSize > 10000) { // Save anything > 10KB on stop
                captureCount++;
                var filename = CAPTURE_DIR + "final_" + captureCount + "_" + totalSize + "b.bin";
                var combined = new Uint8Array(totalSize);
                var offset = 0;
                for (var i = 0; i < sessionData[ssl].length; i++) {
                    var arr = new Uint8Array(sessionData[ssl][i].data);
                    combined.set(arr, offset);
                    offset += sessionData[ssl][i].size;
                }
                var file = new File(filename, "wb");
                file.write(combined.buffer);
                file.flush();
                file.close();
                send({type: 'capture', file: filename, size: totalSize, session: ssl});
            }
        });
        return 'Done. ' + captureCount + ' files captured.';
    },
    status: function() {
        return {
            totalBytesRead: totalBytesRead,
            captureCount: captureCount,
            activeSessions: Object.keys(sessionData).length
        };
    }
};
