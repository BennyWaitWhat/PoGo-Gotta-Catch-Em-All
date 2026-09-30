---
name: reference-frida17-java-bridge
description: "Frida 17 removed the Java global — bundle frida-java-bridge with frida-compile (on Windows); on-device Frida = ZygiskFrida gadget + Termux frida-python 17.9.11, no frida-server/frida-inject"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 23479c7f-0c89-4422-8b89-8816a5d0591b
---

The phone's Frida is **17.9.11**, which **removed the `Java` (and `ObjC`) global** from the runtime. A raw script using `Java.use(...)` dies instantly with `ReferenceError: 'Java' is not defined` (and `require` is also undefined — the frida-inject runtime is bare QuickJS with only native prims: Interceptor, Module, Memory, NativePointer…).

To hook Java/framework methods you must **bundle the bridge**:
1. Write `agent.js` with `import Java from 'frida-java-bridge';`
2. Windows has `frida-compile` at `C:\Program Files\Python314\Scripts\frida-compile.exe` (+ node v24, frida-tools 14.8.2). In the temp dir: `npm install frida-java-bridge --no-save`, then `frida-compile agent.js -o out.js` (yields a ~700KB self-contained bundle).
3. Push `out.js` and inject.

**On-device Frida (2026-09-20):** the ZygiskFrida v1.9.0 gadget (`/data/local/tmp/re.zyg.fri/libgadget.so`, listening on `127.0.0.1:27047` inside PoGo) + Termux **frida-python 17.9.11**, whose local device does the injecting (run `/data/local/tmp/frida_selinux_patch` once per boot before injecting into app processes). `/data/local/tmp` holds no `frida-server`, `frida-inject` or `frida-gadget.so`. Pokemod's own renamed frida-inject lives at `/data/user/0/com.pokemod.app.public/files/injector/pokemod-injector` (Pokemod's; rewritten every launch).

**Gotchas:**
- `adb push` to `/data/local/tmp/...` via **Git Bash mangles the path** to `C:/Program Files/Git/...` — use PowerShell for adb push (consistent with [[feedback-git-bash-windows]]).
- `frida-inject -p PID -s script` holds the session open; backgrounding via `adb shell "... &"` hangs unless you `setsid ... </dev/null >log 2>&1 &`. It's per-PID and dies on detach — not persistent (use Termux/ZygiskFrida for that).
- Targeting GPS Joystick: hook the **`:overlay`** process (PID via `ps -A | grep 'fakegpsjoystick:overlay$'`), not main — that's where `LocationManager.setTestProviderLocation` is called. See [[project-pogo-spoof-stack]] and [[pogo-frida-stability]].
