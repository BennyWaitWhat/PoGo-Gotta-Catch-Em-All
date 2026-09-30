# DEPLOY / RESTORE / PERSISTENCE commands — copy-paste sheet

DO NOT RUN NOW. The phone is busy (desktop catcher attached on port 27047). These are the exact
commands for the later coordinated deploy step. Run them in **Termux on the phone** (root present).
Everything is idempotent and safe to re-run. The catch.js referenced here is produced by the
sibling porting task; this sheet is the mode-switch / restore / boot wiring + safety net only.

Gadget dir on device: `/data/local/tmp/re.zyg.fri/`
PoGo package: `com.nianticlabs.pokemongo`

---

## STEP 0 — full backup + version check (do FIRST, before any change)
```sh
# whole-dir backup (timestamped) — your guaranteed rollback
su -c 'cp -a /data/local/tmp/re.zyg.fri /data/local/tmp/re.zyg.fri.bak.$(date +%s)'
su -c 'ls -la /data/local/tmp/re.zyg.fri.bak.*'

# read the gadget version (renamed .so -> not in filename, so dig it out of the binary)
su -c 'strings /data/local/tmp/re.zyg.fri/libgadget.so | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+" | sort -u | tail'
# >>> If version is 17.x: that is FINE for this script (pure-native, no Java bridge needed).
# >>> Cross-check the desktop frida client major matches (desktop: python -c "import frida; print(frida.__version__)").
```

## STEP 1 — stage the named configs + the script + the toggle flag
```sh
# snapshot the CURRENT (listen) config under a fixed name = your restore source of truth
su -c 'cp /data/local/tmp/re.zyg.fri/libgadget.config.so /data/local/tmp/re.zyg.fri/config.listen.so'

# write the SCRIPT-mode config (heredoc -> atomic, no editor)
su -c 'cat > /data/local/tmp/re.zyg.fri/config.script.so <<EOF
{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"reload"}}
EOF'

# (optional double-check: these two staged files match the ones in this repo dir
#  pogo_extract/system/ondevice_toggle/config.listen.so / config.script.so)

# place catch.js (pushed from desktop to /sdcard first, then moved into the gadget dir)
#   desktop:  adb push catch.js /sdcard/catch.js     # (NOT NOW — phone busy)
su -c 'cp /sdcard/catch.js /data/local/tmp/re.zyg.fri/catch.js'
su -c 'chmod 644 /data/local/tmp/re.zyg.fri/catch.js'

# initialise the ON/OFF toggle to OFF (safe default).
# IMPORTANT: catch.js uses a PRESENCE toggle — the marker FILE catch.on existing == ON,
# absent == OFF (it open()s the file; success=ON). It does NOT read file *contents*.
# So OFF = remove the marker; ON = create it. (Do not use an "echo 0 > RUN" content flag —
# that file is never read, and a present "RUN" containing 0 would still read as ON.)
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'

# verify staging
su -c 'ls -la /data/local/tmp/re.zyg.fri/'
su -c 'cat /data/local/tmp/re.zyg.fri/config.listen.so'
su -c 'cat /data/local/tmp/re.zyg.fri/config.script.so'
```

## STEP 2 — SWITCH TO AUTONOMOUS (script) MODE
```sh
# config is only re-read on PoGo process start, so swap then restart PoGo.
su -c 'cp /data/local/tmp/re.zyg.fri/config.script.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
# watch the on-device log the ported script writes:
su -c 'sh -c "tail -f /data/local/tmp/re.zyg.fri/catch.log"'    # Ctrl-C to stop tailing
```

## STEP 3 — drive the ON/OFF toggle (presence marker `catch.on`, no PoGo restart)
```sh
# catch.js polls the marker every ~1s via its LateUpdate pump (no gadget reload).
# ON  = marker exists; OFF = marker absent. chmod 666 so the PoGo app-uid can stat/open it.
su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'  # ON
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'                                                    # OFF
su -c '[ -f /data/local/tmp/re.zyg.fri/catch.on ] && echo ON || echo OFF'                            # state
# (These are exactly what the home-screen shortcuts pogo-catch-on / -off / -toggle run.)
```

## STEP 4 — push an updated catch.js WITHOUT restarting PoGo (uses on_change:"reload")
```sh
# ATOMIC update: write to .new then rename over, so the gadget's watcher never reads a half file.
#   desktop:  adb push catch.js /sdcard/catch.js.new      # (NOT NOW)
su -c 'cp /sdcard/catch.js.new /data/local/tmp/re.zyg.fri/catch.js.new'
su -c 'mv -f /data/local/tmp/re.zyg.fri/catch.js.new /data/local/tmp/re.zyg.fri/catch.js'
# gadget detects the change and reloads (init stage="late"); watch catch.log for the reload line.
```

---

