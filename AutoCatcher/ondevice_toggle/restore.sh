#!/system/bin/sh
# ============================================================================
#  restore.sh  —  THE GUARANTEED SAFETY NET for the on-device PoGo catcher.
#
#  ONE JOB: unconditionally put the ZygiskFrida gadget back into LISTEN mode
#  (127.0.0.1:27047) and relaunch PoGo, so DESKTOP CONTROL — the existing
#  Python catcher (catch_loop_fast.py) and pogo_il2cpp.py, which attach over
#  that port — works again. This is the panic button you run when autonomous
#  (script-mode) catch.js misbehaves, wedges, or you simply want the PC back.
#
#  WHY THIS IS A SEPARATE SCRIPT (not just `pogo-catch.sh off`):
#    pogo-catch.sh is the everyday toggle: idempotent, derives state from the
#    live config, and REFUSES to run if catch.js / the gadget dir look wrong.
#    A safety net must do the opposite — it must NEVER refuse and NEVER depend
#    on any staged file. restore.sh therefore:
#      * forces LISTEN mode regardless of the current/derived state (no no-op),
#      * carries the exact listen JSON INLINE so it works even if
#        config.listen.so was never staged (or got clobbered),
#      * backs up the live config first (so even the restore is reversible),
#      * writes atomically (temp -> mv) and VERIFIES the bytes landed before
#        claiming success,
#      * also removes the catch.on run-marker (belt-and-suspenders: in-process
#        catching is OFF even if a script config somehow survives),
#      * self-elevates to root, and uses only POSIX/toolbox basics (cp, mv,
#        cat, grep, am, monkey) so it runs from a minimal recovery shell too.
#
#  RUN (from Termux, root present on this device):
#      su -c '/data/local/tmp/re.zyg.fri/restore.sh'
#  or, if you are already in a root shell:
#      /data/local/tmp/re.zyg.fri/restore.sh
#  (it re-execs itself under su if not already uid 0, so either form works.)
#
#  Flags (optional):
#      --no-restart   swap the config but do NOT force-stop / relaunch PoGo
#                     (use if you want to relaunch PoGo by hand afterwards).
#      -h | --help    print usage.
#
#  After it runs, on the DESKTOP:
#      python system/scripts/game_write/catch_loop_fast.py   # attaches on :27047
#  (or any pogo_il2cpp.py-based tool) — the link comes back as it was before.
#
#  Exit codes: 0 = gadget is now in listen mode (restore confirmed).
#              1 = could not write/verify the listen config (see stderr+log);
#                  fall through to the NUCLEAR fallbacks printed on failure.
#  This NEVER touches PoGo's save data; state is server-authoritative, so a
#  mid-throw relaunch just drops that one throw and re-syncs on next launch.
# ============================================================================

set -u

DIR=/data/local/tmp/re.zyg.fri
CFG="$DIR/libgadget.config.so"            # the live config the gadget reads at injection time
LISTEN_CFG="$DIR/config.listen.so"        # canonical listen config, IF it was staged (preferred source)
LOG="$DIR/restore.log"
MARKER="$DIR/catch.on"                     # in-process run-state marker (presence == catching ON)
PKG=com.nianticlabs.pokemongo

# The EXACT listen config this device shipped with (byte-for-byte the current
# /data/local/tmp/re.zyg.fri/libgadget.config.so before autonomy was enabled):
# desktop frida client adds the remote device 127.0.0.1:27047 and attaches.
LISTEN_JSON='{"interaction":{"type":"listen","address":"127.0.0.1","port":27047,"on_load":"resume"}}'

RESTART=1
for a in "$@"; do
  case "$a" in
    --no-restart) RESTART=0 ;;
    -h|--help)
      sed -n '2,46p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "restore.sh: unknown arg: $a (try --help)" >&2 ;;
  esac
done

