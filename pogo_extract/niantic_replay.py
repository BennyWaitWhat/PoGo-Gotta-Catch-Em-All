#!/usr/bin/env python3
"""
Niantic RPC replay POC.

Status: probe-only. The endpoint accepts our request, parses HTTP, but rejects
the body because we lack the (1) flatbuffers envelope schema, (2) per-session
signing key, (3) Play Integrity attestation. See niantic_api_replay_v2.md.

Usage: python niantic_replay.py
"""
import struct
import urllib.request
import json

ENDPOINT = "https://pgorelease.nianticlabs.com/plfe/rpc2"

USER_AGENTS = [
    "Niantic App Framework/1.0 (PokemonGO; com.nianticlabs.pokemongo)",
    "Dalvik/2.1.0 (Linux; U; Android 14; Pixel 9 Pro Build/AP3A.241105.007)",
]


def post(body: bytes, ua: str = USER_AGENTS[0]) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": ua,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", dict(e.headers or {})


def parse_fb_sentinel(buf: bytes) -> dict:
    """The fixed 36-byte response is a flatbuffers table. Decode the structure
    so we know what fields the server fills."""
    if len(buf) < 8:
        return {"error": "short", "raw": buf.hex()}
    root_off = struct.unpack_from("<I", buf, 0)[0]
    soffset = struct.unpack_from("<i", buf, root_off)[0]
    vtable_start = root_off - soffset
    if vtable_start < 0 or vtable_start + 4 > len(buf):
        return {"error": "bad vtable", "raw": buf.hex()}
    vtable_size = struct.unpack_from("<H", buf, vtable_start)[0]
    table_size = struct.unpack_from("<H", buf, vtable_start + 2)[0]
    field_count = (vtable_size - 4) // 2
    field_offsets = [
        struct.unpack_from("<H", buf, vtable_start + 4 + 2 * i)[0]
        for i in range(field_count)
    ]
    fields = {}
    for i, off in enumerate(field_offsets):
        if off == 0:
            fields[f"f{i}"] = None
            continue
        # Read 4 bytes at root_off + off as little-endian u32 (could be a value
        # OR a relative offset to a sub-table - we don't know without the schema).
        val_off = root_off + off
        if val_off + 4 <= len(buf):
            fields[f"f{i}"] = struct.unpack_from("<I", buf, val_off)[0]
        else:
            fields[f"f{i}"] = "OOB"
    return {
        "raw_hex": buf.hex(),
        "vtable_start": vtable_start,
        "vtable_size": vtable_size,
        "table_size": table_size,
        "fields": fields,
    }


def probe():
    print(f"Endpoint: {ENDPOINT}")
    print()

    bodies = [
        ("empty", b""),
        ("zeros 256", b"\x00" * 256),
        ("fake protobuf", bytes.fromhex("080110011a")),
        ("legacy 2016 envelope shape", b"\x08\x02\x10\x01\x18\x00\x20\x00\x28\x00"),
    ]
    for label, body in bodies:
        status, resp, headers = post(body)
        print(f"--- {label} ({len(body)}B) ---")
        print(f"  HTTP {status}, server={headers.get('server', '?')}, "
              f"resp={len(resp)}B, ct={headers.get('content-type', '?')}")
        decoded = parse_fb_sentinel(resp) if 8 <= len(resp) <= 256 else {
            "raw_hex": resp[:64].hex()
        }
        print(f"  fb: {json.dumps(decoded, indent=2)}")
    print()
    print("Verdict: server returns a fixed flatbuffers sentinel for every body.")
    print("To progress further you would need:")
    print("  1. The flatbuffers envelope schema (not public)")
    print("  2. The per-session signing key (sealed in libNianticLabsPlugin.so)")
    print("  3. A Play Integrity attestation token (Google-signed, requires the")
    print("     legitimate PoGo APK + Google Play Services running)")
    print()
    print("None of these are recoverable by static analysis or memory-only probes.")
    print("See niantic_api_replay_v2.md for the full analysis.")


if __name__ == "__main__":
    probe()