## RESTORE-TO-LISTEN  (the panic button — hand desktop control back)
```sh
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'am force-stop com.nianticlabs.pokemongo'
su -c 'monkey -p com.nianticlabs.pokemongo -c android.intent.category.LAUNCHER 1'
# desktop can now attach again on 127.0.0.1:27047 (the existing pogo_il2cpp.py / catch_loop_fast.py).
```

## RECOVERY LADDER  (if PoGo won't launch or misbehaves after a switch)
```sh
# 1) fastest: go back to listen mode (above). Solves "bad script/config" 99% of the time.

# 2) stop surprise live-reloads while you fix catch.js: pin on_change to ignore
su -c 'cat > /data/local/tmp/re.zyg.fri/config.script.so <<EOF
{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"ignore"}}
EOF'
su -c 'cp /data/local/tmp/re.zyg.fri/config.script.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
# then force-stop+relaunch; script now loads ONCE, no watcher.

# 3) NUCLEAR: run PoGo with NO frida gadget at all (rename the .so aside)
su -c 'mv /data/local/tmp/re.zyg.fri/libgadget.so /data/local/tmp/re.zyg.fri/libgadget.so.bak'
su -c 'am force-stop com.nianticlabs.pokemongo'
# ...verify PoGo launches clean... then restore:
su -c 'mv /data/local/tmp/re.zyg.fri/libgadget.so.bak /data/local/tmp/re.zyg.fri/libgadget.so'

# 4) restore the whole dir from the STEP-0 backup
su -c 'rm -rf /data/local/tmp/re.zyg.fri && cp -a /data/local/tmp/re.zyg.fri.bak.<TS> /data/local/tmp/re.zyg.fri'

# 5) last resort: disable the ZygiskFrida Magisk module in Magisk app + reboot (fully removes frida).
```

---

## BOOT PERSISTENCE

### Note: catching already survives reboot with NO boot script
The ZygiskFrida module re-injects the gadget on every PoGo start (Zygisk), and the config file +
catch.js live on `/data/local/tmp` which persists across reboot. So if you leave the config in
`script` mode, **a reboot comes back autonomous on its own.** A boot script is only for enforcing a
*default state* or housekeeping.

### Recommended: Termux:Boot enforcing default-OFF (safe, cannot brick boot)
```sh
# one-time arm: open the Termux:Boot app once (F-Droid installed). It has no UI; opens+minimises.
# Also: Android Settings -> Apps -> Termux:Boot -> Battery -> Unrestricted (or it won't fire).
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/00-catcher-default-off <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
# boot SAFE: hand control to desktop (listen) and OFF; user opts in via the toggle.
su -c 'cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
su -c 'rm -f /data/local/tmp/re.zyg.fri/catch.on'   # marker absent => catching OFF
su -c 'sh -c "echo $(date +%s) boot-default-off >> /data/local/tmp/re.zyg.fri/boot.log"'
EOF
chmod +x ~/.termux/boot/00-catcher-default-off
# To instead boot DIRECTLY into autonomous catching, replace the listen cp with:
#   su -c 'cp /data/local/tmp/re.zyg.fri/config.script.so /data/local/tmp/re.zyg.fri/libgadget.config.so'
#   su -c 'touch /data/local/tmp/re.zyg.fri/catch.on && chmod 666 /data/local/tmp/re.zyg.fri/catch.on'  # auto-catch on boot
```

### Alternative (more deterministic, root, but CAN brick boot if wrong): Magisk service.d
```sh
# Use ONLY after the toggle is proven. service.d = late_start (correct stage). Runs as root, no su needed.
su -c 'cat > /data/adb/service.d/catcher-default-off.sh <<EOF
#!/system/bin/sh
sleep 20
cp /data/local/tmp/re.zyg.fri/config.listen.so /data/local/tmp/re.zyg.fri/libgadget.config.so
rm -f /data/local/tmp/re.zyg.fri/catch.on
echo \$(date +%s) magisk-boot >> /data/local/tmp/re.zyg.fri/boot.log
EOF'
su -c 'chmod +x /data/adb/service.d/catcher-default-off.sh'
# WARNING: a broken script here can hang boot -> requires recovery to delete. Keep it this trivial.
# Do NOT put this in post-fs-data.d (too early; setprop there deadlocks boot).
```

---

## QUICK REFERENCE — the two reversible state changes
| Action | Command (root) | Needs PoGo restart? |
|---|---|---|
| Autonomous ON (mode) | `cp config.script.so libgadget.config.so` + relaunch | yes |
| Desktop/listen (mode) | `cp config.listen.so libgadget.config.so` + relaunch | yes |
| Catch ON  (toggle)   | `touch catch.on && chmod 666 catch.on` | no |
| Catch OFF (toggle)   | `rm -f catch.on` | no |
| Update script        | `mv catch.js.new -> catch.js` (atomic) | no (auto-reload) |
| Neutralise frida     | `mv libgadget.so libgadget.so.bak` + relaunch | yes |
