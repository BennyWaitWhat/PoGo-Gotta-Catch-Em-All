"""
Parallel memory scanner - reads multiple regions concurrently.
"""
import subprocess, struct, json, time, sys, re
from concurrent.futures import ThreadPoolExecutor, as_completed

ADB = ['adb', '-s', '100.98.158.56:5555']
PARALLEL_WORKERS = 8

def adb_root_binary(cmd, timeout=180):
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
        if size < 1 * 1024 * 1024: continue
        if size > 512 * 1024 * 1024: continue
        regions.append((start, end, size, path))
    regions.sort(key=lambda r: -r[2])
    return regions

# Split big regions into chunks for parallelism
def chunk_regions(regions, chunk_mb=32):
    chunk_size = chunk_mb * 1024 * 1024
    chunks = []
    for start, end, size, path in regions:
        if size <= chunk_size:
            chunks.append((start, end, size, path))
        else:
            cur = start
            while cur < end:
                cend = min(cur + chunk_size, end)
                chunks.append((cur, cend, cend - cur, path))
                cur = cend
    return chunks

def read_chunk(pid, start, size):
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

def process_chunk(pid, start, end, size, path):
    t0 = time.time()
    try:
        data = read_chunk(pid, start, size)
    except Exception as e:
        return start, [], 0, f"read failed: {e}"
    if not data: return start, [], 0, "empty"
    results = scan_data(data, start)
    elapsed = time.time() - t0
    return start, results, len(data), f"read {len(data)/1024/1024:.1f}MB in {elapsed:.1f}s"

def main():
    pid = get_pid()
    if not pid:
        log("ERROR: PoGO not running")
        sys.exit(1)
    log(f"PID: {pid}")

    regions = get_regions(pid)
    chunks = chunk_regions(regions, chunk_mb=32)
    total_size = sum(c[2] for c in chunks)
    log(f"Regions: {len(regions)} -> {len(chunks)} chunks, {total_size/1024/1024:.1f}MB total")
    log(f"Workers: {PARALLEL_WORKERS}")

    pokemon = []
    seen = set()
    start_time = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        futures = {ex.submit(process_chunk, pid, c[0], c[1], c[2], c[3]): c for c in chunks}
        for fut in as_completed(futures):
            completed += 1
            try:
                start, results, data_len, status = fut.result()
            except Exception as e:
                log(f"  FAIL: {e}")
                continue

            new = 0
            for p in results:
                if p['uid'] in seen: continue
                seen.add(p['uid'])
                pokemon.append(p)
                new += 1

            if new > 0 or completed % 20 == 0:
                log(f"  [{completed}/{len(chunks)}] {hex(start)} {status} | {len(results)} hits ({new} new) | TOTAL={len(pokemon)}")

            if new > 0:
                with open('pokemon_dump.json', 'w') as f:
                    json.dump(pokemon, f, indent=2)

    total_elapsed = time.time() - start_time
    log(f"\n=== DONE: {len(pokemon)} unique pokemon in {total_elapsed:.1f}s ===")
    with open('pokemon_dump.json', 'w') as f:
        json.dump(pokemon, f, indent=2)

if __name__ == '__main__':
    main()
