"""
Follow-up pass: read PokemonDisplayProto for each pokemon.
Groups display pointers by 4KB page, batches reads.
"""
import subprocess, struct, json, time, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ADB = ['adb', '-s', '100.98.158.56:5555']
PARALLEL = 12

def adb_bin(cmd, timeout=30):
    return subprocess.run(ADB + ['exec-out', f'su -c "{cmd}"'], capture_output=True, timeout=timeout).stdout

def adb_text(cmd):
    return subprocess.run(ADB + ['shell', f'su -c "{cmd}"'], capture_output=True, text=True, timeout=15).stdout

def get_pid():
    return int(adb_text("pidof com.nianticlabs.pokemongo").strip().split()[0])

def read_pages(pid, page_addr, num_pages):
    bs = 4096
    skip = page_addr // bs
    return adb_bin(f"dd if=/proc/{pid}/mem bs={bs} skip={skip} count={num_pages} 2>/dev/null", timeout=60)

def read_string_il2cpp(data, offset):
    if offset < 0 or offset + 0x14 > len(data): return None
    try:
        nlen = struct.unpack_from('<i', data, offset + 0x10)[0]
        if nlen <= 0 or nlen > 100: return None
        if offset + 0x14 + nlen*2 > len(data): return None
        return data[offset + 0x14 : offset + 0x14 + nlen*2].decode('utf-16-le', errors='replace')
    except: return None

def parse_display(data, offset):
    """Parse a PokemonDisplayProto. Common fields:
    - gender_ (int32 enum: 0=unset, 1=male, 2=female, 3=genderless)
    - costume_ (int32 enum)
    - shiny_ (bool)
    - form_ (int32 enum)
    - alignment_ (int32 enum: 0=unset, 1=normal, 2=shadow, 3=purified)
    - currentTempEvolution_ (int32)
    """
    if offset < 0 or offset + 100 > len(data): return None
    result = {}
    # Try common offsets - PokemonDisplay objects in protobuf-gen typically have:
    # 0x00 klass ptr, 0x08 monitor, then fields starting at 0x10
    try:
        # Capture all int32s and bools at every offset
        for i in range(0, 100, 4):
            v = struct.unpack_from('<i', data, offset + i)[0]
            if v != 0:
                result[hex(i)] = v
        # Capture small bytes (potential bools)
        for i in [0x10, 0x14, 0x18, 0x1c, 0x20, 0x24, 0x28, 0x2c, 0x30, 0x34, 0x38, 0x3c, 0x40, 0x44, 0x48, 0x4c, 0x50, 0x54, 0x58, 0x5c, 0x60]:
            if offset + i < len(data):
                b = data[offset + i]
                if b in (0, 1):
                    result[f'b_{hex(i)}'] = b
    except: return None
    return result

def main():
    print("Loading pokemon_full.json...", flush=True)
    pokemon = json.load(open('pokemon_full.json'))
    print(f"  {len(pokemon)} pokemon", flush=True)

    pid = get_pid()
    print(f"PID: {pid}", flush=True)

    # Group display ptrs by 4KB page
    pages_needed = {}  # page_addr -> [(idx, ptr_within_page)]
    for i, p in enumerate(pokemon):
        ptr_str = p.get('pokemonDisplay_ptr', '')
        if not ptr_str or ptr_str == '0x0': continue
        try:
            ptr = int(ptr_str, 16)
        except: continue
        if not (0x70_00000000 < ptr < 0x90_00000000): continue
        page = (ptr // 4096) * 4096
        offset = ptr - page
        pages_needed.setdefault(page, []).append((i, offset))

    print(f"Unique 4KB pages to read: {len(pages_needed)}", flush=True)

    # Read pages in parallel - each read is 1 page (4KB) or batch nearby pages
    page_data = {}
    completed = 0
    t0 = time.time()

    def read_page(page):
        try:
            d = read_pages(pid, page, 1)
            return page, d
        except Exception as e:
            return page, b''

    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futs = {ex.submit(read_page, pg): pg for pg in pages_needed}
        for f in as_completed(futs):
            page, d = f.result()
            completed += 1
            page_data[page] = d
            if completed % 100 == 0:
                print(f"  {completed}/{len(pages_needed)} pages read in {time.time()-t0:.1f}s", flush=True)

    print(f"Read {len(page_data)} pages, parsing displays...", flush=True)

    enriched = 0
    samples = []
    for page, idx_list in pages_needed.items():
        data = page_data.get(page, b'')
        if not data: continue
        for idx, offset in idx_list:
            disp = parse_display(data, offset)
            if disp:
                pokemon[idx]['display'] = disp
                enriched += 1
                if len(samples) < 3:
                    samples.append((pokemon[idx]['pokemonId'], disp))

    print(f"Enriched {enriched}/{len(pokemon)} pokemon with display data", flush=True)
    print("Sample displays:", flush=True)
    for sp_id, d in samples:
        print(f"  Species #{sp_id}: {d}", flush=True)

    with open('pokemon_full.json', 'w') as f:
        json.dump(pokemon, f, indent=2)
    print(f"Saved to pokemon_full.json", flush=True)

if __name__ == '__main__':
    main()
