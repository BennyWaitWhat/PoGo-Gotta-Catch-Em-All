# TERMUX_SETUP.md — one-time Termux setup for the PRIMARY autonomous catcher (Termux-attach)

This is the setup for the **recommended** way to make the phone catch on its own: run the
**proven** desktop catcher *on the phone* in Termux, attaching to the in-process Frida gadget's
**local listen socket** `127.0.0.1:27047`. It sidesteps QuickJS gadget *script* mode (the
`catch.js` path that native-faulted) entirely and reuses `catch_loop_fast.py` + `pogo_il2cpp.py`
byte-for-byte — the off-thread GC-liveness architecture that has never crashed PoGo.

> **Scope.** This file is *only* the Termux-attach path: install Python + frida, seed the proven
> tree, run the launcher, and (optionally) a home-screen ON/OFF button that **starts/stops a Python
> process** (no config swap, no marker file). The separate `termux_widget_setup.md` covers the
> heavier *script-mode* `catch.js` widget — a different mechanism. Use this one first.

The launcher this doc drives: **`termux_run_catcher.sh`** (sibling of this file), which calls
**`termux_catch.py`**, which runs the proven catcher.

---

## 0. Prerequisites (already true on this device — confirm, don't redo)

| # | Requirement | Why |
|---|---|---|
| 0.1 | **Termux + Termux:API installed from F-Droid** (same signing key). | `pkg`, plus `termux-wake-lock` / `termux-toast` for a stable background run and tap feedback. |
| 0.2 | **Root (Magisk) granted to Termux.** | The launcher runs one `su -c` to set the gadget to listen mode. The catcher itself needs no root — it just connects to a loopback socket. |
| 0.3 | **The ZygiskFrida gadget is deployed** at `/data/local/tmp/re.zyg.fri/` with `config.listen.so`, `libgadget.config.so`, `libgadget.so`. | The attach target. The launcher ensures listen mode using the staged `config.listen.so`. |
| 0.4 | **Termux:Widget from F-Droid** (only if you want the home-screen button in §5). | Draws the 1×1 launch/stop icons. |

Device facts this is written for: rooted **Pixel 9 Pro, Android 16**, gadget = **Frida 17.x fork**
(internal `200046.1.1`). The "17.x" matters a lot for the frida client version below.

---

## 1. Install Python

```sh
pkg update
pkg install python
```

Confirm:

```sh
python --version          # expect Python 3.x
pip --version
```

---

## 2. Install the `frida` client in Termux — **the one tricky step**

The launcher attaches with the **frida Python bindings**, and **their MAJOR must equal the
gadget's** (the device gadget is a **17.x** fork — a 16.x client will refuse to attach with a
version-mismatch error). The complication: **PyPI does not publish prebuilt `frida` wheels for
Termux's platform** (`aarch64` + `linux-android`), so a bare `pip install frida` usually tries to
**compile from source and fails** (no Rust/native toolchain, or it pulls a too-new major). Pick the
first path that works:

### 2a. Fast path — try the package/index first

```sh
# Some Termux setups already resolve a usable wheel from the community index:
pip install frida
python -c 'import frida; print("frida", frida.__version__)'
```

- If it prints **`frida 17.x`** → **done, skip to §3.**
- If it prints a **non-17** major → uninstall and pin 17 in §2b.
- If it **errors while building** (gcc/rust/meson/"Building wheel for frida … failed") → §2b.

> Do **not** "fix" a build failure by installing random build tools and compiling frida from
> source in Termux — that path is long and fragile. Install a **prebuilt** binding instead (§2b).

### 2b. Reliable path — install a prebuilt 17.x binding

The robust source of prebuilt frida bindings for Android/aarch64 is the project's **GitHub
releases**. You want the **`frida` Python wheel** built for **Android aarch64**, matching your
Python minor (e.g. cp312 for Python 3.12) — and at a **17.x** version to match the gadget.

```sh
# 1) See your Python minor (e.g. 3.12 -> cp312) and uninstall any wrong frida:
python -c 'import sys; print("cp%d%d" % sys.version_info[:2])'
pip uninstall -y frida frida-tools 2>/dev/null

# 2) Browse the frida releases for an aarch64 *android* wheel at a 17.x tag:
#    https://github.com/frida/frida/releases
#    Pick the asset shaped like:
#       frida-17.<minor>.<patch>-cp<XY>-cp<XY>-android_aarch64.whl
#    (cp<XY> = your Python minor from step 1; android_aarch64 = this device.)
#
# 3) Install it directly by URL (no compiler needed — it's prebuilt):
pip install https://github.com/frida/frida/releases/download/17.<minor>.<patch>/frida-17.<minor>.<patch>-cp<XY>-cp<XY>-android_aarch64.whl
```

