# On-device PoGo auto-catcher — autonomous, home-screen toggle

Goal: PoGo catches on its own, **entirely on the phone**. No desktop, no Python, no ADB,
no Tailscale, no Claude. The existing ZygiskFrida in-process gadget is switched to
**SCRIPT mode** so it auto-runs a self-contained `catch.js` on every PoGo launch. A
home-screen button turns catching ON/OFF.

> Nothing here touches the phone. The phone is currently busy (a desktop catcher is
> attached on `127.0.0.1:27047`). These are **local artifacts + exact commands** for a
> later, coordinated deploy the human runs from Termux.

---

## What's in this folder

| File | What it is |
|---|---|
| **`catch.js`** | THE catcher. Self-contained, self-finding, self-driving. Ported 1:1 from `catch_loop_fast.py` (the catcher JS + the Python driver) and `pogo_il2cpp.py` (the Unity liveness singleton finder). Hard-coded config. **This is the only file that must be byte-perfect.** |
| `libgadget.config.so` | The gadget **script-mode** config to install (replaces the current listen-mode one). `type:"script"`, `path` → catch.js, `on_change:"reload"`, `runtime:"qjs"`. |
| `config.script.so` / `config.listen.so` | Canonical staged configs for the **config-swap** toggle (ON = script, OFF = listen). `config.listen.so` is byte-for-byte the device's current config = your restore-to-desktop source of truth. |
| `install_ondevice_catcher.FULL.sh` | **One-shot installer with `catch.js` inlined.** Run once in Termux (root). Writes catch.js, switches the gadget to script mode (backing up the old config), seeds `config.json`, installs the home-screen shortcuts, leaves catching OFF. **Use this one.** |
| `install_ondevice_catcher.sh` | Same installer but as a template (catch.js replaced by a placeholder) — for reading/diffing. The FULL one is what you run. |
| `shortcuts/pogo-catch-{toggle,on,off,status}` | **PRIMARY toggle** (marker-file). Go in `~/.shortcuts/`. Flip a flag file `catch.on` that catch.js polls (~1s, no PoGo restart). Wire `pogo-catch-toggle` to a Termux:Widget home button. |
| `configswap_toggle/` | **ALTERNATIVE toggle** (config-swap). `pogo-catch.sh` flips the gadget between script/listen and relaunches PoGo. More robust (state derived from the live config) but OFF = hand control back to desktop, and each flip restarts PoGo. |
| `DEPLOY_commands.md` | Copy-paste deploy / restore / boot-persistence command sheet. Start here for the actual deploy. |
| `SAFETY_restore_persistence.md` | Safety analysis: restore-to-listen, crash isolation (the GC stop-world deadlock risk), boot persistence, the Frida-17 question. Read before deploying. |

---

## The two toggle designs (pick one)

**A. Marker-file (PRIMARY, recommended).** `catch.js` stays loaded in script mode at all
times; it polls a flag file `catch.on`. Button present→create file→catching ON; absent→OFF.
- Pro: **instant**, no PoGo restart, no downtime. The LateUpdate pump just early-returns when OFF.
- Con: requires script mode to be the permanent gadget mode (you give up the daily desktop-attach
  workflow unless you also keep the config-swap option around).
- Latency: ~1s (the toggle is read from `manage()`, gated at `MANAGE_MS=1000`, driven off the
  per-frame `CameraFollowingGround.LateUpdate` hook). Only ticks while PoGo is foregrounded — which
  is exactly when you want catching anyway.

