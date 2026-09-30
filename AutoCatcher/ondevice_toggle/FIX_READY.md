# FIX READY — on-device auto-catcher native-fault fix

Date: 2026-06-03. Pure analysis + code; the phone was not touched. The human runs the one
on-device test, with **PoGo foregrounded on the live map**.

---

## 1. ROOT CAUSE (stated plainly)

**The original `catch.js` stops the Unity GC world from PoGo's render thread, every ~1 second, forever — and the proven desktop catcher never does this.**

The fault signature — `pc == fault-addr`, ~15 threads at once, addresses in the
`0x72xxxxxxx` libil2cpp range, looping for ~40 s — is the textbook fingerprint of
**process-global GC / method-metadata corruption**: a clobbered vtable slot makes the
very next `il2cpp_runtime_invoke` on *every* managed thread jump to a data/garbage
address. That is why the crash fans out across all game threads simultaneously and why
the program counter equals the faulting address.

There is exactly one structural difference between the crashing path and the flawless
desktop path:

- **Desktop (proven, never crashes):** the stop-the-world liveness walk
  (`il2cpp_stop_gc_world → livenessAlloc → livenessFromStatics → livenessFinalize →
  start_gc_world`) runs **once, at connect time, on a Frida-managed host thread, in a
  transient script, decoupled from the frame pump.** The desktop's per-frame `tick()` does
  pure queue work — it never stops the GC world. (`catch_loop_fast.py` `tick()` +
  off-thread `pogo_il2cpp.liveness_find_instances`.)
- **Original `catch.js` (crashes):** `manage() → ensureSetup() → livenessFind() →
  stopWorld` runs **re-entrantly from inside the `CameraFollowingGround.LateUpdate`
  interceptor (the render thread), gated only by a 1-second wall clock, indefinitely** —
  and it kept re-walking even after setup, whenever the ItemBag/IapService pointer
  re-resolved. The lone `manageBusy` guard only blocked JS re-entry; it did nothing about
  the structural defect of suspending the GC world from a thread that is itself a mutator
  mid-managed-frame, on a cadence.

Three compounding contributors made it worse, all also present only in the port:
1. **Pre-`il2cpp_init` poke.** `H_()` ended with `H.tA(H.dG())` at table-build time, and the
   `clock_gettime` bootstrap fired that from arbitrary early threads **before
   `il2cpp_init`**, dereferencing a garbage domain.
2. **No kill-switch.** The exception handler logged and `return false`, but set no flag —
   so LateUpdate kept firing the broken path every frame, turning one fault into the 40 s
   storm.
3. **Backgrounded engine (the smoke-test condition).** "The game wasn't in the
   foreground": a backgrounded Unity game pumps LateUpdate abnormally / not at all, so the
   1 s gate fired the GC stop against a half-paused engine — the worst possible moment to
   suspend the world. This *amplified* the defect; it was not the defect itself (stopping
   the world from the render thread on a cadence is wrong even foregrounded).

**The single load-bearing fact: the proven catcher never stops the GC world from the
render thread or before `il2cpp_init`. The port did both, repeatedly. Eliminate that and
the storm goes away.**

---

## 2. PRIMARY FIX and why it resolves it

Two deliverables, in priority order.

### PRIMARY — `termux_catch.py` (Termux-attach; recommended end state)
**File:** `system/ondevice_toggle/termux_catch.py`

