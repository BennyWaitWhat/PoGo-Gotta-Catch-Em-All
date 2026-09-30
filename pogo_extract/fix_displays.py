"""
Fetch missing display data for pokemon where display_ptr is in different chunk.
"""
import json, subprocess, struct, time
from concurrent.futures import ThreadPoolExecutor, as_completed

ADB = ['adb', '-s', '100.98.158.56:5555']
PARALLEL = 15

def adb_bin(cmd, timeout=30):
    return subprocess.run(ADB + ['exec-out', f'su -c "{cmd}"'], capture_output=True, timeout=timeout).stdout

def adb_text(cmd):
    return subprocess.run(ADB + ['shell', f'su -c "{cmd}"'], capture_output=True, text=True, timeout=15).stdout

pid = int(adb_text("pidof com.nianticlabs.pokemongo").strip().split()[0])
print(f"PID: {pid}", flush=True)

data = json.load(open('pokemon_v3.json'))
print(f"Total: {len(data)}", flush=True)

missing = [p for p in data if not p.get('display_raw')]
print(f"Missing display: {len(missing)}", flush=True)

# Group missing display ptrs by 4KB page
pages_to_idx = {}
for i, p in enumerate(data):
    if p.get('display_raw'): continue
    ptr_str = p.get('display_ptr', '')
    try:
        ptr = int(ptr_str, 16)
    except: continue
    if not (0x70_00000000 < ptr < 0x90_00000000): continue
    page = (ptr // 4096) * 4096
    offset = ptr - page
    pages_to_idx.setdefault(page, []).append((i, offset))

print(f"Unique pages to read: {len(pages_to_idx)}", flush=True)

def read_page(page):
    bs = 4096
    skip = page // bs
    return page, adb_bin(f"dd if=/proc/{pid}/mem bs={bs} skip={skip} count=1 2>/dev/null", timeout=30)

t0 = time.time()
page_data = {}
done = 0
with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
    futs = {ex.submit(read_page, pg): pg for pg in pages_to_idx}
    for f in as_completed(futs):
        page, d = f.result()
        page_data[page] = d
        done += 1
        if done % 50 == 0:
            print(f"  {done}/{len(pages_to_idx)} pages in {time.time()-t0:.0f}s", flush=True)

print(f"Read {len(page_data)} pages in {time.time()-t0:.1f}s", flush=True)

# Apply
enriched = 0
for page, idx_list in pages_to_idx.items():
    pdata = page_data.get(page, b'')
    if not pdata: continue
    for idx, offset in idx_list:
        if offset + 200 <= len(pdata):
            data[idx]['display_raw'] = pdata[offset:offset+200].hex()
            enriched += 1

print(f"Enriched {enriched} pokemon", flush=True)

with open('pokemon_v3.json', 'w') as f:
    json.dump(data, f, indent=2)
print("Saved.", flush=True)
