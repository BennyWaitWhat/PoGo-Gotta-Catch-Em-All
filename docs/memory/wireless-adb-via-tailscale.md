---
name: wireless-adb-via-tailscale
description: "Reach the phone over ADB via its stable Tailscale IP (100.98.158.56:5555), not the LAN IP which changes between sessions."
metadata: 
  node_type: memory
  type: reference
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
  modified: 2026-09-25T04:42:01.044Z
---

The most reliable ADB endpoint for the user's phone is its **Tailscale IP**, currently `100.98.158.56:5555` (the canonical PoGo tooling hardcodes this in `pogo_il2cpp.py` as `ADB_TARGET`). The phone's LAN IP changes between sessions (e.g. 192.168.1.121 → 192.168.1.245) and is useless on public WiFi; the Tailscale `100.x.x.x` address is stable and works across home WiFi, public WiFi, and mobile data.

**How to apply:** Connect with `adb connect 100.98.158.56:5555`. If the IP has changed, read it with `adb shell ip -4 addr show tun0` (Tailscale is the /32 on tun0), or run `tailscale status` on the PC and read the pixel-9-pro row. If USB is currently the only link, do `adb tcpip 5555 && adb connect <tailscale-ip>:5555`. The PoGo pipeline's `get_session()` already runs `adb connect` + `adb forward tcp:27047` for you. Relates to [[user-phone-setup]], [[project-pogo-extract]].

**Other Android devices share this ADB server (2026-09-25):** the phone dropped out of `adb devices`, and the only
entry left was `100.113.169.96:5555`, a **Sony Bravia TV** (sony-bravia-4k-2015 on the tailnet). Another session had
connected it. Never send a command to "the device" without `-s 100.98.158.56:5555`, and check
`getprop ro.product.model` (Pixel 9 Pro) before any UI or am command. If the phone is missing, `adb connect` it again.


**2026-09-02 gotcha:** a Sony BRAVIA TV reachable over LAN adb (100.70.99.3:5555; its Tailscale IP is 100.113.169.96) also shows up in `adb devices`, so plain `adb shell` fails with "more than one device/emulator". Always target the phone explicitly: `adb -s 100.98.158.56:5555 ...`. Also: an ADB-over-TCP session goes "offline" after any Tailscale blip and does not self-heal; prefix commands with `adb connect 100.98.158.56:5555`.

Other adb endpoints share the tailnet (2026-09-19): the Google TV "sala-familiar" (100.85.17.54, Smart TV Pro) stays
connected to adb. With the Pixel's Tailscale offline, pogo_il2cpp._resolve_device's fallback ("first device") picked the
TV and the pipeline looked for Pokemon GO on it (found none, aborted, nothing touched). The fallback now accepts only a
USB serial (no ':' in it) that has com.nianticlabs.pokemongo installed. If a pass says "PoGo not running on <ip>",
check `tailscale status` first -- the Pixel row shows "offline, last seen Nh ago" when its Tailscale app is off.

**Cloud sessions (Benny, 2026-09-29):**
- The phone bridge is Tailscale INSIDE the cloud VM: a userspace `tailscaled` plus `socat` -> `tailscale nc 100.98.158.56 5555`.
- The session-start hook binds the phone's OWN address (100.98.158.56:5555) on the VM loopback when it can, else 127.0.0.1:5555,
  and exports `ADB_TARGET` accordingly (plus `TZ=America/New_York`). The phone re-enables adb over TCP 5555 at every boot
  (Magisk `/data/adb/service.d/adb_tcp_5555.sh`).
- Every tool reads `os.environ.get('ADB_TARGET', '100.98.158.56:5555')`: pogo_il2cpp, cutoff_hunt.DEV and the gym tools.
- Never a bare `adb` without `-s`: a TV shares the local adb server.
