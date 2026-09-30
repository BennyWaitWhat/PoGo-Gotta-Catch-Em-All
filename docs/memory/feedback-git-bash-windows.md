---
name: feedback-git-bash-windows
description: On this Windows machine prefer PowerShell; Git Bash mangles Unix paths (MSYS) and lacks some Unix tools (zip).
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

This is a Windows machine and Git Bash here has two recurring failure modes the user has called out directly ("you keep fucking up with git bash, arent you learning anything?"):

1. **MSYS path translation mangles leading-slash paths.** `adb push C:\file /data/local/tmp/x` and `adb pull /product/media/bootanimation.zip` get rewritten to `C:/Program Files/Git/...` before adb sees them — the command reports success but the file lands at the wrong path. Same for any non-MSYS process (adb, ssh, scp, docker) given an absolute Unix path.
2. **Missing Unix tools.** `zip` is NOT installed in Git Bash on this machine (most others — grep, find, unzip, ssh — are present). Windows PowerShell 5.1's `Compress-Archive` always deflates; pwsh 7's `Compress-Archive -CompressionLevel NoCompression` writes STORED entries (verified 2026-09-20). A bootanimation.zip must be STORE-compressed, so never build one with 5.1's Compress-Archive.

**Why:** MSYS rewrites POSIX-looking paths to Windows paths by default, silently corrupting destinations; and the Git Bash install here is incomplete. These cost real time because the failure is silent (path) or only surfaces at invocation (missing tool).

**How to apply:** Default to the PowerShell tool for Windows-native work and for any `adb push`/`adb pull` with a Unix-style destination. If you must use Bash: prefix `MSYS_NO_PATHCONV=1` (or double-leading-slash `//data/...`) when passing absolute Unix paths to non-MSYS processes, and verify a Unix CLI exists with `which X` before invoking it. For STORE-compressed zips use Python `zipfile.ZIP_STORED` inline, or `7z -mx0` (7-Zip CLI is at `C:\Program Files\7-Zip\7z.exe`). Both Python 3.12 and 3.14 are installed. Relates to [[user-phone-setup]].
