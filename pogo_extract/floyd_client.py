#!/usr/bin/env python3
"""
floyd_client.py - Connect to pokemod-injector's Floyd (rebranded Frida) server.

Usage:
  python floyd_client.py patch    # Make a Floyd-renamed copy of frida's _frida.pyd
  python floyd_client.py connect <pid> <script.js>  # Connect via patched module + frida-server fallback

Background:
  pokemod-injector is Frida 17.8.2 with all 'frida' identifiers renamed to 'floyd'.
  Wire-level renames found in pokemod-injector.bin:
      frida:rpc            -> floyd:rpc
      re.frida.HostSession17 -> re.floyd.HostSession17
      /re/frida/HostSession  -> /re/floyd/HostSession
      ... (full table in floyd_protocol.md)

  HOWEVER: pokemod-injector is the 'frida-inject' (one-shot) variant, not 'frida-server'.
  It has no listen mode -- it injects, runs script, exits. There is no persistent
  Floyd server to connect to from outside.

  The /floyd-zymbiote-<32hex> abstract socket only exists transiently during a
  zymbiote (zygote-fork) injection, which only happens when Pokemod orchestrates
  a process spawn, not for already-running PoGo.

  Hence the practical client for our 858-transfer use case is vanilla
  frida-server 17.9.5 already working at /data/local/tmp/frida-server on the phone.
  This file documents the full identifier table so a Floyd-protocol client COULD
  be built later (e.g. to ride a live Pokemod injection if Pokemod's RPC tag
  is reused there), but does not implement one because there's no daemon to talk to.
"""
import sys, shutil, struct
from pathlib import Path

FRIDA_PYD = Path(r"C:\Program Files\Python314\Lib\site-packages\frida\_frida.pyd")
FLOYD_PYD = Path(__file__).parent / "_floyd.pyd"

# Wire-level renames discovered in pokemod-injector.bin (all 5-for-5 substitutions).
RENAMES = {
    b"frida:rpc": b"floyd:rpc",
    b"re.frida.": b"re.floyd.",
    b"/re/frida/": b"/re/floyd/",
}


def patch_pyd():
    """Binary-patch frida's _frida.pyd to use Floyd identifiers in-place."""
    if not FRIDA_PYD.exists():
        sys.exit(f"frida _frida.pyd not at {FRIDA_PYD}")
    data = FRIDA_PYD.read_bytes()
    out = data
    counts = {}
    for old, new in RENAMES.items():
        assert len(old) == len(new), f"length mismatch: {old!r} {new!r}"
        n = out.count(old)
        out = out.replace(old, new)
        counts[old.decode()] = n
    FLOYD_PYD.write_bytes(out)
    print(f"[+] wrote {FLOYD_PYD} ({len(out)} bytes)")
    for k, v in counts.items():
        print(f"    replaced {k!r}: {v} occurrences")
    print("[!] Floyd-protocol pyd is built but cannot be used without a Floyd SERVER")
    print("    (pokemod-injector is one-shot inject, not a persistent listener).")


def connect(pid: int, script_path: str):
    """Connect to vanilla frida-server (because Floyd-server doesn't exist as deployed)."""
    import frida, time
    mgr = frida.get_device_manager()
    dev = mgr.add_remote_device("127.0.0.1:31337")
    print(f"[+] using device: {dev}")
    dev.enumerate_processes()  # refresh cache
    procs = dev.enumerate_processes()  # second refresh after add_remote_device
    matched = [p for p in procs if p.pid == pid]
    if not matched:
        sys.exit(f"PID {pid} not visible to frida-server (try restarting frida-server)")
    sess = dev.attach(pid)
    print(f"[+] attached to PID {pid}")
    code = Path(script_path).read_text()
    script = sess.create_script(code)

    def on_msg(m, data):
        print("MSG:", m, "DATA:" if data else "", data or "")
    script.on("message", on_msg)
    script.load()
    print("[+] script loaded; sleeping 5s for messages")
    time.sleep(5)
    sess.detach()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "patch":
        patch_pyd()
    elif cmd == "connect":
        connect(int(sys.argv[2]), sys.argv[3])
    else:
        sys.exit(f"unknown command {cmd!r}")