# ---- self-elevate to root if needed ---------------------------------------
# Works whether invoked as `su -c '.../restore.sh'`, from a root shell, or as a
# plain user shell that has su available. Avoids "permission denied" surprises.
if [ "$(id -u 2>/dev/null)" != "0" ]; then
  if command -v su >/dev/null 2>&1; then
    exec su -c "sh '$0' $*"
  else
    echo "restore.sh: not root and no su found — re-run as: su -c '$0'" >&2
    exit 1
  fi
fi

ts() { date +%Y-%m-%dT%H:%M:%S 2>/dev/null || echo now; }
logln() { echo "$(ts) $*" >> "$LOG" 2>/dev/null; }
say() { echo "restore: $*"; }

# Printed only when the config write itself failed (rare). Gives the manual
# nuclear ladder so the user is never left stranded by a failing safety net.
print_nuclear() {
  echo "" >&2
  echo "restore: the config swap FAILED. Manual recovery ladder (run as root):" >&2
  echo "  1) write the listen config by hand:" >&2
  echo "       su -c 'printf %s \"$LISTEN_JSON\" > $CFG' && su -c 'am force-stop $PKG'" >&2
  echo "  2) NUCLEAR — run PoGo with NO frida gadget at all (rename the .so aside):" >&2
  echo "       su -c 'mv $DIR/libgadget.so $DIR/libgadget.so.bak' && su -c 'am force-stop $PKG'" >&2
  echo "     (restore later with: su -c 'mv $DIR/libgadget.so.bak $DIR/libgadget.so')" >&2
  echo "  3) restore the whole dir from a STEP-0 backup if you made one:" >&2
  echo "       su -c 'ls -d ${DIR}.bak.*' ; su -c 'rm -rf $DIR && cp -a ${DIR}.bak.<TS> $DIR'" >&2
  echo "  4) last resort: disable the ZygiskFrida Magisk module in the Magisk app + reboot." >&2
  echo "" >&2
}

logln "==== restore.sh invoked (restart=$RESTART) ===="

# ---- 0. ensure the gadget dir exists (create if a recovery shell wiped it) --
# We do NOT bail if catch.js or staged configs are missing — that is the whole
# point of the safety net. We only need to be able to write the live config.
if [ ! -d "$DIR" ]; then
  mkdir -p "$DIR" 2>/dev/null
  if [ ! -d "$DIR" ]; then
    echo "restore: FATAL: gadget dir $DIR is missing and cannot be created." >&2
    echo "restore: the ZygiskFrida module may be disabled — re-enable it in Magisk + reboot." >&2
    logln "FATAL: gadget dir missing, mkdir failed"
    exit 1
  fi
  say "NOTE: gadget dir was missing; created $DIR (gadget .so may also be gone)."
  logln "created missing gadget dir"
fi

# ---- 1. back up the current live config (so even the restore is reversible) -
if [ -f "$CFG" ]; then
  BK="$CFG.prerestore.$(date +%s 2>/dev/null || echo bak)"
  cp "$CFG" "$BK" 2>/dev/null && { say "backed up current config -> $BK"; logln "backup -> $BK"; }
  PREV="$(cat "$CFG" 2>/dev/null)"
  logln "prev live config: $PREV"
else
  say "NOTE: no live config present ($CFG) — writing a fresh listen config."
  logln "no prior live config"
fi

# ---- 2. choose the SOURCE listen config -----------------------------------
# Prefer a staged config.listen.so, but ONLY if it really is a listen config
# (guards against a staged file that got corrupted or swapped). Otherwise fall
# back to the embedded JSON, which is guaranteed correct for this device.
SRC=""
if [ -f "$LISTEN_CFG" ] && grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$LISTEN_CFG" 2>/dev/null; then
  SRC="$LISTEN_CFG"
  say "using staged listen config: $LISTEN_CFG"
  logln "source = staged $LISTEN_CFG"
else
  say "using built-in listen config (no valid staged config.listen.so)"
  logln "source = embedded JSON"
fi

# ---- 3. atomic write of the listen config over the live config -------------
# temp file in the SAME dir, then mv -> the gadget can never read a half file.
TMP="$CFG.tmp.$$"
if [ -n "$SRC" ]; then
  cp "$SRC" "$TMP" 2>/dev/null