**B. Config-swap (ALTERNATIVE, robust).** The button physically swaps `libgadget.config.so`
between `config.script.so` and `config.listen.so` and relaunches PoGo.
- Pro: ON/OFF state is **derived from the real live config** (can't drift); OFF cleanly returns the
  gadget to listen mode so the **desktop tools still work**. Single-flight locked; atomic config write.
- Con: each toggle **force-stops + relaunches PoGo** (a few seconds of downtime).

You can keep BOTH on the device. Use A for moment-to-moment ON/OFF; use B's `off` as the
"give me desktop control back" panic button.

---

## Install (LATER — phone is busy now)

All on the phone, in Termux, root present. Full detail in `DEPLOY_commands.md`; the short path:

```sh
# 0) BACK UP the gadget dir first (your rollback)
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'

# 0b) READ THE GADGET VERSION (decides nothing fatal, but good to know — see risk note below)
su -c 'strings /data/local/tmp/re.zyg.fri/libgadget.so | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+" | sort -uV | tail'

# 1) get install_ondevice_catcher.FULL.sh onto the phone (no PC):
#    in Termux:  nano ~/inst.sh  -> paste the FULL.sh contents -> Ctrl-O, Enter, Ctrl-X
#    then:
bash ~/inst.sh

# 2) restart PoGo so the gadget loads script mode
su -c 'am force-stop com.nianticlabs.pokemongo'
monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1

# 3) once PoGo is on the map, turn catching ON
su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'

# 4) watch it (on-device, no PC):
su -c 'logcat -s frida-catch'          # primary log (catch.js writes here)
# or:  ~/.shortcuts/pogo-catch-status  # ON/OFF + tail of catch.log
```

Home-screen button: install **Termux:Widget** (F-Droid — it is NOT installed yet), then
long-press home → Widgets → Termux:Widget → pick `pogo-catch-toggle`.

### Revert to the desktop/listen workflow (panic button)
```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1
# desktop can now attach again on 127.0.0.1:27047 (pogo_il2cpp.py / catch_loop_fast.py)
```

---

## The one real risk: gadget Frida version (and why catch.js is built to survive it)

There is a 2025 wave of "gadget **script mode** is broken on Frida 17+/Android" reports
(frida #3526, #3516, #3558, #3645). **Two distinct things are conflated in those threads, and
neither breaks this script:**

1. **Bridge removal.** Frida 17 unbundled the Java/ObjC/Swift bridges from the gadget runtime.
   Scripts that call `Java.use`/`Java.perform` now fail silently unless `frida-compile`d with the
   bridge. **`catch.js` uses ZERO bridges** — it is pure native (`Process.findModuleByName`,
   `module.enumerateExports()`, `NativeFunction`, `NativeCallback`, `Interceptor.attach`,
   `Memory.alloc`, pointer reads). Pure-native scripts load and run on 17 exactly as on 16.
   Confirmed by the Frida 17 release notes (only bridges removed; GumJS native runtime incl.
   `console.log` retained) and by the issue threads themselves (the failing scripts all used the
   Java bridge / `npm install java bridge`).

2. **Static `Module.*` removal.** Frida 17 removed the *static* `Module.findExportByName`,
   `Module.getExportByName`, `Module.enumerateExports`, etc. catch.js is written to the **instance**
   API that 17 kept: `Process.findModuleByName('lib').enumerateExports()` /
   `.findExportByName(...)`, with `Module.getGlobalExportByName` as a fallback. (An earlier draft
   used the removed static `Module.findExportByName` in the bootstrap — **fixed**; verified no
   static `Module.*` remain.)

Independent proof it will work on THIS device: the gadget **already runs JS daily** — the desktop
catcher attaches on 27047 and injects the very same IL2CPP NativeFunction + LateUpdate-hook code.
The only thing autonomy changes is *how the script gets in* (read off disk vs. pushed over TCP).

Two more gadget-script-mode gotchas, both already handled in catch.js:

- **`setInterval`/`setTimeout` don't fire in gadget script mode** (frida #2848/#2879 — the QuickJS
  poll loop isn't driven after top-level code returns). catch.js uses **NO JS timers**: a temporary
  `clock_gettime` interceptor (called every frame by the engine) retries `install()` until the
  IL2CPP `LateUpdate` pump lands, then detaches; thereafter everything is driven by the LateUpdate
  hook on its own thread.
- **`console.log` is dropped with no host connected.** catch.js routes logs to Android logcat via
  `__android_log_write` under tag **`frida-catch`** (and best-effort mirrors to `catch.log`).
  View: `logcat -s frida-catch`.

If, after deploy, `logcat -s frida-catch` shows **nothing** and PoGo runs fine, the gadget version
is the suspect: downgrade `libgadget.so` to a known-good **16.x arm64** gadget (e.g. 16.7.19) — see
the recovery ladder in `DEPLOY_commands.md`. The config-swap toggle's `pogo-catch.sh` already prints
a Frida-17 warning if it sniffs a 17+ version.

---

## Catch quality — reproduced exactly from `catch_loop_fast.py`

Same throw mechanics, ball logic, and filters as the proven desktop catcher:
- Open via `MapPokemon.SendEncounterRequest`; throw via `MapPokemon.TryCapture(PokeballThrow, null)`.
- `PokeballThrow` struct: ball id @+0x10, **reticle `0.02 + rand()*0.10` (Excellent band)** @+0x14,
  spin=1 @+0x18, curve=1 @+0x19, bullseye=0 @+0x1a. (Verbatim offsets/values.)
- Data-driven ball pick from `EncounterOutProto` capture probabilities: cheapest ball whose base
  prob ≥ `0.5`, else step up; respects per-tier floors (Poke/Great/Ultra=5). POKE→GREAT→ULTRA.
- Re-throw on `CatchPokemonOutProto` status 2 (escape) / 4 (miss), up to 4 throws, 2s apart.
  1=success, 3=flee → done.
- Range filter: `MapAvatar` GPS + `MapPlaceDirectoryService.get_AllPokemon`, haversine, cutoff 80m;
  `VisibleOnMap` gate; nearest/complete spawn list.
- Skips legendaries/mythicals/UBs (national-dex list).
- Optional Pinap via `ItemBag.UseItemForEncounter` (OFF by default; `USE_PINAP`).
- Rate: 35 opens/min, wall-clock gated (framerate-independent).

Tune by editing the `CFG = { ... }` block at the top of `catch.js`, then (with `on_change:"reload"`)
just copy the new file over — the gadget hot-reloads it, no PoGo restart.
```

(Singletons it finds itself — replacing the Python driver — via the ported Unity GC liveness API:
`MapPlaceDirectoryService`, `MapAvatar`, `ItemBag` (by working `GetItemCount`), `IapService`
(stardust readout). `il2cpp_stop_gc_world` → `il2cpp_unity_liveness_*` → `il2cpp_start_gc_world`,
ported from `pogo_il2cpp.py`. The start/stop are paired inside a try/finally so a scan fault can
never leave PoGo's GC world suspended — see `SAFETY_restore_persistence.md` §2c.)
```
