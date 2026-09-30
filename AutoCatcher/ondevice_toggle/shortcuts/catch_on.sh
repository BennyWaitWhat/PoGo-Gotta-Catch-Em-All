#!/data/data/com.termux/files/usr/bin/sh
# ============================================================================
#  catch_on.sh  —  Termux:Widget home-screen button: turn the on-device
#                  PoGo auto-catcher ON via the CONFIG-SWAP mechanism.
#
#  WHAT IT DOES
#    Puts the in-process Frida gadget into SCRIPT mode (it auto-loads
#    /data/local/tmp/re.zyg.fri/catch.js on every PoGo launch) and then
#    force-stops + relaunches PoGo so the new mode is read at injection time.
#    Once PoGo is back up, catch.js self-starts, self-finds its singletons
#    (MapPlaceDirectoryService / MapAvatar / ItemBag / IapService via the
#    ported Unity-liveness object walk) and catches on its own. NO desktop,
#    NO Python host, NO adb — the phone catches solo.
#
#  WHY A RELAUNCH
#    The gadget only reads libgadget.config.so once, at process start. Flipping
#    the file alone does nothing to a running PoGo; you must restart the app.
#    (The everyday pause/resume button is the separate marker-file toggle
#    `catch.on`, which needs no restart. THIS button is the heavier
#    "arm autonomy / take the phone back from the desktop catcher" switch.)
#
#  IDEMPOTENT
#    If the gadget is already in SCRIPT mode, this is a no-op: it does NOT
#    restart PoGo again (state is DERIVED from the live config's content, so it
#    cannot drift). Safe to double-tap.
#
#  HOW IT RUNS
#    Termux:Widget runs this file directly. All the privileged work happens in
#    ONE foreground `su -c '<here-doc>'` invocation (no `su -c '... &'` — a
#    backgrounded su under Magisk can silently no-op). Prefers the canonical
#    /data/local/tmp/re.zyg.fri/pogo-catch.sh if it is staged (single source of
#    truth + its own lockfile); otherwise it performs the swap inline using the
#    staged config.script.so, falling back to embedded JSON as a last resort.
#
#  Place in ~/.shortcuts/ (perms 700 on the dir, this file executable) and add
#  a 1x1 Termux:Widget pointing at it.  Mirror: catch_off.sh.
# ============================================================================

DIR=/data/local/tmp/re.zyg.fri
PKG=com.nianticlabs.pokemongo

# Run everything privileged in a single foreground root shell. The here-doc is
# quoted ('ROOT') so NOTHING is expanded by Termux's shell — $DIR etc. below are
# literal text evaluated by the root /system/bin/sh, and the embedded JSON keeps
# its quotes intact.
OUT=$(su -c 'sh -s' <<'ROOT'
set -u
DIR=/data/local/tmp/re.zyg.fri
CFG="$DIR/libgadget.config.so"          # the live config the gadget reads at launch
SCRIPT_CFG="$DIR/config.script.so"      # canonical SCRIPT-mode config (staged)
HELPER="$DIR/pogo-catch.sh"             # canonical toggle engine (preferred if present)
PKG=com.nianticlabs.pokemongo
# Exact SCRIPT-mode JSON (matches config.script.so; on_change:reload lets you
# hot-edit catch.js without a relaunch; qjs is the gadget's JS runtime).
SCRIPT_JSON='{"interaction":{"type":"script","path":"/data/local/tmp/re.zyg.fri/catch.js","on_change":"reload"},"runtime":"qjs"}'

[ -d "$DIR" ] || { echo "ERROR: gadget dir missing: $DIR"; exit 1; }
[ -f "$DIR/catch.js" ] || { echo "ERROR: catch.js missing ($DIR/catch.js) — stage it before turning ON"; exit 1; }

# ---- Preferred path: delegate to the canonical engine if it is staged -------
if [ -x "$HELPER" ] || [ -f "$HELPER" ]; then
  sh "$HELPER" on
  exit $?
fi

# ---- Standalone fallback: do the atomic swap ourselves ----------------------
# Derive current mode from the LIVE config content (source of truth).
state=UNKNOWN
if [ -f "$CFG" ]; then
  if grep -q '"type"[[:space:]]*:[[:space:]]*"script"' "$CFG" 2>/dev/null; then state=ON
  elif grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$CFG" 2>/dev/null; then state=OFF
  fi
fi
if [ "$state" = ON ]; then
  echo "PoGo auto-catch already ON (gadget already in SCRIPT mode) — no restart"
  exit 0
fi

# Best-effort Frida-17 warning (script mode is reported parsed-but-not-executed
# on 17.x; if catch.log stays empty after launch, swap libgadget.so to a 16.x).
v=$(strings "$DIR/libgadget.so" 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | sort -uV | tail -n1)
case "$v" in
  1[7-9].*|2[0-9].*) echo "WARNING: gadget looks like Frida $v — SCRIPT mode may be parsed-but-not-executed; if catch.log stays empty, downgrade libgadget.so to a 16.x arm64 gadget (see DEPLOY_commands.md)";;
esac

# Choose the source config: the staged canonical one if present and valid,
# otherwise materialise it from the embedded JSON.
src="$SCRIPT_CFG"
if [ ! -f "$src" ] || ! grep -q '"type"[[:space:]]*:[[:space:]]*"script"' "$src" 2>/dev/null; then
  printf '%s\n' "$SCRIPT_JSON" > "$src" || { echo "ERROR: cannot write $src"; exit 1; }
fi

# Atomic swap: stage a temp in the SAME dir then mv over the live config, so the
# gadget can never read a half-written file.
tmp="$CFG.tmp.$$"
cp "$src" "$tmp" || { echo "ERROR: cannot stage temp config"; exit 1; }
mv -f "$tmp" "$CFG" || { rm -f "$tmp"; echo "ERROR: atomic mv failed"; exit 1; }
chmod 644 "$CFG" 2>/dev/null

# Force-stop + relaunch so the gadget re-reads the config in SCRIPT mode.
am force-stop "$PKG" 2>/dev/null
sleep 2
monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
echo "PoGo auto-catch: ON  (gadget -> SCRIPT mode, catch.js; PoGo relaunched)"
ROOT
)

rc=$?
echo "$OUT"
# Best-effort home-screen feedback from a tap (Termux:API).
if command -v termux-toast >/dev/null 2>&1; then
  termux-toast -g middle "$(printf '%s\n' "$OUT" | head -n1)"
fi
exit $rc
