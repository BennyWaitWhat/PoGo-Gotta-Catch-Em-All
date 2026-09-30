# READY — On-device autonomous PoGo auto-catcher (home-screen toggle)

**This file is the authoritative deploy guide. Where it disagrees with `README.md`, follow
THIS file.** (The old `README.md` recommends `install_ondevice_catcher.FULL.sh` — do NOT use
that one; see §1 and the manifest. The correct installer is **`install.sh`**.)

> Status right now: nothing here has touched the phone. The phone is busy — a desktop catcher
> is attached on `127.0.0.1:27047`. Everything below is local artifacts + exact commands for a
> later, coordinated deploy that you run from the phone. Deploying is safe to *stage* while the
> desktop catcher runs; the one disruptive step (going autonomous) is clearly marked and is done
> only after you stop the desktop catcher.

---

## 1. What this is, and how it frees the phone from the desktop

**The whole catcher is one file: `catch.js`.** It is a self-contained Frida script that runs
*inside* PoGo's own process via the ZygiskFrida in-process gadget switched to **script mode**.
In script mode the gadget reads `catch.js` off disk and runs it on every PoGo launch — so there
is **no desktop, no Python host, no ADB, no Tailscale, no Claude** in the loop. The phone catches
on its own.

`catch.js` is a faithful 1:1 port of the proven desktop catcher
(`system/scripts/game_write/catch_loop_fast.py`) plus the Unity-GC liveness singleton finder from
`pogo_il2cpp.py`. Because script mode has no Python and no RPC host, `catch.js` absorbed *both*
halves of the desktop tool:

- **Self-finds its own singletons** (no pointers pushed in): `MapPlaceDirectoryService`,
  `MapAvatar`, `ItemBag` (via a working `GetItemCount`), `IapService` (stardust readout) — using
  the ported `il2cpp_stop_gc_world → il2cpp_unity_liveness_* → il2cpp_start_gc_world` walk.
