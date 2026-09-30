---
name: phone-root-app-sources
description: "GitHub source map + update gotchas for the user's sideloaded root/Xposed apps and Magisk modules (for \"update my apps\" sessions)."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 55abb03b-c1ff-4b40-a786-4c18e7a40673
  modified: 2026-07-26T05:09:09.684Z
---

> **⛔ COMPATIBILITY GATE — read this before touching any host-hooking Xposed module (learned the hard way 2026-07-26).** A newer version number does NOT mean it works. WaEnhancer/InstaEclipse/NexAlloy each support a *specific range of HOST-APP versions*. The update procedure is: read the release **BODY** (not just `tag_name`) for the "Added support for WA x.y.z" line, compare against the **installed host-app version** (`dumpsys package com.whatsapp | grep versionName`), and only then decide. I once pulled the exact releases API, read only the tags, installed "the latest," and declared everything ✅ updated while WaEnhancer's core features were dead — the user found the error dialog I should have. **Never report an Xposed module as "updated/working" on version numbers alone; verify at the hook level (see AUDIT METHOD below).**
>
> **⚠️ NEVER tell the user to blanket-tap "Update all" in Play Store.** That's what pushes WhatsApp/Instagram past what the Xposed modules support and silently kills the hooks. Per-app auto-update for **com.whatsapp is already OFF** in Play (verified 2026-07-26 — the checkbox is unchecked; do NOT tap it, tapping ENABLES it). Keep it that way; update WhatsApp only after confirming WaEnhancer supports the target version.
>
> **AUDIT METHOD (hook-level ground truth, not guesses):**
> - Enabled modules + their scopes: pull the LSPosed config DB — `su -c "cp /data/adb/lspd/config/modules_config.db /data/local/tmp/mc.db"`, `su -c "chmod 644 ..."`, `adb pull`, then read with desktop Python `sqlite3` (tables `modules(mid,module_pkg_name,enabled)`, `scope(mid,app_pkg_name)`).
> - What's actually hooking vs failing: `su -c 'grep -i <module> /data/adb/lspd/log/modules_*.log'` (filename is timestamped — glob it). "Loading legacy module X" = injected OK; `E/LSPosed-Bridge java.lang.Exception: Unsupported version: <ver>` = broken.
> - Shell-quoting gotcha: a `|` inside a `grep -E` pattern passed through `adb shell su -c` gets re-parsed as a pipe by the device shell — use repeated `-e pat1 -e pat2` instead. And use **PowerShell** for any `/sdcard` or `/data` path ([[feedback-git-bash-windows]] — Git Bash mangles them; I re-hit this).

The user's sideloaded root/Xposed apps update from **GitHub releases only** (no store auto-updates them; `installerPackageName=null`). Store apps (Play/F-Droid) are the user's own to "Update all." See [[user-phone-setup]]. When asked to update apps, audit these repos' `releases/latest` via `api.github.com/repos/OWNER/REPO/releases/latest`, then download → **verify SHA256 & show user** ([[apk-install-verification]]) → `adb -s 100.98.158.56:5555 install -r <apk>` (keeps data + LSPosed scope) → for modules `su -c "magisk --install-module <zip>"` + reboot.