else
  printf '%s\n' "$LISTEN_JSON" > "$TMP" 2>/dev/null
fi
if [ ! -s "$TMP" ]; then
  # last-ditch: write the embedded JSON directly to the live file (non-atomic
  # but better than leaving a script-mode config in place).
  rm -f "$TMP" 2>/dev/null
  printf '%s\n' "$LISTEN_JSON" > "$CFG" 2>/dev/null
  if ! grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$CFG" 2>/dev/null; then
    echo "restore: FATAL: could not write listen config to $CFG." >&2
    logln "FATAL: temp+direct write both failed"
    print_nuclear
    exit 1
  fi
  say "WARNING: atomic path failed; wrote listen config directly (non-atomic)."
  logln "fallback: direct non-atomic write succeeded"
else
  mv -f "$TMP" "$CFG" 2>/dev/null || { cp "$TMP" "$CFG" 2>/dev/null; rm -f "$TMP" 2>/dev/null; }
fi
chmod 644 "$CFG" 2>/dev/null || true

# ---- 4. VERIFY the bytes landed (a safety net that lies is worthless) -------
if grep -q '"type"[[:space:]]*:[[:space:]]*"listen"' "$CFG" 2>/dev/null \
   && grep -q '27047' "$CFG" 2>/dev/null; then
  say "OK — live config is now LISTEN mode:"
  echo "      $(cat "$CFG" 2>/dev/null)"
  logln "VERIFIED listen config written"
else
  echo "restore: FATAL: wrote config but it does NOT read back as listen!" >&2
  echo "         live config now: $(cat "$CFG" 2>/dev/null)" >&2
  logln "FATAL: post-write verify failed; live=$(cat "$CFG" 2>/dev/null)"
  print_nuclear
  exit 1
fi

# ---- 5. force in-process catching OFF too (belt-and-suspenders) -------------
# If for any reason a script-mode config is still loaded in a *running* process,
# removing the run-marker makes catch.js's RUN gate go false on its next pump.
if [ -f "$MARKER" ]; then
  rm -f "$MARKER" 2>/dev/null && { say "removed run-marker (catch.on) — in-process catching OFF"; logln "removed catch.on"; }
fi

# ---- 6. relaunch PoGo so the gadget re-reads the (now listen) config --------
# The gadget reads its config ONLY at process start, so a restart is mandatory
# for the mode change to take effect. (--no-restart skips this.)
if [ "$RESTART" -eq 1 ]; then
  say "restarting PoGo so the gadget loads listen mode..."
  am force-stop "$PKG" 2>/dev/null
  # brief settle so the process is fully gone before relaunch
  sleep 2
  # monkey launches the LAUNCHER activity without needing its exact name;
  # fall back to `am start` if monkey is unavailable in this shell.
  if command -v monkey >/dev/null 2>&1; then
    monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  else
    am start -n "$PKG/com.unity3d.player.UnityPlayerActivity" >/dev/null 2>&1 \
      || am start -c android.intent.category.LAUNCHER -a android.intent.action.MAIN -p "$PKG" >/dev/null 2>&1
  fi
  logln "force-stop + relaunch issued"
  PID="$(pidof "$PKG" 2>/dev/null)"
  say "PoGo relaunched (pid: ${PID:-<still starting>})."
else
  say "--no-restart: config swapped but PoGo NOT restarted."
  say "  -> the change takes effect on the NEXT PoGo launch. Restart it yourself with:"
  say "     su -c 'am force-stop $PKG' ; su -c 'monkey -p $PKG -c android.intent.category.LAUNCHER 1'"
fi

echo
say "DONE. Gadget is in LISTEN mode on 127.0.0.1:27047."
say "Desktop can now attach again:"
say "  python system/scripts/game_write/catch_loop_fast.py"
say "  (pogo_il2cpp.py adds remote device 127.0.0.1:27047 and attaches to PoGo.)"
logln "==== restore complete ===="
exit 0
