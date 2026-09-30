"""Watch for PGP plug-in via USB-C and dump everything we can find about it."""
import subprocess, time, sys
sys.stdout.reconfigure(line_buffering=True)
ADB = ['adb','-s','100.98.158.56:5555']

def sh(cmd, root=False):
    full = ADB + ['shell']
    if root: full += ['su','-c', cmd]
    else: full += [cmd]
    try: return subprocess.check_output(full, text=True, stderr=subprocess.STDOUT, timeout=10).strip()
    except Exception as e: return f"ERR: {e}"

def list_usb_devices():
    out = sh('ls /sys/bus/usb/devices/', root=True)
    return [d for d in out.split() if d and not d.startswith('usb')]

def probe_device(dev):
    info = {}
    for f in ['idVendor','idProduct','manufacturer','product','serial','bDeviceClass','bDeviceSubClass','bDeviceProtocol','bMaxPacketSize0','bcdDevice','speed']:
        info[f] = sh(f'cat /sys/bus/usb/devices/{dev}/{f} 2>/dev/null', root=True)
    return info

print(f"Phone date: {sh('date')}")
print("Initial USB devices:")
baseline = list_usb_devices()
for d in baseline:
    info = probe_device(d)
    if info.get('idVendor'):
        print(f"  {d}: vendor={info.get('idVendor')} product={info.get('idProduct')} mfg={info.get('manufacturer','')} name={info.get('product','')}")

print("\nWaiting for new USB device (plug in PGP now)...")
print("Watching for changes every 2s, will exit when new device appears or after 5min")
start = time.time()
new_dev = None
while time.time() - start < 300:
    cur = list_usb_devices()
    diff = [d for d in cur if d not in baseline]
    if diff:
        new_dev = diff[0]
        print(f"\n*** NEW DEVICE: {new_dev} ***")
        info = probe_device(new_dev)
        for k, v in info.items():
            print(f"  {k}: {v}")
        # Look for HID interfaces
        ifaces = sh(f'ls /sys/bus/usb/devices/{new_dev}/ 2>/dev/null', root=True)
        print(f"\nInterfaces / files:\n{ifaces}")
        # Recent dmesg
        print(f"\nRecent dmesg:")
        print(sh('dmesg | tail -20', root=True))
        break
    time.sleep(2)

if not new_dev:
    print("Timeout - no new device detected")
