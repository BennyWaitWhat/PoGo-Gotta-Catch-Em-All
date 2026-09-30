"""Decode XOR-encoded output from pokemod-injector."""

lines_hex = [
    "2f21273934531d100f5848445b5d415353041701001a004040530c1d190b1215161d061d4e0f1f02000f3a18130d0707361e0c1005",
    "2f21273934531d100f5848445b5d4153531f1c060a0d1148041219004d0a05040907000607491b0c0a4b574e4658491607071f100e16",
    "2f21273934531d100f5848445b5d4153530f1604110a001a0803415a4d0a0a081c2b0400110a4e190b1e0059060d041c1d163214060409495811440b4a5a1f580440445849010c1e020d0e3a14041a06070c1019445b1d4e16515e155a4a094d5b",
]

# Try various XOR approaches
for line in lines_hex[:1]:
    data = bytes.fromhex(line)

    # Try single byte XOR
    print("Single byte XOR attempts:")
    for k in range(256):
        dec = bytes(b ^ k for b in data[:30])
        printable = sum(1 for c in dec if 32 <= c < 127)
        if printable > 25:
            print(f"  key={k:#04x}: {dec.decode('ascii', errors='replace')}")

    # The prefix "2f21273934" is constant across all lines
    # If we assume output starts with "[extract]" or "Error:"
    prefixes_to_try = [
        b"[extract] Java available",
        b"[extract] Script loaded",
        b"Error: Unable to ",
        b"frida-inject error:",
        b"TypeError: cannot ",
        b"console.log output",
    ]

    print("\nKnown-plaintext XOR attempts:")
    for prefix in prefixes_to_try:
        key = bytes(a ^ b for a, b in zip(data, prefix))
        # Check if key is repeating
        if len(set(key[:4])) == 1:
            # Single byte key!
            k = key[0]
            full_dec = bytes(b ^ k for b in data)
            print(f"  '{prefix.decode()}' -> single byte key {k:#x}: {full_dec}")
        else:
            # Try decoding rest with derived key (repeating)
            key_len = len(prefix)
            full_dec = bytes(data[i] ^ key[i % key_len] for i in range(len(data)))
            readable = sum(1 for c in full_dec if 32 <= c < 127)
            if readable > len(data) * 0.7:
                print(f"  '{prefix.decode()}' (key_len={key_len}): {full_dec.decode('ascii', errors='replace')}")
