# Autonomous On-Device PoGo Auto-Catcher — Human Guide

**The phone catches Pokemon on its own. You tap a home-screen button to turn it on or off. No PC, no ADB, no Tailscale, no Claude, no Python — once installed, the phone does everything by itself.**

This guide is for a human operator. It explains what the system is, how it makes the phone autonomous, how to install it (entirely from the phone), how to use the on/off buttons, how it shares the one Frida gadget with the desktop catcher (they are mutually exclusive — explained below), and how to troubleshoot or fully restore the phone.

> Device assumed: rooted Pixel 9 Pro, Android 16, Magisk + LSPosed, the "Pokemod" PoGo build (`com.nianticlabs.pokemongo`), Termux + Termux:Boot + Termux:API installed. The ZygiskFrida in-process gadget lives at `/data/local/tmp/re.zyg.fri/`.

---

## 1. What this is

Pokemon GO already has a Frida "gadget" injected into its own process by ZygiskFrida (a Magisk/Zygisk module). A gadget is a small piece of code that loads *inside* the target app and can either:

- **listen** on a network port and wait for a PC to attach and drive it (this is how the **desktop catcher** works today — your PC runs `catch_loop_fast.py`, which attaches over `127.0.0.1:27047` and tells PoGo what to do), **or**
- **run a script** all by itself, with no PC attached at all.

This system uses the **second** mode. It ships a single self-contained JavaScript file, **`catch.js`**, that the gadget auto-runs every time PoGo launches. `catch.js` *is* the entire catcher — it finds the game's own objects, walks the live spawn list, opens encounters, and throws balls, all from inside PoGo's process. There is no host program of any kind.

A 0-byte **marker file** (`/data/local/tmp/re.zyg.fri/catch.on`) is the on/off switch. When that file exists, `catch.js` catches; when it's gone, `catch.js` sits idle (still loaded, instantly resumable). A **home-screen button** (a Termux:Widget shortcut) creates or removes that file with one tap. That's the whole product: a button on your home screen that turns autonomous catching on and off.

### Where the catcher came from

`catch.js` is a faithful 1:1 port of the desktop catcher, so the catch behavior is identical. The two source files it was ported from:

- **`pogo_extract/system/scripts/game_write/catch_loop_fast.py`** — the desktop catcher. Its embedded Frida JavaScript already did all the real work (hooking the per-frame pump, opening encounters, throwing with a precisely-built `PokeballThrow`, data-driven ball selection, re-throwing on break-out, range-filtering by GPS, skipping legendaries). The Python *outer loop* only found the game's singleton objects and pushed their pointers into the JS, then printed stats.
- **`pogo_extract/pogo_il2cpp.py`** — the shared IL2CPP/Frida helpers. Its `JS_PREAMBLE` contains the **Unity liveness object-finder** (`il2cpp_unity_liveness_*` + stop/start-the-GC-world) that locates a live instance of any game class. The desktop used it from Python via `find_singleton(ns, cls)`.

Because gadget script mode has **no Python and no RPC host**, `catch.js` had to absorb *both* halves: it finds its **own** singletons (the liveness finder, ported into standalone JS), hard-codes its **own** config, and drives its **own** loop. That's what makes it self-contained and self-starting.

---

## 2. How it makes the phone autonomous

### 2.1 Self-starting (no host to kick it off)