Replace `<minor>.<patch>` and `cp<XY>` with the real release/Python values. Then verify:

```sh
python -c 'import frida; print("frida", frida.__version__)'      # MUST be 17.x
```

**If no `android_aarch64` wheel exists for your exact Python minor at a 17.x tag:**

- **Match Python to an available wheel.** Termux can install older/newer Python minors; pick the
  one a 17.x `android_aarch64` wheel exists for, then redo §1's import check. This is usually the
  shortest fix.
- **Last resort — match the desktop client's 17.x version exactly** (`pip show frida` on the PC
  gives it), to remove any doubt about the major. The launcher prints both the client version and a
  warning if it isn't 17.x, so you'll see a mismatch immediately on first run.

> **Why not frida-server instead?** You don't need it. The gadget is *already injected* into PoGo
> and, in listen mode, exposes a loopback socket. The Termux client connects to that socket as a
> remote device (`add_remote_device('127.0.0.1:27047')`) — no `frida-server`, no `adb`,
> no `adb forward` (the socket is already on this device's loopback). Only the **frida Python
> bindings** are required in Termux.

(`frida-tools` — the `frida`/`frida-ps` CLIs — is **optional**; the launcher uses only the bindings.
Install it the same way if you want CLI diagnostics: `pip install frida-tools`.)

---

## 3. Seed the proven `pogo_extract` tree onto the phone

`termux_catch.py` imports the proven sources by **relative layout**, so the directory shape must be
preserved. Minimum files (you can copy the whole `pogo_extract` tree, but these are what's loaded):

```
<ROOT>/pogo_il2cpp.py
<ROOT>/system/scripts/game_write/catch_loop_fast.py
<ROOT>/system/ondevice_toggle/termux_catch.py
<ROOT>/system/ondevice_toggle/termux_run_catcher.sh   ← the launcher
<ROOT>/system/ondevice_toggle/TERMUX_SETUP.md          ← this file
```

`<ROOT>` is auto-resolved as **two directories up** from `system/ondevice_toggle/`. Pick a location:

- **Recommended (no SD-card permission quirks): inside Termux's home.**
  ```sh
  # From the PC over adb, push into Termux-visible storage, then move into $HOME:
  #   adb push pogo_extract /sdcard/pogo_extract
  # Then in Termux:
  termux-setup-storage          # one-time: grants ~/storage symlinks (answer the prompt)
  cp -a ~/storage/shared/pogo_extract ~/pogo_extract
  ```
  Launcher path becomes: `~/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh`

- **Or run straight from `/sdcard`** (simpler, but `/sdcard` is a FUSE mount; fine for reading .py):
  ```sh
  termux-setup-storage
  POGO_ROOT=/sdcard/pogo_extract \
    sh ~/storage/shared/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh
  ```
  If `import` ever misbehaves on the FUSE mount, copy into `$HOME` as above. `POGO_ROOT` overrides
  the auto-resolved ROOT for any odd placement.

Make the launcher executable (optional; `sh <path>` works regardless):

```sh
chmod +x ~/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh
```

---

## 4. Run it (the single shot)

```sh
# 1) Foreground PoGo on the LIVE MAP first (avatar + spawns visible). Keep it foreground.
# 2) In Termux:
sh ~/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh
```

What it does, in order: ensures the gadget is in **listen** mode (relaunching PoGo only if it was
in script mode), takes a **wake-lock**, then runs `termux_catch.py` → the proven catcher.

**Success looks like (stdout):**

```
HH:MM:SS frida client : 17.x.x  (gadget is a 17.x fork; majors must match)
HH:MM:SS gadget mode  : MODE=LISTEN already
=== Termux-attach catcher ===
ROOT      : /data/data/com.termux/files/home/pogo_extract
gadget    : 127.0.0.1:27047 (listen mode required)
...
connected pid=<PID> | Poke=.. Great=.. Ultra=.. | Stardust=.. | msvc=ok avatar=ok iap=ok
run <s>s | now <dust> dust ... | fired=.. | caught=.. esc=.. flee=.. miss=.. | q=.. ...
```

Stand near a spawn → an `open`, then an Excellent throw; escapes re-throw (≤4, 2 s apart);
legendaries skipped; box stays empty (auto-transfer); stardust ticks up each ~10 s report.
**There must be NO `frida-catch` native faults in logcat** — no `catch.js` is loaded on this path.

**Stop:** `Ctrl-C` (releases the wake-lock; PoGo keeps running; the desktop can attach on 27047
afterwards). Nothing to restore — no config was changed and no marker written.

If you're comfortable keeping a Termux process alive with the wake-lock, **you're done** — this is
reliable autonomy. To also survive reboot, add the launcher to **Termux:Boot** (`~/.termux/boot/`),
same as the existing boot scripts.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `the frida python module is not importable` | frida not installed in Termux | §2 (install a **17.x** binding) |
| frida client version warning (not 17.x) | major mismatch with the gadget | §2b — install/pin a **17.x** wheel |
| `... down/unreachable` / can't connect to 27047 | gadget in **script** mode, or PoGo not up | Launcher auto-switches to listen + relaunches; if you used `--no-relaunch`, drop it. Then foreground PoGo. |
| `gadget listen socket exposes no process` | PoGo not running (or still starting) | Launch/foreground PoGo on the map, then re-run. |
| attaches but `caught=0`, dust flat | not near a spawn / out of range | Stand within ~80 m of a visible spawn; watch a few reports. |
| `a Termux catcher ... is already running` | a prior instance is live | That's the OFF case — `pkill -f termux_catch.py`, then relaunch. |

---

## 5. (Optional) Home-screen ON/OFF buttons (Termux:Widget)

For this path, **ON = start the launcher**, **OFF = stop the Python process** (no config swap,
no marker file). Termux:Widget runs any executable script in `~/.shortcuts/`.

**5.1 Create the shortcut dir and two scripts (in Termux):**

```sh
mkdir -p ~/.shortcuts
chmod 700 ~/.shortcuts ~ 2>/dev/null     # widget refuses world-readable script dirs
```

Create **`~/.shortcuts/pogo-attach-on`** — start the catcher (kept in the foreground of a Termux
session the widget spawns; the wake-lock keeps it alive when the screen is off):

```sh
cat > ~/.shortcuts/pogo-attach-on <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# ON = launch the Termux-attach catcher (PRIMARY autonomous path).
L=$HOME/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh
[ -f "$L" ] || L=/sdcard/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh
if pgrep -f 'termux_catch\.py' >/dev/null 2>&1; then
  command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "catcher already ON"
  exit 0
fi
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo catcher: starting…"
exec sh "$L"
EOF
chmod +x ~/.shortcuts/pogo-attach-on
```

Create **`~/.shortcuts/pogo-attach-off`** — stop it and release the wake-lock:

```sh
cat > ~/.shortcuts/pogo-attach-off <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# OFF = stop the Termux-attach catcher. Kills the python process by module name;
# Ctrl-C's handler in the launcher also releases the wake-lock, but we belt-and-
# suspenders it here in case OFF kills the script before its trap runs.
pkill -f 'termux_catch\.py' 2>/dev/null
pkill -f 'termux_run_catcher\.sh' 2>/dev/null
command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo catcher: OFF"
EOF
chmod +x ~/.shortcuts/pogo-attach-off
```

**5.2 Register + place the widget:**

1. Open **Termux:Widget** once from the app drawer (first launch registers it with the system).
2. Long-press the home screen → **Widgets** → **Termux:Widget** → drop the **1×1 shortcut** widget.
3. When it asks which script, pick **`pogo-attach-on`**. Repeat for a second 1×1 → **`pogo-attach-off`**.
4. (Pixel Launcher) you can pin each as an app-style icon and rename to "Catch ON" / "Catch OFF".

**Behavior:** tap **ON** → toast "starting…", the gadget is set to listen (PoGo relaunches if it
was in script mode — **foreground it on the map**), wake-lock taken, catcher runs. Tap **OFF** →
process killed, wake-lock released, toast "OFF". `pogo-attach-on` is idempotent (double-tap = no-op
while already running).

> The widget-launched session ends if you fully swap Termux away *and* the OS reclaims it; the
> **wake-lock** is what prevents doze from suspending it. For maximum durability run it from an open
> Termux session (or add Termux:Boot), not only from a quick widget tap.

---

## TL;DR

```sh
pkg install python
pip install frida          # MUST end up 17.x — see §2b if pip builds/installs the wrong one
termux-setup-storage
cp -a ~/storage/shared/pogo_extract ~/pogo_extract          # or run from /sdcard with POGO_ROOT=
# foreground PoGo on the live map, then:
sh ~/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh
# stop:  Ctrl-C   |   OFF button: pkill -f termux_catch.py
```
