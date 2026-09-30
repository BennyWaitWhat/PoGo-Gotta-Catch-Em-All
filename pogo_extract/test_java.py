"""Quick test: does frida-server's Java bridge work at all?"""
import frida, time

device = frida.get_device_manager().add_remote_device('127.0.0.1:31337')
pid = device.spawn(['com.android.settings'])
session = device.attach(pid)
device.resume(pid)
time.sleep(5)

JS = """
// Check all available global objects
var globals = Object.getOwnPropertyNames(globalThis).sort();
send("Globals: " + globals.join(", "));
send("Script.runtime: " + Script.runtime);
send("Process.platform: " + Process.platform);
send("Process.arch: " + Process.arch);
"""

script = session.create_script(JS, runtime='v8')
script.on('message', lambda m, d: print(f"  {m.get('payload', m)}"))
script.load()
time.sleep(3)
session.detach()
device.kill(pid)
print("Done")
