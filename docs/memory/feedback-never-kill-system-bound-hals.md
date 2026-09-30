---
name: feedback-never-kill-system-bound-hals
description: "NEVER stop/kill HAL services system_server binds to (GNSS, modem, etc.) — it hangs system_server → watchdog crash loop → reboot into safe mode"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 23479c7f-0c89-4422-8b89-8816a5d0591b
---

On 2026-06-05 I ran `setprop ctl.stop pixel.gnss-default gnssd slsi_gnss_service` to "nuke" the real GNSS as a Georgia-hardening step. It looked clean for ~12s (mock survived, system_server alive), so I declared success. It was NOT clean: system_server's location threads make **synchronous binder calls to `android.hardware.gnss.IGnss`**; with the HAL dead those threads hung, the **watchdog killed system_server**, it restarted, hit the dead HAL, hung again — a crash loop (dropbox showed a watchdog/ANR every minute for ~6 min), then a reboot into **safe mode**. The user's phone looked "shut off / won't boot" — it was actually system_server crash-looping.

**Why:** stopping a HAL the framework holds live references to doesn't disable the feature gracefully — it blocks the callers. system_server is watchdog-protected; a hung critical thread = forced kill = whole-UI restart, looping until reboot/safe mode. Modem-adjacent services (Tensor `slsi_gnss_service`) are especially dangerous.

**How to apply:**
- NEVER `ctl.stop`/kill GNSS, modem/RIL, SensorService, SurfaceFlinger, or any HAL system_server binds to. To suppress a sensor/feature, hook at the app or framework layer, or use a provider override — never kill the producer.
- A HAL kill "looking fine for 10s" means nothing — the watchdog timeout is ~60s. Verify stability over minutes AND check `/data/system/dropbox` for `system_server_watchdog`/`anr` before claiming success.
- Before calling a phone "fine," read the crash logs (dropbox, logcat -b events, pstore) — do not eyeball one uptime snapshot. I gave repeated false all-clears by skipping this. See [[feedback-verify-before-irreversible]] and [[project-pogo-spoof-stack]].
- For the actual goal (hide raw GNSS from PoGo): the safe path was Pokemod's own GNSS guard, NOT killing the chip stack. The raw-GNSS vector was already dormant (`last measurements=null`, chip idle) — no aggressive action was even warranted. See [[reference-dumpsys-location-et-field]].