- **Self-drives its own loop**: it hooks `CameraFollowingGround.LateUpdate` as a per-frame pump and
  gates every action on wall-clock milliseconds. **No `setInterval`/`setTimeout`** (those don't
  fire in gadget script mode — frida #2848), so a temporary `clock_gettime` interceptor bootstraps
  the install until the LateUpdate pump lands, then detaches.
- **Hard-codes its config** (rate 35 opens/min, 80 m range, ball floors 5, Excellent reticle
  0.02–0.12, re-throw on escape/miss, legendary skip) — identical catch quality to the desktop.

**Two controls (two levers, do not confuse them):**

| Lever | What it does | Effect | How |
|---|---|---|---|
| **Run-state toggle** (the home button) | Flips a marker file `catch.on` that `catch.js` polls (~1 s) | **Instant** ON/OFF, **no PoGo restart**. The pump just early-returns when OFF. | `catch_toggle` / `catch_on` / `catch_off` |
| **Mode swap** (panic / handoff) | Physically swaps the live gadget config between script and listen and **relaunches PoGo** | Autonomous ↔ desktop. A few seconds of downtime. | `pogo-catch-autonomous` / `pogo-catch-desktop`, or `restore.sh` |

**How it coexists with / replaces the desktop:** the gadget has exactly **one** mode per launch.
*Script* mode = `catch.js` runs in-process, the 27047 socket is closed (desktop **cannot** attach).
*Listen* mode = the gadget opens `127.0.0.1:27047` and runs no catch logic (desktop drives). Going
autonomous = swap the live `libgadget.config.so` to the script config and relaunch. Handing control
back = swap to the listen config and relaunch. The **first** switch to script mode force-stops PoGo
and severs the live desktop session, so you stop the desktop catcher first. (Per project memory PoGo
state is server-authoritative, so a mid-flight swap drops at most one in-flight throw.)

---

## 2. Deploy — EXACT steps, FROM THE PHONE

All on the phone, in Termux, root present. The installer **stages everything but does not flip the
live config** — so STEP 0–3 are safe to run even while the desktop catcher is attached. Only STEP 5
(go autonomous) is disruptive.

### Path A — seed `install.sh` by pasting it into Termux (no PC needed)

`install.sh` has `catch.js` embedded inside it (verified byte-identical, 842/842 lines), so you copy
**one** file and the catcher comes with it.

```sh
# --- STEP 0: BACK UP the gadget dir first (your rollback). ---
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'

# --- STEP 0b: READ THE GADGET VERSION (this is the #1 risk — see §3). ---
su -c 'strings /data/local/tmp/re.zyg.fri/libgadget.so | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+" | sort -uV | tail'
#   16.x  -> good.   17.x  -> script mode may silently no-op; have the 16.7.19 fallback ready (§3, §5).

# --- STEP 1: get install.sh onto the phone. ---
#   In Termux:   nano ~/install.sh
#   Paste the ENTIRE contents of:
#     C:\...\pogo_extract\system\ondevice_toggle\install.sh
#   Save & exit:  Ctrl-O, Enter, Ctrl-X
#   (Tip for a clean paste: `pkg install termux-api`, then on the PC pipe the file to your
#    clipboard and long-press -> Paste in nano. Or use Path B below.)

# --- STEP 2: run it. (Stages catch.js + both configs + pogo-catch.sh + the home buttons;
#             leaves the live config UNTOUCHED; leaves catching OFF.) ---
bash ~/install.sh
#   On success it prints "INSTALL COMPLETE" and the same STEP A–E you see below.

# --- STEP 3: install Termux:Widget (the home-button host). ---
#   It is NOT installed yet. Open F-Droid -> search "Termux:Widget" -> Install.
#   IT MUST COME FROM THE SAME SOURCE/SIGNATURE AS YOUR BASE TERMUX, or it will silently
#   refuse to run the shortcut scripts.  (F-Droid Termux + F-Droid Termux:Widget = matched.)
#   Open Termux:Widget once so Android registers it. (Optional: install Termux:API for the
#   toast feedback the buttons emit.)

# --- STEP 4: pin the button. ---
#   Long-press home screen -> Widgets -> Termux:Widget -> drop a 1x1 widget -> pick "catch_toggle".
#   (Optional extra widgets: catch_status, pogo-catch-desktop, pogo-catch-autonomous.)
#   The buttons live in ~/.shortcuts/ (top-level, where the widget reads them) — correct already.

# --- STEP 5: GO AUTONOMOUS (DISRUPTIVE — do this only when ready). ---
#   FIRST stop the desktop catcher on the PC. Then either tap the "pogo-catch-autonomous"
#   widget, or run:
su -c 'cp /data/local/tmp/re.zyg.fri/config.script.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1

# --- STEP 6: VERIFY it's actually running (the Frida-17 gate — see §3). ---
su -c 'logcat -s frida-catch'
#   Expect, in order:  [catch] init ... -> [catch] installed ... -> [catch] waiting ...
#                      -> [catch] READY — msvc=ok ... itembag=ok ... | Poke=N Great=N Ultra=N
#   SILENT while PoGo runs fine == Frida-17 no-op == do the 16.7.19 swap in §5.

# --- STEP 7: CATCH. Get PoGo onto the live map with spawns nearby, tap "catch_toggle".
#   Within ~1 s catch.js logs ">>> TOGGLE ON — catching" and starts throwing. Tap again = stop.
```

### Path B — one-time ADB push (use ONLY when the desktop is connected to the phone)

Faster and avoids a giant nano paste. **Still does not flip the live config** — it just lands the
files. Do this from the PC; it does not require stopping the desktop catcher (pushing files is
non-disruptive). The actual cutover is still STEP 5 above, run on the phone.

```powershell
# From the PC (PowerShell), with adb reaching the phone (USB, or Tailscale 100.98.158.56:5555):
$D = "C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\system\ondevice_toggle"

# 1) push the catcher + both configs into the gadget dir (push to /sdcard, then su-cp into place):
adb push "$D\catch.js"         /sdcard/catch.js
adb push "$D\config.script.so" /sdcard/config.script.so
adb push "$D\config.listen.so" /sdcard/config.listen.so
adb push "$D\configswap_toggle\pogo-catch.sh" /sdcard/pogo-catch.sh
adb push "$D\restore.sh"       /sdcard/restore.sh
adb shell su -c 'cp /sdcard/catch.js /sdcard/config.script.so /sdcard/config.listen.so /sdcard/pogo-catch.sh /sdcard/restore.sh /data/local/tmp/re.zyg.fri/'
adb shell su -c 'cd /data/local/tmp/re.zyg.fri && chmod 644 catch.js config.script.so config.listen.so && chmod 755 pogo-catch.sh restore.sh'

# 2) push the home-button scripts into Termux's shortcuts dir:
adb shell su -c 'mkdir -p /data/data/com.termux/files/home/.shortcuts'
foreach ($b in @("catch_toggle","catch_on","catch_off","catch_status","pogo-catch-desktop","pogo-catch-autonomous")) {
  # these six are emitted by install.sh; if you have them as files, push each. Otherwise just run
  # `bash install.sh` once on-device (Path A) to write them — it's the canonical source for the buttons.
}
#   Simplest: do the file pushes above for catch.js/configs, then run `bash ~/install.sh` once on
#   the phone — it is idempotent, re-stages identically, and writes the six buttons + perms for you.

# 3) Then continue with STEP 3 (Termux:Widget), STEP 4 (pin), STEP 5 (go autonomous), STEP 6 (verify)
#    from Path A — those are phone-side and identical.
```

> The ADB path is a **one-time convenience for seeding files** when a cable/Tailscale link exists.
> The system itself never needs ADB to *run* — that's the entire point. After seeding, the phone is
> fully self-sufficient.

---

## 3. On-device TEST checklist + the single most likely failure point

Run these **after** STEP 5 (autonomous mode), with PoGo open on the live map.

**Pre-flight (read-only, safe to run anytime, even while desktop is attached):**
```sh
su -c 'sh /data/local/tmp/re.zyg.fri/selftest.sh'
```
`selftest.sh` writes nothing into the gadget dir and never restarts PoGo. It checks paths, that
`catch.js` is valid + carries the load-bearing constructs, that both configs are correct
(`config.script.so` has `runtime:qjs`; `config.listen.so` has `127.0.0.1:27047`), derives the live
mode, and **sniffs the gadget version, warning loudly on Frida 17.x**. Exit 0 = ready.

**Live test checklist:**

1. `logcat -s frida-catch` shows `init → installed → waiting → READY` (not silent). ← gating check
2. `READY` line shows `msvc=ok … mapavatar=ok … itembag=ok` and non-zero `Poke=/Great=/Ultra=`
   ball counts (singleton self-find worked).
3. Tap `catch_toggle` (or `catch_on`) → log shows `>>> TOGGLE ON — catching`.
4. Stand near a spawn → log shows an `open` then a throw; on escape/miss it re-throws (≤4×, 2 s
   apart); on success/flee it moves on. Throws are Excellent-band; only spawns ≤80 m; legendaries
   skipped.
5. Tap `catch_toggle` again → `>>> TOGGLE OFF`; throwing stops within ~1 s; PoGo keeps running.
6. `catch_status` shows `ON/OFF` and a recent heartbeat age. *(If it reads "no heartbeat" but
   logcat shows activity, the app-uid is SELinux-denied writing `catch.hb` — harmless; logcat is the
   source of truth.)*
7. `pogo-catch-desktop` returns the gadget to listen and the desktop can attach on 27047 again.

### ⚠️ THE SINGLE MOST LIKELY FAILURE POINT — gadget is Frida 17.x

**Symptom:** after STEP 5, PoGo runs fine but `logcat -s frida-catch` is **completely silent** —
nothing throws, no `init` line. This is the documented Frida-17 "gadget script mode parsed-but-not-
executed" case (frida #3526/#3558/#3616/#3645). `catch.js` is gadget-version-agnostic and correct;
nothing in the file can mitigate this.

**Why it's the top risk:** the catcher itself is verified sound (catch mechanics are a bit-identical
port). The one thing outside `catch.js`'s control is whether *this device's gadget binary* executes
script mode at all, and the 17.x line is known to not.