When PoGo launches, Zygisk injects the gadget, the gadget reads its config file `libgadget.config.so`, sees `type:"script"`, loads `catch.js`, and calls `init()`. `init()` returns **immediately** (it never blocks the game launch), then arms a tiny bootstrap that watches for the game engine to finish loading. The moment IL2CPP (the game's .NET runtime) and the camera pump method are live, `catch.js` installs its hooks and starts driving itself. No PC, no command, no human action — launching PoGo is the only trigger.

### 2.2 Self-driving (no timers, no polling host)

The catcher is driven entirely off one per-frame hook on the game's own render method `CameraFollowingGround.LateUpdate`. Every frame calls `tick()`. Everything inside `tick()` is gated by **wall-clock milliseconds**, so timing is framerate-independent:

- ~1×/second, `manage()` runs: it (lazily) finds the game singletons, reads your ball counts, decides which ball types are still above their floor, refills the spawn queue from the live map, and reads the on/off marker.
- The open/throw pipeline opens an encounter, waits a fixed lag (3500 ms) to hide latency, then throws — so opens and throws are interleaved and continuous.

> Why no `setInterval`/`setTimeout`? In Frida **gadget script mode** those timers can hang and never fire (a known Frida bug). The per-frame engine hook runs on PoGo's own native render thread, which is immune to that bug. This is *why* the catcher is built as a frame pump rather than a timer loop.

### 2.3 Self-finding its objects (the ported liveness finder)

The desktop relied on Python calling `finder.exports_sync.find_singleton(ns, cls)`. `catch.js` reimplements that exact procedure in JavaScript (`livenessFind()`), ported from `pogo_il2cpp.py` lines 104–132:

```
runtime_class_init(klass)
stop_gc_world()
state = unity_liveness_allocate_struct(klass, 0, onObjects, 0, realloc)
unity_liveness_calculation_from_statics(state)
unity_liveness_finalize(state)
start_gc_world()              <-- ALSO called on the exception path (critical: a
unity_liveness_free_struct(state)   stopped GC world left un-started would ANR-freeze PoGo)
```

`onObjects` collects every live instance of the class. The catcher then picks the right one using the **same discriminators the Python driver used**:

| Object | What it's for | How the right instance is chosen |
|---|---|---|
| `MapPlaceDirectoryService` | the live spawn list (`get_AllPokemon`) | by class name |
| `MapAvatar` | your GPS location (for range filtering) | by class name |
| `ItemBag` | ball / berry counts | the instance whose `GetItemCount(1)` actually works |
| `IapService` | (desktop read stardust here) | highest PokeCoins, stardust tie-break |

Namespaces are looked up at runtime (not hard-coded), so the finder survives game updates that shuffle namespaces.

### 2.4 Catch quality — identical to the desktop

Every catch parameter is bit-identical to `catch_loop_fast.py`:

- **Range:** only spawns within **80 m** (haversine distance from your GPS) are opened. Cutoff sits between confirmed-catchable (~64–69 m) and confirmed-flee (~85 m).
- **Visible-only:** skips spawns not yet visible on the map.
- **Ball selection (data-driven):** reads each encounter's per-ball capture probabilities from `EncounterOutProto`, then picks the **cheapest** ball whose base catch probability ≥ **0.5**; if none clears the bar, it steps up Poke → Great → Ultra and uses the best available.
- **Throw:** builds a `PokeballThrow` with reticle radius `0.02–0.12` (**Excellent** throw), spin/curve = 1, bullseye flag set — i.e. it throws Excellent curveballs.
- **Re-throw:** on break-out (status 2) or miss (status 4) it re-throws after 2 s, up to **4 throws** per encounter. Success (1) and flee (3) stop.
- **Rate:** **35 opens/minute**.
- **Ball floors:** stops using a ball type once it drops to **5** left; when *all three* hit their floor, catching auto-stops. So it never empties your bag.
- **Legendaries / mythicals / ultra beasts** (a national-dex skip list) are **never** auto-caught — they're filtered out so you catch them yourself.
- **Pinap berries:** OFF by default (saving them); can be enabled in config.

These values are hard-coded near the top of `catch.js` in the `CFG` block. To change them you edit `catch.js` (see §8).

---

## 3. The two controls (read this before installing)

There are **two separate switches**. Do not confuse them.

| Control | What it is | How you use it | Speed | When to use |
|---|---|---|---|---|
| **Run-state** *(the everyday button)* | presence of the marker file `catch.on`, which `catch.js` polls ~1×/s | tap the **`pogo-catch-toggle`** home-screen button (or `-on` / `-off`) | **instant (~1 s), no restart** | turning catching on/off during normal solo play |
| **Mode** *(panic / hand control to PC)* | which gadget config is live: **script** (autonomous) vs **listen** (desktop attaches) | run **`pogo-catch.sh`** (or its `-desktop` / `-autonomous` buttons) | ~10–20 s (force-stops + relaunches PoGo) | switching the phone between "catches on its own" and "PC drives it"; fully disabling |

**The everyday button is the run-state marker.** It's instant because `catch.js` stays loaded and just checks a file. You'll use it 99% of the time.

**The mode switch is the heavier lever.** It physically swaps the gadget's config and relaunches PoGo, because the gadget only reads its config once at injection time. You use it only when you want to give the phone back to the desktop catcher (or take it back). See §6.

---

## 4. How it coexists with the desktop catcher (mutually exclusive — why)

**There is exactly ONE Frida gadget inside PoGo, and it can be in exactly ONE mode per launch.** That single fact makes autonomous and desktop catching mutually exclusive — they can never both run at once. This is by design and is the safety property that prevents two catchers fighting over the same encounters.

The gadget reads `libgadget.config.so` when PoGo starts, and that file is either:

- **script mode** — `{"interaction":{"type":"script","path":".../catch.js","on_change":"reload"},"runtime":"qjs"}`
  → the gadget **runs `catch.js`** and opens **no** network port. The desktop's `catch_loop_fast.py` literally cannot attach (nothing is listening). **The phone catches solo.**

- **listen mode** — `{"interaction":{"type":"listen","address":"127.0.0.1","port":27047,"on_load":"resume"}}`
  → the gadget opens **`127.0.0.1:27047`** and runs **no** `catch.js`. Your PC attaches and drives, exactly as it does today. **The PC catches; the phone runs zero catch logic.**

Switching between them = swapping that one config file and relaunching PoGo. That's what `pogo-catch.sh on` / `off` does (`on` = script/autonomous, `off` = listen/desktop). State is **derived from the live config's actual contents**, so it can never drift out of sync with reality.

### What this means in practice

- You can **replace** the desktop catcher with the on-device one: switch the phone to **script mode** once, and from then on the home-screen button is your only control. The PC is no longer involved.
- You can **switch back** to the desktop at any time: switch to **listen mode**, then attach `catch_loop_fast.py` from the PC. One command, always available.
- There is **never** a window where both catch the same spawn. Only one config is live per PoGo process.

> **Important for the first switch:** flipping the phone to autonomous (script mode) **force-stops PoGo**, which **severs any live desktop session**. If your PC is actively catching, stop the desktop catcher first (or accept the link drop) as part of a deliberate cutover. PoGo state is server-authoritative, so a mid-flight swap at worst drops one throw; the next launch re-syncs.

---

## 5. Installing it — step by step, entirely from the phone

You do **not** need a PC for any of this. Everything is done in Termux on the phone.

### 5.1 One-time prerequisites (do these once)

1. **F-Droid:** install **Termux:Widget** (gives you the home-screen button) and confirm **Termux:Boot** is installed.
   - ⚠️ **Termux:Widget MUST come from the same source (same signing key) as your base Termux.** If base Termux is the F-Droid build, install Termux:Widget from F-Droid too. A signature mismatch makes the widget silently refuse to run your scripts.
2. **Launch each plugin once** (open Termux:Widget and Termux:Boot at least once so Android registers them).
3. **Grant Termux root** in Magisk (Magisk → Superuser → allow Termux). The buttons use `su`.
4. **Battery:** set Termux, Termux:Widget, and Termux:Boot to **Unrestricted** so Android doesn't kill them.

### 5.2 Back up first, then check the gadget version

Run these in Termux. The backup lets you restore the gadget directory if anything goes wrong:

```sh
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'
su -c 'strings /data/local/tmp/re.zyg.fri/libgadget.so | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+" | sort -uV | tail'
```

The second line prints the gadget's Frida version. **This matters a lot** (see §9, risk #1): Frida **17.x** gadgets are reported to *parse but not execute* a script mode in this configuration — meaning `catch.js` would load but silently do nothing. If you see **17.x or higher**, plan to swap in the bundled **16.7.19** gadget (`gadget16/`) during the smoke test. If you see **16.x**, you're in the known-good range.

### 5.3 Run the installer

Get `install_ondevice_catcher.FULL.sh` onto the phone. The simplest no-PC way: in Termux, open a new file with the built-in editor, paste the script in, and save it:

```sh
nano ~/inst.sh        # paste the FULL installer, then Ctrl-O, Enter, Ctrl-X
bash ~/inst.sh
```

The installer:

- writes **`catch.js`** into `/data/local/tmp/re.zyg.fri/` (the full catcher is inlined in the installer),
- stages both mode configs (`config.script.so`, `config.listen.so`) **and** the fallback 16.7.19 gadget — but does **not** auto-swap anything,
- installs the home-screen shortcuts into `~/.shortcuts/` (`pogo-catch-toggle`, `-on`, `-off`, `-status`, `-desktop`, `-autonomous`),
- installs the watchdog and boot script,
- **leaves the run-state marker OFF and the live gadget config UNTOUCHED.**

So after the installer, **nothing has changed about how PoGo runs yet.** The phone is staged but still in whatever mode it was in.

### 5.4 Smoke-test that the gadget can run a script at all (the gate)

**Do this before trusting the catcher.** It proves the gadget actually *executes* script mode (rules out the Frida-17 silent-no-op). Point the script config at a 3-line `smoke.js` that just writes one logcat line, swap the live config to it, relaunch PoGo, and watch:

```sh
su -c 'logcat -s frida-catch'
```

- **You see `[smoke] script mode ALIVE`** → the gadget executes scripts. 
- **Silent, but PoGo runs fine** → the gadget is the 17.x-broken kind. Swap in the 16.x gadget (§9, step F) and repeat. **Do not proceed until smoke prints.**

(The exact smoke.js and commands are in `DEPLOY_commands.md`.)

### 5.5 Switch the phone to autonomous (the one deliberate step)

Only after the smoke test passes — and after stopping the desktop catcher if it's running:

```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.script.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1
```

Watch `su -c 'logcat -s frida-catch'` — you should see the catcher come up:
`init …` → `installed …` → `waiting for PoGo to load …` → `READY — msvc=ok … itembag=ok … Poke=N Great=N Ultra=N`. **Nothing is thrown yet** (the run-state marker is still OFF).

### 5.6 Add the home-screen button

1. Long-press your home screen → **Widgets** → **Termux:Widget**.
2. Place the **1×1** widget.
3. Pick **`pogo-catch-toggle`**.

Tap it once PoGo is on the live map. Catching starts within ~1 second. Tap again to stop.

> If Termux:Widget shows "no regular file": ensure `~/.shortcuts` has permissions `700`, the scripts are executable, and each has the full-path shebang `#!/data/data/com.termux/files/usr/bin/sh`. The shipped shortcuts already meet this.

---

## 6. Using it day to day

### The buttons (Termux:Widget shortcuts in `~/.shortcuts/`)

| Button | What it does | Speed |
|---|---|---|
| **`pogo-catch-toggle`** | **Your main button.** Flips catching ON↔OFF (creates/removes the marker). Toasts the new state. | instant |
| `pogo-catch-on` | Force catching ON. | instant |
| `pogo-catch-off` | Force catching OFF (idle — **not** a handoff to the PC). | instant |
| `pogo-catch-status` | Shows ON/OFF, heartbeat age, and the last lines of the catch log. | instant |
| `pogo-catch-desktop` | **Panic / give the PC control.** Switches the gadget to *listen* mode and relaunches PoGo, so your desktop catcher can attach. Also the clean way to fully disable in-process catching. | ~10–20 s |
| `pogo-catch-autonomous` | Switches the gadget back to *script* mode and relaunches PoGo. Re-arms autonomy after a desktop session. | ~10–20 s |

### Typical flow

1. Open PoGo, get onto the map with spawns nearby.
2. Tap **`pogo-catch-toggle`** → toast says "PoGo auto-catch: ON" → it starts throwing within ~1 s.
3. Play, walk, do raids — leave it running. It only opens in-range spawns and skips legendaries.
4. Tap **`pogo-catch-toggle`** again to pause. PoGo stays open; catching resumes instantly when you tap ON again.

### Watching what it's doing (no PC)

Tap **`pogo-catch-status`**, or in Termux:

```sh
su -c 'logcat -s frida-catch'
```

Every ~10 seconds the catcher prints a stats line:
`fired=… caught=… esc=… flee=… miss=… q=… vis=… inr=… P/G/U …`
where `caught` should climb, `P/G/U` are your remaining Poke/Great/Ultra counts, `vis` is spawns seen, `inr` is spawns in range. Acceptance: `caught` rises, ball counts drop, rate ≈35 opens/min, legendaries skipped, only ≤80 m spawns opened. Cross-check `caught` against PoGo's own journal/box.

> The marker is loose-permissioned (`chmod 666`) so PoGo's app user can read the shell-created file. The on-screen toasts come from Termux:API (`termux-toast`).

---

## 7. Manual control without the buttons (Termux one-liners)

The buttons are just thin wrappers. You can do everything by hand from Termux:

```sh
# Run-state (instant; no restart):
su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'   # ON
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'                                                     # OFF

# Mode (relaunches PoGo):
su -c '/data/local/tmp/re.zyg.fri/pogo-catch.sh autonomous'   # script mode (phone catches solo)
su -c '/data/local/tmp/re.zyg.fri/pogo-catch.sh desktop'      # listen mode (PC can attach)
su -c '/data/local/tmp/re.zyg.fri/pogo-catch.sh toggle'       # flip script<->listen
su -c '/data/local/tmp/re.zyg.fri/pogo-catch.sh status'       # show derived state + config + log tail
```

> `pogo-catch.sh` subcommands are `on` (= autonomous/script), `off` (= desktop/listen), `toggle`, `status`. It is idempotent (re-running `on` when already on is a no-op — no needless restart), swaps the config atomically (temp file + `mv`, so the gadget never sees a half-written config), serializes concurrent runs with a lock (double-taps are safe), and derives state from the live config's real contents.

---

## 8. Changing catch behavior

All tunables are the `CFG` block at the top of `/data/local/tmp/re.zyg.fri/catch.js`:

| Setting | Default | Meaning |
|---|---|---|
| `RATE_PER_MIN` | 35 | opens per minute |
| `MAX_RANGE_M` | 80 | GPS range cutoff (meters) |
| `POKE_FLOOR` / `GREAT_FLOOR` / `ULTRA_FLOOR` | 5 | stop using that ball at/below this count |
| `CATCH_THRESHOLD` | 0.5 | use cheapest ball with base catch prob ≥ this |
| `LAG_MS` | 3500 | open→throw latency hide |
| `RETHROW_DELAY` / `MAXTHROW` | 2000 / 4 | re-throw timing and cap |
| `USE_PINAP` / `PINAP_FLOOR` | false / 20 | enable Pinap feeding + keep this many |
| `LEGENDARY_DEX` | (long list) | national-dex #s never auto-caught |

Because the live script config uses `"on_change":"reload"`, editing `catch.js` **reloads it without relaunching PoGo** — the catcher cleanly detaches its hooks and re-installs (it has hot-reload handling built in). Edit on-device:

```sh
su -c 'nano /data/local/tmp/re.zyg.fri/catch.js'   # change CFG, save; gadget hot-reloads
```

If a risky edit ever double-installs hooks, set the script config's `on_change` to `"ignore"` and relaunch PoGo manually instead.

---

## 9. Troubleshooting

Work top-down: prove the gadget runs a script → prove the catcher self-starts → prove it throws.

| Symptom | Likely cause | Fix |
|---|---|---|
| **`logcat -s frida-catch` is totally silent after launch, but PoGo runs fine** | Gadget is **Frida 17.x**, which parses script mode but doesn't execute it (the #1 failure — see risk table). | Swap in the bundled **16.7.19** gadget (step F below), then re-run the smoke test. `catch.js` itself is gadget-version-agnostic. |
| Logcat shows `init …` then `waiting for PoGo to load …` forever | Engine not ready yet (still pre-menu), or you're on a loading screen. | Get PoGo fully onto the live map. The catcher gates on engine readiness and retries every frame; it arms once the map is up. |
| `READY` printed but tapping ON throws nothing | No in-range spawns, or `RUN` didn't flip. | Confirm spawns within 80 m exist; check `pogo-catch-status` shows ON and the marker exists (`su -c 'ls -l /data/local/tmp/re.zyg.fri/catch.on'`). |
| Home button does nothing / no toast | Termux:Widget signature mismatch, missing root grant, or `~/.shortcuts` perms. | Reinstall Termux:Widget from the **same source** as Termux; grant Termux root in Magisk; `su -c 'chmod 700 ~/.shortcuts'`; confirm `pogo-catch-status` shows whether the marker flipped. |
| Catching seems "stuck" (PoGo up, no throws for a while) | Script wedged. | The watchdog auto-relaunches PoGo if the heartbeat goes stale (>90 s). Or relaunch manually: `pogo-catch-desktop` then `pogo-catch-autonomous`. |
| Desktop catcher can't attach | Phone is in **script** mode (no port open). | Tap **`pogo-catch-desktop`** (or `pogo-catch.sh off`) to switch to listen mode, then attach from the PC. |
| Stats line shows `caught=0` but `fired` climbs | Throws landing but not catching (out of range, or balls below floor). | Check `P/G/U` counts and `inr`; raise floors / restock if needed. |

### Reading the heartbeat

The catcher writes `/data/local/tmp/re.zyg.fri/catch.hb` ~1×/second while the pump is alive:
```sh
su -c 'cat /data/local/tmp/re.zyg.fri/catch.hb'   # epoch | RUN | opened | caught
```
Run it twice ~2 s apart — if the epoch advances, the script is healthy. A stale heartbeat means it wedged (the watchdog handles this). The heartbeat is best-effort (SELinux may deny the app writing `/data/local/tmp`); **logcat is the source of truth**, and the catcher does not depend on the heartbeat.

### Step F — swap in the 16.x gadget (only if the smoke test is silent)

```sh
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'cp /data/local/tmp/re.zyg.fri/libgadget.so /data/local/tmp/re.zyg.fri/libgadget.so.17.bak'
su -c 'cp /data/local/tmp/re.zyg.fri/gadget16/libgadget.so.16.7.19 /data/local/tmp/re.zyg.fri/libgadget.so'
su -c 'chmod 644 /data/local/tmp/re.zyg.fri/libgadget.so'
# relaunch PoGo and repeat the smoke test
```
If ZygiskFrida pins a specific gadget hash and the swap doesn't take, fall back to listen mode + the desktop catcher and report it — don't force.

---

## 10. Restore — putting the phone fully back

You can always get back to the original desktop-controlled state.

### Fastest: hand control back to the desktop (no data loss)

```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1
```
PoGo relaunches into **listen mode** (`127.0.0.1:27047`) — exactly today's setup. Your PC `catch_loop_fast.py` can attach again. The `listen.so` shipped here is byte-for-byte the device's original config.

### Stop autonomous catching but keep the phone in script mode

```sh
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'   # OFF; catch.js stays loaded but idle
```

### Full rollback of the gadget directory (if you swapped the gadget binary, etc.)

```sh
ls -d /data/local/tmp/re.zyg.fri.bak.*          # find your backup from §5.2
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'rm -rf /data/local/tmp/re.zyg.fri && cp -a /data/local/tmp/re.zyg.fri.bak.<TS> /data/local/tmp/re.zyg.fri'
```
(Replace `<TS>` with your backup's timestamp.) Then relaunch PoGo. This restores `libgadget.so`, the original config, everything.

### Remove the home-screen pieces

```sh
rm -f ~/.shortcuts/pogo-catch-*                 # delete the shortcut buttons
```
Then long-press the widget on your home screen and remove it. Disable the Termux:Boot autostart by removing the boot script from `~/.termux/boot/` if you set one.

**Rollback ladder (in order of preference):** restore-to-listen → (if smoke was silent) the 16.x gadget swap → the §5.2 directory backup → desktop control. The desktop catcher is always your safety net; autonomy degrading never bricks the device.

---

## 11. Reboot behavior

A boot script (`00-catcher-boot`, installed under Termux:Boot) takes a wake-lock and enforces a chosen default after a reboot. It ships **boot-safe**: after a reboot the phone comes up in **listen mode with catching OFF**, so a reboot never silently starts catching. To resume autonomy, tap **`pogo-catch-autonomous`** then **`pogo-catch-toggle`** (ON). If you prefer the phone to come back already catching, switch to the clearly-labeled boot-autonomous block in that script.

Note: the live gadget mode is itself persistent (it's just a file on disk), so if you leave the phone in script mode it stays in script mode across reboots regardless — the boot script only *enforces* a default and is opt-in.

---

## 12. Files at a glance

On the phone (in `/data/local/tmp/re.zyg.fri/`):

| File | Role |
|---|---|
| `catch.js` | the self-contained catcher (the brain) |
| `catch.on` | the run-state marker (exists = catching) — created/removed by the button |
| `catch.log` / `catch.hb` | debug log / heartbeat |
| `libgadget.config.so` | the **live** gadget config (a copy of one of the two below) |
| `config.script.so` | script-mode config (autonomous) |
| `config.listen.so` | listen-mode config (desktop) — = original |
| `libgadget.so` | the gadget binary (swap to `gadget16/` 16.7.19 if 17.x is broken) |
| `pogo-catch.sh` | the mode-swap driver (`on`/`off`/`toggle`/`status`) |

In Termux (`~/.shortcuts/`): `pogo-catch-{toggle,on,off,status,desktop,autonomous}` — the home-screen buttons.

This repo (`pogo_extract/system/ondevice_toggle/`): all of the above plus `install_ondevice_catcher.FULL.sh` (the on-device installer), `DEPLOY_commands.md` (exact deploy/test commands), `README.md`, `SAFETY_restore_persistence.md`, and this guide.

Ported from: `pogo_extract/system/scripts/game_write/catch_loop_fast.py` (catcher logic) and `pogo_extract/pogo_il2cpp.py` (the liveness singleton-finder).

---

**Bottom line:** install once from the phone, smoke-test the gadget, switch to script mode once, place the `pogo-catch-toggle` widget — then a single home-screen tap turns autonomous catching on and off, with the phone doing all the work and the desktop catcher one `pogo-catch-desktop` tap away whenever you want it back.