**Sideloaded APK apps → repo (package):**
- WaEnhancer (com.wmods.wppenhacer) → **Dev4Mod/WaEnhancer**. Runs NIGHTLY DEV builds — tags are `<ver>-<commithash>` (e.g. `1.5.5-deb58e60`); the top release by date IS the newest build. Xposed hook on WhatsApp.
- InstaEclipse (ps.reso.instaeclipse) → **ReSo7200/InstaEclipse** (author "ReSo"). Xposed hook on Instagram. The `Xposed-Modules-Repo/ps.reso.instaeclipse` store MIRROR LAGS — never use it (would downgrade). Being succeeded by a "Purrfect" project eventually.
- ReVanced-Xposed (io.github.chsbuffer.revancedxposed) → **REBRANDED to NexAlloy/NexAlloy** (old `chsbuffer/ReVancedXposed` redirects; assets renamed `NexAlloy-*.apk`). This is what the `NexAlloy-*.apk` files in the project folder are.
- DisableFlagSecure (io.github.lsposed.disableflagsecure) → **LSPosed/DisableFlagSecure**.
- HideMockLocation (io.github.auag0.hidemocklocation) → **auag0/HideMockLocation** — latest 2.3.1. **NOT archived** — verified 2026-07-26 via GitHub API (`archived:false`, 11 open issues, updated 2026-07-25); an earlier audit agent claimed "archived" and that was WRONG (don't repeat it). Its LSPosed-store mirror IS older (2.3.0) — never update via the module store (downgrade). README claims support only through Android 16 (no A17 mention).
- Telegram (org.telegram.messenger.web) → **telegram.org/dl/android/apk** — the DIRECT-DOWNLOAD build, NOT the Play build, so Play will never update it (silent-gap risk; check it every audit). The URL 302s to a `cdn4.telesco.pe` token URL: downloads TRUNCATE silently (got 0.25 MB once) — always `curl.exe -sL --retry 3 --retry-all-errors` and verify bytes against the redirect's Content-Length (~82.7 MB) + that it opens as a zip before installing.
- iPogo (app.ipogo.android.launcher) → **ipogo.app/install.php** → `ipogo-launcher-<ver>.apk` is the ROOTED-LAUNCHER variant that matches this package (plain `ipogo-<ver>.apk` is the other variant — don't cross-install).
- PoGoPIP (io.github.auag0.pokegopip) → **auag0/PokeGOPiP** — NOTE: this is Pokémon-GO **Picture-in-Picture** (floating window), NOT a Play-Integrity patch despite the name.
- EnableVoLTE (dev.bluehouse.enablevolte) → **kyujin-cho/pixel-volte-patch** — a Shizuku/root app (NOT Xposed) that writes carrier config; tag has no `v` prefix.
- Public Compute Services (com.kieronquinn.app.pcs) → **KieronQuinn/PublicComputeServices** — Xposed mod that fetches Pixel AI models.
- AdAway (org.adaway) → **AdAway/AdAway** (sideloaded here; slow release cadence).
- SAI (com.aefyr.sai) → **Aefyr/SAI** — GitHub FROZEN at 4.5 since 2021; any newer build is Play/F-Droid only.

**Magisk modules → repo (fork identity matters — don't cross-flash):**
- playintegrityfix → **KOWX712/PlayIntegrityFix** (the `-inject-s` line; chiteroman orig discontinued). NOT osm0sis/PlayIntegrityFork (separate line at v17). Flashing v4.7 / v4.7-1 (the current release, installed) MOVES a custom `/data/adb/pif.prop` to `pif.prop.old` (customize.sh "Backup custom pif.prop"), reverting to the module's bundled default; upstream removed that on 2026-07-20 (commit ea93222c), so a release after v4.7-1 should keep it. After any PIF flash, check for a fresh `pif.prop.old`; if the custom file moved, re-run `autopif.sh` (see [[user-phone-setup]]).
- zygisk_shamiko → **LSPosed/LSPosed.github.io** releases (Shamiko).
- zygisk_vector (LSPosed) → **JingMatrix/Vector** (renamed from JingMatrix/LSPosed at v2.0; this is the LSPosed fork the user runs).
- zygiskfrida → **lico-n/ZygiskFrida**.
- com.chiller3.bcr (BCR call recorder) → **chenxiaolong/BCR** (v3.x scheme, flashable zip).
- Magisk → **topjohnwu/Magisk** (on 30.7 = latest stable as of 2026-07).

**Store-owned (user's Play/F-Droid "Update all"):** IntegrityCheck (Play), AirGuard (Play), WiGLE (Play), Shizuku (Play/pkginstaller), SD Maid SE (F-Droid), + ~140 normal apps.

**2026-07-25 update session applied:** WaEnhancer→1.5.5, InstaEclipse→0.6.0, PCS→1.0.5, PlayIntegrityFix→v4.7-inject-s, BCR→v3.5. Verified active across a cold reboot. Everything else already current. After Xposed APK `-r` updates the LSPosed scope persists; a reboot reloads the hooks (force-stop the target app otherwise).
