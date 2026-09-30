# Termux:Widget setup — home-screen ON/OFF buttons for the on-device PoGo auto-catcher

Goal of this file: turn the catcher's ON/OFF (and the desktop-handoff) controls into
**home-screen icons that look and behave like app icons** — one tap = catch ON, one tap = OFF.
Everything is done **on the phone**, no PC. The catcher itself (`catch.js`, the gadget config
swap, the watchdog) is documented elsewhere; this file is **only** the Termux:Widget half.

> Nothing here touches the phone now — the phone is busy (a desktop catcher is attached on
> `127.0.0.1:27047`). These are the exact steps + commands for the later, coordinated deploy.

**What the buttons actually do (the seam):** the everyday ON/OFF button just creates or deletes a
single 0-byte **marker file** `/data/local/tmp/re.zyg.fri/catch.on`. `catch.js` (already loaded in
the PoGo process in gadget *script* mode) polls that file about once a second in its `manage()`
pass (`toggleOn()` → `new File('/data/local/tmp/re.zyg.fri/catch.on','r')`): **file present = catching
ON, file absent = OFF**, with no PoGo restart and no Frida re-attach. The button is `touch`/`rm` as
root, nothing more. (Verified against `catch.js` lines 42–43, 547–548, 659 and the shipped
`shortcuts/pogo-catch-toggle`.)

There is a **second, heavier control** for handing the phone back to the desktop catcher: the
`pogo-catch-desktop` / `pogo-catch-autonomous` buttons, which swap the gadget mode
(`script` ↔ `listen`) via `configswap_toggle/pogo-catch.sh` and relaunch PoGo. Those are mode
buttons (≈10–20 s, restart). The marker button is the instant everyday one.

---

## 0. Prerequisites (one-time, you do these by hand)

| # | Requirement | Why |
|---|---|---|
| 0.1 | **Base Termux is installed from F-Droid** (already true on this device). | Add-ons must share the **same signing key** as base Termux. A Play-Store Termux + F-Droid widget (or vice-versa) silently refuses to run scripts. |
| 0.2 | **Termux:API** installed (already true). | Provides `termux-toast` so a home tap gives you visible "auto-catch: ON/OFF" feedback. |
| 0.3 | **Termux:Boot** installed (already true). | Not used by the buttons themselves, but lets the catcher survive reboot (see the boot script docs). |
| 0.4 | **Termux:Widget is NOT installed yet** — you install it in Step 1. | It is the add-on that draws the home-screen icons. |
| 0.5 | Root present (Magisk) and **Termux granted root** in Magisk. | The buttons run `su -c` to touch a file in the app-owned `/data/local/tmp`. |
| 0.6 | The catcher is already deployed: `catch.js` staged in `/data/local/tmp/re.zyg.fri/`, gadget in **script** mode, run-state currently OFF. | The marker button only flips run-state; it assumes the engine is present. If `catch.js` isn't staged, the button "works" but nothing catches. |

> Device facts this doc is written for: rooted **Pixel 9 Pro, Android 16, Pixel Launcher**. The
> Pixel Launcher fully supports **pinned 1×1 shortcuts** (the app-icon look). This is *not* a
> MIUI/Xiaomi-style launcher that only allows resizable widgets, so the icon route in Step 5 works.

---

## 1. Install Termux:Widget from F-Droid (package `com.termux.widget`)

You have F-Droid installed. Use it (do **not** use the Play Store build — signature mismatch).

**1.1** Open **F-Droid** → tap the search (magnifier) → type **`Termux:Widget`**.

**1.2** Open the result whose package id is **`com.termux.widget`** (publisher: Fredrik Fornwall /
Termux). Confirm it is the **F-Droid** build, not "GitHub version".

**1.3** Tap **Install**. Current version is 0.15.0 (Sep 2025); requires Android 7+. Wait for it to
finish.

> Direct-link alternative (still F-Droid-signed, if search is slow to index):
> open `https://f-droid.org/en/packages/com.termux.widget/` in a browser → **Download APK** →
> install. This is the same APK F-Droid serves; do not substitute an APKMirror/Play build.

**1.4 — IMPORTANT: launch Termux:Widget once.** Find **Termux:Widget** in the app drawer and open
it a single time. It has essentially no UI, but the first launch registers the app with the system
so its widget/shortcut shows up in the launcher's picker. Skipping this is the #1 reason "the widget
doesn't appear."

**1.5 — verify the install from Termux** (optional sanity check):

```sh
pm list packages | grep com.termux.widget
# expect:  package:com.termux.widget
```

---

## 2. Grant Termux:Widget (and Termux) what it needs

