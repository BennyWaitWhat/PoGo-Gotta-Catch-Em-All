#!/data/data/com.termux/files/usr/bin/sh
# ============================================================================
#  catch_off.sh  —  Termux:Widget home-screen button: turn the on-device
#                   PoGo auto-catcher OFF via the CONFIG-SWAP mechanism.
#
#  WHAT IT DOES
#    Puts the in-process Frida gadget back into LISTEN mode (opens
#    127.0.0.1:27047 and runs ZERO catch logic in PoGo's process) and then
#    force-stops + relaunches PoGo so the new mode loads at injection time.
#    This is the ORIGINAL, default state of the device: it hands control back
#    to the DESKTOP catcher (catch_loop_fast.py attaches over :27047) and fully
#    disables in-process catching.
#
#    LISTEN is the safe "panic / give me the phone back" state. (For an everyday
#    PAUSE that keeps autonomy armed and resumes instantly, use the marker-file
#    OFF button that removes `catch.on` — no relaunch. THIS button is the
#    heavier switch that severs in-process catching entirely.)
#
#  WHY A RELAUNCH
#    The gadget only reads libgadget.config.so once, at process start, so the
#    mode change requires restarting PoGo.
#
#  IDEMPOTENT
#    If the gadget is already in LISTEN mode, this is a no-op: it does NOT
#    restart PoGo again (state is DERIVED from the live config content, so it
#    cannot drift). Safe to double-tap.
#
#  HOW IT RUNS
#    One foreground `su -c '<here-doc>'` (no backgrounded su). Prefers the
#    canonical /data/local/tmp/re.zyg.fri/pogo-catch.sh if staged; otherwise
#    swaps inline. The LISTEN config it writes is, in order of preference:
#      1. the staged canonical config.listen.so,
#      2. a snapshot of the current live config if it is already LISTEN,
#      3. the embedded JSON (127.0.0.1:27047, on_load resume) — byte-for-byte
#         the device's known-good original listen config.
#
#  Place in ~/.shortcuts/ (dir 700, file executable) + a Termux:Widget pointing
#  at it.  Mirror: catch_on.sh.
# ============================================================================

DIR=/data/local/tmp/re.zyg.fri
PKG=com.nianticlabs.pokemongo

OUT=$(su -c 'sh -s' <<'ROOT'
set -u
DIR=/data/local/tmp/re.zyg.fri
CFG="$DIR/libgadget.config.so"          # the live config the gadget reads at launch
LISTEN_CFG="$DIR/config.listen.so"      # canonical LISTEN-mode config (= original)
HELPER="$DIR/pogo-catch.sh"             # canonical toggle engine (preferred if present)
PKG=com.nianticlabs.pokemongo
# Exact LISTEN-mode JSON (byte-for-byte the device's current/original config:
# loopback only, port 27047, resume on load).
LISTEN_JSON='{"interaction":{"type":"listen","address":"127.0.0.1","port":27047,"on_load":"resume"}}'

[ -d "$DIR" ] || { echo "ERROR: gadget dir missing: $DIR"; exit 1; }

# ---- Preferred path: delegate to the canonical engine if it is staged -------
if [ -x "$HELPER" ] || [ -f "$HELPER" ]; then
  sh "$HELPER" off
  exit $?
fi

# ---- Standalone fallback: do the atomic swap ourselves ----------------------
state=UNKNOWN
if [ -f "$CFG" ]; then
  if grep -q '"type"[[:space:]]*:[[:space:]]*"script"' "$CFG" 2>/dev/null; then state=ON
  elif grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$CFG" 2>/dev/null; then state=OFF
  fi
fi
if [ "$state" = OFF ]; then
  echo "PoGo auto-catch already OFF (gadget already in LISTEN mode :27047) — no restart"
  exit 0
fi

# Choose the source config: staged canonical listen config, else a snapshot of
# the live config if it is already listen, else the embedded JSON.
src="$LISTEN_CFG"
if [ ! -f "$src" ] || ! grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$src" 2>/dev/null; then
  if [ -f "$CFG" ] && grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$CFG" 2>/dev/null; then
    cp "$CFG" "$src" 2>/dev/null || src="$CFG"
  else
    printf '%s\n' "$LISTEN_JSON" > "$src" || { echo "ERROR: cannot write $src"; exit 1; }
  fi
fi

# Atomic swap.
tmp="$CFG.tmp.$$"
cp "$src" "$tmp" || { echo "ERROR: cannot stage temp config"; exit 1; }
mv -f "$tmp" "$CFG" || { rm -f "$tmp"; echo "ERROR: atomic mv failed"; exit 1; }
chmod 644 "$CFG" 2>/dev/null

# Force-stop + relaunch so the gadget re-reads the config in LISTEN mode.
am force-stop "$PKG" 2>/dev/null
sleep 2
monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
echo "PoGo auto-catch: OFF (gadget -> LISTEN mode :27047; PoGo relaunched; desktop can attach)"
ROOT
)

rc=$?
echo "$OUT"
if command -v termux-toast >/dev/null 2>&1; then
  termux-toast -g middle "$(printf '%s\n' "$OUT" | head -n1)"
fi
exit $rc
