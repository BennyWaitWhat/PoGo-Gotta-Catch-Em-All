#!/data/data/com.termux/files/usr/bin/python3
"""
Direct PoGO memory scanner. Runs on the phone with root.
Bypasses anti-cheat by using /proc/PID/mem at kernel level (no ptrace).

Validates PokemonProto by checking field invariants:
  +40 pokemonId (1-1100)
  +44 cp (10-9999)
  +112 ivAtk (0-15)
  +116 ivDef (0-15)
  +120 ivSta (0-15)
  +124 cpMultiplier (float 0.094-0.9)
  +104 heightM (float 0.1-30)
  +108 weightKg (float 0.1-1000)
"""
import os, sys, struct, json, time

def get_pid():
    for line in os.popen('ps -A').readlines():
        if 'com.nianticlabs.pokemongo' in line and ':pgp' not in line:
            return int(line.split()[1])
    return None

def parse_maps(pid):
    regions = []
    with open(f'/proc/{pid}/maps') as f:
        for line in f:
            parts = line.split()
            if len(parts) < 5: continue
            addr_range = parts[0]
            perms = parts[1]
            path = ' '.join(parts[5:]) if len(parts) > 5 else ''
            if 'rw' not in perms: continue
            # Skip huge file-backed regions and non-anonymous
            if path and not path.startswith('[anon') and path != '': continue
            start, end = [int(x, 16) for x in addr_range.split('-')]
            size = end - start
            if size < 0x1000 or size > 256 * 1024 * 1024: continue
            regions.append((start, end, size, path))
    return regions

def scan_region(mem, start, size):
    """Scan a memory region for PokemonProto patterns."""
    found = []
    try:
        mem.seek(start)
        data = mem.read(size)
    except (OSError, IOError):
        return found

    # PokemonProto is at least 280 bytes (move3 at offset 276)
    # Stride: scan every 8 bytes (object alignment)
    for off in range(0, len(data) - 280, 8):
        try:
            # Read fields at expected offsets
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

            # Read remaining fields
            uid = struct.unpack_from('<q', data, off + 32)[0]
            stamina = struct.unpack_from('<i', data, off + 48)[0]
            move1 = struct.unpack_from('<i', data, off + 56)[0]
            move2 = struct.unpack_from('<i', data, off + 60)[0]
            move3 = struct.unpack_from('<i', data, off + 276)[0]
            pokeball = struct.unpack_from('<i', data, off + 128)[0]
            createMs = struct.unpack_from('<q', data, off + 160)[0]
            isLucky = data[off + 272] != 0

            # Sanity: stamina <= 600 typically, moves are int enums
            if stamina < 0 or stamina > 5000: continue
            if move1 < 0 or move1 > 600: continue
            if move2 < 0 or move2 > 600: continue

            found.append({
                'addr': hex(start + off),
                'uid': uid,
                'pokemonId': pokemonId,
                'cp': cp,
                'stamina': stamina,
                'move1': move1, 'move2': move2, 'move3': move3,
                'ivAtk': ivAtk, 'ivDef': ivDef, 'ivSta': ivSta,
                'heightM': height, 'weightKg': weight,
                'cpMultiplier': cpm, 'pokeball': pokeball,
                'creationTimeMs': createMs, 'isLucky': isLucky,
            })
        except (struct.error, IndexError):
            continue
    return found

def main():
    pid = get_pid()
    if not pid:
        print("ERROR: PoGO not running", flush=True)
        sys.exit(1)
    print(f"PoGO PID: {pid}", flush=True)

    regions = parse_maps(pid)
    print(f"Found {len(regions)} candidate regions", flush=True)

    total_size = sum(r[2] for r in regions)
    print(f"Total size: {total_size / 1024 / 1024:.1f} MB", flush=True)

    pokemon = []
    seen_uids = set()
    start_time = time.time()

    with open(f'/proc/{pid}/mem', 'rb') as mem:
        for i, (start, end, size, path) in enumerate(regions):
            t0 = time.time()
            results = scan_region(mem, start, size)
            elapsed = time.time() - t0
            new = 0
            for p in results:
                if p['uid'] in seen_uids: continue
                seen_uids.add(p['uid'])
                pokemon.append(p)
                new += 1
            if i % 20 == 0 or new > 0:
                print(f"  region {i}/{len(regions)} {hex(start)} {size//1024}KB: {len(results)} matches ({new} new), {elapsed:.1f}s, total={len(pokemon)}", flush=True)

    print(f"\nDONE: {len(pokemon)} unique pokemon in {time.time()-start_time:.1f}s", flush=True)

    out_path = '/data/local/tmp/pokemon_dump.json'
    with open(out_path, 'w') as f:
        json.dump(pokemon, f, indent=2)
    print(f"Saved to {out_path}", flush=True)

if __name__ == '__main__':
    main()
