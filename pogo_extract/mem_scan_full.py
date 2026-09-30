"""
Full PoGO memory scanner v2 - extracts ALL fields per pokemon.

Reads 320-byte PokemonProto, then follows:
- pokemonDisplay_ pointer (offset 216) → PokemonDisplayProto (gender/shiny/form/costume)
- nickname pointer (offset 184) → string
- deployedFortId pointer (offset 64) → string

Also extracts every numeric field at every 4-byte offset for completeness.
"""
import subprocess, struct, json, time, sys, re
from concurrent.futures import ThreadPoolExecutor, as_completed

ADB = ['adb', '-s', '100.98.158.56:5555']
PARALLEL = 12
POGO_LAUNCH_MS = 1467590400000

def adb_bin(cmd, timeout=180):
    return subprocess.run(ADB + ['exec-out', f'su -c "{cmd}"'], capture_output=True, timeout=timeout).stdout

def adb_text(cmd):
    return subprocess.run(ADB + ['shell', f'su -c "{cmd}"'], capture_output=True, text=True, timeout=15).stdout

def get_pid():
    out = adb_text("pidof com.nianticlabs.pokemongo")
    return int(out.strip().split()[0]) if out.strip() else None

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

def read_string_il2cpp(data, offset):
    """Read IL2CPP string: [klass][monitor][len(int32 +0x10)][chars(utf16 +0x14)]"""
    if offset + 0x14 > len(data): return None
    try:
        nlen = struct.unpack_from('<i', data, offset + 0x10)[0]
        if nlen <= 0 or nlen > 100: return None
        if offset + 0x14 + nlen*2 > len(data): return None
        return data[offset + 0x14 : offset + 0x14 + nlen*2].decode('utf-16-le', errors='replace')
    except: return None

def scan_chunk(data, base_addr):
    """Scan for PokemonProto patterns. Capture raw bytes too."""
    found = []
    n = len(data)
    if n < 320: return found

    for off in range(0, n - 320, 8):
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

            uid = struct.unpack_from('<Q', data, off + 32)[0]  # unsigned!
            if uid == 0: continue
            createMs = struct.unpack_from('<q', data, off + 160)[0]
            if createMs < POGO_LAUNCH_MS: continue

            stamina = struct.unpack_from('<i', data, off + 48)[0]
            if stamina < 0 or stamina > 5000: continue
            move1 = struct.unpack_from('<i', data, off + 56)[0]
            move2 = struct.unpack_from('<i', data, off + 60)[0]
            move3 = struct.unpack_from('<i', data, off + 276)[0]
            if move1 < 0 or move1 > 600: continue
            if move2 < 0 or move2 > 600: continue

            # Capture all int32 values at every 4-byte offset
            extra_ints = {}
            for i in range(0, 320, 4):
                if off + i + 4 > n: break
                v = struct.unpack_from('<i', data, off + i)[0]
                if v != 0:
                    extra_ints[hex(i)] = v

            # Capture pointers
            ptrs = {}
            for i in range(0, 320, 8):
                if off + i + 8 > n: break
                p = struct.unpack_from('<Q', data, off + i)[0]
                if 0x70_00000000 < p < 0x90_00000000:  # heap range
                    ptrs[hex(i)] = hex(p)

            # Try to read pokemonDisplay (in same chunk)
            display_ptr = struct.unpack_from('<Q', data, off + 216)[0]
            display_offset = display_ptr - base_addr
            display_data = None
            if 0 <= display_offset < n - 200:
                display_data = data[display_offset:display_offset + 200].hex()

            # Try to read nickname (in same chunk)
            nickname = None
            nick_ptr = struct.unpack_from('<Q', data, off + 184)[0]
            nick_offset = nick_ptr - base_addr
            if 0 <= nick_offset < n - 100:
                nickname = read_string_il2cpp(data, nick_offset)

            # Try to read deployedFortId
            deployed = None
            fort_ptr = struct.unpack_from('<Q', data, off + 64)[0]
            fort_offset = fort_ptr - base_addr
            if 0 <= fort_offset < n - 100:
                deployed = read_string_il2cpp(data, fort_offset)

            # Try to read captured cell ID at various offsets
            # In Holoholo's PokemonProto, captured_cell_id_ usually comes after creation_time
            # Let's look for likely uint64 S2 cell IDs (large numbers)
            captured_cell_id = None
            for cell_off in [168, 176, 192, 200, 208, 224, 232, 240, 248, 256, 264]:
                if off + cell_off + 8 > n: continue
                v = struct.unpack_from('<Q', data, off + cell_off)[0]
                # S2 cell IDs are large 64-bit values, usually > 2^60
                if 0x4000000000000000 < v < 0xC000000000000000:
                    captured_cell_id = v
                    break

            # Origin detail enum at various places
            # Captured at fort, raid, event, etc.
            origin_detail = None
            for orig_off in [200, 208, 232, 240, 256, 268]:
                if off + orig_off + 4 > n: continue
                v = struct.unpack_from('<i', data, off + orig_off)[0]
                if 1 <= v < 30:  # OriginDetail enum is small
                    origin_detail = (orig_off, v)

            found.append({
                'addr': hex(base_addr + off),
                'uid': uid,
                'pokemonId': pokemonId, 'cp': cp, 'stamina': stamina,
                'move1': move1, 'move2': move2, 'move3': move3,
                'ivAtk': ivAtk, 'ivDef': ivDef, 'ivSta': ivSta,
                'heightM': height, 'weightKg': weight,
                'cpMultiplier': cpm,
                'pokeball': struct.unpack_from('<i', data, off + 128)[0],
                'creationTimeMs': createMs,
                'isLucky': data[off + 272] != 0,
                'nickname': nickname,
                'deployedFortId': deployed,
                'pokemonDisplay_ptr': hex(display_ptr),
                'pokemonDisplay_raw': display_data,
                'capturedCellId': captured_cell_id,
                'origin_candidates': origin_detail,
                'extra_ints': extra_ints,  # All non-zero int32s
                'pointers': ptrs,
                'raw_proto': data[off:off+320].hex(),  # Save full bytes
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
        return start, [], 0, f"read fail"
    if not data: return start, [], 0, "empty"
    results = scan_chunk(data, start)
    return start, results, len(data), f"{time.time()-t0:.1f}s"

def main():
    pid = get_pid()
    if not pid: log("ERROR: no PoGO"); sys.exit(1)
    log(f"PID: {pid}")

    regions = get_regions(pid)
    chunks = chunk_regions(regions, chunk_mb=32)
    log(f"Regions: {len(regions)} -> {len(chunks)} chunks, {sum(c[2] for c in chunks)/1024/1024:.0f}MB")

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
            if new > 0 or completed % 20 == 0:
                log(f"  [{completed}/{len(chunks)}] {hex(start)} {status} | {len(results)} hits ({new} new) | total={len(pokemon)}")
            if new > 0:
                with open('pokemon_full.json', 'w') as f2:
                    json.dump(pokemon, f2, indent=2)

    elapsed = time.time() - t0
    log(f"\n=== DONE: {len(pokemon)} pokemon in {elapsed:.1f}s ===")
    with open('pokemon_full.json', 'w') as f:
        json.dump(pokemon, f, indent=2)

if __name__ == '__main__':
    main()
