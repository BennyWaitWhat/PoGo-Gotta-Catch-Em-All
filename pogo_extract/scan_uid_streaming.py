"""Stream from adb shell dd and search for known UID patterns to locate klass pointer."""
import subprocess, struct, sys, os, re

KNOWN_UIDS = {
    -6689107601798619759: 'Growlithe',
    2614813629814984889: 'Corsola',
    4844408966494081688: 'Xerneas',
    5263403840049189255: 'Geodude',
    -7232814157734274823: 'Zapdos'
}
UID_PATTERNS = {struct.pack('<q', uid): name for uid, name in KNOWN_UIDS.items()}

PID = sys.argv[1]
ADB = ['adb', '-s', '100.98.158.56:5555']

# Read maps
maps_text = subprocess.check_output(ADB + ['shell', f'su -c "cat /proc/{PID}/maps"'], text=True)
candidates = []
for line in maps_text.splitlines():
    parts = line.split()
    if len(parts) < 5: continue
    if 'rw-p' not in parts[1]: continue
    sm = parts[0].split('-')
    start = int(sm[0], 16); end = int(sm[1], 16)
    if start < 0x6000000000 or start > 0x8000000000: continue
    size = end - start
    if size < 0x1000: continue
    rest = ' '.join(parts[5:]) if len(parts) > 5 else ''
    if 'dalvik' in rest or 'stack' in rest: continue
    if rest.startswith('/'): continue
    candidates.append((start, end, rest))

# Sort: try ones near 0x737f and 0x74f first (where prior anchors lived)
def priority(c):
    s = c[0]
    if 0x737f000000 <= s < 0x7380000000: return 0
    if 0x74f0000000 <= s < 0x74f4000000: return 1
    if 0x73000000 <= s < 0x76000000: return 2
    return 3
candidates.sort(key=priority)

print(f'Scanning {len(candidates)} regions, {sum(e-s for s,e,_ in candidates)/1024/1024:.1f} MB total', flush=True)

found = {}
for i, (start, end, label) in enumerate(candidates):
    size = end - start
    # Stream the region
    cmd = ADB + ['shell', f'su -c "dd if=/proc/{PID}/mem bs=4096 skip={start//4096} count={size//4096} status=none 2>/dev/null"']
    try:
        data = subprocess.check_output(cmd, timeout=120)
    except Exception as e:
        print(f'  [{i}/{len(candidates)}] {hex(start)} ERR: {e}', flush=True)
        continue
    if len(data) < 32:
        continue
    region_hits = 0
    for pat, name in UID_PATTERNS.items():
        idx = 0
        while True:
            x = data.find(pat, idx)
            if x < 0: break
            if x >= 0x10:
                bind_off = x - 0x10
                klass = struct.unpack_from('<Q', data, bind_off)[0]
                tag_id = struct.unpack_from('<i', data, bind_off + 0x18)[0]
                if 0x6000000000 < klass < 0x8000000000 and 0 <= tag_id <= 30:
                    addr = start + bind_off
                    key = (name, klass, tag_id)
                    if key not in found:
                        found[key] = addr
                        print(f'  HIT {name} addr=0x{addr:x} klass=0x{klass:x} tag={tag_id}', flush=True)
                        region_hits += 1
            idx = x + 1
    if region_hits or i % 50 == 0:
        print(f'  [{i+1}/{len(candidates)}] {hex(start)} ({size/1024/1024:.2f} MB) hits={region_hits}', flush=True)
    # Stop early if we have multiple hits
    if len(found) >= 5:
        print('Found enough samples to determine klass; stopping early', flush=True)
        break

print('\n=== Results ===')
from collections import Counter
klass_counter = Counter(k[1] for k in found.keys())
for k, c in klass_counter.most_common(5):
    print(f'klass=0x{k:x}: {c} bindings')