Run the **proven desktop catcher** (`catch_loop_fast.py` + `pogo_il2cpp.py`, byte-for-byte
unchanged) **on the phone**, in Termux, attaching to the gadget's own loopback **listen**
socket `127.0.0.1:27047`. This **sidesteps QuickJS script mode entirely** and preserves the
exact off-thread architecture that has never crashed PoGo: the GC liveness walk runs on a
proper Frida host thread in a transient script, decoupled from the render frame. It removes
*every* variable the in-process port introduced (QuickJS, early-load, render-thread
re-entrancy, the fork's unverified liveness exports) in one move. It only attaches — it
changes no gadget config and writes no marker. **Lowest risk; this is the one to run
first.** It also doubles as the control proving the catch *logic* is fine on this device.

### FALLBACK — `catch.fixed.js` (zero-Termux, hardened script mode)
**File:** `system/ondevice_toggle/catch.fixed.js` (rename to `catch.js` on deploy)

A single-threaded, render-thread-driven port that reproduces the desktop's *semantics*
(discover once after a foreground warmup, then only read cached pointers) without any
cross-thread GumJS hazard. Why each change kills its fault:

| Fix | Fault it eliminates |
|---|---|
| Liveness moved into a **one-shot `runDiscovery()`** gated behind `READY_FRAMES=90` real LateUpdate frames; `livenessFind()` is hard-blocked once discovery latches. Steady-state `tick()`/`manage()` are pure cached reads. | The primary crash: the render-thread GC stop **every second forever**. The world is stopped at most a bounded handful of times during one foreground warmup, never on a cadence. |
| `H_()` is now **pure export resolution** (`H.tA(H.dG())` removed); attach happens only via `attachSelf()`/`engineReady()`, **only behind a non-null `il2cpp_domain_get()`**. | The pre-`il2cpp_init` garbage-domain dereference. |
| **`CRASHED` kill-switch** on the first native fault makes `tick()`/`manage()`/`livenessFind()` no-op forever (handler still `return false`). | The 40 s storm — one fault can never become per-frame. |
| **`FRAME_SEEN` foreground gate** — a backgrounded game doesn't pump LateUpdate, so discovery **waits inertly instead of crashing**. | The "game wasn't foregrounded" condition. |
| **`livenessExportsMissing()`** hard-verifies all 8 GC/liveness exports **before** any stop-world; if the fork lacks them it logs `FATAL ... use the Termux-attach fallback` and never stops the world. | A null `il2cpp_alloc` reaching the realloc callback — and it's the clean route-to-PRIMARY signal. |
| `start_gc_world()` moved into a **`finally`** block. | A wedged/frozen engine from a half-finished GC region. |
| ItemBag probed on a **local**, class-name-checked, committed to global `IB` only on a working `GetItemCount`. | `runtime_invoke` on a wrong/stale/look-alike bag. |

**Catch quality in `catch.fixed.js` is byte-identical to the proven desktop catcher**
(reticle `0.02 + rand*0.10`, ball floors, threshold 0.5, rate, MAXR 80 m, legendary
skip-list, struct offsets +0x10/+0x14/+0x18/+0x19/+0x1a, result +0x10 / throws +0x38).
`node --check` passes.

---

## 3. EXACT SINGLE-SHOT ON-DEVICE TEST PROTOCOL (PoGo FOREGROUNDED on the live map)

All commands in **Termux on the phone, root present**. Keep PoGo **foregrounded on the live
map (avatar + spawns visible), screen on**, the whole time. **Do not run while the desktop
catcher — or a second copy of this — is attached** (one attach at a time on 27047).

### Phase 0 — backup + sanity (once)
```sh
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'
# confirm the listen-restore source exists (the panic button depends on it):
su -c 'grep -q listen /data/local/tmp/re.zyg.fri/config.listen.so && echo "restore-source OK" || echo "MISSING config.listen.so"'
```

### Phase 1 — PRIMARY: Termux-attach (DO THIS FIRST)
One-time setup (see `TERMUX_SETUP.md` for the frida-wheel details — the one tricky step):
```sh
pkg install python
pip install frida          # MUST be 17.x to match the gadget fork; verify next line
python -c "import frida; print(frida.__version__)"   # expect 17.x
# Seed the pogo_extract tree onto the phone preserving layout (pogo_il2cpp.py at ROOT,
# catch_loop_fast.py at ROOT/system/scripts/game_write/, termux_catch.py at
# ROOT/system/ondevice_toggle/). POGO_ROOT overrides ROOT if you placed it elsewhere.
```
Ensure LISTEN mode, relaunch, foreground, then the single shot:
```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'sleep 2'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'

# >>> Foreground PoGo on the live map. Keep it foregrounded. <<<

# one-second reachability probe (turns a confusing attach timeout into an instant diagnosis):
python -c "import socket;s=socket.create_connection(('127.0.0.1',27047),3);print('socket OK');s.close()"

# THE SHOT:
termux-wake-lock
python /sdcard/pogo_extract/system/ondevice_toggle/termux_catch.py   # adjust path / set POGO_ROOT
```
**SUCCESS (stdout):**
```
connected pid=<PID> | Poke=.. Great=.. Ultra=.. | Stardust=.. | msvc=ok avatar=ok iap=ok
run <s> | now <dust> dust ... | fired=.. | caught=.. esc=.. flee=.. miss=.. | q=..
```
Stand near a spawn → an `open` then an Excellent throw; escapes re-throw (≤4); legendaries
skipped; box stays empty (auto-transfer); dust ticks up. **No `frida-catch` native faults**
(no `catch.js` is loaded on this path). **Stop:** Ctrl-C (releases the wake-lock; nothing to
restore — no config changed). **If this works, you are done — this is the reliable autonomy.**

- `socket OK` but attach `down/unreachable` ⇒ gadget is in script mode → re-run the
  listen-restore `cp` + relaunch. `enumerate_processes empty` ⇒ relaunch PoGo first.
- socket probe **hangs/refuses** while PoGo is up in listen mode ⇒ Termux UID can't reach
  PoGo's loopback (SELinux): retry as root `su -c 'python .../termux_catch.py'`.

### Phase 2 — FALLBACK: hardened script mode (only if Termux frida is intractable)
```sh
# push catch.fixed.js to /sdcard first, then stage it AS catch.js (single-shot, no watcher):
su -c 'cp /sdcard/catch.fixed.js /data/local/tmp/re.zyg.fri/catch.js'
su -c 'chmod 644 /data/local/tmp/re.zyg.fri/catch.js'
# CONFIRM the fixed bytes are in place (must print 1+, else you'd be testing the OLD file):
su -c 'grep -c "KILL-SWITCH" /data/local/tmp/re.zyg.fri/catch.js'
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'      # marker OFF (catching disarmed)
# write a one-shot script config (on_change:ignore = no reload watcher mid-test):
su -c 'printf "%s" "{\"interaction\":{\"type\":\"script\",\"path\":\"/data/local/tmp/re.zyg.fri/catch.js\",\"on_change\":\"ignore\"},\"runtime\":\"qjs\"}" > /data/local/tmp/re.zyg.fri/config.script.oneshot.so'

# --- Session A: logcat FIRST (before relaunch) ---
su -c 'logcat -c; logcat -s frida-catch'

# --- Session B: switch to script mode + relaunch, then IMMEDIATELY foreground PoGo + keep it foregrounded ---
su -c 'cp /data/local/tmp/re.zyg.fri/config.script.oneshot.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'sleep 2'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
```
**Expected logcat order** (note: `installed` prints **before** `warming up`):
```
init stage=... — corrected on-device catcher (single-thread, one-shot frame-gated discovery)
installed (bootstrap): {"pbt":true,"pump":true,"probhook":N,"catchhook":N} liveness=ok
warming up (frames 0/90) before discovery ...
READY — msvc=ok avatar=ok itembag=ok iap=ok | Poke=.. Great=.. Ultra=.. Stardust=..
```
- `FATAL ... missing liveness exports [...]` ⇒ the fork can't self-find singletons
  in-process → **use Phase 1 (Termux)**.
- `NATIVE FAULT ... KILL-SWITCH set` ⇒ **exactly one line, then silence** (no storm) →
  capture the `pc`/`@addr`, roll back (panic button), report, use Phase 1.
- stuck on `warming up (frames 0/90)` ⇒ PoGo isn't actually foregrounded/rendering.

### Phase 3 — arm one catch (Phase 2 only, after READY)
```sh
su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'   # ON
# expect ">>> TOGGLE ON — catching", then "run | ... caught=.." every ~10s; watch a few cycles.
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'                                                     # OFF
```

### PANIC BUTTON (any time — always returns desktop control)
```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'; su -c 'sleep 2'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
```
Every config change above **overwrites `libgadget.config.so` in place** (preserves the 0644 /
`system_file` SELinux context) — **never `rm` then recreate it.** Full recovery if needed:
restore the Phase-0 `re.zyg.fri.bak.<TS>` directory.

---

## 4. TERMUX-ATTACH FALLBACK — what it is, and when to switch

`termux_catch.py` runs the **proven desktop catcher on the phone**, attaching ADB-free to
the gadget's loopback **listen** socket `127.0.0.1:27047` via
`add_remote_device('127.0.0.1:27047')` + `dev.enumerate_processes()[0].pid` (the exact
idiom 30+ in-repo scripts already use). It monkey-patches only `pg.get_session` /
`pg._adb_pidof` before importing `catch_loop_fast.py`, so the proven host-thread /
transient-script GC-liveness architecture — the thing the in-process port broke — stays
100% intact and the off-thread world-stop never touches the render frame; it changes no
config and writes no marker, so Ctrl-C cleanly ends it and the desktop can still attach
afterward. **This is actually the PRIMARY recommendation, not a last resort** — switch to
(or just start with) it whenever you want least risk, and it is the *mandatory* fallback the
moment script mode prints `FATAL ... missing liveness exports`, a single `NATIVE FAULT
... KILL-SWITCH set`, or stays stuck below READY. Its only real precondition is a **17.x
frida wheel in Termux** (see §5).

---

## 5. HONEST CONFIDENCE + the one thing most likely to still go wrong

**Confidence.**
- **PRIMARY (Termux-attach): high (~90%).** It reuses the proven, never-crashed code
  verbatim; the monkey-patch lands (the catcher uses module-qualified `pg.get_session()`,
  resolved at call time); the attach idiom is the repo's own 30×-proven pattern; the
  off-thread liveness is preserved. The only unproven hops are environmental (§ below), not
  code.
- **FALLBACK (`catch.fixed.js`): real but partial (~55–65%).** It *definitively* kills the
  40 s storm, the pre-init garbage-domain deref, and the backgrounded-engine crash — those
  are gone. What it does **not** prove: it still calls `il2cpp_stop_gc_world` from the render
  thread, just **once** instead of every second. The desktop never does this from a render
  thread at all. If the true failure mode is "you cannot stop the GC world from a thread
  that is itself a mutator mid-frame" (not merely "don't do it repeatedly"), then the single
  discovery stop could still fault **once** — you'd see exactly one `NATIVE FAULT ...
  KILL-SWITCH set` (clean, no storm), and the fix is to fall back to Termux. So all bad
  outcomes are now single-shot and self-labeled, which is precisely why it's safe to *try*.

**The one thing most likely to still go wrong on the real test:** getting a **17.x `frida`
Python wheel installed in Termux** for `aarch64`/`linux-android`. PyPI publishes **no**
frida wheels for that platform, so a bare `pip install frida` often either compiles-from-
source-and-fails or resolves a non-17 major the 17.x gadget refuses to attach to. The
gadget fork is 17.x (internal "200046.1.1"); pin the client to the desktop's exact **17.9.11**
(majors guaranteed identical), and if no `cp<minor>` aarch64 wheel exists for Termux's
current Python, install a prebuilt `frida-17.x-cp<XY>-cp<XY>-android_aarch64.whl` from
frida's GitHub releases by URL (those assets do exist), or shift Termux's Python minor to
one a wheel exists for. `termux_catch.py` de-risks this as far as software can — it refuses
to start without an importable frida and warns on a non-17 major — but the wheel acquisition
itself is a manual, environment-dependent step. **A secondary, untested hop:** whether
Android lets Termux's app-UID reach PoGo's loopback listener — the §3 one-line socket probe
diagnoses that in one second, with `su -c 'python ...'` as the fix if SELinux blocks the
sibling-UID connect.

---

### Files
- `system/ondevice_toggle/termux_catch.py` — PRIMARY (runs proven catcher on-device via
  listen socket; ADB-free; no edits to proven files).
- `system/ondevice_toggle/catch.fixed.js` — FALLBACK (single-thread, one-shot frame-gated
  discovery, kill-switch; rename to `catch.js` on deploy; `node --check` clean).
- `system/ondevice_toggle/TERMUX_SETUP.md` — one-time Termux setup incl. the frida-wheel step.
- `system/ondevice_toggle/TEST_PROTOCOL.md` — fuller script-mode protocol (this file is the
  decisive summary).
- Proven, unchanged: `pogo_il2cpp.py`, `system/scripts/game_write/catch_loop_fast.py`.
- Original crashing file kept for diff: `system/ondevice_toggle/catch.js`.
