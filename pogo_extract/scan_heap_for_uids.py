"""
Stream-scan PoGo memory for known pokemon UIDs.
Uses /proc/PID/mem via dd | gzip on the phone, scans on host.
"""
import os
import sys
import re
import struct
import pickle
import json
import subprocess
import argparse

PID = 11836
ADB = ["adb", "-s", "100.98.158.56:5555"]
WORKDIR = "/c/Users/Blanco/Desktop/Claude Operations/Phone Maintenance/pogo_extract"

def parse_maps(maps_text):
    """Yield (start, end, perms, name) for each region."""
    for line in maps_text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 5:
            continue
        addr_range = parts[0]
        perms = parts[1]
        name = parts[5] if len(parts) > 5 else ""
        try:
            start_hex, end_hex = addr_range.split("-")
            start = int(start_hex, 16)
            end = int(end_hex, 16)
        except Exception:
            continue
        yield start, end, perms, name

def read_region(pid, start, length):
    """Read [start, start+length) from /proc/PID/mem via adb su dd."""
    blocks = (length + 4095) // 4096
    skip = start // 4096
    cmd = ADB + ["shell", f"su -c 'dd if=/proc/{pid}/mem bs=4096 skip={skip} count={blocks} 2>/dev/null | gzip -1'"]
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    if p.returncode != 0:
        return None
    import gzip, io
    try:
        data = gzip.decompress(p.stdout)
    except Exception as e:
        return None
    if len(data) < length:
        return data
    return data[:length]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", default=os.path.join(WORKDIR, "pogo_maps_current.txt"))
    ap.add_argument("--uids", default=os.path.join(WORKDIR, "uid_bytes.pkl"))
    ap.add_argument("--out", default=os.path.join(WORKDIR, "uid_hits_fresh.pkl"))
    ap.add_argument("--max-region", type=int, default=256*1024*1024)
    ap.add_argument("--min-region", type=int, default=4096)
    args = ap.parse_args()

    with open(args.uids, "rb") as f:
        d = pickle.load(f)
    uid_bytes = d["uid_bytes"]
    uid_to_uid = d["uid_to_uid"]
    print(f"Loaded {len(uid_bytes)} UID byte patterns")

    with open(args.maps) as f:
        maps_text = f.read()

    regions = []
    for start, end, perms, name in parse_maps(maps_text):
        if "rw" not in perms:
            continue
        # Skip libil2cpp.so writable section (no UID data there)
        if "libil2cpp" in name or "/" in name:
            continue
        if "[" in name:
            # skip [stack], [heap], [vvar], etc - keep [anon] though, but here unnamed-only
            continue
        size = end - start
        if size < args.min_region or size > args.max_region:
            continue
        regions.append((start, end, size, name))

    regions.sort(key=lambda r: r[2], reverse=True)
    total = sum(r[2] for r in regions)
    print(f"Will scan {len(regions)} regions, total {total/1048576:.1f} MB")

    hits = []  # list of (region_start, offset, uid, value_at_offset)
    for ridx, (start, end, size, name) in enumerate(regions):
        sys.stdout.write(f"[{ridx+1}/{len(regions)}] 0x{start:x}-0x{end:x} ({size/1048576:.1f}MB) ")
        sys.stdout.flush()
        # Read in 4MB chunks to avoid memory pressure
        chunk_size = 4 * 1024 * 1024
        offset = 0
        region_hits = 0
        while offset < size:
            this_size = min(chunk_size, size - offset)
            data = read_region(PID, start + offset, this_size)
            if data is None:
                sys.stdout.write("X")
                sys.stdout.flush()
                offset += this_size
                continue
            # Scan 8-byte aligned positions for UID match
            for i in range(0, len(data) - 7, 8):
                w = data[i:i+8]
                if w in uid_bytes:
                    uid = uid_to_uid[w]
                    # Capture surrounding 64 bytes for context
                    ctx_start = max(0, i - 16)
                    ctx_end = min(len(data), i + 48)
                    ctx = data[ctx_start:ctx_end]
                    abs_addr = start + offset + i
                    hits.append({
                        "region_start": start,
                        "abs_addr": abs_addr,
                        "uid": uid,
                        "ctx": ctx.hex(),
                        "ctx_offset": i - ctx_start,
                    })
                    region_hits += 1
            offset += this_size
            sys.stdout.write(".")
            sys.stdout.flush()
        sys.stdout.write(f" {region_hits} hits\n")

        # checkpoint
        if (ridx+1) % 10 == 0:
            with open(args.out, "wb") as f:
                pickle.dump(hits, f)

    with open(args.out, "wb") as f:
        pickle.dump(hits, f)
    print(f"Total hits: {len(hits)}")
    # Distinct UIDs
    distinct = set(h["uid"] for h in hits)
    print(f"Distinct UIDs hit: {len(distinct)}")

if __name__ == "__main__":
    main()
