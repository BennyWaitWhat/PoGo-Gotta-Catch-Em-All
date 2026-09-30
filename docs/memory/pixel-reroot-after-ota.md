---
name: pixel-reroot-after-ota
description: "Recover root on the Pixel 9 Pro after an OTA wiped it — fast init_boot extraction, on-device CLI patch, fastboot flash. Verified on the Android 17 upgrade."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9e97229e-bbef-4f0b-940e-b84b513b701e
  modified: 2026-09-19T00:16:33.590Z
---

**Symptom:** user takes an OTA on the rooted Pixel 9 Pro and root is gone (`su: inaccessible or not found`, no magiskd, Magisk *app* still installed). Verified 2026-09-18 on the Android 16 → 17 jump (`CP1A.260505.005` → `CP2A.260705.006`).

**Cause:** the OTA installs to the INACTIVE slot and boots it. That slot's `init_boot` is stock. Magisk's patch lived on the old slot. The tell is **the slot flipped** (`ro.boot.slot_suffix` `_b` → `_a`). The Magisk flow that prevents it is *Uninstall → Restore Images → take OTA → **Install to Inactive Slot** → reboot*; skipping the last step is what loses root.

**Nothing is lost.** `/data` survives, the bootloader stays unlocked, all module configs in `/data/adb` persist (`/data/adb` returning *Permission denied* rather than *No such file* confirms it's intact). Re-rooting is only a re-patch of `init_boot` — **never** re-lock/unlock (that wipes).

**Once root is gone, PIF stops spoofing, so `getprop` finally tells the truth:** `ro.boot.flash.locked=0`, `verifiedbootstate=orange`, `vbmeta.device_state=unlocked`. (While rooted, `flash.locked` reads `1` — a PIF spoof, see [[user-phone-setup]].)

## Recovery procedure (whole thing ~5 min, no GUI taps)

1. **Get the stock `init_boot.img` for the EXACT build.** Pixel 9 Pro patches **`init_boot`**, not `boot`.
   - `fastboot fetch init_boot` does **NOT** work — `remote: 'Fetching restricted partition: init_boot_a is not allowed'`. Don't waste time on it.
   - Factory-image page is JS-gated; `curl` returns a ~2 KB shell with zero links. **Use the browser pane** and `document.querySelectorAll('a[href*="dl.google.com/dl/android/aosp/caiman"]')` to get the real URL.
   - **Don't download the 4.3 GB zip.** Range-read it: the outer zip stores `image-caiman-*.zip` with `compress_type=0` (STORED), so you can window into it and open the nested zip over HTTP Range and pull only `init_boot.img`. Script: `C:\Users\Blanco\AppData\Local\Temp\claude\C--Users-Blanco-Desktop-Claude-Operations-Phone-Maintenance\9e97229e-bbef-4f0b-940e-b84b513b701e\scratchpad\grab_init_boot.py` (set its `URL`/`OUT` constants per build). **Pulled 2.35 MB instead of 4.3 GB.** Needs ZIP64 handling — Python's `zipfile` over a seekable Range-backed file object handles it for free.
2. **Patch it on-device with Magisk's CLI — no app taps needed.** The Magisk APK contains everything: `unzip -j <apk> 'lib/arm64-v8a/*' 'assets/boot_patch.sh' 'assets/util_functions.sh' 'assets/stub.apk'` into `/data/local/tmp/mpatch`, strip the `lib`/`.so` affixes (`libmagiskboot.so` → `magiskboot`), `chmod 755`, then `KEEPVERITY=true KEEPFORCEENCRYPT=true PATCHVBMETAFLAG=false RECOVERYMODE=false sh ./boot_patch.sh init_boot.img` → produces `new-boot.img`. Shell user CAN exec from `/data/local/tmp`; no root required for this step. Confirm the repack prints the right `OS_VERSION` / `OS_PATCH_LEVEL`.
3. **Flash:** `adb reboot bootloader` → verify `current-slot` and `unlocked: yes` → `fastboot -s <serial> flash init_boot new-boot.img` (writes the ACTIVE slot only) → `fastboot reboot`. Boots in ~60 s.
4. Keep BOTH images (`init_boot_<build>.img` stock + `magisk_patched_<build>.img`) in `ota_prep/` — the stock one is the instant bootloop undo.

## BETTER: do "Install to Inactive Slot" YOURSELF, headlessly (verified 2026-09-18)
You do **not** need the Magisk GUI and you do **not** need to lose root at all. While the OLD system is still booted and rooted, after the OTA finishes:
1. **Read the OTA's real target build first — never assume.** `cat /data/ota_package/metadata` → `post-build=google/caiman/caiman:17/<BUILD>/...` + `post-security-patch-level`. (I nearly patched the September build when the staged OTA was actually August.)
2. **WAIT for `onStatusUpdate: (6, …)` = UPDATED_NEED_REBOOT.** Statuses: 3=downloading, 4=verifying, 5=finalizing, 6=done. Patching before verification finishes makes the hash check fail and **aborts the user's update**. Filter logs on `update_engine|UpdateEngineDelegate` only — a loose `ErrorCode` grep false-positives on unrelated Firebase/`FA-SVC` network errors.
3. Range-extract + `boot_patch.sh` the NEW build's `init_boot` (steps 1–2 above).
4. `dd` it onto the INACTIVE slot: `/dev/block/by-name/init_boot_<other-slot>`.
   **THE BLOCKER: the staged slot is READ-ONLY at the block layer** — `dd` gives `write error: Operation not permitted` even as root, and it is NOT SELinux (no avc denial; `/sys/block/sda/sdaNN/ro` reads `1`). `echo 0 > /sys/.../ro` is itself Permission denied; **`blockdev --setrw /dev/block/sdaNN` WORKS.** Then dd, then `sync`.
5. Verify by hash, not by vibes: `dd if=/dev/block/by-name/init_boot_a|_b bs=1M count=8 | sha256sum` must equal your patched file's sha256. Confirmed the OTA had already written stock init_boot to the inactive slot, and its hash matched the factory-zip extraction byte-for-byte — good cross-check that the extraction was correct.
6. Reboot normally. Root survives; no fastboot, no data risk.

**NEVER flash an init_boot from a different build** (e.g. the leftover A16 `init_boot__a_patched.img`) — ramdisk/OS mismatch.

## POWERSHELL TRAP THAT COST A CYCLE
**PowerShell variables are CASE-INSENSITIVE.** A loop using `$d = (fastboot devices)` silently clobbered the serial in `$D`, so fastboot sat forever on `< waiting for "4A181FDAP0013G\t fastboot">` and the flash never ran. Use distinct names (`$SER`, `$fblist`) — never `$d`/`$D` in the same script.

## Remote access dies with the OTA
Port 5555 comes back *actively refused* — wireless ADB does not survive a major OS upgrade. Termux sshd (port **8022**, `Host pixel` in `~/.ssh/config`, user `u0_a762`) stays listening but **resets at kex** (`kex_exchange_identification: Connection reset`) — `sshd-session` could not link `libgssapi_krb5.so.2`, a symlink the app SELinux domain cannot read; fix = convert the symlinks to hardlinks (see [[pogo-on-phone-catcher]]). A port sweep found the wireless-debugging daemon (random high port, e.g. 41461) but it reports `offline` because that mode needs a **pairing code**, a separate trust store from `adb tcpip`. **Conclusion: after a major OS update you need USB once.** Ask for it immediately instead of burning time on remote paths.

## Android 17 stack verdict (all verified working 2026-09-18)
Magisk **30.7** roots A17 fine. **Vector v2.2 (3080)** works — `vectord` runs (check `ps -A`, NOT `pgrep`, which gave a false NO). **Shamiko 1.2.5 (414)** works (`😋 Shamiko is working as blacklist mode`). **PIF v4.7-1**, **ZygiskFrida v1.9.0**, **BCR**, hosts, tether_noprov, wifi_wardriver all load. Zygisk injects (`grep -c zygisk /proc/<pid>/maps` on a NON-denylisted app — denylisted ones correctly show 0). All settings survived: `denylist=0`, 119 denylist entries, 13 su policies.
