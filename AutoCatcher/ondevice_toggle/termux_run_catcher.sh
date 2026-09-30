#!/data/data/com.termux/files/usr/bin/sh
# ============================================================================
#  termux_run_catcher.sh  —  on-phone LAUNCHER for the PRIMARY autonomous path
#                            (Termux-attach to the gadget's local listen socket).
#
#  WHAT THIS IS
#    The one launcher you run in Termux to make the phone catch on its own
#    WITHOUT the desktop and WITHOUT QuickJS gadget *script* mode. It:
#      1. ensures the in-process Frida gadget is in LISTEN mode (its default),
#         relaunching PoGo once if a prior test left it in SCRIPT mode;
#      2. takes a wake-lock so Termux + the catcher survive doze/screen-off;
#      3. runs the PROVEN desktop catcher on-device via termux_catch.py, which
#         attaches to 127.0.0.1:27047 and reuses catch_loop_fast.py +
#         pogo_il2cpp.py byte-for-byte (the off-thread GC-liveness architecture
#         that has NEVER crashed PoGo).
#
#    "ON"  for this path = this process running.   "OFF" = stop this process.
#    There is no marker file and no config swap here — it only ATTACHES. The
#    gadget stays in listen mode the whole time, so the desktop can still attach
#    on 27047 afterwards, and nothing persists across a Ctrl-C / kill.
#
#  WHY THE PRIMARY PATH IS ATTACH, NOT SCRIPT MODE
#    The crashing in-process catch.js had to stop the Unity GC world from inside
#    PoGo (from the render thread / before il2cpp_init) to self-find singletons —
#    that produced the multi-thread pc==fault storm. The desktop catcher never
#    does that: its GC liveness walk runs on a Frida-managed host thread in a
#    transient script, decoupled from the frame pump. termux_catch.py runs that
#    exact code on the phone over the listen socket, so the proven off-thread
#    design is preserved unchanged. (Fallback: the hardened single-thread
#    catch.hardened.js, only if you want a zero-Termux home button.)
#
#  USAGE (Termux, root present)
#    Interactive (recommended for the first run — watch the log live):
#        sh ~/pogo_extract/system/ondevice_toggle/termux_run_catcher.sh
#    Skip the relaunch (gadget already known-listening, PoGo already foreground):
#        sh termux_run_catcher.sh --no-relaunch
#    Override where the pogo_extract tree lives on-device:
#        POGO_ROOT=/sdcard/pogo_extract sh termux_run_catcher.sh
#    Stop:  Ctrl-C  (or, from a widget/other shell, the OFF button — see
#           TERMUX_SETUP.md; it `pkill -f termux_catch.py`).
#
#  PREREQUISITES  (one-time; full walkthrough in TERMUX_SETUP.md)
#    pkg install python
#    pip install frida          # must resolve a 17.x client to match the gadget
#    # pogo_extract tree seeded on-device preserving layout:
#    #   <ROOT>/pogo_il2cpp.py
#    #   <ROOT>/system/scripts/game_write/catch_loop_fast.py
#    #   <ROOT>/system/ondevice_toggle/termux_catch.py   (this script's sibling)
#
#  EXIT CODES
#    0  catcher exited cleanly (Ctrl-C / all-balls-floor stop inside the catcher)
#    1  prerequisite missing (python/frida/tree) or could not reach the gadget
#    2  another instance is already running (refuses to double-launch)
# ============================================================================
set -u

