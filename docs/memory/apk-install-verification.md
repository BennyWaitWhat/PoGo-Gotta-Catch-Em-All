---
name: apk-install-verification
description: "Before installing any third-party APK, verify version/size/SHA256 and show the user; APKMirror blocks automation."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

The user explicitly said "Be careful. Know which version is being installed." Before installing any APK pulled from a third-party mirror (APKMirror, APKPure, etc.), verify and SHOW the user up front: filename, exact byte size (must match the mirror's listed bytes), SHA256, ZIP magic bytes (`PK` at offset 0), and the target package's current versionName/versionCode (for reference). After install, show the reported versionName + versionCode and confirm it matches expectation. Use `adb install -r <apk>` (replacing is the default and keeps data). `-d` allows a downgrade only for debuggable packages on this user build, so a rollback to an older release versionCode will be refused — do not plan on reinstalling an older APK.

APKMirror blocks automated downloads behind Cloudflare — both `WebFetch` and `curl` get 403. Don't burn cycles automating against it: identify the exact variant page URL and hand it to the user with the expected filename/size/SHA, and let them drop the file where I can pick it up. (Chrome MCP can click through the interstitials, but the download still lands in the user's Downloads folder.)

**Why:** Installing the wrong build or a tampered APK on a rooted daily-driver phone is a real risk; the user wants to know exactly what's going on before anything is installed.

**How to apply:** Always present {filename, byte size, SHA256, target package/version} BEFORE install, and the reported {versionName, versionCode} after. Note: editing files in-place across nested shells (`bash` → `adb shell` → `su -c "..."` → `sed -i`) fails on quote-escaping — instead Read the file, construct the full new contents locally with the Write tool, `adb push` it, then `cp` into place via root. Relates to [[user-phone-setup]], [[feedback-git-bash-windows]].
