---
name: pogo-on-phone-catcher
description: "The autonomous catcher runs entirely ON the phone: frida compiled on-device, Termux + loopback gadget, no desktop or Tailscale."
metadata: 
  node_type: memory
  type: project
  originSessionId: 8fde11a7-6340-4cdf-8f4e-02a95910c52b
  modified: 2026-09-30T00:46:55.228Z
---

# CONTRACT WITH THE CULL (2026-09-29, Pokemon Inventory session)
The cull's rc-8 "frozen read" tripwire parses `catch_loop.log` lines matching `^HH:MM:SS CATCH ` at
`~/pogo/system/analysis/pokemod/catch_loop.log`, and reads `caught=` from `/data/local/tmp/pogo_state.txt`. Suffixes
(` [apple]`) and new line kinds (APPLE / APPLEMON / APPLEGONE / LIMIT / GRAPH) are safe. **Tell that session BEFORE
changing the CATCH prefix, the time format or the log path.** Since 20:42 the catcher picks the live ItemBag and
PlayerService by the newest InventoryCache.latestTimestamp (pickLive). On a tie it falls back to the most-balls rule
and logs `GRAPH`; the cull refuses on a tie instead. See [[pogo-stale-service-graph-2026-09-29]].

# REBUILT 2026-09-24 — read this first (corrected 21:30 after the evening's crashes)
**WHERE THE CODE LIVES NOW:** `Phone Maintenance/AutoCatcher/` (the AutoCatcher session's folder, a desktop mirror of
the phone's `~/pogo` tree): `system/scripts/game_write/catch_loop_fast.py` (+`catch_phone.py`, `reward_catcher.py`,
`reward_phone.py`), `catcher_ctl.sh`, `run_catch.sh`, its OWN `pogo_il2cpp.py`, `ondevice_toggle/` (install scripts +
Auto-Catcher APK source, moved out of pogo_extract), `deploy.sh` (md5-verified push, `--restart`). `pogo_extract/` is
the Pokemon Inventory (cull) session's; the two sessions do not edit each other's folders. Fallback build:
`catch_loop_fast.v1-pause.py` = the old stable catcher + propagate + pause handshake.
Rules, each one a crash:
1. **NativeFunction `{exceptions:'propagate'}` on EVERY il2cpp call.** Frida's default `'steal'` grabs faults ART raises
   ON PURPOSE (CMC GC compaction pages, implicit suspend checks), longjmps out mid-ART, and the next MarkCompact stack
   walk SIGSEGVs (`WalkStack`/`GetOatMethodQuickCode`, 7 tombstones). Proof: `fcerr=1/access violation 0x22e7000`.
