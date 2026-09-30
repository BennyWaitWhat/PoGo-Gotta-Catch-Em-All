#!/system/bin/sh
# ============================================================================
#  pogo-catch.sh  —  CONFIG-SWAP toggle for the on-device PoGo auto-catcher.
#
#  ANGLE: [config-swap-toggle]. This is the ROBUST root-shell mechanism the
#  brief asked for: it does NOT rely on the script polling a marker file. It
#  physically swaps the Frida gadget's mode by replacing libgadget.config.so,
#  then force-stops + relaunches PoGo so the new mode loads on next process
#  start (the gadget only reads its config at injection time).
#
#    ON  = gadget in SCRIPT mode -> auto-loads catch.js -> phone catches solo.
#    OFF = gadget in LISTEN mode -> opens 127.0.0.1:27047 -> desktop can attach
#          (this is the ORIGINAL state; "off" hands control back to the PC and
#           runs zero catch logic in PoGo's process).
#
#  Run as ROOT. From Termux:  su -c '/data/local/tmp/re.zyg.fri/pogo-catch.sh toggle'
#  (the shortcuts/ wrappers call exactly this).
#
#  PROPERTIES:
#   - Idempotent: `on` when already ON is a no-op (no needless PoGo restart);
#     same for `off`. Re-running never corrupts state.
#   - Atomic config swap: writes to a temp file in the SAME dir then mv(1) over
#     libgadget.config.so, so the gadget can never read a half-written config.
#   - Source-of-truth state: ON/OFF is DERIVED from the live config's content
#     ("type":"script" vs "type":"listen"), never from a side flag that can
#     drift. `status` reads the real file.
#   - Self-guarding: refuses to run if the gadget dir / catch.js is missing, and
#     warns (not fatal) if the gadget looks like Frida 17.x (script mode is
#     reported broken there — see DEPLOY notes).
#   - Single-flight: a lockfile serialises concurrent toggles (e.g. a double-tap
#     on the home-screen button) so two swaps can't interleave a restart.
# ============================================================================

set -u

DIR=/data/local/tmp/re.zyg.fri
CFG="$DIR/libgadget.config.so"            # the live gadget config the gadget reads
SCRIPT_CFG="$DIR/config.script.so"        # canonical SCRIPT-mode config (staged once)
LISTEN_CFG="$DIR/config.listen.so"        # canonical LISTEN-mode config (= original)
CATCH_JS="$DIR/catch.js"                  # the self-contained catcher
LOCK="$DIR/.toggle.lock"
LOG="$DIR/toggle.log"
PKG=com.nianticlabs.pokemongo

# Embedded fallbacks: if the canonical config files were never staged, we still
# know the exact JSON to write (verified against the Frida gadget docs + the
# device's current listen config: port 27047, on_load resume). on_change:reload
# lets you hot-edit catch.js without a restart.
SCRIPT_JSON='{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"reload"},"runtime":"qjs"}'
LISTEN_JSON='{"interaction":{"type":"listen","address":"127.0.0.1","port":27047,"on_load":"resume"}}'

ts() { date +%Y-%m-%dT%H:%M:%S 2>/dev/null || echo now; }
logln() { echo "$(ts) $*" >> "$LOG" 2>/dev/null; }
die() { echo "pogo-catch: ERROR: $*" >&2; logln "ERROR: $*"; release_lock; exit 1; }

# ---- single-flight lock (mkdir is atomic on every fs) ----------------------
acquire_lock() {
  i=0
  while ! mkdir "$LOCK" 2>/dev/null; do
    i=$((i+1)); [ "$i" -ge 50 ] && { echo "pogo-catch: another toggle is in progress (lock stuck: $LOCK)"; exit 1; }
    sleep 0.1
  done
}
release_lock() { rmdir "$LOCK" 2>/dev/null || true; }

# ---- preflight: dir + script + (canonical config or embedded fallback) -----
preflight() {
  [ -d "$DIR" ] || die "gadget dir missing: $DIR"
  [ -f "$CATCH_JS" ] || die "catch.js missing: $CATCH_JS (stage it before toggling ON)"
  # Make sure the canonical mode-configs exist; create from embedded JSON if not.
  if [ ! -f "$SCRIPT_CFG" ]; then printf '%s\n' "$SCRIPT_JSON" > "$SCRIPT_CFG" || die "cannot write $SCRIPT_CFG"; fi
  if [ ! -f "$LISTEN_CFG" ]; then
    # Prefer snapshotting the CURRENT live config as the listen baseline (it is
    # the real original); fall back to the embedded JSON only if there's nothing.
    if [ -f "$CFG" ] && grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$CFG" 2>/dev/null; then
      cp "$CFG" "$LISTEN_CFG" || die "cannot snapshot listen config"
    else
      printf '%s\n' "$LISTEN_JSON" > "$LISTEN_CFG" || die "cannot write $LISTEN_CFG"
    fi
  fi
}

