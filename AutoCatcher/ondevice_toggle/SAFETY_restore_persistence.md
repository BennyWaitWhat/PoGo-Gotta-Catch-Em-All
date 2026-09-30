# Safety, Restore & Persistence — research findings for the on-device catch.js toggle

Scope: this is the **safety / restore-to-listen / boot-persistence / crash-isolation** research
angle only. It does NOT port catch.js (that is a sibling task). It tells you how to flip the
ZygiskFrida gadget from `listen` to `script` mode **without losing the ability to flip back**,
how to keep catch.js from bricking PoGo, and how to make the toggle survive a reboot.

Nothing here touches the phone. All commands are for the **later, coordinated** deploy step.

---

## 0. The single most important fact for this device

The current gadget config is:
```json
{"interaction":{"type":"listen","address":"127.0.0.1","port":27047,"on_load":"resume"}}
```
That gadget **is already loading and running scripts** today (the desktop catcher attaches over
port 27047 and injects JS that builds `il2cpp_` NativeFunctions and `Interceptor.attach`es a
LateUpdate pump). **That alone proves the on-device gadget binary can host this exact script.**
The only thing that changes for autonomy is *how the script gets in*: instead of a TCP client
pushing it, the gadget reads it off disk on launch (`type:"script"`).

### The Frida-17 "script mode is broken" scare does **NOT** apply here

