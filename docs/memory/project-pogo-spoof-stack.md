---
name: project-pogo-spoof-stack
description: "How the phone's PoGo location spoof is wired — GPS Joystick system-mock → Pokemod bridge → PoGo; the real leak vector is raw GNSS, not the mock"
metadata: 
  node_type: memory
  type: project
  originSessionId: 23479c7f-0c89-4422-8b89-8816a5d0591b
  modified: 2026-09-21T03:31:34.485Z
---

The Pixel 9 Pro's PoGo location spoof (as of 2026-06-05):

- **GPS Joystick** (`com.theappninjas.fakegpsjoystick`) is the **system mock-location provider**. `gps` and `network` show `[mock]` in dumpsys (identity: GPS Joystick). `fused` does NOT: it is GMS FLP (identity `gms[fused_location_provider]`), which fuses the mocked gps/network. At the 2026-09-20 read its last location equalled the mock position, but FLP also wakes the real chip on PoGo's WorkSource. The spoofed position moves with use (Chicago was the June value). Its faking runs in the **`:overlay`** process (the OverlayService), not main. The mock IS fresh — see [[reference-dumpsys-location-et-field]]. Re-check with dumpsys before relying on any provider being mocked.
- **Pokemod** (`com.pokemod.app.public`, "Pro" tier, `INJECTION_TYPE_V2=attach`, `VPGP_ENABLED=true`) attaches into PoGo and **bridges** the system location into the game. This is the user's words: "Pokemod bridges GPS Joystick."
- **Hide Mock Location** (`io.github.auag0.hidemocklocation`) hides the isMock flag from PoGo.
- **iPogo** (`app.ipogo.android.launcher`) is installed but **vestigial** — no config/prefs, not running.

**The real Georgia-detection vector is NOT the mock** — the app-facing providers serve the spoofed position. It's raw GNSS data straight from the chip, which reveals the real physical location, bypassing the mock. 2026-09-20: PoGo was not a GNSS-MEASUREMENT subscriber this boot, but it IS a GnssStatus listener (dumpsys: GNSS Manager > Status Provider), so chip-sourced satellite status still reaches it. The chip is not idle: `gms[gnss_location_provider]` ran gps_hardware 3h55m (10,223 fixes) and registered with `WorkSource{com.nianticlabs.pokemongo}` at 21:01:43-21:02:38, around a GPS Joystick mock-override reset. WiGLE holds 1 s gps and fused requests (2h51m), and the fused one can wake the chip through GMS FLP. The chip's last real fix was ~1,200 km from the mock. Re-read `dumpsys location` before relying on any of this: the Gnss Measurement aggregate, the GNSS Manager listeners, the gps_hardware aggregate and the event log.

**Don't "fix" this by attaching your own Frida to PoGo** — Pokemod already injects there; a 2nd Frida runtime in-process risks crashing the game/session. The correct hardening is **Pokemod's own GNSS/anti-detection setting** (block/spoof measurements), not the system-mock layer. Related: [[project-pogo-extract]], [[pogo-on-phone-catcher]].
