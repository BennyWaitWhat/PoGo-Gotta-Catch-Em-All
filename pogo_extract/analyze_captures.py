"""Analyze captured SSL traffic - decode protobuf bodies."""
import os
from google.protobuf.internal.decoder import _DecodeVarint32
from google.protobuf.internal.wire_format import (
    WIRETYPE_VARINT, WIRETYPE_FIXED64,
    WIRETYPE_LENGTH_DELIMITED, WIRETYPE_FIXED32
)

def decode_raw(data, max_depth=3, prefix=''):
    results = []
    pos = 0
    while pos < len(data):
        try:
            tag, new_pos = _DecodeVarint32(data, pos)
            if new_pos == pos:
                break
            field_number = tag >> 3
            wire_type = tag & 0x7
            pos = new_pos

            if wire_type == WIRETYPE_VARINT:
                value, pos = _DecodeVarint32(data, pos)
                results.append(f'{prefix}f{field_number}: varint={value}')
            elif wire_type == WIRETYPE_FIXED64:
                value = int.from_bytes(data[pos:pos+8], 'little')
                pos += 8
                results.append(f'{prefix}f{field_number}: i64={value}')
            elif wire_type == WIRETYPE_LENGTH_DELIMITED:
                length, pos = _DecodeVarint32(data, pos)
                if length > len(data) - pos or length < 0 or length > 10_000_000:
                    break
                chunk = data[pos:pos+length]
                pos += length
                try:
                    text = chunk.decode('utf-8')
                    if len(text) > 0 and all(32 <= ord(c) < 127 or c in '\n\r\t' for c in text):
                        results.append(f'{prefix}f{field_number}: str="{text[:80]}"')
                        continue
                except:
                    pass
                if max_depth > 0 and length > 2:
                    nested = decode_raw(chunk, max_depth-1, prefix+'  ')
                    if nested:
                        results.append(f'{prefix}f{field_number}: msg({length}B) {{')
                        results.extend(nested[:8])
                        if len(nested) > 8:
                            results.append(f'{prefix}  ...+{len(nested)-8}')
                        results.append(f'{prefix}}}')
                    else:
                        results.append(f'{prefix}f{field_number}: bytes({length}B)')
                else:
                    results.append(f'{prefix}f{field_number}: bytes({length}B)')
            elif wire_type == WIRETYPE_FIXED32:
                value = int.from_bytes(data[pos:pos+4], 'little')
                pos += 4
                results.append(f'{prefix}f{field_number}: i32={value}')
            else:
                break
        except:
            break
    return results


capdir = os.path.join(os.path.dirname(__file__), "captures")
files = sorted(os.listdir(capdir))

print(f"Analyzing {len(files)} capture files...\n")

for f in files:
    path = os.path.join(capdir, f)
    with open(path, 'rb') as fh:
        data = fh.read()

    if data[:4] == b'HTTP':
        header_end = data.find(b'\r\n\r\n')
        headers = data[:header_end].decode('latin-1')
        body = data[header_end+4:]
        cl = 0
        for line in headers.split('\r\n'):
            if line.lower().startswith('content-length:'):
                cl = int(line.split(':')[1].strip())
        proto_body = body[:cl] if cl else body
        tag = "HTTP"
    else:
        proto_body = data
        tag = "RAW"

    decoded = decode_raw(proto_body[:5000])  # Only first 5KB for speed
    if decoded:
        print(f"=== {f} [{tag}] body={len(proto_body)}B, {len(decoded)} fields ===")
        for line in decoded[:12]:
            print(f"  {line}")
        if len(decoded) > 12:
            print(f"  ...+{len(decoded)-12}")
        print()
    else:
        if tag == "HTTP":
            print(f"=== {f} [{tag}] body={len(proto_body)}B - NOT protobuf ===\n")