Termux:Widget itself needs almost nothing, but two grants make the buttons reliable:

**2.1 — Battery: don't restrict.** Settings → Apps → **Termux:Widget** → Battery → **Unrestricted**.
Do the same for **Termux** and **Termux:API**. (Per the user's standing rule, this is a deliberate,
named change — only do it at deploy time, not silently.) Without this, Android can freeze a
background task button mid-run.

**2.2 — Draw over other apps (only needed for the terminal-style `status` button).** The two flip
buttons in Step 4 run as **background tasks** and are *not* affected by Android 10+'s
background-activity-start restriction. But the `pogo-catch-status` button opens a *terminal session*
to show output, and on Android 10+ a background launch of a terminal can stall until you tap the
Termux notification — unless Termux has **Draw Over Apps**:
Settings → Apps → **Termux** → (Advanced →) **Draw over other apps** → allow. Grant it so `status`
opens cleanly. (The ON/OFF buttons don't need this.)

**2.3 — Root grant** (prereq 0.5, restated): the first time any button runs, Magisk will prompt to
grant Termux superuser. Approve and choose **Remember**. If you want to pre-approve: open Termux,
run `su -c id` once, approve the Magisk prompt.

---

## 3. Create the `~/.shortcuts` layout (in Termux)

Termux:Widget reads scripts from `~/.shortcuts` (= `/data/data/com.termux/files/home/.shortcuts`).
There are **two** sub-locations, and the difference matters:

- `~/.shortcuts/<name>` (top level) → runs in a **foreground terminal session** (a Termux window
  flashes open). Good for `status`, where you *want* to see scrolling output.
- `~/.shortcuts/tasks/<name>` → runs **silently in the background** (no terminal, just a transient
  Termux notification). This is what makes the ON/OFF buttons feel like instant app icons.

So: **flip buttons go in `tasks/`, the status button stays top-level.**

Run this block in Termux **once** to create the layout with the exact permissions Termux:Widget
requires (parent dirs must be readable + executable, or you get *"No regular file found at path"*):

```sh
# directories
mkdir -p ~/.shortcuts/tasks ~/.shortcuts/icons

# Termux:Widget will not show scripts unless ~/.shortcuts is readable+executable.
# 0700 on the dir is the recommended value and is sufficient (owner rwx).
chmod 700 ~/.shortcuts ~/.shortcuts/tasks
# icons dir: 0700 dir, 0600 files (recommended by the Termux:Widget docs)
chmod -R a-x,u=rwX,go-rwx ~/.shortcuts/icons
```

> Constraints Termux:Widget enforces (so you don't trip them): the script's **canonical** path must
> resolve under `~/.shortcuts` (no symlinks pointing outside), the file must be a **regular file**
> (no broken symlinks), and the file + its parent dir must be **executable**. Files inside other
> hidden (dot-prefixed) sub-dirs are ignored.

---

## 4. Install the button scripts

The repo already ships the four marker-file shortcuts under
`pogo_extract/system/ondevice_toggle/shortcuts/`:
`pogo-catch-toggle`, `pogo-catch-on`, `pogo-catch-off`, `pogo-catch-status`. The one-shot
installer (`install_ondevice_catcher.FULL.sh`) copies them into `~/.shortcuts/` for you. **If the
installer already ran, skip to 4.5** (just move the two flip buttons into `tasks/`). The steps below
let you also create them by hand with no PC.

Every script:
- begins with the **full-path shebang** `#!/data/data/com.termux/files/usr/bin/sh` (required —
  Termux:Widget does not honor a bare `#!/bin/sh`),
- uses **one-shot foreground `su -c`** (never `su -c '… &'` — Magisk's background-fork can silently
  no-op the command),
- `chmod 666`s the marker after creating it so the **PoGo app-uid** can `stat` a root-created file,
- emits a `termux-toast` for tap feedback.

### 4.1 `~/.shortcuts/tasks/pogo-catch-toggle` — THE home button (silent, flips ON↔OFF)

```sh
cat > ~/.shortcuts/tasks/pogo-catch-toggle <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# pogo-catch-toggle — home-screen ON/OFF button for the on-device auto-catcher.
# Flips the marker file catch.js polls. ON = file exists, OFF = file gone.
# No gadget reload, no Frida re-attach: catch.js sees the change within ~1s.
MARK=/data/local/tmp/re.zyg.fri/catch.on
if su -c "[ -f $MARK ]"; then
  su -c "rm -f $MARK"
  STATE="OFF"
else
  su -c "touch $MARK && chmod 666 $MARK"
  STATE="ON"
fi
echo "PoGo auto-catch: $STATE"
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo auto-catch: $STATE"
EOF
```

### 4.2 `~/.shortcuts/tasks/pogo-catch-on` — force ON (silent)

```sh
cat > ~/.shortcuts/tasks/pogo-catch-on <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# pogo-catch-on — force the auto-catcher ON (creates the marker catch.js polls).
MARK=/data/local/tmp/re.zyg.fri/catch.on
su -c "touch $MARK && chmod 666 $MARK"
echo "PoGo auto-catch: ON"
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo auto-catch: ON"
EOF
```

### 4.3 `~/.shortcuts/tasks/pogo-catch-off` — force OFF (silent, stays idle; does NOT hand control to desktop)

```sh
cat > ~/.shortcuts/tasks/pogo-catch-off <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# pogo-catch-off — force the auto-catcher OFF (removes the marker). PoGo stays up;
# the LateUpdate pump just early-returns. (This is idle, NOT desktop handoff.)
MARK=/data/local/tmp/re.zyg.fri/catch.on
su -c "rm -f $MARK"
echo "PoGo auto-catch: OFF"
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo auto-catch: OFF"
EOF
```

### 4.4 `~/.shortcuts/pogo-catch-status` — readout (top-level: opens a terminal to show the log)

```sh
cat > ~/.shortcuts/pogo-catch-status <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# pogo-catch-status — report ON/OFF + tail the catcher log, entirely on-device (no PC).
MARK=/data/local/tmp/re.zyg.fri/catch.on
LOG=/data/local/tmp/re.zyg.fri/catch.log
HB=/data/local/tmp/re.zyg.fri/catch.hb
if su -c "[ -f $MARK ]"; then echo "PoGo auto-catch: ON"; else echo "PoGo auto-catch: OFF"; fi
# heartbeat age (catch.js writes epoch|run|opened|caught ~1/s while the pump is alive)
if su -c "[ -f $HB ]"; then
  HBLINE=$(su -c "cat $HB" 2>/dev/null)
  HBTS=$(echo "$HBLINE" | cut -d'|' -f1)
  NOW=$(date +%s)
  [ -n "$HBTS" ] && echo "heartbeat: ${HBLINE}  (age $((NOW-HBTS))s)"
else
  echo "heartbeat: (none yet)"
fi
echo "---- last 25 log lines ----"
su -c "[ -f $LOG ] && tail -n 25 $LOG || echo '(no log yet — launch PoGo at least once)'"
EOF
```

### 4.5 (Desktop-handoff mode buttons — optional but recommended)

These flip the **gadget mode** (not the marker) by calling the already-staged
`/data/local/tmp/re.zyg.fri/pogo-catch.sh`. Use them only when you want the **desktop** catcher to
take over (panic / give the PC control back), or to re-arm autonomy afterward. They restart PoGo, so
keep them as background tasks too.

```sh
# pogo-catch-desktop — hand control to the desktop catcher (gadget -> LISTEN :27047 + relaunch)
cat > ~/.shortcuts/tasks/pogo-catch-desktop <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# Switch the gadget to LISTEN mode so the PC (catch_loop_fast.py) can attach on 127.0.0.1:27047.
# This relaunches PoGo and runs ZERO in-process catch logic afterwards.
su -c '/data/local/tmp/re.zyg.fri/pogo-catch.sh off'
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo: DESKTOP mode (listen :27047)"
EOF

# pogo-catch-autonomous — re-arm phone-solo catching (gadget -> SCRIPT mode + relaunch)
cat > ~/.shortcuts/tasks/pogo-catch-autonomous <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# Switch the gadget back to SCRIPT mode so catch.js auto-runs and the phone catches on its own.
# After this, use the pogo-catch-toggle marker button for instant ON/OFF.
su -c '/data/local/tmp/re.zyg.fri/pogo-catch.sh on'
command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "PoGo: AUTONOMOUS mode (script)"
EOF
```

### 4.6 Make them all executable, then list what Termux:Widget will see

```sh
chmod 700 ~/.shortcuts/tasks/* ~/.shortcuts/pogo-catch-status
ls -la ~/.shortcuts ~/.shortcuts/tasks
```

> If you used the FULL installer (which drops the four scripts in **top-level** `~/.shortcuts/`),
> move the three flip scripts into `tasks/` so they run silently:
> ```sh
> mv ~/.shortcuts/pogo-catch-toggle ~/.shortcuts/pogo-catch-on ~/.shortcuts/pogo-catch-off ~/.shortcuts/tasks/ 2>/dev/null
> chmod 700 ~/.shortcuts/tasks/*
> ```
> Leave `pogo-catch-status` at top level so it opens a terminal to show the log.

---

## 5. Pin the buttons to the home screen so they look like app icons

There are **two** ways the launcher can surface a Termux:Widget script. The task wants **app-icon-style
buttons**, so use method A (pinned 1×1 shortcuts). Method B (the resizable widget panel) is the
fallback / multi-button option.

### Method A — pinned 1×1 shortcut (the app-icon look) — RECOMMENDED

On Android 8+ with the Pixel Launcher, Termux:Widget can place an individual **1×1 pinned shortcut**
that sits on the home screen exactly like an app icon and launches one script on tap. Do this once
per button you want:

1. Long-press an empty area of the home screen → **Widgets**.
2. Scroll to **Termux:Widget**. You'll see two entries:
   - a resizable **"Termux shortcut"** *widget* (method B), and
   - a 1×1 **shortcut** entry.
   Pick the **1×1 shortcut** entry (drag it out, or tap-and-place).
3. The launcher immediately asks **which script** to bind. Choose **`pogo-catch-toggle`**.
4. An icon now lives on the home screen. **One tap toggles catching ON/OFF** with a toast. Done.
5. Repeat for any others you want as their own icon (e.g. `pogo-catch-status`,
   `pogo-catch-desktop`).

> Note: depending on the launcher, a pinned shortcut may carry a tiny "Termux:Widget" app badge in
> one corner. On the Pixel Launcher this is minimal. The custom icon in Step 6 overrides the main
> glyph regardless.

### Method B — resizable widget panel (one tile lists several scripts)

If you'd rather have a single small panel showing several buttons (toggle / on / off / status):

1. Long-press home → **Widgets** → **Termux:Widget** → drag the **"Termux shortcut"** (resizable)
   widget onto the home screen; size it (2×2 is enough for a few rows).
2. The widget lists the scripts in `~/.shortcuts` **and** `~/.shortcuts/tasks`. Tap any row to run it.
3. If the list is empty or stale after you add/rename scripts, open the **Termux:Widget** app and tap
   **REFRESH** (refresh widgets), or tap the refresh glyph on the widget itself.

> Either method runs the **same** scripts; pick A for clean single-purpose icons, B for a compact
> multi-button tile. You can use both.

---

## 6. (Optional) Give the buttons real icons so they look like app icons

Termux:Widget will use a custom PNG for a shortcut if a file with the **same base name as the script**
exists in `~/.shortcuts/icons/`. So `pogo-catch-toggle` → `~/.shortcuts/icons/pogo-catch-toggle.png`.

```sh
mkdir -p ~/.shortcuts/icons
# put your PNGs in (any way you like — Android share-sheet a PNG to Termux, or:)
#   cp /sdcard/Download/pokeball_on.png  ~/.shortcuts/icons/pogo-catch-toggle.png
#   cp /sdcard/Download/pokeball_stat.png ~/.shortcuts/icons/pogo-catch-status.png
# recommended perms (0700 dir, 0600 files):
chmod -R a-x,u=rwX,go-rwx ~/.shortcuts/icons
```

Requirements: the icon must be a **regular file** whose canonical path is under `~/.shortcuts/icons`
(or `~/.termux`). A square PNG (e.g. 192×192) looks best. After adding/replacing icons, **re-pin** the
shortcut (Method A) or hit **REFRESH** in the Termux:Widget app — the launcher caches the old glyph.

> No PNG on hand? The button still works with the default Termux:Widget icon; the icon is cosmetic.
> A single Poké Ball PNG for `pogo-catch-toggle` is enough to get the "app icon" feel.

---

## 7. Verify the buttons end-to-end (do this at deploy, on the map)

Assumes the catcher is deployed and the gadget is in **script** mode (autonomous). Get PoGo onto the
live map with spawns nearby, then:

1. **Tap the `pogo-catch-toggle` icon.** Expect a toast **"PoGo auto-catch: ON"**.
2. Confirm the marker exists: `su -c 'ls -l /data/local/tmp/re.zyg.fri/catch.on'`.
3. Watch the catcher react within ~1 s:
   ```sh
   su -c 'logcat -s frida-catch'
   ```
   Expect `>>> TOGGLE ON — catching`, then ~every 10 s a stats line
   (`fired=… caught=… esc=… flee=… miss=… q=… vis=… inr=… P/G/U …`). Balls should start dropping;
   only in-range (≤80 m) spawns open; legendaries skipped; ~35 opens/min. (These are the exact
   semantics ported from `catch_loop_fast.py`.)
4. **Tap the icon again.** Toast **"PoGo auto-catch: OFF"**; throwing stops within ~1 s; PoGo stays
   running (hooks stay installed → instant re-ON next tap).
5. **Tap `pogo-catch-status`** (or run it): shows ON/OFF, heartbeat age, and the last 25 log lines —
   your no-PC dashboard.
6. (If you installed the mode buttons) **Tap `pogo-catch-desktop`** → PoGo relaunches into listen
   mode; from the PC you can re-attach `catch_loop_fast.py` on `127.0.0.1:27047`. **Tap
   `pogo-catch-autonomous`** to return to phone-solo.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Widget/shortcut **not in the launcher's picker** | Termux:Widget never launched once; or installed from a different store than base Termux | Open the **Termux:Widget** app once (Step 1.4). Confirm both came from **F-Droid** (`pm list packages \| grep com.termux`). |
| **"No regular file found at path"** when tapping | `~/.shortcuts` (or `tasks/`) not readable/executable, or script not executable, or a symlink leaving `~/.shortcuts` | `chmod 700 ~/.shortcuts ~/.shortcuts/tasks; chmod 700 ~/.shortcuts/tasks/*`; ensure no symlinks point outside `~/.shortcuts`. |
| Tapping the button **flashes a terminal** | Script is in **top-level** `~/.shortcuts/` instead of `~/.shortcuts/tasks/` | Move it: `mv ~/.shortcuts/pogo-catch-toggle ~/.shortcuts/tasks/` then re-pin/refresh. |
| `status` button **hangs / never opens** | Android 10+ blocks background terminal-session start | Grant Termux **Draw over other apps** (Step 2.2), or tap the Termux notification to release it. |
| Toast says **ON** but **nothing catches** | `catch.js` not staged, gadget not in **script** mode, or PoGo not on the map | Confirm `logcat -s frida-catch` shows the engine (`READY …`); if silent, the engine/gadget side isn't up — see the catcher/gadget docs (script-mode + 16.x-gadget gate), not this file. |
| Toast says **ON** but `logcat` shows the marker isn't seen | PoGo app-uid can't `stat` the root-created marker | The scripts already `chmod 666` it; verify `su -c 'ls -l /data/local/tmp/re.zyg.fri/catch.on'` shows `-rw-rw-rw-`. |
| Button does **nothing**, no toast | Magisk root not granted to Termux; or `su -c '… &'` background-fork | Approve the Magisk superuser prompt (Step 2.3); confirm the scripts use **foreground** `su -c` (they do). |
| Widget list **stale** after editing scripts/icons | Launcher cached the shortcut list | Open **Termux:Widget** → **REFRESH**; or remove and re-pin the shortcut. |
| Button **freezes after a while in background** | Battery optimization froze Termux/Termux:Widget | Set Termux, Termux:API, **Termux:Widget** battery to **Unrestricted** (Step 2.1). |

---

## 9. Quick reference — paths and names (must match the rest of the system)

| Thing | Value |
|---|---|
| Termux:Widget package | `com.termux.widget` (install from **F-Droid**) |
| Termux home | `/data/data/com.termux/files/home` (`~`) |
| Silent (no-terminal) scripts dir | `~/.shortcuts/tasks/` |
| Terminal (visible-output) scripts dir | `~/.shortcuts/` (top level) |
| Custom icons dir | `~/.shortcuts/icons/` (PNG named after the script) |
| Shebang every script needs | `#!/data/data/com.termux/files/usr/bin/sh` |
| Run-state marker (the seam) | `/data/local/tmp/re.zyg.fri/catch.on` — **present = ON** |
| Catcher log (file) | `/data/local/tmp/re.zyg.fri/catch.log` |
| Catcher log (live) | `logcat -s frida-catch` |
| Heartbeat | `/data/local/tmp/re.zyg.fri/catch.hb` (`epoch\|run\|opened\|caught`) |
| Mode-swap driver (desktop handoff) | `/data/local/tmp/re.zyg.fri/pogo-catch.sh {on\|off\|toggle\|status}` |
| PoGo package | `com.nianticlabs.pokemongo` |

**The button = `touch`/`rm` of one file as root. The engine does the rest.**

---

### Sources

- [Termux:Widget — GitHub README](https://github.com/termux/termux-widget/blob/master/README.md) (the `~/.shortcuts` vs `~/.shortcuts/tasks` split, permission/canonical-path rules, custom-icon dir, REFRESH, Android 10+ Draw-Over-Apps note)
- [Termux:Widget on F-Droid (`com.termux.widget`)](https://f-droid.org/en/packages/com.termux.widget/) (package id, version, F-Droid install)
- [termux/termux-widget repo](https://github.com/termux/termux-widget) (pinned 1×1 shortcut via ShortcutManager on Android 8+, dynamic shortcuts)
