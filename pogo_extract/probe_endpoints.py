#!/usr/bin/env python3
"""
Probe live PoGo memory for endpoint URLs and session-state markers via /proc/PID/mem.
Read-only. Intended to run via `adb shell su -c 'python3 ...'` or pulled-and-piped.
"""
import os, re, sys, struct

PID = sys.argv[1] if len(sys.argv) > 1 else None
if not PID:
    for p in os.listdir('/proc'):
        if p.isdigit():
            try:
                cmd = open(f'/proc/{p}/cmdline').read()
                if 'com.nianticlabs.pokemongo' in cmd:
                    PID = p; break
            except: pass

if not PID:
    print("PoGo not running"); sys.exit(1)
print(f"PID={PID}")

# Patterns to find
PATTERNS = [
    (b'pgorelease.nianticlabs.com', 'PGORELEASE'),
    (b'nianticlabs.com', 'NIANTIC_DOMAIN'),
    (b'/api/get-time', 'API_GETTIME'),
    (b'/embed/', 'AUTH_EMBED'),
    (b'rpc.holoholo', 'HOLOHOLO'),
    (b'Holoholo.Rpc', 'HOLOHOLO_RPC'),
    (b'ProxyRequest', 'PROXY_REQ'),
    (b'/plfe/', 'PLFE'),
    (b'/rpc', 'RPC_PATH'),
    (b'eyJhbGciOi', 'JWT_HEADER'),  # base64 of {"alg":"
    (b'Bearer ', 'BEARER'),
    (b'X-Unique-Id', 'X_UNIQUE'),
    (b'X-Niantic', 'X_NIANTIC'),
    (b'X-Client', 'X_CLIENT'),
    (b'BackgroundToken', 'BG_TOKEN'),
    (b'ClientHash', 'CLIENT_HASH'),
    (b'EncounterCounter', 'ENC_COUNTER'),
    (b'PlatformId', 'PLATFORM_ID'),
    (b'SessionInfo', 'SESS_INFO'),
    (b'SignRequest', 'SIGN_REQ'),
    (b'NIANTIC_HOLOHOLO', 'NIA_HH'),
    (b'platform-shared', 'PLAT_SHARED'),
    (b'pgo_request', 'PGO_REQ'),
    (b'request_envelope', 'REQ_ENV'),
]

# Read maps
maps = []
for line in open(f'/proc/{PID}/maps'):
    parts = line.split()
    if len(parts) < 2: continue
    rng, perms = parts[0], parts[1]
    if 'r' not in perms: continue
    # Skip device-mapped to avoid hangs
    if len(parts) > 5 and parts[5].startswith('/dev'): continue
    try:
        a, b = rng.split('-')
        start, end = int(a, 16), int(b, 16)
        size = end - start
        if size > 200_000_000: continue  # skip huge mappings
        maps.append((start, end, perms, parts[5] if len(parts) > 5 else ''))
    except: pass

print(f"Will scan {len(maps)} regions")

mem = open(f'/proc/{PID}/mem', 'rb', buffering=0)
hits = {name: [] for _, name in PATTERNS}

for start, end, perms, path in maps:
    size = end - start
    try:
        mem.seek(start)
        data = mem.read(size)
    except (OSError, OverflowError):
        continue
    if not data: continue
    for pat, name in PATTERNS:
        idx = 0
        c = 0
        while True:
            idx = data.find(pat, idx)
            if idx < 0: break
            ctx = data[max(0,idx-32):idx+len(pat)+96]
            try:
                txt = ctx.decode('utf-8', errors='replace').replace('\x00', '\\0')
            except:
                txt = repr(ctx)
            hits[name].append((hex(start+idx), path, txt[:200]))
            idx += len(pat)
            c += 1
            if c > 5: break  # cap per region per pattern

for name, lst in hits.items():
    if lst:
        print(f"\n=== {name} ({len(lst)} hits) ===")
        for addr, path, ctx in lst[:8]:
            tag = path.split('/')[-1] if path else 'anon'
            print(f"  {addr} [{tag}] {ctx}")
