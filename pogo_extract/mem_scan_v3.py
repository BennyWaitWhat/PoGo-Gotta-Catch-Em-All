"""
Comprehensive scanner v3:
- 15 parallel workers
- Captures 512 bytes per pokemon (covers ALL fields including trade/mega/buddy)
- Follows pointer at +0xb8 (original owner nickname?), +0x100, +0x130 (potentially trader info)
- Captures full PokemonDisplay (200 bytes)
"""
import subprocess, struct, json, time, sys, re
from concurrent.futures import ThreadPoolExecutor, as_completed

ADB = ['adb', '-s', '100.98.158.56:5555']
PARALLEL = 15
POGO_LAUNCH_MS = 1467590400000

def adb_bin(cmd, timeout=180):
    return subprocess.run(ADB + ['exec-out', f'su -c "{cmd}"'], capture_output=True, timeout=timeout).stdout

def adb_text(cmd):
    return subprocess.run(ADB + ['shell', f'su -c "{cmd}"'], capture_output=True, text=True, timeout=15).stdout

def get_pid():
    return int(adb_text("pidof com.nianticlabs.pokemongo").strip().split()[0])

def get_regions(pid):
    maps = adb_text(f"cat /proc/{pid}/maps")
    regions = []
    for line in maps.split('\n'):
        m = re.match(r'([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)', line)
        if not m: continue
        start = int(m.group(1), 16); end = int(m.group(2), 16)
        perms = m.group(3); path = m.group(4).strip()
        size = end - start
        if 'rw' not in perms: continue
        if path and not (path.startswith('[anon') or path == ''): continue
        if size < 1*1024*1024 or size > 512*1024*1024: continue
        regions.append((start, end, size, path))
    regions.sort(key=lambda r: -r[2])
    return regions

def chunk_regions(regions, chunk_mb=32):
    cs = chunk_mb * 1024 * 1024
    chunks = []
    for s, e, sz, p in regions:
        if sz <= cs: chunks.append((s, e, sz, p))
        else:
            cur = s
            while cur < e:
                ce = min(cur + cs, e); chunks.append((cur, ce, ce - cur, p)); cur = ce
    return chunks

def read_chunk(pid, start, size):
    bs = 4096
    skip = start // bs; count = (size + bs - 1) // bs
    return adb_bin(f"dd if=/proc/{pid}/mem bs={bs} skip={skip} count={count} 2>/dev/null", timeout=180)

def read_string(data, offset):
    if offset < 0 or offset + 0x14 > len(data): return None
    try:
        nlen = struct.unpack_from('<i', data, offset + 0x10)[0]
        if nlen <= 0 or nlen > 100: return None
        if offset + 0x14 + nlen*2 > len(data): return None
        return data[offset + 0x14 : offset + 0x14 + nlen*2].decode('utf-16-le', errors='replace')
    except: return None

EMPTY_STR = 0x7b81c1cf40  # System.String.Empty global pointer

def scan_chunk(data, base_addr):
    found = []
    n = len(data)
    if n < 512: return found

    PROTO_SIZE = 512  # capture more fields

    for off in range(0, n - PROTO_SIZE, 8):
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

            uid = struct.unpack_from('<Q', data, off + 32)[0]
            if uid == 0: continue
            createMs = struct.unpack_from('<q', data, off + 160)[0]
            if createMs < POGO_LAUNCH_MS: continue
            stamina = struct.unpack_from('<i', data, off + 48)[0]
            if stamina < 0 or stamina > 5000: continue

            # Capture full 512 bytes
            raw_proto = data[off:off+PROTO_SIZE].hex() if off+PROTO_SIZE <= n else data[off:].hex()

            # Try to read pokemonDisplay (PokemonDisplayProto, 200 bytes)
            display_ptr = struct.unpack_from('<Q', data, off + 216)[0]
            display_raw = None
            if 0x70_00000000 < display_ptr < 0x90_00000000:
                # Check if in this chunk
                disp_off = display_ptr - base_addr
                if 0 <= disp_off < n - 200:
                    display_raw = data[disp_off:disp_off+200].hex()

            # Try to read string pointers (any offset that looks like a heap ptr)
            strings = {}
            for str_off in [64, 184, 256, 304, 320, 360, 384]:
                if off + str_off + 8 > n: continue
                p = struct.unpack_from('<Q', data, off + str_off)[0]
                if p == EMPTY_STR: strings[hex(str_off)] = ''  # Empty string sentinel
                elif 0x70_00000000 < p < 0x90_00000000:
                    # Try to read in chunk
                    s_off = p - base_addr
                    s = read_string(data, s_off) if 0 <= s_off < n - 100 else None
                    strings[hex(str_off)] = (hex(p), s)

            found.append({
                'addr': hex(base_addr + off),
                'uid': uid,
                'pokemonId': pokemonId, 'cp': cp, 'stamina': stamina,
                'creationTimeMs': createMs,
                'ivAtk': ivAtk, 'ivDef': ivDef, 'ivSta': ivSta,
                'cpm': cpm, 'height': height, 'weight': weight,
                'raw_proto': raw_proto,        # 512 bytes
                'display_ptr': hex(display_ptr),
                'display_raw': display_raw,    # 200 bytes
                'strings': strings,
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
        return start, [], 0, f"fail: {e}"
    if not data: return start, [], 0, "empty"
    return start, scan_chunk(data, start), len(data), f"{time.time()-t0:.1f}s"

def main():
    pid = get_pid()
    if not pid: log("ERROR: no PoGO"); sys.exit(1)
    log(f"PID: {pid}")

    regions = get_regions(pid)
    chunks = chunk_regions(regions, chunk_mb=32)
    log(f"Regions: {len(regions)} -> {len(chunks)} chunks ({sum(c[2] for c in chunks)/1024/1024:.0f}MB), {PARALLEL} workers")

    pokemon = []
    seen = set()
    completed = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futs = {ex.submit(process_chunk, pid, c[0], c[1], c[2], c[3]): c for c in chunks}
        for f in as_completed(futs):
            completed += 1
            try:
                start, results, dlen, status = f.result()
            except Exception as e:
                log(f"  FAIL: {e}"); continue
            new = 0
            for p in results:
                if p['uid'] in seen: continue
                seen.add(p['uid']); pokemon.append(p); new += 1
            if new > 0 or completed % 30 == 0:
                log(f"  [{completed}/{len(chunks)}] {hex(start)} {status} | {len(results)} hits ({new} new) total={len(pokemon)}")
            if new > 0:
                with open('pokemon_v3.json', 'w') as f2:
                    json.dump(pokemon, f2, indent=2)

    elapsed = time.time() - t0
    log(f"\n=== DONE: {len(pokemon)} pokemon in {elapsed:.1f}s ===")
    with open('pokemon_v3.json', 'w') as f:
        json.dump(pokemon, f, indent=2)

if __name__ == '__main__':
    main()