There is a wave of 2025 reports that "gadget script mode is broken on Frida 17+ / Android"
([frida#3526](https://github.com/frida/frida/issues/3526),
[frida#3516](https://github.com/frida/frida/issues/3516),
[frida#3558](https://github.com/frida/frida/issues/3558),
[frida#3645](https://github.com/frida/frida/issues/3645)). The root cause is that **Frida 17
stopped bundling the language bridges** (Java bridge, ObjC bridge) into the gadget — so scripts
that call `Java.perform`, `Java.use`, `Java.choose`, etc. silently fail unless you `frida-compile`
the script with `npm install frida-java-bridge` baked in.

**catch.js uses ZERO Java.** It is pure native: `Process.findModuleByName`, `Module.enumerateExports`,
`new NativeFunction(...)`, `Interceptor.attach`, `Memory.alloc`, `NativeCallback`, pointer reads.
None of that depends on a bridge. A pure-native script loads and runs in script mode on Frida 17+
exactly as it did on 16. **So you do NOT need frida-compile, npm, or a bridge for this script.**

Caveat / action item: **identify the gadget version before deploy** so we are not surprised.
On a renamed `libgadget.so` the version is not in the filename, so read it out of the binary
(strings approach, [PyPI frida-gadget](https://pypi.org/project/frida-gadget/),
[frida-gadget.version](https://github.com/frida/frida-core/blob/main/lib/gadget/frida-gadget.version)).
The desktop-side host (`pogo_il2cpp.py`) pins `FRIDA_REMOTE = 127.0.0.1:27047`; whatever `pip`
version is talking to it today is the matching gadget vintage — sanity-check they agree.

```bash
# LATER, on the phone (Termux+root), NOT now — read the gadget version:
su -c 'strings /data/local/tmp/re.zyg.fri/libgadget.so | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+" | sort -u | tail'
# Cross-check the desktop host version that currently drives this same gadget:
#   (desktop)  python -c "import frida; print(frida.__version__)"
# They should be the same major (gadget <-> frida client are version-locked).
```

---

## 1. Restore-to-listen safety net (the #1 safeguard)

**Requirement:** desktop control (the existing Python catcher, dex reads, tag ops) must remain
recoverable. We achieve that by **never destroying the listen config** — we keep it as a named
file and make the active config a thing we can swap with one `cp`.

### 1a. Two static configs, swap by copy (recommended)

Keep BOTH configs on disk under fixed names and make `libgadget.config.so` a **copy** of whichever
mode you want. This is bullet-proof: restoring desktop control is a single `cp`, no editor, no JSON
typo risk, works from a recovery shell.

`config.listen.so` (the current/desktop mode — byte-for-byte today's content):
```json
{"interaction":{"type":"listen","address":"127.0.0.1","port":27047,"on_load":"resume"}}
```

`config.script.so` (autonomous on-device mode):
```json
{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"reload"}}
```

Deploy / toggle commands (LATER, coordinated — phone is busy now):
```bash
# one-time: stage both named configs next to the gadget
su -c 'cp /data/local/tmp/re.zyg.fri/libgadget.config.so /data/local/tmp/re.zyg.fri/config.listen.so'   # snapshot current listen cfg
# (write config.script.so via the heredoc in the deploy script — see DEPLOY_commands.md)

# >>> SWITCH TO AUTONOMOUS (script) MODE <<<
su -c 'cp /data/local/tmp/re.zyg.fri/config.script.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
# then force-stop + relaunch PoGo so the gadget re-reads config on next process start

# >>> RESTORE DESKTOP CONTROL (listen) MODE — the panic button <<<
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
# force-stop + relaunch PoGo; desktop Python can attach on 27047 again
```

### 1b. Why a copy, not an edit

- A botched in-place `sed`/echo can leave `libgadget.config.so` as **invalid JSON**, and an
  invalid config can make the gadget fall back to defaults or refuse to load — risking that
  *neither* desktop nor on-device control works. A whole-file `cp` of a known-good file can't
  half-write valid JSON.
- The config is only re-read when the **gadget constructor runs**, i.e. at process start
  ([Frida Gadget docs](https://frida.re/docs/gadget/): "Gadget gets kickstarted as soon as the
  dynamic linker executes its constructor function"). So switching modes ALWAYS requires a PoGo
  force-stop + relaunch. There is no live mode-switch. This is good: it means a bad config can
  never corrupt a *running* session — worst case the *next* launch misbehaves and you `cp` back.

### 1c. The absolute fallback: rename the gadget out of the way

If a config swap ever wedges PoGo on launch, you can neutralise Frida entirely (PoGo runs clean,
unmodded-by-frida) by moving the gadget aside. Pokemod's own mods are separate; this only removes
the Frida layer.
```bash
# NUCLEAR fallback — PoGo launches with NO frida gadget at all:
su -c 'mv /data/local/tmp/re.zyg.fri/libgadget.so /data/local/tmp/re.zyg.fri/libgadget.so.bak'
# restore it later:
su -c 'mv /data/local/tmp/re.zyg.fri/libgadget.so.bak /data/local/tmp/re.zyg.fri/libgadget.so'
```
Note: how the gadget is injected (Zygisk module "re.zyg.fri") determines whether renaming the
.so is enough or whether the Zygisk loader must also be toggled. Confirm the injection mechanism
at deploy time. Worst case, disabling the ZygiskFrida Magisk module + reboot fully removes it.

### 1d. Back up the whole gadget dir before ANY change
```bash
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'
```

---

## 2. Don't brick PoGo when catch.js errors — crash-isolation safeguards

Two **different** failure classes, only one of which `try/catch` can save you from. This
distinction is the crux of in-process safety
([frida#2039](https://github.com/frida/frida/issues/2039),
[frida#1486](https://github.com/frida/frida/issues/1486 "UnityMain SIGSEGV"),
[frida-gum#371](https://github.com/frida/frida-gum/issues/371)).

| Failure class | Example | Does JS try/catch help? | Mitigation |
|---|---|---|---|
| **JS exception** in hook body | bad property, `undefined.add()`, throw | **YES** | wrap every hook body + every loop iter in `try{}catch(e){}` |
| **Native fault** (SIGSEGV/SIGBUS) | deref a stale/garbage il2cpp pointer; hook installed too early | **NO** — it's a signal, kills the process | validate pointers before deref; gate install on engine-ready; never hook libil2cpp before main menu |

### 2a. JS-exception isolation — the script ALREADY does this well, keep it

The ported catch.js must preserve the existing pattern from `catch_loop_fast.py`'s JS:
- `tick()` (the per-frame pump fired from `CameraFollowingGround.LateUpdate`) wraps its whole body
  in `try{ ... }catch(err){}`. **This is the single most important guard** — the pump runs every
  frame on PoGo's main thread, so an unguarded throw there would fire continuously. Keep it.
- `fireOpen`, `fireCatch`, `useBerry`, `onCatchResult`, `readCP`, `readProbs`, `refillService`'s
  inner loop body — each is individually `try/catch`-wrapped. Keep all of them.
- Pointer reads are guarded with `.isNull()` checks before `.add(...).read*()`. Keep and ADD MORE
  (see 2c).

A JS exception that is caught inside the LateUpdate `onEnter` does NOT propagate into Unity's
native LateUpdate caller — Frida's interceptor trampoline returns normally — so PoGo keeps
rendering. That is exactly why the existing desktop catcher never crashes PoGo today. The
on-device version inherits this for free **as long as you keep the try/catch around `tick()`**.

WARNING — the detach-hang footgun ([frida-gum#371](https://github.com/frida/frida-gum/issues/371)):
if a JS exception **propagates out of a hooked function back into Frida's process-wide handler**
(i.e. you did NOT catch it locally), the Interceptor can end up in a state that "will fail to ever
detach," hanging the Frida thread. The defence is the same: **catch locally inside every hook body**
so nothing ever reaches the global handler. In script mode there is no client to recover the
session, so a wedged Frida thread = you must restart PoGo. Local try/catch avoids it entirely.

### 2b. Add a top-level process exception handler (diagnose native faults)

`try/catch` cannot catch SIGSEGV. Install a process-wide handler so a near-miss is *logged*
(to file, since there's no console reader on-device) instead of silently taking PoGo down. It also
lets you optionally swallow a fault during the risky install window. Per multiple issues, native
il2cpp faults are only visible once `Process.setExceptionHandler` is installed
([frida#2039](https://github.com/frida/frida/issues/2039)).

```js
// add near the TOP of catch.js, before any Interceptor.attach
var LOGF = "/data/local/tmp/re.zyg.fri/catch.log";
function logln(s){ try{ var f=new File(LOGF,"a"); f.write((Date.now())+" "+s+"\n"); f.flush(); f.close(); }catch(e){} }
Process.setExceptionHandler(function(d){
  try{ logln("NATIVE FAULT "+d.type+" @"+d.address+" ctx.pc="+(d.context&&d.context.pc)); }catch(e){}
  return false;   // false = let the OS handle it (normal crash). returning true would swallow it
                  // and resume — only do that if you KNOW the faulting instruction is safe to skip.
});
```
Recommendation: **return `false`** (don't swallow) in normal operation — a swallowed memory fault
can corrupt state worse than a clean crash. Use `return true` only as a last-resort experiment if a
specific, understood fault is blocking startup. The value of the handler here is the **log line**:
after an unexpected PoGo crash you'll have a file telling you it was a native fault from the script
vs. an unrelated PoGo crash.

### 2c. The biggest native-fault risk in THIS script: the GC liveness/stop-world path

The singleton finder ported from `pogo_il2cpp.py` (`liveness_find_instances`, lines 104-132) calls:
```
il2cpp_stop_gc_world()  ->  il2cpp_unity_liveness_*  ->  il2cpp_start_gc_world()
```
**If `il2cpp_start_gc_world()` is ever skipped, every managed thread stays suspended and PoGo
DEADLOCKS (frozen, ANR, force-close).** This is a documented, repeatable Unity failure mode: the
stop/start calls must be paired, and the liveness scan itself is a known native crash site
(`Liveness.cpp`) ([Unity: Native Crash Liveness.cpp:454](https://discussions.unity.com/t/native-crash-il2cpp-libil2cpp-vm-liveness-cpp-454/905826),
[Unity Issue Tracker: LivenessState::AddProcessObject crash](https://issuetracker.unity3d.com/issues/ios-il2cpp-crash-on-il2cpp-vm-livenessstate-addprocessobject-when-using-social-dot-loadusers-and-then-changing-scenes),
[Unity: deadlock from GC world contention](https://discussions.unity.com/t/deadlock-issue-caused-by-enabling-incremental-gc/922987)).

The desktop `pogo_il2cpp.py` already does the right thing — note its `catch(e)` restarts the world:
```js
} catch(e) {
    if (IL2.startWorld) { try { IL2.startWorld(); } catch(e2) {} }   // <-- MUST keep this
    return {err: 'liveness threw: ' + e.toString()};
}
```
**MANDATORY when porting to standalone JS — harden it further into a finally-style guarantee:**
```js
function liveness_find_instances(klass){
  // ... build callbacks ...
  var worldStopped = false;
  try {
    if (IL2.stopWorld){ IL2.stopWorld(); worldStopped = true; }
    var state = IL2.livenessAlloc(klass, 0, onObjects, ptr(0), realloc);
    IL2.livenessFromStatics(state);
    if (IL2.livenessFinalize) IL2.livenessFinalize(state);
    if (IL2.livenessFreeStruct) IL2.livenessFreeStruct(state);
  } catch(e){
    logln("liveness threw: "+e);
    return {err:String(e)};
  } finally {
    if (worldStopped && IL2.startWorld){ try{ IL2.startWorld(); }catch(e2){ logln("startWorld FAILED: "+e2); } }
  }
  return {hits: hits};
}
```
Extra liveness-specific safeguards for the autonomous build:
- **Don't enumerate every frame.** The desktop host called `find_singleton` only at connect-time and
  occasionally (IapService re-locate every ~10s). The on-device loop must do the same: resolve
  singletons ONCE at startup, cache the pointers, and re-resolve only on a long timer or after a
  detected failure. A stop-the-world GC pass every LateUpdate frame would tank PoGo's framerate
  and massively widen the crash window.
- **Gate the first liveness call on engine readiness** (see 2d) — a stop-world before the GC heap
  is fully initialised is a prime `Liveness.cpp` crash trigger.
- Consider falling back to the *cheaper* singleton strategy where possible: the script can also
  find some objects by hooking a method that receives them (the existing code already hooks
  `EncounterOutProto.MergeFrom` and `CatchPokemonOutProto.MergeFrom` to harvest pointers without
  GC scanning). Prefer hook-harvested pointers over stop-world scans wherever a hook exists.

### 2d. Early-instrumentation timing — the classic libil2cpp-not-loaded crash

In script mode the gadget runs your script **very early** (constructor time), and the docs say it
"calls your `init()` method and waits for it to return before letting the program execute its
entrypoint" ([Frida Gadget docs](https://frida.re/docs/gadget/)). At that instant **libil2cpp.so
may not be mapped yet**, and hooking libil2cpp too early is a documented SIGSEGV
([frida#1486](https://github.com/frida/frida/issues/1486): "placing hooks early onto libil2cpp.so
at startup eventually leads to SIGSEGV... doing the same once the game reaches the main menu does
not"). The desktop host sidestepped this entirely by only attaching *after* PoGo was up; the
autonomous script must reproduce that gate **itself**.

**MANDATORY: do not install hooks at script-load. Poll until the engine is ready, then install.**
```js
function il2cppReady(){
  var m = Process.findModuleByName("libil2cpp.so");
  if(!m) return false;
  // also require the exports we need to be resolvable (module present != fully linked)
  try { return !!Module.findExportByName("libil2cpp.so","il2cpp_domain_get"); } catch(e){ return false; }
}
function whenReady(cb){
  var id = setInterval(function(){
    try{
      if(il2cppReady()){
        clearInterval(id);
        // extra settle so the domain/assemblies + main menu exist (mirrors desktop's settle/bag-walk gate)
        setTimeout(cb, 4000);
      }
    }catch(e){ logln("ready-poll err: "+e); }
  }, 500);
}
// top level of catch.js:
whenReady(function(){ install(); /* then start the LateUpdate pump, then resolve singletons */ });
```
Mirror the desktop readiness proof: `pogo_il2cpp.py:restart_pogo_and_wait` does not consider PoGo
ready until a fresh `PokemonBagImpl` walk returns >100 mons. The on-device script should likewise
not flip `RUN=true` (or even resolve singletons) until it has positively confirmed the engine works
(e.g. a successful `find_singleton` returning at least one plausible hit), not merely that the
module is present.

NOTE on `setInterval`/`setTimeout` in gadget script mode: there is a historical report that timers
were broken in some gadget builds ([frida#2848](https://github.com/frida/frida/issues/2848)). Since
this device's gadget already runs timer-driven desktop scripts fine, timers should work — **but the
robust primary clock is the LateUpdate pump itself** (the existing design is wall-clock gated:
`if (now - lastOpenMs >= INTERVAL_MS)`), which does not depend on `setInterval` at all. Use the
LateUpdate pump as the heartbeat; use `setInterval` only for the one-shot readiness poll. If timers
turn out flaky, the readiness poll can instead piggyback on the first few LateUpdate ticks.

### 2e. Guard EVERY pointer deref (native-fault prevention)

Most SIGSEGVs in this script will come from reading a field off a pointer that's null/stale/freed.
The existing code mostly does this; the standalone port must be **uniformly** defensive:
- `if(!p || p.isNull()) return ...;` before every `.add(off).read*()`.
- Bound enumeration loops with a guard counter (the desktop `refillService` already caps at 3000;
  `bag_walk` caps at `lcount+200`). Keep all guard caps.
- Treat a singleton pointer as **possibly stale after any relog/resync** — re-resolve rather than
  trusting a latched pointer (the desktop code re-locates IapService every report for exactly this
  reason). A throw/flee status or a sudden read of garbage is the signal to re-resolve.

### 2f. `on_change:"reload"` is a safety feature — but mind reload semantics

With `on_change:"reload"` the gadget watches catch.js and reloads it on file change
([Frida Gadget docs](https://frida.re/docs/gadget/)). Benefits for safety:
- You can push a fixed catch.js to the phone and it takes effect **without** force-stopping PoGo.
- On reload, `init(stage,...)` is called with `stage === "late"` (vs `"early"` on first load), so
  the script can tell a reload from a cold start.

Reload hazards to handle in the ported script:
- A reload **re-runs the whole script top-to-bottom**. If the script does
  `Interceptor.attach(LateUpdate,...)` unconditionally, a reload can **double-attach** the pump (two
  ticks per frame) and re-hook MergeFrom twice. Guard installs against this: keep a module-global
  "installed" flag, or implement `rpc.exports.dispose = function(){ Interceptor.detachAll(); clearInterval(...); }`
  so the old instance tears down before the new one installs. Frida calls `dispose()` on unload/reload.
- If you push a **syntactically broken** catch.js, the reload fails to load. The currently-running
  (good) instance generally keeps running, but to be safe **edit atomically**: write to `catch.js.new`
  then `mv` over `catch.js` (rename is atomic; the watcher never sees a half-written file).
```bash
# atomic script update (LATER): never let the watcher read a partial file
su -c 'cp /sdcard/catch.js.new /data/local/tmp/re.zyg.fri/catch.js.new && mv -f /data/local/tmp/re.zyg.fri/catch.js.new /data/local/tmp/re.zyg.fri/catch.js'
```
- If you want to be conservative for the *first* deploy, set `on_change:"ignore"` so the script can
  ONLY change on a deliberate PoGo restart (no surprise live reloads). Flip to `reload` once stable.

---

## 3. Boot persistence (Termux:Boot) — and why the gadget barely needs it

### Key realisation: the gadget itself is already boot-persistent

The gadget loads via the **ZygiskFrida Magisk/Zygisk module** every time PoGo starts — that's
inherent to Zygisk injection and already survives reboots **today**. So "catching survives reboot"
needs only two things after a reboot:
1. `libgadget.config.so` still points at `script` mode (it's a file on `/data/local/tmp`, which
   persists across reboot — **no boot script needed for this**), and
2. catch.js still on disk (also persists).

**Therefore a reboot already comes back in autonomous mode with no boot script at all**, provided
you left the config in script mode. The ON/OFF *toggle* (section 4) is what gates catching, not boot.

### When you DO want Termux:Boot

Use a boot script only for **active management** you want at every boot, e.g.:
- enforce a **default-OFF on boot** (safer): flip the config back to `listen` on boot so the phone
  never auto-starts catching unattended, and you opt-in via the toggle.
- write a heartbeat/log marker, take a wake-lock so Termux survives doze, or kick the toggle's
  desired state.

Termux:Boot facts ([termux/termux-boot](https://github.com/termux/termux-boot),
[F-Droid](https://f-droid.org/en/packages/com.termux.boot/),
[guide](https://termuxtools.com/termux-boot-autorun-scripts/)):
- Install from F-Droid (present on this device), **launch the app once** to arm the
  `BOOT_COMPLETED` receiver (it has no UI; it opens and minimises — that's normal).
- Scripts live in `~/.termux/boot/` (`/data/data/com.termux/files/home/.termux/boot/`), run in
  **sorted filename order**, each independently — **one failing script does not stop the others**
  (failures are silent → log everything).
- Termux:Boot runs as the **unprivileged Termux user**, NOT root. For anything touching
  `/data/local/tmp/re.zyg.fri` you must shell to root: `su -c '...'`.
- **Disable battery optimization for Termux:Boot** (Android kills background receivers aggressively)
  and `termux-wake-lock` first if the script must keep running.

Example boot script `~/.termux/boot/00-catcher-default-off` (LATER):
```sh
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
# default to SAFE (desktop/listen) mode on every boot; user opts in via the toggle widget.
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'sh -c "echo $(date +%s) booted >> /data/local/tmp/re.zyg.fri/boot.log"'
```

### More robust than Termux:Boot for root tasks: Magisk `service.d`

Because the gadget is a Magisk/Zygisk thing already, a Magisk **general boot script** is the most
reliable place for any root-level boot action and needs no app, no `su` call, no battery-opt fight
([Magisk guides](https://topjohnwu.github.io/Magisk/guides.html)):
- Put an executable script in `/data/adb/service.d/` (runs in **late_start service** mode — after
  Zygote/most services; the recommended stage). `chmod +x`. It runs as root automatically.
- **Avoid `post-fs-data.d`** for this — it runs before Zygote and "using setprop will deadlock the
  boot process"; it's also often too early. `service.d` (+ a small `sleep` if needed) is correct.
- **DANGER:** a buggy Magisk boot script "can result in a non-functioning phone" requiring recovery
  (TWRP) to remove the file. Keep it trivial (a single `cp`), test by hand first, and prefer the
  Termux:Boot route during bring-up since a bad Termux script can't brick boot.

Recommendation: during bring-up use **Termux:Boot** (can't brick boot). Once the toggle is proven,
optionally move the default-state enforcement to a one-line **Magisk `service.d`** script for
determinism. For pure "keep catching after reboot," you need **neither** — the persisted config
file already does it.

---

## 4. The ON/OFF toggle — how it interacts with safety

The toggle's job is to set the gadget mode (or a flag the script reads). Two designs, with the
safety trade-off:

**Design A — toggle swaps the config + restarts PoGo (heavier, fully off).**
- ON  = `cp config.script.so libgadget.config.so` + relaunch PoGo (catcher loads).
- OFF = `cp config.listen.so libgadget.config.so` + relaunch PoGo (no catcher; desktop can attach).
- Pro: OFF means catch.js is **not even loaded** — zero in-process risk, desktop fully restored.
- Con: every toggle force-stops PoGo (a few seconds of downtime).

**Design B — config stays in script mode; toggle flips a marker file the script polls (lighter). THIS IS WHAT catch.js IMPLEMENTS.**
- catch.js polls a PRESENCE marker `/data/local/tmp/re.zyg.fri/catch.on` each pump pass (it `open()`s
  the file; success ⇒ ON). The file's *contents are irrelevant* — only its existence matters. This
  drives the in-process `RUN` gate (marker present ⇒ `RUN=true`, absent ⇒ `RUN=false`).
- ON = create the marker, OFF = remove it — **no PoGo restart**, instant (~1s poll latency).
- DO NOT use a content flag like `echo 0 > RUN`: catch.js never reads a file named `RUN`, and a
  marker that merely *exists* reads as ON regardless of the "0" inside it.
- Pro: instant, no downtime; the LateUpdate pump already early-returns when `!RUN`, so OFF is cheap.
- Con: catch.js is always loaded (the in-process safeguards in §2 are doing the work even when OFF).
- Safety add: when the flag flips OFF, also detach the heavy hooks if you want true quiescence
  (`Interceptor.detachAll()`), and re-`install()` on the next ON. Simpler: just gate on `RUN` (the
  pump runs but does nothing) — the existing design already supports this and is battle-tested.

Recommendation: **Design B for the everyday toggle** (instant, reuses the proven `RUN` gate),
**plus** keep Design A's config swap available as the "fully disable / hand control back to desktop"
panic button (§1a). i.e. the home-screen button = flag file; a separate command/Termux shortcut =
restore-to-listen.

Toggle marker, both directions (LATER):
```bash
su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'  # ON
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'                                                    # OFF
```
Note: Termux:Widget is NOT installed on this device — the home-screen button mechanism is a sibling
task's concern. From a safety view, whatever drives the button must end up running one of the
`su -c` lines above (flag) or the config `cp` (mode). Both are root writes to `/data/local/tmp`.

---

## 5. What happens to PoGo stability if the in-process script throws — summary

- **Caught JS exception in a hook body** → nothing; Frida's trampoline returns normally, PoGo keeps
  running. (This is the normal, safe case and is why the desktop catcher never crashes PoGo.) The
  existing script's pervasive `try/catch` is what buys this. KEEP IT.
- **Uncaught JS exception that reaches Frida's global handler** → can wedge the Interceptor so it
  "will fail to ever detach" ([frida-gum#371](https://github.com/frida/frida-gum/issues/371)); in
  script mode there's no client to recover → must restart PoGo. Prevent by catching locally.
- **Native fault (SIGSEGV/SIGBUS)** from a bad pointer deref or too-early libil2cpp hook → **PoGo
  crashes** (force-close), `try/catch` cannot stop it. Prevent with: readiness gate (§2d),
  uniform pointer guards (§2e), paired stop/start GC world (§2c).
- **Skipped `il2cpp_start_gc_world()`** → **PoGo deadlocks/ANRs** (worst outcome — a hang, not a
  clean crash). Prevent with the `finally`-guaranteed `startWorld` (§2c). This is the single most
  dangerous line in the whole port.
- **Script syntactically broken on reload** → reload fails; running instance usually survives; next
  cold start has no catcher. Prevent with atomic `mv` updates (§2f); recover with config `cp` to
  listen and/or fixing the file.
- **Worst realistic on-device meltdown** = PoGo won't launch (bad config or crash-on-install).
  Recovery ladder, in order: (1) `cp config.listen.so` over the config + relaunch; (2) set
  `on_change:"ignore"` + fix catch.js; (3) rename `libgadget.so` aside (PoGo runs frida-free);
  (4) restore `re.zyg.fri.bak.*`; (5) disable the ZygiskFrida Magisk module + reboot.

None of these can lose data: PoGo's catch/inventory/stardust state is **server-authoritative**
(per project memory), so a crash mid-throw just drops that throw — the next launch re-syncs.

---

## 6. Concrete safeguard checklist for the ported catch.js (hand to the porting task)

1. [ ] Pure-native only (no `Java.*`) — confirmed compatible with Frida 17+ gadget, no bridge/compile needed.
2. [ ] Top-of-file `logln()` to a file + `Process.setExceptionHandler` returning `false` (log native faults).
3. [ ] `whenReady()` gate on `libil2cpp.so` export-resolvable + settle delay; **install hooks only after**.
4. [ ] Keep the `try{}catch{}` around `tick()` (the LateUpdate pump) — non-negotiable.
5. [ ] Keep per-function `try/catch` on fireOpen/fireCatch/useBerry/onCatchResult/readCP/readProbs/refill loop.
6. [ ] Port the liveness finder with a **`finally`-guaranteed `il2cpp_start_gc_world()`** + logging.
7. [ ] Resolve singletons ONCE at startup (cache pointers); re-resolve only on timer/failure, never per frame.
8. [ ] Prefer hook-harvested pointers (MergeFrom hooks) over stop-world GC scans where available.
9. [ ] Uniform `.isNull()` guards before every pointer deref; keep all loop guard-caps.
10. [ ] Guard against double-install on reload (the `INSTALLED` flag; `dispose()` need not clearInterval since none are used).
11. [ ] Drive the heartbeat from the LateUpdate pump (wall-clock gated), NOT from `setInterval`/`setTimeout` — those are broken in gadget script mode (frida #2848 / #2879). The `clock_gettime` bootstrap hook is the timer-free retry until the pump lands.
12. [ ] Drive the `RUN` gate from the PRESENCE of marker `catch.on` (open()=ON), default OFF if absent.
13. [ ] Hard-code config (rate/range/floors/legendary dex/reticle 0.02–0.12/rethrow) — values listed in §7.

---

## 7. Config values to hard-code (lifted verbatim from catch_loop_fast.py — for the porting task)

These are the exact catch-quality knobs; reproduce them so on-device catching == desktop catching:
- `RATE_PER_MIN = 35` → `INTERVAL_MS = round(60000/35) = 1714` ms between opens.
- `LAG_MS = 3500` (open→throw hidden-latency delay), `RETHROW_DELAY = 2000`, `MAXTHROW = 4`.
- `MAX_RANGE_M = 80.0` (desktop `MAXR` default in JS is 90 but Python pushes 80 — **use 80**).
- Ball floors `POKE/GREAT/ULTRA_FLOOR = 5`; data-driven pick `CATCH_THRESHOLD = 0.5`.
- Reticle (Excellent) = `0.02 + random()*0.10`; spin=1, curve=1, bullseye=1 (the PokeballThrow struct).
- `USE_PINAP = False`, `PINAP_FLOOR = 20`, `PINAP_ID = 705`.
- `LEGENDARY_DEX` list (national dex #s) — copy the full array from `catch_loop_fast.py:42`.
- Struct offsets / class+method names — copy from the JS in `catch_loop_fast.py` (PokeballThrow at
  +0x10 ball / +0x14 reticle / +0x18 spin / +0x19 curve / +0x1a bullseye; CatchPokemonOutProto
  status +0x10, throws +0x38; etc.). Those are the load-bearing magic numbers.

---

### Sources
- Frida Gadget docs (interaction types, on_change/on_load, init lifecycle, constructor timing): https://frida.re/docs/gadget/
- Frida modes of operation: https://frida.re/docs/modes/
- Frida 17 gadget script mode broken / bridges unbundled: https://github.com/frida/frida/issues/3526 , https://github.com/frida/frida/issues/3516 , https://github.com/frida/frida/issues/3558 , https://github.com/frida/frida/issues/3645
- Gadget timers (setTimeout) issue: https://github.com/frida/frida/issues/2848
- Interceptor detach-hang after caught exception: https://github.com/frida/frida-gum/issues/371
- Native faults need Process.setExceptionHandler; bad-access on il2cpp hooks: https://github.com/frida/frida/issues/2039 , https://github.com/frida/frida/issues/1486
- Gadget autonomous "zombie" process at exit (Windows): https://github.com/frida/frida-core/issues/468
- il2cpp stop/start GC world deadlock + Liveness.cpp crash sites: https://discussions.unity.com/t/native-crash-il2cpp-libil2cpp-vm-liveness-cpp-454/905826 , https://issuetracker.unity3d.com/issues/ios-il2cpp-crash-on-il2cpp-vm-livenessstate-addprocessobject-when-using-social-dot-loadusers-and-then-changing-scenes , https://discussions.unity.com/t/deadlock-issue-caused-by-enabling-incremental-gc/922987
- Termux:Boot (autorun, root caveat, battery opt): https://github.com/termux/termux-boot , https://f-droid.org/en/packages/com.termux.boot/ , https://termuxtools.com/termux-boot-autorun-scripts/
- Magisk boot scripts (service.d vs post-fs-data, brick warning): https://topjohnwu.github.io/Magisk/guides.html
- Reading gadget version from the binary: https://pypi.org/project/frida-gadget/ , https://github.com/frida/frida-core/blob/main/lib/gadget/frida-gadget.version