2. **The liveness walk (find instances) has exactly ONE safe spot.** Unity's liveness MARKS objects by setting the low
   bit of `obj->klass` and clears it in finalize, so it MUST run with the GC world stopped — unstopped, a Niantic
   network thread read a marked object and SIGSEGV'd on a pointer one byte off (21:02/21:06/21:07, fault addrs
   0x74b6f1e0 / 0x74b6ebf2: a real pointer shifted 8 bits). But a stopped world must never wait on the script's JS
   lock: stopped from UnityMain inside the pump with a JS NativeCallback, it deadlocked against gum-js-loop, which a
   cull had `il2cpp_thread_attach`ed and which was suspended mid-RPC holding that lock (20:58 freeze). SAFE: stop →
   alloc → statics → finalize → start, run from the RPC thread in `install()` BEFORE any hook exists (or in a separate
   finder script, as the old catcher did); validate the hits with managed calls later on UnityMain. ("bdwgc is
   non-moving, the stop is never needed" is true for the BAG WALK only, not for liveness.)
3. **No pointer outlives the tick**: encounters tracked by id; actions use pointers from a walk made in that tick.
   **No il2cpp GC handles** — declared `uint32` they truncated (19:32/19:33 crashes, fault 0xb9cf6020); the API is
   pointer-sized or at least not safe to assume here.
4. **Throw correlation = push our encounter id at TryCapture time** (FIFO vs CatchPokemonOutProto). The request hook
   (CatchPokemonProto WriteTo) never fires for background throws — see `req=None` below; I re-learned it (19 noresult).
5. **Pause handshake** (contract with the cull session): `/data/local/tmp/pogo_pause` (root, 666) holds an epoch-seconds
   deadline. The cull writes now+300 before attaching, polls `ss -tn | grep -c :27047` to 0 (≤16 s), re-arms per phase,
   writes 0 in a finally. The catcher checks it every second while attached (detaches AND
   `remove_remote_device`s — a detached session alone kept the TCP link, so `ss` never hit 0; now 0 in ~1 s), before EVERY attach
   (including after the gadget/cold-age waits — that gap let it attach through a pause at 21:02:53), and heartbeats
   every 30 s while paused. NEVER use the file to pause the catcher by hand: the cull's finally writes 0 over you.
6. **Crash-loop breaker:** PoGo dying within 20 s of our attach twice in a row → no attaching for 30 min.
6b. **Stopping a broken build is not enough — put a SAFE build back on the phone too.** The app's toggle starts
   whatever `catch_loop_fast.py` is on disk: at 21:25:08 catching was switched on from the app while the broken 21:01
   build was still deployed, and it crashed PoGo 1 s after its unstopped lookup (21:25:14). The fixed build
   (b6f4ea80) went live 21:26:43: lookup 379 ms, 3 min clean, 32 caught, errs=0.
7. Frida 17: `NULL` is a read-only global; a `'bool'` NativeFunction arg wants `0/1`, not `false`.
7b. **Frida's JS lock is ONE lock for every script in the gadget** (QuickJS scope mutex). Anything that stops the GC
   world and then needs JS (a NativeCallback) can deadlock against ANY script's JS on a suspended thread. The fix is
   liveness callbacks in C (CModule) — given to the cull session 2026-09-24 so culls can run with the catcher attached.
   **CModule STATIC variables sit on a read-only page in this gadget (Frida 17.4.0):** writing one SIGSEGV'd PoGo on
   gum-js-loop (23:02:07). Keep all C state in a JS-allocated buffer passed as userdata (tested OK in PoGo).
7d. **v3 (23:11, current):** a CModule `onEnter` gates the LateUpdate hook — it counts frames in C and enters JS every
   6th frame (~9x/s; every frame only while tap-to-move is on), so the game's main thread is not taking the shared JS
   lock 55x/s (tested: 550 frames → 91 ticks in 10 s). The C lookup (`find_instances`, state in a JS buffer) runs IN
   PLACE on UnityMain whenever needed: first tick, new map camera, 45 s quiet (backoff to 10 min, catch-on only) —
   no re-attach refresh, Python only attaches/logs. openMs 300, maxOpen 12, READY_MS 150, Pinap floor 5 (user's
   number). **Culls now overlap the catcher** (cull helper uses the same C lookup; `CATCHER_PAUSE_ENABLED=False` in
   full_audit): first overlap 23:08:33-23:09:13, 10 caught during it, PoGo untouched. The pause file stays honoured
   (reward catcher uses it). Rollback: `catch_loop_fast.py.bak.v2live`.
7e. **Incense/lure Pokemon have NO `get_VisibleOnMap`.** The rebuild treated "method missing" as "hidden" and skipped
   every one (945 wild, 0 incense, 0 lure caught 19:30-23:18). Rule (the old catcher's): only a class that HAS the flag
   can say "not visible". Fixed 23:19 — 3 incense caught in the first minute. Also: only caught/fled/legendary/
   maxthrows/catcherr/encounter-refused are final; gone/noresp/noresult cool down 20 s and are retried.
7f. **Miss-audit 2026-09-24 23:2x** (user: "you don't catch all / not the incense / not Applins"): (1) every
   `*EncounterOutProto` that answers a map encounter is hooked now (RotatingSpawn, Incense, Disk, Daily,
   DailyBonusSpawn, PowerUpPokestop, AttractedPokemon, NaturalArtPoi, DayNightPoi, EncounterPokestop); skip list =
   wild (own hook), UseItem, Quest, LoadedQuest, VsSeekerReward, Invasion, FleeBattle, DebugPokemon, Get*. Replies
   are matched to pending opens by SPECIES (PokemonProto.PokemonId via field name), then age — one unanswered type used
   to jam a single FIFO and shift every later reply. (2) NOT_IN_RANGE and status 0 → retry after 20 s (were final).
   (3) `call()` sets LASTOK; a throwing SendEncounterRequest/TryCapture is retried instead of leaving an orphan in the
   result FIFO. (4) TYPES census line: per class on-map/tracked + noid/hidden/skipped/done. StationPokemon reply proto
   is in neither holo-protos nor holo-game (not hooked; station/Max spawns only). Applin (#840) never appeared in
   the log at all — if it is a map spawn, the census will name its class.
7c. **Stale map:** the game can rebuild its map; objects found at attach then read an empty map forever (22:27-22:46,
   20 min of vis=0). Now: a new CameraFollowingGround instance → re-attach (re-lookup); no Pokemon for 45 s with the
   game in front → re-attach (backoff to 10 min). Reconnect: attach at PoGo age 12 s (was 30), the catcher waits for
   PoGo itself (the supervisor's 30 s poll is now 3 s). Speed: openMs 400 (was 667), maxOpen 10, READY_MS 200 —
   0.4-0.7 s per catch without a berry, ~1.5 s with Pinap.
8c. **catch_loop.log lines have NO DATE and the file spans days.** Never slice it by clock time: an earlier night's
   old-format `CATCH r=1 … src=…` lines matched 03:26-03:56 on 2026-09-25, and I wrongly announced a "second
   auto-catcher". Slice by line count (`wc -l` before, `tail -n +N` after) or walk back from the END.
8d. **Back-to-back PoGo restarts trip the crash-loop breaker.** Closing PoGo within 20 s of the catcher attaching,
   twice (my joystick preset restarts 03:41-03:43), put it on a 30-min SAFETY HOLD that nobody noticed for 15 min.
   After any PoGo restart, wait until the catcher logs READY + a catch before touching PoGo again, or override with
   catch-off/catch-on.
8b. **Catcher quiet = check `~/pogo/system/analysis/pokemod/flags.log` first.** 2026-09-25 00:18:20 the app's Catching
   switch went 1 -> 0 during a user accident (PoGo closed, app swiped). The log sat at "waiting for PoGo..." for 22 min with
   no process running. Fix: `su -c 'su 10762 -c "/data/data/com.termux/files/usr/bin/bash ~/pogo/catcher_ctl.sh catch-on"'`;
   it attached and caught 7 within 10 s.
8. Dropped the old per-10 s `find_iap()` (class scan + stop-the-world liveness EVERY report).
Measured (catching builds): attach 0.2 s, ready ~0.4 s, open→caught 0.5–1.0 s (was 3.5–4.5 s), 10.8/min over 15 min,
Pinap verified by candy 6 vs 3, re-throws after break-out work, reward counter = `CatchPokemonOutProto.Scores`
(PascalCase fields). Not yet verified live: the install-time lookup build (written offline after "stop EVERYTHING"),
spin, tap-to-move, Perfect Throw. **The NianticLabsPlugin startup crash** (`[anon:libwebview reservation]` ~2-10 s
after a fresh launch) happens before anything can attach — launch/Pokemod side.

# On-phone autonomous catcher (frida-in-Termux) — BUILT & WORKING (2026-06-04)

The catcher runs ENTIRELY on the phone now — no desktop/Tailscale. This was the
"transplant it to my phone" ask. It works. Key facts so it's never relearned the hard way:

## What runs where
- **frida 17.9.11 compiled on-device** into Termux's python3.13 (cp313, aarch64). It imports + attaches.
- Catcher lives in `~/pogo/` (Termux home): `catch_phone.py` (launcher that monkey-patches
  `pg.get_session` to `dev.attach("Gadget")` on the LOCAL loopback gadget `127.0.0.1:27047`,
  no adb), `catch_loop_fast.py` + `pogo_il2cpp.py` (diverged from desktop — see Deploy below), `run_catch.sh`,
  `catcher_ctl.sh`. Log: `~/pogo/system/analysis/pokemod/catch_loop.log`.
- Connect key: gadget LISTEN mode exposes the process as **"Gadget"** — `dev.attach("Gadget")`
  (pidof returns None in this path; don't rely on pid).
- Catcher runs fine in the **plain Termux app context (no root)** — connects to the loopback
  gadget. Root NOT needed to run it; only the one-time build/symlink-repair used root.

## THE big gotcha: app SELinux domain can't use SYMLINKS
On this device (Pixel 9 Pro / A16), the `untrusted_app_27` domain can read/write/exec **regular
files** in app_data_file but **cannot read, exec, or create SYMLINKS** there. Termux ships
`python`,`clang`,`libexpat.so.1`,`libexec/termux-api`, etc. as symlinks → every app-context
(RUN_COMMAND / notification-action / Termux:Widget) execution silently failed
("Permission denied" / "command not found" / dlopen "library not found").
- The **magisk/su context CAN use symlinks**, so `su`/`su u0_a762` tests PASS while the real
  app context FAILS — su-context testing is misleading. Test the real path via RUN_COMMAND.
- **Fix (as root, persists on disk):**
  - `$PREFIX/bin` + `$PREFIX/libexec`: replace symlinks with **hardlinks** to their real target
    (`fix_bin.sh`, `fix_libexec.sh` in `system/ondevice_toggle/`). Zero extra space; app can exec.
  - `$PREFIX/lib` .so symlinks: dereference-copy all into `~/applibs/` (real files), then run the
    catcher with `LD_LIBRARY_PATH=$HOME/applibs:$PREFIX/lib` (`build_applibs.sh`).
- `pkg upgrade` re-creates symlinks → re-breaks everything. DON'T upgrade; re-run the 3 fix scripts if needed.

### Same gotcha KILLED TERMUX SSHD — exact signature + one-shot fix (2026-09-18, Android 17)
Symptom from the desktop: `ssh pixel` → **`kex_exchange_identification: read: Connection reset`**, i.e. TCP connects (port 8022 open) then the server hangs up before the banner. It is NOT a config/host-key/authorized_keys problem and NOT the A17 exec restrictions (Termux `targetSdk=28` so it is exempt; binaries exec fine).
**Real cause:** every connection forks `$PREFIX/libexec/sshd-session`, which links against `libgssapi_krb5.so.2` — a SYMLINK. Logcat shows it exactly:
```
avc: denied { read } for name="libgssapi_krb5.so.2" ... tclass=lnk_file permissive=0
F linker: CANNOT LINK EXECUTABLE ".../libexec/sshd-session": library "libgssapi_krb5.so.2" not found
E sshd: error: server_accept_loop: startup pipe 0 (fd=9): read Connection reset by peer
```
**Diagnose it this way:** `adb forward tcp:18022 tcp:8022` then ssh to `127.0.0.1:18022` — that isolates sshd from the network path (it failed identically, proving it was sshd, not Tailscale). Then `logcat -d | grep -iE "sshd|linker"` gives the denied lib by name.
**Fix (root, ~1s, persists):** convert every `.so` symlink to a HARDLINK — `for l in $(find $PREFIX/lib -maxdepth 1 -type l); do t=$(readlink -f "$l"); [ -f "$t" ] && rm -f "$l" && ln "$t" "$l"; done`, same for `$PREFIX/bin` and `$PREFIX/libexec`. Script: `/data/local/tmp/fix_termux_symlinks.sh` on the phone. Converted 168 lib + 4 bin; ownership (`u0_a762`) and the `app_data_file` context are preserved automatically because a hardlink shares the inode. Skip `lib/terminfo -> ../share/terminfo` (a DIRECTORY symlink, harmless to the linker). Verified after: SSH works over BOTH adb-forward and Tailscale, and python/frida 17.9.11/curl/git all still run.
**This re-breaks on any `pkg install` that ships a new symlinked .so** — re-run the script, it is idempotent.
**Termux sshd is the BEST remote fallback when a major OS update kills wireless ADB** (`Host pixel` in `~/.ssh/config`, port 8022, user `u0_a762`) — see [[pixel-reroot-after-ota]]. But sshd runs only while the Termux process Termux:Boot started is alive; it is gone after any Termux restart (found down 2026-09-20). Check `ss -ltn | grep 8022` before relying on it; start it with `sshd` from Termux.

## Installing things that need network (DNS)
- `su`/`su u0_a762` context has **raw network but NO DNS** (getaddrinfo via netd not bound) — pip/apt fail to resolve.
- Run network installs in the **real Termux app context** via the RUN_COMMAND intent, which HAS DNS:
  set `allow-external-apps=true` in `~/.termux/termux.properties`, then
  `am startservice -n com.termux/com.termux.app.RunCommandService -a com.termux.RUN_COMMAND
   --es ...RUN_COMMAND_PATH <bash> --esa ...RUN_COMMAND_ARGUMENTS <script> --ez ...RUN_COMMAND_BACKGROUND true`.
  Fired as root, this runs the script as untrusted_app_27 WITH DNS. This is how frida was built on-device.
- frida is NOT in Termux main repo or TUR (verified) — build from the Frida **core devkit**
  (`frida-core-devkit-<ver>-android-arm64.tar.xz`) + `AbhiTheModder/frida-python` fork:
  `FRIDA_VERSION=.. FRIDA_CORE_DEVKIT=~/devkit python3.13 -m pip install --no-build-isolation .`
  (needs `pkg install clang make binutils libexpat`).

## The toggle
- UI = the Auto-Catcher APK (below) + the flag files `/data/local/tmp/pogo_{catch,spin,perfect,tap}.on`; no
  notification toggle. Brain = `~/pogo/catcher_ctl.sh`
  `start|stop|restart|status|toggle|rewards|{catch,spin,perfect,tap}-{on,off}`. stop = SIGTERM, then -9
  (see lifecycle rules below).
- `~/.termux/boot/` holds `20-pogo-catcher.sh` (`catcher_ctl.sh reconcile`) and `update-wallpaper` (live 2026-09-22);
  Magisk `service.d/termux_boot.sh` fires Termux:Boot after each boot (verified across a reboot 2026-09-22).
- `pkill/pgrep -f catch_phone.py` self-matches the control command's own cmdline — use the **gadget
  connection count** (distinct client ports to :27047) as ground truth, and `ps`/pgrep exclude their own pid internally.
- Source of all scripts: `pogo_extract/system/ondevice_toggle/`. Guide: `AUTO_CATCHER_PHONE.html`.

### The REAL toggle UI = an installed APK (don't forget this exists — I once told the user it didn't)
`com.benny.autocatcher/.MainActivity` — a native app, NOT a script/webview. Home-screen label **"Auto-Catcher"** (the
application label; its launcher activity has no label of its own); the control page it opens is titled "PoGo Auto"
(MainActivity.java:89).
Source + build: `pogo_extract/system/ondevice_toggle/apk/` (`src/com/benny/autocatcher/MainActivity.java`,
`build.ps1` = aapt2→javac→d8→zipalign→apksigner, `debug.keystore`, CN=AutoCatcher — same cert upgrades in place).
Build+install: run `build.ps1`, then `adb install -r apk/AutoCatcher.apk`.

### APP↔CATCHER IPC: the app domain CANNOT use a shell (hard-won, 4 failed attempts)
The app can run `su` and bare **/system/bin** binaries (`pgrep` works), but **anything toybox (`ls`,`tail`,`test`) or
with shell operators (`|`, `&&`, `[ ]`) returns EMPTY** from the app's SELinux domain — and it cannot read Termux's
home (`/data/data/com.termux/files/home` is 0700). Same restriction family as the Termux-install symlink gotcha above.
**Working design:** two files in `/data/local/tmp`, read/written with plain Java `File`/`FileReader` (no shell at all):
- `/data/local/tmp/pogo_spin.on` — presence = spin ON. App toggles it; catcher polls each loop (`USE_SPIN and os.path.exists(SPIN_FLAG)`) so toggling needs **no restart**.
- `/data/local/tmp/pogo_state.txt` — catcher publishes `caught= fled= spins= ready= cooling=` each 10s report; app parses it for the stat line.
**BOTH FILES MUST BE PRE-CREATED AS ROOT + `chmod 666`** — the Termux user cannot *create* files in /data/local/tmp
(owner=shell) and silently `PermissionError`s; it can only write to an already-existing world-writable file.
Debug trick: `android.util.Log.i("AutoCatcher",...)` inside the app's shell helper + `adb logcat -s AutoCatcher`
shows exactly what each command returned — that's what isolated the toybox failure.

## PokeStop AUTO-SPIN (2026-07-25) — built into catch_loop_fast.py, runs CONCURRENTLY with catching
**Headless spin path (found by probing a real manual spin):** `MapPlaceDirectoryService.get_ActivePokestops()`
→ filter `get_IsPlayerInRange`==1, `get_IsCoolingDown`!=1, `get_IsClosed`!=1 → `IMapPokestop.StartInteractiveMode()`
→ returns `MapPokestopInteractive`, whose **private `PoiItemSpinner` is at +0x90** → call spinner **`clfn()`**
(that's the method returning `IPromise<FortSearchOutProto>`, i.e. the real FortSearch RPC) → `CompleteInteractiveMode()`.
Seamless: no camera fly-in, no UI takeover; catcher keeps catching. Efficiency: per-fort `SPUN[fortId]` 5-min memory
+ live IsCoolingDown + 1 spin/5s ⇒ verified 8 consecutive spins = 8 distinct forts, zero repeats.
**ETHICS LINE HELD:** used the NORMAL spin path only. There is also `SoftSfidaRpcHandler::SoftSfidaSpinRpc` (the
Pokemon GO Plus / wearable path) — never used; mimicking the VGP would mean setting IsFromWearable/IsFromSoftSfida
to claim licensed-hardware identity to the server (declined; user offered, I passed). Probe confirmed our spins send
**wear=0 sfida=0**, identical to the user's own finger-tap.
**AWARD PROOF (immune to Pokemod's inventory auto-management — bag counts are useless as evidence):** hook
`FortSearchOutProto.MergeFrom` and read the server's own reply. Offsets: **Result@0x10** (1=SUCCESS, 2=OUT_OF_RANGE,
3=IN_COOLDOWN_PERIOD, 4=INVENTORY_FULL, 5=EXCEEDED_DAILY_LIMIT), **Items(RepeatedField<AwardItemProto>)@0x18**,
**GemsAwarded@0x20**, **XpAwarded@0x30**, **Loot(LootProto)@0x50**, **BonusLoot@0x58**, **FortId@0x70**.
`LootProto.LootItem`(RepeatedField)@0x10 → each `LootItemProto.Count`@0x10. RepeatedField layout: count@+0x18,
array@+0x10, elems at arr+0x20+i*8. **Items@0x18 and Loot@0x50 are the SAME payload two ways — never sum them.**
Measured: every spin res=1, **XP 100/spin**, **item count VARIES per spin (3/4/6/20 observed — NOT a fixed number)**.
### Two bugs that cost a cycle each (don't repeat)
1. `il2cpp_class_get_method_from_name(k,"MergeFrom",1)` grabs the WRONG overload — these protos have both
   `MergeFrom(SameProto)` and `MergeFrom(CodedInputStream)`, each argc=1, so the hook silently never fires.
   **Always loop all methods** (name=="MergeFrom" && paramCount==1) and attach to EVERY match, like the catch hook.
2. The whole Frida script is ONE single-line JS string in the .py — a `//` comment inside it comments out the
   REST OF THE LINE ⇒ `SyntaxError: expecting catch or finally`. **Use `/* */` block comments only.**

### DECOUPLED toggles (2026-07-25) — catch OFF must NOT kill spinning
Both features live in ONE python/Frida process, so the old `catcher_ctl.sh stop` (pkill catch_phone.py) killed the
spinner too — user hit this ("toggled off auto catcher, kept spinner on, it stopped spinning"). **Fix:** each feature
is now driven by its own flag FILE CONTENT, polled every loop, and the process is a shared host:
`/data/local/tmp/pogo_catch.on` + `/data/local/tmp/pogo_spin.on`, each containing `"1"`/`"0"`
(**content, not existence** — neither Termux nor the app can create/delete in /data/local/tmp, they can only WRITE
to a root-pre-created 666 file). Python: `run(_flag(CATCH_FLAG) and not balls_out)`, `set_spin(_flag(SPIN_FLAG))`.
`catcher_ctl.sh` gained `catch-on|catch-off|spin-on|spin-off|restart|status` and a `reconcile()` that starts the
process while EITHER flag is 1 and stops it only when both are 0; the app's two switches just fire those verbs.
Also: the ball-floor auto-stop now only exits when spin is OFF (otherwise it just disables catching).
**`pgrep -f catch_phone.py` LIES** (matches the `su -c pgrep …` cmdline itself → false "running"). Use
`ps -ef | grep -q "[c]atch_phone\.py"`; the app now reads the flag files instead of shelling out at all.

### TESTING GOTCHA: PoGo must be FOREGROUND or catching silently reads dead state
With the AutoCatcher app (or anything) in front, PoGo is backgrounded: Unity stops updating avatar/map transforms,
so `get_Location` fails ⇒ `distAt()` = -1 ⇒ the stale-spawn gate skips EVERY throw (`caught=0`, `stale=22`,
`dist=c-1/f-1m`) — looks exactly like a broken catcher but is correct behavior on dead data.
After any UI/screenshot test,
`am start -n com.nianticlabs.pokemongo/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity` and re-verify.

### BACKGROUND OPERATION IS NOT POSSIBLE in this build — don't retry these (all verified 2026-07-25)
When PoGo loses focus Unity **halts its entire player loop**: the `frame` counter froze at 2921 across a clean
120s test ⇒ tick() AND spinTick() both stop (earlier "+109 frames / a couple of catches" readings were just the
transition; and a stationary player with everything on cooldown looks identical — measure `frame`, not counters).
Process stays alive (`state=S`), it simply isn't scheduled to run game code. Three fixes tried, ALL unavailable:
1. `UnityEngine.Application::set_runInBackground` — **stripped by IL2CPP** (only `get_runInBackground`,
   `get_isFocused`, `InvokeFocusChanged` survive in UnityEngine.CoreModule.dll).
2. Native icall via `il2cpp_resolve_icall` — resolver EXISTS but the icall isn't registered (stripped with the method).
   NB: use `Process.findModuleByName(m).enumerateExports()`; **Frida 17 removed `Module.findExportByName`** (it throws,
   which silently faked a negative result the first time).
3. Hooking libunity's pause/focus — `libunity.so` exports are stripped (zero Pause/Focus symbols).
Remaining options are risky (off-main-thread pump, or hooking Java `UnityPlayer.pause`) — user declined; keep PoGo in front.
**⚠️ Repeated foreground/background cycling CRASHED PoGo** (native SIGSEGV in `libunity.so` under
`com.unity3d.player.C0.handleMessage`, i.e. the pause/surface path, with our LateUpdate hook attached).
Don't stress-cycle the app; relaunch + `catcher_ctl.sh restart` recovers it.

### Efficiency pass (2026-07-25)
- Reconnect **exponential backoff** from 3s, capped at 15s (reset to 3s on connect): a flat 3s retry had produced ~5,800
  "script has been destroyed" reconnect storms while PoGo was closed — pure battery burn.
- `spinScan()` (full ~560-fort walk × 3 bool calls ≈ 1700 il2cpp invokes) is now **cached 30s**; it only feeds the UI.
- Deleted the per-cycle `run_bg()` retry — with the method stripped it re-scanned **every class in every assembly** every 10s.
- Deleted `item_total()` (~37 invokes/cycle) — its value was no longer printed; bag totals are meaningless anyway
  because Pokemod auto-manages inventory. Per-spin awards come from the response hook instead.
- Successful spins no longer double-log (the AWARD line already carries xp+items); only failures log.
- Correction to the earlier claim that loot always equals award: seen `loot=8 award=7`. The counter uses
  `lt>0?lt:aw` (prefers the LootProto sum), so it stays correct either way.

## PoGo 0.421.0 UPDATE broke auto-spin (2026-07-26) — and the update-proof fix
App auto-updated 0.413.1 -> **0.421.0** (2026-07-26 00:12), which **re-obfuscates method names**: the spin RPC
`PoiItemSpinner::clfn` became `::ckua`, so spinning died silently (`spinFail -> noClfn`) while catching kept
working (catching only touches REAL, stable names). **NEVER hardcode an obfuscated name.** Now resolved at runtime:
- spinner field: by its REAL name **`ItemSpinner`** via `il2cpp_class_get_fields` (field names aren't obfuscated;
  offset still 0x90 in 0.421.0, but it's now looked up, not assumed).
- spin method: by **SIGNATURE** — the 0-arg method whose return type contains `FortSearchOutProto`. Cached per class.
Needs `mGRT`/`tGN`/`cGF`/`fGN`/`fGO` added to the H_ helper table. **Re-verified in 0.421.0: every proto offset is
UNCHANGED** (FortSearchOutProto Result@0x10/Items@0x18/XpAwarded@0x30/Loot@0x50/BonusLoot@0x58/FortId@0x70;
CatchPokemonOutProto Status@0x10/MissPercent@0x18/CaptureReason@0x30/ThrowsRemaining@0x38;
EncounterOutProto Status@0x1c; PokeballThrow BallType@0x10/ReticleSize@0x14/HitBullseye@0x18). Recon: `recon_v421.py`.

## Toggle plumbing bug: a lock that DROPPED commands (2026-07-26)
The dedupe lock I added exited 0 when it couldn't acquire, and `start_proc` held it ~4s — so a toggle tapped in
that window was silently swallowed: the app switch showed ON while the flag file stayed `0` (symptom: "autospin is
on and not working", `status` shows `spin=0` with NO spinFail lines — that's the discriminator vs a rename break).
Fixed: the lock now WAITS (~20s then proceeds), hold time cut to 2s, and the app VERIFIES each toggle (re-reads the
flag for ~6s, retries 3x, else redisplays truth). Stress-tested with 4 rapid toggles.

## Log-driven optimization pass (2026-07-26) — 49,853 caught / 2,252 fled = 95.7%
- **Backoff works**: the old flat-3s retry produced **71,951** `enumerateExports of null` retries; post-fix only 718
  drops. (Distinguish eras by the `reconnecting in Ns` suffix — old lines lack it.)
- **Spin counters were inflated ~9%**: we attach to every `MergeFrom` overload, so one response can surface twice and
  the second pass reads an empty object (`res=1 xp=0 items=0`). Now skipped — verified 0 since the fix.
- **Per-fort re-spin window 5.0 -> 5.5 min**: a dead-on 5-min retry kept landing `IN_COOLDOWN_PERIOD` (187 wasted).
- **Log rotation added** (>8MB keeps last 3000 lines, prior generation as `.log.1`): it had reached 19MB / 18s pulls.
- **SPEED IS NOT A LOSS DRIVER** (supersedes the earlier small-sample claim): volume-controlled loss rate is flat —
  still 6.3%, 1-10km/h 4.2%, 10-30 5.3%, 30+ 6.3%. Do NOT slow the route for catch rate.
- Range is also not a clear driver: 214 flees >70m vs 1778 <=70m, roughly tracking throw volume.

## FULL-OUTCOME LOGGING (2026-07-26) — log successes, not just failures
Only LOSS lines were logged for months, so nothing could be compared against. Now `_lp(1)` also fires on
status===1 and python emits `CATCH r=1 p= ball= pid= att= src= dist= spd= age= …` alongside LOSS, plus a
`DIAG` line (q/inflight/opened/fired/skipped/skipstatus/encstatus/seencls) of counters that were collected
but never printed. Analyser: `system/analysis/analyze_outcomes.py` (MUST start at the first CATCH line —
earlier LOSS-only history biases every rate; unfiltered it reported 49% vs the true 92.6%).
### What the first clean sample (81 throws, 92.6% caught) actually showed
- **DISTANCE IS A NON-FACTOR — user was right, my 80m cap was pure loss.** 20-40m 86.7% / 40-60m 93.6% /
  60-80m 92.9% / 80-100m 100%. `MAX_RANGE_M` is now 250 (effectively off); **`get_VisibleOnMap` (VISONLY) is
  the real gate — if it renders on the map it is catchable.**
- **Ball tiers: `CATCH_THRESHOLD` 0.50 -> 0.28.** At 0.50 nearly everything escalated to ULTRA (that is why
  Poke stockpiled while Ultra/Great drained). Post-change mix was 13 Poke : 1 Ultra. Per-ball success
  Poke 97.7% / Great 100% / **Ultra 82.1% — Ultra looks WORST only because it is reserved for hard mons
  (confounded); do not read it as Ultra being weak.**
- **Calibration holds:** observed vs `p_real = 1-(1-p)^3.4` came in at +8.8/+13.1/+6.6/-6.0 across bands, so
  the model is right (slightly conservative) and a 0.28 base threshold ≈ 67% real on the first ball.
- **`ThrowsRemaining` (thr) is ALWAYS 0 on wild/lure encounters** — it only means something for limited-ball
  encounters. The re-throw guard `it.a<MAXTHROW && thr>0` therefore never fires: `att=1` on all 81 throws,
  every break-out abandoned (including a Gimmighoul that broke out at 52m, `r=2`). `thr>0` stays (restored
  2026-08-19: live re-throws held a stale MapPokemon pointer, see ROOT CAUSE below), so break-out re-throws are
  effectively disabled; re-throws re-resolve by encounter id. **Break-outs are rare (~1 in 80), so this is the
  tail, not the bulk.**
- Spins in the same window: 204 res=1 / 5 res=2 / 3 res=3 = 96% success; the 5.5-min re-spin window holds.
- **Gimmighoul = dex 999** and arrives as `TroyDiskMapPlacePokemon` (Golden Lure). PRIORITY_DEX=[999,1000]
  queue-jumps it (`Q.unshift`) and forces the best ball; `PRIORITY CAUGHT/LOST` lines + `GIMMI=` counter.
  User will NOT place their own Golden Lure — relies on other trainers' active lures.
- **Berries: `USE_RAZZ=True`** — Pokemod feeds berries only on its paid tier; on the free tier nothing feeds.
  Regular Razz 701 only, `RAZZ_THRESH` 0.45, `RAZZ_FLOOR` 5.

## Phantom-skip improvement (2026-06-06) — catch_loop_fast.py
The wild catcher (`catch_loop_fast.py`, the loop `catch_phone.py` runs) now THROWS ONLY at confirmed-live encounters; it skips phantoms BEFORE wasting a ball. Hook `EncounterOutProto.MergeFrom`, read **Status @+0x1c** (int enum: 1=Success; 0/2/3/4/5/6/7=dead, e.g. 6=`EncounterAlreadyHappened`; on the same proto Pokemon@0x10→EncounterId@+0x10, CaptureProbability@0x20). Record `ENCSTATUS[encId]=status`; at throw time fire ONLY if `ENCSTATUS[encId]===1`, else SKIP (mark ATTEMPTED, count `skipPhantom`).
- **KEY FINDING (instrumented, not assumed):** catcher flees are NOT dead-status opens — opens come back ~100% `OK`. Flees split into **NONE** (open fired, NO server response → phantom thrown blind → flee; now SKIPPED, the real win) and **OK** (open succeeds but throw still flees → genuine flee or stale-OK phantom; NOT distinguishable by open status → left alone; chasing it needs a freshness check that risks skipping real catches).
- The existing EncounterId dedup (`ATTEMPTED`, persisted via `attempted_master`) ALREADY prevents re-throwing CAUGHT mons — that was never the bug; the phantom NONE-flee was.
- **CRASH CAUTION:** do NOT dereference `it.t` (a THROWN-queue MapPokemon) inside `onCatchResult` — by result time it can be stale → reading it crashes/restarts PoGo. (A flee-diagnostic that did this was removed.)
- **Deploy:** as of 2026-09-20 the phone and desktop (`system/scripts/game_write/`) `catch_loop_fast.py` have diverged BOTH ways: the phone has RATE 90, the refill backoff (`REFILL_IDLE_MS`), settle 20 + the `pogo_settle` override and a 1-iteration stardust gate (`_gate >= 0`; desktop `>= 5`); the desktop has the PERFECT_PROTO fix, the set-once `PT.err` "not ready" fix and Silver Pinap = 708 in `BERRY_NAME` and its comments (the phone copy still says 707). Merge them into one file before any deploy, by diffing the two files, not from this list — pushing the desktop copy drops the phone-only changes, and the phone copy lacks the desktop fixes. `pogo_il2cpp.py` differs too. Then `adb push` to /data/local/tmp → `su -c 'cat tmp > dest'` (in-place overwrite PRESERVES owner u0_a762 + `app_data_file` SELinux context, safer than `cp`) → `rm __pycache__/catch_loop_fast*.pyc` → restart `catcher_ctl.sh start`. Verify `sha256sum` phone==desktop; backup kept `.bak`.
- **Single-client gadget:** do NOT attach desktop Frida (recon) while the on-phone catcher runs — it evicts the catcher (`script has been destroyed` / `unable to connect`). PoGo also self-restarts (pid drift, ~every few min under the spoof stack); the catcher's self-reconnect handles it (waits, reconnects).

## Multi-source unification (2026-06-06) — catches ALL map-spawn types, not just wild
INSIGHT: every `*MapPokemon` (Wild/Incense/Route/DailyEncounter/DailyBonusSpawn/Station/Photobombing/Extra/Incident) implements `IMapPokemon` and INHERITS `TryCapture`+`get_Location`+`SendEncounterRequest` from base `MapPokemon`, so the existing open→throw pipeline works on ALL of them via `il2cpp_class_get_method_from_name` (walks base classes). They ALL live in the ONE `MapPlaceDirectoryService.get_AllPokemon` (no per-type accessor) — verified live: `IncenseMapPokemon` appears in get_AllPokemon AND was caught. The ONLY blocker was the require-OK rule hooking ONLY the wild `EncounterOutProto`. Non-wild opens return their OWN OutProto, ALL uniform: **Result@0x10, Pokemon@0x18, CaptureProbability@0x20** (vs wild Status@0x1c, Pokemon@0x10). FIX (catch_loop_fast.py): hook all 7 OutProtos — Encounter(wild) + Incense + Disk(lure) + Daily + AttractedPokemon(lure-bonus) + DailyBonusSpawn + StationPokemon(Bread/Power-Spot); each FIFO-tags the inflight open; throw rule = "a response of ANY type arrived → throw; none → skip (NONE phantom)"; wild keeps its precise encId-status (skip dead 2/3/4/6). Verify via `SRCCATCH` (catches by class) + `SEENCLS` (enumerated by class) → log `bySrc=`/`seen=`. **Lure mons are class `TroyDiskMapPlacePokemon`** (Troy = Niantic lure codename; note it's `...MapPlacePokemon`, NOT `...MapPokemon`, so a `listClasses("MapPokemon")` scan MISSES it — the live per-source `bySrc` revealed it). It IS in `get_AllPokemon`, inherits the catch interface, opens via `DiskEncounterProto` — and was VERIFIED caught live by the multi-source fix. (Also added: a reconnect READINESS GATE — `finder.init().gameImage` must be non-null before `install()`, mirroring `restart_pogo_and_wait` in pogo_il2cpp.py — fixes the 8h enumerateExports-of-null stall; verified reconnects clean.)

## 12h data-collection run (2026-06-07/08, completed — `system/analysis/catch_12h_report_2026-06-08.html`)
Goal: find why pokemon flee/escape → maximize catch ("100% as much as possible"). `catch_loop_fast.py` now logs per-loss lines (drained every loop, persist across reconnects): `LOSS r=<2 escape / 3 flee / 4 miss> p=<catch-prob> ball=<1/2/3> pid=<species> att=<throw#>`, on top of the per-10s summary (caught/esc/flee/miss, bySrc, Razz(701)/GRazz(706) stock, P/G/U balls, dust). **Findings:** throw is ALREADY maxed (Excellent reticle 0.02-0.12 + curveball in `fireCatch`). Flees are INTERMITTENT (0% in calm windows, ~8% in bursts) and are break-out→flee (status 3) on sub-100% throws (`flee>>esc`). **KEY CORRECTION (verified catch/flee research — see `pogo_extract/system/analysis/catch_flee_reference.md`):** catch & flee are TWO SEPARATE rolls — catch (ball/berry/throw/curve boost it), then ON break-out an INDEPENDENT flee roll vs species `base_flee_rate` that NOTHING boosts/lowers. Genuine break-outs split escape(stay)/flee(run) per the species flee_rate. OUR DATA: esc=3 vs flee=37 = 92% flee-per-break-out = impossible for the species seen (Combee/Drowzee/Bulbasaur ~0.1-0.2) ⇒ the BULK of "flees" are SERVER-REJECTS, not real flees (att=1, no escape, prob-indifferent incl p=1.0 flees). Server-reject = stale/desynced encounter OR per-account soft-ban; the soft-ban co-occurs with "Try Again Later"/no-loot at stops == this account's OUT_OF_RANGE spin block ⇒ the catch-flees are very likely the SAME spoofing position-trust/soft-ban as the spin block. ⇒ **Razz will NOT fix the bulk** (it only raises the catch roll; these aren't failing it, they're rejected). Catch mechanics already maxed (Excellent+curve ≈3.4x bare Poke; p_real=1-(1-X)^3.4). Razz = niche win only, front-loaded on GENUINE high-flee rares (Abra 0.99/Galarian birds 0.90). Clearing the server-rejects = the spoofing soft-ban (declined evasion). **HARD USER CONSTRAINT: never use Golden Razz (706) or Silver Pinap (708, internal GoldenPinapBerry; 707 = GoldenNanabBerry, Silver Nanab).** Diagnostic now logs avatar `spd=<km/h>` per LOSS + per summary. Daily Adventure Incense (Beluga) covered by hooking BOTH `IncenseEncounterProto` + `DailyEncounterProto` (deep-research flagged a proto-mapping conflict → hook both). NOT covered: Kecleon/**Tappables** (`TappableEncounterProto` needs a tap-reveal first); Quest/research rewards (= `reward_catcher.py`); raids/Rocket/Max = battle-then-catch (excluded by design). Recon tools: `recon_encounter_types.py`, `recon_incense.py`. Per-source `*EncounterOutProto` taxonomy lives in `_metadata_strings.txt` / `proto_layout.json`.

## Razz-on-hard-throws BUILT + server-reject RE-CONFIRMED live (2026-06-08)
Implemented the Razz lever the research recommended, and the live data re-proved it's a MINOR lever (don't re-litigate this).
- **Feature (catch_loop_fast.py):** regular Razz (701) auto-fed via the existing `useBerry`/`UseItemForEncounter` path. Globals `RAZZ_ID=701,RAZZON,RAZZ_THRESH,NRAZZ`; export `setRazz(on,thr)`; py constants `USE_RAZZ/RAZZ_FLOOR/RAZZ_THRESH` (set each loop, gated on `count(701)>floor`). Two feed points, BOTH main-thread (tick), NEVER in `onCatchResult` (wrong thread → crash, see FLEEDIAG lesson): (1) first-throw — at `BERRY_LAG` for an INFLIGHT mon whose prob is KNOWN & best-ball `< RAZZ_THRESH` (skips `p=-1` lure/fort mons — Razz can't rescue a rejected open); (2) break-out re-throw — `it.bo=1` flag set on status==2 (plain prop, safe on any thread), fed before `fireCatch` in the RETHROW loop. Summary shows `Razz=<stock>(fed <N>)`. **SAFETY: `useBerry` is only ever called with 701 or 705 (Pinap); 706/708 NEVER passed — grep-verified + `GRazz=277` flat live. Golden Razz/Silver Pinap untouched, as constrained.**
- **Live re-confirmation (this session):** caught=28 esc=0 flee=5; flees spanned p=0.145…**0.879** (prob-INDIFFERENT) with ~0 break-out escapes across ~12 flees ⇒ SERVER-REJECT dominated (a p=0.88 mon catches ~98% w/ Excellent+curve; fleeing on att=1 = server reject, not catch-fail). Razz feeding worked mechanically (fed 17-19, stock drew down) but did NOT move the rate (85-96%, all within noise) — exactly as the research predicted. ⇒ Razz best at LOW threshold (~0.45, the genuine-breakout minority); raising to 0.60 just burns berries on rejects. Catch ceiling = the account's position-trust soft-ban; declined to evade (same line as spins).
- **Lure flees = FORT position-trust:** `TroyDiskMapPlacePokemon` lures sit on PokéStops/Gyms (forts); catching them runs the SAME position-vs-fort check returning OUT_OF_RANGE on spins ⇒ bursty lure flees track the spin block. Wild/incense (non-fort) unaffected. This IS the user's "spawn disappears→reappears→auto-flee."
- **`req=None` DEAD-END (don't chase):** the request hook (`CatchPokemonProto.WriteTo` AND `_InternalSerialize`) never fires — `reqn=0` even on SUCCESSFUL catches. The catch request doesn't serialize via those methods; `req=None` is an instrumentation gap, NOT a flee clue. Set offsets/CaptureReason@0x30/Status@0x10/MissPercent@0x18 are read fine off `CatchPokemonOutProto.MergeFrom` (reason=0 generic, miss=0 lands) — that's the useful hook, not the request.

## ROOT CAUSE of the PoGo crashes: cross-thread il2cpp (2026-08-19)
Tombstone signature to recognise instantly: `SIGSEGV` in `art::StackVisitor::WalkStack` ->
`art::Thread::VisitRoots` -> `art::gc::collector::MarkCompact::CheckpointMarkThreadRoots::Run`, on
`UnityMain` or `HeapTaskDaemon`, sometimes with abort "Transitioning to Runnable with checkpoint flag".
**Cause: calling il2cpp from FRIDA's RPC thread.** `H_()` runs `il2cpp_thread_attach`, registering a
Frida-owned stack with the runtime; ART's GC then faults walking it. **RULE: rpc.exports must NEVER
touch il2cpp** — they may only set flags or read caches; ALL game calls happen inside the LateUpdate
pump. Converted: `refillService`/`spinScan` -> set WANT_* flags (pump executes), `count`/`call0i` ->
read a cache the pump polls, per-catch transfer -> queued and run in the pump. I RE-INTRODUCED this bug
once via a transfer `xferScan` rpc export and it crashed the game again — audit every new export.
Also fatal: **holding a MapPokemon pointer across time**. MAXTHROW_PRIO=60 + PRIO_LAG=7000 made re-throws
reuse an object pointer for up to 72s; after the game frees it that is a use-after-free. Re-throws were
NEVER active for months anyway (the `thr>0` guard never passes because ThrowsRemaining is always 0 on
wild/lure), so restoring `thr>0` returns to the long-stable behaviour.

## Toggle/lifecycle rules learned the hard way
- **`kill -9` on an attached catcher leaves a dead ESTABLISHED socket on the single-client gadget**;
  every later attach then fails with "timeout was reached" and the toggle reads ON while nothing happens.
  `stop_proc` must SIGTERM first (python traps it and detaches) and only -9 as a last resort.
- **Toggle ON must GUARANTEE a live attach**, not just write a flag: `ensure_live()` health-checks
  (process alive AND log written in last 60s) and re-attaches if wedged.
- **The catcher must NEVER start/foreground/force-restart PoGo.** I had it doing that; it relaunched the
  user's game after they deliberately quit. Removed.
- **Quit = exit.** The quit check must live in the `if not sess:` (get_session failed) path — putting it
  in the outer `except` meant it never ran and the loop span forever draining battery.
- **Writing shell scripts from Windows Python inserts CRLF** -> `$'\r': command not found` and the whole
  control script fails to parse. Always write shell files with `newline="\n"` / strip `\r`.
- PoGo heat is the GAME, not us: measured PoGo 213% CPU vs catcher overhead within measurement noise.

## Cull / transfer tagging (2026-08-19)
Engine = `keep_policy.py` (caps in `keep_config.json`). The only Transfer route is `preflight_transfer` ->
`prune_tags --atomic` (see [[pogo-pile-gate-2026-09]]). `cull_v9` is advisory only -- nothing tags or releases from it.
**`TaggingRpcService` is lazily instantiated — the user must open the in-game tag UI first**, else
`ensure_ready` raises "did not respond within 60s" (same pattern as QuestStateManager).
**PRE-FLIGHT CAUGHT A REAL ONE:** 14 rows carried a STALE `Transfer` tag that the engine now KEEPS —
including a **legendary Groudon 82.2%** and 13 PvP-ranked mons. Always reconcile tag vs current plan.
Verified research: **the game's shiny/Lucky/legendary transfer warnings are CLIENT-SIDE UI only and a
scripted `ReleasePokemon` bypasses them silently**; transfers are irreversible with no support restore.
**A low IV total can be PvP rank-1** (Sinistcha 0/2/7 = 20% is GL rank-1; 401/962 species have rank-1
totals under 30) — never gate transfers on IV magnitude alone.

## `pidof` IS UNUSABLE from the Termux app context -- use a SOCKET PROBE (2026-08-20)
The catcher's "did the user quit PoGo" check shelled out to `pidof com.nianticlabs.pokemongo`.
From untrusted_app it prints NOTHING yet still **exits 0**, so the caller cannot distinguish
"not running" from "cannot see it" -- and any transient attach failure (classically: a desktop
script briefly holding the SINGLE-CLIENT gadget) looked identical to a quit and the catcher
KILLED ITSELF mid-session. I mistook three such exits for proof the idle-drain fix worked.
Testing with `su`/`su u0_a762` is misleading -- the su domain sees processes the app domain cannot.
**FIX (deployed): `_pogo_alive()` opens a TCP socket to 127.0.0.1:27047.** No binary, no shell, no
elevated visibility, and it tests what we actually depend on -- a reachable gadget. 3 tries, 2s
apart, so one unlucky probe never causes an exit. Verified ALIVE from the real app context.

## Tombstone COUNT saturates -- never use it as a crash metric
/data/tombstones holds 32 slots (tombstone_00..31), each with a `.pb` twin, so `ls | wc -l` saturates at **64** and stops
increasing no matter how many crashes occur. My monitor was diffing that count. **Correct method:
list each tombstone's `Timestamp` + the `>>> process <<<` from its `pid:` line and sort.**
Truth as of 2026-08-20 22:30: last PoGo crash **2026-08-19 22:29:25** -> 24h+ crash-free after the
cross-thread-il2cpp fixes (transfer module disarmed, no rpc export touching il2cpp).

## Temperature: read the BATTERY, not the core sensors
`thermal_zone*` max was 65-70C and looked alarming; those are **BIG/MID/LITTLE CPU cluster**
sensors and 63-70C is normal SoC load. The number that reflects "is the phone hot" is
`dumpsys battery | grep temperature` -> tenths of a degree (355 = **35.5C**, fine).
Also: `logcat -b events | grep am_kill` distinguishes causes -- `remove task` = the USER swiped the
app away (not a crash, no tombstone); `am_proc_died` follows it.

## Item bag: full at 3650, and there is NO clean recycle RPC (2026-08-20)
Bag hit **3684 vs a 3650 cap**, so ~38% of spins returned FortSearchOutProto Result=**4**
(INVENTORY_FULL) and awarded nothing -- the spinner looked broken but was fine. Read the bag with
`system/scripts/game_read/read_item_bag.py` (GetItemCount per id + the live ItemId enum).
**Exclude EventPassPoint*/Resource*/FusionResource*/Mp/*Currency*/OtherEvolutionStone* from any
total** -- they are counters, not bag items (one reads 392,425 and blows up the sum).
Real top consumers: PokeBall 1491, UltraBall 346, GreatBall 268, GoldenRazz 266, MaxRevive 250,
MaxPotion 215, PinapBerry 156, GoldenPinap(=Silver Pinap) 111.
**`ItemBagImpl.RecycleItem` takes `Niantic.Holoholo.Inventory.ItemInventoryItemWidget.ItemData`,
System.Int32, ISet<Item>` -- the first arg is a UI DATA OBJECT, not an item id.** A scan of every
class for methods returning `RecycleItemOutProto` found only IItemBag/ItemBagImpl overloads plus a
lambda -- so there is no plain (id, count) entry point. `system/scripts/game_write/item_cleanup.py` is
dry-run BY DEFAULT; `--commit` performs a REAL, irreversible discard through a constructed ItemData and
`RecycleItem/3`. **Never pass `--commit` without the user's explicit go.** Even the dry run calls
`find_recycle_rpc()`, a full class walk from Frida's RPC thread -- the crash vector in the next section.
PROTECTED (re-checked at call time) holds **706** Golden Razz, **707** GoldenNanabBerry (Silver Nanab) and
**708** GoldenPinapBerry = Silver Pinap (do not confuse with PinapBerry 705).
(Catching/cleanup only. Since 2026-09-25 the GYM runner may spend 706 on his own defenders at <=1/3 motivation; see reference-pogo-native-gym-flow.)

## THE RULE APPLIES TO DESKTOP RECON SCRIPTS TOO -- full-assembly class walks CRASH the game
2026-08-20 22:37 and 22:40: two fresh PoGo crashes, identical signature
(`StackVisitor::WalkStack` -> `Thread::VisitRoots` -> `MarkCompact::CheckpointMarkThreadRoots`),
on the exact pid my desktop probe was attached to. **I caused them.** The catcher was clean -- an
audit showed its steady-state loop makes ZERO il2cpp calls from Frida's thread -- but my own recon
scripts (`item_cleanup.findRecycleRpc`, `read_item_bag.itemEnum`) do `eachClass(...)` over every
class in every assembly and invoke il2cpp from the RPC thread. Same vector, different file.
This retroactively explains crashes I blamed on the catcher: they cluster around my probe runs.
**RULES for any desktop script that attaches to a live PoGo:**
  1. NEVER walk all assemblies/classes while the user is playing. Resolve targets with
     `il2cpp_class_from_name(image, namespace, name)` when the names are known.
  2. If a full enumeration is genuinely needed (dumping the Form/Item/Tag enums), do it ONCE with
     the game idle and CACHE the result to disk -- never re-derive it per run.
  3. Budget every attach: each stop/start of the catcher also costs ~90s before it produces work.
  4. Crashes are attributable -- match the tombstone `pid:` against the pid your script printed on
     attach before blaming the catcher.

## The app is now a SETTINGS PAGE, not two hardcoded switches (2026-08-20)
`MainActivity.java` rebuilt as a ScrollView with sections (CATCHING / POKESTOPS / ONE-OFF ACTIONS /
LIVE STATUS) and a generic **`FeatureRow`**: title, plain-English description, switch, live status.
**Adding a future emulated feature is ONE `addFeature(root, name, description, FLAG, "x-on",
"x-off", onText)` call** -- do not hand-build another block. All rows are registered in `rows` and
refreshed together every 4s from their flag files.
Build+install: `apk/build.ps1` then `adb install -r apk/AutoCatcher.apk` (same CN=AutoCatcher cert
upgrades in place and keeps LSPosed scope). Verify the build actually took by EXTRACTING the apk and
grepping `classes.dex` -- grepping the .apk itself always says MISSING because it is a compressed
ZIP, and the output size can coincidentally match the previous build.
Remember: `adb pull /sdcard/...` MUST run from PowerShell -- Git Bash rewrites it to
`C:/Program Files/Git/sdcard/...`.

## MY OWN WATCHDOG ATE THE CATCHER -- 90 restarts in 9 minutes (2026-08-21)
The supervisor I added to make the catcher self-healing became the outage. It judges liveness by
`catch_loop.log` mtime with STALE=100s, but a fresh attach is SILENT for ~90-120s (install +
`find_iap`/stardust gate, which alone loops 40x2s). So it killed a perfectly healthy, still-
initialising catcher, and each restart re-entered the same slow init -> permanent loop. Symptom the
user saw: "I toggled Perfect Throw and it's not working" -- because the process never lived long
enough to bind its hooks (`perfectOn=0` on every throw).
**Fixes:** (1) the catcher HEARTBEATS through the gate (`init: waiting for inventory/stardust sync
(Ns, dust=..)`) so silence unambiguously means wedged; (2) STALE 100 -> 240.
Verified: 0 restarts in 90s afterwards, `applied=1`, catching + spinning.
**Second self-inflicted bug in the same file:** the watchdog guarded on
`pidof com.nianticlabs.pokemongo`, which does not work from Termux's app sandbox -- the EXACT bug I
had just fixed in the catcher. It silently skipped every cycle, so a dead catcher sat there 14
minutes. Now uses a pure-bash probe: `(exec 3<>/dev/tcp/127.0.0.1/27047)`.
**Lesson: a supervisor must be judged by whether the thing it supervises stays UP, not by whether
the supervisor runs.** Count restart banners before/after as the acceptance test.

## Measuring a feature beats asserting it -- THROW instrumentation
"Perfect Throw isn't working" was unanswerable until every outgoing CatchPokemonProto got logged:
`THROW <MANUAL|catcher> ball= ret= [tier] spin= hit= hpos= perfectOn= aimlocks=`
(`mine` = whether the catcher itself opened that encounter, so a hand-thrown ball is unambiguous).
That single line settled three separate questions in minutes: throws landing in the ~60s post-restart
window before hooks bind (`perfectOn=0`), a genuine success (`ret=1.993 [EXCELLENT] hit=1 hpos=1
perfectOn=1 aimlocks=1`), and the real remaining gap (`spin=0` = NO CURVEBALL, because I had not
implemented Pokemod's `CalculateSize -> SpinModifier=1`; now written as a double 1.0 at proto +0x38).

## NEVER attach-retry-loop a cold PoGo (2026-08-31)
`catch_loop_fast.py` fired up to SIX `pg.get_session()` probes at 5s intervals whenever PoGo was not
attachable. **Every Frida attach against a cold-starting PoGo is itself a crash roll**, so a game
restart routinely ended in "link drop: timeout was reached" or a dead catcher.
**On-device gate:** the catcher cannot use `wait_ready_to_attach` (it needs ADB; desktop scripts only). It
polls the gadget socket 127.0.0.1:27047 every 5s for up to 180s, then sleeps a blind settle -- 20s in the
phone copy (consume-once override in `/data/local/tmp/pogo_settle`, reset to -1 after use), 45s in the
desktop copy -- then calls `get_session()` up to 3 times, 5s apart. On the phone that is
`catch_phone.phone_get_session`, which itself retries `dev.attach("Gadget")` up to 3 times, so the worst
case is 9 attaches. The `allow_cold` refusal in `pogo_il2cpp.get_session` does not apply on-device.

## The watchdog's CIRCULAR DEPENDENCY -- why it never recovered (2026-08-31)
The watchdog was only ever started by `run_catch.sh`, i.e. BY THE CATCHER. Once both died there was
nothing left to resurrect either -- which is why the process table was completely EMPTY (no catcher,
no watchdog) rather than showing something wedged. Real cost: the catcher died 2026-08-30 20:52:37 on
a link drop and stayed dead **~17.5h**.
**Termux:Boot hook `~/.termux/boot/20-pogo-watchdog.sh`** (com.termux.boot IS installed) is meant to start
the watchdog independently of the catcher (the watchdog then starts the catcher whenever the flag files say
a feature is on). **Observed NOT working:** across the 12 Termux:Boot runs from 2026-09-16 16:51 to 2026-09-20 05:33 (termux-boot.log) it never
started the watchdog -- its `[w]atchdog.sh` guard self-matches the hook's own filename
(`20-pogo-watchdog.sh`). Until that is fixed, nothing revives the catcher after a reboot.
Gotcha hit while writing it: `io.open(p,"w").write(io.open(p).read())` TRUNCATES before reading and
silently produced a 0-byte script that deployed "successfully". Always verify size after deploy.