# --- Resolve our own location so paths work no matter the cwd ----------------
# Termux:Widget and `sh <path>` both run us with $0 = the file path.
SELF=$0
case "$SELF" in
  */*) HERE=$(CDPATH= cd -- "$(dirname -- "$SELF")" && pwd) ;;
  *)   HERE=$(pwd) ;;
esac
# ROOT = .../pogo_extract  (two dirs up: ondevice_toggle -> system -> pogo_extract)
ROOT_DEFAULT=$(CDPATH= cd -- "$HERE/../.." && pwd)
ROOT=${POGO_ROOT:-$ROOT_DEFAULT}

PY=${PY:-python}
CATCH_PY="$HERE/termux_catch.py"
GADGET_DIR=/data/local/tmp/re.zyg.fri
PKG=com.nianticlabs.pokemongo
RELAUNCH=1

for arg in "$@"; do
  case "$arg" in
    --no-relaunch) RELAUNCH=0 ;;
    -h|--help)
      sed -n '2,55p' "$SELF"; exit 0 ;;
    *) echo "unknown arg: $arg (try --help)"; exit 1 ;;
  esac
done

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }
toast() { command -v termux-toast >/dev/null 2>&1 && termux-toast -g middle "$*"; }

# --- Single-instance guard ---------------------------------------------------
# Refuse to stack catchers on the same 27047 socket (two clients fighting over
# the gadget = flaky attach + double throws). pgrep over the python module name.
if pgrep -f 'termux_catch\.py' >/dev/null 2>&1; then
  log "ERROR: a Termux catcher (termux_catch.py) is already running."
  log "       Stop it first:  pkill -f termux_catch.py    (this is the OFF button)"
  toast "catcher already running"
  exit 2
fi

# --- Prerequisite checks (fail fast, with the exact fix) ---------------------
if ! command -v "$PY" >/dev/null 2>&1; then
  log "ERROR: '$PY' not found. Run:  pkg install python"; exit 1
fi
if ! "$PY" -c 'import frida' >/dev/null 2>&1; then
  log "ERROR: the frida python module is not importable in Termux."
  log "       Fix:  pip install frida   (see TERMUX_SETUP.md 'frida in Termux')."
  log "       It MUST be a 17.x client to match the device gadget (fork 17.x)."
  exit 1
fi
if [ ! -f "$CATCH_PY" ]; then
  log "ERROR: termux_catch.py not found next to this script ($CATCH_PY)."
  log "       Seed the pogo_extract tree preserving its layout (see TERMUX_SETUP.md)."
  exit 1
fi
if [ ! -f "$ROOT/pogo_il2cpp.py" ] || \
   [ ! -f "$ROOT/system/scripts/game_write/catch_loop_fast.py" ]; then
  log "ERROR: proven sources missing under ROOT=$ROOT"
  log "         need: $ROOT/pogo_il2cpp.py"
  log "         need: $ROOT/system/scripts/game_write/catch_loop_fast.py"
  log "       Set POGO_ROOT to the pogo_extract dir if it lives elsewhere."
  exit 1
fi

# --- Report the frida client version (must share the gadget's MAJOR) ---------
FV=$("$PY" -c 'import frida; print(frida.__version__)' 2>/dev/null)
log "frida client : ${FV:-unknown}  (gadget is a 17.x fork; majors must match)"
case "${FV:-}" in
  17.*) : ;;
  '' )  log "WARNING: could not read frida.__version__; attach may still work." ;;
  *)    log "WARNING: frida client is ${FV}, gadget is 17.x — a major mismatch will refuse to attach." ;;
esac

# --- Ensure the gadget is in LISTEN mode (idempotent), via one root shell -----
# Derive state from the LIVE config content (source of truth), only relaunch if
# we actually had to switch it. If --no-relaunch, we only WARN on a mismatch.
ensure_listen() {
  su -c 'sh -s' <<ROOT
set -u
DIR=$GADGET_DIR
PKG=$PKG
CFG="\$DIR/libgadget.config.so"
LISTEN_CFG="\$DIR/config.listen.so"
[ -d "\$DIR" ] || { echo "MODE=ERROR gadget dir missing: \$DIR"; exit 1; }

mode=UNKNOWN
if [ -f "\$CFG" ]; then
  if grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "\$CFG" 2>/dev/null; then mode=LISTEN
  elif grep -q '"type"[[:space:]]*:[[:space:]]*"script"' "\$CFG" 2>/dev/null; then mode=SCRIPT
  fi
fi

if [ "\$mode" = LISTEN ]; then
  echo "MODE=LISTEN already"
  exit 0
fi

if [ "$RELAUNCH" = 0 ]; then
  echo "MODE=\$mode (not LISTEN) and --no-relaunch given — NOT switching"
  exit 3
fi

# Need a listen config to swap in. Prefer the staged canonical file; else write
# the exact JSON (matches config.listen.so). on_load:resume so PoGo isn't frozen.
src="\$LISTEN_CFG"
if [ ! -f "\$src" ] || ! grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "\$src" 2>/dev/null; then
  printf '%s\n' '{"interaction":{"type":"listen","address":"127.0.0.1","port":27047,"on_load":"resume"}}' > "\$src" || { echo "MODE=ERROR cannot write \$src"; exit 1; }
fi
# Atomic swap (temp in same dir, then mv) so the gadget never reads a half file.
tmp="\$CFG.tmp.\$\$"
cp "\$src" "\$tmp" || { echo "MODE=ERROR cannot stage temp"; exit 1; }
mv -f "\$tmp" "\$CFG" || { rm -f "\$tmp"; echo "MODE=ERROR atomic mv failed"; exit 1; }
chmod 644 "\$CFG" 2>/dev/null
am force-stop "\$PKG" 2>/dev/null
sleep 2
monkey -p "\$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
echo "MODE=SWITCHED_TO_LISTEN (PoGo relaunched — FOREGROUND it on the live map now)"
ROOT
}

MODE_OUT=$(ensure_listen)
rc=$?
log "gadget mode  : $MODE_OUT"
if [ "$rc" -eq 1 ]; then
  log "ERROR: could not put the gadget into listen mode (is root granted to Termux?)."
  exit 1
fi
if [ "$rc" -eq 3 ]; then
  log "WARNING: gadget is NOT in listen mode and you passed --no-relaunch."
  log "         The attach below will fail until you switch it. Continuing anyway."
fi
case "$MODE_OUT" in
  *SWITCHED_TO_LISTEN*)
    log ">>> PoGo was relaunched. FOREGROUND it on the live map (avatar + spawns"
    log "    visible) before it tries to attach. Giving it a few seconds..."
    # termux_catch.py / catch_loop_fast.py already retry the attach ~6x with
    # 3-5s backoff, so a brief head-start is enough; no long blind sleep.
    i=0; while [ "$i" -lt 6 ]; do i=$((i+1)); sleep 1; done
    ;;
esac

# --- Wake-lock so screen-off / doze doesn't suspend the catcher ---------------
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
  log "wake-lock    : acquired (termux-wake-lock)"
  trap 'termux-wake-unlock 2>/dev/null; log "wake-lock released"; exit 0' INT TERM
else
  log "wake-lock    : termux-wake-lock not found (install Termux:API) — catcher"
  log "               may be suspended when the screen is off. Not fatal."
  trap 'exit 0' INT TERM
fi

# --- Run the proven catcher (foreground; its stdout is the live status line) --
log "launching    : $CATCH_PY  (ROOT=$ROOT)"
log "stop with    : Ctrl-C here, or  pkill -f termux_catch.py"
log "------------------------------------------------------------------------"
POGO_ROOT="$ROOT" exec "$PY" "$CATCH_PY"