**The fix — downgrade `libgadget.so` to a known-good 16.x arm64 gadget (e.g. 16.7.19):**
```sh
# Stage the 16.7.19 arm64 gadget into the dir first (NOT shipped here — see note below), then:
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'cp /data/local/tmp/re.zyg.fri/libgadget.so       /data/local/tmp/re.zyg.fri/libgadget.so.17.bak'
su -c 'cp /data/local/tmp/re.zyg.fri/libgadget.so.16.7.19 /data/local/tmp/re.zyg.fri/libgadget.so'
su -c 'chmod 644 /data/local/tmp/re.zyg.fri/libgadget.so'
# relaunch and re-run STEP 6.
monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1
```
**You must obtain `libgadget.so.16.7.19` (arm64-v8a) yourself** from the Frida 16.7.19 GitHub release
(`frida-gadget-16.7.19-android-arm64.so.xz`, decompress, rename) — it is **not** staged in this
folder. Run `STEP 0b` first; if the version is already 16.x, you will not hit this and can skip the
swap entirely.

---

## 4. Complete file manifest

Everything under `…\pogo_extract\system\ondevice_toggle\`:

| File | Purpose | Use it? |
|---|---|---|
| **`catch.js`** | THE catcher (842 lines). Self-finding, self-driving, self-toggling. The only file that must be byte-perfect. Carries the engine-readiness gate + heartbeat. | **YES — core** |
| **`install.sh`** | **The canonical installer** (1354 lines). Embeds catch.js, stages both configs + `pogo-catch.sh` + the six buttons, **leaves the live config untouched**, leaves catching OFF, prints the go-live steps. | **YES — run this** |
| **`config.script.so`** | Script-mode gadget config (`type:script` → catch.js, `runtime:qjs`). Copied onto `libgadget.config.so` to go autonomous. | YES |
| **`config.listen.so`** | Listen-mode config (`127.0.0.1:27047`). Byte-for-byte the device's original = restore-to-desktop source of truth. | YES |
| **`restore.sh`** | Safety-net (226 lines): forces the gadget back to listen mode with an embedded-JSON fallback, verifies the readback, removes the marker, relaunches PoGo. The true panic button. Run: `su -c '/data/local/tmp/re.zyg.fri/restore.sh'`. | YES — safety |
| **`selftest.sh`** | Read-only on-device sanity check (620 lines): paths, catch.js validity, config correctness, live mode, **Frida-version sniff**. Writes nothing. | YES — pre-flight |
| `configswap_toggle/pogo-catch.sh` | The atomic, idempotent, single-flight mode-swap driver `install.sh` installs into the gadget dir (`pogo-catch.sh on|off|toggle|status`). | YES (installed by install.sh) |
| `configswap_toggle/shortcuts/pogo-catch-{on,off,toggle,status}` | Reference copies of config-swap buttons. `install.sh` writes its own button bodies; these are for reading. | reference only |
| `shortcuts/catch_on.sh`, `catch_off.sh` | Standalone **config-swap** ON/OFF wrappers (relaunch PoGo). Reference / alternative; not what `install.sh` deploys (it deploys marker-file buttons of the same intent). | reference / optional |
| `shortcuts/pogo-catch-{on,off,toggle,status}` | Reference copies of the marker-file buttons. | reference only |
| `DEPLOY_commands.md` | Copy-paste deploy/restore/boot command sheet. **Caveat:** its STEP 0 says "17.x is FINE" and its STEP 1 heredoc writes a script config **missing `runtime:qjs`** — both stale. Prefer THIS file's §2; if you use the sheet, add `,"runtime":"qjs"}` to that heredoc. | reference (with caveat) |
| `TOGGLE_GUIDE.md` | Long-form operator guide. Accurate on mechanics; references a few not-yet-built extras (watchdog, boot script, 16.7.19 binary) as the target end-state. | reference |
| `termux_widget_setup.md` | Detailed Termux:Widget walkthrough (install, perms, custom icons, pin). **Note:** put buttons in **top-level `~/.shortcuts/`** (where `install.sh` writes them and where the 1×1 widget reads them), not `~/.shortcuts/tasks/`. | reference |
| `SAFETY_restore_persistence.md` | Safety analysis: restore-to-listen, the GC stop-world crash-isolation discussion (§2c), boot persistence, the Frida-17 question. | reference |
| `README.md` | Original folder readme. **Superseded by this file.** It recommends `install_ondevice_catcher.FULL.sh` ("Use this one") — do NOT; that one is stale and flips the live config at install time. | superseded |
| `install_ondevice_catcher.FULL.sh` | **DO NOT USE.** Older one-shot installer: embeds a **stale** catch.js (no engine-readiness gate, no heartbeat) AND **flips the live config to script mode during install** — which would sever the desktop catcher on the busy phone. | **NO** |
| `install_ondevice_catcher.sh` | **DO NOT USE.** Template form of the above (catch.js placeholdered). | **NO** |
| `libgadget.config.so` | A staged *script-mode* config blob (pretty-printed, == `config.script.so`). Not consumed by `install.sh` (which never copies it). Leftover; ignore. | ignore |
| `libgadget.config.script.so` / `libgadget.config.listen.so` | Orphan duplicate configs referenced by nothing. Safe to delete. | ignore |

> Cleanup is optional and out of scope for this deploy: the three orphan `libgadget.config*.so` blobs
> and the two `install_ondevice_catcher*.sh` files can be deleted without affecting `install.sh`.

---

## 5. Honest status + restore path

### Verified statically (local reads, syntax checks, source-diffs — no phone touched)
- **`catch.js` catch mechanics are a bit-identical 1:1 port** of `catch_loop_fast.py`: PokeballThrow
  struct (ball@+0x10, reticle 0.02+rand*0.10 @+0x14, +0x18=1, +0x19=1, +0x1a=0), data-driven ball
  pick (≥0.5 step-up, floors 5), re-throw on status 2/4 (≤4, 2 s), 80 m haversine range filter,
  legendary skip, 35 opens/min. Confirmed against the source line-by-line by multiple reviews.
- **Singleton self-find** (`livenessFind`) is a faithful port of `pogo_il2cpp.py:liveness_find_instances`
  (same `stopWorld → alloc → fromStatics → finalize → startWorld → freeStruct` order, with
  `startWorld` on the exception path); discriminators for all four singletons match the desktop driver.
- **Syntax/encoding:** `catch.js` passes `node --check` and is ES5/QuickJS-clean; all shell scripts
  pass `sh -n`/`bash -n` and are LF-only. `install.sh`'s embedded catch.js is `diff`-identical to the
  standalone file. Both configs parse as valid JSON; `config.script.so` has `runtime:qjs`;
  `config.listen.so` is the device's original listen config.
- **`install.sh` is self-contained and on-device-only** (no ADB/desktop/Python in its own path),
  idempotent, leaves the live config untouched, leaves catching OFF. The mode-swap (`pogo-catch.sh`),
  the standalone wrappers, and `restore.sh` all do atomic temp+`mv` swaps and reliably return control.

### NOT yet verified — needs a real on-device run
- **That the device's gadget actually executes script mode** (the Frida-17 gate, §3). This is the
  one thing static analysis cannot settle and the **most likely** thing to need the fallback.
- That all four singletons resolve on *this* modded ("Pokemod") build on the live map.
- That the PoGo app-uid can write `catch.hb`/`catch.log` into the shell-owned gadget dir (SELinux).
  If denied, status readout degrades but **catching is unaffected** (logcat is the source of truth).
- The minor robustness items reviewers flagged (none block the happy path): in-process liveness runs
  a brief stop-the-world from the render thread during cold-start setup (inherited from the desktop
  design; gated by the engine-readiness check); a wedged toggle lock can need a manual `rmdir`
  (the panic path `restore.sh` is lock-free and unaffected); `monkey` relaunch can occasionally flake
  (re-tap, or `am start`). Watchdog/boot-persistence are documented as a target but not built here.

### Restore path if anything goes wrong
1. **Hand control back to desktop (normal):** tap **`pogo-catch-desktop`**, or
   `su -c '/data/local/tmp/re.zyg.fri/restore.sh'` (verifies it landed on listen + relaunches).
   Or manually: `su -c 'cp …/config.listen.so …/libgadget.config.so'` → force-stop → relaunch.
2. **Script mode silent (Frida 17):** swap to the 16.7.19 arm64 gadget (§3) and re-verify.
3. **Anything weirder:** restore the whole gadget dir from your STEP 0 backup:
   `su -c 'rm -rf /data/local/tmp/re.zyg.fri && cp -a /data/local/tmp/re.zyg.fri.bak.<TS> /data/local/tmp/re.zyg.fri'`,
   then force-stop + relaunch PoGo. (Last resort below that: disable the ZygiskFrida Magisk module
   and reboot — PoGo then launches clean with no gadget at all.)

Because PoGo state is server-authoritative, any of these costs at most one in-flight throw.

---
*Built and verified entirely from local files (`catch_loop_fast.py`, `pogo_il2cpp.py`, and the
artifacts above) + web research. No phone interaction was performed. On-device deploy/test is the
human's coordinated step.*
