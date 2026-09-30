"""
Fast PoGO memory scanner - only scans large heap regions.
"""
import subprocess, struct, json, time, sys, re

ADB = ['adb', '-s', '100.98.158.56:5555']

def adb_root_binary(cmd, timeout=120):
    full = ADB + ['exec-out', f'su -c "{cmd}"']
    return subprocess.run(full, capture_output=True, timeout=timeout).stdout

def adb_root_text(cmd):
    full = ADB + ['shell', f'su -c "{cmd}"']
    return subprocess.run(full, capture_output=True, text=True, timeout=15).stdout

def get_pid():
    out = adb_root_text("pidof com.nianticlabs.pokemongo")
    return int(out.strip().split()[0]) if out.strip() else None

def get_regions(pid):
    maps = adb_root_text(f"cat /proc/{pid}/maps")
    regions = []
    for line in maps.split('\n'):
        m = re.match(r'([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)', line)
        if not m: continue
        start = int(m.group(1), 16)
        end = int(m.group(2), 16)
        perms = m.group(3)
        path = m.group(4).strip()
        size = end - start
        if 'rw' not in perms: continue
        if path and not (path.startswith('[anon') or path == ''): continue
        # Only LARGE regions: >= 1MB. PokemonProto bag fits in single chunk.
        if size < 1 * 1024 * 1024: continue
        if size > 512 * 1024 * 1024: continue
        regions.append((start, end, size, path))
    # Sort largest first - dalvik spaces and big heaps come first
    regions.sort(key=lambda r: -r[2])
    return regions

def read_region(pid, start, size):
    bs = 4096
    skip = start // bs
    count = (size + bs - 1) // bs
    cmd = f"dd if=/proc/{pid}/mem bs={bs} skip={skip} count={count} 2>/dev/null"
    return adb_root_binary(cmd, timeout=180)

def scan_data(data, base_addr):
    found = []
    n = len(data)
    if n < 280: return found

    for off in range(0, n - 280, 8):
        try:
            pokemonId = struct.unpack_from('<i', data, off + 40)[0]
            if pokemonId < 1 or pokemonId > 1100: continue
            cp = struct.unpack_from('<i', data, off + 44)[0]
            if cp < 10 or cp > 9999: continue
            ivAtk = struct.unpack_from('<i', data, off + 112)[0]
            if ivAtk < 0 or ivAtk > 15: continue
            ivDef = struct.unpack_from('<i', data, off + 116)[0]
            if ivDef < 0 or ivDef > 15: continue
            ivSta = struct.unpack_from('<i', data, off + 120)[0]
            if ivSta < 0 or ivSta > 15: continue
            cpm = struct.unpack_from('<f', data, off + 124)[0]
            if cpm < 0.05 or cpm > 0.95: continue
            height = struct.unpack_from('<f', data, off + 104)[0]
            if height < 0.05 or height > 50: continue
            weight = struct.unpack_from('<f', data, off + 108)[0]
            if weight < 0.05 or weight > 2000: continue

            uid = struct.unpack_from('<q', data, off + 32)[0]
            stamina = struct.unpack_from('<i', data, off + 48)[0]
            if stamina < 0 or stamina > 5000: continue
            move1 = struct.unpack_from('<i', data, off + 56)[0]
            move2 = struct.unpack_from('<i', data, off + 60)[0]
            move3 = struct.unpack_from('<i', data, off + 276)[0]
            if move1 < 0 or move1 > 600: continue
            if move2 < 0 or move2 > 600: continue
            pokeball = struct.unpack_from('<i', data, off + 128)[0]
            createMs = struct.unpack_from('<q', data, off + 160)[0]
            isLucky = data[off + 272] != 0

            found.append({
                'addr': hex(base_addr + off),
                'uid': uid,
                'pokemonId': pokemonId, 'cp': cp, 'stamina': stamina,
                'move1': move1, 'move2': move2, 'move3': move3,
                'ivAtk': ivAtk, 'ivDef': ivDef, 'ivSta': ivSta,
                'heightM': height, 'weightKg': weight,
                'cpMultiplier': cpm, 'pokeball': pokeball,
                'creationTimeMs': createMs, 'isLucky': isLucky,
            })
        except (struct.error, IndexError):
            continue
    return found

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def main():
    pid = get_pid()
    if not pid:
        log("ERROR: PoGO not running")
        sys.exit(1)
    log(f"PID: {pid}")

    regions = get_regions(pid)
    total_size = sum(r[2] for r in regions)
    log(f"Large regions: {len(regions)}, total {total_size/1024/1024:.1f}MB")
    for i, r in enumerate(regions[:10]):
        log(f"  [{i}] {hex(r[0])} size={r[2]/1024/1024:.1f}MB {r[3]}")

    pokemon = []
    seen = set()
    start_time = time.time()

    for i, (start, end, size, path) in enumerate(regions):
        t0 = time.time()
        try:
            data = read_region(pid, start, size)
        except Exception as e:
            log(f"  region {i} read failed: {e}")
            continue

        if not data:
            log(f"  region {i} empty result")
            continue

        results = scan_data(data, start)
        new = 0
        for p in results:
            if p['uid'] in seen: continue
            seen.add(p['uid'])
            pokemon.append(p)
            new += 1

        elapsed = time.time() - t0
        log(f"  [{i+1}/{len(regions)}] {hex(start)} {size/1024/1024:.1f}MB: {len(data)/1024/1024:.1f}MB read, {len(results)} hits ({new} new) in {elapsed:.1f}s | total={len(pokemon)}")

        # Save incrementally on every region with hits
        if new > 0:
            with open('pokemon_dump.json', 'w') as f:
                json.dump(pokemon, f, indent=2)
            log(f"  >>> SAVED {len(pokemon)} pokemon to pokemon_dump.json")

    total_elapsed = time.time() - start_time
    log(f"\n=== DONE: {len(pokemon)} unique pokemon in {total_elapsed:.1f}s ===")

if __name__ == '__main__':
    main()