# ---- current state, DERIVED from the live config content -------------------
# echoes: ON | OFF | UNKNOWN
current_state() {
  [ -f "$CFG" ] || { echo UNKNOWN; return; }
  if grep -q '"type"[[:space:]]*:[[:space:]]*"script"' "$CFG" 2>/dev/null; then echo ON
  elif grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$CFG" 2>/dev/null; then echo OFF
  else echo UNKNOWN; fi
}

# ---- gadget version sniff (best-effort, non-fatal) -------------------------
warn_if_frida17() {
  v=$(strings "$DIR/libgadget.so" 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | sort -uV | tail -n1)
  case "$v" in
    1[7-9].*|2[0-9].*) echo "pogo-catch: WARNING gadget looks like Frida $v — autonomous SCRIPT mode is reported broken on Android for 17+ (script is parsed but not executed). If catch.log stays empty after launch, downgrade libgadget.so to a 16.x (e.g. 16.7.19) arm64 gadget. See DEPLOY_commands.md.";;
  esac
}

# ---- atomic write of a canonical config over the live config ---------------
swap_config() {  # $1 = source canonical config path
  src="$1"
  [ -f "$src" ] || die "missing canonical config: $src"
  tmp="$CFG.tmp.$$"
  cp "$src" "$tmp" || die "cannot stage temp config"
  # mv within the same filesystem is atomic -> gadget never sees a partial file.
  mv -f "$tmp" "$CFG" || { rm -f "$tmp"; die "atomic mv failed"; }
  chmod 644 "$CFG" 2>/dev/null || true
}

# ---- force-stop + relaunch PoGo so the new gadget mode loads ----------------
restart_pogo() {
  am force-stop "$PKG" 2>/dev/null
  # tiny settle so the process is fully gone before relaunch
  sleep 2
  # monkey launches the LAUNCHER activity without needing its exact name.
  monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
}

# ---- high-level ops --------------------------------------------------------
go_on() {
  preflight
  warn_if_frida17
  if [ "$(current_state)" = ON ]; then echo "PoGo auto-catch already ON (script mode)"; logln "on: already ON (noop)"; return 0; fi
  swap_config "$SCRIPT_CFG"
  restart_pogo
  echo "PoGo auto-catch: ON  (gadget -> SCRIPT mode, catch.js; PoGo relaunched)"
  logln "ON: swapped to script + relaunched"
}

go_off() {
  preflight
  if [ "$(current_state)" = OFF ]; then echo "PoGo auto-catch already OFF (listen mode)"; logln "off: already OFF (noop)"; return 0; fi
  swap_config "$LISTEN_CFG"
  restart_pogo
  echo "PoGo auto-catch: OFF (gadget -> LISTEN mode :27047; PoGo relaunched; desktop can attach)"
  logln "OFF: swapped to listen + relaunched"
}

go_toggle() {
  case "$(current_state)" in
    ON)  go_off ;;
    OFF) go_on ;;
    *)   echo "pogo-catch: live config is neither script nor listen (UNKNOWN) — defaulting to OFF/listen for safety"; logln "toggle: UNKNOWN -> off"; go_off ;;
  esac
}

go_status() {
  s=$(current_state)
  echo "state: $s"
  echo "config: $CFG"
  if [ -f "$CFG" ]; then echo "  $(cat "$CFG" 2>/dev/null)"; else echo "  (missing)"; fi
  pid=$(pidof "$PKG" 2>/dev/null)
  echo "pogo pid: ${pid:-<not running>}"
  if [ -f "$DIR/catch.log" ]; then
    echo "---- catch.log (last 15) ----"
    tail -n 15 "$DIR/catch.log" 2>/dev/null
  else
    echo "(no catch.log yet — launch PoGo in ON mode at least once)"
  fi
}

usage() {
  cat <<EOF
pogo-catch.sh — config-swap toggle for the on-device auto-catcher (run as root)
  on      switch gadget to SCRIPT mode (catch.js) + relaunch PoGo  -> phone catches
  off     switch gadget to LISTEN mode (:27047)     + relaunch PoGo -> desktop control
  toggle  flip ON<->OFF based on the live config (home-screen button target)
  status  print derived state + live config + pid + tail of catch.log
EOF
}

# ---- dispatch (lock only around mutating ops) ------------------------------
cmd="${1:-toggle}"
case "$cmd" in
  on)     acquire_lock; go_on;     rc=$?; release_lock; exit $rc ;;
  off)    acquire_lock; go_off;    rc=$?; release_lock; exit $rc ;;
  toggle) acquire_lock; go_toggle; rc=$?; release_lock; exit $rc ;;
  status) go_status ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
